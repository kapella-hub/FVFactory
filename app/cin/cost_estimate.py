"""Cost estimates and the per-video cap (spec 2026-10-03 §7). Pure apart from reading settings.

Two checkpoints: pre_tts (after the script, before the first paid call) and pre_clips (after
plan_segments, before motion generation). Unit rules are the ones main._log_costs logs with, so a
run whose clips all succeed logs exactly pre_clips.spent + pre_clips.clips. Retries and fallback
models are not estimated (fal bills successful generations; a fallback clip is logged at its price).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Optional

from app.cin.shot_plan import HANDLE
from app.cin.tiers import QUALITY_TIERS, TIER_MODELS
from app.config import settings
from app.cost_tracker import unit_clip_cost, unit_costs
from app.motion_gen import CLASSIC_CLIP_SECONDS, CLIP_MODELS, ClipModel, snap_duration
from app.script_quality import DURATION_SECONDS, SCENE_RANGE, WORDS_PER_SECOND, word_budget

__all__ = ["CostCapError", "CostEstimate", "unit_clip_cost", "llm_cost_item", "tts_cost_item", "tts_units",
           "llm_calls", "stage_costs", "motion_estimate", "estimate_pre_tts", "estimate_pre_clips",
           "exceeds_cap", "tier_estimates", "clip_model_options"]


class CostCapError(RuntimeError):
    """The estimate exceeds max_cost_per_video; the run stops before the next paid stage (spec §4.5)."""


@dataclass
class CostEstimate:
    stage: str                 # "pre_tts" | "pre_clips"
    clips: float               # motion
    images: float
    tts: float
    llm: float
    spent: float               # already paid at the checkpoint (pre_clips only; 0 at pre_tts)
    total: float               # what the finished video is expected to cost
    model: str                 # clip model key
    clip_seconds: float        # summed requested seconds (0 when motion is off)

    def to_json(self) -> dict:
        return asdict(self)


def llm_cost_item(provider: Optional[str] = None) -> str:
    """Cost-log item of one script LLM call by `provider` (None = settings.llm_provider): OpenAI is
    billed, the claude and codex CLIs run on subscription logins and log $0 (spec §4.7)."""
    provider = settings.llm_provider if provider is None else provider
    if provider == "openai":
        return "openai_gpt4o"
    return "codex_cli" if provider == "codex" else "claude_cli"


def tts_cost_item() -> Optional[str]:
    """Cost-log item of the narration, by the key the TTS layer uses first; None = nothing logged."""
    if settings.elevenlabs_api_key:
        return "elevenlabs_tts"
    if settings.openai_api_key:
        return "openai_tts"
    return None


def tts_units(chars: int) -> int:
    """Billed 1k-character units, as the cost log counts them (at least one)."""
    return max(1, int(chars) // 1000)


def llm_calls(revision: Optional[str]) -> int:
    """Script LLM calls: the draft, plus the length revision when one was attempted.
    "not_applicable" = a verbatim story: one visuals call, never a revision."""
    return 1 if revision in (None, "", "not_needed", "not_applicable") else 2


def stage_costs(*, narration_chars: int, image_count: int, mock_images: bool, llm_calls: int,
                rates: Optional[dict] = None, llm_provider: Optional[str] = None) -> dict:
    """USD of TTS, images and the script LLM calls, with the rules main._log_costs logs.
    llm_provider = the provider that answered the script (None = settings.llm_provider)."""
    rates = unit_costs() if rates is None else rates
    tts_item = tts_cost_item()
    return {
        "tts": round(tts_units(narration_chars) * rates[tts_item], 4) if tts_item else 0.0,
        "images": 0.0 if mock_images else round(image_count * rates["flux_image"], 4),
        "llm": round(llm_calls * rates[llm_cost_item(llm_provider)], 4),
    }


def _scene_lengths(needed: float, durations) -> list:
    snapped = snap_duration(needed, durations)
    if snapped is not None:
        return [snapped]
    longest = max(durations)
    return [longest] * math.ceil(needed / longest)       # chained segments of an over-long scene


def motion_estimate(*, words: int, scene_count: int, model: ClipModel,
                    pricing: Optional[dict] = None) -> tuple:
    """(USD, requested seconds) of motion for a script: narration = words / WORDS_PER_SECOND spread
    evenly over the scenes, each scene + HANDLE snapped up to the model's lengths."""
    if scene_count <= 0 or words <= 0:
        return 0.0, 0.0
    lengths = _scene_lengths(words / WORDS_PER_SECOND / scene_count + HANDLE, model.durations) * scene_count
    usd = sum(unit_clip_cost(model.key, length, pricing) for length in lengths)
    return round(usd, 4), round(sum(lengths), 2)


