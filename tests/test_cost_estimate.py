"""Cost estimates and the cap rule (spec 2026-10-03 §7). Hand-computed totals at list prices.
Compare models by .key: tests/test_motion_gen.py reloads app.motion_gen."""
import pytest

from app.cin.cost_estimate import (CostCapError, clip_model_options, estimate_pre_clips, estimate_pre_tts,
                                   exceeds_cap, llm_calls, llm_cost_item, motion_estimate, stage_costs,
                                   tier_estimates, tts_cost_item, tts_units, unit_clip_cost)
from app.cin.shot_plan import SegmentRequest
from app.config import Settings, settings
from app.motion_gen import CLIP_MODELS

PRICES = Settings(_env_file=None).clip_pricing
NO_COSTS = {"tts": 0.0, "images": 0.0, "llm": 0.0}


@pytest.fixture(autouse=True)
def _list_prices(monkeypatch):
    """A developer .env may override prices or keys; these tests pin the list prices."""
    monkeypatch.setattr(settings, "clip_pricing", PRICES)
    monkeypatch.setattr(settings, "cost_flux_image", 0.03)
    monkeypatch.setattr(settings, "cost_elevenlabs_per_1k_chars", 0.01)
    monkeypatch.setattr(settings, "cost_openai_tts_per_1k_chars", 0.015)
    monkeypatch.setattr(settings, "cost_openai_gpt4o", 0.005)
    monkeypatch.setattr(settings, "cost_claude_cli", 0.0)
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")


def test_cost_cap_error_is_a_runtime_error():
    assert issubclass(CostCapError, RuntimeError)


def test_unit_clip_cost_matches_the_tracker_rule():
    assert unit_clip_cost("kling", 5.0) == 0.42
    assert unit_clip_cost("kling-pro", 5.0) == 0.56
    assert unit_clip_cost("hailuo", 6.0) == 0.5
    assert unit_clip_cost("h3-turbo", 7.0) == 0.28
    with pytest.raises(ValueError, match="No clip pricing"):
        unit_clip_cost("sora", 5.0)


def test_cost_items_follow_the_provider_and_keys(monkeypatch):
    assert llm_cost_item() == "claude_cli" and tts_cost_item() is None
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "x")
    assert llm_cost_item() == "openai_gpt4o" and tts_cost_item() == "openai_tts"
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    assert tts_cost_item() == "elevenlabs_tts"


@pytest.mark.parametrize("chars, units", [(0, 1), (650, 1), (999, 1), (1000, 1), (2500, 2)])
def test_tts_units_match_the_cost_log(chars, units):
    assert tts_units(chars) == units


@pytest.mark.parametrize("revision, calls", [("not_needed", 1), (None, 1), ("accepted", 2),
                                             ("kept_draft", 2), ("failed", 2)])
def test_llm_calls_count_the_revision(revision, calls):
    assert llm_calls(revision) == calls


