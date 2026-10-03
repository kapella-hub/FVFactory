# Shot-Based Editor — Phase A (Picture + Encode + Sources) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-scene CinematicEngine with a speech-aligned shot planner and renderer, render every job into its own `output/<job>/` folder with kept sources, encode upload-grade H.264 at 30 fps with two-pass loudnorm, and add `--rerender`.

**Architecture:** The pipeline becomes script → TTS → (Whisper alignment ∥ images) → segment plan → parallel motion clips → shot plan → shot renderer (video only) → audio mix → loudnorm + copy-mux. The pure core (`app/cin/textnorm.py`, `align.py`, `shot_plan.py`) has no I/O and is unit-tested on saved Whisper word fixtures; I/O lives in `clip_sourcing.py`, `renderer.py`, `mix.py`, `editor.py` and `app/encoding.py`. `shot_plan.json` (spec §6.6) is the contract between planning and rendering, which is what makes `--rerender` possible with zero API calls.

**Tech Stack:** Python 3.14 venv (Docker 3.12), MoviePy 2.1.2, Pillow, NumPy, openai-whisper, ffmpeg/ffprobe 8 (PATH) with imageio-ffmpeg 7.1 fallback, pydantic-settings 2.12, pytest 9.

**Spec:** `docs/superpowers/specs/2026-10-02-shot-based-editor-design.md` (Phase A = §13 A; sections §4, §5, §6, §9, parts of §10 and §11)

## Global Constraints

- Run everything with the venv: `.venv/Scripts/python.exe` (Git Bash). Test command prefix used below: `.venv/Scripts/python.exe -m pytest`.
- The venv lacks `fal-client`, `apscheduler`, `fastapi` and the Google API libraries even though `requirements.txt` lists some of them. Never import `fal_client` at module level; tests must pass without it. Full-suite runs use `--ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py` (they fail at import for missing deps — out of scope).
- Baseline after Task 1 (measured 2026-10-02 with `extra="ignore"` applied): **12 pre-existing failures, all out of scope** — `test_local_image_gen.py::test_generate_creates_image`, `test_trend_scout.py::test_fetch_youtube_trending_with_api_key`, `test_trends.py::TestTrendScorer::{test_score_bounds,test_breakdown_keys,test_blocklist_blocks,test_recency_decay,test_niche_match_scoring}`, `test_trends.py::TestOrchestratorResilience::test_continues_on_source_failure`, and 4 in `test_uploader.py` (missing google libs). Do not chase them. "Full suite green" in this plan means: only these 12 fail.
- Never print, paste or commit `.env` values. Pydantic errors echo input values: run failing-config steps with `--tb=no`, and every test that builds `Settings` passes `_env_file=None`.
- Code must also run on Python 3.12 (Docker): no PEP 695 syntax; `from __future__ import annotations` is fine.
- No new dependencies. The text normalizer is built in (spec §5). `cv2` is optional (not installed here); use it only behind `try: import cv2`.
- Tests make **zero network calls**: patch ElevenLabs/OpenAI TTS, the LLM, Whisper (`app.cin.align.transcribe_words`) and fal (`sys.modules["fal_client"]`); integration tests also replace `requests.get/post` with functions that raise.
- Pacing presets (spec §6.1, verbatim): `calm` 4.2 s target / 3.5 min / 5.0 max; `standard` (default) 2.8 / 2.2 / 3.5; `fast` 2.1 / 1.8 / 2.5.
- Cut score (spec §6.2): `gap_seconds + 0.5 if sentence end + 0.25 if comma`; DP minimizes `Σ (shot_len − target)² − Σ score`.
- Framing (spec §6.3): `1.0` and `1.18` (centred punch-in, slight upper-third bias); adjacent shots from the same source never share framing.
- Clip sourcing (spec §6.4): request `scene_len + 0.5 s`, snapped up to model durations (Minimax/hailuo fixed ≈ 6 s; Kling v1/1.5: 5 or 10 s); split scenes too long for the model's max at the best gap near the middle; second segment starts from the first clip's last frame (scene image if the first failed); footage short by ≤ 15 % → uniform speed factor ≥ 0.87, beyond that the tail is a still (reported); parallel with `settings.motion_concurrency` (default 4).
- Transitions (spec §6.5): hard cut by default; up to 3 scene boundaries with the longest preceding pause get flash / zoom-through / whip pan, 0.3 s, built from moving frames (0.15 s each side).
- Alignment (spec §5): `difflib.SequenceMatcher` (with `autojunk=False`), fallback to word-count split below 70 % token match or when `scene_texts` is missing / does not join back to the narration; `alignment_fallback` is reported.
- Encode (spec §9.1, verbatim): video-only MoviePy render at 30 fps with `-c:v libx264 -preset slow -crf 18 -profile:v high -pix_fmt yuv420p -colorspace bt709 -color_primaries bt709 -color_trc bt709`; two-pass `loudnorm=I=-14:TP=-1:LRA=11` on the mixed WAV; mux with `-c:v copy -c:a aac -b:a 192k -ar 48000 -movflags +faststart`.
- Job folder (spec §9.2): `output/<job>/{final.mp4, run_report.json, sources/{narration.mp3, words.json, alignment.json, shot_plan.json, images/sceneNN.png, clips/sceneNN_x.mp4, mix.wav}}`. Every path stored in JSON is job-relative posix (`sources/clips/scene00_a.mp4`).
- New settings (spec §11): `whisper_model="small"`, `motion_concurrency=4`, `keep_sources_days=14`, `fal_video_fallback_model=""`, plus `pacing="standard"`, `strict=False`.
- Line numbers cite today's tree. After Tasks 2, 7 and 10 shift `main.py`, `app/asset_manager.py` and `app/video_editor.py`, the quoted text anchors in each step are authoritative.
- Commit only the files each task lists (the working tree has many unrelated untracked files). End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not commit this plan file.

**Phase A decisions and deviations (read before starting):**
- Hook headline is deferred to Phase B: `shot_plan.json` keeps `"hook_headline": null`; the new path drops the old 4 s centre title card and shows captions from frame one (spec §7 "no suppression window").
- Captions keep the existing karaoke renderer (`VideoEditor._create_karaoke_clips`), fed with aligned script-token groups instead of a second Whisper pass. Known debt fixed by the Phase B caption rewrite: words inside a group are timed evenly (`app/video_editor.py:495`) and the caption sits at y = 1570 (`app/video_editor.py:512`), outside the spec's safe zone.
- Music/SFX keep the existing code paths (`_get_random_music_file`, `_prepare_background_music`, `SFXMixer`) mixed into `mix.wav`; Phase C replaces them. `music_missing` / `sfx_missing` are still reported (today all `assets/music/<mood>/` folders and `assets/sfx/` are empty). `--music-source` is Phase C.
- `sfx`, `music`, `hook_headline` keys are always present in `shot_plan.json` (`[]` / `null`) so later phases never branch on key existence.
- Prompt-count normalization merges extra `scene_texts` into the last scene instead of dropping them (spec §10 says "truncate extras"); dropping narration text would make every such run fail the "joins back to the narration" check and fall back to word counts.
- Cut DP relaxation: spec §6.2 makes "no valid cut set" a one-shot scene, assuming that only happens for scenes shorter than `min`. Gap geometry also makes long segments infeasible (gold fixture, scene 1, 5.68 s at `fast`: strict bounds give a single 5.68 s shot). Segments longer than `max` retry with bounds ×(0.8, 1.25), then (0, ×1.5) before giving up.
- `h264_metadata` bitstream filter on the copy-mux: MoviePy's x264 output tags only `colorspace`; primaries/transfer read `unknown` without it (verified with ffprobe). This is added to the spec's mux flags.
- Out of scope for A: web form / scheduler / generator_worker option plumbing and `/api/generate` warnings (D), caption rewrite + fonts (B), music/SFX libraries, ducking, voice polish (C), cost estimate/cap (sub-project 3). In A, `pacing`/`strict` reach `run_pipeline`, the CLI and `Settings` only.

## Review Focus

1. **LLM `scene_texts` that do not join back to the narration** (paraphrased, missing a sentence): the run must still render with word-count scene timing, Whisper-timed captions, and an `alignment_fallback` warning — pinned in Task 4 (`test_scene_texts_that_do_not_join_fall_back_to_word_count`) and Task 12 (`test_paraphrased_scene_texts_render_with_alignment_fallback`).
2. **Very short narration or degenerate scenes** (one short sentence; an empty `scene_text`; a scene shorter than one frame after alignment): no zero-length scene or shot, shots contiguous from 0 to the audio duration — pinned in Task 4 (`test_empty_scene_text_never_produces_zero_length_scene`) and Task 6 (`test_very_short_narration_is_one_shot`, `test_scene_shorter_than_min_is_one_shot`).
3. **Every clip fails** (fal down, bad key, or `fal_client` not installed — true in this venv): the run must not crash; every segment becomes a push-in still with one `still_fallback` warning each, and `strict=True` stops before rendering — pinned in Task 8 (`test_all_clips_failing_never_raises`, `test_missing_fal_client_counts_as_clip_failure`) and Task 12 (`test_strict_mode_fails_before_render_on_still_fallback`).
4. **Windows-hostile topics and moved job folders** (`Rolex: "Why?" <CON>`, spaces in paths, a job folder renamed or copied before `--rerender`): folder names stay `[a-z0-9_]`, JSON paths are relative posix, and a moved job re-renders — pinned in Task 7 (`test_slug_is_windows_safe`, `test_rel_and_resolve_are_posix_and_relative`) and Task 13 (`test_rebuild_plan_after_moving_job_folder`).
5. **Two jobs started in the same second** (web UI `asyncio.to_thread`, scheduler): distinct job folders, no shared narration path, Whisper loaded once — pinned in Task 7 (`test_create_job_is_unique_under_concurrency`) and Task 12 (`test_concurrent_runs_get_separate_job_folders`).

## File Map

| File | Status | Responsibility |
|---|---|---|
| `app/config.py` | modify | `extra="ignore"`, new settings, `clip_pricing` |
| `app/cost_tracker.py` | modify | per-model clip pricing, `log_clip`, `get_video_items` |
| `app/motion_gen.py` | modify | `ClipModel` table, `snap_duration`, `max_duration`, `generate_clip` |
| `app/content_engine.py` | modify | `normalize_prompt_counts` |
| `app/cin/textnorm.py` | create | spoken-form normalizer (numbers, %, $, hyphens) |
| `app/cin/align.py` | create | `Alignment`, `align_words` (pure), `align` (Whisper) |
| `app/cin/shot_plan.py` | create | contract dataclasses, `plan_segments`, `build_shot_plan` |
| `app/cin/job.py` | create | job folder paths, `create_job`, `open_job`, `prune_sources` |
| `app/cin/report.py` | create | `RunReport` → `run_report.json` |
| `app/cin/clip_sourcing.py` | create | parallel clip generation, retry → fallback → failed, chaining |
| `app/encoding.py` | create | ffmpeg discovery, probe, loudness, platform check, `write_video`, `mux_final` |
| `app/cin/renderer.py` | create | `ShotRenderer`, `cover_fit`, `apply_framing`, `caption_overlays` |
| `app/cin/particles.py` | modify | private RNG instead of `random.seed(42)` on the global RNG |
| `app/video_editor.py` | modify | module-level `apply_color_grade`; remove cinematic branch (`:668-686`) |
| `app/cin/mix.py` | create | Phase A mix → `sources/mix.wav` |
| `app/cin/editor.py` | create | `RenderOptions`, `render_job`, rerender (`rebuild_plan`, `rerender_job`) |
| `app/asset_manager.py` | modify | narration/images written into the job folder |
| `app/library.py`, `app/web/routes/api_library.py` | create / modify | find videos in `output/<job>/final.mp4` and legacy flat files (Task 12a) |
| `main.py` | modify | pipeline reorder, `--pacing/--strict/--rerender/--color-grade`, mock-aware `validate_config` |
| `app/cinematic.py`, `app/cin/multishot.py` | delete | superseded by the shot planner/renderer |
| `tests/conftest.py`, `tests/fixtures/*.json` | create | fixtures, media helpers, `render` marker |

## Task Order and Dependencies

1 → everything. 2 needs 1. 3 → 4 → 5 → 6. 7 needs 1. 8 needs 2, 4, 5, 7. 9 needs 4 (it uses the conftest media helpers). 10 needs 5, 7, 9. 11 needs 6, 9, 10. 12 needs 3, 4, 6, 7, 8, 11. 12a needs 12. 13 needs 11, 12. 14 needs all. Once Task 4 is in, Tasks 5–6, 7 and 9 can be done in parallel by separate workers.

`render`-marked tests encode real 1080×1920 frames (measured: an 8 s render takes ≈ 27 s on the dev box). They run by default; skip them with `-m "not render"`, run only them with `-m render`.

---

### Task 1: Settings tolerate legacy `.env` keys; shot-editor settings

Unblocks the whole suite: today every test module that imports `app.config` errors at collection because `.env` holds `ayrshare_api_key`/`pexels_api_key` and `Settings` forbids extras (`app/config.py:5`).

**Files:**
- Modify: `app/config.py:1-9` (imports, `model_config`), `app/config.py:153` (append settings after `cinematic_enabled`)
- Test: `tests/test_config.py` (rewrite)

**Interfaces:**
- Produces: `settings.whisper_model: str = "small"`, `settings.motion_concurrency: int = 4`, `settings.keep_sources_days: int = 14`, `settings.fal_video_fallback_model: str = ""`, `settings.pacing: Literal["calm","standard","fast"] = "standard"`, `settings.strict: bool = False`.

- [ ] **Step 1: Confirm today's failure without printing secrets**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q --tb=no -p no:cacheprovider`
Expected: `1 error` (collection error — `Extra inputs are not permitted`). Do not rerun with a traceback; it echoes `.env` values.

- [ ] **Step 2: Rewrite `tests/test_config.py` (hermetic + new defaults)**

The old file read the developer's `.env` (so `replicate_api_token == ""` failed) and asserted stale defaults (`reddit_subreddits`, `provider_mode == "local"`, `wan_model_size == "1.3b"`). Replace the whole file:

```python
import pytest
from pydantic import ValidationError

from app.config import Settings


def make(**kw):
    """_env_file=None keeps these tests independent of the developer's .env."""
    return Settings(_env_file=None, **kw)


def test_v2_settings_have_defaults():
    s = make(openai_api_key="test")
    assert s.replicate_api_token == ""
    assert s.flux_model == "black-forest-labs/flux-1.1-pro"
    assert s.minimax_model == "minimax/image-to-video"
    assert s.elevenlabs_model == "eleven_multilingual_v2"
    assert s.elevenlabs_voice_id == "pqHfZKP75CvOlQylNhV4"  # Bill
    assert s.subtitle_style == "bold_impact"
    assert s.crossfade_duration == 0.8
    assert s.youtube_client_secrets == "client_secrets.json"
    assert s.youtube_token_path == "youtube_token.json"
    assert s.youtube_privacy == "public"
    assert "bill" in s.voice_presets
    assert "stoicism" in s.voice_niche_map
    assert s.enable_sfx is True
    assert s.enable_motion is True
    assert s.enable_intro is False
    assert s.channel_name == ""
    assert s.logo_path == ""
    assert s.color_grade == ""
    assert s.niche == ""
    assert s.sfx_dir == "assets/sfx"
    assert s.max_parallel_workers == 3
    assert s.cost_flux_image == 0.03
    assert s.cost_minimax_video == 0.10
    assert s.cost_elevenlabs_per_1k_chars == 0.01
    assert s.cost_openai_gpt4o == 0.005
    assert s.cost_openai_tts_per_1k_chars == 0.015
    assert s.reddit_subreddits == (
        "todayilearned,Damnthatsinteresting,interestingasfuck,space,technology,science,Futurology"
    )
    assert s.trend_count == 5


def test_v1_settings_unchanged():
    s = make(openai_api_key="test", elevenlabs_api_key="test2")
    assert s.openai_api_key == "test"
    assert s.elevenlabs_api_key == "test2"
    assert s.output_dir == "output"
    assert s.mascot_enabled is True


def test_provider_settings_defaults():
    s = make(openai_api_key="test", elevenlabs_api_key="test")
    assert s.provider_mode == "api"
    assert s.llm_provider == "claude_cli"
    assert s.image_provider == "fal"
    assert s.motion_provider == "fal"
    assert s.wan_model_size == "enhanced"
    assert s.data_dir == "data"
    assert s.claude_cli_timeout == 120


def test_provider_mode_api():
    s = make(openai_api_key="test", provider_mode="api")
    assert s.provider_mode == "api"


def test_legacy_env_keys_are_ignored(tmp_path):
    env = tmp_path / ".env"
    env.write_text("AYRSHARE_API_KEY=dummy\nPEXELS_API_KEY=dummy\nCHANNEL_NAME=fromfile\n", encoding="utf-8")
    s = Settings(_env_file=str(env))
    assert s.channel_name == "fromfile"
    assert not hasattr(s, "ayrshare_api_key")
    assert not hasattr(s, "pexels_api_key")


def test_shot_editor_settings_defaults():
    s = make()
    assert s.whisper_model == "small"
    assert s.motion_concurrency == 4
    assert s.keep_sources_days == 14
    assert s.fal_video_fallback_model == ""
    assert s.pacing == "standard"
    assert s.strict is False


def test_pacing_rejects_unknown_value():
    with pytest.raises(ValidationError):
        make(pacing="hyper")
```

- [ ] **Step 3: Implement the settings change**

In `app/config.py`, change the imports and `model_config`:

```python
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # legacy .env keys (e.g. AYRSHARE_API_KEY) must not break startup
    )
```

Directly after `cinematic_enabled: bool = True` (line 153) add:

```python
    # === Shot-based editor (spec 2026-10-02) ===
    whisper_model: str = "small"            # "base" is a valid, lighter choice for small VPSes
    motion_concurrency: int = 4             # parallel motion-clip generations
    keep_sources_days: int = 14             # prune output/<job>/sources/ older than this; <= 0 disables
    fal_video_fallback_model: str = ""      # e.g. "kling"; "" = no fallback model
    pacing: Literal["calm", "standard", "fast"] = "standard"
    strict: bool = False                    # True: fail the run instead of shipping a still shot
```

- [ ] **Step 4: Run the config tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q --tb=short -p no:cacheprovider`
Expected: `7 passed`

- [ ] **Step 5: Run the full suite to record the baseline**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --tb=no -rf -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py`
Expected: `12 failed, 155 passed` — the 12 failures are exactly the list in Global Constraints.

- [ ] **Step 6: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "fix: ignore legacy .env keys; add shot-editor settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Motion model table and per-model clip pricing

The cost tracker logs Minimax clips at a flat $0.10 (`app/config.py:115`, `app/cost_tracker.py:26`); fal's list price is $0.50 per hailuo clip, $0.045/s for Kling v1 standard and $0.10/s for Kling v1.5 pro (fal.ai model pages, checked 2026-10-02; both Kling endpoints are marked deprecated there — kept for existing configs, sub-project 3 replaces the table).

**Files:**
- Modify: `app/motion_gen.py:1-19` (imports, model table, helpers)
- Modify: `app/config.py:115` (replace `cost_minimax_video` with `clip_pricing`)
- Modify: `app/cost_tracker.py:22-61` (unit costs, `log_clip`, `get_video_items`)
- Modify: `main.py:19` (import), `main.py:399-402` (classic clip cost logging)
- Test: `tests/test_motion_gen.py` (append), `tests/test_cost_tracker.py` (append), `tests/test_config.py:27` (one assertion)

