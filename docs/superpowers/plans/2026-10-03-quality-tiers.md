# Quality Tiers (Selectable Motion Model, Cost Estimate and Cap) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every video picks a quality tier (motion model) per run from the CLI, web form, scheduler slot or Settings default, sees a list-price cost estimate before anything is paid, and can set a per-video cap that stops the run before the next paid stage instead of overspending or degrading.

**Architecture:** `app/motion_gen.py` gets the new clip-model table (Kling v3, H3, hailuo) and a pure `build_fal_arguments` request builder. A new pure `app/cin/tiers.py` resolves tier + provider + custom model to one `ClipModel`; a new pure `app/cin/cost_estimate.py` computes the `pre_tts` and `pre_clips` estimates with the same unit rules `main._log_costs` logs with, plus the cap rule and the web helpers. `main.run_pipeline` validates tier/cap up front, resolves the model once, runs checkpoint 1 after the script and checkpoint 2 after `plan_segments`, and raises `CostCapError` over the cap. Options flow through the existing `app/run_options.py` plumbing (web, scheduler, worker, Settings) and two CLI flags.

**Tech Stack:** Python 3.14 (venv `.venv/`), pydantic v2 / pydantic-settings, pytest, vanilla JS (checked with `node --check`), Windows + Git Bash. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-03-quality-tiers-design.md`

## Spec deviations

The spec is the authority; these are places where the code contradicts it or leaves it ambiguous. Each line gives the finding and the resolution this plan implements.

1. **LLM cost is always logged as `openai_gpt4o`.** `main._log_costs` calls `tracker.log_cost(video_id, "openai_gpt4o")` whatever `settings.llm_provider` is, so spec §7 ("llm = 0 for `claude_cli`") and the §8.3 equality test cannot both hold. Resolution: one helper `llm_cost_item()` (`"openai_gpt4o"` when `llm_provider == "openai"`, else `"claude_cli"`, which costs `settings.cost_claude_cli` = $0) used by `_log_costs` and the estimate. The draft and the attempted revision are two separate items (spec decision 7).
2. **TTS is logged in whole 1k-character units.** `_log_costs` logs `max(1, len(narration) // 1000)` units, not `chars / 1000` (spec §7). Resolution: `tts_units(chars)` with the logger's rule, shared by `_log_costs` and both estimates.
3. **There is no TTS-provider setting.** `_log_costs` picks the item by key presence (`elevenlabs_api_key` → `elevenlabs_tts`, else `openai_api_key` → `openai_tts`, else nothing). Resolution: `tts_cost_item()` mirrors that rule. Consequently `estimate_pre_tts` / `estimate_pre_clips` take one `costs` dict from `stage_costs(...)` (tts, images, llm) instead of `tts_provider` / `llm_cost` / `spent` arguments; `pre_clips.spent` is derived from it.
4. **`validate_settings_update` does not exist.** The real functions are `clean_settings_updates` and `validate_settings_updates`; the latter validates with `TypeAdapter(field.annotation)`, which drops `Field(ge=0)`. Resolution: `clean_settings_updates` rejects blank, negative, NaN, infinite and non-numeric `max_cost_per_video` (and blank / unknown `quality_tier`) itself.
5. **Classic clips would shrink to 3 s.** The classic editor calls `_generate_fal` with no duration; spec §5's builder uses `min(durations)`, which is 3 s on Kling v3 (5 s on the old v1), while `_log_costs` logs classic clips at `snap_duration(5.0, ...)`. Spec §8.7 says classic is unchanged. Resolution: `CLASSIC_CLIP_SECONDS = 5.0` in `app/motion_gen.py`, passed by `generate_motion_clip` and used by `_log_costs`.
6. **A non-fal key as the custom model.** `CLIP_MODELS.get("local")` / `"replicate-minimax"` returns a model with `endpoint=None`, which `_generate_fal` refuses, so every clip would become a still. Resolution: `resolve_clip_model` treats non-fal keys like unknown keys (`ValueError` naming the fal keys).
7. **Classic / persona runs ignore the cap.** Spec §8.7 gives the classic path no checkpoints, so `max_cost` is recorded (`report.cost["cap"]`) but not enforced there. Resolution: implemented as specified; `tier_ignored` (spec decision 6) also fires for classic runs when the tier was set explicitly. Open item for the user: decide whether classic runs should get checkpoint 1.
8. **Failed runs write no cost log.** `_log_costs` runs only after a successful render, so a `CostCapError` at `pre_clips` leaves the paid TTS and images out of `output/cost_log.json`. This is pre-existing for every failed run; not changed here (the `pre_clips` estimate in `run_report.json` records `spent`).
9. **Tier estimate vs the spec's prose band.** At whole-second Kling billing a typical medium video (117 words, 10 scenes of 5 s) is $4.20 Standard / $5.60 Premium, above spec §4.1's "≈ $3.4–3.8 / $4.5–5.0 per 40 s". The UI shows the computed figure, labelled as a list-price estimate.
10. **`clip_models` lists fal models only.** It replaces the hard-coded `fal_video_model` select, so `local` / `replicate-minimax` (no endpoint) are left out. A saved key that is no longer known stays selectable, marked "(unknown)".
11. **`unit_clip_cost` lives in `app/cost_tracker.py`.** `app/cin/cost_estimate.py` imports `unit_costs` from the tracker module, so defining `unit_clip_cost` in `cost_estimate` and calling it from `CostTracker` would be circular. Resolution: module-level `unit_clip_cost` / `unit_costs` in `app/cost_tracker.py` (the tracker delegates to them) and re-exported by `app/cin/cost_estimate.py`.
12. **`api_generate` `max_cost` type.** `Optional[float]` would turn a blank `""` into a pydantic 422 instead of "blank = default" (spec §9). Resolution: `Optional[Union[float, str]]`; `pipeline_kwargs` parses it and gives one message for every bad value.
13. **Settings page blank cap.** Settings defaults are concrete values (existing rule in `clean_settings_updates`), so the API rejects a blank `max_cost_per_video`; the Settings page sends `0` (no cap) when its input is blank.

## Global Constraints

- Motion only: every shot is AI motion footage. The cap never degrades a run to stills, a cheaper model or fewer clips; over the cap the run stops with `CostCapError` (a `RuntimeError`) before the next paid stage. `max_cost` `0` (default) = no cap.
- Tiers: `QUALITY_TIERS = ("standard", "premium", "custom")`, `TIER_MODELS = {"standard": "kling", "premium": "kling-pro"}`, `custom` = `settings.fal_video_model`; default `quality_tier = "standard"`. The tier applies only to fal motion in the shot editor.
- `kling` / `kling-pro` keep their names and point at `fal-ai/kling-video/v3/standard/image-to-video` / `fal-ai/kling-video/v3/pro/image-to-video`; Kling lengths `range(3, 16)`, H3 lengths `range(5, 16)`; Kling sends `start_image_url`, `duration` as a string and `generate_audio: False`; no model sends `aspect_ratio`.
- List prices only (no promo prices): `kling {per_second 0.084}`, `kling-pro {per_second 0.112}`, `hailuo {per_clip 0.50}`, `h3-turbo {per_second 0.04}`, `h3 {per_second 0.08}`, `replicate-minimax {per_clip 0.50}`, `local {per_clip 0.0}`. Every `CLIP_MODELS` key has a `clip_pricing` entry.
- No paid API calls. Tests are offline: `fal_client`, TTS, the LLM and image generation are fakes. Pipeline tests use the `offline` fixture in `tests/test_pipeline.py`; an unpatched LLM call starts the `claude` CLI subprocess, so never leave one unpatched.
- Never read or print `.env`.
- Never stage `output/cost_log.json` (it is modified in the working tree). `git add` only the files a task lists; never `git add -A` / `git add .`; never `git add -f` anything under `.superpowers/`.
- CRLF line endings are kept (the repo has `core.autocrlf=true`; working-tree files are CRLF). New files are written with CRLF too.
- Compare clip models by `.key`, never by `==` / `is`: `tests/test_motion_gen.py::test_generate_motion_clip_fal` reloads `app.motion_gen`, which creates new `ClipModel` objects.
- `fastapi` and `apscheduler` are not installed locally: route and scheduler code is only `py_compile`-checked; logic lives in pure modules (`app/run_options.py`, `app/cin/cost_estimate.py`, `app/cin/tiers.py`).
- Run commands from the repo root in Git Bash with `.venv/Scripts/python.exe`.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Baseline (`main`, 2026-10-03): `.venv/Scripts/python.exe -m pytest tests/ -q --tb=short -rf -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py` → `601 passed, 12 failed` (4 `test_uploader`, 6 `test_trends`, 1 `test_trend_scout`, 1 `test_local_image_gen`). These 12 stay failing; nothing else may.

## Review Focus

1. **`--rerender` of a job made before this change, whose plan and report name `kling`** — a person expects the saved clips to be reused with zero generator calls, even though `kling` now means Kling v3. Pinned by `test_rerender_of_a_kling_plan_makes_no_generator_calls` (Task 1).
2. **`custom` tier with an unknown or non-fal `fal_video_model`** (a typo such as `sora`, or `local` saved from an old config) — a person expects the run to be rejected before any job folder or paid call, with the valid keys named, not a silent hailuo substitution or a video of stills. Pinned by `test_unknown_or_non_fal_custom_model_raises_naming_the_choices` (Task 2) and `test_unknown_custom_model_rejected_before_any_work` (Task 4).
3. **A tier chosen while motion is `local` / `replicate`, motion is off, images are mock, or the run is classic** — a person expects the tier to be recorded with no effect and a `tier_ignored` warning only when they set it explicitly (never for the Settings default). Pinned by `test_local_and_replicate_ignore_the_tier` (Task 2), `test_explicit_tier_with_mock_images_warns_tier_ignored`, `test_settings_default_tier_never_warns`, `test_tier_has_no_effect_on_local_or_replicate_motion`, `test_classic_run_records_its_model_without_estimates` (Task 4).
4. **A cap exactly equal to the estimate** — a person expects the run to proceed (the cap is a maximum, not exceeded by equality, and float noise must not tip it). Pinned by `test_cap_rule` (Task 3) and `test_cap_equal_to_the_estimate_is_not_exceeded` (Task 4).
5. **`max_cost` given as `"0"`, blank, negative, `"abc"`, `"nan"`, `"inf"` or `true`** through the CLI, web form, scheduler slot, worker, Settings page and `run_pipeline` — a person expects `0` = no cap, blank = the Settings default (Settings page: blank = 0), and every other bad value rejected up front (argparse error / HTTP 422 / `OptionError` / `ValueError`), never a silent "no cap". Pinned by `test_quality_tier_settings_defaults_and_validation` (Task 2), `test_bad_tier_or_cap_rejected_before_any_work` (Task 4), `test_max_cost_option`, `test_bad_max_cost_rejected`, `test_settings_update_cleaning_for_tier_and_cap`, `test_worker_rejects_bad_cap_before_going_busy`, `test_bad_tier_or_max_cost_rejected` (Task 5).

---

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `app/motion_gen.py` | `ClipModel` table (Kling v3, H3, hailuo), `build_fal_arguments`, `CLASSIC_CLIP_SECONDS` | 1 |
| `app/config.py` | `clip_pricing` list prices; `quality_tier`, `max_cost_per_video` | 1, 2 |
| `app/cin/tiers.py` (new) | `QUALITY_TIERS`, `TIER_MODELS`, `resolve_clip_model`. Pure. | 2 |
| `app/cost_tracker.py` | module-level `unit_costs`, `unit_clip_cost` (tracker delegates) | 3 |
| `app/cin/cost_estimate.py` (new) | estimates, `CostCapError`, cap rule, `tier_estimates`, `clip_model_options`. Pure. | 3 |
| `app/cin/report.py` | warning codes `cost_cap_exceeded`, `tier_ignored` | 4 |
| `main.py` | tier/cap validation, model resolution, checkpoints, `report.cost` shape, revision logging; CLI flags | 4, 5 |
| `app/run_options.py` | `TIER_CHOICES`, `to_max_cost`, `pipeline_kwargs`, `clean_settings_updates` | 5 |
| `app/web/routes/api_generate.py`, `app/web/routes/api_config.py`, `app/generator_worker.py` | request fields, config payload, worker arguments | 5 |
| `app/web/static/js/{generate,scheduler,settings}.js`, `CLAUDE.md`, `.env.example` | UI fields, docs | 2, 6 |

`app/scheduler.py` and `app/web/routes/api_scheduler.py` need no change: slots already go through `pipeline_kwargs` (run time and slot validation), so the new keys are carried and validated automatically.

---

### Task 1: Clip-model table, fal request builder and list prices

**Files:**
- Modify: `app/motion_gen.py` (`ClipModel`, `CLIP_MODELS`, new `build_fal_arguments`, `_generate_fal`, `generate_motion_clip`)
- Modify: `app/config.py` (`clip_pricing`, `fal_video_model` comment)
- Test: `tests/test_motion_gen.py`, `tests/test_cost_tracker.py`, `tests/test_config.py`, `tests/test_rerender.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Tasks 2–6):
  - `@dataclass(frozen=True) ClipModel(key: str, endpoint: Optional[str], durations: Optional[Tuple[float, ...]], duration_format: str = "none", image_arg: str = "image_url", extra_args: Tuple[Tuple[str, object], ...] = (), label: str = "")` — the `sends_duration` field is removed.
  - `KLING_V3_LENGTHS`, `H3_LENGTHS: Tuple[float, ...]`; `CLASSIC_CLIP_SECONDS: float = 5.0`
  - `CLIP_MODELS: dict[str, ClipModel]` with keys, in order, `kling`, `kling-pro`, `hailuo`, `h3-turbo`, `h3`, `replicate-minimax`, `local`
  - `build_fal_arguments(model: ClipModel, image_url: str, prompt: str, duration: Optional[float]) -> dict`
  - `settings.clip_pricing` entries for every `CLIP_MODELS` key
  - unchanged: `clip_model_for(provider, fal_model) -> ClipModel`, `snap_duration`, `max_duration`, `FAL_MODELS`

- [ ] **Step 1: Write the failing tests**

In `tests/test_motion_gen.py` (the first line of the file), find

```python
import tempfile
```

and replace it with

```python
import tempfile

import pytest
```

In `tests/test_motion_gen.py::test_clip_model_for_providers`, find

```python
    assert CLIP_MODELS["hailuo"].durations == (6.0,)
    assert CLIP_MODELS["kling"].sends_duration is True
```

and replace it with

```python
    assert CLIP_MODELS["hailuo"].durations == (6.0,)
    assert CLIP_MODELS["kling"].duration_format == "int_str"
```

In `tests/test_motion_gen.py::test_generate_clip_kling_requests_snapped_duration`, find

```python
    assert fal.subscribe.call_args.args[0] == CLIP_MODELS["kling"].endpoint
    arguments = fal.subscribe.call_args.kwargs["arguments"]
    assert arguments["duration"] == "10" and arguments["aspect_ratio"] == "9:16"
```

and replace it with

```python
    assert fal.subscribe.call_args.args[0] == CLIP_MODELS["kling"].endpoint
    assert fal.subscribe.call_args.kwargs["arguments"] == {
        "prompt": "orbit", "start_image_url": "https://fal.media/in.png",
        "generate_audio": False, "duration": "7"}
```

Append to the end of `tests/test_motion_gen.py`:

```python


# ---------------------------------------------------------------- quality tiers (spec 2026-10-03 §5)

def test_clip_model_table_points_kling_keys_at_v3():
    from app.motion_gen import CLIP_MODELS, H3_LENGTHS, KLING_V3_LENGTHS
    assert CLIP_MODELS["kling"].endpoint == "fal-ai/kling-video/v3/standard/image-to-video"
    assert CLIP_MODELS["kling-pro"].endpoint == "fal-ai/kling-video/v3/pro/image-to-video"
    assert CLIP_MODELS["h3-turbo"].endpoint == "minimax/h3-max-turbo/image-to-video"
    assert CLIP_MODELS["h3"].endpoint == "minimax/h3-max/image-to-video"
    assert KLING_V3_LENGTHS == tuple(float(d) for d in range(3, 16))
    assert H3_LENGTHS == tuple(float(d) for d in range(5, 16))
    assert all(m.key == k and m.label for k, m in CLIP_MODELS.items())


@pytest.mark.parametrize("key", ["kling", "kling-pro"])
def test_kling_v3_payload_never_bills_audio(key):
    """Cost correctness: fal's generate_audio default is true and costs more (spec §5)."""
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    args = build_fal_arguments(CLIP_MODELS[key], "https://fal.media/in.png", "orbit", 4.7)
    assert args == {"prompt": "orbit", "start_image_url": "https://fal.media/in.png",
                    "generate_audio": False, "duration": "5"}
    assert "image_url" not in args and "aspect_ratio" not in args


@pytest.mark.parametrize("duration, expected", [(None, "3"), (2.0, "3"), (5.0, "5"), (5.01, "6"),
                                                (14.9, "15"), (20.0, "15")])
def test_kling_duration_snaps_up_to_whole_seconds(duration, expected):
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    assert build_fal_arguments(CLIP_MODELS["kling"], "u", "p", duration)["duration"] == expected


@pytest.mark.parametrize("key", ["h3-turbo", "h3"])
def test_h3_payload_has_numeric_duration_and_768p(key):
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    args = build_fal_arguments(CLIP_MODELS[key], "https://fal.media/in.png", "pan", 6.2)
    assert args == {"prompt": "pan", "image_url": "https://fal.media/in.png", "resolution": "768P",
                    "prompt_expansion_mode": "balanced", "duration": 7}
    assert build_fal_arguments(CLIP_MODELS[key], "u", "p", 2.0)["duration"] == 5


def test_hailuo_payload_has_no_duration():
    from app.motion_gen import CLIP_MODELS, build_fal_arguments
    assert build_fal_arguments(CLIP_MODELS["hailuo"], "u", "p", 4.0) == {"prompt": "p", "image_url": "u"}


def test_generate_fal_sends_the_builder_payload(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import CLIP_MODELS, MotionGenerator, build_fal_arguments
    monkeypatch.setattr(settings, "motion_provider", "fal")
    fal = _fake_fal()
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        MotionGenerator(temp_dir=str(tmp_path)).generate_clip(
            str(image), "orbit", str(out), duration=6.2, model_key="h3-turbo")
    assert fal.subscribe.call_args.args[0] == CLIP_MODELS["h3-turbo"].endpoint
    assert fal.subscribe.call_args.kwargs["arguments"] == build_fal_arguments(
        CLIP_MODELS["h3-turbo"], "https://fal.media/in.png", "orbit", 6.2)


def test_classic_clip_keeps_five_seconds_on_kling_v3(tmp_path, monkeypatch):
    """The classic editor passes no length; it used to get Kling's old 5 s minimum (spec §8.7: unchanged)."""
    from app.config import settings
    from app.motion_gen import MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_video_model", "kling")
    fal = _fake_fal()
    image, _ = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        assert MotionGenerator(temp_dir=str(tmp_path)).generate_motion_clip(str(image), "orbit") is not None
    assert fal.subscribe.call_args.kwargs["arguments"]["duration"] == "5"


def test_every_clip_model_has_list_pricing():
    from app.config import Settings
    from app.motion_gen import CLIP_MODELS
    pricing = Settings(_env_file=None).clip_pricing
    assert set(CLIP_MODELS) <= set(pricing)
    assert pricing["kling"] == {"per_second": 0.084} and pricing["kling-pro"] == {"per_second": 0.112}
    assert pricing["h3-turbo"] == {"per_second": 0.04} and pricing["h3"] == {"per_second": 0.08}
    assert pricing["hailuo"] == {"per_clip": 0.50}
```

In `tests/test_cost_tracker.py`, find

```python
def test_kling_clip_priced_per_second(tmp_path):
    tracker = CostTracker(output_dir=str(tmp_path))
    assert tracker.log_clip("v1", "kling", seconds=10.0) == 0.45
```

and replace it with

```python
def test_kling_clip_priced_per_second(tmp_path, monkeypatch):
    from app.config import Settings, settings
    monkeypatch.setattr(settings, "clip_pricing", Settings(_env_file=None).clip_pricing)
    tracker = CostTracker(output_dir=str(tmp_path))
    assert tracker.log_clip("v1", "kling", seconds=10.0) == 0.84          # Kling v3 Standard $0.084/s
    assert tracker.log_clip("v1", "kling-pro", seconds=5.0) == 0.56       # Kling v3 Pro $0.112/s
```

In `tests/test_config.py::test_v2_settings_have_defaults`, find

```python
    assert s.clip_pricing["kling"] == {"per_second": 0.045}
```

and replace it with

```python
    assert s.clip_pricing["kling"] == {"per_second": 0.084}         # Kling v3 Standard, audio off
```

Append to the end of `tests/test_rerender.py` (a regression guard: it passes before and after this task):

```python


def test_rerender_of_a_kling_plan_makes_no_generator_calls(tmp_path, monkeypatch):
    """Quality tiers (spec 2026-10-03 §4.2): "kling" now names Kling v3; a re-render of an old plan
    that names it reuses the saved clips and never calls a motion generator."""
    job, plan = saved_job(tmp_path)                 # build_gold_job made every clip with model "kling"
    prev = RunReport.load(job.report)
    prev.clips = {"requested": 2, "generated": 2, "failed": 0, "by_model": {"kling": 2}}
    prev.save(job.report)

    def no_generation(*args, **kwargs):
        raise AssertionError("motion generator called during rerender")

    monkeypatch.setattr("app.motion_gen.MotionGenerator.generate_clip", no_generation)
    monkeypatch.setattr("app.motion_gen.MotionGenerator._generate_fal", no_generation)
    monkeypatch.setattr("app.cin.clip_sourcing.generate_segment_clips", no_generation)
    monkeypatch.setitem(sys.modules, "fal_client", None)
    monkeypatch.setattr("app.cin.editor.render_job", lambda *a, **k: job.final)
    assert rerender_job(job.root, pacing="fast") == str(job.final)
    assert all(s.source.type == "clip" for s in ShotPlan.load(job.shot_plan).shots)
    assert RunReport.load(job.report).clips["by_model"] == {"kling": 2}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_cost_tracker.py tests/test_config.py tests/test_rerender.py -q -p no:cacheprovider -m "not render"`
Expected: FAIL — `ImportError: cannot import name 'build_fal_arguments'` / `'KLING_V3_LENGTHS'`, `AttributeError: 'ClipModel' object has no attribute 'duration_format'`, `assert 0.45 == 0.84`, the old `{"per_second": 0.045}` pricing, and the Kling payload still carrying `aspect_ratio`. `test_rerender_of_a_kling_plan_makes_no_generator_calls` passes.

- [ ] **Step 3: Implement the clip-model table and the builder**

In `app/motion_gen.py`, find

```python
@dataclass(frozen=True)
class ClipModel:
    """A motion model and the clip lengths it can return (spec §6.4)."""
    key: str
    endpoint: Optional[str]                    # fal endpoint; None for non-fal providers
    durations: Optional[Tuple[float, ...]]     # supported lengths in seconds; None = any length
    sends_duration: bool = False               # pass a "duration" argument to the endpoint


# Kling v1 / v1.5 fal endpoints are marked deprecated on fal.ai (checked 2026-10-02); they stay
# for existing configs. Sub-project 3 replaces this table with current models.
CLIP_MODELS = {
    "hailuo": ClipModel("hailuo", "fal-ai/minimax-video/image-to-video", (6.0,)),
    "kling": ClipModel("kling", "fal-ai/kling-video/v1/standard/image-to-video", (5.0, 10.0), True),
    "kling-pro": ClipModel("kling-pro", "fal-ai/kling-video/v1.5/pro/image-to-video", (5.0, 10.0), True),
    "replicate-minimax": ClipModel("replicate-minimax", None, (6.0,)),
    "local": ClipModel("local", None, None),
}
```

and replace it with

```python
@dataclass(frozen=True)
class ClipModel:
    """A motion model: endpoint, clip lengths and request format (spec 2026-10-03 §5)."""
    key: str
    endpoint: Optional[str]                    # fal endpoint; None for non-fal providers
    durations: Optional[Tuple[float, ...]]     # supported lengths in seconds; None = any length
    duration_format: str = "none"              # "none" | "int_str" ("5") | "number" (5)
    image_arg: str = "image_url"               # Kling v3: "start_image_url"
    extra_args: Tuple[Tuple[str, object], ...] = ()   # constant arguments, e.g. (("generate_audio", False),)
    label: str = ""                            # human label for the Settings page / API


KLING_V3_LENGTHS = tuple(float(d) for d in range(3, 16))
H3_LENGTHS = tuple(float(d) for d in range(5, 16))        # upper bound unverified (spec §4.4)
_KLING_ARGS = (("generate_audio", False),)                 # fal default is true and bills more
_H3_ARGS = (("resolution", "768P"), ("prompt_expansion_mode", "balanced"))
CLASSIC_CLIP_SECONDS = 5.0     # the classic editor's clip length (old Kling minimum); see main._log_costs

# fal list prices live in settings.clip_pricing (checked 2026-10-03). Kling v1/v1.5 are dead on
# fal; the "kling" / "kling-pro" keys now name Kling v3 so saved configs stay valid.
CLIP_MODELS = {
    "kling": ClipModel("kling", "fal-ai/kling-video/v3/standard/image-to-video", KLING_V3_LENGTHS,
                       "int_str", "start_image_url", _KLING_ARGS, "Kling v3 Standard"),
    "kling-pro": ClipModel("kling-pro", "fal-ai/kling-video/v3/pro/image-to-video", KLING_V3_LENGTHS,
                           "int_str", "start_image_url", _KLING_ARGS, "Kling v3 Pro"),
    "hailuo": ClipModel("hailuo", "fal-ai/minimax-video/image-to-video", (6.0,), label="Minimax video-01"),
    "h3-turbo": ClipModel("h3-turbo", "minimax/h3-max-turbo/image-to-video", H3_LENGTHS, "number",
                          extra_args=_H3_ARGS, label="MiniMax H3 Max Turbo (unverified 9:16)"),
    "h3": ClipModel("h3", "minimax/h3-max/image-to-video", H3_LENGTHS, "number",
                    extra_args=_H3_ARGS, label="MiniMax H3 Max (unverified 9:16)"),
    "replicate-minimax": ClipModel("replicate-minimax", None, (6.0,), label="Replicate Minimax"),
    "local": ClipModel("local", None, None, label="Local (free)"),
}
```

In `app/motion_gen.py::snap_duration` (its last lines), find

```python
    for d in sorted(durations):
        if d + 1e-6 >= needed:
            return d
    return None
```

and replace it with

```python
    for d in sorted(durations):
        if d + 1e-6 >= needed:
            return d
    return None


def build_fal_arguments(model: ClipModel, image_url: str, prompt: str, duration: Optional[float]) -> dict:
    """The fal request body for one clip (spec 2026-10-03 §5). No model sends aspect_ratio: Kling v3
    and H3 follow the 9:16 start image, hailuo never took one. duration None = the shortest length."""
    args = {"prompt": prompt, model.image_arg: image_url, **dict(model.extra_args)}
    if model.duration_format != "none":
        length = snap_duration(duration or min(model.durations), model.durations) or max(model.durations)
        args["duration"] = str(int(length)) if model.duration_format == "int_str" else int(length)
    return args
```

In `app/motion_gen.py::MotionGenerator._generate_fal`, find

```python
        # Build arguments
        args = {
            "prompt": motion_prompt,
            "image_url": image_url,
        }

        # Kling takes a length ("5"/"10") and an aspect ratio; Minimax/hailuo takes neither
        if model.sends_duration:
            length = snap_duration(duration or min(model.durations), model.durations) or max(model.durations)
            args["duration"] = str(int(length))
            args["aspect_ratio"] = "9:16"
```

and replace it with

```python
        args = build_fal_arguments(model, image_url, motion_prompt, duration)
```

In `app/motion_gen.py::MotionGenerator.generate_motion_clip` (the classic path), find

```python
        try:
            if provider == "fal":
                return self._generate_fal(image_path, motion_prompt, index)
            elif provider == "replicate":
                return self._generate_replicate(image_path, motion_prompt, index)
            elif provider == "local":
                return self._generate_local(image_path, motion_prompt, index)
            else:
                # Default: try fal first, fall back to replicate
                return self._generate_fal(image_path, motion_prompt, index)
```

and replace it with

```python
        try:
            if provider == "fal":
                return self._generate_fal(image_path, motion_prompt, index, duration=CLASSIC_CLIP_SECONDS)
            elif provider == "replicate":
                return self._generate_replicate(image_path, motion_prompt, index)
            elif provider == "local":
                return self._generate_local(image_path, motion_prompt, index)
            else:
                # Default: try fal first, fall back to replicate
                return self._generate_fal(image_path, motion_prompt, index, duration=CLASSIC_CLIP_SECONDS)
```

- [ ] **Step 4: Set the list prices**

In `app/config.py`, find

```python
    # Motion clip pricing per model: {"per_clip": usd} or {"per_second": usd}.
    # fal list prices checked 2026-10-02 — verify against billing.
    clip_pricing: dict = {
        "hailuo": {"per_clip": 0.50},
        "kling": {"per_second": 0.045},
        "kling-pro": {"per_second": 0.10},
        "replicate-minimax": {"per_clip": 0.50},
        "local": {"per_clip": 0.0},
    }
```

and replace it with

```python
    # Motion clip pricing per model: {"per_clip": usd} or {"per_second": usd}. Every CLIP_MODELS key
    # needs an entry. fal list prices (audio off) checked 2026-10-03, subject to change; no promo prices.
    clip_pricing: dict = {
        "kling": {"per_second": 0.084},          # Kling v3 Standard
        "kling-pro": {"per_second": 0.112},      # Kling v3 Pro
        "hailuo": {"per_clip": 0.50},            # Minimax video-01, 6 s fixed
        "h3-turbo": {"per_second": 0.04},        # MiniMax H3 Max Turbo 768P
        "h3": {"per_second": 0.08},              # MiniMax H3 Max 768P
        "replicate-minimax": {"per_clip": 0.50},
        "local": {"per_clip": 0.0},
    }
```

In `app/config.py`, find

```python
    fal_video_model: str = "hailuo"         # "hailuo" | "kling" | "kling-pro"
```

and replace it with

```python
    fal_video_model: str = "hailuo"         # custom tier model: kling | kling-pro | hailuo | h3-turbo | h3
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_cost_tracker.py tests/test_config.py tests/test_rerender.py -q -p no:cacheprovider -m "not render"`
Expected: PASS (0 failed).

Run: `git grep -n "sends_duration" -- app tests main.py`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add app/motion_gen.py app/config.py tests/test_motion_gen.py tests/test_cost_tracker.py tests/test_config.py tests/test_rerender.py
git commit -m "feat: Kling v3 / H3 clip-model table, fal request builder, list prices

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Tier resolution and the tier / cap settings

**Files:**
- Create: `app/cin/tiers.py`
- Modify: `app/config.py` (imports; new `quality_tier`, `max_cost_per_video` after `music_source`)
- Modify: `.env.example`
- Test: `tests/test_tiers.py` (new), `tests/test_config.py`

**Interfaces:**
- Consumes: `CLIP_MODELS`, `ClipModel`, `clip_model_for` from Task 1.
- Produces (used by Tasks 3–6):
  - `QUALITY_TIERS: tuple = ("standard", "premium", "custom")`
  - `TIER_MODELS: dict = {"standard": "kling", "premium": "kling-pro"}`
  - `fal_model_keys() -> list[str]` — `["kling", "kling-pro", "hailuo", "h3-turbo", "h3"]`
  - `resolve_clip_model(tier: str, provider: str, custom_model: str) -> ClipModel` — `ValueError` for an unknown tier or an unknown / non-fal custom key
  - `settings.quality_tier: Literal["standard", "premium", "custom"] = "standard"`
  - `settings.max_cost_per_video: float = 0.0` (`ge=0`, no NaN / infinity)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tiers.py`:

```python
"""Quality tier -> clip model (spec 2026-10-03 §6). Compare .key, never ClipModel identity:
tests/test_motion_gen.py reloads app.motion_gen, which creates new ClipModel objects."""
import pytest

from app.cin.tiers import QUALITY_TIERS, TIER_MODELS, fal_model_keys, resolve_clip_model
from app.motion_gen import CLIP_MODELS


def test_tier_table():
    assert QUALITY_TIERS == ("standard", "premium", "custom")
    assert TIER_MODELS == {"standard": "kling", "premium": "kling-pro"}
    assert all(CLIP_MODELS[key].endpoint for key in TIER_MODELS.values())


@pytest.mark.parametrize("tier, custom, expected", [
    ("standard", "hailuo", "kling"), ("premium", "hailuo", "kling-pro"),
    ("custom", "hailuo", "hailuo"), ("custom", "h3-turbo", "h3-turbo"), ("custom", "kling-pro", "kling-pro"),
])
def test_fal_tiers_resolve(tier, custom, expected):
    assert resolve_clip_model(tier, "fal", custom).key == expected


@pytest.mark.parametrize("tier", QUALITY_TIERS)
def test_local_and_replicate_ignore_the_tier(tier):
    assert resolve_clip_model(tier, "local", "kling").key == "local"
    assert resolve_clip_model(tier, "replicate", "kling").key == "replicate-minimax"


@pytest.mark.parametrize("custom", ["sora", "", "local", "replicate-minimax"])
def test_unknown_or_non_fal_custom_model_raises_naming_the_choices(custom):
    with pytest.raises(ValueError) as info:
        resolve_clip_model("custom", "fal", custom)
    assert "kling-pro" in str(info.value) and "h3-turbo" in str(info.value)


def test_unknown_tier_raises():
    with pytest.raises(ValueError, match="choose one of standard, premium, custom"):
        resolve_clip_model("gold", "fal", "kling")


def test_fal_model_keys_are_the_models_with_an_endpoint():
    assert fal_model_keys() == ["kling", "kling-pro", "hailuo", "h3-turbo", "h3"]
```

Append to the end of `tests/test_config.py`:

```python


def test_quality_tier_settings_defaults_and_validation():
    s = make()
    assert s.quality_tier == "standard" and s.max_cost_per_video == 0.0
    assert make(quality_tier="premium", max_cost_per_video=4.5).max_cost_per_video == 4.5
    for bad in ({"quality_tier": "gold"}, {"max_cost_per_video": -1}, {"max_cost_per_video": float("nan")},
                {"max_cost_per_video": float("inf")}, {"max_cost_per_video": "abc"}):
        with pytest.raises(ValidationError):
            make(**bad)


def test_env_example_documents_quality_tier_settings():
    import re
    from pathlib import Path
    text = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
    keys = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, flags=re.M))
    assert {"QUALITY_TIER", "MAX_COST_PER_VIDEO"} <= keys
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tiers.py tests/test_config.py -q -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cin.tiers'` (collection error for `tests/test_tiers.py`), `AttributeError: 'Settings' object has no attribute 'quality_tier'`, and the `.env.example` keys missing.

- [ ] **Step 3: Create the tier module**

Create `app/cin/tiers.py`:

```python
"""Quality tiers -> motion model (spec 2026-10-03 §4, §6). Pure: no I/O.

Tiers differ by motion model only; every shot is motion footage. "custom" means
settings.fal_video_model. The tier only applies to fal: local / replicate keep their own model.
"""
from __future__ import annotations

from app.motion_gen import CLIP_MODELS, ClipModel, clip_model_for

QUALITY_TIERS = ("standard", "premium", "custom")
TIER_MODELS = {"standard": "kling", "premium": "kling-pro"}


def fal_model_keys() -> list:
    """Clip-model keys a fal run can use (the custom tier's choices)."""
    return [key for key, model in CLIP_MODELS.items() if model.endpoint]


def resolve_clip_model(tier: str, provider: str, custom_model: str) -> ClipModel:
    """provider local/replicate -> clip_model_for(provider, ...) regardless of tier; fal:
    standard/premium -> the tier's model; custom -> CLIP_MODELS[custom_model]. An unknown tier or an
    unknown / non-fal custom key raises ValueError (never a silent hailuo substitution)."""
    if tier not in QUALITY_TIERS:
        raise ValueError(f"Unknown quality tier {tier!r}; choose one of {', '.join(QUALITY_TIERS)}")
    if provider in ("local", "replicate"):
        return clip_model_for(provider, custom_model)
    if tier in TIER_MODELS:
        return CLIP_MODELS[TIER_MODELS[tier]]
    model = CLIP_MODELS.get(custom_model)
    if model is None or model.endpoint is None:
        raise ValueError(f"Unknown fal video model {custom_model!r} for the custom tier; "
                         f"set fal_video_model to one of {', '.join(fal_model_keys())}")
    return model
```

`clip_model_for` keeps its unknown-key fallback to `hailuo` for the classic path (spec §6).

- [ ] **Step 4: Add the settings**

In `app/config.py`, find

```python
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
```

and replace it with

```python
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
```

In `app/config.py`, find

```python
    music_source: Literal["mine", "generated", "any", "none"] = "any"   # spec §8.1
```

and replace it with

```python
    music_source: Literal["mine", "generated", "any", "none"] = "any"   # spec §8.1

    # === Quality tiers (spec 2026-10-03) ===
    # standard = Kling v3 Standard, premium = Kling v3 Pro, custom = fal_video_model. Tiers change the
    # motion model only; every shot stays motion footage.
    quality_tier: Literal["standard", "premium", "custom"] = "standard"
    # USD per video. A run whose estimate exceeds it stops before the next paid stage (never degrades
    # to stills or a cheaper model). 0 = no cap.
    max_cost_per_video: float = Field(0.0, ge=0, allow_inf_nan=False)
```

In `.env.example`, find

```
# Fallback fal video model, e.g. kling (empty = none)
# FAL_VIDEO_FALLBACK_MODEL=
```

and replace it with

```
# Fallback fal video model, e.g. kling (empty = none)
# FAL_VIDEO_FALLBACK_MODEL=

# Quality tiers (motion model per video): standard (Kling v3 Standard) | premium (Kling v3 Pro) |
# custom (FAL_VIDEO_MODEL: kling | kling-pro | hailuo | h3-turbo | h3)
# QUALITY_TIER=standard
# Per-video spending cap in USD; the run stops before the next paid stage when the estimate is higher (0 = no cap)
# MAX_COST_PER_VIDEO=0
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_tiers.py tests/test_config.py -q -p no:cacheprovider`
Expected: PASS (0 failed).

Run (reload-order check: `test_motion_gen.py` reloads `app.motion_gen` before the tier tests run; they compare `.key`, so they still pass): `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_tiers.py -q -p no:cacheprovider`
Expected: PASS (0 failed).

- [ ] **Step 6: Commit**

```bash
git add app/cin/tiers.py app/config.py .env.example tests/test_tiers.py tests/test_config.py
git commit -m "feat: quality tier resolution and tier/cap settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Cost estimates, the cap rule and the web helpers

**Files:**
- Modify: `app/cost_tracker.py` (module-level `unit_costs`, `unit_clip_cost`; the tracker delegates)
- Create: `app/cin/cost_estimate.py`
- Test: `tests/test_cost_estimate.py` (new); existing `tests/test_cost_tracker.py` must stay green

**Interfaces:**
- Consumes: `CLIP_MODELS`, `ClipModel`, `snap_duration` (Task 1); `QUALITY_TIERS`, `TIER_MODELS` (Task 2); `HANDLE` from `app/cin/shot_plan.py`; `WORDS_PER_SECOND`, `DURATION_SECONDS`, `SCENE_RANGE`, `word_budget` from `app/script_quality.py`; `SegmentRequest.requested_len`.
- Produces (used by Tasks 4–5):
  - `app/cost_tracker.py`: `unit_costs() -> dict`, `unit_clip_cost(model: str, seconds: float, pricing: Optional[dict] = None) -> float` (`ValueError` "No clip pricing for model ..." when missing)
  - `app/cin/cost_estimate.py`:
    - `class CostCapError(RuntimeError)`
    - `@dataclass CostEstimate(stage, clips, images, tts, llm, spent, total, model, clip_seconds)` with `to_json() -> dict`
    - `llm_cost_item() -> str` (`"openai_gpt4o"` | `"claude_cli"`), `tts_cost_item() -> Optional[str]`, `tts_units(chars: int) -> int`, `llm_calls(revision: Optional[str]) -> int`
    - `stage_costs(*, narration_chars: int, image_count: int, mock_images: bool, llm_calls: int, rates: Optional[dict] = None) -> dict` → `{"tts", "images", "llm"}`
    - `motion_estimate(*, words: int, scene_count: int, model: ClipModel, pricing: Optional[dict] = None) -> tuple[float, float]` (USD, seconds)
    - `estimate_pre_tts(*, words: int, scene_count: int, model: ClipModel, motion_on: bool, costs: dict, pricing=None) -> CostEstimate`
    - `estimate_pre_clips(requests_: list, *, model: ClipModel, motion_on: bool, costs: dict, pricing=None) -> CostEstimate`
    - `exceeds_cap(total: float, max_cost: float) -> bool`
    - `tier_estimates(custom_model: Optional[str] = None, pricing=None) -> dict` → `{tier: {"model", "short", "medium", "long"} | None}`
    - `clip_model_options(pricing=None) -> list[dict]` → `[{"key", "label", "price_text"}]` (fal models)
    - re-export `unit_clip_cost`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cost_estimate.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cost_estimate.py -q -p no:cacheprovider`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'app.cin.cost_estimate'`.

- [ ] **Step 3: Make the unit rates module-level in the cost tracker**

In `app/cost_tracker.py`, find

```python
# Serialises load-modify-save across tracker instances in this process (concurrent runs).
_LOCK = threading.Lock()
```

and replace it with

```python
# Serialises load-modify-save across tracker instances in this process (concurrent runs).
_LOCK = threading.Lock()


def unit_costs() -> dict:
    """USD per unit of every non-clip cost item, read from settings at call time."""
    return {
        "flux_image": settings.cost_flux_image,
        "elevenlabs_tts": settings.cost_elevenlabs_per_1k_chars,
        "openai_gpt4o": settings.cost_openai_gpt4o,
        "openai_tts": settings.cost_openai_tts_per_1k_chars,
        "whisper": 0.00,
        "local_image": settings.cost_local_image,       # $0.00
        "local_video": settings.cost_local_video,       # $0.00
        "claude_cli": settings.cost_claude_cli,         # $0.00
    }


def unit_clip_cost(model: str, seconds: float, pricing: Optional[dict] = None) -> float:
    """USD for one clip of `seconds` from settings.clip_pricing (or `pricing`). Unknown model -> ValueError."""
    pricing = settings.clip_pricing if pricing is None else pricing
    price = pricing.get(model)
    if price is None:
        raise ValueError(f"No clip pricing for model {model!r}. Known: {sorted(pricing)}")
    if "per_second" in price:
        return round(float(price["per_second"]) * float(seconds), 4)
    return float(price.get("per_clip", 0.0))
```

In `app/cost_tracker.py::CostTracker`, find

```python
    @property
    def unit_costs(self) -> dict:
        return {
            "flux_image": settings.cost_flux_image,
            "elevenlabs_tts": settings.cost_elevenlabs_per_1k_chars,
            "openai_gpt4o": settings.cost_openai_gpt4o,
            "openai_tts": settings.cost_openai_tts_per_1k_chars,
            "whisper": 0.00,
            "local_image": settings.cost_local_image,       # $0.00
            "local_video": settings.cost_local_video,       # $0.00
            "claude_cli": settings.cost_claude_cli,         # $0.00
        }
```

and replace it with

```python
    @property
    def unit_costs(self) -> dict:
        return unit_costs()
```

In `app/cost_tracker.py::CostTracker`, find

```python
    def clip_unit_cost(self, model: str, seconds: float) -> float:
        price = settings.clip_pricing.get(model)
        if price is None:
            raise ValueError(f"No clip pricing for model {model!r}. Known: {sorted(settings.clip_pricing)}")
        if "per_second" in price:
            return round(float(price["per_second"]) * float(seconds), 4)
        return float(price.get("per_clip", 0.0))
```

and replace it with

```python
    def clip_unit_cost(self, model: str, seconds: float) -> float:
        return unit_clip_cost(model, seconds)
```

(Inside the `unit_costs` property, the bare name `unit_costs()` resolves to the module function: a class body is not an enclosing scope.)

- [ ] **Step 4: Create the estimate module**

Create `app/cin/cost_estimate.py`:

```python
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
from app.motion_gen import CLIP_MODELS, ClipModel, snap_duration
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


def llm_cost_item() -> str:
    """Cost-log item of one script LLM call: OpenAI is billed, the claude CLI is $0 (spec §4.7)."""
    return "openai_gpt4o" if settings.llm_provider == "openai" else "claude_cli"


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
    """Script LLM calls: the draft, plus the length revision when one was attempted."""
    return 1 if revision in (None, "", "not_needed") else 2


def stage_costs(*, narration_chars: int, image_count: int, mock_images: bool, llm_calls: int,
                rates: Optional[dict] = None) -> dict:
    """USD of TTS, images and the script LLM calls, with the rules main._log_costs logs."""
    rates = unit_costs() if rates is None else rates
    tts_item = tts_cost_item()
    return {
        "tts": round(tts_units(narration_chars) * rates[tts_item], 4) if tts_item else 0.0,
        "images": 0.0 if mock_images else round(image_count * rates["flux_image"], 4),
        "llm": round(llm_calls * rates[llm_cost_item()], 4),
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
        for preset in DURATION_SECONDS:
            lo, hi = SCENE_RANGE[preset]
            row[preset] = motion_estimate(words=word_budget(preset).target, scene_count=(lo + hi) // 2,
                                          model=model, pricing=pricing)[0]
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
```

Worked numbers the tests pin (list prices): a medium script is 117 words / 2.6 = 45 s over 10 scenes, 4.5 s + 0.5 s handle = 5 s per clip: Standard 10 × 5 s × $0.084 = $4.20, Premium 10 × 5 s × $0.112 = $5.60, hailuo 10 × $0.50 = $5.00, H3 Turbo 10 × 5 s × $0.04 = $2.00. Short (78 words, 7 scenes): 4.79 s → 5 s. Long (156 words, 12 scenes): 5.5 s → 6 s.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cost_estimate.py tests/test_cost_tracker.py tests/test_tiers.py -q -p no:cacheprovider`
Expected: PASS (0 failed).

Run: `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_tiers.py tests/test_cost_estimate.py -q -p no:cacheprovider`
Expected: PASS (0 failed) — the reload in `test_motion_gen.py` does not disturb the `.key` comparisons.

- [ ] **Step 6: Commit**

```bash
git add app/cost_tracker.py app/cin/cost_estimate.py tests/test_cost_estimate.py
git commit -m "feat: pre-TTS / pre-clips cost estimates, cap rule and tier estimates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Pipeline wiring — tier, checkpoints, report fields, revision logging

**Files:**
- Modify: `app/cin/report.py` (`WARNING_CODES`)
- Modify: `main.py` (imports, new `_cost_checkpoint`, `_run_shot_editor`, `_log_costs`, `run_pipeline`)
- Test: `tests/test_pipeline.py` (fixture + new tests), `tests/test_cin_report.py`

**Interfaces:**
- Consumes: `resolve_clip_model`, `QUALITY_TIERS` (Task 2); `CostCapError`, `estimate_pre_tts`, `estimate_pre_clips`, `exceeds_cap`, `stage_costs`, `llm_calls`, `llm_cost_item`, `tts_cost_item`, `tts_units` (Task 3); `CLASSIC_CLIP_SECONDS`, `clip_model_for` (Task 1); `settings.quality_tier`, `settings.max_cost_per_video` (Task 2).
- Produces (used by Task 5):
  - `run_pipeline(..., quality_tier: Optional[str] = None, max_cost: Optional[float] = None) -> str` — `None` = Settings default; unknown tier, negative / NaN / infinite / non-numeric / bool cap, or an unknown custom model raise `ValueError` before the job folder exists
  - `main.CostCapError` (imported name) raised at `pre_tts` (before TTS) or `pre_clips` (before the first clip)
  - `run_report.json`: `options.quality_tier`, `options.clip_model`, `options.max_cost`; `cost = {"estimated": {"pre_tts": {...}, "pre_clips": {...}} | None (classic), "cap": float, "actual": [...], "total": float}`; warnings `cost_cap_exceeded` (`detail: {stage, estimate, cap}`) and `tier_ignored`
  - `_run_shot_editor(job, script, narration, duration, options, report, asset_manager, use_mock_images, motion_on, model, max_cost=0.0, llm_n=1)`
  - `_log_costs(..., llm_n: int = 1)`

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline.py`, find

```python
from app.config import settings
```

and replace it with

```python
from app.config import Settings, settings
```

In the `offline` fixture of `tests/test_pipeline.py`, find

```python
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_video_model", "hailuo")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
```

and replace it with

```python
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_video_model", "hailuo")
    monkeypatch.setattr(settings, "quality_tier", "custom")        # = fal_video_model (hailuo)
    monkeypatch.setattr(settings, "max_cost_per_video", 0.0)
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(settings, "clip_pricing", Settings(_env_file=None).clip_pricing)
    monkeypatch.setattr(settings, "cost_flux_image", 0.03)
    monkeypatch.setattr(settings, "cost_elevenlabs_per_1k_chars", 0.01)
    monkeypatch.setattr(settings, "cost_openai_gpt4o", 0.005)
    monkeypatch.setattr(settings, "cost_claude_cli", 0.0)
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
```

The fixture pins the custom tier (hailuo) so the existing tests keep their hailuo segment counts (`test_strict_mode_fails_before_render_on_still_fallback` asserts 3 hailuo segments; the Standard tier would plan 2 Kling segments), and it pins the provider and prices a developer `.env` could override.

Append to the end of `tests/test_pipeline.py`:

```python



# ---------------------------------------------------------------- quality tiers (spec 2026-10-03 §8)
# Gold fixture: 24 words, 2 scenes, 8.0 s narration (scene 1 starts at 2.32 s).

def _real_images(monkeypatch):
    """use_mock_images=False (motion on, images priced) but the image files are drawn locally."""
    original = AssetManager.generate_images
    monkeypatch.setattr(AssetManager, "generate_images",
                        lambda self, prompts, use_mock=True, output_dir=None: original(self, prompts, True, output_dir))


def _clip_calls(monkeypatch, make=False):
    """Replace the motion generator. make=True writes a real tiny clip, else every clip fails."""
    from tests.conftest import make_test_clip
    calls = []

    def generate_clip(self, image_path, prompt, output_path, duration=None, model_key=None):
        calls.append((model_key, duration))
        return str(make_test_clip(output_path, duration)) if make else None

    monkeypatch.setattr("app.motion_gen.MotionGenerator.generate_clip", generate_clip)
    return calls


def test_cap_below_pre_tts_estimate_stops_before_tts(offline, monkeypatch):
    """hailuo pre_tts: 24 words / 2.6 = 9.23 s -> 2 scenes of 5.1 s -> 2 clips $1.00 + 2 images $0.06."""
    _real_images(monkeypatch)
    tts_calls = []
    monkeypatch.setattr(AssetManager, "generate_audio", lambda *a, **k: tts_calls.append(1))
    with pytest.raises(main.CostCapError, match="before text-to-speech") as info:
        main.run_pipeline("Gold facts", max_cost=1.0)
    job = only_job(offline.out)
    assert tts_calls == [] and info.value.job_dir == str(job)
    rep = report_of(job)
    assert rep["status"] == "failed" and rep["error"].startswith("CostCapError")
    cap = [w for w in rep["warnings"] if w["code"] == "cost_cap_exceeded"]
    assert cap == [{"code": "cost_cap_exceeded", "message": cap[0]["message"],
                    "detail": {"stage": "pre_tts", "estimate": 1.06, "cap": 1.0}}]
    assert rep["cost"]["estimated"] == {"pre_tts": {
        "stage": "pre_tts", "clips": 1.0, "images": 0.06, "tts": 0.0, "llm": 0.0, "spent": 0.0,
        "total": 1.06, "model": "hailuo", "clip_seconds": 12.0}}
    assert rep["cost"]["cap"] == 1.0


def test_cap_between_estimates_stops_before_any_clip(offline, monkeypatch):
    """pre_tts $1.06 passes a $1.30 cap; the real alignment needs 3 hailuo clips (scene 1 is 6.18 s),
    so pre_clips is $1.56 and the run stops before the first clip, keeping the job folder."""
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch)
    rendered = []
    monkeypatch.setattr(main, "render_job", lambda *a: rendered.append(1) or fake_render(*a))
    with pytest.raises(main.CostCapError, match="kept in") as info:
        main.run_pipeline("Gold facts", max_cost=1.3)
    job = only_job(offline.out)
    assert calls == [] and rendered == [] and str(job) in str(info.value)
    assert (job / "sources/narration.mp3").exists() and (job / "sources/images/scene00.png").exists()
    rep = report_of(job)
    assert rep["status"] == "failed"
    assert rep["cost"]["estimated"]["pre_tts"]["total"] == 1.06
    assert rep["cost"]["estimated"]["pre_clips"] == {
        "stage": "pre_clips", "clips": 1.5, "images": 0.06, "tts": 0.0, "llm": 0.0, "spent": 0.06,
        "total": 1.56, "model": "hailuo", "clip_seconds": 18.0}
    assert [w["detail"]["stage"] for w in rep["warnings"] if w["code"] == "cost_cap_exceeded"] == ["pre_clips"]


def test_cap_equal_to_the_estimate_is_not_exceeded(offline, monkeypatch):
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch)                 # every clip fails -> still fallback, not strict
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", max_cost=1.56)
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok" and len(calls) == 6          # 3 segments x (try + retry)
    assert "cost_cap_exceeded" not in [w["code"] for w in rep["warnings"]]


def test_no_cap_run_logs_exactly_the_pre_clips_estimate(offline, monkeypatch):
    """Standard tier (Kling v3): scene 0 2.32 s + 0.5 -> 3 s, scene 1 5.68 s + 0.5 -> 7 s = 10 s x $0.084.
    OpenAI LLM with a failed revision = 2 calls; ElevenLabs TTS = 1 unit. Every clip succeeds."""
    monkeypatch.setattr(settings, "quality_tier", "standard")
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch, make=True)
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts")
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok" and sorted(calls) == [("kling", 3.0), ("kling", 7.0)]
    est = rep["cost"]["estimated"]
    assert set(est) == {"pre_tts", "pre_clips"} and rep["cost"]["cap"] == 0.0
    assert est["pre_clips"] == {"stage": "pre_clips", "clips": 0.84, "images": 0.06, "tts": 0.01, "llm": 0.01,
                                "spent": 0.08, "total": 0.92, "model": "kling", "clip_seconds": 10.0}
    assert round(est["pre_clips"]["spent"] + est["pre_clips"]["clips"], 4) == rep["cost"]["total"] == 0.92
    assert [i["item"] for i in rep["cost"]["actual"]].count("openai_gpt4o") == 2
    assert rep["options"]["quality_tier"] == "standard" and rep["options"]["clip_model"] == "kling"
    assert rep["options"]["max_cost"] == 0.0


def test_claude_cli_script_is_logged_at_zero(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    rep = report_of(only_job(offline.out))
    assert [(i["item"], i["cost"]) for i in rep["cost"]["actual"]] == [("claude_cli", 0.0), ("claude_cli", 0.0)]
    assert rep["cost"]["total"] == 0.0


def test_explicit_tier_with_mock_images_warns_tier_ignored(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True, quality_tier="premium")
    rep = report_of(only_job(offline.out))
    assert "tier_ignored" in [w["code"] for w in rep["warnings"]]
    assert rep["options"]["quality_tier"] == "premium" and rep["options"]["clip_model"] == "kling-pro"
    assert rep["cost"]["estimated"]["pre_tts"]["clips"] == 0.0


def test_settings_default_tier_never_warns(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    assert "tier_ignored" not in [w["code"] for w in report_of(only_job(offline.out))["warnings"]]


@pytest.mark.parametrize("provider, model", [("local", "local"), ("replicate", "replicate-minimax")])
def test_tier_has_no_effect_on_local_or_replicate_motion(offline, monkeypatch, provider, model):
    _real_images(monkeypatch)
    calls = _clip_calls(monkeypatch)
    monkeypatch.setattr(settings, "motion_provider", provider)
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", quality_tier="premium")
    rep = report_of(only_job(offline.out))
    assert rep["options"]["clip_model"] == model and {key for key, _ in calls} == {model}
    assert "tier_ignored" in [w["code"] for w in rep["warnings"]]


def test_classic_run_records_its_model_without_estimates(offline, monkeypatch):
    def fake_assemble(self, **kwargs):
        path = self.output_dir / kwargs["output_filename"]
        path.write_bytes(b"classic")
        return str(path)

    monkeypatch.setattr(main.VideoEditor, "assemble_video", fake_assemble)
    main.run_pipeline("Gold facts", use_mock_images=True, classic=True, quality_tier="standard", max_cost=0.01)
    rep = report_of(only_job(offline.out))
    assert rep["status"] == "ok" and rep["options"]["clip_model"] == "hailuo"
    assert rep["cost"]["estimated"] is None and rep["cost"]["cap"] == 0.01
    assert "tier_ignored" in [w["code"] for w in rep["warnings"]]


@pytest.mark.parametrize("kwargs", [{"quality_tier": "gold"}, {"max_cost": -1}, {"max_cost": float("nan")},
                                    {"max_cost": float("inf")}, {"max_cost": "abc"}, {"max_cost": True}])
def test_bad_tier_or_cap_rejected_before_any_work(offline, kwargs):
    with pytest.raises(ValueError):
        main.run_pipeline("Gold facts", use_mock_images=True, **kwargs)
    assert not offline.out.exists() or not any(offline.out.iterdir())


@pytest.mark.parametrize("model", ["sora", "local"])
def test_unknown_custom_model_rejected_before_any_work(offline, monkeypatch, model):
    monkeypatch.setattr(settings, "fal_video_model", model)
    with pytest.raises(ValueError, match="h3-turbo"):
        main.run_pipeline("Gold facts", quality_tier="custom")
    assert not offline.out.exists() or not any(offline.out.iterdir())


def test_settings_cap_applies_when_no_cap_is_passed(offline, monkeypatch):
    _real_images(monkeypatch)
    monkeypatch.setattr(settings, "max_cost_per_video", 0.5)
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts")
    assert report_of(only_job(offline.out))["cost"]["cap"] == 0.5
    with pytest.raises(main.CostCapError):
        main.run_pipeline("Gold facts", max_cost=None)
```

Append to the end of `tests/test_cin_report.py`:

```python


def test_quality_tier_warning_codes_registered_and_never_carried():
    from app.cin.editor import _CARRIED_WARNINGS
    from app.cin.report import WARNING_CODES
    assert {"cost_cap_exceeded", "tier_ignored"} <= set(WARNING_CODES)
    assert not {"cost_cap_exceeded", "tier_ignored"} & set(_CARRIED_WARNINGS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_cin_report.py -q -p no:cacheprovider -m "not render"`
Expected: FAIL — `AttributeError: module 'main' has no attribute 'CostCapError'`, `TypeError: run_pipeline() got an unexpected keyword argument 'max_cost'` / `'quality_tier'`, the old `[("openai_gpt4o", 0.005)]` cost items, and the missing warning codes. The existing pipeline tests still pass with the new fixture.

- [ ] **Step 3: Register the warning codes**

In `app/cin/report.py`, find

```python
    "plan_save_failed", "script_length_off_target", "scene_roles_derived", "hook_headline_fallback",
)
```

and replace it with

```python
    "plan_save_failed", "script_length_off_target", "scene_roles_derived", "hook_headline_fallback",
    "cost_cap_exceeded", "tier_ignored",      # quality tiers (spec 2026-10-03 §8); never carried by --rerender
)
```

`app/cin/editor.py::_CARRIED_WARNINGS` stays unchanged (a re-render costs nothing).

- [ ] **Step 4: Imports in `main.py`**

In `main.py`, find

```python
import argparse
import json
import logging
import sys
```

and replace it with

```python
import argparse
import json
import logging
import math
import sys
```

In `main.py`, find

```python
from app.motion_gen import MotionGenerator, clip_model_for, snap_duration
```

and replace it with

```python
from app.motion_gen import CLASSIC_CLIP_SECONDS, MotionGenerator, clip_model_for, snap_duration
```

In `main.py`, find

```python
from app.cin.music_library import MOODS, MUSIC_SOURCES
```

and replace it with

```python
from app.cin.music_library import MOODS, MUSIC_SOURCES
from app.cin.cost_estimate import (CostCapError, estimate_pre_clips, estimate_pre_tts, exceeds_cap, llm_calls,
                                   llm_cost_item, stage_costs, tts_cost_item, tts_units)
from app.cin.tiers import QUALITY_TIERS, resolve_clip_model
```

(`tests/test_cli.py::test_main_module_has_no_unused_imports_or_dead_helpers` requires every imported name to be used; Steps 5–7 use all of them.)

- [ ] **Step 5: Checkpoint 2 in the shot editor**

In `main.py`, find

```python
def _run_shot_editor(job, script, narration: str, duration: float, options: RenderOptions,
                     report: RunReport, asset_manager: AssetManager, use_mock_images: bool,
                     motion_on: bool):
    """Spec §4 order: (align || images) -> segments -> clips -> shot plan -> render + encode."""
    model = clip_model_for(settings.motion_provider, settings.fal_video_model)

```

and replace it with

```python
def _cost_checkpoint(report: RunReport, estimate, max_cost: float, job) -> None:
    """Store an estimate in run_report.json; over the cap -> cost_cap_exceeded + CostCapError, before
    the next paid stage. Never degrades to stills or a cheaper model (spec 2026-10-03 §4.5, §8)."""
    report.cost["estimated"][estimate.stage] = estimate.to_json()
    logger.info("Cost estimate (%s): $%.2f total, $%.2f motion (%s)", estimate.stage, estimate.total,
                estimate.clips, estimate.model)
    if not exceeds_cap(estimate.total, max_cost):
        return
    report.warn("cost_cap_exceeded",
                f"Estimated cost ${estimate.total:.2f} exceeds the ${max_cost:.2f} cap at {estimate.stage}",
                {"stage": estimate.stage, "estimate": estimate.total, "cap": max_cost})
    if estimate.stage == "pre_tts":
        where = "stopped before text-to-speech; only the script was generated"
    else:
        where = f"stopped before the motion clips; script, narration and images are kept in {job.root}"
    raise CostCapError(f"Estimated cost ${estimate.total:.2f} exceeds the ${max_cost:.2f} per-video cap "
                       f"({estimate.stage}, model {estimate.model}): {where}")


def _run_shot_editor(job, script, narration: str, duration: float, options: RenderOptions,
                     report: RunReport, asset_manager: AssetManager, use_mock_images: bool,
                     motion_on: bool, model, max_cost: float = 0.0, llm_n: int = 1):
    """Spec §4 order: (align || images) -> segments -> cost checkpoint 2 -> clips -> shot plan ->
    render + encode. model is the run's resolved ClipModel (app.cin.tiers.resolve_clip_model)."""
```

In `main.py::_run_shot_editor`, find

```python
    requests_ = plan_segments(alignment, model.durations if motion_on else None)
    with report.stage("clips"):
```

and replace it with

```python
    requests_ = plan_segments(alignment, model.durations if motion_on else None)
    costs = stage_costs(narration_chars=len(narration), image_count=len(image_paths),
                        mock_images=use_mock_images, llm_calls=llm_n)
    _cost_checkpoint(report, estimate_pre_clips(requests_, model=model, motion_on=motion_on, costs=costs),
                     max_cost, job)
    with report.stage("clips"):
```

- [ ] **Step 6: Log what the estimate counts**

In `main.py`, find

```python
def _log_costs(video_id: str, report: RunReport, narration: str, use_mock_images: bool,
               image_count: int, specs=None, classic_clips=None) -> float:
    """Cost bookkeeping after a successful render. It must never fail the run (an unknown clip
    model or a cost-file error is logged as a warning and skipped)."""
```

and replace it with

```python
def _log_costs(video_id: str, report: RunReport, narration: str, use_mock_images: bool,
               image_count: int, specs=None, classic_clips=None, llm_n: int = 1) -> float:
    """Cost bookkeeping after a successful render. It must never fail the run (an unknown clip
    model or a cost-file error is logged as a warning and skipped). Units follow
    app.cin.cost_estimate.stage_costs, so the pre_clips estimate and the log agree."""
```

In `main.py::_log_costs`, find

```python
    attempt("gpt4o", lambda: tracker.log_cost(video_id, "openai_gpt4o"))
    if settings.elevenlabs_api_key:
        attempt("tts", lambda: tracker.log_cost(video_id, "elevenlabs_tts", quantity=max(1, len(narration) // 1000)))
    elif settings.openai_api_key:
        attempt("tts", lambda: tracker.log_cost(video_id, "openai_tts", quantity=max(1, len(narration) // 1000)))
```

and replace it with

```python
    llm_item = llm_cost_item()
    for _ in range(llm_n):                       # the draft, plus the length revision when one was attempted
        attempt("llm", lambda: tracker.log_cost(video_id, llm_item))
    tts_item = tts_cost_item()
    if tts_item:
        attempt("tts", lambda: tracker.log_cost(video_id, tts_item, quantity=tts_units(len(narration))))
```

In `main.py::_log_costs`, find

```python
                tracker.log_clip(video_id, model.key, seconds=snap_duration(5.0, model.durations) or 5.0,
                                 count=done)
```

and replace it with

```python
                tracker.log_clip(video_id, model.key, count=done,
                                 seconds=snap_duration(CLASSIC_CLIP_SECONDS, model.durations) or CLASSIC_CLIP_SECONDS)
```

In `main.py::_log_costs`, find

```python
        report.cost = {"estimated": None, "actual": tracker.get_video_items(video_id), "total": total}
```

and replace it with

```python
        report.cost.update({"actual": tracker.get_video_items(video_id), "total": total})   # keeps estimated + cap
```

- [ ] **Step 7: Tier, cap and checkpoint 1 in `run_pipeline`**

In `main.py::run_pipeline`, find

```python
    classic: bool = False,
    music_source: Optional[str] = None,
) -> str:
```

and replace it with

```python
    classic: bool = False,
    music_source: Optional[str] = None,
    # Quality tiers (spec 2026-10-03)
    quality_tier: Optional[str] = None,
    max_cost: Optional[float] = None,
) -> str:
```

In `main.py::run_pipeline` (the docstring), find

```python
    music_source defaults to settings.music_source (mine | generated | any | none).
    """
```

and replace it with

```python
    music_source defaults to settings.music_source (mine | generated | any | none).
    quality_tier (standard | premium | custom) picks the motion model; max_cost (USD, 0 = no cap)
    stops the run with CostCapError at a cost checkpoint. Both default to the Settings values.
    """
```

In `main.py::run_pipeline`, find

```python
    classic = classic or not settings.cinematic_enabled or bool(persona)
    motion_on = enable_motion and not use_mock_images
```

and replace it with

```python
    tier_explicit = bool(quality_tier)
    quality_tier = quality_tier or settings.quality_tier
    if quality_tier not in QUALITY_TIERS:
        raise ValueError(f"Unknown quality_tier {quality_tier!r}; choose one of {', '.join(QUALITY_TIERS)}")
    max_cost = settings.max_cost_per_video if max_cost is None else max_cost
    if isinstance(max_cost, bool) or not isinstance(max_cost, (int, float)) \
            or not math.isfinite(max_cost) or max_cost < 0:
        raise ValueError(f"max_cost must be a number >= 0 (0 = no cap), got {max_cost!r}")
    max_cost = float(max_cost)
    classic = classic or not settings.cinematic_enabled or bool(persona)
    motion_on = enable_motion and not use_mock_images
    # Classic / persona runs keep settings.fal_video_model and have no cost checkpoints (spec §8.7).
    model = clip_model_for(settings.motion_provider, settings.fal_video_model) if classic else \
        resolve_clip_model(quality_tier, settings.motion_provider, settings.fal_video_model)
```

In `main.py::run_pipeline`, find

```python
        "use_mock_images": use_mock_images, "classic": classic,
    })
    logger.info(f"Job folder: {job.root}")
```

and replace it with

```python
        "use_mock_images": use_mock_images, "classic": classic,
        "quality_tier": quality_tier, "clip_model": model.key, "max_cost": max_cost,
    })
    report.cost = {"estimated": None if classic else {}, "cap": max_cost, "actual": [], "total": 0.0}
    if tier_explicit and (classic or not motion_on or settings.motion_provider in ("local", "replicate")):
        report.warn("tier_ignored",
                    f"Quality tier {quality_tier!r} has no effect on this run (motion {model.key}); "
                    "tiers apply to fal motion clips in the shot editor only",
                    {"quality_tier": quality_tier, "clip_model": model.key, "classic": classic,
                     "motion": motion_on, "motion_provider": settings.motion_provider})
    logger.info(f"Job folder: {job.root}")
```

In `main.py::run_pipeline`, find

```python
        options.subtitle_style = resolve_subtitle_style(subtitle_style, video_style)
        report.options["subtitle_style"] = options.subtitle_style
        _print_script(script)

        logger.info("Generating audio narration...")
        asset_manager = AssetManager(video_style=options.video_style)
        full_narration = f"{script.hook} {script.body}"
        with report.stage("tts"):
```

and replace it with

```python
        options.subtitle_style = resolve_subtitle_style(subtitle_style, video_style)
        report.options["subtitle_style"] = options.subtitle_style
        _print_script(script)
        full_narration = f"{script.hook} {script.body}"
        llm_n = llm_calls(report.script.get("revision"))
        if not classic:          # checkpoint 1: nothing but the script is paid yet (spec 2026-10-03 §8.2)
            costs = stage_costs(narration_chars=len(full_narration), image_count=len(script.image_prompts),
                                mock_images=use_mock_images, llm_calls=llm_n)
            _cost_checkpoint(report, estimate_pre_tts(
                words=report.script.get("words") or 0, scene_count=len(script.image_prompts), model=model,
                motion_on=motion_on, costs=costs), max_cost, job)

        logger.info("Generating audio narration...")
        asset_manager = AssetManager(video_style=options.video_style)
        with report.stage("tts"):
```

In `main.py::run_pipeline`, find

```python
            output_path, image_paths, specs = _run_shot_editor(
                job, script, full_narration, audio_result.duration, options, report, asset_manager,
                use_mock_images, motion_on)
```

and replace it with

```python
            output_path, image_paths, specs = _run_shot_editor(
                job, script, full_narration, audio_result.duration, options, report, asset_manager,
                use_mock_images, motion_on, model, max_cost=max_cost, llm_n=llm_n)
```

In `main.py::run_pipeline`, find

```python
        _log_costs(video_id, report, full_narration, use_mock_images, len(image_paths), specs, classic_clips)
```

and replace it with

```python
        _log_costs(video_id, report, full_narration, use_mock_images, len(image_paths), specs, classic_clips,
                   llm_n=llm_n)
```

`CostCapError` needs no special handling: the existing `except Exception` block records it like any failed run (`status: failed`, `error: "CostCapError: ..."`, warnings kept, `job_dir` tagged), and the web / scheduler payloads read it through `load_summary`.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_cin_report.py tests/test_cli.py tests/test_rerender.py -q -p no:cacheprovider -m "not render"`
Expected: PASS (0 failed).

- [ ] **Step 9: Commit**

```bash
git add main.py app/cin/report.py tests/test_pipeline.py tests/test_cin_report.py
git commit -m "feat: quality tier and cost cap in run_pipeline (pre-TTS and pre-clips checkpoints)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Options plumbing — CLI, run_options, web request, worker, config API

**Files:**
- Modify: `app/run_options.py` (`TIER_CHOICES`, `to_max_cost`, `pipeline_kwargs`, `clean_settings_updates`)
- Modify: `main.py` (`_max_cost_arg`, `--tier`, `--max-cost`, `run_auto_mode`, `run_interactive_mode`)
- Modify: `app/web/routes/api_generate.py`, `app/generator_worker.py`, `app/web/routes/api_config.py`
- Test: `tests/test_run_options.py`, `tests/test_generator_worker.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `QUALITY_TIERS` (Task 2); `clip_model_options`, `tier_estimates` (Task 3); `run_pipeline(quality_tier=, max_cost=)` (Task 4).
- Produces (used by Task 6):
  - `app/run_options.py`: `TIER_CHOICES`, `to_max_cost(name: str, value: Any, default: Optional[float]) -> Optional[float]` (raises `OptionError`); `pipeline_kwargs(...)` adds `"quality_tier": Optional[str]` and `"max_cost": Optional[float]`; `clean_settings_updates` validates `quality_tier` and `max_cost_per_video`
  - CLI: `--tier {standard,premium,custom}`, `--max-cost USD` (both default `None` = Settings)
  - `POST /api/generate` body: `quality_tier: Optional[str]`, `max_cost: Optional[float | str]` (blank / null = Settings default)
  - `GeneratorWorker.start(..., quality_tier=None, max_cost=None)`
  - `GET /api/config` adds `quality_tier`, `max_cost_per_video`, `clip_models` (`[{key, label, price_text}]`) and `tier_estimates` (`{tier: {"model", "short", "medium", "long"} | null}`)
  - Scheduler slots: no code change — `app/scheduler.py` and `app/web/routes/api_scheduler.py` already pass slot config through `pipeline_kwargs`, so `quality_tier` / `max_cost` keys are validated at save time (HTTP 422) and applied at run time.

- [ ] **Step 1: Write the failing tests**

In `tests/test_run_options.py`, find

```python
from app.run_options import (MUSIC_SOURCE_CHOICES, PACING_CHOICES, OptionError, apply_saved_settings,
                             apply_settings_updates, clean_settings_updates, load_config_file,
                             pipeline_kwargs, to_bool, validate_settings_updates)
```

and replace it with

```python
from app.run_options import (MUSIC_SOURCE_CHOICES, PACING_CHOICES, TIER_CHOICES, OptionError, apply_saved_settings,
                             apply_settings_updates, clean_settings_updates, load_config_file,
                             pipeline_kwargs, to_bool, to_max_cost, validate_settings_updates)
```

In `tests/test_run_options.py::test_empty_config_means_settings_defaults`, find

```python
                  "niche": None, "video_style": "", "video_duration": "",
                  "pacing": None, "music_source": None, "strict": None}
```

and replace it with

```python
                  "niche": None, "video_style": "", "video_duration": "",
                  "pacing": None, "music_source": None, "strict": None,
                  "quality_tier": None, "max_cost": None}
```

Append to the end of `tests/test_run_options.py`:

```python



# ---------------------------------------------------------------- quality tiers (spec 2026-10-03 §9)

def test_tier_choices():
    assert TIER_CHOICES == ("standard", "premium", "custom")


@pytest.mark.parametrize("value, expected", [("", None), (None, None), ("  ", None), ("premium", "premium"),
                                             (" Custom ", "custom"), ("STANDARD", "standard")])
def test_quality_tier_option(value, expected):
    assert pipeline_kwargs({"quality_tier": value})["quality_tier"] == expected


@pytest.mark.parametrize("value", ["gold", 2, True])
def test_unknown_quality_tier_rejected(value):
    with pytest.raises(OptionError, match="choose one of standard, premium, custom"):
        pipeline_kwargs({"quality_tier": value})


@pytest.mark.parametrize("value, expected", [("", None), (None, None), (" ", None), ("0", 0.0), (0, 0.0),
                                             ("4.5", 4.5), (" 4.5 ", 4.5), (3, 3.0), (2.25, 2.25)])
def test_max_cost_option(value, expected):
    assert pipeline_kwargs({"max_cost": value})["max_cost"] == expected


@pytest.mark.parametrize("value", ["-1", -0.01, "abc", "nan", "inf", float("nan"), float("inf"), True, [], {}])
def test_bad_max_cost_rejected(value):
    with pytest.raises(OptionError, match=">= 0"):
        pipeline_kwargs({"max_cost": value})


def test_to_max_cost_default_for_blank():
    assert to_max_cost("max_cost", "", 2.0) == 2.0


def test_settings_update_cleaning_for_tier_and_cap():
    out = clean_settings_updates({"quality_tier": "Premium", "max_cost_per_video": "4.5"})
    assert out == {"quality_tier": "premium", "max_cost_per_video": 4.5}
    assert clean_settings_updates({"max_cost_per_video": 0})["max_cost_per_video"] == 0.0
    for bad in ({"quality_tier": "gold"}, {"quality_tier": ""}, {"max_cost_per_video": ""},
                {"max_cost_per_video": "-1"}, {"max_cost_per_video": "abc"}, {"max_cost_per_video": "nan"}):
        with pytest.raises(OptionError):
            clean_settings_updates(bad)


def test_saved_tier_and_cap_applied_and_bad_ones_skipped():
    s = Settings(_env_file=None)
    assert sorted(apply_saved_settings(s, {"quality_tier": "premium", "max_cost_per_video": "3"})) == [
        "max_cost_per_video", "quality_tier"]
    assert s.quality_tier == "premium" and s.max_cost_per_video == 3.0
    assert apply_saved_settings(s, {"quality_tier": "gold", "max_cost_per_video": -2}) == []
    assert s.quality_tier == "premium" and s.max_cost_per_video == 3.0
```

Append to the end of `tests/test_generator_worker.py`:

```python



def test_worker_passes_quality_tier_and_cap():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/j/final.mp4") as mock_pipe:
        w.start(topic="Test", quality_tier="premium", max_cost="4.5")
        w._thread.join()
    kw = mock_pipe.call_args.kwargs
    assert (kw["quality_tier"], kw["max_cost"]) == ("premium", 4.5)


def test_worker_defaults_tier_and_cap_to_settings():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/j/final.mp4") as mock_pipe:
        w.start(topic="Test")
        w._thread.join()
    assert (mock_pipe.call_args.kwargs["quality_tier"], mock_pipe.call_args.kwargs["max_cost"]) == (None, None)


def test_worker_rejects_bad_cap_before_going_busy():
    import pytest
    from app.run_options import OptionError
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline") as mock_pipe:
        with pytest.raises(OptionError):
            w.start(topic="Test", max_cost=-1)
        with pytest.raises(OptionError):
            w.start(topic="Test", quality_tier="gold")
    assert w.status == "idle" and not mock_pipe.called
```

Append to the end of `tests/test_cli.py`:

```python



def test_tier_and_max_cost_flags():
    args = parse_args(["--auto", "--tier", "premium", "--max-cost", "4.5"])
    assert args.tier == "premium" and args.max_cost == 4.5
    assert parse_args(["--max-cost", "0"]).max_cost == 0.0


def test_tier_and_max_cost_default_to_settings():
    args = parse_args([])
    assert args.tier is None and args.max_cost is None


def test_bad_tier_or_max_cost_rejected():
    import pytest
    for argv in (["--tier", "gold"], ["--max-cost", "-1"], ["--max-cost", "abc"], ["--max-cost", "nan"],
                 ["--max-cost", "inf"]):
        with pytest.raises(SystemExit):
            parse_args(argv)


def test_auto_mode_passes_tier_and_cap(monkeypatch):
    import main
    seen = {}
    monkeypatch.setattr(main, "run_pipeline", lambda **kw: seen.update(kw))
    main.run_auto_mode(parse_args(["--auto", "--topic", "Gold", "--tier", "custom", "--max-cost", "3"]))
    assert (seen["quality_tier"], seen["max_cost"]) == ("custom", 3.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_run_options.py tests/test_generator_worker.py tests/test_cli.py -q -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'TIER_CHOICES' from 'app.run_options'` (collection error for `tests/test_run_options.py`), `TypeError: GeneratorWorker.start() got an unexpected keyword argument 'quality_tier'`, and argparse `error: unrecognized arguments: --tier premium --max-cost 4.5` (`SystemExit: 2`).

- [ ] **Step 3: Parse tier and cap in `app/run_options.py`**

In `app/run_options.py`, find

```python
import json
import logging
from pathlib import Path
```

and replace it with

```python
import json
import logging
import math
from pathlib import Path
```

In `app/run_options.py`, find

```python
from app.cin.shot_plan import PACING
from app.config import settings
```

and replace it with

```python
from app.cin.shot_plan import PACING
from app.cin.tiers import QUALITY_TIERS
from app.config import settings
```

In `app/run_options.py`, find

```python
MUSIC_SOURCE_CHOICES = tuple(MUSIC_SOURCES)    # ("mine", "generated", "any", "none"), spec §8.1
```

and replace it with

```python
MUSIC_SOURCE_CHOICES = tuple(MUSIC_SOURCES)    # ("mine", "generated", "any", "none"), spec §8.1
TIER_CHOICES = QUALITY_TIERS                   # ("standard", "premium", "custom"), spec 2026-10-03 §4
```

In `app/run_options.py`, find

```python
def pipeline_kwargs(config: Mapping[str, Any]) -> dict:
```

and replace it with

```python
def to_max_cost(name: str, value: Any, default: Optional[float]) -> Optional[float]:
    """A per-video cap in USD: a number or numeric string >= 0 (0 = no cap); blank -> default.
    Booleans, NaN, infinity, negatives and non-numeric text are rejected."""
    if _blank(value):
        return default
    number = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            number = None
    if number is None or not math.isfinite(number) or number < 0:
        raise OptionError(f"{name} must be a number of USD >= 0 (0 = no cap), got {value!r}")
    return number


def pipeline_kwargs(config: Mapping[str, Any]) -> dict:
```

In `app/run_options.py::pipeline_kwargs`, find

```python
        "strict": to_bool("strict", config.get("strict"), None),
    }
```

and replace it with

```python
        "strict": to_bool("strict", config.get("strict"), None),
        "quality_tier": _choice("quality_tier", config.get("quality_tier"), TIER_CHOICES),
        "max_cost": to_max_cost("max_cost", config.get("max_cost"), None),
    }