def estimate_pre_tts(*, words: int, scene_count: int, model: ClipModel, motion_on: bool, costs: dict,
                     pricing: Optional[dict] = None) -> CostEstimate:
    """Checkpoint 1: after the script stage, before TTS (the first paid call)."""
    clips, seconds = motion_estimate(words=words, scene_count=scene_count, model=model,
                                     pricing=pricing) if motion_on else (0.0, 0.0)
    total = round(clips + costs["images"] + costs["tts"] + costs["llm"], 4)
    return CostEstimate("pre_tts", clips, costs["images"], costs["tts"], costs["llm"], 0.0, total,
                        model.key, seconds)


def estimate_classic(*, clip_count: int, model: ClipModel, motion_on: bool, costs: dict,
                     pricing: Optional[dict] = None) -> CostEstimate:
    """Checkpoint 1 for classic / persona runs: one clip per image at CLASSIC_CLIP_SECONDS (the length
    _log_costs logs them at). The classic editor has no second checkpoint."""
    if motion_on and clip_count:
        length = snap_duration(CLASSIC_CLIP_SECONDS, model.durations) or CLASSIC_CLIP_SECONDS
        clips = round(clip_count * unit_clip_cost(model.key, length, pricing), 4)
        seconds = round(clip_count * length, 2)
    else:
        clips, seconds = 0.0, 0.0
    total = round(clips + costs["images"] + costs["tts"] + costs["llm"], 4)
    return CostEstimate("pre_tts", clips, costs["images"], costs["tts"], costs["llm"], 0.0, total,
                        model.key, seconds)


def estimate_pre_clips(requests_: list, *, model: ClipModel, motion_on: bool, costs: dict,
                       pricing: Optional[dict] = None) -> CostEstimate:
    """Checkpoint 2: after plan_segments, before generate_segment_clips. Exact clip lengths;
    spent = what TTS, images and the LLM cost (stage_costs of the real narration and images)."""
    if motion_on:
        clips = round(sum(unit_clip_cost(model.key, r.requested_len, pricing) for r in requests_), 4)
        seconds = round(sum(r.requested_len for r in requests_), 2)
    else:
        clips, seconds = 0.0, 0.0
    spent = round(costs["images"] + costs["tts"] + costs["llm"], 4)
    return CostEstimate("pre_clips", clips, costs["images"], costs["tts"], costs["llm"], spent,
                        round(spent + clips, 4), model.key, seconds)


def exceeds_cap(total: float, max_cost: float) -> bool:
    """max_cost 0 = no cap; an estimate equal to the cap is within it (both compared at 4 decimals)."""
    return max_cost > 0 and round(total, 4) > round(max_cost, 4)


def tier_estimates(custom_model: Optional[str] = None, pricing: Optional[dict] = None) -> dict:
    """{tier: {"model": key, "short": usd, "medium": usd, "long": usd} | None}: the pre_tts motion
    estimate of a typical video per duration preset (word-budget target, middle of the scene range).
    None for a custom tier whose model is unknown or not a fal model."""
    out = {}
    for tier in QUALITY_TIERS:
        model = CLIP_MODELS.get(TIER_MODELS.get(tier, custom_model or ""))
        if model is None or model.endpoint is None:
            out[tier] = None
            continue
        row = {"model": model.key}
        try:
            for preset in DURATION_SECONDS:
                lo, hi = SCENE_RANGE[preset]
                row[preset] = motion_estimate(words=word_budget(preset).target, scene_count=(lo + hi) // 2,
                                              model=model, pricing=pricing)[0]
        except ValueError:                 # no pricing entry for this model (an overridden clip_pricing)
            row = None
        out[tier] = row
    return out


def _price_text(price: Optional[dict]) -> str:
    if not price:
        return "no price"
    if "per_second" in price:
        return f"${float(price['per_second']):g}/s"
    return f"${float(price.get('per_clip', 0.0)):.2f}/clip"


def clip_model_options(pricing: Optional[dict] = None) -> list:
    """[{key, label, price_text}] of the fal models (the Settings page's fal_video_model choices)."""
    pricing = settings.clip_pricing if pricing is None else pricing
    return [{"key": key, "label": model.label, "price_text": _price_text(pricing.get(key))}
            for key, model in CLIP_MODELS.items() if model.endpoint]