**Interfaces:**
- Produces (`app/motion_gen.py`): `ClipModel(key: str, endpoint: Optional[str], durations: Optional[tuple[float, ...]], sends_duration: bool = False)`; `CLIP_MODELS: dict[str, ClipModel]` with keys `hailuo`, `kling`, `kling-pro`, `replicate-minimax`, `local`; `FAL_MODELS` (unchanged keys); `clip_model_for(provider: str, fal_model: str) -> ClipModel`; `max_duration(durations) -> float` (`math.inf` for `None`); `snap_duration(needed: float, durations) -> Optional[float]`.
- Produces (`app/cost_tracker.py`): `CostTracker.clip_unit_cost(model: str, seconds: float) -> float`, `CostTracker.log_clip(video_id: str, model: str, seconds: float, count: int = 1) -> float`, `CostTracker.get_video_items(video_id: str) -> list[dict]`.
- Produces (`app/config.py`): `settings.clip_pricing: dict[str, dict]` (`{"per_clip": usd}` or `{"per_second": usd}`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_motion_gen.py`:

```python
import math

from app.motion_gen import CLIP_MODELS, clip_model_for, max_duration, snap_duration


def test_snap_duration_rounds_up_to_supported_lengths():
    assert snap_duration(2.8, (6.0,)) == 6.0
    assert snap_duration(6.2, (6.0,)) is None          # too long: caller must split the scene
    assert snap_duration(5.0, (5.0, 10.0)) == 5.0
    assert snap_duration(5.01, (5.0, 10.0)) == 10.0
    assert snap_duration(7.333, None) == 7.33           # any-length model: exact request


def test_max_duration():
    assert max_duration((5.0, 10.0)) == 10.0
    assert max_duration(None) == math.inf


def test_clip_model_for_providers():
    assert clip_model_for("fal", "kling").key == "kling"
    assert clip_model_for("fal", "unknown-model").key == "hailuo"
    assert clip_model_for("replicate", "kling").key == "replicate-minimax"
    assert clip_model_for("local", "hailuo").durations is None
    assert CLIP_MODELS["hailuo"].durations == (6.0,)
    assert CLIP_MODELS["kling"].sends_duration is True
```

Append to `tests/test_cost_tracker.py`:

```python
import pytest


def test_hailuo_clip_priced_per_clip(tmp_path):
    tracker = CostTracker(output_dir=str(tmp_path))
    assert tracker.log_clip("v1", "hailuo", seconds=6.0, count=3) == 1.5
    assert tracker.get_video_cost("v1") == 1.5
    item = tracker.get_video_items("v1")[0]
    assert item["item"] == "clip:hailuo"
    assert item["quantity"] == 3
    assert item["unit_cost"] == 0.5


def test_kling_clip_priced_per_second(tmp_path):
    tracker = CostTracker(output_dir=str(tmp_path))
    assert tracker.log_clip("v1", "kling", seconds=10.0) == 0.45


def test_unknown_clip_model_raises(tmp_path):
    with pytest.raises(ValueError):
        CostTracker(output_dir=str(tmp_path)).log_clip("v1", "sora", 5.0)


def test_flat_minimax_item_removed(tmp_path):
    assert "minimax_video" not in CostTracker(output_dir=str(tmp_path)).unit_costs
```

In `tests/test_config.py::test_v2_settings_have_defaults` replace `assert s.cost_minimax_video == 0.10` with:

```python
    assert s.clip_pricing["hailuo"] == {"per_clip": 0.50}
    assert s.clip_pricing["kling"] == {"per_second": 0.045}
    assert not hasattr(s, "cost_minimax_video")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_cost_tracker.py tests/test_config.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'CLIP_MODELS'` (collection error for test_motion_gen.py), `AttributeError: 'CostTracker' object has no attribute 'log_clip'`, `KeyError`/`AttributeError` on `clip_pricing`.

- [ ] **Step 3: Implement the model table**

In `app/motion_gen.py` replace lines 1-19 (docstring, imports, `FAL_MODELS`) with:

```python
"""Motion Generator — fal.ai Minimax Hailuo (default), Replicate, or local fallback."""

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from app.config import settings

logger = logging.getLogger(__name__)


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

# fal.ai model endpoints (kept for older call sites)
FAL_MODELS = {key: m.endpoint for key, m in CLIP_MODELS.items() if m.endpoint}


def clip_model_for(provider: str, fal_model: str) -> ClipModel:
    if provider == "local":
        return CLIP_MODELS["local"]
    if provider == "replicate":
        return CLIP_MODELS["replicate-minimax"]
    return CLIP_MODELS.get(fal_model, CLIP_MODELS["hailuo"])


def max_duration(durations: Optional[Tuple[float, ...]]) -> float:
    return math.inf if durations is None else max(durations)


def snap_duration(needed: float, durations: Optional[Tuple[float, ...]]) -> Optional[float]:
    """Smallest supported length >= needed; None when even the longest is too short."""
    if durations is None:
        return round(needed, 2)
    for d in sorted(durations):
        if d + 1e-6 >= needed:
            return d
    return None
```

- [ ] **Step 4: Implement per-model pricing**

In `app/config.py` replace `    cost_minimax_video: float = 0.10` with:

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

In `app/cost_tracker.py` delete the `"minimax_video": settings.cost_minimax_video,` line from `unit_costs`, then replace `log_cost` (lines 42-61) with:

```python
    def log_cost(self, video_id: str, item: str, quantity: int = 1) -> None:
        if item not in self.unit_costs:
            raise ValueError(f"Unknown cost item: {item}. Valid: {list(self.unit_costs.keys())}")
        unit = self.unit_costs[item]
        self._append(video_id, {"item": item, "quantity": quantity, "unit_cost": unit,
                                "cost": round(unit * quantity, 4)})
        logger.debug(f"Cost: {item} x{quantity} = ${unit * quantity:.4f} (video: {video_id})")

    def clip_unit_cost(self, model: str, seconds: float) -> float:
        price = settings.clip_pricing.get(model)
        if price is None:
            raise ValueError(f"No clip pricing for model {model!r}. Known: {sorted(settings.clip_pricing)}")
        if "per_second" in price:
            return round(float(price["per_second"]) * float(seconds), 4)
        return float(price.get("per_clip", 0.0))

    def log_clip(self, video_id: str, model: str, seconds: float, count: int = 1) -> float:
        unit = self.clip_unit_cost(model, seconds)
        cost = round(unit * count, 4)
        self._append(video_id, {"item": f"clip:{model}", "quantity": count, "seconds": seconds,
                                "unit_cost": unit, "cost": cost})
        return cost

    def get_video_items(self, video_id: str) -> list:
        return list(self._costs["videos"].get(video_id, {}).get("items", []))

    def _append(self, video_id: str, entry: dict) -> None:
        video = self._costs["videos"].setdefault(video_id, {"items": [], "total": 0.0})
        video["items"].append(entry)
        video["total"] = round(video["total"] + entry["cost"], 4)
```

In `main.py:19` change the import to `from app.motion_gen import MotionGenerator, clip_model_for, snap_duration` and replace lines 399-402 with:

```python
        if motion_clip_paths:
            success_count = sum(1 for c in motion_clip_paths if c is not None)
            if success_count > 0:
                model = clip_model_for(settings.motion_provider, settings.fal_video_model)
                tracker.log_clip(video_id, model.key, seconds=snap_duration(5.0, model.durations) or 5.0,
                                 count=success_count)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_cost_tracker.py tests/test_config.py -q --tb=short -p no:cacheprovider`
Expected: `24 passed` (7 + 10 + 7)

- [ ] **Step 6: Commit**

```bash
git add app/motion_gen.py app/config.py app/cost_tracker.py main.py tests/test_motion_gen.py tests/test_cost_tracker.py tests/test_config.py
git commit -m "feat: motion model duration table and per-model clip pricing" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Text normalizer and prompt-count normalization

Two pure helpers that run before anything is paid for: the spoken-form normalizer alignment depends on (spec §5 step 2), and the prompt-count fix for the crash at `app/motion_gen.py:146` (spec §10).

**Files:**
- Create: `app/cin/textnorm.py`
- Modify: `app/content_engine.py:6-13` (imports, logger), append `normalize_prompt_counts` after `ScriptOutput` (after line 51)
- Test: `tests/test_cin_textnorm.py`, `tests/test_prompt_normalization.py`

**Interfaces:**
- Produces: `normalize_token(raw: str) -> list[str]`, `cardinal(n: int) -> list[str]`, `year_words(n: int) -> list[str]` in `app/cin/textnorm.py`.
- Produces: `GENERIC_MOTION_PROMPT: str`, `normalize_prompt_counts(script: ScriptOutput) -> tuple[ScriptOutput, Optional[dict]]` in `app/content_engine.py` (detail is `{"before": counts, "after": counts}` with keys `image_prompts`, `motion_prompts`, `scene_texts`, `pacing_hints`; `None` when nothing changed).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_textnorm.py`:

```python
"""Spoken-form normalizer used by speech alignment (spec §5 step 2)."""
import pytest

from app.cin.textnorm import cardinal, normalize_token


@pytest.mark.parametrize("raw, expected", [
    ("1926,", ["nineteen", "twenty", "six"]),
    ("1905", ["nineteen", "oh", "five"]),
    ("1900", ["nineteen", "hundred"]),
    ("2005", ["two", "thousand", "five"]),
    ("2024", ["twenty", "twenty", "four"]),
    ("1000", ["one", "thousand"]),
    ("115", ["one", "hundred", "fifteen"]),
    ("1", ["one"]),
    ("1,000,000", ["one", "million"]),
    ("1,250,000", ["one", "million", "two", "hundred", "fifty", "thousand"]),
    ("$5,000", ["five", "thousand", "dollars"]),
    ("40%", ["forty", "percent"]),
    ("2.5", ["two", "point", "five"]),
    ("21st", ["twenty", "first"]),
    ("3rd", ["third"]),
    ("12th", ["twelfth"]),
    ("40th", ["fortieth"]),
    ("twenty-six", ["twenty", "six"]),
    ("That's", ["thats"]),
    ("Hello,", ["hello"]),
    ("(Rolex)", ["rolex"]),
    ("—", []),
    ("...", []),
])
def test_normalize_token(raw, expected):
    assert normalize_token(raw) == expected


def test_digit_and_word_forms_compare_equal():
    assert normalize_token("1926") == normalize_token("nineteen") + normalize_token("twenty-six")
    assert normalize_token("40%") == normalize_token("40") + normalize_token("percent")


def test_cardinal_zero():
    assert cardinal(0) == ["zero"]
```

Create `tests/test_prompt_normalization.py`:

```python
"""Prompt-count normalization after the LLM call, before paid generation (spec §10)."""
from app.content_engine import GENERIC_MOTION_PROMPT, ScriptOutput, normalize_prompt_counts


def make(images=6, motion=6, scenes=6, hints=0):
    return ScriptOutput(
        hook="Hook.", body="Body.", keywords=["k"],
        image_prompts=[f"img {i}" for i in range(images)],
        motion_prompts=[f"move {i}" for i in range(motion)],
        scene_texts=[f"Scene {i}." for i in range(scenes)],
        pacing_hints=["fast"] * hints,
    )


def test_equal_counts_unchanged():
    script = make()
    out, change = normalize_prompt_counts(script)
    assert out is script
    assert change is None


def test_missing_motion_prompts_padded_with_generic_move():
    out, change = normalize_prompt_counts(make(motion=4))
    assert len(out.motion_prompts) == 6
    assert out.motion_prompts[4:] == [GENERIC_MOTION_PROMPT, GENERIC_MOTION_PROMPT]
    assert change["before"]["motion_prompts"] == 4 and change["after"]["motion_prompts"] == 6


def test_extra_motion_prompts_truncated():
    out, _ = normalize_prompt_counts(make(motion=8))
    assert out.motion_prompts == [f"move {i}" for i in range(6)]


def test_fewer_scene_texts_truncate_image_prompts_below_validator_minimum():
    out, change = normalize_prompt_counts(make(scenes=4))       # 4 < ScriptOutput's min of 5
    assert out.image_prompts == ["img 0", "img 1", "img 2", "img 3"]
    assert len(out.motion_prompts) == 4
    assert change["after"]["image_prompts"] == 4


def test_extra_scene_texts_merge_into_last_scene():
    script = make(scenes=8)
    out, _ = normalize_prompt_counts(script)
    assert len(out.scene_texts) == 6
    assert out.scene_texts[-1] == "Scene 5. Scene 6. Scene 7."
    assert " ".join(out.scene_texts) == " ".join(script.scene_texts)   # narration preserved


def test_missing_scene_texts_keep_image_count():
    out, _ = normalize_prompt_counts(make(scenes=0))
    assert len(out.image_prompts) == 6 and out.scene_texts == []


def test_empty_motion_prompts_all_generic():
    out, change = normalize_prompt_counts(make(motion=0))
    assert out.motion_prompts == [GENERIC_MOTION_PROMPT] * 6
    assert change is not None


def test_pacing_hints_padded_only_when_present():
    assert normalize_prompt_counts(make(hints=3))[0].pacing_hints == ["fast"] * 3 + ["normal"] * 3
    assert normalize_prompt_counts(make(hints=0))[0].pacing_hints == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_textnorm.py tests/test_prompt_normalization.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cin.textnorm'` and `ImportError: cannot import name 'GENERIC_MOTION_PROMPT'`.

- [ ] **Step 3: Implement `app/cin/textnorm.py`**

```python
"""Small text normalizer for speech alignment (spec §5 step 2). No third-party dependencies.

normalize_token() turns one whitespace-separated token into the lowercase words a speaker says,
so script text and Whisper text compare equal:
"1926," -> ["nineteen", "twenty", "six"], "40%" -> ["forty", "percent"], "twenty-six" -> ["twenty", "six"].
"""
import re

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_SCALES = [(1_000_000_000, "billion"), (1_000_000, "million"), (1_000, "thousand")]
_IRREGULAR_ORDINALS = {"one": "first", "two": "second", "three": "third", "five": "fifth",
                       "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
_EDGE = ".,!?;:\"'()[]{}…“”‘’"
_ORDINAL_RE = re.compile(r"^(\d+)(st|nd|rd|th)$")
_INT_RE = re.compile(r"^\d+$")
_DEC_RE = re.compile(r"^\d+\.\d+$")


def _under_1000(n: int) -> list:
    words = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        words += [_ONES[hundreds], "hundred"]
    if rest >= 20:
        tens, ones = divmod(rest, 10)
        words.append(_TENS[tens])
        if ones:
            words.append(_ONES[ones])
    elif rest:
        words.append(_ONES[rest])
    return words


def cardinal(n: int) -> list:
    if n == 0:
        return ["zero"]
    words = []
    for value, name in _SCALES:
        if n >= value:
            words += cardinal(n // value) + [name]
            n %= value
    return words + _under_1000(n)


def year_words(n: int) -> list:
    """1100-1999 and 2010-2099 are read in pairs; 2000-2009 as cardinals."""
    if 2000 <= n <= 2009:
        return cardinal(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return _under_1000(hi) + ["hundred"]
    if lo < 10:
        return _under_1000(hi) + ["oh", _ONES[lo]]
    return _under_1000(hi) + _under_1000(lo)


def _ordinal(words: list) -> list:
    last = words[-1]
    if last in _IRREGULAR_ORDINALS:
        last = _IRREGULAR_ORDINALS[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last += "th"
    return words[:-1] + [last]


def _normalize_part(part: str) -> list:
    p = part.strip(_EDGE)
    if not p:
        return []
    dollars = p.startswith("$")
    percent = p.endswith("%")
    p = p.strip("$%")
    m = _ORDINAL_RE.match(p)
    if m:
        return _ordinal(cardinal(int(m.group(1))))
    num = p.replace(",", "")
    if _INT_RE.match(num):
        n = int(num)
        is_year = len(p) == 4 and (1100 <= n <= 1999 or 2000 <= n <= 2099)
        words = year_words(n) if is_year else cardinal(n)
    elif _DEC_RE.match(num):
        whole, frac = num.split(".")
        words = cardinal(int(whole)) + ["point"] + [_ONES[int(d)] for d in frac]
    else:
        word = re.sub(r"[^a-z0-9]", "", p)  # drops apostrophes: "that's" -> "thats" on both sides
        words = [word] if word else []
    if dollars:
        words.append("dollars")
    if percent:
        words.append("percent")
    return words


def normalize_token(raw: str) -> list:
    """Normalize one whitespace token into spoken lowercase words ([] for pure punctuation)."""
    t = raw.lower().replace("’", "'").strip()
    out = []
    for part in re.split("[-–—/]", t):
        out += _normalize_part(part)
    return out
```

- [ ] **Step 4: Implement `normalize_prompt_counts`**

In `app/content_engine.py` change the imports (lines 6-12) to:

```python
import json
import logging
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.llm import generate_json

logger = logging.getLogger(__name__)
```

Insert after the `ScriptOutput` class (after its `validate_image_prompts_count` validator):

```python
GENERIC_MOTION_PROMPT = "slow cinematic push-in with subtle camera drift"


def _prompt_counts(script: "ScriptOutput") -> dict:
    return {"image_prompts": len(script.image_prompts), "motion_prompts": len(script.motion_prompts),
            "scene_texts": len(script.scene_texts), "pacing_hints": len(script.pacing_hints)}


def normalize_prompt_counts(script: "ScriptOutput") -> Tuple["ScriptOutput", Optional[dict]]:
    """Make image_prompts / motion_prompts / scene_texts / pacing_hints the same length (spec §10).

    Runs right after the LLM call, before any paid generation. The scene count is the number of
    image prompts, or fewer scene_texts if the LLM returned fewer. Extra scene_texts are merged into
    the last scene (not dropped) so the scenes still join back to the narration for alignment.
    Missing motion prompts get GENERIC_MOTION_PROMPT. model_copy(update=...) skips validation on
    purpose: truncating to fewer than five scenes is allowed here.
    Returns (script, None) when nothing changed, else (new_script, {"before", "after"}).
    """
    n = len(script.image_prompts)
    if script.scene_texts:
        n = min(n, len(script.scene_texts))
    scenes = list(script.scene_texts)
    if len(scenes) > n:
        scenes = scenes[:n - 1] + [" ".join(scenes[n - 1:])]
    motion = list(script.motion_prompts[:n])
    motion += [GENERIC_MOTION_PROMPT] * (n - len(motion))
    hints = list(script.pacing_hints)
    if hints:
        hints = hints[:n] + ["normal"] * max(0, n - len(hints))
    new = script.model_copy(update={"image_prompts": list(script.image_prompts[:n]),
                                    "motion_prompts": motion, "scene_texts": scenes,
                                    "pacing_hints": hints})
    before, after = _prompt_counts(script), _prompt_counts(new)
    if before == after:
        return script, None
    logger.warning("Normalized prompt counts %s -> %s", before, after)
    return new, {"before": before, "after": after}
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_textnorm.py tests/test_prompt_normalization.py tests/test_content_engine.py -q --tb=short -p no:cacheprovider`
Expected: `37 passed` (25 textnorm + 8 normalization + 4 existing content-engine tests).

- [ ] **Step 6: Commit**

```bash
git add app/cin/textnorm.py app/content_engine.py tests/test_cin_textnorm.py tests/test_prompt_normalization.py
git commit -m "feat: spoken-form text normalizer and prompt-count normalization" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 4: Speech alignment (`app/cin/align.py`) and word-timing fixtures

Replaces the word-count proportional split (`app/cinematic.py:194`) with Whisper word timings mapped onto the script's tokens. Whisper output format (checked in `.venv/Lib/site-packages/whisper/timing.py`): `result["segments"][i]["words"] = [{"word": " Rolex", "start": 0.0, "end": 0.32, "probability": 0.93}, ...]` — leading space, punctuation attached.

**Files:**
- Create: `app/cin/align.py`
- Create: `tests/fixtures/words_rolex_40s.json`, `tests/fixtures/words_gold_8s.json`
- Create: `tests/conftest.py`
- Track: `tests/__init__.py` (exists locally but is untracked; tests import helpers as `tests.conftest`)
- Test: `tests/test_cin_align.py`

**Interfaces:**
- Consumes: `normalize_token(raw) -> list[str]` (Task 3).
- Produces (`app/cin/align.py`):
  - `AlignedToken(text: str, t0: float, t1: float, matched: bool, sentence_end: bool = False, comma: bool = False)`
  - `SceneSpan(index: int, t0: float, t1: float, text: str, first_token: int, last_token: int)` (`last_token` exclusive)
  - `Alignment(method: str, fallback: bool, match_ratio: float, duration: float, tokens: list[AlignedToken], scenes: list[SceneSpan], reason: str = "")` with `to_json() -> dict` / `Alignment.from_json(d)`; `method` is `"whisper+script"` or `"word_count"`
  - `MATCH_THRESHOLD = 0.70`, `MIN_SCENE = 1/30`
  - `align_words(words: list[dict], scene_texts: list[str], narration: str, duration: float, num_scenes: Optional[int] = None) -> Alignment` (pure)
  - `word_count_alignment(words, scene_texts, narration, duration, num_scenes: int, reason: str, match_ratio: float = 0.0) -> Alignment`
  - `transcribe_words(audio_path, model_name: str) -> list[dict]` (Whisper; patched in every test)
  - `align(audio_path, scene_texts, narration, duration, *, num_scenes=None, model_name=None) -> tuple[Alignment, list[dict]]` (never raises for Whisper failures)
- Produces (`tests/conftest.py`): `load_fixture(name) -> dict`, `fixture_alignment(name) -> Alignment`, fixtures `rolex`, `gold`, the `render` marker, and the synthetic-media helpers later tasks use: `ffmpeg_exe()`, `make_test_clip(path, seconds, size="108x192", color="red", rate=30)`, `make_color_clip(path, seconds, color, size="108x192", rate=30)`, `make_tone(path, seconds, volume=0.3)`, `make_silence(path, seconds)`.

Fixture design: `words_rolex_40s.json` is a 98-token, 40.12 s Rolex narration in 7 scenes. Whisper "mishears" `Wilsdorf` as `Wils Dorf`, writes `one` for the script's `1` (as in "1 million") and `40%` for the script's `40 percent`. `words_gold_8s.json` is a 24-token, 8.0 s, 2-scene narration used by render tests.

- [ ] **Step 1: Create the fixtures**

Create `tests/fixtures/words_rolex_40s.json`:

```json
{
  "duration": 40.12,
  "narration": "This watch costs more than a car. In 1905, a German orphan named Hans Wilsdorf founded a tiny watch company in London. By 1926, he had built the Oyster, the first truly waterproof wristwatch the world had ever seen. A young swimmer wore one across the English Channel, and after ten hours in cold water, it still kept perfect time. Today, Rolex makes about 1 million watches a year. Yet some models sell for 40 percent above retail, and buyers wait years just for the chance to pay. That's not a watch. That's an investment you can wear.",
  "scene_texts": [
    "This watch costs more than a car.",
    "In 1905, a German orphan named Hans Wilsdorf founded a tiny watch company in London.",
    "By 1926, he had built the Oyster, the first truly waterproof wristwatch the world had ever seen.",
    "A young swimmer wore one across the English Channel, and after ten hours in cold water, it still kept perfect time.",
    "Today, Rolex makes about 1 million watches a year.",
    "Yet some models sell for 40 percent above retail, and buyers wait years just for the chance to pay.",
    "That's not a watch. That's an investment you can wear."
  ],
  "words": [
    {"word": " This", "start": 0.05, "end": 0.37, "probability": 0.93},
    {"word": " watch", "start": 0.4, "end": 0.77, "probability": 0.93},
    {"word": " costs", "start": 0.81, "end": 1.18, "probability": 0.93},
    {"word": " more", "start": 1.22, "end": 1.53, "probability": 0.93},
    {"word": " than", "start": 1.57, "end": 1.89, "probability": 0.93},
    {"word": " a", "start": 1.92, "end": 2.09, "probability": 0.93},
    {"word": " car.", "start": 2.12, "end": 2.39, "probability": 0.93},
    {"word": " In", "start": 2.78, "end": 3.0, "probability": 0.93},
    {"word": " 1905,", "start": 3.03, "end": 3.35, "probability": 0.93},
    {"word": " a", "start": 3.52, "end": 3.68, "probability": 0.93},
    {"word": " German", "start": 3.72, "end": 4.14, "probability": 0.93},
    {"word": " orphan", "start": 4.18, "end": 4.6, "probability": 0.93},
    {"word": " named", "start": 4.63, "end": 5.0, "probability": 0.93},
    {"word": " Hans", "start": 5.04, "end": 5.36, "probability": 0.93},
    {"word": " Wils", "start": 5.39, "end": 5.71, "probability": 0.93},
    {"word": " Dorf", "start": 5.75, "end": 6.06, "probability": 0.93},
    {"word": " founded", "start": 6.1, "end": 6.57, "probability": 0.93},
    {"word": " a", "start": 6.61, "end": 6.77, "probability": 0.93},
    {"word": " tiny", "start": 6.81, "end": 7.13, "probability": 0.93},
    {"word": " watch", "start": 7.16, "end": 7.53, "probability": 0.93},
    {"word": " company", "start": 7.57, "end": 8.04, "probability": 0.93},
    {"word": " in", "start": 8.08, "end": 8.29, "probability": 0.93},
    {"word": " London.", "start": 8.33, "end": 8.75, "probability": 0.93},
    {"word": " By", "start": 9.14, "end": 9.36, "probability": 0.93},
    {"word": " 1926,", "start": 9.39, "end": 9.71, "probability": 0.93},
    {"word": " he", "start": 9.88, "end": 10.09, "probability": 0.93},
    {"word": " had", "start": 10.13, "end": 10.4, "probability": 0.93},
    {"word": " built", "start": 10.43, "end": 10.8, "probability": 0.93},
    {"word": " the", "start": 10.84, "end": 11.1, "probability": 0.93},
    {"word": " Oyster,", "start": 11.14, "end": 11.56, "probability": 0.93},
    {"word": " the", "start": 11.73, "end": 12.0, "probability": 0.93},
    {"word": " first", "start": 12.03, "end": 12.4, "probability": 0.93},
    {"word": " truly", "start": 12.44, "end": 12.81, "probability": 0.93},
    {"word": " waterproof", "start": 12.84, "end": 13.47, "probability": 0.93},
    {"word": " wristwatch", "start": 13.51, "end": 14.13, "probability": 0.93},
    {"word": " the", "start": 14.17, "end": 14.43, "probability": 0.93},
    {"word": " world", "start": 14.47, "end": 14.84, "probability": 0.93},
    {"word": " had", "start": 14.88, "end": 15.14, "probability": 0.93},
    {"word": " ever", "start": 15.18, "end": 15.5, "probability": 0.93},
    {"word": " seen.", "start": 15.53, "end": 15.85, "probability": 0.93},
    {"word": " A", "start": 16.24, "end": 16.41, "probability": 0.93},
    {"word": " young", "start": 16.44, "end": 16.81, "probability": 0.93},
    {"word": " swimmer", "start": 16.85, "end": 17.32, "probability": 0.93},
    {"word": " wore", "start": 17.36, "end": 17.67, "probability": 0.93},
    {"word": " one", "start": 17.71, "end": 17.98, "probability": 0.93},
    {"word": " across", "start": 18.01, "end": 18.43, "probability": 0.93},
    {"word": " the", "start": 18.47, "end": 18.74, "probability": 0.93},
    {"word": " English", "start": 18.77, "end": 19.25, "probability": 0.93},
    {"word": " Channel,", "start": 19.28, "end": 19.75, "probability": 0.93},
    {"word": " and", "start": 19.92, "end": 20.19, "probability": 0.93},
    {"word": " after", "start": 20.22, "end": 20.59, "probability": 0.93},
    {"word": " ten", "start": 20.63, "end": 20.9, "probability": 0.93},
    {"word": " hours", "start": 20.93, "end": 21.3, "probability": 0.93},
    {"word": " in", "start": 21.34, "end": 21.55, "probability": 0.93},
    {"word": " cold", "start": 21.59, "end": 21.91, "probability": 0.93},
    {"word": " water,", "start": 21.94, "end": 22.31, "probability": 0.93},
    {"word": " it", "start": 22.48, "end": 22.7, "probability": 0.93},
    {"word": " still", "start": 22.73, "end": 23.1, "probability": 0.93},
    {"word": " kept", "start": 23.14, "end": 23.46, "probability": 0.93},
    {"word": " perfect", "start": 23.49, "end": 23.96, "probability": 0.93},
    {"word": " time.", "start": 24.0, "end": 24.32, "probability": 0.93},
    {"word": " Today,", "start": 24.71, "end": 25.08, "probability": 0.93},
    {"word": " Rolex", "start": 25.25, "end": 25.61, "probability": 0.93},
    {"word": " makes", "start": 25.65, "end": 26.02, "probability": 0.93},
    {"word": " about", "start": 26.06, "end": 26.43, "probability": 0.93},
    {"word": " one", "start": 26.46, "end": 26.73, "probability": 0.93},
    {"word": " million", "start": 26.77, "end": 27.24, "probability": 0.93},
    {"word": " watches", "start": 27.27, "end": 27.74, "probability": 0.93},
    {"word": " a", "start": 27.78, "end": 27.95, "probability": 0.93},
    {"word": " year.", "start": 27.98, "end": 28.3, "probability": 0.93},
    {"word": " Yet", "start": 28.69, "end": 28.96, "probability": 0.93},
    {"word": " some", "start": 28.99, "end": 29.31, "probability": 0.93},
    {"word": " models", "start": 29.35, "end": 29.77, "probability": 0.93},
    {"word": " sell", "start": 29.81, "end": 30.12, "probability": 0.93},
    {"word": " for", "start": 30.16, "end": 30.43, "probability": 0.93},
    {"word": " 40%", "start": 30.46, "end": 30.73, "probability": 0.93},
    {"word": " above", "start": 30.77, "end": 31.13, "probability": 0.93},
    {"word": " retail,", "start": 31.17, "end": 31.59, "probability": 0.93},
    {"word": " and", "start": 31.76, "end": 32.02, "probability": 0.93},
    {"word": " buyers", "start": 32.06, "end": 32.48, "probability": 0.93},
    {"word": " wait", "start": 32.52, "end": 32.84, "probability": 0.93},
    {"word": " years", "start": 32.87, "end": 33.24, "probability": 0.93},
    {"word": " just", "start": 33.28, "end": 33.6, "probability": 0.93},
    {"word": " for", "start": 33.63, "end": 33.9, "probability": 0.93},
    {"word": " the", "start": 33.94, "end": 34.2, "probability": 0.93},
    {"word": " chance", "start": 34.24, "end": 34.66, "probability": 0.93},
    {"word": " to", "start": 34.7, "end": 34.91, "probability": 0.93},
    {"word": " pay.", "start": 34.95, "end": 35.21, "probability": 0.93},
    {"word": " That's", "start": 35.61, "end": 36.03, "probability": 0.93},
    {"word": " not", "start": 36.06, "end": 36.33, "probability": 0.93},
    {"word": " a", "start": 36.37, "end": 36.53, "probability": 0.93},
    {"word": " watch.", "start": 36.57, "end": 36.93, "probability": 0.93},
    {"word": " That's", "start": 37.33, "end": 37.75, "probability": 0.93},
    {"word": " an", "start": 37.78, "end": 38.0, "probability": 0.93},
    {"word": " investment", "start": 38.03, "end": 38.66, "probability": 0.93},
    {"word": " you", "start": 38.7, "end": 38.96, "probability": 0.93},
    {"word": " can", "start": 39.0, "end": 39.27, "probability": 0.93},
    {"word": " wear.", "start": 39.3, "end": 39.62, "probability": 0.93}
  ]
}
```

Create `tests/fixtures/words_gold_8s.json`:

```json
{
  "duration": 8.0,
  "narration": "Gold is heavier than you think. A single cube this size weighs as much as a small car, and it fits in your hand.",
  "scene_texts": [
    "Gold is heavier than you think.",
    "A single cube this size weighs as much as a small car, and it fits in your hand."
  ],
  "words": [
    {"word": " Gold", "start": 0.05, "end": 0.33, "probability": 0.93},
    {"word": " is", "start": 0.37, "end": 0.56, "probability": 0.93},
    {"word": " heavier", "start": 0.59, "end": 1.01, "probability": 0.93},
    {"word": " than", "start": 1.05, "end": 1.33, "probability": 0.93},
    {"word": " you", "start": 1.36, "end": 1.6, "probability": 0.93},
    {"word": " think.", "start": 1.64, "end": 1.96, "probability": 0.93},
    {"word": " A", "start": 2.32, "end": 2.46, "probability": 0.93},
    {"word": " single", "start": 2.49, "end": 2.87, "probability": 0.93},
    {"word": " cube", "start": 2.9, "end": 3.19, "probability": 0.93},
    {"word": " this", "start": 3.22, "end": 3.5, "probability": 0.93},
    {"word": " size", "start": 3.54, "end": 3.82, "probability": 0.93},
    {"word": " weighs", "start": 3.85, "end": 4.23, "probability": 0.93},
    {"word": " as", "start": 4.26, "end": 4.45, "probability": 0.93},
    {"word": " much", "start": 4.49, "end": 4.77, "probability": 0.93},
    {"word": " as", "start": 4.81, "end": 5.0, "probability": 0.93},
    {"word": " a", "start": 5.03, "end": 5.18, "probability": 0.93},
    {"word": " small", "start": 5.21, "end": 5.54, "probability": 0.93},
    {"word": " car,", "start": 5.57, "end": 5.81, "probability": 0.93},
    {"word": " and", "start": 5.96, "end": 6.2, "probability": 0.93},
    {"word": " it", "start": 6.23, "end": 6.42, "probability": 0.93},
    {"word": " fits", "start": 6.46, "end": 6.74, "probability": 0.93},
    {"word": " in", "start": 6.77, "end": 6.97, "probability": 0.93},
    {"word": " your", "start": 7.0, "end": 7.28, "probability": 0.93},
    {"word": " hand.", "start": 7.32, "end": 7.6, "probability": 0.93}
  ]
}
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
"""Shared test helpers for the shot-based editor."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def fixture_alignment(name: str):
    from app.cin.align import align_words
    fx = load_fixture(name)
    return align_words(fx["words"], fx["scene_texts"], fx["narration"], fx["duration"])


@pytest.fixture
def rolex() -> dict:
    return load_fixture("words_rolex_40s.json")


@pytest.fixture
def gold() -> dict:
    return load_fixture("words_gold_8s.json")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "render: renders real frames/encodes with ffmpeg (slow, 10-120 s). Skip with -m \"not render\".",
    )


# ---------------------------------------------------------------- synthetic media

def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def make_test_clip(path, seconds: float, size: str = "108x192", color: str = "red", rate: int = 30) -> Path:
    """Synthetic motion clip: ffmpeg testsrc blended with a solid colour."""
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={seconds}",
                    "-f", "lavfi", "-i", f"color=c={color}:size={size}:rate={rate}:duration={seconds}",
                    "-filter_complex", "[0][1]blend=all_mode=average",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return Path(path)


def make_color_clip(path, seconds: float, color: str, size: str = "108x192", rate: int = 30) -> Path:
    """Solid-colour clip (renderer colour assertions)."""
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c={color}:size={size}:rate={rate}:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return Path(path)


def make_tone(path, seconds: float, volume: float = 0.3) -> Path:
    """Speech-like test tone (220 Hz, 3 Hz tremolo). Container/codec follow the extension."""
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds}",
                    "-af", f"volume={volume},tremolo=f=3:d=0.7", str(path)], check=True)
    return Path(path)


def make_silence(path, seconds: float) -> Path:
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=stereo", "-t", str(seconds), str(path)], check=True)
    return Path(path)
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_cin_align.py`:

```python
"""Speech alignment on saved Whisper word timings (spec §5, §12)."""
import json
from unittest.mock import patch

import pytest

from app.cin.align import MIN_SCENE, Alignment, align, align_words


def _align(fx, scene_texts=None, words=None):
    return align_words(words if words is not None else fx["words"],
                       scene_texts if scene_texts is not None else fx["scene_texts"],
                       fx["narration"], fx["duration"])


def test_rolex_scene_boundaries_come_from_speech(rolex):
    a = _align(rolex)
    assert a.method == "whisper+script"
    assert a.fallback is False
    assert a.match_ratio == pytest.approx(97 / 98, abs=1e-4)
    assert [s.t0 for s in a.scenes] == [0.0, 2.78, 9.14, 16.24, 24.71, 28.69, 35.61]
    assert a.scenes[-1].t1 == 40.12
    assert [(s.first_token, s.last_token) for s in a.scenes] == [
        (0, 7), (7, 22), (22, 39), (39, 60), (60, 69), (69, 88), (88, 98)]


def test_misheard_name_keeps_script_spelling_with_interpolated_timing(rolex):
    a = _align(rolex)
    tok = next(t for t in a.tokens if t.text == "Wilsdorf")
    assert tok.matched is False
    assert (tok.t0, tok.t1) == (5.36, 6.1)   # between "Hans" (ends 5.36) and "founded" (starts 6.10)


def test_numbers_match_across_digit_and_word_forms(rolex):
    a = _align(rolex)
    by_text = {t.text: t for t in a.tokens}
    assert by_text["1"].matched and by_text["1"].t0 == 26.46          # script "1", whisper "one"
    assert by_text["40"].matched and by_text["40"].t0 == 30.46        # script "40 percent", whisper "40%"
    assert by_text["percent"].matched and by_text["percent"].t1 == 30.73
    assert by_text["1926"].comma is True


def test_scene_texts_that_do_not_join_fall_back_to_word_count(rolex):
    scene_texts = list(rolex["scene_texts"])
    scene_texts[2] = "By 1926 he built the Oyster."          # LLM paraphrased one scene
    a = _align(rolex, scene_texts=scene_texts)
    assert a.fallback is True
    assert a.method == "word_count"
    assert a.reason == "scene_texts_do_not_join"
    assert len(a.scenes) == 7
    assert a.scenes[0].t0 == 0.0 and a.scenes[-1].t1 == 40.12
    assert all(s.t1 == nxt.t0 for s, nxt in zip(a.scenes, a.scenes[1:]))
    assert len(a.tokens) == 98                                  # caption timings still come from Whisper


def test_low_match_ratio_falls_back(rolex):
    words = [dict(w, word=" lorem") for w in rolex["words"]]
    a = _align(rolex, words=words)
    assert a.fallback is True
    assert a.reason == "low_match_ratio"
    assert a.match_ratio < 0.70


def test_missing_scene_texts_split_evenly_into_requested_scene_count(rolex):
    a = align_words(rolex["words"], [], rolex["narration"], rolex["duration"], num_scenes=5)
    assert a.fallback is True and a.reason == "scene_texts_missing"
    assert len(a.scenes) == 5
    assert a.scenes[1].t0 == pytest.approx(40.12 / 5, abs=1e-3)


def test_autojunk_disabled_on_long_narrations():
    # 360 tokens; Whisper drops every "on". difflib's autojunk would ignore "the" (>1 % of 200+ items)
    # and lose matches; with autojunk=False every other token matches.
    script = []
    for i in range(60):
        script += ["the", f"cat{i}", "sat", "on", "the", "mat."]
    heard = [w for w in script if w != "on"]
    words = [{"word": " " + w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate(heard)]
    narration = " ".join(script)
    a = align_words(words, [narration], narration, 100.0)
    assert a.match_ratio == pytest.approx(300 / 360, abs=1e-9)


def test_empty_scene_text_never_produces_zero_length_scene(rolex):
    scene_texts = list(rolex["scene_texts"])
    scene_texts.insert(3, "")
    a = align_words(rolex["words"], scene_texts, rolex["narration"], rolex["duration"])
    assert len(a.scenes) == 8
    assert all(s.t1 - s.t0 >= MIN_SCENE - 1e-3 for s in a.scenes)
    assert all(s.t1 == nxt.t0 for s, nxt in zip(a.scenes, a.scenes[1:]))


def test_alignment_json_roundtrip(rolex):
    a = _align(rolex)
    d = json.loads(json.dumps(a.to_json()))
    assert Alignment.from_json(d).to_json() == d


def test_align_survives_whisper_failure(rolex):
    with patch("app.cin.align.transcribe_words", side_effect=RuntimeError("no model")):
        a, words = align("narration.mp3", rolex["scene_texts"], rolex["narration"], rolex["duration"])
    assert words == []
    assert a.fallback is True
    assert a.reason.startswith("transcription_failed")
    assert len(a.scenes) == 7
```

- [ ] **Step 4: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_align.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cin.align'`.

- [ ] **Step 5: Implement `app/cin/align.py`**

```python
"""Speech alignment: Whisper word timings mapped onto the script's own tokens (spec §5).

Pure core: align_words(). I/O wrapper: align() (runs Whisper). Captions use the script's
spelling with Whisper's timings; scene boundaries come from the first token of each scene.
"""
from __future__ import annotations

import difflib
import logging
import threading
from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np

from app.cin.textnorm import normalize_token

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 0.70          # spec §5 step 5
MIN_SCENE = 1.0 / 30            # a scene is never shorter than one frame at 30 fps
_EDGE_PUNCT = ".,!?;:\"'()[]{}…—–“”‘’"
_SENTENCE_END = (".", "!", "?", "…")
_CLAUSE_END = (",", ";", ":", "—", "–")


@dataclass
class AlignedToken:
    text: str            # script spelling, edge punctuation stripped ("Wilsdorf", "That's")
    t0: float
    t1: float
    matched: bool        # False = timing interpolated (or a fallback token)
    sentence_end: bool = False
    comma: bool = False


@dataclass
class SceneSpan:
    index: int
    t0: float
    t1: float
    text: str
    first_token: int     # index into Alignment.tokens
    last_token: int      # exclusive


@dataclass
class Alignment:
    method: str                      # "whisper+script" | "word_count"
    fallback: bool
    match_ratio: float
    duration: float
    tokens: list = field(default_factory=list)
    scenes: list = field(default_factory=list)
    reason: str = ""                 # why the fallback was used ("" when it was not)

    def to_json(self) -> dict:
        return {
            "method": self.method,
            "fallback": self.fallback,
            "match_ratio": round(self.match_ratio, 4),
            "duration": round(self.duration, 4),
            "reason": self.reason,
            "tokens": [asdict(t) for t in self.tokens],
            "scenes": [asdict(s) for s in self.scenes],
        }

    @classmethod
    def from_json(cls, d: dict) -> "Alignment":
        return cls(
            method=d["method"], fallback=d["fallback"], match_ratio=d["match_ratio"],
            duration=d["duration"], reason=d.get("reason", ""),
            tokens=[AlignedToken(**t) for t in d["tokens"]],
            scenes=[SceneSpan(**s) for s in d["scenes"]],
        )


def _token_info(raw: str):
    """(display, normalized_words, sentence_end, comma) for one whitespace token; None if empty."""
    norm = normalize_token(raw)
    if not norm:
        return None
    tail = raw.rstrip("\"'”’)]")
    display = raw.strip(_EDGE_PUNCT) or raw
    return display, norm, tail.endswith(_SENTENCE_END), tail.endswith(_CLAUSE_END)


def script_tokens(text: str) -> list:
    return [info for info in (_token_info(r) for r in text.split()) if info]


def _whisper_subwords(words: list):
    subwords, times = [], []
    for wd in words:
        if "start" not in wd or "end" not in wd:
            continue
        for w in normalize_token(wd.get("word", "")):
            subwords.append(w)
            times.append((float(wd["start"]), float(wd["end"])))
    return subwords, times


def _interpolate(t0: list, t1: list, duration: float) -> None:
    """Fill unmatched runs evenly between matched neighbours (0.0 / duration at the edges)."""
    n = len(t0)
    i = 0
    while i < n:
        if t0[i] is not None:
            i += 1
            continue
        j = i
        while j < n and t0[j] is None:
            j += 1
        left = t1[i - 1] if i > 0 else 0.0
        right = max(t0[j] if j < n else duration, left)
        step = (right - left) / (j - i)
        for k in range(i, j):
            t0[k] = left + step * (k - i)
            t1[k] = left + step * (k - i + 1)
        i = j
    for k in range(1, n):
        t0[k] = max(t0[k], t0[k - 1])
        t1[k] = max(t1[k], t0[k])


def _enforce_min_gaps(starts: list, duration: float) -> list:
    """Strictly increasing scene starts, every scene >= MIN_SCENE, first scene starts at 0."""
    n = len(starts)
    if n == 0:
        return []
    if duration < n * MIN_SCENE:
        return [duration * k / n for k in range(n)]
    out = list(starts)
    out[0] = 0.0
    for k in range(1, n):
        out[k] = max(out[k], out[k - 1] + MIN_SCENE)
    for k in range(n - 1, 0, -1):
        upper = duration if k == n - 1 else out[k + 1]
        out[k] = min(out[k], upper - MIN_SCENE)
    return out


def _spans(starts: list, duration: float) -> list:
    return [(starts[k], starts[k + 1] if k + 1 < len(starts) else duration) for k in range(len(starts))]


def _fallback_tokens(words: list, narration: str, duration: float) -> list:
    tokens = []
    for wd in words:
        info = _token_info(wd.get("word", "").strip())
        if info and "start" in wd and "end" in wd:
            tokens.append(AlignedToken(info[0], round(float(wd["start"]), 3), round(float(wd["end"]), 3),
                                       False, info[2], info[3]))
    if tokens:
        return tokens
    infos = script_tokens(narration)
    weights = [len(i[0]) + 1 for i in infos]
    total = sum(weights) or 1
    acc = 0.0
    for info, w in zip(infos, weights):
        a = duration * acc / total
        acc += w
        tokens.append(AlignedToken(info[0], round(a, 3), round(duration * acc / total, 3), False, info[2], info[3]))
    return tokens


def word_count_alignment(words: list, scene_texts: list, narration: str, duration: float,
                         num_scenes: int, reason: str, match_ratio: float = 0.0) -> Alignment:
    """Spec §5 step 5 fallback: scene lengths proportional to scene word counts."""
    n = max(num_scenes, 1)
    if scene_texts and len(scene_texts) == n:
        weights = [max(len(t.split()), 1) for t in scene_texts]
        texts = list(scene_texts)
    else:
        weights = [1] * n
        texts = [""] * n
    total = sum(weights)
    starts, acc = [], 0
    for w in weights:
        starts.append(duration * acc / total)
        acc += w
    starts = _enforce_min_gaps(starts, duration)
    tokens = _fallback_tokens(words, narration, duration)
    scenes = []
    for si, (s0, s1) in enumerate(_spans(starts, duration)):
        idx = [i for i, t in enumerate(tokens)
               if s0 <= (t.t0 + t.t1) / 2 < s1 or (si == n - 1 and (t.t0 + t.t1) / 2 >= s1)]
        first = idx[0] if idx else (scenes[-1].last_token if scenes else 0)
        last = idx[-1] + 1 if idx else first
        scenes.append(SceneSpan(si, round(s0, 4), round(s1, 4), texts[si], first, last))
    return Alignment("word_count", True, match_ratio, duration, tokens, scenes, reason)


def align_words(words: list, scene_texts: list, narration: str, duration: float,
                num_scenes: Optional[int] = None) -> Alignment:
    """Pure alignment of Whisper words (whisper's dict format) to the script's scene_texts."""
    n = num_scenes or len(scene_texts) or 1
    if not scene_texts:
        return word_count_alignment(words, [], narration, duration, n, reason="scene_texts_missing")
    if len(scene_texts) != n:
        return word_count_alignment(words, scene_texts, narration, duration, n, reason="scene_count_mismatch")
    per_scene = [script_tokens(t) for t in scene_texts]
    joined = [w for toks in per_scene for tok in toks for w in tok[1]]
    narr = [w for tok in script_tokens(narration) for w in tok[1]]
    if not joined or joined != narr:
        return word_count_alignment(words, scene_texts, narration, duration, n, reason="scene_texts_do_not_join")

    flat = [(si, tok) for si, toks in enumerate(per_scene) for tok in toks]
    s_words, s_owner = [], []
    for ti, (_, tok) in enumerate(flat):
        for w in tok[1]:
            s_words.append(w)
            s_owner.append(ti)
    w_words, w_times = _whisper_subwords(words)

    # autojunk=False: with autojunk on, words like "the" are ignored once a sequence has 200+ items.
    sm = difflib.SequenceMatcher(None, s_words, w_words, autojunk=False)
    t0 = [None] * len(flat)
    t1 = [None] * len(flat)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            ti = s_owner[a + k]
            st, en = w_times[b + k]
            t0[ti] = st if t0[ti] is None else min(t0[ti], st)
            t1[ti] = en if t1[ti] is None else max(t1[ti], en)
    matched = [x is not None for x in t0]
    ratio = sum(matched) / len(flat)
    if ratio < MATCH_THRESHOLD:
        return word_count_alignment(words, scene_texts, narration, duration, n,
                                    reason="low_match_ratio", match_ratio=ratio)

    _interpolate(t0, t1, duration)
    tokens = [AlignedToken(tok[0], round(t0[i], 3), round(t1[i], 3), matched[i], tok[2], tok[3])
              for i, (_, tok) in enumerate(flat)]
    owners = [si for si, _ in flat]

    starts, ranges, cursor = [], [], 0
    for si in range(n):
        idx = [i for i, o in enumerate(owners) if o == si]
        if idx:
            starts.append(tokens[idx[0]].t0)
            ranges.append((idx[0], idx[-1] + 1))
            cursor = idx[-1] + 1
        else:  # empty scene text: zero length here, widened by _enforce_min_gaps
            starts.append(tokens[cursor - 1].t1 if cursor else 0.0)
            ranges.append((cursor, cursor))
    starts = _enforce_min_gaps(starts, duration)
    scenes = [SceneSpan(si, round(s0, 4), round(s1, 4), scene_texts[si], ranges[si][0], ranges[si][1])
              for si, (s0, s1) in enumerate(_spans(starts, duration))]
    return Alignment("whisper+script", False, ratio, duration, tokens, scenes)


# ---------------------------------------------------------------- Whisper I/O

_MODELS: dict = {}
_MODEL_LOCK = threading.Lock()
_TRANSCRIBE_LOCK = threading.Lock()


def _load_whisper(name: str):
    with _MODEL_LOCK:
        if name not in _MODELS:
            import whisper
            logger.info("Loading Whisper '%s' model...", name)
            _MODELS[name] = whisper.load_model(name)
        return _MODELS[name]


def _audio_16k(audio_path) -> np.ndarray:
    """Decode with MoviePy's bundled ffmpeg so Whisper does not need ffmpeg on PATH."""
    from moviepy import AudioFileClip
    with AudioFileClip(str(audio_path)) as clip:
        arr = clip.to_soundarray(fps=16000)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    return np.ascontiguousarray(arr, dtype=np.float32)


def transcribe_words(audio_path, model_name: str) -> list:
    """Whisper word timings as [{"word", "start", "end"}] (whisper's own word-dict keys)."""
    model = _load_whisper(model_name)
    audio = _audio_16k(audio_path)
    with _TRANSCRIBE_LOCK:  # whisper models are not thread-safe; concurrent jobs take turns
        result = model.transcribe(audio, word_timestamps=True, language="en", fp16=False)
    return [{"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
            for seg in result.get("segments", []) for w in seg.get("words", [])]


def align(audio_path, scene_texts: list, narration: str, duration: float, *,
          num_scenes: Optional[int] = None, model_name: Optional[str] = None):
    """Transcribe + align. Returns (Alignment, whisper_words). Never raises for Whisper failures."""
    from app.config import settings
    n = num_scenes or len(scene_texts) or 1
    try:
        words = transcribe_words(audio_path, model_name or settings.whisper_model)
    except Exception as e:  # noqa: BLE001 - any Whisper failure becomes a reported fallback
        logger.warning("Whisper transcription failed, using word-count split: %s", e)
        return word_count_alignment([], scene_texts, narration, duration, n,
                                    reason=f"transcription_failed: {e}"), []
    return align_words(words, scene_texts, narration, duration, num_scenes=n), words
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_align.py -q --tb=short -p no:cacheprovider`
Expected: `10 passed`

- [ ] **Step 7: Commit**

```bash
git add app/cin/align.py tests/__init__.py tests/conftest.py tests/fixtures/words_rolex_40s.json tests/fixtures/words_gold_8s.json tests/test_cin_align.py
git commit -m "feat: align Whisper word timings to script tokens with word-count fallback" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Shot-plan contract and clip segment planning

The `shot_plan.json` dataclasses (spec §6.6) and the pre-generation half of clip sourcing (spec §6.4): one segment per scene, `scene_len + 0.5 s` snapped up to the model's lengths, scenes too long for the model split at the best word gap near the middle.

**Files:**
- Create: `app/cin/shot_plan.py` (data types, `word_gaps`, `plan_segments`; Task 6 appends the planner)
- Test: `tests/test_cin_segments.py`

**Interfaces:**
- Consumes: `Alignment` (Task 4); `snap_duration`, `max_duration` (Task 2).
- Produces (`app/cin/shot_plan.py`):
  - constants `PACING`, `HANDLE = 0.5`, `MIN_SPEED = 0.87`, `FPS = 30`, `FRAMINGS = (1.0, 1.18)`, `TRANSITION_LEN = 0.3`, `MAX_TRANSITIONS = 3`, `TRANSITION_CYCLE = ("flash", "zoom_through", "whip_pan")`, `STILL_MOVE = "push_in"`, `MIN_PIECE = 0.25`, `RELAX_STEPS`
  - `Gap(t, length, score)`; `word_gaps(alignment) -> list[Gap]`
  - `SegmentRequest(scene: int, index: int, t0: float, t1: float, requested_len: float, chained: bool)` with `.name` → `"scene01_b"`
  - `ClipSpec(scene, index, t0, t1, requested_len, start_image: str, path: Optional[str] = None, duration: float = 0.0, last_frame: Optional[str] = None, failed: bool = False, model: str = "", attempts: int = 0)` — the input to `build_shot_plan`
  - JSON types: `Segment(t0, t1, clip, requested_len, start_image)`, `Scene(index, t0, t1, text, segments)`, `ShotSource(type, path, clip_t0=0.0, clip_t1=0.0, speed=1.0, move="")`, `Shot(index, scene, t0, t1, source, framing=1.0, transition_in="cut")`, `CaptionWord(text, t0, t1)`, `CaptionGroup(t0, t1, words)`, `ShotPlan(duration, fps, pacing, alignment: dict, scenes, shots, captions, sfx=[], music=None, hook_headline=None, version=1, warnings=[])` with `to_json()`, `from_json(d)`, `save(path)`, `load(path)`. `warnings` is not serialized.
  - `plan_segments(alignment, durations: Optional[tuple[float, ...]]) -> list[SegmentRequest]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_segments.py`:

```python
"""Clip segment planning + shot_plan.json contract (spec §6.4, §6.6)."""
import json

from app.cin.shot_plan import (
    CaptionGroup, CaptionWord, Scene, Segment, Shot, ShotPlan, ShotSource, plan_segments,
)
from tests.conftest import fixture_alignment

HAILUO = (6.0,)
KLING = (5.0, 10.0)


def test_short_scene_snaps_up_to_fixed_model_length():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), HAILUO)
    assert (segs[0].scene, segs[0].t0, segs[0].t1, segs[0].requested_len) == (0, 0.0, 2.32, 6.0)


def test_scene_longer_than_model_max_splits_at_best_gap_near_middle():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), HAILUO)
    scene1 = [s for s in segs if s.scene == 1]
    # 5.68 s + 0.5 s handle > 6 s: split at the comma pause after "car," (5.81 -> 5.96)
    assert [(s.t0, s.t1) for s in scene1] == [(2.32, 5.885), (5.885, 8.0)]
    assert [s.chained for s in scene1] == [False, True]
    assert [s.name for s in scene1] == ["scene01_a", "scene01_b"]
    assert all(s.requested_len == 6.0 for s in scene1)


def test_choice_model_snaps_to_smallest_sufficient_length():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), KLING)
    assert [(s.scene, s.requested_len) for s in segs] == [(0, 5.0), (1, 10.0)]


def test_unlimited_model_requests_exact_length_and_never_splits():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), None)
    assert [(s.scene, s.requested_len) for s in segs] == [(0, 2.82), (1, 6.18)]


def test_rolex_every_segment_fits_hailuo():
    segs = plan_segments(fixture_alignment("words_rolex_40s.json"), HAILUO)
    assert len(segs) == 11
    assert all(s.t1 - s.t0 + 0.5 <= 6.0 + 1e-6 for s in segs)
    assert segs[0].t0 == 0.0 and segs[-1].t1 == 40.12
    assert all(a.t1 == b.t0 for a, b in zip(segs, segs[1:]))


def _sample_plan() -> ShotPlan:
    return ShotPlan(
        duration=2.21, fps=30, pacing="standard",
        alignment={"method": "whisper+script", "fallback": False, "match_ratio": 0.94},
        scenes=[Scene(0, 0.0, 2.21, "This watch costs more than a car.",
                      [Segment(0.0, 2.21, "sources/clips/scene00_a.mp4", 6.0, "sources/images/scene00.png")])],
        shots=[Shot(0, 0, 0.0, 1.10, ShotSource("clip", "sources/clips/scene00_a.mp4", 0.0, 1.10, 1.0), 1.0, "cut"),
               Shot(1, 0, 1.10, 2.21, ShotSource("still", "sources/images/scene00.png", move="push_in"), 1.18, "cut")],
        captions=[CaptionGroup(0.0, 0.62, [CaptionWord("THIS", 0.0, 0.21)])],
    )


def test_shot_plan_json_matches_contract_keys():
    d = _sample_plan().to_json()
    assert set(d) == {"version", "duration", "fps", "pacing", "alignment", "scenes", "shots",
                      "captions", "sfx", "music", "hook_headline"}
    assert d["version"] == 1 and d["sfx"] == [] and d["music"] is None and d["hook_headline"] is None
    assert set(d["scenes"][0]) == {"index", "t0", "t1", "text", "segments"}
    assert set(d["scenes"][0]["segments"][0]) == {"t0", "t1", "clip", "requested_len", "start_image"}
    assert set(d["shots"][0]) == {"index", "scene", "t0", "t1", "source", "framing", "transition_in"}
    assert set(d["shots"][0]["source"]) == {"type", "path", "clip_t0", "clip_t1", "speed"}
    assert d["shots"][1]["source"] == {"type": "still", "path": "sources/images/scene00.png", "move": "push_in"}
    assert d["captions"][0] == {"t0": 0.0, "t1": 0.62, "words": [{"text": "THIS", "t0": 0.0, "t1": 0.21}]}


def test_shot_plan_roundtrip_through_file(tmp_path):
    plan = _sample_plan()
    path = tmp_path / "shot_plan.json"
    plan.save(path)
    assert "\\" not in path.read_text(encoding="utf-8")       # job-relative posix paths only
    assert ShotPlan.load(path).to_json() == json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_segments.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cin.shot_plan'`.

- [ ] **Step 3: Implement the first half of `app/cin/shot_plan.py`**

```python
"""Shot planner (spec §6). Pure functions — no I/O, no rendering.

Two phases around clip generation:
  plan_segments(alignment, durations)  -> [SegmentRequest]  (what clips to ask for)
  build_shot_plan(alignment, pacing, clip_specs) -> ShotPlan  (how to cut what came back)
ShotPlan.to_json() is the shot_plan.json contract (spec §6.6).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.cin.align import Alignment
from app.motion_gen import max_duration, snap_duration

# spec §6.1 — (target, min, max) seconds
PACING = {
    "calm": (4.2, 3.5, 5.0),
    "standard": (2.8, 2.2, 3.5),
    "fast": (2.1, 1.8, 2.5),
}
HANDLE = 0.5                 # spec §6.4: requested clip length = scene length + 0.5 s
MIN_SPEED = 0.87             # spec §6.4: footage short by <= 15 % is slowed, never below 0.87x
FPS = 30
FRAMINGS = (1.0, 1.18)       # spec §6.3: full frame / punch-in
TRANSITION_LEN = 0.3         # spec §6.5
MAX_TRANSITIONS = 3
TRANSITION_CYCLE = ("flash", "zoom_through", "whip_pan")
STILL_MOVE = "push_in"
MIN_PIECE = 0.25             # never emit a footage/still sliver shorter than this
# When gap positions make [min, max] infeasible for a segment longer than max, relax the bounds
# step by step instead of leaving one over-long shot (spec §6.2 only defines the short-scene case).
RELAX_STEPS = ((1.0, 1.0), (0.8, 1.25), (0.0, 1.5))
_EPS = 1e-6


# ------------------------------------------------------------------ data types

@dataclass
class Gap:
    t: float          # cut time (middle of the silence between two words)
    length: float     # silence length in seconds
    score: float      # spec §6.2: gap + 0.5 sentence end + 0.25 comma


@dataclass
class SegmentRequest:
    """One clip to generate (spec §6.4). Planned before any paid generation."""
    scene: int
    index: int               # 0 -> "a", 1 -> "b", ...
    t0: float
    t1: float
    requested_len: float
    chained: bool            # True: start image is the previous segment's last frame

    @property
    def name(self) -> str:
        return f"scene{self.scene:02d}_{'abcdefghijklmnopqrstuvwxyz'[self.index]}"


@dataclass
class ClipSpec:
    """What clip generation produced for one segment — the input to build_shot_plan."""
    scene: int
    index: int
    t0: float
    t1: float
    requested_len: float
    start_image: str                  # job-relative posix path
    path: Optional[str] = None        # job-relative posix path of the clip; None = no footage
    duration: float = 0.0             # real clip length (s)
    last_frame: Optional[str] = None  # job-relative posix path of the clip's last frame PNG
    failed: bool = False              # generation was attempted and failed -> still_fallback
    model: str = ""                   # model that produced the clip (cost logging)
    attempts: int = 0


@dataclass
class Segment:
    t0: float
    t1: float
    clip: Optional[str]
    requested_len: float
    start_image: str

    def to_json(self) -> dict:
        return {"t0": round(self.t0, 3), "t1": round(self.t1, 3), "clip": self.clip,
                "requested_len": round(self.requested_len, 3), "start_image": self.start_image}


@dataclass
class Scene:
    index: int
    t0: float
    t1: float
    text: str
    segments: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"index": self.index, "t0": round(self.t0, 3), "t1": round(self.t1, 3),
                "text": self.text, "segments": [s.to_json() for s in self.segments]}


@dataclass
class ShotSource:
    type: str                 # "clip" | "still"
    path: str                 # job-relative posix path
    clip_t0: float = 0.0
    clip_t1: float = 0.0
    speed: float = 1.0
    move: str = ""            # stills only

    def to_json(self) -> dict:
        if self.type == "still":
            return {"type": "still", "path": self.path, "move": self.move or STILL_MOVE}
        return {"type": "clip", "path": self.path, "clip_t0": round(self.clip_t0, 3),
                "clip_t1": round(self.clip_t1, 3), "speed": round(self.speed, 4)}


@dataclass
class Shot:
    index: int
    scene: int
    t0: float
    t1: float
    source: ShotSource
    framing: float = 1.0
    transition_in: str = "cut"

    def to_json(self) -> dict:
        return {"index": self.index, "scene": self.scene, "t0": round(self.t0, 3),
                "t1": round(self.t1, 3), "source": self.source.to_json(),
                "framing": self.framing, "transition_in": self.transition_in}


@dataclass
class CaptionWord:
    text: str
    t0: float
    t1: float


@dataclass
class CaptionGroup:
    t0: float
    t1: float
    words: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"t0": round(self.t0, 3), "t1": round(self.t1, 3),
                "words": [{"text": w.text, "t0": round(w.t0, 3), "t1": round(w.t1, 3)} for w in self.words]}


@dataclass
class ShotPlan:
    duration: float
    fps: int
    pacing: str
    alignment: dict
    scenes: list
    shots: list
    captions: list
    sfx: list = field(default_factory=list)          # Phase C fills this
    music: Optional[dict] = None                      # Phase C fills this
    hook_headline: Optional[dict] = None              # Phase B fills this
    version: int = 1
    warnings: list = field(default_factory=list)      # planner warnings for run_report; not serialized

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "duration": round(self.duration, 3),
            "fps": self.fps,
            "pacing": self.pacing,
            "alignment": self.alignment,
            "scenes": [s.to_json() for s in self.scenes],
            "shots": [s.to_json() for s in self.shots],
            "captions": [c.to_json() for c in self.captions],
            "sfx": self.sfx,
            "music": self.music,
            "hook_headline": self.hook_headline,
        }

    @classmethod
    def from_json(cls, d: dict) -> "ShotPlan":
        scenes = [Scene(s["index"], s["t0"], s["t1"], s["text"],
                        [Segment(g["t0"], g["t1"], g["clip"], g["requested_len"], g["start_image"])
                         for g in s["segments"]]) for s in d["scenes"]]
        shots = []
        for s in d["shots"]:
            src = s["source"]
            if src["type"] == "still":
                source = ShotSource("still", src["path"], move=src.get("move", STILL_MOVE))
            else:
                source = ShotSource("clip", src["path"], src["clip_t0"], src["clip_t1"], src["speed"])
            shots.append(Shot(s["index"], s["scene"], s["t0"], s["t1"], source, s["framing"], s["transition_in"]))
        captions = [CaptionGroup(c["t0"], c["t1"], [CaptionWord(w["text"], w["t0"], w["t1"]) for w in c["words"]])
                    for c in d["captions"]]
        return cls(duration=d["duration"], fps=d["fps"], pacing=d["pacing"], alignment=d["alignment"],
                   scenes=scenes, shots=shots, captions=captions, sfx=d.get("sfx", []),
                   music=d.get("music"), hook_headline=d.get("hook_headline"), version=d.get("version", 1))

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "ShotPlan":
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------------ gaps

def word_gaps(alignment: Alignment) -> list:
    """Candidate cut points: the silence between every pair of consecutive tokens."""
    gaps = []
    toks = alignment.tokens
    for a, b in zip(toks, toks[1:]):
        length = max(0.0, b.t0 - a.t1)
        score = length + (0.5 if a.sentence_end else 0.0) + (0.25 if a.comma else 0.0)
        gaps.append(Gap(t=round(a.t1 + length / 2, 4), length=length, score=score))
    return gaps


def _inside(gaps: list, t0: float, t1: float, margin: float = 0.0) -> list:
    return [g for g in gaps if t0 + margin + _EPS < g.t < t1 - margin - _EPS]


# ------------------------------------------------------------------ segments (spec §6.4)

def _best_cut_near_middle(t0: float, t1: float, gaps: list) -> float:
    length = t1 - t0
    mid = t0 + length / 2
    window = [g for g in gaps if t0 + 0.3 * length <= g.t <= t0 + 0.7 * length]
    if window:
        return max(window, key=lambda g: (g.score, -abs(g.t - mid))).t
    inner = _inside(gaps, t0, t1, margin=0.5)
    if inner:
        return min(inner, key=lambda g: abs(g.t - mid)).t
    return mid


def _split_span(t0: float, t1: float, gaps: list, limit: float) -> list:
    if (t1 - t0) + HANDLE <= limit + _EPS:
        return [(t0, t1)]
    cut = _best_cut_near_middle(t0, t1, _inside(gaps, t0, t1))
    return _split_span(t0, cut, gaps, limit) + _split_span(cut, t1, gaps, limit)


def plan_segments(alignment: Alignment, durations) -> list:
    """One clip per scene of scene_len + HANDLE, snapped up to a supported model length.
    Scenes too long for the model's longest clip are split at the best word gap near the middle.
    durations=None means any length (local model or motion disabled)."""
    gaps = word_gaps(alignment)
    limit = max_duration(durations)
    out = []
    for sc in alignment.scenes:
        for i, (a, b) in enumerate(_split_span(sc.t0, sc.t1, gaps, limit)):
            req = snap_duration(b - a + HANDLE, durations)
            out.append(SegmentRequest(sc.index, i, round(a, 4), round(b, 4), req, chained=i > 0))
    return out
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_segments.py -q --tb=short -p no:cacheprovider`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add app/cin/shot_plan.py tests/test_cin_segments.py
git commit -m "feat: shot_plan.json contract and clip segment planning" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Shot planner — cuts, framing, speed rule, stills, transitions, captions

`build_shot_plan` (spec §6.2–6.5). Replaces `plan_cuts` (`app/cin/multishot.py:39-77`), whose output `_render_scene` never read (`app/cinematic.py:72-98, 202`); `multishot.py` and its test are deleted in Task 12 together with `app/cinematic.py`.

**Files:**
- Modify: `app/cin/shot_plan.py` (append)
- Test: `tests/test_cin_shot_plan.py`

**Interfaces:**
- Consumes: everything Task 5 produced.
- Produces: `choose_cuts(t0, t1, gaps, target, lo, hi) -> list[float]`; `build_shot_plan(alignment: Alignment, pacing: str, clip_specs: list[ClipSpec], *, fps: int = FPS) -> ShotPlan` (raises `ValueError` for unknown pacing or a scene without specs). `plan.warnings` holds `{"code", "message", "detail"}` dicts with codes `speed_adjusted` and `still_fallback`.
- Rules implemented: segment boundaries are forced cuts; within a segment, DP over word gaps (relaxed per `RELAX_STEPS` only when a segment longer than `max` has no valid set); framing alternates `1.0`/`1.18` per shot within a scene; footage short by ≤ 15 % → `speed = clip_len / seg_len` (≥ 0.87) and clip times scale by it; shorter footage → clip until it runs out, then a still from the clip's last frame (no piece shorter than `MIN_PIECE`); failed segment → stills from the start image; up to 3 scene boundaries with the longest preceding pause get `flash`, `zoom_through`, `whip_pan` in time order (both neighbouring shots ≥ 0.3 s); captions are ≤ 3-token groups broken after punctuation (Phase A; Phase B replaces the grouping).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_shot_plan.py`:

```python
"""Shot planner: pacing, cut placement, framing, speed rule, stills, transitions (spec §6)."""
import pytest

from app.cin.align import align_words
from app.cin.shot_plan import (
    FRAMINGS, PACING, ClipSpec, build_shot_plan, plan_segments, word_gaps,
)
from tests.conftest import fixture_alignment

HAILUO = (6.0,)
KLING = (5.0, 10.0)


def specs_for(segs, length=lambda s: s.requested_len, path=True, failed=False):
    return [ClipSpec(s.scene, s.index, s.t0, s.t1, s.requested_len, f"sources/images/scene{s.scene:02d}.png",
                     path=f"sources/clips/{s.name}.mp4" if path else None,
                     duration=length(s) if path else 0.0,
                     last_frame=f"sources/clips/{s.name}_last.png" if path else None,
                     failed=failed)
            for s in segs]


def rolex_plan(pacing):
    a = fixture_alignment("words_rolex_40s.json")
    segs = plan_segments(a, HAILUO)
    return a, segs, build_shot_plan(a, pacing, specs_for(segs))


def assert_contiguous(plan):
    assert plan.shots[0].t0 == 0.0
    assert plan.shots[-1].t1 == plan.duration
    assert all(a.t1 == b.t0 for a, b in zip(plan.shots, plan.shots[1:]))
    assert all(s.t1 > s.t0 for s in plan.shots)


@pytest.mark.parametrize("pacing", sorted(PACING))
def test_shots_respect_pacing_bounds(pacing):
    a, segs, plan = rolex_plan(pacing)
    target, lo, hi = PACING[pacing]
    assert_contiguous(plan)
    seg_bounds = {(s.t0, s.t1) for s in segs}
    for shot in plan.shots:
        length = shot.t1 - shot.t0
        whole_segment = (shot.t0, shot.t1) in seg_bounds
        assert whole_segment or lo * 0.8 - 1e-6 <= length <= hi * 1.25 + 1e-6, (pacing, shot)


def test_faster_pacing_means_more_shots():
    counts = {p: len(rolex_plan(p)[2].shots) for p in PACING}
    assert counts["calm"] < counts["standard"] < counts["fast"]


def test_cuts_land_on_word_gaps_or_segment_boundaries():
    a, segs, plan = rolex_plan("fast")
    allowed = {g.t for g in word_gaps(a)} | {s.t0 for s in segs} | {40.12}
    assert all(s.t0 in allowed for s in plan.shots)


def test_long_segment_with_awkward_gaps_is_still_cut():
    # gold scene 1 is 5.68 s; strict fast bounds [1.8, 2.5] admit no cut set, relaxed bounds do
    a = fixture_alignment("words_gold_8s.json")
    plan = build_shot_plan(a, "fast", specs_for(plan_segments(a, KLING)))
    assert [(s.t0, s.t1) for s in plan.shots] == [(0.0, 2.32), (2.32, 4.245), (4.245, 5.885), (5.885, 8.0)]


def test_adjacent_shots_from_same_source_never_share_framing():
    for pacing in PACING:
        _, _, plan = rolex_plan(pacing)
        for x, y in zip(plan.shots, plan.shots[1:]):
            if x.source.path == y.source.path:
                assert x.framing != y.framing
        assert {s.framing for s in plan.shots} <= set(FRAMINGS)


def test_shot_plays_its_segment_clip_window():
    a = fixture_alignment("words_gold_8s.json")
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, HAILUO)))
    last = plan.shots[-1]
    assert last.source.path == "sources/clips/scene01_b.mp4"
    assert last.source.clip_t0 == pytest.approx(0.0)
    assert last.source.clip_t1 == pytest.approx(8.0 - 5.885)


def test_footage_short_by_at_most_15_percent_is_slowed():
    a = fixture_alignment("words_gold_8s.json")
    segs = plan_segments(a, KLING)
    plan = build_shot_plan(a, "standard", specs_for(segs, length=lambda s: (s.t1 - s.t0) * 0.9))
    assert all(s.source.speed == pytest.approx(0.9) for s in plan.shots)
    assert plan.shots[-1].source.clip_t1 == pytest.approx((8.0 - 2.32) * 0.9)
    assert [w["code"] for w in plan.warnings] == ["speed_adjusted", "speed_adjusted"]


def test_footage_short_by_more_than_15_percent_gets_a_still_tail():
    a = fixture_alignment("words_gold_8s.json")
    segs = plan_segments(a, KLING)
    plan = build_shot_plan(a, "standard", specs_for(segs, length=lambda s: (s.t1 - s.t0) * 0.5))
    assert_contiguous(plan)
    assert [(s.t0, s.t1, s.source.type) for s in plan.shots] == [
        (0.0, 1.16, "clip"), (1.16, 2.32, "still"), (2.32, 5.195, "clip"), (5.195, 8.0, "still")]
    assert plan.shots[1].source.path == "sources/clips/scene00_a_last.png"
    assert [w["code"] for w in plan.warnings] == ["still_fallback", "still_fallback"]


def test_failed_clips_become_push_in_stills_with_warnings():
    a = fixture_alignment("words_gold_8s.json")
    segs = plan_segments(a, HAILUO)
    plan = build_shot_plan(a, "standard", specs_for(segs, path=False, failed=True))
    assert all(s.source.type == "still" and s.source.move == "push_in" for s in plan.shots)
    assert {s.source.path for s in plan.shots} == {"sources/images/scene00.png", "sources/images/scene01.png"}
    assert [w["code"] for w in plan.warnings] == ["still_fallback"] * len(segs)


def test_motion_disabled_stills_are_not_reported_as_failures():
    a = fixture_alignment("words_gold_8s.json")
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None), path=False))
    assert all(s.source.type == "still" for s in plan.shots)
    assert plan.warnings == []


def _synthetic(pauses):
    """len(pauses)+1 one-sentence scenes; the pause before scene k is pauses[k-1]."""
    words, t, texts = [], 0.0, []
    for k in range(len(pauses) + 1):
        sentence = [f"w{k}a", f"w{k}b", f"w{k}c", f"w{k}d."]
        texts.append(" ".join(sentence))
        for i, w in enumerate(sentence):
            words.append({"word": " " + w, "start": round(t, 3), "end": round(t + 0.5, 3)})
            t += 0.55
        if k < len(pauses):
            t += pauses[k]
    narration = " ".join(texts)
    return align_words(words, texts, narration, round(t + 0.3, 3))


def test_transitions_go_to_longest_pauses_max_three():
    a = _synthetic([0.9, 0.2, 0.6, 0.4])
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)))
    styled = [(s.scene, s.transition_in) for s in plan.shots if s.transition_in != "cut"]
    assert styled == [(1, "flash"), (3, "zoom_through"), (4, "whip_pan")]   # 0.2 s pause loses
    assert plan.shots[0].transition_in == "cut"
    assert all(s.t0 == plan.scenes[s.scene].t0 for s in plan.shots if s.transition_in != "cut")


def test_very_short_narration_is_one_shot():
    a = align_words([{"word": " Hi", "start": 0.1, "end": 0.4}, {"word": " there.", "start": 0.45, "end": 0.9}],
                    ["Hi there."], "Hi there.", 1.2)
    plan = build_shot_plan(a, "fast", specs_for(plan_segments(a, HAILUO)))
    assert [(s.t0, s.t1) for s in plan.shots] == [(0.0, 1.2)]


def test_scene_shorter_than_min_is_one_shot():
    a = _synthetic([0.1, 0.1, 0.1])        # 2.25 s scenes
    plan = build_shot_plan(a, "calm", specs_for(plan_segments(a, None)))
    assert len(plan.shots) == len(plan.scenes)


def test_captions_use_script_spelling_in_groups_of_three():
    _, _, plan = rolex_plan("standard")
    words = [w.text for g in plan.captions for w in g.words]
    assert "Wilsdorf" in words and "Wils" not in words
    assert all(1 <= len(g.words) <= 3 for g in plan.captions)
    assert [w.text for w in plan.captions[0].words] == ["This", "watch", "costs"]


def test_unknown_pacing_rejected():
    a = fixture_alignment("words_gold_8s.json")
    with pytest.raises(ValueError):
        build_shot_plan(a, "hyper", specs_for(plan_segments(a, None)))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_shot_plan.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ImportError: cannot import name 'build_shot_plan' from 'app.cin.shot_plan'`.

- [ ] **Step 3: Append the planner to `app/cin/shot_plan.py`**

```python
# ------------------------------------------------------------------ cuts (spec §6.2)

def choose_cuts(t0: float, t1: float, gaps: list, target: float, lo: float, hi: float) -> list:
    """Cut times inside [t0, t1]: every shot in [lo, hi], minimising
    sum((len - target)^2) - sum(score). A segment shorter than lo is one shot ([]).
    A longer segment whose gaps admit no valid set is retried with RELAX_STEPS bounds."""
    if t1 - t0 <= hi + _EPS:
        lo_eff = min(lo, t1 - t0)
        return _dp_cuts(t0, t1, gaps, target, lo_eff, hi) or []
    for lo_k, hi_k in RELAX_STEPS:
        cuts = _dp_cuts(t0, t1, gaps, target, lo * lo_k, hi * hi_k)
        if cuts is not None:
            return cuts
    return []


def _dp_cuts(t0: float, t1: float, gaps: list, target: float, lo: float, hi: float):
    """Optimal cut list, or None when no cut set keeps every shot within [lo, hi]."""
    cands = _inside(gaps, t0, t1)
    points = [t0] + [g.t for g in cands] + [t1]
    scores = [0.0] + [g.score for g in cands] + [0.0]
    n = len(points)
    best = [math.inf] * n
    prev = [-1] * n
    best[0] = 0.0
    for j in range(1, n):
        for i in range(j):
            if best[i] == math.inf:
                continue
            length = points[j] - points[i]
            if length < lo - _EPS or length > hi + _EPS:
                continue
            cost = best[i] + (length - target) ** 2 - (scores[j] if j < n - 1 else 0.0)
            if cost < best[j]:
                best[j] = cost
                prev[j] = i
    if best[-1] == math.inf:
        return None
    cuts, j = [], prev[n - 1]
    while j > 0:
        cuts.append(points[j])
        j = prev[j]
    return sorted(cuts)


# ------------------------------------------------------------------ plan

def _warning(code: str, message: str, **detail) -> dict:
    return {"code": code, "message": message, "detail": detail}


def _segment_shots(spec: ClipSpec, bounds: list, warnings: list) -> list:
    """(t0, t1, ShotSource) pieces for one segment, applying the 15 % speed rule (spec §6.4)."""
    seg_len = spec.t1 - spec.t0
    speed, covered = 1.0, spec.t1
    if spec.path and spec.duration > 0 and spec.duration + _EPS < seg_len:
        ratio = spec.duration / seg_len
        if ratio >= MIN_SPEED:
            speed = ratio
            warnings.append(_warning("speed_adjusted", f"{spec.path} slowed to {ratio:.3f}x",
                                     clip=spec.path, speed=round(ratio, 4)))
        else:
            covered = spec.t0 + spec.duration
            warnings.append(_warning("still_fallback", f"{spec.path} is {spec.duration:.2f}s for a "
                                     f"{seg_len:.2f}s segment; tail shown as a still",
                                     clip=spec.path, scene=spec.scene, segment=spec.index,
                                     uncovered=round(spec.t1 - covered, 3)))
    elif not spec.path and spec.failed:
        warnings.append(_warning("still_fallback", f"scene {spec.scene} segment {spec.index}: clip "
                                 "generation failed; still shown", scene=spec.scene, segment=spec.index))

    still_path = spec.last_frame if (spec.path and spec.last_frame) else spec.start_image
    pieces = []
    for a, b in zip(bounds, bounds[1:]):
        if not spec.path:
            pieces.append((a, b, ShotSource("still", spec.start_image, move=STILL_MOVE)))
            continue
        splits = [(a, b)]
        if a + MIN_PIECE <= covered <= b - MIN_PIECE:
            splits = [(a, covered), (covered, b)]
        for x, y in splits:
            if x > covered - MIN_PIECE:
                pieces.append((x, y, ShotSource("still", still_path, move=STILL_MOVE)))
            else:
                pieces.append((x, y, ShotSource("clip", spec.path, (x - spec.t0) * speed,
                                                (y - spec.t0) * speed, speed)))
    return pieces


def _captions(alignment: Alignment) -> list:
    """Phase A grouping: up to 3 script tokens, breaking after punctuation (Phase B replaces this)."""
    groups, current = [], []
    for tok in alignment.tokens:
        current.append(CaptionWord(tok.text, tok.t0, tok.t1))
        if len(current) == 3 or tok.sentence_end or tok.comma:
            groups.append(CaptionGroup(current[0].t0, current[-1].t1, current))
            current = []
    if current:
        groups.append(CaptionGroup(current[0].t0, current[-1].t1, current))
    return groups


def _pick_transitions(alignment: Alignment, shots: list) -> None:
    toks = alignment.tokens
    first_shot = {}
    for i, s in enumerate(shots):
        first_shot.setdefault(s.scene, i)
    candidates = []
    for sc in alignment.scenes[1:]:
        i = first_shot.get(sc.index)
        if i is None or i == 0 or not (0 < sc.first_token < len(toks)):
            continue
        pause = toks[sc.first_token].t0 - toks[sc.first_token - 1].t1
        a, b = shots[i - 1], shots[i]
        if pause > 0 and a.t1 - a.t0 >= TRANSITION_LEN and b.t1 - b.t0 >= TRANSITION_LEN:
            candidates.append((pause, -sc.index, i))
    chosen = sorted(i for _, _, i in sorted(candidates, reverse=True)[:MAX_TRANSITIONS])
    for n, i in enumerate(chosen):
        shots[i].transition_in = TRANSITION_CYCLE[n % len(TRANSITION_CYCLE)]


def build_shot_plan(alignment: Alignment, pacing: str, clip_specs: list, *, fps: int = FPS) -> ShotPlan:
    if pacing not in PACING:
        raise ValueError(f"Unknown pacing {pacing!r}; choose one of {sorted(PACING)}")
    target, lo, hi = PACING[pacing]
    gaps = word_gaps(alignment)
    by_scene = {}
    for spec in clip_specs:
        by_scene.setdefault(spec.scene, []).append(spec)

    scenes, shots, warnings = [], [], []
    for sc in alignment.scenes:
        specs = sorted(by_scene.get(sc.index, []), key=lambda s: s.index)
        if not specs:
            raise ValueError(f"No clip spec for scene {sc.index}")
        scenes.append(Scene(sc.index, sc.t0, sc.t1, sc.text,
                            [Segment(s.t0, s.t1, s.path, s.requested_len, s.start_image) for s in specs]))
        framing_i = 0
        for spec in specs:
            bounds = [spec.t0] + choose_cuts(spec.t0, spec.t1, gaps, target, lo, hi) + [spec.t1]
            for a, b, source in _segment_shots(spec, bounds, warnings):
                shots.append(Shot(len(shots), sc.index, round(a, 4), round(b, 4), source,
                                  FRAMINGS[framing_i % 2]))
                framing_i += 1

    if shots:
        shots[0].t0 = 0.0
        shots[-1].t1 = alignment.duration
    _pick_transitions(alignment, shots)
    return ShotPlan(
        duration=alignment.duration, fps=fps, pacing=pacing,
        alignment={"method": alignment.method, "fallback": alignment.fallback,
                   "match_ratio": round(alignment.match_ratio, 4)},
        scenes=scenes, shots=shots, captions=_captions(alignment), warnings=warnings,
    )
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_shot_plan.py tests/test_cin_segments.py tests/test_cin_align.py -q --tb=short -p no:cacheprovider`
Expected: `34 passed` (17 + 7 + 10)

- [ ] **Step 5: Commit**

```bash
git add app/cin/shot_plan.py tests/test_cin_shot_plan.py
git commit -m "feat: shot planner with phrase-boundary cuts, framing, speed rule and transitions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 7: Job folder, run report, and per-job asset paths

Every run gets `output/<YYYYMMDD_HHMMSS>_<slug>[_N]/` (spec §9.2). Today narration always goes to `assets/temp/audio.mp3` (`app/asset_manager.py:89`) and images to `assets/temp/image_{i}.png` (`app/asset_manager.py:192, 204, 294`), so two concurrent jobs overwrite each other, and `cleanup_temp()` (`app/asset_manager.py:344-348`, called at `main.py:440-452`) deletes paid assets even on failure.

**Files:**
- Create: `app/cin/job.py`, `app/cin/report.py`
- Modify: `app/asset_manager.py:5-8` (import `os`), `:68-106` (`generate_audio`), `:167-211` (`generate_images`), `:265-313` (`_generate_images_fal`, `_generate_images_local`)
- Test: `tests/test_cin_job.py`, `tests/test_cin_report.py`, `tests/test_asset_manager.py` (append)

**Interfaces:**
- Produces (`app/cin/job.py`): `slugify(topic, max_len=40) -> str`; `JobPaths(root: Path)` (frozen) with properties `name, sources, images, clips, narration, words, alignment, shot_plan, mix, final, final_prev, report, render_tmp` and methods `image(scene) -> Path`, `clip(name) -> Path`, `last_frame(name) -> Path`, `rel(path) -> str` (job-relative posix), `resolve(rel) -> Path`, `ensure()`; `create_job(topic, output_dir="output", now: Optional[datetime] = None) -> JobPaths`; `open_job(job_dir) -> JobPaths` (raises `FileNotFoundError` without `sources/`); `prune_sources(output_dir, keep_days: int, now: Optional[float] = None) -> list[Path]`.
- Produces (`app/cin/report.py`): `RunReport(job: str, options: dict = {}, status="running", error=None, warnings=[], loudness=None, platform_safe=None, cost={"estimated": None, "actual": [], "total": 0.0}, durations={}, clips={}, version=1)` with `warn(code, message, detail=None)`, `stage(name)` (context manager accumulating seconds), `to_json()`, `save(path)` (atomic), `RunReport.load(path)`; `WARNING_CODES`.
- Produces (`app/asset_manager.py`): `generate_audio(text, voice_id=None, output_path: Optional[Path] = None) -> AudioResult`; `generate_images(prompts, use_mock=True, output_dir: Optional[Path] = None) -> list[str]` writing `sceneNN.png` into `output_dir` for all four providers (mock, fal, local, replicate). Without the new arguments the legacy temp paths are unchanged.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_job.py`:

```python
"""Job folder layout, naming, path handling and pruning (spec §9.2)."""
import os
import threading
import time
from datetime import datetime

import pytest

from app.cin.job import JobPaths, create_job, open_job, prune_sources, slugify

NOW = datetime(2026, 10, 2, 14, 30, 5)


def test_create_job_layout(tmp_path):
    job = create_job("History of Rolex", tmp_path / "output", now=NOW)
    assert job.name == "20261002_143005_history_of_rolex"
    assert job.images.is_dir() and job.clips.is_dir()
    assert job.narration == job.root / "sources" / "narration.mp3"
    assert job.shot_plan.name == "shot_plan.json" and job.mix.name == "mix.wav"
    assert job.final == job.root / "final.mp4" and job.report == job.root / "run_report.json"
    assert job.image(3).name == "scene03.png"
    assert job.clip("scene03_b").name == "scene03_b.mp4"
    assert job.last_frame("scene03_a").name == "scene03_a_last.png"


def test_create_job_is_unique_under_concurrency(tmp_path):
    out = tmp_path / "output"
    jobs = []
    threads = [threading.Thread(target=lambda: jobs.append(create_job("same topic", out, now=NOW)))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    names = sorted(j.name for j in jobs)
    assert len(set(names)) == 8
    assert "20261002_143005_same_topic" in names and "20261002_143005_same_topic_8" in names


def test_slug_is_windows_safe():
    slug = slugify('Rolex: "Why?" <CON>/..\\x | 100%')
    assert slug == "rolex_why_con_x_100"
    assert slugify("CON") == "con_"
    assert slugify("???") == "video"
    assert len(slugify("a" * 200)) == 40


def test_rel_and_resolve_are_posix_and_relative(tmp_path):
    job = create_job("x", tmp_path / "out dir with spaces", now=NOW)
    rel = job.rel(job.clip("scene00_a"))
    assert rel == "sources/clips/scene00_a.mp4"
    assert job.resolve(rel) == job.clip("scene00_a")
    outside = tmp_path / "elsewhere.mp3"
    assert job.rel(outside) == outside.as_posix()


def test_open_job_requires_sources(tmp_path):
    job = create_job("x", tmp_path, now=NOW)
    assert open_job(job.root) == JobPaths(job.root)
    with pytest.raises(FileNotFoundError):
        open_job(tmp_path / "not_a_job")


def _finished_job(out, topic, age_days):
    job = create_job(topic, out, now=NOW)
    job.final.write_bytes(b"mp4")
    job.report.write_text("{}", encoding="utf-8")
    old = time.time() - age_days * 86400
    os.utime(job.sources, (old, old))
    return job


def test_prune_removes_only_old_sources(tmp_path):
    out = tmp_path / "output"
    old = _finished_job(out, "old", 20)
    fresh = _finished_job(out, "fresh", 1)
    (out / "metadata").mkdir()
    legacy = out / "legacy_job"
    (legacy / "sources").mkdir(parents=True)          # no run_report.json: not ours, never touched
    os.utime(legacy / "sources", (0, 0))

    removed = prune_sources(out, keep_days=14)

    assert removed == [old.sources]
    assert not old.sources.exists() and old.final.exists() and old.report.exists()
    assert fresh.sources.exists()
    assert (out / "metadata").exists() and (legacy / "sources").exists()


def test_prune_disabled_with_zero_days(tmp_path):
    old = _finished_job(tmp_path, "old", 400)
    assert prune_sources(tmp_path, keep_days=0) == []
    assert old.sources.exists()
```

Create `tests/test_cin_report.py`:

```python
"""run_report.json writer (spec §10)."""
import json

from app.cin.report import RunReport


def test_warn_records_code_message_detail():
    report = RunReport(job="j")
    report.warn("still_fallback", "scene 2 is a still", {"scene": 2})
    assert report.warnings == [{"code": "still_fallback", "message": "scene 2 is a still", "detail": {"scene": 2}}]


def test_stage_accumulates_durations():
    report = RunReport(job="j")
    with report.stage("render"):
        pass
    with report.stage("render"):
        pass
    assert set(report.durations) == {"render"} and report.durations["render"] >= 0.0


def test_save_and_load_roundtrip(tmp_path):
    report = RunReport(job="j", options={"pacing": "fast"})
    report.status = "ok"
    report.loudness = {"I": -14.0, "TP": -1.5, "LRA": 4.0}
    report.warn("music_missing", "no music")
    path = tmp_path / "run_report.json"
    report.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "ok" and data["warnings"][0]["code"] == "music_missing"
    assert set(data) >= {"job", "options", "status", "error", "warnings", "loudness",
                         "platform_safe", "cost", "durations", "clips", "version"}
    assert RunReport.load(path).to_json() == data
    assert not (tmp_path / "run_report.json.tmp").exists()


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "run_report.json"
    path.write_text(json.dumps({"job": "j", "status": "ok", "future_field": 1}), encoding="utf-8")
    assert RunReport.load(path).status == "ok"
```

Append to `tests/test_asset_manager.py`:

```python
def test_generate_audio_writes_to_requested_job_path(tmp_path):
    from app.config import settings
    manager = AssetManager()
    response = MagicMock(status_code=200, content=b"fake_audio")
    target = tmp_path / "job" / "sources" / "narration.mp3"
    original_key = settings.elevenlabs_api_key
    try:
        settings.elevenlabs_api_key = "fake_key"
        with patch("app.asset_manager.requests.post", return_value=response), \
                patch.object(manager, "_get_audio_duration", return_value=3.0):
            result = manager.generate_audio("Hello world", output_path=target)
    finally:
        settings.elevenlabs_api_key = original_key
    assert result.file_path == str(target)
    assert target.read_bytes() == b"fake_audio"


def test_mock_images_written_as_scene_files(tmp_path):
    paths = AssetManager().generate_images(["p1", "p2"], use_mock=True, output_dir=tmp_path / "images")
    assert paths == [str(tmp_path / "images" / "scene00.png"), str(tmp_path / "images" / "scene01.png")]
    assert all(Path(p).exists() for p in paths)


def test_fal_images_written_into_output_dir(tmp_path, monkeypatch):
    from app.config import settings
    fal = MagicMock()
    fal.subscribe.return_value = {"images": [{"url": "https://fal.media/img.png"}]}
    monkeypatch.setattr(settings, "image_provider", "fal")
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.asset_manager.requests.get", return_value=MagicMock(status_code=200, content=b"png")):
        paths = AssetManager().generate_images(["a", "b"], use_mock=False, output_dir=tmp_path)
    assert paths == [str(tmp_path / "scene00.png"), str(tmp_path / "scene01.png")]
    assert (tmp_path / "scene01.png").read_bytes() == b"png"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_job.py tests/test_cin_report.py tests/test_asset_manager.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cin.job'`, `No module named 'app.cin.report'`, and `TypeError: ... unexpected keyword argument 'output_path'` / `'output_dir'`.

- [ ] **Step 3: Implement `app/cin/job.py`**

```python
"""Per-run job folder (spec §9.2): output/<job>/final.mp4, run_report.json, sources/...

All paths written into JSON are job-relative posix strings ("sources/clips/scene00_a.mp4") so a
job folder can be moved, zipped or re-rendered on another OS.
"""
from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                     *(f"lpt{i}" for i in range(1, 10))}
SLUG_MAX = 40


def slugify(topic: str, max_len: int = SLUG_MAX) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:max_len].strip("_")
    if not slug:
        return "video"
    return slug + "_" if slug in _WINDOWS_RESERVED else slug


@dataclass(frozen=True)
class JobPaths:
    root: Path

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def images(self) -> Path:
        return self.sources / "images"

    @property
    def clips(self) -> Path:
        return self.sources / "clips"

    @property
    def narration(self) -> Path:
        return self.sources / "narration.mp3"

    @property
    def words(self) -> Path:
        return self.sources / "words.json"

    @property
    def alignment(self) -> Path:
        return self.sources / "alignment.json"

    @property
    def shot_plan(self) -> Path:
        return self.sources / "shot_plan.json"

    @property
    def mix(self) -> Path:
        return self.sources / "mix.wav"

    @property
    def final(self) -> Path:
        return self.root / "final.mp4"

    @property
    def final_prev(self) -> Path:
        return self.root / "final.prev.mp4"

    @property
    def report(self) -> Path:
        return self.root / "run_report.json"

    @property
    def render_tmp(self) -> Path:
        return self.root / "_render"

    def image(self, scene: int) -> Path:
        return self.images / f"scene{scene:02d}.png"

    def clip(self, name: str) -> Path:
        return self.clips / f"{name}.mp4"

    def last_frame(self, name: str) -> Path:
        return self.clips / f"{name}_last.png"

    def rel(self, path) -> str:
        """Job-relative posix path for JSON; paths outside the job are returned as posix as-is."""
        p = Path(path)
        try:
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()

    def resolve(self, rel: str) -> Path:
        """Inverse of rel(): works for posix strings on Windows and for absolute paths."""
        p = Path(rel)
        return p if p.is_absolute() else self.root.joinpath(*rel.split("/"))

    def ensure(self) -> "JobPaths":
        for d in (self.images, self.clips):
            d.mkdir(parents=True, exist_ok=True)
        return self


def create_job(topic: str, output_dir="output", now: Optional[datetime] = None) -> JobPaths:
    """Claim a fresh output/<YYYYMMDD_HHMMSS>_<slug>[_N]/ folder. mkdir(exist_ok=False) is the
    atomic claim, so concurrent jobs started in the same second never share a folder."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = f"{(now or datetime.now()).strftime('%Y%m%d_%H%M%S')}_{slugify(topic)}"
    for n in range(1, 1000):
        root = out / (base if n == 1 else f"{base}_{n}")
        try:
            root.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return JobPaths(root).ensure()
    raise RuntimeError(f"Could not create a job folder for {base!r}")


def open_job(job_dir) -> JobPaths:
    root = Path(job_dir)
    if not (root / "sources").is_dir():
        raise FileNotFoundError(f"Not a job folder (no sources/ inside): {root}")
    return JobPaths(root)


def prune_sources(output_dir, keep_days: int, now: Optional[float] = None) -> list:
    """Delete output/<job>/sources/ older than keep_days (spec §9.2). Only folders that contain a
    run_report.json are touched; final.mp4 and run_report.json are kept. keep_days <= 0 disables."""
    if keep_days <= 0:
        return []
    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    removed = []
    for src in Path(output_dir).glob("*/sources"):
        if not src.is_dir() or not (src.parent / "run_report.json").is_file():
            continue
        try:
            if src.stat().st_mtime < cutoff:
                shutil.rmtree(src)
                removed.append(src)
                logger.info("Pruned old sources: %s", src)
        except OSError as e:  # file locked by a player on Windows, permissions, ...
            logger.warning("Could not prune %s: %s", src, e)
    return removed
```

- [ ] **Step 4: Implement `app/cin/report.py`**

```python
"""run_report.json writer (spec §10). Phase A: warnings, loudness, platform check, cost, stage
durations, clip counts. Phase D surfaces it through /api/generate."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Codes used in Phase A (spec §10 list plus clip_retry / loudness_skipped).
WARNING_CODES = (
    "still_fallback", "alignment_fallback", "font_fallback", "music_missing", "sfx_missing",
    "speed_adjusted", "prompt_count_normalized", "clip_retry", "loudness_skipped",
)


@dataclass
class RunReport:
    job: str
    options: dict = field(default_factory=dict)
    status: str = "running"                  # running | ok | failed
    error: Optional[str] = None
    warnings: list = field(default_factory=list)
    loudness: Optional[dict] = None          # {"I", "TP", "LRA"} measured on final.mp4
    platform_safe: Optional[dict] = None     # {"ok": bool, "issues": [...]}
    cost: dict = field(default_factory=lambda: {"estimated": None, "actual": [], "total": 0.0})
    durations: dict = field(default_factory=dict)
    clips: dict = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        self._lock = threading.Lock()

    def warn(self, code: str, message: str, detail: Optional[dict] = None) -> None:
        with self._lock:
            self.warnings.append({"code": code, "message": message, "detail": detail or {}})
        logger.warning("[%s] %s", code, message)

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            with self._lock:
                self.durations[name] = round(self.durations.get(name, 0.0) + elapsed, 2)

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("_lock", None)
        return d

    def save(self, path) -> None:
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_json(), indent=1), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path) -> "RunReport":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
```

- [ ] **Step 5: Write assets into the job folder**

In `app/asset_manager.py` add `import os` after `import logging`. Change the `generate_audio` signature and its first lines:

```python
    def generate_audio(
        self,
        text: str,
        voice_id: Optional[str] = None,
        output_path: Optional[Path] = None,
    ) -> AudioResult:
```

and replace `output_path = self.TEMP_DIR / "audio.mp3"` (line 89) with:

```python
        # Per-job path (spec §9.2); the shared temp path is kept only for legacy callers.
        output_path = Path(output_path) if output_path else self.TEMP_DIR / "audio.mp3"
        output_path.parent.mkdir(parents=True, exist_ok=True)
```

Insert this helper directly above `generate_images` and change its signature:

```python
    def _image_path(self, index: int, output_dir: Optional[Path]) -> Path:
        """sources/images/sceneNN.png inside a job folder, or the legacy temp name."""
        if output_dir is None:
            return self.TEMP_DIR / f"image_{index}.png"
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        return Path(output_dir) / f"scene{index:02d}.png"

    def generate_images(
        self,
        prompts: List[str],
        use_mock: bool = True,
        output_dir: Optional[Path] = None,
    ) -> List[str]:
```

Inside `generate_images`, replace both `output_path = self.TEMP_DIR / f"image_{i}.png"` lines (mock branch and Replicate branch) with `output_path = self._image_path(i, output_dir)`, and pass the directory through:

```python
        elif settings.image_provider == "fal":
            return self._generate_images_fal(prompts, output_dir)
        elif settings.image_provider == "local":
            return self._generate_images_local(prompts, output_dir)
```

Change `_generate_images_fal` to `def _generate_images_fal(self, prompts: list[str], output_dir: Optional[Path] = None) -> list[str]:` and its `output_path = self.TEMP_DIR / f"image_{i}.png"` to `output_path = self._image_path(i, output_dir)`. Replace `_generate_images_local` with:

```python
    def _generate_images_local(self, prompts: list[str], output_dir: Optional[Path] = None) -> list[str]:
        """Generate images using local FLUX model."""
        from app.local_image_gen import LocalImageGenerator

        gen = LocalImageGenerator(model_id=settings.flux_local_model)
        try:
            enhanced = [self._enhance_prompt_with_style(p) for p in prompts]
            paths = gen.generate_batch(enhanced, self.IMAGE_WIDTH, self.IMAGE_HEIGHT, str(self.TEMP_DIR))
            if output_dir is None:
                return paths
            moved = []
            for i, path in enumerate(paths):
                dest = self._image_path(i, output_dir)
                os.replace(path, dest)
                moved.append(str(dest))
            return moved
        finally:
            gen.unload()
```

`cleanup_temp()` stays as is: after Task 12 nothing paid is written to `assets/temp` any more (only the persona animator still uses it).

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_job.py tests/test_cin_report.py tests/test_asset_manager.py -q --tb=short -p no:cacheprovider`
Expected: `18 passed` (7 + 4 + 7)

- [ ] **Step 7: Commit**

```bash
git add app/cin/job.py app/cin/report.py app/asset_manager.py tests/test_cin_job.py tests/test_cin_report.py tests/test_asset_manager.py
git commit -m "feat: per-job output folder, run report writer, job-scoped asset paths" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Clip sourcing — parallel generation, retry → fallback model → still, chaining

Replaces the sequential `generate_all_clips` loop (`app/motion_gen.py:142-157`) for the shot editor. `generate_all_clips` and its `ValueError` (`:146`) stay for `--classic`; Task 3's normalization means the mismatch can no longer reach it.

**Files:**
- Modify: `app/motion_gen.py` (`generate_clip`; `output_path`/`duration`/`model_key` on `_generate_fal`, `_generate_replicate`, `_generate_local`)
- Create: `app/cin/clip_sourcing.py`
- Test: `tests/test_motion_gen.py` (append), `tests/test_clip_sourcing.py`

**Interfaces:**
- Consumes: `SegmentRequest`, `ClipSpec` (Task 5); `JobPaths` (Task 7: `image`, `clip`, `last_frame`, `rel`); `RunReport.warn` (Task 7); `CLIP_MODELS`, `snap_duration` (Task 2); `make_test_clip` (Task 4 conftest).
- Produces (`app/motion_gen.py`): `MotionGenerator.generate_clip(image_path: str, prompt: str, output_path: str, duration: Optional[float] = None, model_key: Optional[str] = None) -> Optional[str]` — one attempt, returns `output_path` or `None`, never raises.
- Produces (`app/cin/clip_sourcing.py`): `StrictModeError(RuntimeError)`; `probe_clip_duration(path) -> float`; `extract_last_frame(clip_path, png_path) -> Optional[str]`; `generate_segment_clips(requests, image_paths, motion_prompts, job, report, *, enable_motion=True, generator=None, model_key="hailuo", fallback_model=None, concurrency=None) -> list[ClipSpec]` (sets `report.clips` and adds `clip_retry` warnings; failed segments come back with `failed=True`, `path=None`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_motion_gen.py` (imports inside the tests on purpose: `test_generate_motion_clip_fal` reloads `app.motion_gen`):

```python
def _fake_fal():
    fal = MagicMock()
    fal.upload_file.return_value = "https://fal.media/in.png"
    fal.subscribe.return_value = {"video": {"url": "https://fal.media/out.mp4"}}
    return fal


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    response.content = b"fake_mp4"
    return response


def _clip_paths(tmp_path):
    image = tmp_path / "in.png"
    image.write_bytes(b"png")
    out = tmp_path / "clips" / "scene00_a.mp4"
    out.parent.mkdir()
    return image, out


def test_generate_clip_kling_requests_snapped_duration(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import CLIP_MODELS, MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    fal = _fake_fal()
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        result = MotionGenerator(temp_dir=str(tmp_path)).generate_clip(
            str(image), "orbit", str(out), duration=6.2, model_key="kling")
    assert result == str(out) and out.read_bytes() == b"fake_mp4"
    assert fal.subscribe.call_args.args[0] == CLIP_MODELS["kling"].endpoint
    arguments = fal.subscribe.call_args.kwargs["arguments"]
    assert arguments["duration"] == "10" and arguments["aspect_ratio"] == "9:16"


def test_generate_clip_hailuo_sends_no_duration(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    fal = _fake_fal()
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": fal}), \
            patch("app.motion_gen.requests.get", return_value=_ok_response()):
        MotionGenerator(temp_dir=str(tmp_path)).generate_clip(
            str(image), "push in", str(out), duration=4.0, model_key="hailuo")
    assert "duration" not in fal.subscribe.call_args.kwargs["arguments"]


def test_missing_fal_client_counts_as_clip_failure(tmp_path, monkeypatch):
    from app.config import settings
    from app.motion_gen import MotionGenerator
    monkeypatch.setattr(settings, "motion_provider", "fal")
    image, out = _clip_paths(tmp_path)
    with patch.dict("sys.modules", {"fal_client": None}):
        assert MotionGenerator(temp_dir=str(tmp_path)).generate_clip(str(image), "p", str(out)) is None
    assert not out.exists()
```

Create `tests/test_clip_sourcing.py`:

```python
"""Clip sourcing: chaining, retry -> fallback -> failure, parallelism (spec §6.4, §10)."""
import sys
import threading
import time
from pathlib import Path

from PIL import Image

from app.cin.clip_sourcing import generate_segment_clips
from app.cin.job import create_job
from app.cin.report import RunReport
from app.cin.shot_plan import build_shot_plan, plan_segments
from tests.conftest import fixture_alignment, make_test_clip


class FakeGenerator:
    """Stands in for MotionGenerator.generate_clip. fail(start_name, out_name, model_key) -> bool."""

    def __init__(self, fail=lambda start, out, model: False, delay=0.0, length=None):
        self.fail, self.delay, self.length = fail, delay, length
        self.calls = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def generate_clip(self, image_path, prompt, output_path, duration=None, model_key=None):
        with self._lock:
            self.calls.append((Path(image_path).name, Path(output_path).name, model_key))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            if self.fail(Path(image_path).name, Path(output_path).name, model_key):
                return None
            make_test_clip(output_path, self.length or duration)
            return output_path
        finally:
            with self._lock:
                self.active -= 1


def gold_job(tmp_path, durations=(6.0,)):
    job = create_job("gold", tmp_path / "output")
    alignment = fixture_alignment("words_gold_8s.json")
    images = []
    for i in range(len(alignment.scenes)):
        Image.new("RGB", (108, 192), (200, 30 * i, 30)).save(job.image(i))
        images.append(str(job.image(i)))
    return job, alignment, plan_segments(alignment, durations), images


def run(job, segs, images, gen, **kw):
    report = RunReport(job=job.name)
    specs = generate_segment_clips(segs, images, ["push in", "orbit"], job, report, generator=gen, **kw)
    return specs, report


def test_chained_segment_starts_from_previous_last_frame(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    specs, report = run(job, segs, images, FakeGenerator())
    assert [(s.scene, s.index) for s in specs] == [(0, 0), (1, 0), (1, 1)]
    assert specs[2].start_image == "sources/clips/scene01_a_last.png"
    assert (job.root / specs[2].start_image).exists()
    assert specs[1].path == "sources/clips/scene01_a.mp4"
    assert abs(specs[1].duration - 6.0) < 0.1
    assert report.clips == {"requested": 3, "generated": 3, "failed": 0, "by_model": {"hailuo": 3}}


def test_retry_then_fallback_model(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    gen = FakeGenerator(fail=lambda start, out, model: out == "scene00_a.mp4" and model == "hailuo")
    specs, report = run(job, segs, images, gen, fallback_model="kling")
    assert [c[2] for c in gen.calls if c[1] == "scene00_a.mp4"] == ["hailuo", "hailuo", "kling"]
    assert specs[0].model == "kling" and specs[0].attempts == 3 and specs[0].path
    assert [w["code"] for w in report.warnings] == ["clip_retry"]


def test_failed_first_segment_chains_from_scene_image(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    specs, _ = run(job, segs, images, FakeGenerator(fail=lambda start, out, model: out == "scene01_a.mp4"))
    assert specs[1].failed and specs[1].path is None
    assert specs[2].start_image == "sources/images/scene01.png"


def test_all_clips_failing_never_raises(tmp_path):
    job, alignment, segs, images = gold_job(tmp_path)
    specs, report = run(job, segs, images, FakeGenerator(fail=lambda *a: True))
    assert all(s.failed and s.path is None for s in specs)
    assert report.clips["failed"] == 3 and report.clips["generated"] == 0
    plan = build_shot_plan(alignment, "standard", specs)
    assert all(s.source.type == "still" for s in plan.shots)
    assert [w["code"] for w in plan.warnings] == ["still_fallback"] * 3


def test_motion_disabled_makes_no_calls(tmp_path):
    job, _, _, images = gold_job(tmp_path)
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), None)
    gen = FakeGenerator()
    specs, report = run(job, segs, images, gen, enable_motion=False)
    assert gen.calls == []
    assert all(s.path is None and not s.failed for s in specs)
    assert report.clips["requested"] == 0


def test_scenes_run_in_parallel(tmp_path):
    job, _, _, images = gold_job(tmp_path)
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), (10.0,))   # 2 scenes, 1 segment each
    gen = FakeGenerator(delay=0.3, length=1.0)
    run(job, segs, images, gen, concurrency=4)
    assert gen.max_active == 2


def test_short_clip_reports_real_duration(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    specs, _ = run(job, segs, images, FakeGenerator(length=2.0))
    assert all(abs(s.duration - 2.0) < 0.1 for s in specs)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_clip_sourcing.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `AttributeError: 'MotionGenerator' object has no attribute 'generate_clip'` and `ModuleNotFoundError: No module named 'app.cin.clip_sourcing'`.

- [ ] **Step 3: Add `generate_clip` and job-path arguments to `app/motion_gen.py`**

Insert above `_generate_fal`:

```python
    def generate_clip(self, image_path: str, prompt: str, output_path: str,
                      duration: Optional[float] = None, model_key: Optional[str] = None) -> Optional[str]:
        """One generation attempt for the shot editor. Returns output_path, or None on any failure
        (missing fal_client, HTTP error, quota...). Retries/fallbacks live in app.cin.clip_sourcing."""
        provider = settings.motion_provider
        try:
            if provider == "replicate":
                return self._generate_replicate(image_path, prompt, 0, output_path=output_path)
            if provider == "local":
                return self._generate_local(image_path, prompt, 0, output_path=output_path, duration=duration)
            return self._generate_fal(image_path, prompt, 0, output_path=output_path,
                                      duration=duration, model_key=model_key)
        except Exception as e:  # noqa: BLE001
            logger.warning("Motion clip %s failed: %s", Path(output_path).name, e)
            return None
```

Change the `_generate_fal` signature to:

```python
    def _generate_fal(self, image_path: str, motion_prompt: str, index: int,
                      output_path: Optional[str] = None, duration: Optional[float] = None,
                      model_key: Optional[str] = None) -> Optional[str]:
```

and inside it replace the model lookup, the Kling block and the output path:

```python
        model = CLIP_MODELS.get(model_key or settings.fal_video_model, CLIP_MODELS["hailuo"])
        if model.endpoint is None:
            model = CLIP_MODELS["hailuo"]
        endpoint = model.endpoint

        logger.info(f"Generating motion clip {index} via fal.ai ({model.key}): {motion_prompt[:50]}...")
```

```python
        # Kling takes a length ("5"/"10") and an aspect ratio; Minimax/hailuo takes neither
        if model.sends_duration:
            length = snap_duration(duration or min(model.durations), model.durations) or max(model.durations)
            args["duration"] = str(int(length))
            args["aspect_ratio"] = "9:16"
```

```python
        # Download video
        output_path = Path(output_path) if output_path else self.temp_dir / f"motion_{index:03d}.mp4"
```

Change `_generate_replicate` to accept `output_path: Optional[str] = None` and use `output_path = Path(output_path) if output_path else self.temp_dir / f"motion_{index:03d}.mp4"`. Replace `_generate_local` with:

```python
    def _generate_local(self, image_path: str, motion_prompt: str, index: int,
                        output_path: Optional[str] = None, duration: Optional[float] = None) -> Optional[str]:
        """Generate motion clip using local enhanced motion effects."""
        from app.local_video_gen import LocalVideoGenerator

        output_path = str(output_path or self.temp_dir / f"motion_{index:03d}.mp4")
        gen = LocalVideoGenerator()
        gen.generate(image_path, motion_prompt, output_path, duration=duration or 5.0)
        logger.info("Local motion clip %d saved: %s", index, output_path)
        return output_path
```

- [ ] **Step 4: Implement `app/cin/clip_sourcing.py`**

```python
"""Motion-clip sourcing for planned segments (spec §6.4, §10).

Scenes are generated in parallel (settings.motion_concurrency). Segments inside a scene run in
order, because a chained segment starts from the previous segment's last frame (or the scene
image when that clip failed). Per segment: model, retry once, settings.fal_video_fallback_model,
then give up — build_shot_plan turns a failed segment into a push-in still (still_fallback).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PIL import Image

from app.cin.shot_plan import ClipSpec

logger = logging.getLogger(__name__)


class StrictModeError(RuntimeError):
    """strict=True and the plan would ship a still-fallback shot (spec §10)."""


def probe_clip_duration(path) -> float:
    from moviepy import VideoFileClip
    clip = VideoFileClip(str(path), audio=False)
    try:
        return float(clip.duration or 0.0)
    finally:
        clip.close()


def extract_last_frame(clip_path, png_path) -> Optional[str]:
    from moviepy import VideoFileClip
    try:
        clip = VideoFileClip(str(clip_path), audio=False)
        try:
            t = max(0.0, (clip.duration or 0.0) - 1.5 / (clip.fps or 30))
            Image.fromarray(clip.get_frame(t)[:, :, :3]).save(png_path)
        finally:
            clip.close()
        return str(png_path)
    except Exception as e:  # noqa: BLE001 - a missing last frame only loses chaining
        logger.warning("Could not extract last frame of %s: %s", clip_path, e)
        return None


def _attempt_models(model_key: str, fallback_model: Optional[str]) -> list:
    keys = [model_key, model_key]                       # first try + one retry
    if fallback_model and fallback_model != model_key:
        keys.append(fallback_model)
    return keys


def generate_segment_clips(requests: list, image_paths: list, motion_prompts: list, job, report, *,
                           enable_motion: bool = True, generator=None, model_key: str = "hailuo",
                           fallback_model: Optional[str] = None,
                           concurrency: Optional[int] = None) -> list:
    """Generate one clip per SegmentRequest. Never raises for clip failures; returns ClipSpecs
    in (scene, index) order with job-relative posix paths."""
    from app.config import settings

    if enable_motion and generator is None:
        from app.motion_gen import MotionGenerator
        generator = MotionGenerator(temp_dir=str(job.clips))

    by_scene: dict = {}
    for req in requests:
        by_scene.setdefault(req.scene, []).append(req)

    def run_scene(scene_reqs: list) -> list:
        specs, prev_last = [], None
        for req in sorted(scene_reqs, key=lambda r: r.index):
            start = prev_last if (req.chained and prev_last) else image_paths[req.scene]
            spec = ClipSpec(req.scene, req.index, req.t0, req.t1, req.requested_len, job.rel(start))
            prev_last = None
            if enable_motion:
                prompt = motion_prompts[req.scene] if req.scene < len(motion_prompts) else ""
                out = job.clip(req.name)
                for n, key in enumerate(_attempt_models(model_key, fallback_model), start=1):
                    spec.attempts = n
                    if generator.generate_clip(str(start), prompt, str(out),
                                               duration=req.requested_len, model_key=key):
                        spec.path, spec.model = job.rel(out), key
                        break
                if spec.path:
                    try:
                        spec.duration = probe_clip_duration(out)
                    except Exception as e:  # noqa: BLE001 - corrupt download counts as a failure
                        logger.warning("Unreadable clip %s: %s", out, e)
                        spec.path, spec.model = None, ""
                if spec.path:
                    last = extract_last_frame(out, job.last_frame(req.name))
                    spec.last_frame = job.rel(last) if last else None
                    prev_last = last
                else:
                    spec.failed = True
            specs.append(spec)
        return specs

    workers = max(1, concurrency or settings.motion_concurrency)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run_scene, [by_scene[k] for k in sorted(by_scene)]))
    specs = [s for scene_specs in results for s in scene_specs]

    by_model: dict = {}
    for s in specs:
        if s.path:
            by_model[s.model] = by_model.get(s.model, 0) + 1
            if s.attempts > 1:
                report.warn("clip_retry", f"scene {s.scene} segment {s.index} needed {s.attempts} attempts",
                            {"scene": s.scene, "segment": s.index, "model": s.model, "attempts": s.attempts})
    report.clips = {
        "requested": len(specs) if enable_motion else 0,
        "generated": sum(1 for s in specs if s.path),
        "failed": sum(1 for s in specs if s.failed),
        "by_model": by_model,
    }
    return specs
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_motion_gen.py tests/test_clip_sourcing.py -q --tb=short -p no:cacheprovider`
Expected: `17 passed` (10 + 7)

- [ ] **Step 6: Commit**

```bash
git add app/motion_gen.py app/cin/clip_sourcing.py tests/test_motion_gen.py tests/test_clip_sourcing.py
git commit -m "feat: parallel clip sourcing with retry, fallback model and last-frame chaining" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Upload-grade encoding (`app/encoding.py`)

Spec §9.1. Today the cinematic path writes 24 fps, preset medium, no loudness normalization (`app/cinematic.py:182-189`). `probe_video`, `get_audio_loudness`, `is_platform_safe` are ported from `src/encoding.py:71, 176, 401` (`src/` is the legacy pipeline; `app/` must not import it). Verified on this machine: ffmpeg 8.0.1 and ffprobe are on PATH; MoviePy uses imageio-ffmpeg 7.1; MoviePy's x264 output reports `color_primaries=unknown` until the copy-mux adds `h264_metadata`; a tone mix normalized this way measures −14.02 LUFS.

**Files:**
- Create: `app/encoding.py`
- Test: `tests/test_encoding.py`

**Interfaces:**
- Consumes: `make_test_clip`, `make_tone`, `make_silence` (Task 4 conftest).
- Produces: `EncodingError`; `find_ffmpeg() -> str` (PATH, then imageio-ffmpeg); `find_ffprobe() -> str`; `probe_video(path) -> dict` (keys `duration, width, height, fps, video_codec, pixel_format, color_primaries, color_transfer, color_space, audio_codec, audio_sample_rate, has_audio, file_size, bitrate`); `get_audio_loudness(path) -> Optional[dict]`; `faststart_ok(path) -> bool`; `is_platform_safe(path) -> tuple[bool, list[str]]`; `measure_loudness(path) -> Optional[dict]` (floats `input_i, input_tp, input_lra, input_thresh, target_offset`; `None` for silence); `write_video(clip, out_path, fps=30)`; `mux_final(video_path, wav_path, out_path, measured: Optional[dict])`; constants `X264_PRESET = "slow"`, `X264_PARAMS`, `LOUDNORM = "I=-14:TP=-1:LRA=11"`, `COLOR_BSF`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_encoding.py`:

```python
"""Encode helpers: probe, loudness, platform check, two-pass loudnorm mux (spec §9.1)."""
from pathlib import Path

import numpy as np
import pytest

from app.encoding import (
    X264_PARAMS, faststart_ok, find_ffmpeg, find_ffprobe, get_audio_loudness, is_platform_safe,
    measure_loudness, mux_final, probe_video, write_video,
)
from tests.conftest import make_silence, make_test_clip, make_tone


def test_ffmpeg_and_ffprobe_found():
    assert Path(find_ffmpeg()).exists()
    assert Path(find_ffprobe()).exists()


def test_x264_params_match_spec():
    assert X264_PARAMS == ["-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                           "-color_primaries", "bt709", "-color_trc", "bt709"]


def test_probe_video(tmp_path):
    clip = make_test_clip(tmp_path / "c.mp4", 1.0)
    info = probe_video(clip)
    assert (info["width"], info["height"], info["fps"]) == (108, 192, 30.0)
    assert info["video_codec"] == "h264" and info["has_audio"] is False


def test_measure_loudness_tone_and_silence(tmp_path):
    tone = measure_loudness(make_tone(tmp_path / "t.wav", 3.0))
    assert tone is not None and -45 < tone["input_i"] < -20
    assert measure_loudness(make_silence(tmp_path / "s.wav", 3.0)) is None


def test_write_video_then_mux_hits_targets(tmp_path):
    from moviepy import VideoClip
    clip = VideoClip(lambda t: np.full((192, 108, 3), int(t * 30) % 255, np.uint8), duration=8.0)
    video = tmp_path / "video.mp4"
    write_video(clip, video)
    wav = make_tone(tmp_path / "mix.wav", 8.0)
    out = tmp_path / "final.mp4"
    mux_final(video, wav, out, measure_loudness(wav))

    info = probe_video(out)
    assert info["fps"] == 30.0 and info["pixel_format"] == "yuv420p"
    assert (info["color_primaries"], info["color_transfer"], info["color_space"]) == ("bt709", "bt709", "bt709")
    assert info["audio_codec"] == "aac" and info["audio_sample_rate"] == 48000
    assert abs(info["duration"] - 8.0) <= 0.05
    assert faststart_ok(out)
    loud = measure_loudness(out)
    assert -15.0 <= loud["input_i"] <= -13.0
    assert loud["input_tp"] <= -1.0
    assert get_audio_loudness(out)["mean_volume"] < 0


def test_mux_without_measurement_still_muxes(tmp_path):
    video = make_test_clip(tmp_path / "v.mp4", 2.0)
    out = tmp_path / "final.mp4"
    mux_final(video, make_silence(tmp_path / "s.wav", 2.0), out, None)
    assert probe_video(out)["has_audio"] is True


def test_platform_check_flags_wrong_resolution(tmp_path):
    ok, issues = is_platform_safe(make_test_clip(tmp_path / "c.mp4", 1.0))
    assert ok is False
    assert "Resolution 108x192 should be 1080x1920" in issues
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_encoding.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.encoding'`.

- [ ] **Step 3: Implement `app/encoding.py`**

```python
"""Upload-grade encode (spec §9.1): video-only x264 render settings, two-pass loudnorm, copy-mux.

probe_video / get_audio_loudness / is_platform_safe are ported from src/encoding.py
(src/ is the legacy pipeline and is not imported by app/).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30
X264_PRESET = "slow"
# spec §9.1 step 1 (the preset is passed separately because MoviePy always adds -preset)
X264_PARAMS = ["-crf", "18", "-profile:v", "high", "-pix_fmt", "yuv420p",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]
LOUDNORM = "I=-14:TP=-1:LRA=11"
# MoviePy's x264 output only carries colorspace; tag primaries/transfer on the copy-mux.
COLOR_BSF = "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"
_LOUDNORM_JSON = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class EncodingError(Exception):
    pass


def find_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # noqa: BLE001
        raise EncodingError(f"ffmpeg not found on PATH or via imageio-ffmpeg: {e}")


def find_ffprobe() -> str:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    sibling = Path(find_ffmpeg()).with_name("ffprobe" + Path(find_ffmpeg()).suffix)
    if sibling.exists():
        return str(sibling)
    raise EncodingError("ffprobe not found. Install ffmpeg (with ffprobe) and add it to PATH.")


def _run(cmd: list, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def probe_video(video_path) -> dict:
    """Ported from src/encoding.py:71, plus color tags and audio sample rate."""
    video_path = str(video_path)
    if not Path(video_path).exists():
        raise EncodingError(f"Video file not found: {video_path}")
    result = _run([find_ffprobe(), "-v", "quiet", "-print_format", "json",
                   "-show_format", "-show_streams", video_path], timeout=30)
    if result.returncode != 0:
        raise EncodingError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise EncodingError("No video stream found")
    num, _, den = video.get("r_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    fmt = data.get("format", {})
    return {
        "duration": round(float(fmt.get("duration", 0)), 3),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "fps": round(fps, 2),
        "video_codec": video.get("codec_name", "unknown"),
        "pixel_format": video.get("pix_fmt", "unknown"),
        "color_primaries": video.get("color_primaries", "unknown"),
        "color_transfer": video.get("color_transfer", "unknown"),
        "color_space": video.get("color_space", "unknown"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "audio_sample_rate": int(audio.get("sample_rate", 0)) if audio else 0,
        "has_audio": audio is not None,
        "file_size": int(fmt.get("size", 0)),
        "bitrate": int(fmt.get("bit_rate", 0)),
    }


def get_audio_loudness(video_path) -> Optional[dict]:
    """Ported from src/encoding.py:176 (volumedetect mean/max dB)."""
    result = _run([find_ffmpeg(), "-hide_banner", "-i", str(video_path),
                   "-af", "volumedetect", "-f", "null", "-"], timeout=120)
    mean = re.search(r"mean_volume:\s*(-?[\d.]+) dB", result.stderr)
    peak = re.search(r"max_volume:\s*(-?[\d.]+) dB", result.stderr)
    if not mean:
        return None
    return {"mean_volume": float(mean.group(1)), "max_volume": float(peak.group(1)) if peak else None}


def faststart_ok(video_path) -> bool:
    """True when the moov atom precedes mdat (spec §12: faststart atom first)."""
    head = Path(video_path).read_bytes()[:4 * 1024 * 1024]
    moov, mdat = head.find(b"moov"), head.find(b"mdat")
    return moov != -1 and (mdat == -1 or moov < mdat)


def is_platform_safe(video_path) -> tuple:
    """Ported from src/encoding.py:401, plus the faststart check."""
    try:
        stats = probe_video(video_path)
    except EncodingError as e:
        return False, [str(e)]
    issues = []
    if stats["video_codec"] not in ("h264", "avc1"):
        issues.append(f"Video codec '{stats['video_codec']}' should be H.264")
    if stats["pixel_format"] != "yuv420p":
        issues.append(f"Pixel format '{stats['pixel_format']}' should be yuv420p")
    if stats["has_audio"] and stats["audio_codec"] not in ("aac", "mp4a"):
        issues.append(f"Audio codec '{stats['audio_codec']}' should be AAC")
    if stats["width"] != DEFAULT_WIDTH or stats["height"] != DEFAULT_HEIGHT:
        issues.append(f"Resolution {stats['width']}x{stats['height']} should be {DEFAULT_WIDTH}x{DEFAULT_HEIGHT}")
    if not 24 <= stats["fps"] <= 60:
        issues.append(f"FPS {stats['fps']} should be between 24-60")
    if not faststart_ok(video_path):
        issues.append("moov atom is not at the front (missing +faststart)")
    return len(issues) == 0, issues


def measure_loudness(media_path) -> Optional[dict]:
    """loudnorm pass 1. Returns floats input_i/input_tp/input_lra/input_thresh/target_offset,
    or None when the input is silent (-inf) or ffmpeg output cannot be parsed."""
    result = _run([find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(media_path),
                   "-af", f"loudnorm={LOUDNORM}:print_format=json", "-f", "null", "-"], timeout=300)
    m = _LOUDNORM_JSON.search(result.stderr)
    if not m:
        logger.warning("loudnorm measurement failed: %s", result.stderr[-500:])
        return None
    raw = json.loads(m.group(0))
    try:
        out = {k: float(raw[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, ValueError):
        return None
    if out["input_i"] == float("-inf") or out["input_i"] < -70:
        return None
    return out


def write_video(clip, out_path, fps: int = DEFAULT_FPS) -> None:
    """Video-only MoviePy render with the spec §9.1 x264 settings."""
    clip.write_videofile(str(out_path), fps=fps, codec="libx264", audio=False,
                         preset=X264_PRESET, ffmpeg_params=list(X264_PARAMS), logger=None)


def mux_final(video_path, wav_path, out_path, measured: Optional[dict]) -> None:
    """loudnorm pass 2 (linear, from pass-1 measurements) + copy-mux (spec §9.1 steps 2-3).
    measured=None (silent mix) muxes without normalization."""
    cmd = [find_ffmpeg(), "-hide_banner", "-y", "-i", str(video_path), "-i", str(wav_path),
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-bsf:v", COLOR_BSF]
    if measured:
        cmd += ["-af", (f"loudnorm={LOUDNORM}:measured_I={measured['input_i']}"
                        f":measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}"
                        f":measured_thresh={measured['input_thresh']}:offset={measured['target_offset']}"
                        ":linear=true:print_format=summary,aresample=48000")]
    cmd += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_path)]
    result = _run(cmd)
    if result.returncode != 0:
        raise EncodingError(f"ffmpeg mux failed: {result.stderr[-2000:]}")
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_encoding.py -q --tb=short -p no:cacheprovider`
Expected: `7 passed` (about 5 s)

- [ ] **Step 5: Commit**

```bash
git add app/encoding.py tests/test_encoding.py
git commit -m "feat: upload-grade encode helpers with two-pass loudnorm copy-mux" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 10: Shot renderer (`app/cin/renderer.py`)

Replaces CinematicEngine's per-scene loop (`app/cinematic.py:111-134`, `_render_scene` `:202-269`, frozen-frame transitions `:355-393`). One frame function plays the shot list: source lookup (clip time = `clip_t0 + (t − shot.t0) × speed`, clamped to the clip) → cover-fit (fal clips are not always 9:16; the old code stretched with `resized((W, H))` at `app/cinematic.py:215`) → framing crop → colour grade → particles. Styled transitions call `app/cin/transitions.py` with frames from **both** neighbouring shots at the same timeline instant, so both sides keep moving. Particles and colour grade are applied per frame for every shot (the cinematic path never applied `color_grade`). The audio-energy zoom punch (`app/cinematic.py:256-257`) is gone (spec §2). Hook headline: deferred to Phase B.

Also fixes `ParticleSystem.__init__` calling `random.seed(42)` on the global RNG (`app/cin/particles.py:43`), which made every later `random.choice` (music pick) deterministic and is unsafe with concurrent jobs.

**Files:**
- Create: `app/cin/renderer.py`
- Modify: `app/cin/particles.py:43-54` (private RNG)
- Modify: `app/video_editor.py:435-471` (method delegates to new module-level `apply_color_grade`)
- Test: `tests/test_cin_renderer.py`, `tests/test_video_editor.py` (append)

**Interfaces:**
- Consumes: `ShotPlan`, `Shot`, `ShotSource`, `TRANSITION_LEN` (Task 5); `JobPaths.resolve` (Task 7); `write_video` (Task 9); `TRANSITIONS` (`app/cin/transitions.py`); `ParticleSystem`, `STYLE_PARTICLES`; `make_color_clip` (Task 4 conftest).
- Produces: `WIDTH = 1080`, `HEIGHT = 1920`, `PUSH_IN_END = 1.08`; `RenderError(RuntimeError)`; `cover_fit(frame, w, h) -> np.ndarray`; `apply_framing(frame, zoom, w, h) -> np.ndarray`; `ShotRenderer(plan, job, *, video_style="photorealistic", color_grade=None, width=WIDTH, height=HEIGHT)` with `frame_at(t) -> np.ndarray`, `render(out_path, overlays=None) -> Path` (video only, wraps any failure in `RenderError`, always closes clip readers); `caption_overlays(plan, subtitle_style, width=WIDTH, height=HEIGHT) -> list` (Phase A adapter onto `VideoEditor._create_karaoke_clips`).
- Produces (`app/video_editor.py`): `apply_color_grade(frame: np.ndarray, grade_name: str) -> np.ndarray`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_renderer.py`:

```python
"""Shot renderer: sources, framing, still push-in, transitions, output format (spec §6, §9.1)."""
import random

import numpy as np
import pytest

from app.cin.job import create_job
from app.cin.particles import ParticleSystem
from app.cin.renderer import RenderError, ShotRenderer, apply_framing, cover_fit
from app.cin.shot_plan import Scene, Segment, Shot, ShotPlan, ShotSource
from app.encoding import probe_video
from tests.conftest import make_color_clip

W, H = 108, 192


def test_cover_fit_crops_instead_of_stretching():
    landscape = np.zeros((100, 300, 3), np.uint8)
    landscape[:, :100] = (255, 0, 0)
    landscape[:, 100:200] = (0, 255, 0)
    landscape[:, 200:] = (0, 0, 255)
    out = cover_fit(landscape, W, H)
    assert out.shape == (H, W, 3)
    assert (out[:, :, 1] > 200).all() and (out[:, :, 0] < 50).all()   # only the green middle survives


def test_apply_framing_keeps_size():
    frame = np.random.randint(0, 255, (H, W, 3), np.uint8)
    assert apply_framing(frame, 1.0, W, H) is frame
    assert apply_framing(frame, 1.18, W, H).shape == (H, W, 3)


def test_particles_do_not_reseed_global_random():
    random.seed(1)
    expected = random.random()
    random.seed(1)
    ParticleSystem(preset="dust", width=W, height=H)
    assert random.random() == expected


def two_shot_plan(job, transition="cut", second_type="clip"):
    red = make_color_clip(job.clip("scene00_a"), 1.5, "red")
    blue = make_color_clip(job.clip("scene01_a"), 1.5, "blue")
    second = (ShotSource("clip", job.rel(blue), 0.0, 1.0, 1.0) if second_type == "clip"
              else ShotSource("still", "sources/images/scene01.png", move="push_in"))
    if second_type == "still":
        from PIL import Image
        Image.new("RGB", (W, H), (0, 0, 255)).save(job.image(1))
    return ShotPlan(
        duration=2.0, fps=30, pacing="standard", alignment={"method": "whisper+script", "fallback": False, "match_ratio": 1.0},
        scenes=[Scene(0, 0.0, 1.0, "a", [Segment(0.0, 1.0, job.rel(red), 6.0, "sources/images/scene00.png")]),
                Scene(1, 1.0, 2.0, "b", [Segment(1.0, 2.0, job.rel(blue), 6.0, "sources/images/scene01.png")])],
        shots=[Shot(0, 0, 0.0, 1.0, ShotSource("clip", job.rel(red), 0.0, 1.0, 1.0), 1.0, "cut"),
               Shot(1, 1, 1.0, 2.0, second, 1.0, transition)],
        captions=[],
    )


def renderer(job, plan):
    return ShotRenderer(plan, job, video_style="comic_book", width=W, height=H)   # comic_book: no particles


def test_frames_follow_the_shot_list(tmp_path):
    job = create_job("r", tmp_path)
    r = renderer(job, two_shot_plan(job))
    try:
        a, b = r.frame_at(0.5).mean(axis=(0, 1)), r.frame_at(1.5).mean(axis=(0, 1))
    finally:
        r.sources.close()
    assert a[0] > 200 and a[2] < 60
    assert b[2] > 200 and b[0] < 60


def test_flash_transition_uses_both_moving_shots(tmp_path):
    job = create_job("r", tmp_path)
    r = renderer(job, two_shot_plan(job, transition="flash"))
    try:
        assert r.frame_at(0.97).mean() > 250                        # white peak inside the 0.3 s window
        assert r.frame_at(0.80).mean(axis=(0, 1))[0] > 200          # before the window: plain red
        assert r.frame_at(1.20).mean(axis=(0, 1))[2] > 200          # after the window: plain blue
    finally:
        r.sources.close()


def test_still_shot_pushes_in(tmp_path):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job, second_type="still")
    r = renderer(job, plan)
    try:
        assert r.frame_at(1.9).shape == (H, W, 3)
    finally:
        r.sources.close()


def test_source_time_past_clip_end_is_clamped(tmp_path):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job)
    plan.shots[1].source.clip_t1 = 5.0
    plan.shots[1].source.speed = 4.0                                 # asks for 4 s of a 1.5 s clip
    r = renderer(job, plan)
    try:
        assert r.frame_at(1.99).shape == (H, W, 3)
    finally:
        r.sources.close()


def test_render_writes_30fps_video(tmp_path):
    job = create_job("r", tmp_path)
    out = renderer(job, two_shot_plan(job, transition="whip_pan")).render(tmp_path / "video.mp4")
    info = probe_video(out)
    assert (info["width"], info["height"], info["fps"], info["pixel_format"]) == (W, H, 30.0, "yuv420p")
    assert abs(info["duration"] - 2.0) <= 0.05
    assert info["has_audio"] is False


def test_missing_clip_raises_render_error(tmp_path):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job)
    plan.shots[0].source.path = "sources/clips/missing.mp4"
    with pytest.raises(RenderError):
        renderer(job, plan).render(tmp_path / "video.mp4")
```

Append to `tests/test_video_editor.py`:

```python
def test_module_level_color_grade_matches_method():
    import numpy as np
    from app.video_editor import apply_color_grade
    frame = np.random.randint(0, 255, (20, 20, 3), dtype=np.uint8)
    assert (apply_color_grade(frame, "history") == VideoEditor()._apply_color_grade(frame, "history")).all()
    assert apply_color_grade(frame, "nonexistent") is frame
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_renderer.py tests/test_video_editor.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cin.renderer'` and `ImportError: cannot import name 'apply_color_grade'`.

- [ ] **Step 3: Private RNG in `app/cin/particles.py`**

Replace lines 43-54 (from `random.seed(seed)` to the end of the `for` loop) with:

```python
        rng = random.Random(seed)  # private RNG: never reseed the global one (thread-safe, keeps music choice random)
        self.particles = []
        for _ in range(self.config["count"]):
            self.particles.append({
                "x": rng.uniform(0, width),
                "y": rng.uniform(0, height),
                "size": rng.uniform(*self.config["size_range"]),
                "opacity": rng.randint(*self.config["opacity_range"]),
                "dx": rng.uniform(-0.3, 0.3) * self.config["speed"],
                "dy": rng.uniform(-0.5, -0.1) * self.config["speed"],
                "phase": rng.uniform(0, 2 * math.pi),
            })
```

- [ ] **Step 4: Module-level colour grade in `app/video_editor.py`**

Replace the body of `_apply_color_grade` (lines 436-471) so the method delegates:

```python
    def _apply_color_grade(self, frame: np.ndarray, grade_name: str) -> np.ndarray:
        """Apply color grading to a video frame."""
        return apply_color_grade(frame, grade_name)
```

and append at the end of the module (after the module-level `assemble_video` function):

```python
def apply_color_grade(frame: np.ndarray, grade_name: str) -> np.ndarray:
    """Apply a VideoEditor.COLOR_GRADES preset to one RGB frame (module level so the shot
    renderer can grade frames without building a VideoEditor)."""
    grade = VideoEditor.COLOR_GRADES.get(grade_name, None)
    if not grade:
        return frame

    result = frame.astype(np.float32)

    if "contrast" in grade:
        mean = result.mean()
        result = (result - mean) * grade["contrast"] + mean

    if "saturation" in grade:
        gray = np.mean(result, axis=2, keepdims=True)
        result = gray + (result - gray) * grade["saturation"]

    if "blue_shift" in grade:
        result[:, :, 2] = result[:, :, 2] + grade["blue_shift"]

    if "warmth" in grade:
        result[:, :, 0] = result[:, :, 0] + grade["warmth"]
        result[:, :, 2] = result[:, :, 2] - grade["warmth"] * 0.5

    if "brightness" in grade:
        result = result + grade["brightness"]

    if "sepia" in grade:
        sepia_amount = grade["sepia"]
        gray = np.mean(result, axis=2, keepdims=True)
        sepia_frame = np.stack([
            gray[:, :, 0] * 1.2,
            gray[:, :, 0] * 1.0,
            gray[:, :, 0] * 0.8,
        ], axis=2)
        result = result * (1 - sepia_amount) + sepia_frame * sepia_amount

    return np.clip(result, 0, 255).astype(np.uint8)
```

- [ ] **Step 5: Implement `app/cin/renderer.py`**

```python
"""Shot renderer (spec §6, §13 A). Plays shot_plan shots back to back from one frame function:
source lookup -> framing crop -> colour grade -> particles. Styled transitions blend moving
frames of both neighbouring shots. Video only; audio is mixed and muxed by app.cin.editor.
"""
from __future__ import annotations

import bisect
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from app.cin.particles import STYLE_PARTICLES, ParticleSystem
from app.cin.shot_plan import TRANSITION_LEN, ShotPlan
from app.cin.transitions import TRANSITIONS
from app.encoding import write_video

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1920
PUSH_IN_END = 1.08          # still shots zoom 1.00 -> 1.08 across the shot
UPPER_BIAS = 0.42           # punch-in crop sits slightly above centre (0.5 = centred)

try:  # spec §14: use cv2.resize when available
    import cv2  # type: ignore
except ImportError:  # cv2 is optional; not installed in the dev venv
    cv2 = None


class RenderError(RuntimeError):
    pass


def _resize(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    if arr.shape[1] == w and arr.shape[0] == h:
        return arr
    if cv2 is not None:
        return cv2.resize(arr, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.asarray(Image.fromarray(arr).resize((w, h), Image.BILINEAR))


def cover_fit(frame: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale to cover w x h and centre-crop. Never stretches (fal clips may not be 9:16)."""
    fh, fw = frame.shape[:2]
    scale = max(w / fw, h / fh)
    nw, nh = max(w, round(fw * scale)), max(h, round(fh * scale))
    big = _resize(frame, nw, nh)
    x, y = (nw - w) // 2, (nh - h) // 2
    return big[y:y + h, x:x + w]


def apply_framing(frame: np.ndarray, zoom: float, w: int, h: int) -> np.ndarray:
    if zoom <= 1.0001:
        return frame
    cw, ch = max(1, round(w / zoom)), max(1, round(h / zoom))
    x = (w - cw) // 2
    y = int((h - ch) * UPPER_BIAS)
    return _resize(np.ascontiguousarray(frame[y:y + ch, x:x + cw]), w, h)


class _Sources:
    """Opens each clip once. Per-reader access is monotonic, so MoviePy never re-seeks."""

    def __init__(self, job, w: int, h: int):
        self.job, self.w, self.h = job, w, h
        self._readers: dict = {}
        self._stills: dict = {}

    def clip_frame(self, rel: str, t: float) -> np.ndarray:
        from moviepy import VideoFileClip
        reader = self._readers.get(rel)
        if reader is None:
            path = self.job.resolve(rel)
            if not path.exists():
                raise RenderError(f"Clip missing: {rel}")
            reader = self._readers[rel] = VideoFileClip(str(path), audio=False)
        last = max(0.0, (reader.duration or 0.0) - 1.0 / (reader.fps or 30))
        frame = reader.get_frame(min(max(t, 0.0), last))
        return cover_fit(np.asarray(frame)[:, :, :3], self.w, self.h)

    def still(self, rel: str) -> np.ndarray:
        if rel not in self._stills:
            path = self.job.resolve(rel)
            if not path.exists():
                raise RenderError(f"Still image missing: {rel}")
            self._stills[rel] = cover_fit(np.asarray(Image.open(path).convert("RGB")), self.w, self.h)
        return self._stills[rel]

    def close(self) -> None:
        for reader in self._readers.values():
            try:
                reader.close()
            except Exception:  # noqa: BLE001
                pass
        self._readers.clear()


class ShotRenderer:
    def __init__(self, plan: ShotPlan, job, *, video_style: str = "photorealistic",
                 color_grade: Optional[str] = None, width: int = WIDTH, height: int = HEIGHT):
        self.plan, self.job, self.w, self.h = plan, job, width, height
        self.sources = _Sources(job, width, height)
        self.particles = ParticleSystem(preset=STYLE_PARTICLES.get(video_style, "dust"),
                                        width=width, height=height)
        self.color_grade = color_grade or None
        self._starts = [s.t0 for s in plan.shots]
        self._styled = [(plan.shots[i].t0, plan.shots[i].transition_in, i)
                        for i in range(1, len(plan.shots)) if plan.shots[i].transition_in != "cut"]

    def shot_frame(self, i: int, t: float) -> np.ndarray:
        shot = self.plan.shots[i]
        src = shot.source
        if src.type == "clip":
            frame = self.sources.clip_frame(src.path, src.clip_t0 + (t - shot.t0) * src.speed)
            return apply_framing(frame, shot.framing, self.w, self.h)
        progress = min(max((t - shot.t0) / max(shot.t1 - shot.t0, 1e-6), 0.0), 1.0)
        zoom = shot.framing * (1.0 + (PUSH_IN_END - 1.0) * progress)
        return apply_framing(self.sources.still(src.path), zoom, self.w, self.h)

    def base_frame(self, t: float) -> np.ndarray:
        half = TRANSITION_LEN / 2
        for boundary, name, j in self._styled:
            if boundary - half <= t < boundary + half:
                progress = (t - (boundary - half)) / TRANSITION_LEN
                return TRANSITIONS[name](self.shot_frame(j - 1, t), self.shot_frame(j, t), progress)
        i = min(max(bisect.bisect_right(self._starts, t) - 1, 0), len(self._starts) - 1)
        return self.shot_frame(i, t)

    def frame_at(self, t: float) -> np.ndarray:
        frame = self.base_frame(t)
        if self.color_grade:
            from app.video_editor import apply_color_grade
            frame = apply_color_grade(frame, self.color_grade)
        overlay = self.particles.render_frame(t)
        if overlay.size and overlay.shape[2] == 4 and overlay[:, :, 3].any():
            alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
            frame = (frame.astype(np.float32) * (1 - alpha) + overlay[:, :, :3] * alpha).astype(np.uint8)
        return np.ascontiguousarray(frame, dtype=np.uint8)

    def render(self, out_path, overlays: Optional[list] = None) -> Path:
        from moviepy import CompositeVideoClip, VideoClip
        clip = VideoClip(self.frame_at, duration=self.plan.duration).with_fps(self.plan.fps)
        if overlays:
            clip = CompositeVideoClip([clip] + list(overlays), size=(self.w, self.h)).with_duration(self.plan.duration)
        try:
            write_video(clip, out_path, fps=self.plan.fps)
        except RenderError:
            raise
        except Exception as e:  # noqa: BLE001 - spec §10: renderer errors fail the run
            raise RenderError(f"Render failed: {e}") from e
        finally:
            self.sources.close()
            clip.close()
        return Path(out_path)


def caption_overlays(plan: ShotPlan, subtitle_style: str, width: int = WIDTH, height: int = HEIGHT) -> list:
    """Phase A adapter: aligned caption groups -> the existing karaoke clips.

    Known debt, fixed by the Phase B caption rewrite: _create_karaoke_clips splits a group's time
    evenly across its words (app/video_editor.py:495) and places captions at y = 1570 (:512)."""
    from app.subtitle_styles import SubtitleRenderer
    from app.video_editor import SubtitleSegment, VideoEditor
    segments = [SubtitleSegment(text=" ".join(w.text for w in g.words), start=g.t0, end=g.t1)
                for g in plan.captions if g.words and g.t1 > g.t0]
    renderer = SubtitleRenderer(style=subtitle_style, width=width, height=height)
    return VideoEditor()._create_karaoke_clips(segments, renderer, skip_until=0.0)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_renderer.py tests/test_video_editor.py tests/test_cin_audio.py -q --tb=short -p no:cacheprovider`
Expected: `20 passed` (9 + 7 + 4)

- [ ] **Step 7: Commit**

```bash
git add app/cin/renderer.py app/cin/particles.py app/video_editor.py tests/test_cin_renderer.py tests/test_video_editor.py
git commit -m "feat: shot renderer with framing, still push-in and moving-frame transitions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Phase A audio mix and `render_job` (render → mix → loudnorm → mux)

Composes Tasks 9 and 10 into the per-job render used by both `run_pipeline` and `--rerender`. Music/SFX reuse the existing code paths (`app/video_editor.py:117-201`, `app/sfx.py:55`) — Phase C replaces them — but the mix now lands in `sources/mix.wav` at 48 kHz and is loudness-normalized on the mux. A previous `final.mp4` is moved to `final.prev.mp4`. Measured on the dev box: the full-size 8 s gold render with captions and the `tech` grade takes ≈ 70 s (≈ 0.29 s/frame) — a 40 s video therefore renders in ≈ 6 min; record the VPS number in the run report's `durations.render` (spec §14).

**Files:**
- Create: `app/cin/mix.py`, `app/cin/editor.py`
- Modify: `tests/conftest.py` (append `build_gold_job`)
- Test: `tests/test_cin_editor.py`

**Interfaces:**
- Consumes: `ShotRenderer`, `caption_overlays` (Task 10); `measure_loudness`, `mux_final`, `is_platform_safe` (Task 9); `JobPaths` (Task 7); `RunReport` (Task 7); `ShotPlan`, `ClipSpec`, `plan_segments` (Task 5); `VideoEditor._get_random_music_file`, `VideoEditor._prepare_background_music`, `SFXMixer.build_sfx_track` (existing).
- Produces (`app/cin/mix.py`): `mix_audio(narration, out_wav, duration: float, *, music_path: Optional[Path] = None, scene_starts=(), enable_sfx: bool = True) -> dict` (`{"music": posix path | None, "sfx": bool}`).
- Produces (`app/cin/editor.py`): `RenderOptions(pacing="standard", subtitle_style="bold_impact", video_style="photorealistic", color_grade="", enable_subtitles=True, enable_music=True, enable_sfx=True, music_mood="", strict=False)` with `to_json()` / `from_json(d)` (ignores unknown keys); `pick_music(options, report) -> Optional[Path]` (warns `music_missing`); `render_job(job: JobPaths, plan: ShotPlan, options: RenderOptions, report: RunReport) -> Path` (fills `report.loudness = {"I","TP","LRA"}`, `report.platform_safe = {"ok","issues"}`, durations `render`/`mix`/`encode`; warns `sfx_missing`, `loudness_skipped`).
- Produces (`tests/conftest.py`): `build_gold_job(tmp_path, durations=(5.0, 10.0), clip_size="360x640", topic="gold test") -> (JobPaths, Alignment, list[ClipSpec])`.

- [ ] **Step 1: Append the job builder to `tests/conftest.py`**

```python
# ---------------------------------------------------------------- job builder (Task 11)

def build_gold_job(tmp_path, durations=(5.0, 10.0), clip_size: str = "360x640", topic: str = "gold test"):
    """A ready-to-render job from the gold fixture: tone narration, scene images, synthetic clips.
    Returns (job, alignment, clip_specs). durations=(5, 10) keeps one segment per scene."""
    from PIL import Image
    from app.cin.job import create_job
    from app.cin.shot_plan import ClipSpec, plan_segments

    fx = load_fixture("words_gold_8s.json")
    alignment = fixture_alignment("words_gold_8s.json")
    job = create_job(topic, Path(tmp_path) / "output")
    make_tone(job.narration, fx["duration"])
    job.words.write_text(json.dumps(fx["words"]), encoding="utf-8")
    job.alignment.write_text(json.dumps(alignment.to_json()), encoding="utf-8")
    specs = []
    for seg in plan_segments(alignment, durations):
        image = job.image(seg.scene)
        if not image.exists():
            Image.new("RGB", (1080, 1920), (60 + 90 * seg.scene, 80, 150)).save(image)
        clip = make_test_clip(job.clip(seg.name), seg.requested_len, size=clip_size,
                              color=("red", "blue", "green")[seg.scene % 3])
        specs.append(ClipSpec(seg.scene, seg.index, seg.t0, seg.t1, seg.requested_len, job.rel(image),
                              path=job.rel(clip), duration=seg.requested_len, model="kling", attempts=1))
    return job, alignment, specs
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_cin_editor.py`:

```python
"""render_job: shot render -> mix -> two-pass loudnorm -> mux -> checks (spec §9)."""
import pytest

from app.cin.editor import RenderOptions, pick_music, render_job
from app.cin.report import RunReport
from app.cin.shot_plan import build_shot_plan
from app.encoding import faststart_ok, probe_video
from tests.conftest import build_gold_job, make_silence, make_test_clip


def test_render_options_roundtrip_ignores_unknown_keys():
    opts = RenderOptions(pacing="fast", color_grade="tech")
    assert RenderOptions.from_json({**opts.to_json(), "topic": "x"}) == opts
    assert RenderOptions.from_json(None) == RenderOptions()


def test_pick_music_reports_missing_library(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "music_dir", str(tmp_path / "music"))
    monkeypatch.setattr(settings, "music_enabled", True)
    (tmp_path / "music" / "epic").mkdir(parents=True)
    report = RunReport(job="j")
    assert pick_music(RenderOptions(music_mood="epic"), report) is None
    assert [w["code"] for w in report.warnings] == ["music_missing"]
    assert pick_music(RenderOptions(enable_music=False), RunReport(job="j")) is None


class _TinyRenderer:
    """Stands in for ShotRenderer: writes a small clip instead of rendering frames."""

    def __init__(self, plan, job, **kwargs):
        self.plan = plan

    def render(self, out_path, overlays=None):
        return make_test_clip(out_path, self.plan.duration)


def test_silent_mix_skips_loudnorm_and_keeps_previous_final(tmp_path, monkeypatch):
    job, alignment, specs = build_gold_job(tmp_path)
    make_silence(job.narration, 8.0)
    job.final.write_bytes(b"old render")
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    report = RunReport(job=job.name)
    plan = build_shot_plan(alignment, "standard", specs)
    render_job(job, plan, RenderOptions(enable_music=False, enable_sfx=False, enable_subtitles=False), report)
    assert "loudness_skipped" in [w["code"] for w in report.warnings]
    assert job.final_prev.read_bytes() == b"old render"
    assert probe_video(job.final)["has_audio"] is True
    assert not job.render_tmp.exists()
    assert job.mix.exists()


@pytest.mark.render
def test_render_job_full_size_meets_delivery_spec(tmp_path):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, "standard", specs)
    plan.shots[1].transition_in = "zoom_through"
    report = RunReport(job=job.name)
    final = render_job(job, plan, RenderOptions(enable_music=False, enable_sfx=False, color_grade="tech"), report)

    info = probe_video(final)
    assert (info["width"], info["height"], info["fps"]) == (1080, 1920, 30.0)
    assert info["pixel_format"] == "yuv420p" and info["color_primaries"] == "bt709"
    assert info["audio_codec"] == "aac" and info["audio_sample_rate"] == 48000
    assert abs(info["duration"] - 8.0) <= 0.05
    assert faststart_ok(final)
    assert -15.0 <= report.loudness["I"] <= -13.0
    assert report.loudness["TP"] <= -1.0
    assert report.platform_safe == {"ok": True, "issues": []}
    assert set(report.durations) >= {"render", "mix", "encode"}
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_editor.py -q --tb=line -p no:cacheprovider`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.cin.editor'`.

- [ ] **Step 4: Implement `app/cin/mix.py`**

```python
"""Phase A audio mix (spec §8.3 placeholder): narration + the existing music and SFX code paths,
written as a 48 kHz WAV to sources/mix.wav. Phase C replaces this with the music library,
ducking and voice polish; loudness normalization happens later, in app.encoding.mux_final."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings


def mix_audio(narration, out_wav, duration: float, *, music_path: Optional[Path] = None,
              scene_starts=(), enable_sfx: bool = True) -> dict:
    """Returns {"music": posix path or None, "sfx": bool}."""
    from moviepy import AudioFileClip, CompositeAudioClip
    from app.sfx import SFXMixer
    from app.video_editor import VideoEditor

    voice = AudioFileClip(str(narration))
    tracks = [voice.with_volume_scaled(settings.voice_volume)]
    info = {"music": None, "sfx": False}
    try:
        if music_path:
            tracks.append(VideoEditor()._prepare_background_music(Path(music_path), duration))
            info["music"] = Path(music_path).as_posix()
        if enable_sfx:
            sfx = SFXMixer().build_sfx_track(scene_timestamps=list(scene_starts), total_duration=duration)
            if sfx is not None:
                tracks.append(sfx)
                info["sfx"] = True
        mixed = CompositeAudioClip(tracks).with_duration(duration)
        mixed.write_audiofile(str(out_wav), fps=48000, nbytes=2, codec="pcm_s16le", logger=None)
    finally:
        for clip in [voice] + tracks:
            try:
                clip.close()
            except Exception:  # noqa: BLE001
                pass
    return info
```

- [ ] **Step 5: Implement `app/cin/editor.py`**

```python
"""Render orchestration for one job (spec §9): shot render -> mix -> loudnorm + copy-mux -> checks.
Shared by run_pipeline (main.py) and --rerender."""
from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from app.cin.align import Alignment
from app.cin.clip_sourcing import probe_clip_duration
from app.cin.job import JobPaths, open_job
from app.cin.mix import mix_audio
from app.cin.renderer import ShotRenderer, caption_overlays
from app.cin.report import RunReport
from app.cin.shot_plan import ClipSpec, ShotPlan, build_shot_plan
from app.config import settings
from app.encoding import is_platform_safe, measure_loudness, mux_final

logger = logging.getLogger(__name__)


@dataclass
class RenderOptions:
    pacing: str = "standard"
    subtitle_style: str = "bold_impact"
    video_style: str = "photorealistic"
    color_grade: str = ""
    enable_subtitles: bool = True
    enable_music: bool = True
    enable_sfx: bool = True
    music_mood: str = ""
    strict: bool = False

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: Optional[dict]) -> "RenderOptions":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


def pick_music(options: RenderOptions, report: RunReport) -> Optional[Path]:
    """Existing music path (VideoEditor._get_random_music_file); Phase C replaces it."""
    if not (options.enable_music and settings.music_enabled):
        return None
    from app.video_editor import VideoEditor
    path = VideoEditor(music_mood=options.music_mood)._get_random_music_file(options.music_mood)
    if path is None:
        report.warn("music_missing", f"No music files for mood '{options.music_mood or 'any'}' "
                    f"under {settings.music_dir}", {"mood": options.music_mood})
    return path


def render_job(job: JobPaths, plan: ShotPlan, options: RenderOptions, report: RunReport) -> Path:
    """Render plan into job.final. A previous final.mp4 is kept as final.prev.mp4."""
    job.render_tmp.mkdir(parents=True, exist_ok=True)
    video_tmp = job.render_tmp / "video.mp4"
    final_tmp = job.render_tmp / "final.mp4"

    with report.stage("render"):
        overlays = caption_overlays(plan, options.subtitle_style) if options.enable_subtitles else []
        ShotRenderer(plan, job, video_style=options.video_style,
                     color_grade=options.color_grade or None).render(video_tmp, overlays)

    with report.stage("mix"):
        sfx_on = options.enable_sfx and settings.enable_sfx
        info = mix_audio(job.narration, job.mix, plan.duration, music_path=pick_music(options, report),
                         scene_starts=[s.t0 for s in plan.scenes], enable_sfx=sfx_on)
        report.options["music_file"] = info["music"]
        if sfx_on and not info["sfx"]:
            report.warn("sfx_missing", f"No SFX files under {settings.sfx_dir}", {})

    with report.stage("encode"):
        measured = measure_loudness(job.mix)
        if measured is None:
            report.warn("loudness_skipped", "Mix is silent or unmeasurable; loudnorm skipped", {})
        mux_final(video_tmp, job.mix, final_tmp, measured)
        if job.final.exists():
            os.replace(job.final, job.final_prev)
        os.replace(final_tmp, job.final)
        loud = measure_loudness(job.final)
        report.loudness = ({"I": loud["input_i"], "TP": loud["input_tp"], "LRA": loud["input_lra"]}
                           if loud else None)
        ok, issues = is_platform_safe(job.final)
        report.platform_safe = {"ok": ok, "issues": issues}

    shutil.rmtree(job.render_tmp, ignore_errors=True)
    logger.info("Rendered %s", job.final)
    return job.final
```

- [ ] **Step 6: Run the tests (the `render` test takes about 70 s)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_editor.py -q --tb=short -p no:cacheprovider`
Expected: `4 passed`

- [ ] **Step 7: Commit**

```bash
git add app/cin/mix.py app/cin/editor.py tests/conftest.py tests/test_cin_editor.py
git commit -m "feat: render_job - shot render, Phase A mix, two-pass loudnorm mux, platform checks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 12: Pipeline reorder, failure semantics, `--pacing` / `--strict` / `--classic`, remove CinematicEngine

Rewires `run_pipeline` (`main.py:213-455`) to spec §4: script → normalize prompts → TTS into the job → (Whisper alignment ∥ images) → segments → clips → shot plan → `render_job`. Renderer exceptions now fail the run with sources kept (the silent fallback at `app/video_editor.py:685-686` is deleted with the cinematic branch `:668-686`); `--classic` (`main.py:502, 657-658`) is the only way to the old editor. `cleanup_temp()` is no longer called (`main.py:440-452`); old `sources/` are pruned at startup instead. `validate_config` stops demanding image/motion keys for `--mock` (today `python main.py --auto --mock` exits on a missing `FAL_API_KEY`, and this `.env` has none).

**Files:**
- Modify: `main.py:7-22` (imports), `:36-63` (`validate_config`), `:213-455` (`run_pipeline` + helpers), `:502-503` (CLI flags), `:528-539` and `:621-632` (pass new options), `:673` (validate call)
- Modify: `app/video_editor.py:620-686` (drop `cinematic`/`video_style` params and the cinematic branch)
- Delete: `app/cinematic.py`, `app/cin/multishot.py`, `tests/test_cinematic.py`, `tests/test_cin_multishot.py` (they assert the replaced per-scene engine and `plan_cuts`' conservative 1–2 cuts)
- Test: `tests/test_pipeline.py`, `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `normalize_prompt_counts` (Task 3); `align` (Task 4); `PACING`, `plan_segments`, `build_shot_plan` (Tasks 5–6); `create_job`, `prune_sources`, `RunReport` (Task 7); `generate_segment_clips`, `StrictModeError` (Task 8); `RenderOptions`, `render_job` (Task 11); `clip_model_for`, `snap_duration` (Task 2); `CostTracker.log_clip`, `get_video_items` (Task 2); `AssetManager.generate_audio(..., output_path=)`, `generate_images(..., output_dir=)` (Task 7).
- Produces: `run_pipeline(topic, use_mock_images=False, enable_subtitles=True, enable_music=True, persona=None, use_chroma_key=False, enable_motion=True, subtitle_style="bold_impact", enable_sfx=True, voice=None, upload=False, niche=None, video_style="", video_duration="", pacing: Optional[str] = None, strict: Optional[bool] = None, classic: bool = False) -> str` (path of `output/<job>/final.mp4`; existing callers in `app/generator_worker.py:65`, `app/scheduler.py:117`, `app/web/routes/api_generate.py:51` keep working unchanged); `validate_config(use_mock=False, enable_motion=True) -> bool`; CLI `--pacing {calm,fast,standard}`, `--strict`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline.py`:

```python
"""run_pipeline wiring: job folder, reorder, failure semantics, strict, classic, concurrency (spec §4, §9.2, §10).
Every test is offline: LLM, TTS, Whisper, metadata, fal and HTTP are patched."""
import json
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import main
from app.asset_manager import AssetManager, AudioResult
from app.cin.clip_sourcing import StrictModeError
from app.cin.renderer import RenderError
from app.config import settings
from app.content_engine import ScriptOutput
from tests.conftest import make_tone


@pytest.fixture
def offline(monkeypatch, tmp_path, gold):
    """Zero-network run_pipeline. Returns .out (output dir) and .state (set state["scene_texts"] to override)."""
    import requests

    def no_network(*args, **kwargs):
        raise AssertionError("network call attempted")

    out = tmp_path / "output"
    monkeypatch.setattr(settings, "output_dir", str(out))
    monkeypatch.setattr(settings, "music_enabled", False)
    monkeypatch.setattr(settings, "enable_sfx", False)
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_video_model", "hailuo")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setitem(sys.modules, "fal_client", None)

    state = {"scene_texts": gold["scene_texts"]}

    def fake_script(self, topic, **kwargs):
        return ScriptOutput(hook=gold["scene_texts"][0], body=gold["scene_texts"][1],
                            image_prompts=["gold bar", "gold cube", "vault", "scale", "hand"],
                            keywords=["gold"], motion_prompts=["slow push", "orbit"],
                            scene_texts=state["scene_texts"])

    def fake_tts(self, text, voice_id=None, output_path=None):
        make_tone(output_path, gold["duration"])
        return AudioResult(file_path=str(output_path), duration=gold["duration"])

    monkeypatch.setattr(main.ScriptGenerator, "generate_script", fake_script)
    monkeypatch.setattr(AssetManager, "generate_audio", fake_tts)
    monkeypatch.setattr("app.cin.align.transcribe_words", lambda path, model: gold["words"])
    monkeypatch.setattr(main.MetadataGenerator, "generate_metadata",
                        lambda self, topic, hook, keywords, niche="": {"title_tiktok": topic})
    monkeypatch.setattr(main.MetadataGenerator, "generate_thumbnail", lambda self, **kwargs: None)
    return SimpleNamespace(out=out, state=state)


def fake_render(job, plan, options, report):
    job.final.write_bytes(b"final")
    return job.final


def only_job(out):
    jobs = [p for p in out.iterdir() if p.is_dir() and (p / "sources").is_dir()]
    assert len(jobs) == 1
    return jobs[0]


def report_of(job_dir):
    return json.loads((job_dir / "run_report.json").read_text(encoding="utf-8"))


def test_job_folder_and_sources_written(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    out_path = main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    assert out_path == str(job / "final.mp4")
    for rel in ("sources/narration.mp3", "sources/words.json", "sources/alignment.json",
                "sources/shot_plan.json", "sources/images/scene00.png", "sources/images/scene01.png"):
        assert (job / rel).exists(), rel
    report = report_of(job)
    assert report["status"] == "ok"
    assert [w["code"] for w in report["warnings"]] == ["prompt_count_normalized"]   # 5 prompts, 2 scenes
    assert set(report["durations"]) >= {"script", "tts", "align", "images", "clips"}
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert all(s["source"]["type"] == "still" for s in plan["shots"])                 # --mock: stills, no warning
    assert plan["scenes"][1]["t0"] == 2.32


def test_paraphrased_scene_texts_render_with_alignment_fallback(offline, monkeypatch):
    offline.state["scene_texts"] = ["Gold is heavy.", "A small cube weighs as much as a car."]
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    report = report_of(only_job(offline.out))
    assert report["status"] == "ok"
    assert "alignment_fallback" in [w["code"] for w in report["warnings"]]


def test_renderer_error_fails_run_and_keeps_sources(offline, monkeypatch):
    def boom(*args, **kwargs):
        raise RenderError("boom")

    def classic_must_not_run(*args, **kwargs):
        raise AssertionError("classic editor used as a silent fallback")

    monkeypatch.setattr(main, "render_job", boom)
    monkeypatch.setattr(main.VideoEditor, "assemble_video", classic_must_not_run)
    with pytest.raises(RenderError):
        main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    report = report_of(job)
    assert report["status"] == "failed" and "boom" in report["error"]
    assert (job / "sources/narration.mp3").exists() and (job / "sources/shot_plan.json").exists()


@pytest.mark.parametrize("strict", [True, False])
def test_strict_mode_fails_before_render_on_still_fallback(offline, monkeypatch, strict):
    original = AssetManager.generate_images
    monkeypatch.setattr(AssetManager, "generate_images",
                        lambda self, prompts, use_mock=True, output_dir=None: original(self, prompts, True, output_dir))
    rendered = []
    monkeypatch.setattr(main, "render_job", lambda *a: rendered.append(1) or fake_render(*a))
    if strict:
        with pytest.raises(StrictModeError):
            main.run_pipeline("Gold facts", strict=True)          # fal_client missing -> every clip fails
        assert rendered == []
    else:
        main.run_pipeline("Gold facts", strict=False)
        assert rendered == [1]
    report = report_of(only_job(offline.out))
    assert report["status"] == ("failed" if strict else "ok")
    assert [w["code"] for w in report["warnings"]].count("still_fallback") == 3   # 3 hailuo segments
    assert report["clips"]["failed"] == 3


def test_classic_flag_uses_old_editor_inside_job_folder(offline, monkeypatch):
    calls = {}

    def fake_assemble(self, **kwargs):
        calls.update(kwargs, output_dir=self.output_dir)
        path = self.output_dir / kwargs["output_filename"]
        path.write_bytes(b"classic")
        return str(path)

    monkeypatch.setattr(main.VideoEditor, "assemble_video", fake_assemble)
    out_path = main.run_pipeline("Gold facts", use_mock_images=True, classic=True)
    job = only_job(offline.out)
    assert out_path == str(job / "final.mp4")
    assert calls["output_filename"] == "final.mp4" and calls["output_dir"] == job


def test_concurrent_runs_get_separate_job_folders(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    results, errors = [], []

    def go():
        try:
            results.append(main.run_pipeline("Same topic", use_mock_images=True))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(set(results)) == 2
    jobs = [p for p in offline.out.iterdir() if (p / "sources").is_dir()]
    assert len(jobs) == 2 and all((j / "sources/narration.mp3").exists() for j in jobs)


def test_old_sources_pruned_at_start(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    old = offline.out / "20250101_000000_old"
    (old / "sources").mkdir(parents=True)
    (old / "run_report.json").write_text("{}", encoding="utf-8")
    stamp = time.time() - 30 * 86400
    os.utime(old / "sources", (stamp, stamp))
    main.run_pipeline("Gold facts", use_mock_images=True)
    assert not (old / "sources").exists() and (old / "run_report.json").exists()


def test_validate_config_mock_skips_image_and_motion_keys(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(settings, "provider_mode", "mixed")
    monkeypatch.setattr(settings, "image_provider", "fal")
    monkeypatch.setattr(settings, "motion_provider", "fal")
    monkeypatch.setattr(settings, "fal_api_key", "")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    assert main.validate_config(use_mock=True) is True
    assert main.validate_config() is False


def test_unknown_pacing_rejected_before_any_work(offline):
    with pytest.raises(ValueError):
        main.run_pipeline("Gold facts", use_mock_images=True, pacing="hyper")
    assert not offline.out.exists() or not any(offline.out.iterdir())


@pytest.mark.render
def test_mock_run_end_to_end(offline):
    from app.encoding import probe_video
    out_path = main.run_pipeline("Gold facts", use_mock_images=True, enable_music=False, enable_sfx=False)
    job = only_job(offline.out)
    info = probe_video(out_path)
    assert (info["width"], info["height"], info["fps"], info["pixel_format"]) == (1080, 1920, 30.0, "yuv420p")
    assert abs(info["duration"] - 8.0) <= 0.05
    report = report_of(job)
    assert report["status"] == "ok" and report["platform_safe"]["ok"] is True
    assert -15.0 <= report["loudness"]["I"] <= -13.0
    assert (job / "sources/mix.wav").exists() and not (job / "_render").exists()
```

Append to `tests/test_cli.py`:

```python
def test_pacing_and_strict_flags():
    args = parse_args(["--auto", "--pacing", "fast", "--strict", "--classic"])
    assert args.pacing == "fast" and args.strict is True and args.classic is True


def test_pacing_and_strict_default_to_settings():
    args = parse_args([])
    assert args.pacing is None and args.strict is False and args.classic is False


def test_unknown_pacing_rejected():
    import pytest
    with pytest.raises(SystemExit):
        parse_args(["--pacing", "hyper"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_cli.py -q --tb=line -p no:cacheprovider -m "not render"`
Expected: FAIL — `AttributeError: <module 'main'> does not have the attribute 'render_job'`, `TypeError: run_pipeline() got an unexpected keyword argument 'classic'`, `error: unrecognized arguments: --pacing`.

- [ ] **Step 3: Replace the imports at `main.py:7-22`**

```python
import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from app.config import settings
from app.content_engine import ScriptGenerator, ScriptGeneratorError, normalize_prompt_counts
from app.asset_manager import AssetManager, AssetManagerError
from app.video_editor import VideoEditor, VideoEditorError
from app.animator import PortraitAnimator, AnimatorError
from app.trend_scout import TrendScout
from app.motion_gen import MotionGenerator, clip_model_for, snap_duration
from app.cost_tracker import CostTracker
from app.metadata_gen import MetadataGenerator
from app.uploader import YouTubeUploader, UploaderError
from app.cin.align import align
from app.cin.clip_sourcing import StrictModeError, generate_segment_clips
from app.cin.editor import RenderOptions, render_job
from app.cin.job import create_job, prune_sources
from app.cin.report import RunReport
from app.cin.shot_plan import PACING, build_shot_plan, plan_segments
```

- [ ] **Step 4: Make `validate_config` mock-aware (`main.py:36-59`)**

Replace the function head through the motion check (keep the TTS check and the error reporting below it):

```python
def validate_config(use_mock: bool = False, enable_motion: bool = True) -> bool:
    """Validate that required API keys are configured for selected providers.
    --mock makes no image or motion API calls, so those keys are not required then."""
    errors = []

    # LLM: only need OpenAI key if using OpenAI provider
    if settings.llm_provider == "openai" or settings.provider_mode == "api":
        if not settings.openai_api_key:
            errors.append("OPENAI_API_KEY is required when llm_provider=openai")

    if not use_mock:
        # Image: check key for selected provider
        if settings.image_provider == "fal":
            if not settings.fal_api_key:
                errors.append("FAL_API_KEY is required when image_provider=fal")
        elif settings.image_provider == "replicate":
            if not settings.replicate_api_token:
                errors.append("REPLICATE_API_TOKEN is required when image_provider=replicate")

    if not use_mock and enable_motion:
        # Motion: check key for selected provider
        if settings.motion_provider == "fal":
            if not settings.fal_api_key:
                errors.append("FAL_API_KEY is required when motion_provider=fal")
        elif settings.motion_provider == "replicate":
            if not settings.replicate_api_token:
                errors.append("REPLICATE_API_TOKEN is required when motion_provider=replicate")

```

and change the call in `main()` (line 673) to `if not validate_config(use_mock=args.mock, enable_motion=not args.no_motion):`.

- [ ] **Step 5: Replace `run_pipeline` (`main.py:213-455`) with the helpers and the new pipeline**

Delete everything from `def run_pipeline(` up to (not including) `def list_personas() -> list:` and insert:

```python
def _print_script(script) -> None:
    print()
    print("=" * 50)
    print("GENERATED SCRIPT")
    print("=" * 50)
    print(f"\nHOOK: {script.hook}")
    print(f"\nBODY:\n{script.body}")
    print("\nIMAGE PROMPTS:")
    for i, prompt in enumerate(script.image_prompts, 1):
        print(f"  {i}. {prompt}")
    print(f"\nKEYWORDS: {', '.join(script.keywords)}")
    print("=" * 50)
    print()


def _run_shot_editor(job, script, narration: str, duration: float, options: RenderOptions,
                     report: RunReport, asset_manager: AssetManager, use_mock_images: bool,
                     motion_on: bool):
    """Spec §4 order: (align || images) -> segments -> clips -> shot plan -> render + encode."""
    model = clip_model_for(settings.motion_provider, settings.fal_video_model)

    def make_images():
        start = time.perf_counter()
        try:
            return asset_manager.generate_images(script.image_prompts, use_mock=use_mock_images,
                                                 output_dir=job.images)
        finally:
            report.durations["images"] = round(time.perf_counter() - start, 2)

    with ThreadPoolExecutor(max_workers=1) as pool:
        images_future = pool.submit(make_images)
        with report.stage("align"):
            alignment, words = align(job.narration, script.scene_texts, narration, duration,
                                     num_scenes=len(script.image_prompts))
        image_paths = images_future.result()
    job.words.write_text(json.dumps(words, indent=1), encoding="utf-8")
    job.alignment.write_text(json.dumps(alignment.to_json(), indent=1), encoding="utf-8")
    if alignment.fallback:
        report.warn("alignment_fallback", f"Scene timing fell back to word counts ({alignment.reason})",
                    {"reason": alignment.reason, "match_ratio": round(alignment.match_ratio, 4)})

    requests_ = plan_segments(alignment, model.durations if motion_on else None)
    with report.stage("clips"):
        specs = generate_segment_clips(
            requests_, image_paths, script.motion_prompts, job, report,
            enable_motion=motion_on, model_key=model.key,
            fallback_model=settings.fal_video_fallback_model if settings.motion_provider == "fal" else None,
        )
    plan = build_shot_plan(alignment, options.pacing, specs)
    for w in plan.warnings:
        report.warn(w["code"], w["message"], w["detail"])
    plan.save(job.shot_plan)
    if options.strict and any(w["code"] == "still_fallback" for w in plan.warnings):
        raise StrictModeError("strict mode: the plan contains still-fallback shots (see run_report.json); "
                              f"sources kept in {job.root} for --rerender")
    final = render_job(job, plan, options, report)
    return str(final), image_paths, specs


def _run_classic(job, script, audio_result, options: RenderOptions, asset_manager: AssetManager,
                 use_mock_images: bool, enable_motion: bool, persona: Optional[str], use_chroma_key: bool):
    """The pre-shot-editor path (--classic, or persona hybrid mode), writing into the job folder."""
    image_paths = asset_manager.generate_images(script.image_prompts, use_mock=use_mock_images,
                                                output_dir=job.images)
    motion_clip_paths = None
    if enable_motion and script.motion_prompts and not use_mock_images:
        motion_clip_paths = MotionGenerator(temp_dir=str(job.clips)).generate_all_clips(
            image_paths, script.motion_prompts)

    video_editor = VideoEditor(music_mood=options.music_mood)
    video_editor.output_dir = job.root

    if persona:
        animator = PortraitAnimator()
        persona_path = animator.get_persona_path(persona)
        if not persona_path:
            raise AnimatorError(f"Persona not found: {persona}")
        animated = animator.animate_portrait(audio_path=audio_result.file_path,
                                             persona_image_path=str(persona_path),
                                             output_filename=f"animated_{job.name}.mp4")
        if animated:
            output = video_editor.assemble_hybrid_video(
                audio_path=audio_result.file_path, image_paths=image_paths, talking_head_path=animated,
                output_filename="final.mp4", enable_subtitles=options.enable_subtitles,
                enable_music=options.enable_music, use_chroma_key=use_chroma_key)
            return output, image_paths, motion_clip_paths
        logger.warning("Portrait animation failed (content filter), falling back to standard mode")

    output = video_editor.assemble_video(
        audio_path=audio_result.file_path, image_paths=image_paths, output_filename="final.mp4",
        hook_text=script.hook, enable_subtitles=options.enable_subtitles, enable_music=options.enable_music,
        motion_clip_paths=motion_clip_paths, pacing_hints=script.pacing_hints or None,
        subtitle_style=options.subtitle_style, color_grade=options.color_grade or None,
        enable_sfx=options.enable_sfx, title=script.hook, scene_texts=script.scene_texts or None,
    )
    return output, image_paths, motion_clip_paths


def _log_costs(video_id: str, report: RunReport, narration: str, use_mock_images: bool,
               image_count: int, specs=None, classic_clips=None) -> float:
    tracker = CostTracker()
    tracker.log_cost(video_id, "openai_gpt4o")
    if settings.elevenlabs_api_key:
        tracker.log_cost(video_id, "elevenlabs_tts", quantity=max(1, len(narration) // 1000))
    elif settings.openai_api_key:
        tracker.log_cost(video_id, "openai_tts", quantity=max(1, len(narration) // 1000))
    if not use_mock_images:
        tracker.log_cost(video_id, "flux_image", quantity=image_count)
    for spec in specs or []:
        if spec.path:
            tracker.log_clip(video_id, spec.model, seconds=spec.requested_len)
    if classic_clips:
        done = sum(1 for c in classic_clips if c is not None)
        if done:
            model = clip_model_for(settings.motion_provider, settings.fal_video_model)
            tracker.log_clip(video_id, model.key, seconds=snap_duration(5.0, model.durations) or 5.0, count=done)
    tracker.save()
    total = tracker.get_video_cost(video_id)
    report.cost = {"estimated": None, "actual": tracker.get_video_items(video_id), "total": total}
    logger.info(f"Total cost for this video: ${total:.2f}")
    return total


def run_pipeline(
    topic: str,
    use_mock_images: bool = False,
    enable_subtitles: bool = True,
    enable_music: bool = True,
    persona: Optional[str] = None,
    use_chroma_key: bool = False,
    # V2 parameters
    enable_motion: bool = True,
    subtitle_style: str = "bold_impact",
    enable_sfx: bool = True,
    voice: Optional[str] = None,
    upload: bool = False,
    niche: Optional[str] = None,
    # V3 parameters
    video_style: str = "",
    video_duration: str = "",
    # Shot editor (spec 2026-10-02)
    pacing: Optional[str] = None,
    strict: Optional[bool] = None,
    classic: bool = False,
) -> str:
    """
    Run the full video generation pipeline into output/<job>/ and return the path of final.mp4.

    Order (spec §4): script -> TTS -> (align || images) -> clip segments -> motion clips ->
    shot plan -> render -> encode. Sources stay in output/<job>/sources/ (also after a failure),
    so a fixed run can be rebuilt with `python main.py --rerender output/<job>`.
    pacing/strict default to settings.pacing / settings.strict. classic=True (or --classic, or a
    persona) uses the old VideoEditor path; renderer errors never fall back to it silently.
    """
    pacing = pacing or settings.pacing
    if pacing not in PACING:
        raise ValueError(f"Unknown pacing {pacing!r}; choose one of {sorted(PACING)}")
    strict = settings.strict if strict is None else strict
    classic = classic or not settings.cinematic_enabled or bool(persona)
    motion_on = enable_motion and not use_mock_images

    prune_sources(settings.output_dir, settings.keep_sources_days)
    job = create_job(topic, settings.output_dir)
    options = RenderOptions(
        pacing=pacing, subtitle_style=subtitle_style, video_style=video_style or settings.video_style,
        color_grade=settings.color_grade, enable_subtitles=enable_subtitles, enable_music=enable_music,
        enable_sfx=enable_sfx, music_mood=resolve_music_mood(niche, video_style), strict=strict,
    )
    report = RunReport(job=job.name, options={
        **options.to_json(), "topic": topic, "niche": niche or "", "enable_motion": motion_on,
        "use_mock_images": use_mock_images, "classic": classic,
    })
    logger.info(f"Job folder: {job.root}")

    try:
        logger.info("Generating script...")
        with report.stage("script"):
            script = ScriptGenerator().generate_script(
                topic, enable_v2=enable_motion, video_style=video_style, video_duration=video_duration)
        script, change = normalize_prompt_counts(script)
        if change:
            report.warn("prompt_count_normalized",
                        "LLM returned mismatched prompt counts; normalized before any paid generation", change)
        options.subtitle_style = resolve_subtitle_style(subtitle_style, video_style)
        report.options["subtitle_style"] = options.subtitle_style
        _print_script(script)

        logger.info("Generating audio narration...")
        asset_manager = AssetManager()
        full_narration = f"{script.hook} {script.body}"
        with report.stage("tts"):
            audio_result = asset_manager.generate_audio(full_narration, voice_id=voice, output_path=job.narration)
        logger.info(f"Audio generated: {audio_result.duration:.1f} seconds")

        specs, classic_clips = None, None
        if classic:
            output_path, image_paths, classic_clips = _run_classic(
                job, script, audio_result, options, asset_manager, use_mock_images, enable_motion,
                persona, use_chroma_key)
        else:
            output_path, image_paths, specs = _run_shot_editor(
                job, script, full_narration, audio_result.duration, options, report, asset_manager,
                use_mock_images, motion_on)
        logger.info(f"Video rendered successfully: {output_path}")

        video_id = job.name
        _log_costs(video_id, report, full_narration, use_mock_images, len(image_paths), specs, classic_clips)

        logger.info("Generating metadata...")
        meta_gen = MetadataGenerator()
        metadata = meta_gen.generate_metadata(topic=topic, hook=script.hook, keywords=script.keywords,
                                              niche=settings.niche)
        meta_gen.save_metadata(video_id, metadata)
        logger.info("Generating thumbnail...")
        meta_gen.generate_thumbnail(video_path=output_path, video_id=video_id,
                                    title=metadata.get("title_tiktok", topic))

        if upload:
            try:
                video_url = YouTubeUploader().upload(video_path=output_path, video_id=video_id, niche=niche)
                logger.info(f"YouTube upload complete: {video_url}")
            except UploaderError as e:
                logger.error(f"YouTube upload failed: {e}")

        report.status = "ok"
        return output_path

    except Exception as e:
        report.status = "failed"
        report.error = f"{type(e).__name__}: {e}"
        logger.error(f"Pipeline failed: {e} (sources kept in {job.root}; fix and --rerender)")
        raise
    finally:
        report.save(job.report)
```

- [ ] **Step 6: CLI flags and option plumbing**

Replace the `--classic` argument (`main.py:502-503`) with:

```python
    parser.add_argument("--classic", action="store_true",
                        help="Use the classic Ken Burns editor instead of the shot editor")
    parser.add_argument("--pacing", choices=sorted(PACING), default=None,
                        help="Shot pacing: calm, standard or fast (default: settings.pacing)")
    parser.add_argument("--strict", action="store_true",
                        help="Fail the run instead of shipping a still when a motion clip fails")
```

In `run_auto_mode`'s `run_pipeline(...)` call add after `niche=args.niche,`:

```python
                pacing=args.pacing,
                strict=args.strict or None,
                classic=args.classic,
```

and in `run_interactive_mode`'s call add after `enable_sfx=not args.no_sfx,`:

```python
            pacing=args.pacing,
            strict=args.strict or None,
            classic=args.classic,
```

`main()` keeps `if args.classic: settings.cinematic_enabled = False` (it also drives `app/web/routes/api_config.py:41`).

- [ ] **Step 7: Remove the cinematic engine**

In `app/video_editor.py` `assemble_video`, delete the two parameters under `# V3 parameters` (`cinematic: bool = True,` and `video_style: str = "photorealistic",`) and delete the block from `        # Use Cinematic Engine if enabled` through `            logger.warning("Cinematic engine failed, falling back to classic: %s", e)` (lines 668-686). Then:

```bash
git rm app/cinematic.py app/cin/multishot.py tests/test_cinematic.py tests/test_cin_multishot.py
```

Check nothing else references them:

Run: `grep -rn "cinematic import\|CinematicEngine\|multishot\|plan_cuts\|extract_shots" --include=*.py app main.py tests`
Expected: no output.

- [ ] **Step 8: Run the tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_cli.py tests/test_video_editor.py tests/test_generator_worker.py -q --tb=short -p no:cacheprovider`
Expected: `41 passed` (11 pipeline incl. the `render` end-to-end ≈ 70 s, 17 CLI, 7 video editor, 6 generator worker)

- [ ] **Step 9: Commit**

```bash
git add main.py app/video_editor.py tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: shot-editor pipeline order, job folders, strict/pacing/classic, no silent fallback" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12a: Web library finds videos in job folders

Task 12 writes each video to `output/<job>/final.mp4`, but the web library (`app/web/routes/api_library.py:19`) only globs `output/*.mp4`, and `get_video` (`:44`) only resolves `output/<id>.mp4`. Without this task every new video disappears from the web UI. Discovery moves into a pure helper so it can be tested without FastAPI (not installed in this venv). Metadata and thumbnails stay where `MetadataGenerator` already writes them (`output/metadata/<id>.json`, `output/thumbnails/<id>.png`, `app/metadata_gen.py:22-23`), keyed by `job.name` (Task 12 sets `video_id = job.name`).

**Files:**
- Create: `app/library.py`
- Modify: `app/web/routes/api_library.py:13-48`
- Test: `tests/test_library.py`

**Interfaces:**
- Consumes: job folder layout from Task 7 (`output/<job>/final.mp4`).
- Produces: `find_videos(output_dir: Path) -> list[dict]` (keys `id, filename, path, created, size_mb, has_thumbnail, metadata`, newest first, legacy flat `output/*.mp4` included); `resolve_video(output_dir: Path, video_id: str) -> Optional[Path]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_library.py
import json
import os
import time
from pathlib import Path

from app.library import find_videos, resolve_video


def _touch(path: Path, data: bytes = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_finds_job_folder_and_legacy_videos_newest_first(tmp_path):
    now = time.time()
    _touch(tmp_path / "old_flat.mp4", mtime=now - 100)
    _touch(tmp_path / "20261002_1200_rolex" / "final.mp4", mtime=now)
    _touch(tmp_path / "20261002_1200_rolex" / "final.prev.mp4", mtime=now)
    (tmp_path / "metadata").mkdir()
    (tmp_path / "metadata" / "20261002_1200_rolex.json").write_text(json.dumps({"title": "Rolex"}))
    _touch(tmp_path / "thumbnails" / "20261002_1200_rolex.png")

    videos = find_videos(tmp_path)

    assert [v["id"] for v in videos] == ["20261002_1200_rolex", "old_flat"]
    assert videos[0]["metadata"] == {"title": "Rolex"}
    assert videos[0]["has_thumbnail"] is True
    assert videos[1]["metadata"] is None


def test_folder_without_final_is_ignored(tmp_path):
    _touch(tmp_path / "20261002_1300_failed" / "sources" / "narration.mp3")
    assert find_videos(tmp_path) == []


def test_resolve_prefers_job_folder_then_legacy(tmp_path):
    job = _touch(tmp_path / "abc" / "final.mp4")
    flat = _touch(tmp_path / "legacy.mp4")
    assert resolve_video(tmp_path, "abc") == job
    assert resolve_video(tmp_path, "legacy") == flat
    assert resolve_video(tmp_path, "missing") is None


def test_resolve_rejects_path_traversal(tmp_path):
    _touch(tmp_path.parent / "secret" / "final.mp4")
    assert resolve_video(tmp_path, "../secret") is None
    assert resolve_video(tmp_path, "..\secret") is None


def test_missing_output_dir_returns_empty(tmp_path):
    assert find_videos(tmp_path / "nope") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_library.py -q --tb=short -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.library'`

- [ ] **Step 3: Write minimal implementation**

```python
# app/library.py
"""Locate rendered videos for the web library: job folders and legacy flat files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.\- ]+$")


def _entry(output_dir: Path, video_id: str, mp4: Path) -> dict:
    meta_path = output_dir / "metadata" / f"{video_id}.json"
    thumb_path = output_dir / "thumbnails" / f"{video_id}.png"
    metadata = None
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            metadata = None
    stat = mp4.stat()
    return {
        "id": video_id,
        "filename": mp4.name,
        "path": str(mp4),
        "created": stat.st_mtime,
        "size_mb": round(stat.st_size / 1024 / 1024, 1),
        "has_thumbnail": thumb_path.exists(),
        "metadata": metadata,
    }


def find_videos(output_dir: Path) -> list[dict]:
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return []
    entries = [_entry(output_dir, mp4.stem, mp4) for mp4 in output_dir.glob("*.mp4")]
    entries += [_entry(output_dir, final.parent.name, final) for final in output_dir.glob("*/final.mp4")]
    return sorted(entries, key=lambda e: e["created"], reverse=True)


def resolve_video(output_dir: Path, video_id: str) -> Optional[Path]:
    if not _SAFE_ID.match(video_id) or ".." in video_id:
        return None
    output_dir = Path(output_dir)
    for candidate in (output_dir / video_id / "final.mp4", output_dir / f"{video_id}.mp4"):
        if candidate.is_file():
            return candidate
    return None
```

Then replace the bodies of `list_videos` and `get_video` in `app/web/routes/api_library.py`:

```python
from app.library import find_videos, resolve_video


@router.get("/library")
async def list_videos():
    videos = find_videos(Path(settings.output_dir))
    for v in videos:
        v.pop("path", None)
    return {"videos": videos}


@router.get("/library/{video_id}/video")
async def get_video(video_id: str):
    path = resolve_video(Path(settings.output_dir), video_id)
    if path is None:
        return {"error": "Video not found"}
    return FileResponse(path, media_type="video/mp4")
```

Leave `get_thumbnail` unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_library.py -q --tb=short -p no:cacheprovider`
Expected: `5 passed`

Then check the route module still parses (FastAPI is not installed here, so compile only):
Run: `.venv/Scripts/python.exe -m py_compile app/web/routes/api_library.py && echo ok`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add app/library.py app/web/routes/api_library.py tests/test_library.py
git commit -m "feat: web library lists videos from job folders" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: `--rerender <job_dir>`

Spec §9.3: rebuild `final.mp4` from `sources/` with zero API calls. Overrides in Phase A: `--pacing`, `--subtitle-style`, `--no-sfx`, `--no-music`, `--color-grade` (`--music-source` is Phase C). Scene boundaries and clips are fixed; `--pacing` changes cuts within scenes. It must branch before `validate_config()` (`main.py:673`) and skip the LLM metadata step.

**Files:**
- Modify: `app/cin/editor.py` (append re-render functions)
- Modify: `main.py` (`--rerender`, `--color-grade`, `--subtitle-style` default `None`, early branch in `main()`, `args.subtitle_style or settings.subtitle_style` in both run modes)
- Test: `tests/test_rerender.py`, `tests/test_cli.py` (append + update `test_default_args`)

**Interfaces:**
- Consumes: `render_job`, `RenderOptions` (Task 11); `open_job` (Task 7); `RunReport.load` (Task 7); `Alignment.from_json` (Task 4); `ShotPlan.load`, `ClipSpec`, `build_shot_plan` (Tasks 5–6); `probe_clip_duration` (Task 8).
- Produces (`app/cin/editor.py`): `clip_specs_from_plan(plan, job, enable_motion=True) -> list[ClipSpec]`; `rebuild_plan(job, pacing, enable_motion=True) -> ShotPlan`; `rerender_job(job_dir, *, pacing=None, subtitle_style=None, no_sfx=False, no_music=False, color_grade=None) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rerender.py`:

```python
"""--rerender: rebuild final.mp4 from sources/ with zero API calls (spec §9.3)."""
import shutil
import sys

import pytest

from app.cin.editor import RenderOptions, clip_specs_from_plan, rebuild_plan, render_job, rerender_job
from app.cin.job import open_job
from app.cin.report import RunReport
from app.cin.shot_plan import ShotPlan, build_shot_plan
from app.encoding import probe_video
from tests.conftest import build_gold_job


def saved_job(tmp_path, pacing="standard"):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, pacing, specs)
    plan.save(job.shot_plan)
    opts = RenderOptions(pacing=pacing, enable_music=False, enable_sfx=False)
    RunReport(job=job.name, options={**opts.to_json(), "enable_motion": True}).save(job.report)
    return job, plan


def test_rebuild_plan_changes_cuts_not_scenes(tmp_path):
    job, old = saved_job(tmp_path)
    new = rebuild_plan(job, "fast")
    assert len(old.shots) == 3 and len(new.shots) == 4
    assert [(s.t0, s.t1) for s in new.scenes] == [(s.t0, s.t1) for s in old.scenes]
    assert [g.clip for s in new.scenes for g in s.segments] == [g.clip for s in old.scenes for g in s.segments]


def test_missing_clip_becomes_failed_segment(tmp_path):
    job, old = saved_job(tmp_path)
    job.clip("scene01_a").unlink()
    specs = clip_specs_from_plan(old, job, enable_motion=True)
    assert specs[1].path is None and specs[1].failed is True
    assert specs[0].path == "sources/clips/scene00_a.mp4" and abs(specs[0].duration - 5.0) < 0.1


def test_rebuild_plan_after_moving_job_folder(tmp_path):
    job, old = saved_job(tmp_path)
    moved = shutil.move(str(job.root), str(tmp_path / "moved dir with spaces" / job.name))
    new = rebuild_plan(open_job(moved), "standard")
    assert [s.source.path for s in new.shots] == [s.source.path for s in old.shots]
    assert all(s.source.type == "clip" for s in new.shots)


def test_rerender_requires_a_job_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        rerender_job(tmp_path / "nope")


@pytest.mark.render
def test_rerender_fast_pacing_zero_network(tmp_path, monkeypatch):
    import requests

    def no_network(*args, **kwargs):
        raise AssertionError("network call during rerender")

    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setitem(sys.modules, "fal_client", None)
    monkeypatch.setattr("app.cin.align.transcribe_words", no_network)

    job, old = saved_job(tmp_path)
    render_job(job, old, RenderOptions(enable_music=False, enable_sfx=False), RunReport(job=job.name))
    first = job.final.stat().st_mtime_ns

    out = rerender_job(job.root, pacing="fast")

    assert out == str(job.final)
    assert job.final_prev.exists() and job.final.stat().st_mtime_ns >= first
    new = ShotPlan.load(job.shot_plan)
    assert new.pacing == "fast" and len(new.shots) == 4
    assert [(s.t0, s.t1) for s in new.scenes] == [(s.t0, s.t1) for s in old.scenes]
    report = RunReport.load(job.report)
    assert report.status == "ok" and report.options["pacing"] == "fast" and report.options["rerender"] is True
    info = probe_video(job.final)
    assert (info["width"], info["height"], info["fps"]) == (1080, 1920, 30.0)
```

Append to `tests/test_cli.py`:

```python
def test_rerender_flags():
    args = parse_args(["--rerender", "output/20261002_143005_rolex", "--pacing", "fast",
                       "--color-grade", "tech", "--subtitle-style", "neon_glow", "--no-music"])
    assert args.rerender == "output/20261002_143005_rolex"
    assert args.pacing == "fast" and args.color_grade == "tech"
    assert args.subtitle_style == "neon_glow" and args.no_music is True


def test_rerender_defaults_keep_job_options():
    args = parse_args([])
    assert args.rerender is None and args.color_grade is None and args.subtitle_style is None


def test_main_rerender_skips_config_validation(monkeypatch):
    import sys
    import pytest
    import main
    calls = {}

    def fake_rerender(job_dir, **kwargs):
        calls.update(kwargs, job_dir=job_dir)
        return f"{job_dir}/final.mp4"

    def must_not_validate(*args, **kwargs):
        raise AssertionError("validate_config must not run for --rerender")

    monkeypatch.setattr("app.cin.editor.rerender_job", fake_rerender)
    monkeypatch.setattr(main, "validate_config", must_not_validate)
    monkeypatch.setattr(sys, "argv", ["main.py", "--rerender", "output/job", "--pacing", "fast", "--no-sfx"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 0
    assert calls == {"job_dir": "output/job", "pacing": "fast", "subtitle_style": None,
                     "no_sfx": True, "no_music": False, "color_grade": None}
```

In `tests/test_cli.py::test_default_args` replace `assert args.subtitle_style == "bold_impact"` with:

```python
    assert args.subtitle_style is None          # resolved to settings.subtitle_style when generating
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rerender.py tests/test_cli.py -q --tb=line -p no:cacheprovider -m "not render"`
Expected: FAIL — `ImportError: cannot import name 'clip_specs_from_plan' from 'app.cin.editor'` and `error: unrecognized arguments: --rerender`.

- [ ] **Step 3: Append the re-render functions to `app/cin/editor.py`**

```python
# ---------------------------------------------------------------- re-render (spec §9.3)

_LETTERS = "abcdefghijklmnopqrstuvwxyz"
_CARRIED_WARNINGS = ("alignment_fallback", "prompt_count_normalized", "clip_retry")


def clip_specs_from_plan(plan: ShotPlan, job: JobPaths, enable_motion: bool = True) -> list:
    """Rebuild ClipSpecs from a saved plan. Clip lengths are re-probed; missing clip files
    become failed segments (stills) when motion was enabled for the job."""
    specs = []
    for sc in plan.scenes:
        for i, seg in enumerate(sc.segments):
            name = f"scene{sc.index:02d}_{_LETTERS[i]}"
            path = seg.clip if seg.clip and job.resolve(seg.clip).exists() else None
            last = job.last_frame(name)
            specs.append(ClipSpec(
                sc.index, i, seg.t0, seg.t1, seg.requested_len, seg.start_image,
                path=path,
                duration=probe_clip_duration(job.resolve(path)) if path else 0.0,
                last_frame=job.rel(last) if path and last.exists() else None,
                failed=enable_motion and path is None,
            ))
    return specs


def rebuild_plan(job: JobPaths, pacing: str, enable_motion: bool = True) -> ShotPlan:
    """Same scenes and clips, new cuts: --pacing only changes cuts within scenes (spec §9.3)."""
    alignment = Alignment.from_json(json.loads(job.alignment.read_text(encoding="utf-8")))
    old = ShotPlan.load(job.shot_plan)
    return build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))


def rerender_job(job_dir, *, pacing: Optional[str] = None, subtitle_style: Optional[str] = None,
                 no_sfx: bool = False, no_music: bool = False, color_grade: Optional[str] = None) -> str:
    """Rebuild final.mp4 from sources/ with zero API calls (spec §9.3)."""
    job = open_job(job_dir)
    prev = RunReport.load(job.report) if job.report.exists() else RunReport(job=job.name)
    opts = RenderOptions.from_json(prev.options)
    if pacing:
        opts.pacing = pacing
    if subtitle_style:
        opts.subtitle_style = subtitle_style
    if no_sfx:
        opts.enable_sfx = False
    if no_music:
        opts.enable_music = False
    if color_grade is not None:
        opts.color_grade = color_grade

    report = RunReport(job=job.name, options={**prev.options, **opts.to_json(), "rerender": True})
    report.cost = prev.cost                      # no new spend
    report.clips = prev.clips
    report.warnings = [w for w in prev.warnings if w.get("code") in _CARRIED_WARNINGS]
    try:
        with report.stage("plan"):
            plan = rebuild_plan(job, opts.pacing, enable_motion=bool(prev.options.get("enable_motion", True)))
        for w in plan.warnings:
            report.warn(w["code"], w["message"], w["detail"])
        plan.save(job.shot_plan)
        final = render_job(job, plan, opts, report)
        report.status = "ok"
        return str(final)
    except Exception as e:
        report.status = "failed"
        report.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        report.save(job.report)
```

- [ ] **Step 4: Wire the CLI in `main.py`**

Change `--subtitle-style` in `parse_args`:

```python
    parser.add_argument("--subtitle-style", type=str, default=None,
                        help="Subtitle preset (default bold_impact; with --rerender: keep the job's)")
```

Add after the `--strict` argument:

```python
    parser.add_argument("--rerender", type=str, default=None, metavar="JOB_DIR",
                        help="Rebuild output/<job>/final.mp4 from its sources/ with zero API calls")
    parser.add_argument("--color-grade", type=str, default=None,
                        help="Colour grade preset for --rerender (tech, finance, history, science, default; '' = none)")
```

In both `run_auto_mode` and `run_interactive_mode` change `subtitle_style=args.subtitle_style,` to `subtitle_style=args.subtitle_style or settings.subtitle_style,`. In `main()`, directly after `args = parse_args()`:

```python
    # Re-render needs no API keys and makes no API calls: handle it before validate_config().
    if args.rerender:
        from app.cin.editor import rerender_job
        try:
            out = rerender_job(args.rerender, pacing=args.pacing, subtitle_style=args.subtitle_style,
                               no_sfx=args.no_sfx, no_music=args.no_music, color_grade=args.color_grade)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Re-render failed: {e}")
            sys.exit(1)
        print(f"Re-rendered: {out}")
        sys.exit(0)
```

- [ ] **Step 5: Run the tests (the `render` test renders twice, about 90 s)**

Run: `.venv/Scripts/python.exe -m pytest tests/test_rerender.py tests/test_cli.py -q --tb=short -p no:cacheprovider`
Expected: `25 passed` (5 rerender + 20 CLI)

- [ ] **Step 6: Commit**

```bash
git add app/cin/editor.py main.py tests/test_rerender.py tests/test_cli.py
git commit -m "feat: --rerender rebuilds final.mp4 from job sources with zero API calls" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Full verification, mock end-to-end run, re-render check, docs

No paid run here (spec §12's ≈ $4.50 real run needs explicit approval). Note that `--mock` is not free of external calls: it still calls the LLM (`llm_provider=claude_cli` by default — the Claude CLI) and TTS (ElevenLabs, ≈ 1 k characters ≈ $0.01 at the configured rate). Images and motion are skipped. Ask the user before Step 3 if that spend is not already approved. The patched `tests/test_pipeline.py::test_mock_run_end_to_end` is the zero-network gate.

**Files:**
- Modify: `CLAUDE.md` (Commands section: new flags; fix the stale `app/dashboard.py` line)
- Modify: `.claude/memory.md` (progress note, per the project CLAUDE.md)

- [ ] **Step 1: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --tb=short -rf -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py`
Expected: exactly the 12 known failures listed in Global Constraints, 0 errors, everything else passed (about 4 minutes with the `render` tests). Quick loop without renders: add `-m "not render"`.

- [ ] **Step 2: Confirm no stale references**

Run: `grep -rn "cleanup_temp()" main.py; grep -rn "assets/temp/audio.mp3\|CinematicEngine" --include=*.py app main.py`
Expected: no output.

- [ ] **Step 3: Manual mock run (LLM + ~$0.01 TTS; no images, no motion)**

Use `base` to avoid a ≈ 460 MB `small` download (only `base.pt` is cached in `~/.cache/whisper`). The script step needs the `claude` CLI on PATH (`llm_provider=claude_cli`); `LLM_PROVIDER=openai` is the fallback and is a paid call:

Run: `WHISPER_MODEL=base .venv/Scripts/python.exe main.py --auto --topic "History of Rolex" --mock`
Expected: log ends with `Video rendered successfully: output/<YYYYMMDD_HHMMSS>_history_of_rolex/final.mp4` and `Total cost for this video: $...`; exit code 0. Note the job folder name as `JOB`.

- [ ] **Step 4: Inspect the job folder**

Run: `JOB=$(ls -dt output/*_history_of_rolex | head -1); ls "$JOB" "$JOB/sources" "$JOB/sources/images"`
Expected: `final.mp4  run_report.json  sources`; `alignment.json  clips  images  mix.wav  narration.mp3  shot_plan.json  words.json`; `scene00.png …`.

Run: `.venv/Scripts/python.exe -c "import json,sys; r=json.load(open(sys.argv[1]+'/run_report.json')); print(r['status'], r['loudness'], r['platform_safe'], [w['code'] for w in r['warnings']], r['durations'])" "$JOB"`
Expected: `ok {'I': -14.x, 'TP': <= -1.0, 'LRA': ...} {'ok': True, 'issues': []} [...]` — warnings may include `music_missing` and `sfx_missing` (empty libraries until Phase C) and `prompt_count_normalized`; `alignment_fallback` should be absent for a normal script.

- [ ] **Step 5: ffprobe and loudness on the first render**

Run: `ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,pix_fmt,color_primaries -of default=nw=1 "$JOB/final.mp4"`
Expected:
```
width=1080
height=1920
pix_fmt=yuv420p
color_primaries=bt709
r_frame_rate=30/1
```

Run: `ffmpeg -hide_banner -nostats -i "$JOB/final.mp4" -af loudnorm=I=-14:TP=-1:LRA=11:print_format=json -f null - 2>&1 | grep -E '"input_(i|tp|lra)"'`
Expected: `input_i` between -15.0 and -13.0, `input_tp` ≤ -1.0.

- [ ] **Step 6: Re-render with fast pacing, with outbound HTTP blocked**

Run: `.venv/Scripts/python.exe -c "import json,sys; print(len(json.load(open(sys.argv[1]+'/sources/shot_plan.json'))['shots']))" "$JOB"` (note the count as N1)
Run: `HTTPS_PROXY=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 .venv/Scripts/python.exe main.py --rerender "$JOB" --pacing fast`
Expected: `Re-rendered: output/.../final.mp4`, exit code 0 (any HTTP attempt would fail through the dead proxy).
Run: `ls "$JOB"; .venv/Scripts/python.exe -c "import json,sys; p=json.load(open(sys.argv[1]+'/sources/shot_plan.json')); print(p['pacing'], len(p['shots']), [s['t0'] for s in p['scenes']])" "$JOB"`
Expected: `final.mp4  final.prev.mp4  run_report.json  sources`; `fast N2 [...]` with N2 ≥ N1 (normally greater; a script whose scenes are all short can tie) and the same scene `t0` list as before.
Repeat the two Step 5 commands on the re-rendered `final.mp4`: same expected values.

- [ ] **Step 7: Document the new flags**

In `CLAUDE.md` replace `streamlit run app/dashboard.py` and its comment line with:

```bash
# Web UI
python main.py --serve
```

and add to the Commands block:

```bash
# Shot editor options (default pacing: standard)
python main.py --auto --pacing fast          # calm | standard | fast
python main.py --auto --strict               # fail instead of shipping a still when a clip fails
python main.py --auto --classic              # old Ken Burns editor

# Rebuild a finished job from output/<job>/sources with zero API calls
python main.py --rerender output/<job> --pacing fast --subtitle-style neon_glow --color-grade tech
```

Add a short "Shot editor Phase A — done" entry to `.claude/memory.md` (what landed, the 12 known unrelated failures, Phase B/C/D next).

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md .claude/memory.md
git commit -m "docs: shot editor Phase A flags and progress note" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (done while writing)

- **Spec coverage (Phase A):** §4 order → Task 12; §5 → Tasks 3–4; §6.1–6.5 → Tasks 5–6, 8 (generation), 10 (transitions from moving frames); §6.6 contract → Task 5; renderer replacing CinematicEngine with particles + colour grade per shot → Task 10; §9.1 → Tasks 9, 11; §9.2 job folder + prune → Tasks 7, 12; §9.3 → Task 13; §10 (renderer error fails run, `--classic`, retry → fallback → still, `strict`, prompt-count normalization, minimal `run_report.json`) → Tasks 3, 7, 8, 11, 12; §11 settings, `extra="ignore"`, per-model pricing → Tasks 1–2. Deferred by design: hook headline and caption safe zone (B), music library/LRU/ducking/voice polish/`--music-source` (C), web/scheduler/generator_worker plumbing and `/api/generate` warnings (D).
- **Placeholders:** none; every code step carries the code.
- **Name consistency checked:** `ClipSpec`, `SegmentRequest.name`, `plan_segments`, `build_shot_plan`, `ShotPlan.save/load`, `JobPaths.rel/resolve/image/clip/last_frame`, `RunReport.warn/stage/save/load`, `generate_segment_clips`, `generate_clip`, `render_job`, `RenderOptions`, `rerender_job`, `measure_loudness`, `mux_final`, `write_video`.
- **Prototype evidence:** the pure modules, clip sourcing, encoding, renderer, editor, pipeline and re-render code in this plan were run in a scratch copy of the repo on 2026-10-02 (all tests listed here passed there; the 8 s full-size renders took 27–86 s).