def test_stage_costs_openai_and_elevenlabs(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    assert stage_costs(narration_chars=650, image_count=10, mock_images=False, llm_calls=2) == {
        "tts": 0.01, "images": 0.3, "llm": 0.01}
    assert stage_costs(narration_chars=650, image_count=10, mock_images=True, llm_calls=1)["images"] == 0.0


def test_claude_cli_costs_nothing():
    assert stage_costs(narration_chars=650, image_count=0, mock_images=True, llm_calls=2) == NO_COSTS


@pytest.mark.parametrize("key, usd, seconds", [("kling", 4.2, 50.0), ("kling-pro", 5.6, 50.0),
                                               ("hailuo", 5.0, 60.0), ("h3-turbo", 2.0, 50.0)])
def test_medium_script_motion_estimate(key, usd, seconds):
    """117 words / 2.6 = 45 s over 10 scenes: 4.5 + 0.5 handle = 5 s per clip (hailuo: 6 s)."""
    assert motion_estimate(words=117, scene_count=10, model=CLIP_MODELS[key]) == (usd, seconds)


def test_over_long_scene_counts_chained_clips_of_the_longest_length():
    """hailuo (6 s max): 52 words = 20 s in 2 scenes -> 10.5 s each -> 2 clips of 6 s per scene."""
    assert motion_estimate(words=52, scene_count=2, model=CLIP_MODELS["hailuo"]) == (2.0, 24.0)


def test_pre_tts_medium_standard_total(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    costs = stage_costs(narration_chars=650, image_count=10, mock_images=False, llm_calls=1)
    est = estimate_pre_tts(words=117, scene_count=10, model=CLIP_MODELS["kling"], motion_on=True, costs=costs)
    assert est.to_json() == {"stage": "pre_tts", "clips": 4.2, "images": 0.3, "tts": 0.01, "llm": 0.005,
                             "spent": 0.0, "total": 4.515, "model": "kling", "clip_seconds": 50.0}


def test_pre_tts_premium_total():
    est = estimate_pre_tts(words=117, scene_count=10, model=CLIP_MODELS["kling-pro"], motion_on=True,
                           costs={"tts": 0.01, "images": 0.3, "llm": 0.0})
    assert (est.clips, est.total) == (5.6, 5.91)


def test_motion_off_estimates_no_clips():
    est = estimate_pre_tts(words=117, scene_count=10, model=CLIP_MODELS["kling"], motion_on=False,
                           costs=NO_COSTS)
    assert (est.clips, est.clip_seconds, est.total) == (0.0, 0.0, 0.0)


def test_pre_clips_is_exact_and_spent_is_the_paid_stages():
    reqs = [SegmentRequest(0, 0, 0.0, 2.32, 3.0, False), SegmentRequest(1, 0, 2.32, 8.0, 7.0, False)]
    est = estimate_pre_clips(reqs, model=CLIP_MODELS["kling"], motion_on=True,
                             costs={"tts": 0.01, "images": 0.06, "llm": 0.01})
    assert est.to_json() == {"stage": "pre_clips", "clips": 0.84, "images": 0.06, "tts": 0.01, "llm": 0.01,
                             "spent": 0.08, "total": 0.92, "model": "kling", "clip_seconds": 10.0}
    off = estimate_pre_clips(reqs, model=CLIP_MODELS["kling"], motion_on=False, costs=NO_COSTS)
    assert (off.clips, off.clip_seconds) == (0.0, 0.0)


def test_missing_pricing_entry_raises(monkeypatch):
    monkeypatch.setattr(settings, "clip_pricing", {k: v for k, v in PRICES.items() if k != "kling"})
    with pytest.raises(ValueError, match="No clip pricing for model 'kling'"):
        estimate_pre_tts(words=117, scene_count=10, model=CLIP_MODELS["kling"], motion_on=True, costs=NO_COSTS)


@pytest.mark.parametrize("total, cap, over", [(4.5, 0.0, False), (4.5, 4.5, False), (4.5000004, 4.5, False),
                                              (4.5001, 4.5, True), (0.01, 0.0, False), (5.0, 4.99, True)])
def test_cap_rule(total, cap, over):
    assert exceeds_cap(total, cap) is over


def test_tier_estimates_per_duration_preset():
    est = tier_estimates(custom_model="h3-turbo")
    assert est["standard"] == {"model": "kling", "short": 2.94, "medium": 4.2, "long": 6.048}
    assert est["premium"] == {"model": "kling-pro", "short": 3.92, "medium": 5.6, "long": 8.064}
    assert est["custom"]["model"] == "h3-turbo" and est["custom"]["medium"] == 2.0


@pytest.mark.parametrize("custom", [None, "", "sora", "local"])
def test_tier_estimates_unknown_custom_model_is_none(custom):
    assert tier_estimates(custom_model=custom)["custom"] is None


def test_clip_model_options_are_the_fal_models_with_prices():
    opts = clip_model_options()
    assert [o["key"] for o in opts] == ["kling", "kling-pro", "hailuo", "h3-turbo", "h3"]
    by_key = {o["key"]: o for o in opts}
    assert by_key["kling"] == {"key": "kling", "label": "Kling v3 Standard", "price_text": "$0.084/s"}
    assert by_key["hailuo"]["price_text"] == "$0.50/clip"
    assert by_key["h3-turbo"]["price_text"] == "$0.04/s"
