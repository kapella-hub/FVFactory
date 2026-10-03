# Quality Tiers (Selectable Motion Model, Cost Estimate and Cap) — Design Spec

Status: approved by controller self-review (user instruction "review yourself", 2026-10-03)
Sub-project 3 of the "top of the line short-form video" effort. Sub-project 1: shot-based editor
(spec 2026-10-02). Sub-project 2: script upgrades (spec 2026-10-03-script-upgrades).

## 1. Goal

Every shot is AI motion footage (user ruling 2026-10-02: "videos should be motion not stills
transitioning"). Quality tiers therefore differ by **motion model**, never by how many shots move.
The user picks a tier per video (web form, scheduler slot, CLI, Settings default), sees what it will
cost before anything is paid, and can set a per-video spending cap that stops a run before the paid
motion stage instead of overspending or degrading to stills.

## 2. Background (verified 2026-10-03, main @ 90b2710)

| Fact | Where |
|---|---|
| `CLIP_MODELS` maps `hailuo` → `fal-ai/minimax-video/image-to-video` (6 s fixed), `kling` → `fal-ai/kling-video/v1/standard/...`, `kling-pro` → `fal-ai/kling-video/v1.5/pro/...` | `app/motion_gen.py:28-34` |
| Both Kling endpoints are marked **deprecated** ("no longer supported") on fal.ai | fal model pages, checked 2026-10-03 |
| `_generate_fal` always sends `image_url`; when `sends_duration` it sends `duration=str(int(x))` and `aspect_ratio="9:16"` | `app/motion_gen.py:136-145` |
| `plan_segments(alignment, durations)` snaps each segment to the smallest supported length ≥ scene + 0.5 s handle | `app/cin/shot_plan.py:241-` |
| `settings.clip_pricing` (per_clip / per_second) drives `CostTracker.log_clip`; clips are logged at their real requested length | `app/config.py:122-128`, `app/cost_tracker.py:97-110`, `main._log_costs` |
| `report.cost = {"estimated": None, "actual": [...], "total": x}` — the estimate slot exists and is unused | `main.py` `_log_costs` |
| Options plumbing: `app/run_options.py` (`pipeline_kwargs`, `validate_settings_update`), `api_generate` request model, scheduler slots, `GeneratorWorker`, Settings page, CLI flags | sub-project 1 Phase D |
| The script stage costs $0 on the default `llm_provider="claude_cli"`; the first paid call is TTS | `main.run_pipeline` |
| The sub-project 2 length-revision call is not cost-logged (final review M4, deferred here) | `main._log_costs` |

Model facts (fal OpenAPI schemas `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<id>` and
model pages, checked 2026-10-03; list prices, "subject to change"):

| Key (new table) | Endpoint | Price | `duration` arg | Image arg | Audio |
|---|---|---|---|---|---|
| `kling` (Kling v3 Standard) | `fal-ai/kling-video/v3/standard/image-to-video` | $0.084/s audio off | string `"3"`…`"15"` | `start_image_url` | `generate_audio` default **true** → send `false` |
| `kling-pro` (Kling v3 Pro) | `fal-ai/kling-video/v3/pro/image-to-video` | $0.112/s audio off | string `"3"`…`"15"` | `start_image_url` | same |
| `hailuo` (Minimax video-01) | `fal-ai/minimax-video/image-to-video` (live, HTTP 200) | $0.50/clip | none (6 s fixed) | `image_url` | none |
| `h3-turbo` (MiniMax H3 Max Turbo, 768P) | `minimax/h3-max-turbo/image-to-video` | $0.04/s | number (default 5) | `image_url` | always generated, no toggle (unverified) |
| `h3` (MiniMax H3 Max, 768P) | `minimax/h3-max/image-to-video` | $0.08/s | number | `image_url` | same |

Kling v3 infers aspect ratio from the start image (schema: no `aspect_ratio` arg). H3's 9:16
behaviour and its allowed duration range are **unverified** (no aspect arg; range 5–15 from a search
result only).

## 3. Scope

In: the clip-model table and per-model request builder; tier → model resolution; pre-run and
pre-clips cost estimates; the per-video cap; cost-logging the revision call; tier/cap plumbing to
CLI, web form, scheduler, worker, Settings; run report fields; Settings model list.

Out (one line each, deliberate):
- Image model per tier (FLUX.2, Nano Banana 2) — tiers differ by motion model only; a later option.
- TTS model (`eleven_v4`) — already a setting (`elevenlabs_model`); the user flips it when their
  ElevenLabs plan is set up.
- Veo 3.1 — about twice the Premium price, different argument format; nobody asked.
- Relaxing `SCENE_RANGE` for 3–15 s clips — a calibration after the first paid runs.
- Promo prices (H3 −40% until 2026-10-15) — list prices only.
- The `--classic` / persona path keeps using `settings.fal_video_model` (legacy editor; §8).

## 4. Decisions

1. **Tiers.** `QUALITY_TIERS = {"standard": "kling", "premium": "kling-pro"}` plus `"custom"`, which
   means `settings.fal_video_model`. Default `quality_tier = "standard"`. Standard ≈ $3.4–3.8 and
   Premium ≈ $4.5–5.0 of motion per 40 s video — inside the bands the user saw on the tiers page.
2. **Kling keys move to v3.** `kling` / `kling-pro` keep their names (existing `.env`, `data/config.json`
   and old `shot_plan.json` values stay valid) and point at the v3 endpoints. The v1/v1.5 endpoints
   are dead, so nothing that worked stops working. Re-render makes no API calls, so old plans that
   name `kling` are unaffected.
3. **H3 is opt-in, not a tier default.** `h3-turbo` and `h3` are selectable through
   `fal_video_model` with tier `custom`. Making H3 the Standard default (cheaper: ≈ $1.6–1.9 per 40 s)
   needs one paid 480P test clip (≈ $0.13) to confirm 9:16 output — an open item for the user.
4. **Durations as ranges.** Kling: `tuple(float(d) for d in range(3, 16))`; H3: `range(5, 16)`
   (unverified upper bound; a clip request above fal's limit fails and falls back per the existing
   retry/fallback chain). `snap_duration` and `plan_segments` work unchanged. Kling therefore bills
   whole seconds: a 4.2 s scene + 0.5 s handle requests `"5"`.
5. **The cap never degrades.** A run whose estimate exceeds `max_cost_per_video` stops with
   `CostCapError` before the next paid stage. It never swaps in stills, a cheaper model or fewer clips.
   `0` (default) means no cap.
6. **Tier applies only to fal.** With `motion_provider` `replicate` or `local`, or with motion off /
   mock images, the tier is recorded but has no effect; when the tier was set explicitly (not the
   Settings default) the report warns `tier_ignored`.
7. **Revision call is logged** as a second `openai_gpt4o` item when
   `report.script["revision"] != "not_needed"` and the provider is OpenAI (cost-tracker item already
   exists; `claude_cli` stays $0).

## 5. Clip models (`app/motion_gen.py`)

```python
@dataclass(frozen=True)
class ClipModel:
    key: str
    endpoint: Optional[str]                    # fal endpoint; None for non-fal providers
    durations: Optional[Tuple[float, ...]]     # supported lengths; None = any length
    duration_format: str = "none"              # "none" | "int_str" ("5") | "number" (5)
    image_arg: str = "image_url"               # Kling v3: "start_image_url"
    extra_args: Tuple[Tuple[str, object], ...] = ()   # constant arguments, e.g. (("generate_audio", False),)
    label: str = ""                            # human label for the Settings page / API

KLING_V3_LENGTHS = tuple(float(d) for d in range(3, 16))
H3_LENGTHS = tuple(float(d) for d in range(5, 16))

CLIP_MODELS = {
    "kling": ClipModel("kling", "fal-ai/kling-video/v3/standard/image-to-video", KLING_V3_LENGTHS,
                       "int_str", "start_image_url", (("generate_audio", False),), "Kling v3 Standard"),
    "kling-pro": ClipModel("kling-pro", "fal-ai/kling-video/v3/pro/image-to-video", KLING_V3_LENGTHS,
                           "int_str", "start_image_url", (("generate_audio", False),), "Kling v3 Pro"),
    "hailuo": ClipModel("hailuo", "fal-ai/minimax-video/image-to-video", (6.0,), label="Minimax video-01"),
    "h3-turbo": ClipModel("h3-turbo", "minimax/h3-max-turbo/image-to-video", H3_LENGTHS, "number",
                          extra_args=(("resolution", "768P"), ("prompt_expansion_mode", "balanced")),
                          label="MiniMax H3 Max Turbo (unverified 9:16)"),
    "h3": ClipModel("h3", "minimax/h3-max/image-to-video", H3_LENGTHS, "number",
                    extra_args=(("resolution", "768P"), ("prompt_expansion_mode", "balanced")),
                    label="MiniMax H3 Max (unverified 9:16)"),
    "replicate-minimax": ClipModel("replicate-minimax", None, (6.0,), label="Replicate Minimax"),
    "local": ClipModel("local", None, None, label="Local (free)"),
}
```

`build_fal_arguments(model: ClipModel, image_url: str, prompt: str, duration: Optional[float]) -> dict`
(pure, module level) returns `{"prompt": prompt, model.image_arg: image_url, **dict(model.extra_args)}`
plus `duration` when `duration_format != "none"`: the snapped length (`snap_duration(duration or
min(durations), durations) or max(durations)`) as `str(int(L))` for `int_str` or `int(L)` for
`number`. No model sends `aspect_ratio` (Kling v3 and H3 infer it from the 9:16 image; `hailuo` never
took one). `_generate_fal` calls it; `sends_duration` is removed.

`settings.clip_pricing` becomes:
`kling {per_second 0.084}`, `kling-pro {per_second 0.112}`, `hailuo {per_clip 0.50}`,
`h3-turbo {per_second 0.04}`, `h3 {per_second 0.08}`, `replicate-minimax {per_clip 0.50}`,
`local {per_clip 0.0}`. A test asserts every `CLIP_MODELS` key has a pricing entry.

## 6. Tier resolution (`app/cin/tiers.py`, new, pure)

```python
QUALITY_TIERS = ("standard", "premium", "custom")
TIER_MODELS = {"standard": "kling", "premium": "kling-pro"}

def resolve_clip_model(tier: str, provider: str, custom_model: str) -> ClipModel:
    """provider local/replicate → clip_model_for(provider, ...) regardless of tier;
    fal: standard/premium → CLIP_MODELS[TIER_MODELS[tier]]; custom → CLIP_MODELS.get(custom_model),
    unknown custom key → ValueError naming the known keys (no silent hailuo fallback)."""
```

`clip_model_for` keeps its signature for the classic path; its unknown-key fallback to `hailuo` is
replaced by the same `ValueError` only inside `resolve_clip_model` (classic behaviour unchanged).

## 7. Cost estimate (`app/cin/cost_estimate.py`, new, pure)

```python
@dataclass
class CostEstimate:
    stage: str                 # "pre_tts" | "pre_clips"
    clips: float               # motion
    images: float
    tts: float
    llm: float
    spent: float               # already logged for this video at the checkpoint (pre_clips only)
    total: float               # what the finished video is expected to cost
    model: str                 # clip model key
    clip_seconds: float        # summed requested seconds (0 when motion is off)
    def to_json(self) -> dict

def unit_clip_cost(model_key: str, seconds: float, pricing: dict) -> float   # same rule as CostTracker
def estimate_pre_tts(*, narration_chars: int, scene_count: int, image_count: int, words: int,
                     model: ClipModel, motion_on: bool, mock_images: bool, tts_provider: str,
                     llm_cost: float) -> CostEstimate
def estimate_pre_clips(requests_: list, *, model: ClipModel, motion_on: bool,
                       spent: float, ...) -> CostEstimate
```

- **pre_tts** (after the script stage, before TTS — the first paid call). Narration seconds =
  `words / WORDS_PER_SECOND`; per scene `snap_duration(narration_seconds / scene_count + HANDLE,
  model.durations) or max(model.durations)` (chained segments for over-long scenes are counted as
  `ceil(len / max)` clips of `max`); TTS = `narration_chars / 1000 × rate` for the configured TTS
  provider (`elevenlabs` rate, else OpenAI TTS rate); images = `image_count × cost_flux_image`
  (0 when mock); llm = what the script stage already cost (`cost_openai_gpt4o` × calls, 0 for
  `claude_cli`).
- **pre_clips** (after `plan_segments`, before `generate_segment_clips`): exact
  `sum(unit_clip_cost(model.key, r.requested_len))` over the requests; `spent` = what TTS, images and the LLM
  actually cost so far (§8.3).
- Retries and fallback models are not estimated (fal bills successful generations; a fallback clip is
  logged at its real price afterwards).

## 8. Pipeline wiring (`main.py`)

1. `run_pipeline(..., quality_tier: Optional[str] = None, max_cost: Optional[float] = None)`:
   `quality_tier = quality_tier or settings.quality_tier` (must be in `QUALITY_TIERS` → `ValueError`);
   `max_cost = settings.max_cost_per_video if max_cost is None else max_cost` (negative → `ValueError`).
   The resolved `ClipModel` is computed once (`resolve_clip_model`) and passed to
   `_run_shot_editor` (replacing its `clip_model_for(...)` line). `report.options` gains
   `quality_tier`, `clip_model`, `max_cost`.
2. **Checkpoint 1** right after the script stage: `estimate_pre_tts(...)`; stored at
   `report.cost["estimated"]["pre_tts"]`; if `max_cost > 0 and total > max_cost` →
   `report.warn("cost_cap_exceeded", ..., {"stage": "pre_tts", "estimate": total, "cap": max_cost})`
   and raise `CostCapError` (new, in `app/cin/cost_estimate.py`). Nothing paid yet except the LLM.
3. **Spent so far** at checkpoint 2 is computed, not read from the tracker: actual narration
   characters × the TTS rate + generated image count × `cost_flux_image` + LLM cost, with the same
   unit rates `_log_costs` uses. `_log_costs` stays the single end-of-run writer (no double counting;
   a test asserts `pre_clips.spent + pre_clips.clips` equals the logged total for a run whose clips
   all succeed).
4. **Checkpoint 2** in `_run_shot_editor` after `plan_segments`, before `generate_segment_clips`:
   `estimate_pre_clips(...)`, stored at `report.cost["estimated"]["pre_clips"]`; over cap → same
   warning with `stage: "pre_clips"`, raise `CostCapError`. The job folder (script, narration, images,
   alignment) is kept; the message names it.
5. `report.cost` shape: `{"estimated": {"pre_tts": {...}, "pre_clips": {...}} | None, "cap": max_cost,
   "actual": [...], "total": x}` — `"estimated"` stays `None` for classic runs.
6. Revision call logged (decision 7).
7. Classic / persona path: unchanged model selection (`settings.fal_video_model`); records
   `clip_model` in `report.options`; no checkpoints (legacy path; spec 2026-10-02 §10).
8. `CostCapError` is a `RuntimeError` subclass; the pipeline's failure handling records it like any
   failed run (status `failed`, error text, warnings kept). The web/scheduler surfaces the warning
   through the existing run-report summary.

`WARNING_CODES` gains `cost_cap_exceeded`, `tier_ignored`. `_CARRIED_WARNINGS` does not carry them
(re-render costs nothing).

## 9. Options plumbing (selectable everywhere — user preference)

| Surface | Change |
|---|---|
| `app/config.py` | `quality_tier: Literal["standard","premium","custom"] = "standard"`; `max_cost_per_video: float = 0.0` (ge 0); `clip_pricing` (§5); `fal_video_model` comment lists the new keys |
| CLI | `--tier {standard,premium,custom}` (default None), `--max-cost USD` (float, default None) |
| `app/run_options.py` | `TIER_CHOICES`; `pipeline_kwargs` passes `quality_tier` (choice) and `max_cost` (float ≥ 0; blank = default; non-numeric / negative → `OptionError`); `validate_settings_update` accepts both settings |
| `api_generate` request model | `quality_tier: Optional[str]`, `max_cost: Optional[float]` |
| Scheduler slots / `GeneratorWorker` | carry both through `pipeline_kwargs` (same pattern as `pacing`) |
| `api_config` GET | exposes `quality_tier`, `max_cost_per_video`, and `clip_models`: `[{key, label, price_text}]` built from `CLIP_MODELS` + `clip_pricing`, and `tier_estimates`: per tier × duration preset the pre_tts-style motion estimate (pure helper in `cost_estimate.py`) |
| Web Generate form | Tier select (Default / Standard / Premium / Custom) showing "≈ $X motion for a medium video" from `tier_estimates`; Max cost input (blank = Settings) |
| Scheduler slot form | same two fields |
| Settings page | tier default, max cost, and the `fal_video_model` select built from `clip_models` (replaces the hard-coded `['hailuo','kling','kling-pro']` list) |

## 10. Failure semantics

| Condition | Result |
|---|---|
| Estimate > cap at pre_tts | run fails, `cost_cap_exceeded`, nothing paid but the LLM |
| Estimate > cap at pre_clips | run fails, `cost_cap_exceeded`; TTS + images were paid; job folder kept |
| Unknown tier / negative cap (CLI, API, Settings) | rejected up front (`ValueError` / `OptionError` → HTTP 422) |
| `custom` tier with unknown `fal_video_model` | `ValueError` naming known keys, before any paid call |
| Provider local/replicate, motion off, mock | tier recorded, no effect; `tier_ignored` only when set explicitly |
| A clip fails | existing retry → fallback model → still_fallback (or strict failure); unchanged |
| Pricing entry missing for a model | `ValueError` from the estimate (a test keeps the table complete) |

## 11. Testing (offline; fal and LLM are fakes)

- `build_fal_arguments` payloads pinned per model: Kling v3 → `start_image_url`, `duration: "5"`,
  `generate_audio: False`, no `image_url`, no `aspect_ratio`; H3 → numeric duration,
  `resolution`, `prompt_expansion_mode`; hailuo → no duration. The `generate_audio=False` assertion
  is a cost-correctness test.
- `_generate_fal` passes the builder's dict to a faked `fal_client.subscribe`.
- Every `CLIP_MODELS` key has `clip_pricing`; tier table resolves; unknown custom key raises.
- Estimates: hand-computed totals for a medium script on standard and premium; chained over-long
  scenes; motion off → clips 0; mock → images 0; claude_cli → llm 0.
- Pipeline: cap below the pre_tts estimate → no TTS call (fake TTS asserts not called), status failed,
  `cost_cap_exceeded`; cap between pre_tts and pre_clips → clip generator never called; cap 0 → normal
  run with both estimates in `run_report.json`; `pre_clips.spent + clips` equals the logged total.
- Options: CLI parse, `pipeline_kwargs` accept/reject (blank, "premium", "gold", "-1", "abc"),
  `validate_settings_update`.
- Rerender of a job whose plan names `kling` makes no generator calls (regression guard).
- JS: `node --check` on changed files.

## 12. Risks

| Risk | Mitigation |
|---|---|
| fal prices change | prices live in `settings.clip_pricing` (overridable); estimate is labelled "estimate" |
| Kling v3 9:16 inference differs from the image | Kling schema says aspect follows `start_image_url`; first paid run checks it (open item) |
| H3 durations/aspect unverified | opt-in only; labelled "unverified" in the UI |
| Whole-second billing raises motion cost ~5–10% vs exact | accepted; pre_clips estimate shows the real figure |
| A strict cap stops a run after TTS+images were paid | pre_tts checkpoint catches most overruns before anything is paid |

## 13. Open items for the user (need paid calls — not done without approval)

- First paid Standard and Premium runs (≈ $4–6 each) to confirm 9:16 output and quality.
- One H3 Turbo 480P clip (≈ $0.13) before H3 can become the Standard default.
- Calibrate `WORDS_PER_SECOND` and scene ranges from `run_report.json` after those runs.

## 14. Amendments from planning (2026-10-03)

The implementation plan (`docs/superpowers/plans/2026-10-03-quality-tiers.md`, "Spec deviations")
records 13 places where the code refined this spec; the controller accepted them. The ones that change
behaviour a user sees:
- LLM cost is logged by provider (`claude_cli` at $0) and TTS in the logger's whole 1k-character units;
  estimates use the same rules (`stage_costs`), so an estimate and the logged total agree.
- Estimates follow whole-second Kling billing: a typical medium video is ≈ $4.20 Standard / $5.60
  Premium of motion (list price), above the rough band in §4.1; the UI shows the computed figure.
- A non-fal key (`local`, `replicate-minimax`) as the `custom` model is rejected like an unknown key.
- Classic / persona runs record the cap but do not enforce it (no checkpoints on the legacy path) —
  open item for the user.
- A run stopped by the cap at `pre_clips` writes no `cost_log.json` entry (true of every failed run
  today); `run_report.json` keeps the `pre_clips` estimate with `spent` — open item.

## 15. Follow-up (2026-10-03, user: "do whatever you recommend")

- Classic / persona runs now get checkpoint 1 (`estimate_classic`: one clip per image at 5 s, the length
  `_log_costs` uses); `cap_ignored` is gone. The classic editor still has no second checkpoint.
- A failed or capped run logs what it already paid (`main._log_partial_costs`): script calls, the narration
  when TTS ran, the images on disk, and generated clips; never twice when the failure comes after cost logging.