```

In `app/run_options.py::clean_settings_updates`, find

```python
    if "strict" in cleaned:
        cleaned["strict"] = to_bool("strict", cleaned["strict"], False)
    return cleaned
```

and replace it with

```python
    if "strict" in cleaned:
        cleaned["strict"] = to_bool("strict", cleaned["strict"], False)
    if "quality_tier" in cleaned:
        if _blank(cleaned["quality_tier"]):
            raise OptionError(f"quality_tier must be one of {', '.join(TIER_CHOICES)}")
        cleaned["quality_tier"] = _choice("quality_tier", cleaned["quality_tier"], TIER_CHOICES)
    if "max_cost_per_video" in cleaned:      # Field(ge=0) is not seen by validate_settings_updates
        if _blank(cleaned["max_cost_per_video"]):
            raise OptionError("max_cost_per_video must be a number of USD >= 0 (0 = no cap)")
        cleaned["max_cost_per_video"] = to_max_cost("max_cost_per_video", cleaned["max_cost_per_video"], None)
    return cleaned
```

- [ ] **Step 4: CLI flags in `main.py`**

In `main.py`, find

```python
def _per_mood(text: str) -> int:
```

and replace it with

```python
def _max_cost_arg(text: str) -> float:
    """--max-cost: USD >= 0 (0 = no cap). float() alone would accept "nan" and "inf"."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--max-cost must be a number of USD, got {text!r}")
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("--max-cost must be >= 0 (0 = no cap)")
    return value


def _per_mood(text: str) -> int:
```

In `main.py::parse_args`, find

```python
    parser.add_argument("--rerender", type=str, default=None, metavar="JOB_DIR",
```

and replace it with

```python
    parser.add_argument("--tier", choices=list(QUALITY_TIERS), default=None,
                        help="Motion quality: standard (Kling v3 Standard), premium (Kling v3 Pro) or "
                             "custom (settings.fal_video_model) (default: settings.quality_tier)")
    parser.add_argument("--max-cost", type=_max_cost_arg, default=None, metavar="USD",
                        help="Stop the run before the next paid stage when its cost estimate exceeds "
                             "this (0 = no cap; default: settings.max_cost_per_video)")
    parser.add_argument("--rerender", type=str, default=None, metavar="JOB_DIR",
```

In `main.py::run_auto_mode`, find

```python
                strict=args.strict,
                classic=args.classic,
                music_source=args.music_source,
            )
        except Exception as e:
            logger.error(f"Failed: {e}")
            continue
```

and replace it with

```python
                strict=args.strict,
                classic=args.classic,
                music_source=args.music_source,
                quality_tier=args.tier,
                max_cost=args.max_cost,
            )
        except Exception as e:
            logger.error(f"Failed: {e}")
            continue
```

In `main.py::run_interactive_mode`, find

```python
            strict=args.strict,
            classic=args.classic,
            music_source=args.music_source,
        )

        print()
```

and replace it with

```python
            strict=args.strict,
            classic=args.classic,
            music_source=args.music_source,
            quality_tier=args.tier,
            max_cost=args.max_cost,
        )

        print()
```

(`--rerender` ignores both flags: a re-render makes no API calls.)

- [ ] **Step 5: Web request, worker and config API**

In `app/web/routes/api_generate.py`, find

```python
import uuid
from typing import Optional
```

and replace it with

```python
import uuid
from typing import Optional, Union
```

In `app/web/routes/api_generate.py::GenerateRequest`, find

```python
    strict: Optional[bool] = None
```

and replace it with

```python
    strict: Optional[bool] = None
    # Quality tiers (spec 2026-10-03 §9). Text is accepted so pipeline_kwargs gives one message for
    # blank ("" = Settings default), negative and non-numeric caps.
    quality_tier: Optional[str] = None      # standard | premium | custom
    max_cost: Optional[Union[float, str]] = None   # USD, 0 = no cap
```

(`generate_video` already calls `pipeline_kwargs(req.model_dump())` and maps `OptionError` to HTTP 422.)

In `app/generator_worker.py::GeneratorWorker.start`, find

```python
              pacing: Optional[str] = None, music_source: Optional[str] = None,
              strict: Optional[bool] = None) -> bool:
        """Start generation. Returns False if already busy. pacing / music_source / strict = None
        use the Settings defaults; an invalid value raises OptionError before the worker goes busy."""
```

and replace it with

```python
              pacing: Optional[str] = None, music_source: Optional[str] = None,
              strict: Optional[bool] = None, quality_tier: Optional[str] = None,
              max_cost: Optional[float] = None) -> bool:
        """Start generation. Returns False if already busy. pacing / music_source / strict /
        quality_tier / max_cost = None use the Settings defaults; an invalid value raises OptionError
        before the worker goes busy."""
```

In `app/generator_worker.py::GeneratorWorker.start`, find

```python
            "pacing": pacing, "music_source": music_source, "strict": strict,
        })
```

and replace it with

```python
            "pacing": pacing, "music_source": music_source, "strict": strict,
            "quality_tier": quality_tier, "max_cost": max_cost,
        })
```

In `app/web/routes/api_config.py`, find

```python
from fastapi import APIRouter, HTTPException
from app.config import settings
```

and replace it with

```python
from fastapi import APIRouter, HTTPException
from app.cin.cost_estimate import clip_model_options, tier_estimates
from app.config import settings
```

In `app/web/routes/api_config.py::get_config`, find

```python
        "strict": settings.strict,
        "enable_motion": settings.enable_motion,
```

and replace it with

```python
        "strict": settings.strict,
        "quality_tier": settings.quality_tier,
        "max_cost_per_video": settings.max_cost_per_video,
        "enable_motion": settings.enable_motion,
```

In `app/web/routes/api_config.py::get_config`, find

```python
    current.update(saved)
    return current
```

and replace it with

```python
    current.update(saved)
    # Derived lists (spec 2026-10-03 §9), never overridden by config.json
    current["clip_models"] = clip_model_options()
    current["tier_estimates"] = tier_estimates(custom_model=settings.fal_video_model)
    return current
```

`PUT /api/config` needs no change: it runs `clean_settings_updates` (Step 3) and maps `OptionError` to HTTP 422; server start applies `data/config.json` through `apply_saved_settings`, which skips a bad saved tier or cap with a warning.

- [ ] **Step 6: Run the tests and compile the routes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_run_options.py tests/test_generator_worker.py tests/test_cli.py tests/test_pipeline.py -q -p no:cacheprovider -m "not render"`
Expected: PASS (0 failed).

Run: `.venv/Scripts/python.exe -m py_compile app/web/routes/api_generate.py app/web/routes/api_config.py app/web/routes/api_scheduler.py app/scheduler.py && echo COMPILED`
Expected: `COMPILED`

Run (the request model's coercion, without FastAPI):

```bash
.venv/Scripts/python.exe -c "
from typing import Optional, Union
from pydantic import BaseModel
from app.run_options import OptionError, pipeline_kwargs
class R(BaseModel):
    quality_tier: Optional[str] = None
    max_cost: Optional[Union[float, str]] = None
for v in [None, '', '0', 4.5, '4.5', -1, 'abc', 'nan']:
    try:
        out = pipeline_kwargs(R(max_cost=v).model_dump())['max_cost']
    except OptionError:
        out = 'OptionError'
    print(repr(v), '->', out)
"
```

Expected:

```
None -> None
'' -> None
'0' -> 0.0
4.5 -> 4.5
'4.5' -> 4.5
-1 -> OptionError
'abc' -> OptionError
'nan' -> OptionError
```

- [ ] **Step 7: Commit**

```bash
git add app/run_options.py main.py app/web/routes/api_generate.py app/generator_worker.py app/web/routes/api_config.py tests/test_run_options.py tests/test_generator_worker.py tests/test_cli.py
git commit -m "feat: quality tier and max cost options for CLI, web, scheduler, worker and Settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Web UI fields, docs and the full-suite check

**Files:**
- Modify: `app/web/static/js/generate.js` (tier select, max-cost input, estimate hint, request body)
- Modify: `app/web/static/js/scheduler.js` (slot tier select, max-cost input, slot config)
- Modify: `app/web/static/js/settings.js` (`fal_video_model` select from `clip_models`, tier default, max cost)
- Modify: `CLAUDE.md` (Commands)
- Test: `node --check` on the three JS files; the full Python suite

**Interfaces:**
- Consumes: `GET /api/config` → `quality_tier`, `max_cost_per_video`, `clip_models`, `tier_estimates` (Task 5); `POST /api/generate` body `quality_tier`, `max_cost` (Task 5); scheduler slot config keys `quality_tier`, `max_cost` (validated by `pipeline_kwargs`, Task 5); `PUT /api/config` keys `quality_tier`, `max_cost_per_video` (validated by `clean_settings_updates`, Task 5).
- Produces: UI only. Rules the JS follows: tier `""` → `null` (Settings default); max cost blank → `null` on the Generate form and scheduler slots (Settings default), `0` on the Settings page (no cap); a non-blank max cost is sent as the typed text so the server rejects bad values (HTTP 422 toast) instead of JavaScript turning them into `NaN` → `null`.

There is no JS test runner in this repo; the JS check is `node --check` plus a manual look in `python main.py --serve` when the user runs the web UI (no paid call is needed to see the fields and the estimate hint: they come from `GET /api/config`).

- [ ] **Step 1: Add the fields to the three pages**

In `app/web/static/js/generate.js` (constants at the top of `GeneratePage`), find

```javascript
  const MUSIC_SOURCES = [
    { id: 'any',       label: 'Any (my tracks + generated)' },
    { id: 'mine',      label: 'My tracks only' },
    { id: 'generated', label: 'Generated library only' },
    { id: 'none',      label: 'No music' },
  ];
```

and replace it with

```javascript
  const MUSIC_SOURCES = [
    { id: 'any',       label: 'Any (my tracks + generated)' },
    { id: 'mine',      label: 'My tracks only' },
    { id: 'generated', label: 'Generated library only' },
    { id: 'none',      label: 'No music' },
  ];
  // Quality tiers (spec 2026-10-03 §9): the motion model per video. "" = the Settings default.
  const TIERS = [
    { id: 'standard', label: 'Standard (Kling v3 Standard)' },
    { id: 'premium',  label: 'Premium (Kling v3 Pro)' },
    { id: 'custom',   label: 'Custom (Settings model)' },
  ];
  let defaults = {};
```

In `app/web/static/js/generate.js::render` (the form), find

```javascript
        <!-- Toggles -->
        <div style="display:flex;gap:var(--space-8);flex-wrap:wrap;margin-bottom:var(--space-5)">
          <div class="toggle toggle--active" id="toggle-motion" onclick="GeneratePage.toggleSwitch('toggle-motion')">
```

and replace it with

```javascript
        <!-- Quality tier + spending cap (spec 2026-10-03 §9) -->
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Quality Tier</label>
            <select class="form-select" id="gen-tier" onchange="GeneratePage.updateTierHint()">
              <option value="">Default</option>
              ${TIERS.map(t => `<option value="${t.id}">${t.label}</option>`).join('')}
            </select>
            <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-1)" id="gen-tier-hint"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Max Cost (USD)</label>
            <input class="form-input" id="gen-max-cost" type="number" min="0" step="0.5" placeholder="Default">
            <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-1)">Stops the run before the next paid stage if the estimate is higher. 0 = no cap.</div>
          </div>
        </div>

        <!-- Toggles -->
        <div style="display:flex;gap:var(--space-8);flex-wrap:wrap;margin-bottom:var(--space-5)">
          <div class="toggle toggle--active" id="toggle-motion" onclick="GeneratePage.toggleSwitch('toggle-motion')">
```

In `app/web/static/js/generate.js::loadDefaults`, find

```javascript
      label('gen-pacing', cfg.pacing);
      label('gen-music-source', cfg.music_source);
      if (cfg.strict === true) document.getElementById('cb-strict')?.classList.add('checkbox--checked');
    } catch (e) {
      // Labels stay "Default"; the server applies the Settings defaults anyway.
    }
    enableStrict();
  }
```

and replace it with

```javascript
      label('gen-pacing', cfg.pacing);
      label('gen-music-source', cfg.music_source);
      label('gen-tier', cfg.quality_tier);
      const cap = document.getElementById('gen-max-cost');
      if (cap) cap.placeholder = cfg.max_cost_per_video > 0 ? `Default ($${cfg.max_cost_per_video})` : 'Default (no cap)';
      if (cfg.strict === true) document.getElementById('cb-strict')?.classList.add('checkbox--checked');
      defaults = cfg;
    } catch (e) {
      // Labels stay "Default"; the server applies the Settings defaults anyway.
    }
    enableStrict();
    updateTierHint();
  }

  // "≈ $X of motion for a medium video" from /api/config tier_estimates (list prices, estimate only).
  function updateTierHint() {
    const hint = document.getElementById('gen-tier-hint');
    if (!hint) return;
    const tier = document.getElementById('gen-tier')?.value || defaults.quality_tier || 'standard';
    const dur = getSelectedDuration();
    const est = (defaults.tier_estimates || {})[tier];
    if (est && typeof est[dur] === 'number') {
      hint.textContent = `≈ $${est[dur].toFixed(2)} of motion for a ${dur} video (${est.model}, list-price estimate)`;
    } else if (tier === 'custom' && defaults.tier_estimates) {
      hint.textContent = 'Custom uses the fal.ai video model from Settings, which is not a known model.';
    } else {
      hint.textContent = '';
    }
  }
```

In `app/web/static/js/generate.js::selectDuration`, find

```javascript
  function selectDuration(durId) {
    document.querySelectorAll('#duration-grid .style-card').forEach(c => c.classList.remove('style-card--selected'));
    document.querySelector(`[data-dur="${durId}"]`)?.classList.add('style-card--selected');
  }
```

and replace it with

```javascript
  function selectDuration(durId) {
    document.querySelectorAll('#duration-grid .style-card').forEach(c => c.classList.remove('style-card--selected'));
    document.querySelector(`[data-dur="${durId}"]`)?.classList.add('style-card--selected');
    updateTierHint();
  }
```

In `app/web/static/js/generate.js::submit` (the request body), find

```javascript
      pacing: document.getElementById('gen-pacing').value || null,
      music_source: document.getElementById('gen-music-source').value || null,
```

and replace it with

```javascript
      pacing: document.getElementById('gen-pacing').value || null,
      music_source: document.getElementById('gen-music-source').value || null,
      quality_tier: document.getElementById('gen-tier').value || null,                 // null = Settings default
      max_cost: document.getElementById('gen-max-cost').value.trim() || null,         // text: the server validates
```

In `app/web/static/js/generate.js` (the module's return statement), find

```javascript
  return { render, toggleAuto, selectStyle, selectVideoStyle, selectDuration, toggleSwitch, toggleCheckbox, submit };
```

and replace it with

```javascript
  return { render, toggleAuto, selectStyle, selectVideoStyle, selectDuration, toggleSwitch, toggleCheckbox, submit,
           updateTierHint };
```

In `app/web/static/js/settings.js::renderSettings` (Providers section), find

```javascript
            <select class="form-select" data-key="fal_video_model">
              ${['hailuo', 'kling', 'kling-pro'].map(m => `<option value="${m}" ${config.fal_video_model === m ? 'selected' : ''}>${m === 'hailuo' ? 'Minimax Hailuo (best value)' : m === 'kling' ? 'Kling Standard' : 'Kling Pro'}</option>`).join('')}
            </select>
```

and replace it with

```javascript
            <select class="form-select" data-key="fal_video_model">
              ${falModelOptions().map(m => `<option value="${m.key}" ${config.fal_video_model === m.key ? 'selected' : ''}>${m.label}${m.price_text ? ` (${m.price_text})` : ''}</option>`).join('')}
            </select>
            <div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-1)">Used by the Custom quality tier and the classic editor.</div>
```

In `app/web/static/js/settings.js::renderSettings` (Generation Defaults section), find

```javascript
        <div style="display:flex;gap:var(--space-8);flex-wrap:wrap;margin-top:var(--space-2)">
          ${settingToggle('cinematic_enabled', 'Shot editor (off = classic)', config.cinematic_enabled !== false)}
```

and replace it with

```javascript
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Default Quality Tier</label>
            <select class="form-select" data-key="quality_tier">
              ${[['standard', 'Standard (Kling v3 Standard)'], ['premium', 'Premium (Kling v3 Pro)'], ['custom', 'Custom (fal.ai video model)']]
                .map(([t, label]) => `<option value="${t}" ${(config.quality_tier || 'standard') === t ? 'selected' : ''}>${label}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Max Cost per Video (USD, 0 = no cap)</label>
            <input class="form-input" type="number" min="0" step="0.5" data-key="max_cost_per_video"
                   value="${Number(config.max_cost_per_video) || 0}">
          </div>
        </div>

        <div style="display:flex;gap:var(--space-8);flex-wrap:wrap;margin-top:var(--space-2)">
          ${settingToggle('cinematic_enabled', 'Shot editor (off = classic)', config.cinematic_enabled !== false)}
```

In `app/web/static/js/settings.js`, find

```javascript
  async function save() {
    const updates = {};

    // Collect select/input values
    document.querySelectorAll('[data-key]').forEach(el => {
      const key = el.dataset.key;
      let val = el.value;
      if (el.type === 'range') val = parseFloat(val);
      updates[key] = val;
    });
```

and replace it with

```javascript
  // fal_video_model choices from /api/config clip_models; a saved key that is no longer known stays
  // selectable (marked unknown) so saving the page never changes it silently.
  function falModelOptions() {
    const models = Array.isArray(config.clip_models) && config.clip_models.length
      ? config.clip_models.slice()
      : [{ key: 'hailuo', label: 'Minimax video-01', price_text: '' }];
    if (config.fal_video_model && !models.some(m => m.key === config.fal_video_model)) {
      models.push({ key: config.fal_video_model, label: `${config.fal_video_model} (unknown)`, price_text: '' });
    }
    return models;
  }

  async function save() {
    const updates = {};

    // Collect select/input values
    document.querySelectorAll('[data-key]').forEach(el => {
      const key = el.dataset.key;
      let val = el.value;
      if (el.type === 'range') val = parseFloat(val);
      if (key === 'max_cost_per_video' && String(val).trim() === '') val = 0;   // blank = no cap
      updates[key] = val;
    });
```

In `app/web/static/js/scheduler.js::openCreateModal`, find

```javascript
          <div class="form-group">
            <label class="form-label">Strict (fail instead of a still)</label>
            <select class="form-select" id="sched-strict">
```

and replace it with

```javascript
          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Quality Tier</label>
              <select class="form-select" id="sched-tier">
                <option value="">Default</option>
                ${[['standard', 'Standard (Kling v3 Standard)'], ['premium', 'Premium (Kling v3 Pro)'], ['custom', 'Custom (Settings model)']].map(([t, label]) =>
                  `<option value="${t}" ${config.quality_tier === t ? 'selected' : ''}>${label}</option>`
                ).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Max Cost (USD, blank = Settings)</label>
              <input class="form-input" id="sched-max-cost" type="number" min="0" step="0.5" placeholder="Default"
                     value="${escapeHtml(config.max_cost == null ? '' : String(config.max_cost))}">
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Strict (fail instead of a still)</label>
            <select class="form-select" id="sched-strict">
```

In `app/web/static/js/scheduler.js::saveJob`, find

```javascript
    const strict = document.getElementById('sched-strict').value;
```

and replace it with

```javascript
    const strict = document.getElementById('sched-strict').value;
    const maxCost = document.getElementById('sched-max-cost').value.trim();
```

In `app/web/static/js/scheduler.js::saveJob` (the slot config), find

```javascript
      strict: strict === '' ? null : strict === 'true',
    };
```

and replace it with

```javascript
      strict: strict === '' ? null : strict === 'true',
      quality_tier: document.getElementById('sched-tier').value || null,           // null = Settings default
      max_cost: maxCost === '' ? null : maxCost,                                   // text: the server validates
    };
```

- [ ] **Step 2: Syntax-check the JavaScript**

Run: `for f in generate settings scheduler; do node --check app/web/static/js/$f.js && echo "$f ok"; done`
Expected:

```
generate ok
settings ok
scheduler ok
```

Run: `git grep -n "'hailuo', 'kling', 'kling-pro'" -- app/web/static/js`
Expected: no output (the hard-coded model list is gone).

- [ ] **Step 3: Document the options**

In `CLAUDE.md` (Commands section), find

```
# Shot editor options (default pacing: standard)
```

and replace it with

```
# Quality tiers: the motion model per video (every shot stays motion). Default: settings.quality_tier
python main.py --auto --tier standard        # Kling v3 Standard (~$4 of motion for a medium video)
python main.py --auto --tier premium         # Kling v3 Pro (~$5.6)
python main.py --auto --tier custom          # settings.fal_video_model: kling | kling-pro | hailuo | h3-turbo | h3
python main.py --auto --max-cost 5           # stop before the next paid stage if the estimate exceeds $5 (0 = no cap)
# Estimates (pre_tts, pre_clips) and the cap land in output/<job>/run_report.json "cost". List prices
# live in settings.clip_pricing; a cap never swaps in stills or a cheaper model.

# Shot editor options (default pacing: standard)
```

In `CLAUDE.md` (Commands section, Web UI comment), find

```
# Web UI. Generate form, Scheduler slots and Settings page carry pacing, music source and strict
```

and replace it with

```
# Web UI. Generate form, Scheduler slots and Settings page carry pacing, music source, strict, quality tier and max cost
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --tb=short -rf -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py`
Expected: `730 passed, 12 failed` — the baseline's 601 plus 129 new tests; the 12 failures are exactly the baseline ones (4 `test_uploader`, 6 `test_trends`, 1 `test_trend_scout`, 1 `test_local_image_gen`). Any other failure is a regression to fix before committing. (Prototype check in a clean worktree, where `tests/test_trends.py` and `tests/test_upload_pack.py` are untracked and absent: `558 passed, 6 failed` before → `687 passed, 6 failed` after.)

Run: `git status --short`
Expected: only the four files of this task are modified among tracked files besides the pre-existing ` M output/cost_log.json` (never stage it).

- [ ] **Step 5: Commit**

```bash
git add app/web/static/js/generate.js app/web/static/js/scheduler.js app/web/static/js/settings.js CLAUDE.md
git commit -m "feat: quality tier and max cost fields in the web UI; docs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Open items for the user (paid calls, not done without approval)

- First paid Standard and Premium runs (≈ $4–6 each) to confirm Kling v3 9:16 output and quality.
- One H3 Turbo 480P clip (≈ $0.13) before H3 can become the Standard default.
- Calibrate `WORDS_PER_SECOND` and the scene ranges from `run_report.json` after those runs.
- Decide whether classic / persona runs should honour the cap (Spec deviation 7).
