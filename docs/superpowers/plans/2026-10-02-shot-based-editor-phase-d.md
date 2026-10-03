# Shot-Based Editor — Phase D (Options Plumbing, Run Report in the API, Housekeeping) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pacing`, `music_source` and `strict` reach every entry point (web Generate form, Scheduler slots, background worker, Settings page) exactly like the CLI does, the web UI shows each run's `run_report.json` warnings after generation and in the Library, and the cheap Phase A review debts are paid.

**Architecture:** One pure helper module, `app/run_options.py`, turns any option dict (web request body, scheduler slot config, worker arguments, Settings update) into validated `run_pipeline` keyword arguments with the CLI's rule "missing / `None` / `""` = Settings default", and builds the WebSocket result payloads from `run_report.json` via a never-raising `load_summary()` in `app/cin/report.py`. FastAPI routes, the APScheduler job and the JS pages become thin callers of that helper, because `fastapi` and `apscheduler` are not installed in the local venv and route code cannot be imported by tests. A failed `run_pipeline` keeps its exception type and gains a `job_dir` attribute so the web UI can show the failed run's warnings (the strict / still-fallback case).

**Tech Stack:** Python 3.14 venv (Docker 3.12), pydantic-settings 2.12, pytest 9, vanilla JS (no build step; `node` v24 on PATH for `node --check` and a throwaway DOM smoke script), ffmpeg 8.

**Spec:** `docs/superpowers/specs/2026-10-02-shot-based-editor-design.md` (Phase D = §13 D; §10 last bullet "`/api/generate` returns the report's `warnings` with the result"; §11 options table and "plumbed like `subtitle_style` (web generate request model + form, CLI flag, scheduler slot config, `Settings` default)"; §11 housekeeping `generator_worker.py` + `CLAUDE.md`; §10 classic-editor wording amendment by controller ruling).

**Written against the tree of 2026-10-03** — branch `feat/shot-editor-phase-b` at `66bed45` (Phase B Task 6 still in progress) — **as it will be after Phase C** (`docs/superpowers/plans/2026-10-02-shot-based-editor-phase-c.md`). Phase D uses these Phase C interfaces and nothing else from C:
- `app.cin.music_library.MUSIC_SOURCES = ("mine", "generated", "any", "none")` (C Task 1);
- `Settings.music_source: Literal["mine", "generated", "any", "none"] = "any"` (C Task 1);
- `main.run_pipeline(..., music_source: Optional[str] = None)` — `None` → `settings.music_source` (C Task 5);
- C adds warning codes `music_track_skipped`, `sfx_file_skipped`; **Phase D adds no warning codes** and does not touch `WARNING_CODES` or `test_new_warning_codes_registered`.

Files both phases change, and how they stay apart (every step quotes text anchors that exist in today's code and that Phase C does not edit; line numbers are hints only):
- `main.py`: C edits the import block below `from app.cin.shot_plan import ...` (adds `MUSIC_SOURCES`, later `MOODS, MUSIC_SOURCES`), `_run_shot_editor`, `_run_classic`, the `run_pipeline` signature/body above the `try:`, `parse_args`, `main()`. D edits only `from datetime import datetime`, the three `*Error` imports, `generate_output_filename`, inserts `_tag_job_dir` before `def run_pipeline(`, and the `except`/`finally` lines at the end of `run_pipeline`. D does not touch C's exact-kwargs `rerender_job(...)` CLI test.
- `app/cin/editor.py`: C edits `RenderOptions`, `pick_music`, the mix stage, `rebuild_plan` and `rerender_job`'s signature. D edits only `report.save(job.report)` in `rerender_job`'s `finally:`.
- `app/cin/report.py`: C edits `WARNING_CODES`. D adds `save_quietly` after `save` and `load_summary` at the end of the file.
- `app/config.py`: C appends settings after `strict: bool = False`. D edits only the `cinematic_enabled` comment.
- `CLAUDE.md`: C adds `--music-source` / builder lines after the `--rerender` example. D edits the classic line, removes the stale Series example and adds a Web UI block (Task 7 says where).
- `tests/test_cli.py`, `tests/test_pipeline.py`, `tests/test_rerender.py`: both phases only append tests.

**Dry-run evidence (2026-10-03):** Tasks 1–6 were applied to a scratch copy of today's tree under `%TEMP%`, with a three-line stand-in for Phase C (`app/cin/music_library.py` exporting `MUSIC_SOURCES`, `Settings.music_source`, and the `music_source` parameter on `run_pipeline`). Every new test failed before its change (except the two characterisation cases named in Task 6) and passed after; the full suite there gave **12 failed (the baseline list) / 426 passed** (= 377 − 6 deleted + 55 new); all seven JS files passed `node --check`, and the Task 4 DOM smoke script printed `UI smoke OK`. The repo itself was not modified.

## Global Constraints

- Run everything with the venv: `.venv/Scripts/python.exe` (Git Bash). Test prefix: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider`.
- **Precondition before Task 1:** Phase B and Phase C are implemented and committed on this branch (stacked: A → B → C → D). Check: `git log --oneline -15` shows C's last commit (`feat: --build-music-library / --build-sfx-library CLI flags; docs for Phase C audio`), `grep -n "MUSIC_SOURCES" app/cin/music_library.py` and `grep -n "music_source" app/config.py main.py` all hit, and `git status --short app main.py tests` shows nothing modified. If C is not in, stop: Task 1 imports `MUSIC_SOURCES` and Tasks 3/5 pass `music_source` to `run_pipeline`.
- Full-suite command: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py --tb=no -rf`. **Baseline measured 2026-10-03 on today's tree (Phase B in progress, before C): 12 failed, 377 passed (158 s)** — exactly the 12 out-of-scope failures: `test_local_image_gen.py::test_generate_creates_image`, `test_trend_scout.py::test_fetch_youtube_trending_with_api_key`, `test_trends.py::TestTrendScorer::{test_score_bounds,test_breakdown_keys,test_blocklist_blocks,test_recency_decay,test_niche_match_scoring}`, `test_trends.py::TestOrchestratorResilience::test_continues_on_source_failure`, and 4 in `test_uploader.py`. Re-measure once before Task 1 (C adds ≈ 64 tests) and write the passed count into the progress log. "Full suite green" means only these 12 fail. Task 6 deletes two test files (6 tests), so the passed count drops by 6 there — that is expected, not a regression.
- `fastapi`, `uvicorn` and `apscheduler` are **not installed** in the venv. `app/web/server.py`, `app/web/ws.py`, `app/web/routes/*.py` and `app/scheduler.py` cannot be imported by tests; `tests/test_web_api.py` and `tests/test_scheduler.py` stay ignored. Never add tests to those two files. All logic goes into `app/run_options.py`, `app/cin/report.py`, `app/library.py` (importable) and is tested there; route and scheduler files are verified with `.venv/Scripts/python.exe -m py_compile <file>`, JS files with `node --check <file>`.
- Do not install packages. Do not start the web server (it needs fastapi). Zero network in tests: no test may call the LLM, TTS, fal or HTTP (the existing `offline` fixture in `tests/test_pipeline.py` enforces this for pipeline tests).
- Never print, paste or commit `.env` values. Tests that build `Settings` pass `_env_file=None`; failing-config runs use `--tb=no`. `/api/config` keeps returning only `has_*_key` booleans for secrets.
- Option rule (spec §11, matching the CLI in `main.py`): for `pacing`, `music_source`, `strict` a missing key, `None` or `""` means "use the Settings default" and is passed to `run_pipeline` as `None`. Values: `pacing` ∈ `calm | standard | fast` (default `standard`), `music_source` ∈ `mine | generated | any | none` (default `any`), `strict` bool (default `false`). Unknown values are rejected with HTTP 422 before a run starts; boolean strings (`"true"`, `"false"`, `"1"`, `"0"`, `"yes"`, `"no"`, `"on"`, `"off"`) are parsed, never Python-truthy.
- Code must also run on Python 3.12: no PEP 695 syntax; `from __future__ import annotations` is fine. No new dependencies.
- Repo source files use LF line endings. Edit them with the Edit tool (it preserves endings); do not rewrite files through Python `Path.write_text` on Windows (that converts them to CRLF and produces a whole-file diff).
- Commit only the files each task lists (the working tree has many unrelated untracked files: `output/*.png`, `scripts/`, `src/`, `nul`, ...). End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not commit this plan file.

**Phase D decisions (read before starting):**
- **Saved Settings now survive a restart.** Today `data/config.json` is merged into `GET /api/config` and applied in-process on `PUT`, but nothing applies it at startup (`_load_config` is referenced only in `app/web/routes/api_config.py`), so after a restart the Settings page *shows* a saved default that runs do not use. Without a fix the new Settings defaults for pacing/music source/strict would silently revert. The server lifespan now applies the saved file through `apply_saved_settings`, which validates the three option keys and skips (with a log warning) any bad saved value instead of stopping the server. This applies **all** saved keys at startup, which is what the page already claims; it is a behaviour change for anyone with an old `data/config.json`.
- **The web form's `strict` is an explicit checkbox,** pre-checked from `GET /api/config` (`loadDefaults()`), and always sent as `true`/`false` (a checkbox cannot say "default"). `pacing` / `music_source` use a "Default" option (value `""` → `null`), relabelled "Default (fast)" etc. once `/api/config` answers. The Scheduler modal uses a three-way select (Default / On / Off) for `strict` instead, because a slot is stored and an explicit `false` would freeze it against later Settings changes.
- **`/api/generate` result shape.** The WebSocket `complete` message's `result` changes from `{"video_id": "<full path to final.mp4>"}` to `{"video_id": "<job folder name>", "path": "<full path>", "job", "status", "error", "warnings": [{code, message, detail}], "loudness", "platform_safe"}`; `video_id` now equals the Library id. No JS reads the old `result.video_id` (checked: `generate.js`, `dashboard.js`, `app.js`, `ws.js`). The `error` message gains `result` with the failed job's summary (or `{"video_id": null, "status": "failed", "warnings": []}` when the failure happened before a job folder existed, e.g. topic discovery).
- **Failed run → job folder.** `run_pipeline` sets `exc.job_dir = str(job.root)` on the exception it re-raises; the type is unchanged (tests assert `RenderError` / `StrictModeError`).
- **Report writes never mask errors** (Phase A deferred minor): both `finally: report.save(...)` blocks (`run_pipeline`, `rerender_job`) become `report.save_quietly(...)`, which logs and returns `False` instead of raising.
- **Two existing web bugs on the template path are fixed, not inherited:** `api_generate.py` never passed `enable_music` to `run_pipeline` (the request model had it), and `generate.js` `getSelectedStyle()` queried the first `.style-card--selected` in the whole page — the *video style* card, which has no `data-style` — so the web always submitted `bold_impact` (and "Auto" never worked). `scheduler.py` hard-coded `"bold_impact"` instead of the Settings default and ignored `enable_music`; the helper fixes both.
- **CLAUDE.md:** the stale `app/dashboard.py` reference the spec mentions is **already gone** (neither HEAD nor the working copy has it; Phase A replaced it with `python main.py --serve`). The remaining stale entry is the "Series mode" example: `--series` / `--parts` are parsed (`main.py` `parse_args`, asserted by `tests/test_cli.py::test_default_args`) but never read, so the example does nothing. Phase D removes the example and leaves the flags (removing them is out of scope).
- **Housekeeping scope (from `.superpowers/sdd/2026-10-02-shot-based-editor-phase-a/progress.md`, "minor (deferred" lines):** fixed here — local image provider writing the shared `assets/temp` then `os.replace` (Task 7 minor), `faststart_ok` reading the whole file and `measure_loudness` `json.loads` outside `try` / NaN accepted (Task 9 minors), dead `generate_output_filename` + unused `*Error` imports in `main.py` and `report.save` in `finally` masking the original exception (Task 12 minors), plus the dead pre-shot-editor modules `app/cin/audio_analysis.py`, `depth.py`, `parallax.py`, `kinetic_text.py` (unreferenced by `app/`, `main.py`, `scripts/`, `src/`; only their own tests import them). Already fixed by earlier work, nothing to do: `_SAFE_ID` uses `fullmatch`; `api_library.py` has no unused imports. Left deferred (not cheap or not valuable now): textnorm minus/decades, `JobPaths.resolve` containment, `RunReport` unlocked `.tmp`, MoviePy close/debris items, duplicate legacy ids.
- **`generator_worker.py`** is referenced only by `tests/test_generator_worker.py` (no app caller today). The spec names it, so it is fixed minimally; deleting it is out of scope.
- **Out of scope:** new warning codes; scheduler history showing warnings (the Library shows them for every finished job); quality tiers / cost cap (sub-project 3); removing `--series`.

## Review Focus

1. **A finished video whose `run_report.json` is missing, truncated or not JSON** (killed process, legacy job, disk full during save): the Library listing and the `/api/generate` result must still work, with `status: "unknown"` and no warnings — pinned in Task 2 (`test_load_summary_never_raises`, `test_run_result_without_report_still_has_video_id`) and Task 3 (`test_missing_or_corrupt_report_never_breaks_the_listing`).
2. **A scheduler slot saved by the pre-Phase-D UI** (only `niche`, `voice`, `enable_motion`, `enable_sfx`): it must run with the Settings defaults for pacing / music source / strict, and with music on — pinned in Task 1 (`test_old_scheduler_slot_without_new_keys_runs_with_defaults`).
3. **A hand-edited or stale `data/config.json`** (invalid `pacing`, broken JSON, a list instead of an object): server startup applies the good keys, logs and skips the bad ones, never crashes — pinned in Task 1 (`test_saved_config_with_bad_values_never_stops_startup`, `test_config_file_missing_corrupt_or_not_an_object_is_empty`).
4. **A strict web run that fails on a still fallback:** the error the user sees must come with the `still_fallback` warnings from that job's report, and the exception type must stay `StrictModeError` — pinned in Task 2 (`test_failed_run_exposes_job_dir_without_changing_exception_type`, `test_run_failure_reads_the_failed_jobs_report`) and the Task 4 smoke script (error event renders the report).
5. **Booleans sent as strings** (curl `"strict": "false"`, older JSON slot configs): parsed to the right bool, garbage rejected with 422, never `bool("false") is True` — pinned in Task 1 (`test_bool_strings_are_parsed_never_truthy`, `test_bad_bool_is_rejected`).

## File Map

| File | Status | Responsibility |
|---|---|---|
| `app/run_options.py` | create | `pipeline_kwargs`, `to_bool`, `OptionError`, Settings-update cleaning/applying, `load_config_file`; WS payloads `run_result` / `run_failure` (Task 2) |
| `app/cin/report.py` | modify | `RunReport.save_quietly`, `load_summary` |
| `main.py` | modify | `_tag_job_dir`; `save_quietly` in `finally`; remove dead helper and unused imports (Task 6) |
| `app/cin/editor.py` | modify | `save_quietly` in `rerender_job`'s `finally` |
| `app/library.py` | modify | `status` + `warnings` per job-folder video |
| `app/web/routes/api_generate.py` | modify | request fields `pacing`/`music_source`/`strict`, `enable_music` passed, 422 on bad options, report in WS payloads |
| `app/web/ws.py` | modify | `send_error(..., result=None)` |
| `app/web/routes/api_config.py` | modify | expose/validate the three defaults; tolerant config file read |
| `app/web/server.py` | modify | apply saved `data/config.json` at startup |
| `app/web/routes/api_scheduler.py` | modify | 422 on bad slot options |
| `app/scheduler.py` | modify | slot config → `pipeline_kwargs` |
| `app/generator_worker.py` | modify | no hard-coded `enable_sfx=False`; new options |
| `app/web/static/js/{generate,settings,scheduler,library}.js` | modify | selects, strict control, run-report panel, library warnings, subtitle-style selector fix |
| `app/asset_manager.py`, `app/encoding.py`, `app/config.py` | modify | housekeeping (Task 6) |
| `app/cin/{audio_analysis,depth,parallax,kinetic_text}.py`, `tests/test_cin_{audio,depth}.py` | delete | dead modules and their tests |
| `CLAUDE.md`, spec §10, `.claude/memory.md` | modify | docs (Task 7) |
| `tests/test_run_options.py` | create | helper tests |
| `tests/test_cin_report.py`, `test_pipeline.py`, `test_rerender.py`, `test_library.py`, `test_generator_worker.py`, `test_asset_manager.py`, `test_encoding.py`, `test_cli.py` | modify | appended tests |

## Task Order and Dependencies

1 → 2 → 3 → 4. 5 needs 1. 6 is independent of 1–5 (it touches `main.py` lines Task 2 does not). 7 needs all. Tasks 5 and 6 can run in parallel after Task 1 / at any time.

---

### Task 1: Pure option helper (`app/run_options.py`)

**Files:**
- Create: `app/run_options.py`
- Test: `tests/test_run_options.py` (create)

**Interfaces:**
- Consumes: `app.cin.music_library.MUSIC_SOURCES` (Phase C), `app.cin.shot_plan.PACING` (dict, keys in order calm/standard/fast), `app.config.settings.subtitle_style`.
- Produces:
  - `PACING_CHOICES = ("calm", "standard", "fast")`, `MUSIC_SOURCE_CHOICES = ("mine", "generated", "any", "none")`
  - `class OptionError(ValueError)`
  - `to_bool(name: str, value, default: Optional[bool]) -> Optional[bool]`
  - `pipeline_kwargs(config: Mapping) -> dict` with exactly the keys `use_mock_images, enable_subtitles, enable_motion, enable_sfx, enable_music, subtitle_style, niche, video_style, video_duration, pacing, music_source, strict` (never `topic` / `voice`)
  - `clean_settings_updates(updates: Mapping) -> dict`, `apply_settings_updates(target, updates) -> list[str]`, `apply_saved_settings(target, saved) -> list[str]`, `load_config_file(path) -> dict`

- [ ] **Step 1: Check the precondition and re-measure the baseline**

Run the checks in Global Constraints ("Precondition before Task 1"), then the full-suite command. Expected: 12 failed (the listed ones). Record the passed count in the progress log as "Phase D baseline".

- [ ] **Step 2: Write the failing tests**

Create `tests/test_run_options.py`:

```python
"""Per-video options for the web form, scheduler and worker (spec §11) and the run-report payloads
(spec §10). Pure helpers: the web app and scheduler cannot be imported in the local venv."""
import json

import pytest

from app.config import Settings, settings
from app.run_options import (MUSIC_SOURCE_CHOICES, PACING_CHOICES, OptionError, apply_saved_settings,
                             apply_settings_updates, clean_settings_updates, load_config_file,
                             pipeline_kwargs, to_bool)


def test_choices_follow_spec_order():
    assert PACING_CHOICES == ("calm", "standard", "fast")
    assert MUSIC_SOURCE_CHOICES == ("mine", "generated", "any", "none")


def test_empty_config_means_settings_defaults(monkeypatch):
    monkeypatch.setattr(settings, "subtitle_style", "neon_glow")
    kw = pipeline_kwargs({})
    assert kw == {"use_mock_images": False, "enable_subtitles": True, "enable_motion": True,
                  "enable_sfx": True, "enable_music": True, "subtitle_style": "neon_glow",
                  "niche": None, "video_style": "", "video_duration": "",
                  "pacing": None, "music_source": None, "strict": None}


def test_old_scheduler_slot_without_new_keys_runs_with_defaults():
    """A slot saved by the pre-Phase-D UI: only niche/voice/enable_motion/enable_sfx."""
    kw = pipeline_kwargs({"niche": "tech", "voice": "auto", "enable_motion": False, "enable_sfx": True})
    assert kw["niche"] == "tech" and kw["enable_motion"] is False and kw["enable_music"] is True
    assert (kw["pacing"], kw["music_source"], kw["strict"]) == (None, None, None)
    assert "voice" not in kw and "topic" not in kw            # callers resolve these


def test_web_request_body_maps_to_run_pipeline_kwargs():
    body = {"topic": "x", "niche": "", "voice": "auto", "subtitle_style": "fire", "enable_motion": True,
            "enable_sfx": False, "enable_music": False, "use_mock": True, "auto_topic": False,
            "video_style": "anime", "video_duration": "short",
            "pacing": "fast", "music_source": "generated", "strict": True}
    kw = pipeline_kwargs(body)
    assert kw["use_mock_images"] is True and kw["enable_music"] is False and kw["enable_sfx"] is False
    assert kw["niche"] is None and kw["subtitle_style"] == "fire" and kw["video_style"] == "anime"
    assert (kw["pacing"], kw["music_source"], kw["strict"]) == ("fast", "generated", True)


def test_non_string_text_fields_fall_back_to_defaults(monkeypatch):
    monkeypatch.setattr(settings, "subtitle_style", "bold_impact")
    kw = pipeline_kwargs({"subtitle_style": 5, "niche": ["x"], "video_style": None})
    assert kw["subtitle_style"] == "bold_impact" and kw["niche"] is None and kw["video_style"] == ""


@pytest.mark.parametrize("value", ["", "  ", None])
def test_blank_choice_means_default(value):
    kw = pipeline_kwargs({"pacing": value, "music_source": value})
    assert kw["pacing"] is None and kw["music_source"] is None


def test_choices_are_case_and_space_tolerant():
    kw = pipeline_kwargs({"pacing": " Fast ", "music_source": "MINE"})
    assert (kw["pacing"], kw["music_source"]) == ("fast", "mine")


@pytest.mark.parametrize("key,value", [("pacing", "warp"), ("music_source", "spotify"), ("pacing", 3)])
def test_unknown_choice_is_rejected_with_the_choices(key, value):
    with pytest.raises(OptionError, match="choose one of"):
        pipeline_kwargs({key: value})


@pytest.mark.parametrize("value,expected", [(True, True), (False, False), ("true", True), ("False", False),
                                            ("1", True), ("0", False), ("yes", True), ("off", False),
                                            (1, True), (0, False)])
def test_bool_strings_are_parsed_never_truthy(value, expected):
    assert pipeline_kwargs({"strict": value})["strict"] is expected
    assert pipeline_kwargs({"enable_sfx": value})["enable_sfx"] is expected


@pytest.mark.parametrize("value", ["maybe", 2, [], {}])
def test_bad_bool_is_rejected(value):
    with pytest.raises(OptionError, match="true or false"):
        to_bool("strict", value, None)


def test_settings_update_cleaning():
    out = clean_settings_updates({"pacing": "Calm", "music_source": "none", "strict": "true", "niche": "tech"})
    assert out == {"pacing": "calm", "music_source": "none", "strict": True, "niche": "tech"}
    for bad in ({"pacing": "warp"}, {"pacing": ""}, {"music_source": ""}, {"strict": "maybe"}):
        with pytest.raises(OptionError):
            clean_settings_updates(bad)


def test_apply_settings_updates_sets_known_keys_only():
    s = Settings(_env_file=None)
    applied = apply_settings_updates(s, {"pacing": "fast", "not_a_setting": 1})
    assert applied == ["pacing"] and s.pacing == "fast" and not hasattr(s, "not_a_setting")


def test_saved_config_with_bad_values_never_stops_startup():
    """Hand-edited data/config.json: bad option values are skipped, good ones applied."""
    s = Settings(_env_file=None)
    saved = json.loads('{"pacing": "warp", "music_source": "mine", "strict": "maybe", "niche": "tech"}')
    applied = apply_saved_settings(s, saved)
    assert sorted(applied) == ["music_source", "niche"]
    assert s.pacing == "standard" and s.music_source == "mine" and s.strict is False and s.niche == "tech"


def test_config_file_missing_corrupt_or_not_an_object_is_empty(tmp_path):
    p = tmp_path / "config.json"
    assert load_config_file(p) == {}
    for bad in ("{oops", "[1, 2]", "\"text\""):
        p.write_text(bad, encoding="utf-8")
        assert load_config_file(p) == {}
    p.write_text('{"pacing": "fast"}', encoding="utf-8")
    assert load_config_file(p) == {"pacing": "fast"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_run_options.py -q --tb=line`
Expected: collection error `ModuleNotFoundError: No module named 'app.run_options'`.

- [ ] **Step 4: Implement `app/run_options.py`**

```python
"""Per-video options shared by the web form, the scheduler and the background worker (spec §11).

Pure: no FastAPI / APScheduler imports, so it is unit-tested in the local venv (which has neither).
The rule everywhere is the CLI's: an option that is missing, None or "" means "use the Settings
default", which run_pipeline applies (pacing / music_source / strict default to None there).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Optional

from app.cin.music_library import MUSIC_SOURCES
from app.cin.shot_plan import PACING
from app.config import settings

logger = logging.getLogger(__name__)

PACING_CHOICES = tuple(PACING)                 # ("calm", "standard", "fast"), spec §6.1 order
MUSIC_SOURCE_CHOICES = tuple(MUSIC_SOURCES)    # ("mine", "generated", "any", "none"), spec §8.1

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


class OptionError(ValueError):
    """An option value the pipeline would reject. Routes turn it into HTTP 422."""


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _choice(name: str, value: Any, choices: tuple) -> Optional[str]:
    if _blank(value):
        return None
    if not isinstance(value, str) or value.strip().lower() not in choices:
        raise OptionError(f"Unknown {name} {value!r}; choose one of {', '.join(choices)}")
    return value.strip().lower()


def to_bool(name: str, value: Any, default: Optional[bool]) -> Optional[bool]:
    """JSON bools pass through; "true"/"false"-style strings (curl, form posts) are parsed;
    anything else is rejected. Never Python truthiness: bool("false") is True."""
    if _blank(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE:
            return True
        if v in _FALSE:
            return False
    raise OptionError(f"{name} must be true or false, got {value!r}")


def pipeline_kwargs(config: Mapping[str, Any]) -> dict:
    """Web request body / scheduler slot config / worker arguments -> run_pipeline keyword
    arguments (everything except topic and voice, which callers resolve). Raises OptionError."""
    config = dict(config or {})
    return {
        "use_mock_images": to_bool("use_mock", config.get("use_mock"), False),
        "enable_subtitles": to_bool("enable_subtitles", config.get("enable_subtitles"), True),
        "enable_motion": to_bool("enable_motion", config.get("enable_motion"), True),
        "enable_sfx": to_bool("enable_sfx", config.get("enable_sfx"), True),
        "enable_music": to_bool("enable_music", config.get("enable_music"), True),
        "subtitle_style": _text(config.get("subtitle_style")) or settings.subtitle_style,
        "niche": _text(config.get("niche")) or None,
        "video_style": _text(config.get("video_style")),
        "video_duration": _text(config.get("video_duration")),
        "pacing": _choice("pacing", config.get("pacing"), PACING_CHOICES),
        "music_source": _choice("music_source", config.get("music_source"), MUSIC_SOURCE_CHOICES),
        "strict": to_bool("strict", config.get("strict"), None),
    }


def clean_settings_updates(updates: Mapping[str, Any]) -> dict:
    """Validate the per-video defaults inside a Settings update (PUT /api/config). Settings
    defaults must be concrete values, so blanks are rejected too. Other keys pass through."""
    cleaned = dict(updates or {})
    if "pacing" in cleaned:
        if _blank(cleaned["pacing"]):
            raise OptionError(f"pacing must be one of {', '.join(PACING_CHOICES)}")
        cleaned["pacing"] = _choice("pacing", cleaned["pacing"], PACING_CHOICES)
    if "music_source" in cleaned:
        if _blank(cleaned["music_source"]):
            raise OptionError(f"music_source must be one of {', '.join(MUSIC_SOURCE_CHOICES)}")
        cleaned["music_source"] = _choice("music_source", cleaned["music_source"], MUSIC_SOURCE_CHOICES)
    if "strict" in cleaned:
        cleaned["strict"] = to_bool("strict", cleaned["strict"], False)
    return cleaned


def apply_settings_updates(target, updates: Mapping[str, Any]) -> list:
    """setattr every key the Settings object knows (pydantic-settings does not validate
    assignment, so callers clean first). Returns the applied keys."""
    applied = []
    for key, value in (updates or {}).items():
        if hasattr(target, key):
            setattr(target, key, value)
            applied.append(key)
    return applied


def apply_saved_settings(target, saved: Mapping[str, Any]) -> list:
    """Server startup: apply data/config.json. A bad saved value (hand edit, older version) is
    skipped with a warning; it never stops the server. Returns the applied keys."""
    applied = []
    for key, value in (saved or {}).items():
        try:
            cleaned = clean_settings_updates({key: value})
        except OptionError as e:
            logger.warning("Ignoring saved setting %s from config.json: %s", key, e)
            continue
        applied += apply_settings_updates(target, cleaned)
    return applied


def load_config_file(path) -> dict:
    """data/config.json as a dict. Missing, unreadable or non-object content is an empty config."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable %s: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_run_options.py -q`
Expected: all pass (30 tests; Task 2 appends 3 more).

Then check the import cost (the API routes import this module at server start):
`.venv/Scripts/python.exe -c "import sys, app.run_options; print([m for m in ('torch', 'whisper', 'moviepy', 'fal_client') if m in sys.modules])"`
Expected: `[]` (dry run: ≈ 0.37 s total, numpy is the heaviest import). If a heavy module appears, replace the two `tuple(...)` constants with literals and add a test asserting they equal `tuple(PACING)` / `tuple(MUSIC_SOURCES)`, instead of importing `app.cin.shot_plan` / `app.cin.music_library` at module level.

- [ ] **Step 6: Commit**

```bash
git add app/run_options.py tests/test_run_options.py
git commit -m "feat: run_options helper maps web/scheduler/worker options to run_pipeline kwargs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Run report summary, failed-run job folder, report writes that never mask errors

**Files:**
- Modify: `app/cin/report.py` (after `def save`, end of file)
- Modify: `app/run_options.py` (imports, append two functions)
- Modify: `main.py` (insert before `def run_pipeline(`; `except`/`finally` at the end of `run_pipeline`)
- Modify: `app/cin/editor.py` (`rerender_job`'s `finally:`)
- Test: `tests/test_cin_report.py`, `tests/test_run_options.py`, `tests/test_pipeline.py`, `tests/test_rerender.py` (append)

**Interfaces:**
- Consumes: `RunReport` (`app/cin/report.py`), `run_pipeline` (`main.py`), `rerender_job` (`app/cin/editor.py`, Phase C signature with `music_source=`).
- Produces:
  - `RunReport.save_quietly(path) -> bool`
  - `load_summary(path) -> dict` with keys `job, status, error, warnings, loudness, platform_safe`; `warnings` is a list of `{"code": str, "message": str, "detail": dict}`; never raises
  - `run_result(final_path) -> dict` = `{"video_id": <job folder name>, "path": str, **load_summary(...)}`
  - `run_failure(exc) -> dict` = `{"video_id", **summary}` from `exc.job_dir`, or `{"video_id": None, "status": "failed", "warnings": []}`
  - Exceptions re-raised by `run_pipeline` carry `job_dir: str` (absolute job folder path)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cin_report.py`:

```python


def test_load_summary_of_a_saved_report(tmp_path):
    from app.cin.report import load_summary
    job = tmp_path / "20261003_1200_gold"
    job.mkdir()
    report = RunReport(job=job.name, status="ok")
    report.warn("still_fallback", "scene 1 is a still", {"scene": 1})
    report.loudness = {"I": -14.1, "TP": -1.2, "LRA": 5.0}
    report.save(job / "run_report.json")
    s = load_summary(job / "run_report.json")
    assert s == {"job": job.name, "status": "ok", "error": None,
                 "warnings": [{"code": "still_fallback", "message": "scene 1 is a still", "detail": {"scene": 1}}],
                 "loudness": {"I": -14.1, "TP": -1.2, "LRA": 5.0}, "platform_safe": None}


def test_load_summary_never_raises(tmp_path):
    from app.cin.report import load_summary
    job = tmp_path / "jobx"
    job.mkdir()
    missing = load_summary(job / "run_report.json")
    assert missing["status"] == "unknown" and missing["warnings"] == [] and missing["job"] == "jobx"
    for bad in (b"{not json", b"\xff\xfe\x00garbage", b"[1, 2]"):
        (job / "run_report.json").write_bytes(bad)
        s = load_summary(job / "run_report.json")
        assert s["status"] == "unknown" and s["warnings"] == [] and s["error"]
    (job / "run_report.json").write_text(json.dumps({"status": "ok", "warnings": ["oops", {"code": "x"}]}))
    s = load_summary(job / "run_report.json")
    assert s["warnings"] == [{"code": "x", "message": "", "detail": {}}] and s["job"] == "jobx"


def test_save_quietly_logs_instead_of_raising(tmp_path, caplog):
    report = RunReport(job="j")
    assert report.save_quietly(tmp_path / "missing_dir" / "run_report.json") is False
    assert "Could not write run report" in caplog.text
    assert report.save_quietly(tmp_path / "run_report.json") is True
```

Append to `tests/test_run_options.py`:

```python


def test_run_result_carries_report_warnings(tmp_path):
    from app.cin.report import RunReport
    from app.run_options import run_result
    job = tmp_path / "20261003_1200_gold"
    job.mkdir()
    report = RunReport(job=job.name, status="ok")
    report.warn("music_missing", "No music files", {"mood": "epic"})
    report.save(job / "run_report.json")
    out = run_result(job / "final.mp4")
    assert out["video_id"] == job.name and out["path"] == str(job / "final.mp4")
    assert out["status"] == "ok" and [w["code"] for w in out["warnings"]] == ["music_missing"]


def test_run_result_without_report_still_has_video_id(tmp_path):
    from app.run_options import run_result
    out = run_result(tmp_path / "jobz" / "final.20261003_120000.mp4")      # locked-final fallback name
    assert out["video_id"] == "jobz" and out["warnings"] == [] and out["status"] == "unknown"


def test_run_failure_reads_the_failed_jobs_report(tmp_path):
    from app.cin.report import RunReport
    from app.run_options import run_failure
    job = tmp_path / "jobf"
    job.mkdir()
    report = RunReport(job="jobf", status="failed", error="StrictModeError: strict mode")
    report.warn("still_fallback", "scene 0 is a still", {})
    report.save(job / "run_report.json")
    err = RuntimeError("strict mode")
    err.job_dir = str(job)
    out = run_failure(err)
    assert out["video_id"] == "jobf" and out["status"] == "failed"
    assert [w["code"] for w in out["warnings"]] == ["still_fallback"]
    assert run_failure(ValueError("no topics")) == {"video_id": None, "status": "failed", "warnings": []}
```

Append to `tests/test_pipeline.py` (`_raise`, `only_job`, `report_of`, `fake_render` and the `offline` fixture already exist in that file):

```python


def test_failed_run_exposes_job_dir_without_changing_exception_type(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", _raise(RenderError("boom")))
    with pytest.raises(RenderError) as info:
        main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    assert info.value.job_dir == str(job)
    assert report_of(job)["status"] == "failed"


def test_report_write_failure_does_not_mask_the_pipeline_error(offline, monkeypatch):
    from app.cin.report import RunReport
    monkeypatch.setattr(main, "render_job", _raise(RenderError("render died")))
    monkeypatch.setattr(RunReport, "save", _raise(OSError("disk full")))
    with pytest.raises(RenderError, match="render died"):
        main.run_pipeline("Gold facts", use_mock_images=True)


def test_report_write_failure_does_not_fail_a_finished_run(offline, monkeypatch):
    from app.cin.report import RunReport
    monkeypatch.setattr(main, "render_job", fake_render)
    monkeypatch.setattr(RunReport, "save", _raise(OSError("disk full")))
    out = main.run_pipeline("Gold facts", use_mock_images=True)
    assert out.endswith("final.mp4")
```

Append to `tests/test_rerender.py` (`saved_job`, `RunReport`, `rerender_job`, `pytest` already imported there):

```python


def test_rerender_report_write_failure_does_not_mask_render_error(tmp_path, monkeypatch):
    job, plan = saved_job(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("render died")

    def disk_full(self, path):
        raise OSError("disk full")

    monkeypatch.setattr("app.cin.editor.render_job", boom)
    monkeypatch.setattr(RunReport, "save", disk_full)
    with pytest.raises(RuntimeError, match="render died"):
        rerender_job(job.root, pacing="fast")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cin_report.py tests/test_run_options.py tests/test_pipeline.py tests/test_rerender.py -q --tb=line -m "not render"`
Expected: the 10 new tests fail — `ImportError: cannot import name 'load_summary'` / `'run_result'` / `'run_failure'`, `AttributeError: 'RunReport' object has no attribute 'save_quietly'`, `AttributeError: 'RenderError' object has no attribute 'job_dir'`, and `OSError: disk full` raised instead of the render error (three tests). Pre-existing tests pass.

- [ ] **Step 3: `app/cin/report.py`**

Directly after the `save` method (the block ending `        os.replace(tmp, path)`) and before `    @classmethod`, add:

```python
    def save_quietly(self, path) -> bool:
        """save() for finally-blocks: a failed write is logged, never raised, so it cannot replace
        the exception that is already propagating (or fail a finished render)."""
        try:
            self.save(path)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Could not write run report %s", path)
            return False
```

At the end of the file add:

```python


def load_summary(path) -> dict:
    """UI-safe view of run_report.json for /api/generate and the library. Never raises: a missing
    or unreadable report gives status "unknown" and no warnings, so a listing never fails on it."""
    path = Path(path)
    summary = {"job": path.parent.name, "status": "unknown", "error": None, "warnings": [],
               "loudness": None, "platform_safe": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return summary
    except (OSError, ValueError) as e:            # JSONDecodeError and UnicodeDecodeError are ValueErrors
        logger.warning("Unreadable run report %s: %s", path, e)
        return {**summary, "error": "run_report.json is unreadable"}
    if not isinstance(data, dict):
        return {**summary, "error": "run_report.json is not an object"}
    warnings = []
    for w in data.get("warnings") or []:
        if isinstance(w, dict):
            detail = w.get("detail")
            warnings.append({"code": str(w.get("code", "")), "message": str(w.get("message", "")),
                             "detail": detail if isinstance(detail, dict) else {}})
    return {**summary, "job": str(data.get("job") or summary["job"]),
            "status": str(data.get("status") or "unknown"), "error": data.get("error"),
            "warnings": warnings, "loudness": data.get("loudness"),
            "platform_safe": data.get("platform_safe")}
```

Also update the module docstring's second line from `durations, clip counts. Phase D surfaces it through /api/generate."""` to `durations, clip counts. load_summary() is the read side for /api/generate and the web library."""`.

- [ ] **Step 4: `app/run_options.py` payload builders**

Add the import below `from app.cin.music_library import MUSIC_SOURCES`:

```python
from app.cin.report import load_summary
```

Append at the end of the file:

```python


def run_result(final_path) -> dict:
    """WebSocket 'complete' payload: library id of the job plus the run report summary
    (spec §10: /api/generate returns the report's warnings with the result)."""
    final = Path(final_path)
    return {"video_id": final.parent.name, "path": str(final),
            **load_summary(final.parent / "run_report.json")}


def run_failure(exc: BaseException) -> dict:
    """WebSocket 'error' payload extras. run_pipeline tags exceptions with job_dir (main.py);
    errors raised before a job folder exists (topic discovery) carry no report."""
    job_dir = getattr(exc, "job_dir", None)
    if not job_dir:
        return {"video_id": None, "status": "failed", "warnings": []}
    return {"video_id": Path(job_dir).name, **load_summary(Path(job_dir) / "run_report.json")}
```

- [ ] **Step 5: `main.py`**

1. Immediately above the line `def run_pipeline(` insert:

```python
def _tag_job_dir(exc: BaseException, job_root) -> None:
    """Callers (web UI, scheduler) find run_report.json of a failed run via exc.job_dir.
    The exception type is unchanged; an exception that refuses attributes is left alone."""
    try:
        exc.job_dir = str(job_root)
    except (AttributeError, TypeError):
        pass


```

2. At the end of `run_pipeline`, replace

```python
        logger.error(f"Pipeline failed: {e} (sources kept in {job.root}; fix and --rerender)")
        raise
    finally:
        report.save(job.report)
```

with

```python
        logger.error(f"Pipeline failed: {e} (sources kept in {job.root}; fix and --rerender)")
        _tag_job_dir(e, job.root)
        raise
    finally:
        report.save_quietly(job.report)
```

- [ ] **Step 6: `app/cin/editor.py`**

In `rerender_job`, replace

```python
        raise
    finally:
        report.save(job.report)
```

with

```python
        raise
    finally:
        report.save_quietly(job.report)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cin_report.py tests/test_run_options.py tests/test_pipeline.py tests/test_rerender.py tests/test_cin_editor.py -q`
Expected: all pass, including the `render`-marked tests in `test_rerender.py` / `test_pipeline.py` / `test_cin_editor.py`.

- [ ] **Step 8: Commit**

```bash
git add app/cin/report.py app/run_options.py main.py app/cin/editor.py tests/test_cin_report.py tests/test_run_options.py tests/test_pipeline.py tests/test_rerender.py
git commit -m "feat: run report summary and payloads; failed runs expose job_dir; report writes never mask errors

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Web API — options in `/api/generate`, report in the WebSocket result, Settings defaults, Library warnings

**Files:**
- Modify: `app/library.py`
- Modify: `app/web/routes/api_generate.py` (whole file)
- Modify: `app/web/ws.py` (`send_error`)
- Modify: `app/web/routes/api_config.py`
- Modify: `app/web/server.py` (`lifespan`)
- Modify: `app/web/routes/api_scheduler.py`
- Test: `tests/test_library.py` (append); routes verified with `py_compile`

**Interfaces:**
- Consumes: `pipeline_kwargs`, `OptionError`, `clean_settings_updates`, `apply_settings_updates`, `apply_saved_settings`, `load_config_file` (Task 1); `run_result`, `run_failure`, `load_summary` (Task 2); `run_pipeline(..., music_source=)` (Phase C).
- Produces:
  - `find_videos()` entries gain `"status": str | None` and `"warnings": list` (`[]` and `None` for legacy flat files)
  - `POST /api/generate` body accepts `pacing`, `music_source`, `strict` (`null`/absent = Settings default); 422 with a readable `detail` string on a bad value
  - WS `{"type": "complete", "job_id", "result": run_result(...)}`; WS `{"type": "error", "job_id", "error", "result": run_failure(...)}`
  - `GET /api/config` includes `pacing`, `music_source`, `strict`; `PUT /api/config` returns 422 on a bad value
  - `POST/PUT /api/scheduler/jobs` return 422 on a bad slot option

- [ ] **Step 1: Write the failing library tests**

Append to `tests/test_library.py` (`_touch` and `find_videos` already exist there):

```python


def test_job_folder_entries_carry_run_report_warnings(tmp_path):
    from app.cin.report import RunReport
    job = tmp_path / "20261003_0900_gold"
    _touch(job / "final.mp4")
    report = RunReport(job=job.name, status="ok")
    report.warn("still_fallback", "scene 2 is a still", {"scene": 2})
    report.save(job / "run_report.json")
    _touch(tmp_path / "legacy.mp4")
    by_id = {v["id"]: v for v in find_videos(tmp_path)}
    assert by_id[job.name]["status"] == "ok"
    assert [w["code"] for w in by_id[job.name]["warnings"]] == ["still_fallback"]
    assert by_id["legacy"]["warnings"] == [] and by_id["legacy"]["status"] is None


def test_missing_or_corrupt_report_never_breaks_the_listing(tmp_path):
    _touch(tmp_path / "a" / "final.mp4")                      # no run_report.json
    _touch(tmp_path / "b" / "final.mp4")
    (tmp_path / "b" / "run_report.json").write_bytes(b"{truncated")
    videos = {v["id"]: v for v in find_videos(tmp_path)}
    assert videos["a"]["status"] == "unknown" and videos["a"]["warnings"] == []
    assert videos["b"]["status"] == "unknown" and videos["b"]["warnings"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_library.py -q --tb=line`
Expected: the two new tests fail with `KeyError: 'status'`; the others pass.

- [ ] **Step 3: `app/library.py`**

1. Below `from typing import Optional` add (with one blank line before it):

```python

from app.cin.report import load_summary
```

2. Replace `def _entry(output_dir: Path, video_id: str, mp4: Path) -> dict:` with

```python
def _entry(output_dir: Path, video_id: str, mp4: Path, report: Optional[Path] = None) -> dict:
```

3. Replace

```python
    stat = mp4.stat()
    return {
```

with

```python
    stat = mp4.stat()
    summary = load_summary(report) if report is not None else None    # legacy flat files have none
    return {
```

4. Replace

```python
        "metadata": metadata,
    }
```

with

```python
        "metadata": metadata,
        "status": summary["status"] if summary else None,
        "warnings": summary["warnings"] if summary else [],
    }
```

5. Replace

```python
    entries += [_entry(output_dir, final.parent.name, final) for final in output_dir.glob("*/final.mp4")]
```

with

```python
    entries += [_entry(output_dir, final.parent.name, final, final.parent / "run_report.json")
                for final in output_dir.glob("*/final.mp4")]
```

`app/web/routes/api_library.py` needs no change: it already returns every entry key except `path`.

- [ ] **Step 4: Run the library tests**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_library.py -q`
Expected: all pass.

- [ ] **Step 5: `app/web/routes/api_generate.py` (replace the whole file)**

```python
"""Video generation API endpoints."""
import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.run_options import OptionError, pipeline_kwargs, run_failure, run_result
from app.web.ws import ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    topic: str = ""
    niche: str = ""
    voice: str = "auto"
    subtitle_style: str = "bold_impact"
    enable_motion: bool = True
    enable_sfx: bool = True
    enable_music: bool = True
    use_mock: bool = False
    auto_topic: bool = False
    video_style: str = "photorealistic"
    video_duration: str = "medium"
    # Shot editor (spec §11). None / "" = the Settings default, like the CLI.
    pacing: Optional[str] = None            # calm | standard | fast
    music_source: Optional[str] = None      # mine | generated | any | none
    strict: Optional[bool] = None


class GenerateResponse(BaseModel):
    job_id: str
    status: str


@router.post("/generate")
async def generate_video(req: GenerateRequest) -> GenerateResponse:
    try:
        options = pipeline_kwargs(req.model_dump())       # reject bad options before starting
    except OptionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    job_id = str(uuid.uuid4())[:8]

    async def _run():
        try:
            await ws_manager.send_progress(job_id, "starting", 0.0, "Starting pipeline...")
            from main import run_pipeline, resolve_voice
            from app.trend_scout import TrendScout

            topic = req.topic
            if req.auto_topic or not topic:
                scout = TrendScout()
                topics = scout.discover_topics(niche=req.niche, count=1)
                topic = topics[0].title if topics else "Interesting facts about the world"

            voice_id = resolve_voice(req.voice, req.niche, req.video_style)
            await ws_manager.send_progress(job_id, "script", 0.1, f"Topic: {topic}")

            result = await asyncio.to_thread(run_pipeline, topic=topic, voice=voice_id, **options)

            # spec §10: the result carries the run report's warnings
            await ws_manager.send_complete(job_id, run_result(result))
        except Exception as e:
            logger.exception("Generation failed for job %s", job_id)
            await ws_manager.send_error(job_id, str(e), run_failure(e))

    asyncio.create_task(_run())
    return GenerateResponse(job_id=job_id, status="started")
```

This also passes `enable_music` (previously dropped) and `enable_subtitles=True` through `options`.

- [ ] **Step 6: `app/web/ws.py`**

Replace

```python
    async def send_error(self, job_id: str, error: str):
        await self.broadcast({"type": "error", "job_id": job_id, "error": error})
```

with

```python
    async def send_error(self, job_id: str, error: str, result: dict | None = None):
        await self.broadcast({"type": "error", "job_id": job_id, "error": error, "result": result})
```

- [ ] **Step 7: `app/web/routes/api_config.py`**

1. Replace

```python
from fastapi import APIRouter
from app.config import settings
```

with

```python
from fastapi import APIRouter, HTTPException
from app.config import settings
from app.run_options import OptionError, apply_settings_updates, clean_settings_updates, load_config_file
```

2. Replace the body of `_load_config`:

```python
def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}
```

with

```python
def _load_config() -> dict:
    return load_config_file(CONFIG_PATH)      # missing / corrupt file = empty config, never a 500
```

3. In `_save_config`, replace `    CONFIG_PATH.write_text(json.dumps(config, indent=2))` with `    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")`.

4. In `get_config`, after the line `        "cinematic_enabled": settings.cinematic_enabled,` add:

```python
        "pacing": settings.pacing,
        "music_source": settings.music_source,
        "strict": settings.strict,
```

5. Replace the whole `update_config` body:

```python
async def update_config(updates: dict):
    config = _load_config()
    config.update(updates)
    _save_config(config)
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return {"status": "ok", "config": config}
```

with

```python
async def update_config(updates: dict):
    try:
        updates = clean_settings_updates(updates)      # pydantic-settings does not validate setattr
    except OptionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    config = _load_config()
    config.update(updates)
    _save_config(config)
    apply_settings_updates(settings, updates)
    return {"status": "ok", "config": config}
```

The `json` import stays (used by `_save_config`).

- [ ] **Step 8: `app/web/server.py` — apply saved settings at startup**

In `lifespan`, replace

```python
    DATA_DIR.mkdir(exist_ok=True)
    logger.info("FVFactory server starting...")
```

with

```python
    DATA_DIR.mkdir(exist_ok=True)
    # Settings-page values survive a restart (before Phase D they were applied in-process only).
    from app.config import settings
    from app.run_options import apply_saved_settings, load_config_file
    from app.web.routes.api_config import CONFIG_PATH
    applied = apply_saved_settings(settings, load_config_file(CONFIG_PATH))
    if applied:
        logger.info("Applied saved settings from %s: %s", CONFIG_PATH, ", ".join(sorted(applied)))
    logger.info("FVFactory server starting...")
```

- [ ] **Step 9: `app/web/routes/api_scheduler.py` — reject bad slot options**

1. Replace

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
```

with

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.run_options import OptionError, pipeline_kwargs
```

2. Immediately above `class JobUpdate(BaseModel):` insert:

```python
def _check_config(config: dict | None) -> None:
    """Reject a slot whose options run_pipeline would refuse at run time (HTTP 422)."""
    if config is None:
        return
    try:
        pipeline_kwargs(config)
    except OptionError as e:
        raise HTTPException(status_code=422, detail=str(e))


```

3. In `create_job`, make `    _check_config(req.config)` the first line of the body (before `    from app.scheduler import get_scheduler`). In `update_job`, likewise make `    _check_config(req.config)` the first line.

- [ ] **Step 10: Verify the route files compile and the helpers still pass**

Run:

```bash
for f in app/web/routes/api_generate.py app/web/routes/api_config.py app/web/routes/api_scheduler.py app/web/ws.py app/web/server.py app/library.py; do .venv/Scripts/python.exe -m py_compile "$f" && echo "ok $f"; done
.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_library.py tests/test_run_options.py -q
grep -n "enable_music\|music_source\|strict" app/web/routes/api_generate.py
```

Expected: six `ok` lines; tests pass; the grep shows `music_source` / `strict` in `GenerateRequest` (enable_music is passed via `**options`). The routes cannot be imported here (no fastapi); do not try to start the server.

- [ ] **Step 11: Commit**

```bash
git add app/library.py app/web/routes/api_generate.py app/web/ws.py app/web/routes/api_config.py app/web/server.py app/web/routes/api_scheduler.py tests/test_library.py
git commit -m "feat: web API plumbs pacing/music_source/strict; run report warnings in generate result and library

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Web UI — selects, strict control, run-report panel, Library warnings

**Files:**
- Modify: `app/web/static/js/generate.js`
- Modify: `app/web/static/js/settings.js`
- Modify: `app/web/static/js/scheduler.js`
- Modify: `app/web/static/js/library.js`
- Verify: `node --check`, plus a throwaway DOM smoke script in the scratchpad (not committed)

**Interfaces:**
- Consumes: Task 3 API shapes — `GET /api/config` keys `pacing`, `music_source`, `strict`; WS `complete`/`error` `result.{video_id, status, warnings[]}`; Library entries `warnings[]`; 422 responses with a string `detail`.
- Produces: request body keys `pacing` (string or `null`), `music_source` (string or `null`), `strict` (bool) from the Generate page; Settings `PUT` keys `pacing`, `music_source` (strings), `strict` (bool); scheduler slot config keys `enable_music` (bool), `pacing`, `music_source` (string or `null`), `strict` (bool or `null`).

All markup reuses existing classes (`form-row`, `form-group`, `form-label`, `form-select`, `checkbox`, `toggle`, `badge badge--yellow|green|red`, `section__title`, `progress-log__entry`, `video-detail__meta-*`). Every server string inserted into HTML goes through the page's existing `escapeHtml`.

- [ ] **Step 1: Write the smoke script (the failing check)**

Create `<scratchpad>/ui_smoke.js` (outside the repo; `<scratchpad>` is the session scratchpad directory) with this content:

```javascript
// Phase D UI smoke: renders the four pages against a fake DOM and canned API responses.
// Usage: node ui_smoke.js <repo root>. Not committed; catches runtime template errors that
// `node --check` (syntax only) cannot.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = process.argv[2] || '.';
const js = (f) => fs.readFileSync(path.join(root, 'app/web/static/js', f), 'utf8');

const elements = {};
function el(id) {
  if (!elements[id]) {
    elements[id] = {
      id, innerHTML: '', value: '', textContent: '', dataset: {}, style: {},
      classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
        toggle(c, on) { (on ?? !this._s.has(c)) ? this._s.add(c) : this._s.delete(c); },
        contains(c) { return this._s.has(c); } },
      remove() {}, focus() {}, appendChild() {},
    };
  }
  return elements[id];
}
const appended = [];
const document = {
  readyState: 'complete',
  getElementById: el,
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => {
    const n = { innerHTML: '', className: '', id: '', onclick: null };
    Object.defineProperty(n, 'textContent', { set(v) {   // what escapeHtml() relies on
      n.innerHTML = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); } });
    return n;
  },
  body: { appendChild: (n) => appended.push(n) },
  addEventListener() {},
};
const responses = {
  '/api/config': { pacing: 'fast', music_source: 'mine', strict: true, cinematic_enabled: true },
  '/api/library': { videos: [{ id: 'job1', filename: 'final.mp4', created: 0, size_mb: 1, has_thumbnail: false,
    metadata: null, status: 'ok', warnings: [{ code: 'still_fallback', message: 'scene 1 <b>still</b>', detail: {} }] }] },
  '/api/scheduler/jobs': { jobs: [{ id: 'j1', name: 'Daily', cron_expression: '0 9 * * *', enabled: true,
    config: { niche: 'tech', pacing: 'calm', music_source: 'none', strict: false, subtitle_style: 'fire' } }] },
  '/api/scheduler/history': { history: [] },
};
const ctx = {
  document, console, setTimeout, location: { protocol: 'http:', host: 'x' },
  WebSocket: function () { ctx.sock = this; }, navigator: {}, confirm: () => true,
  fetch: async (url, init) => { if (init && init.body) ctx.posted = JSON.parse(init.body);
    return { ok: true, json: async () => (url === '/api/generate' ? { job_id: 'abc' } : responses[url] || {}) }; },
  FVToast: { show() {} }, FVRouter: { navigate() {} },
};
vm.createContext(ctx);
for (const f of ['ws.js', 'generate.js', 'settings.js', 'scheduler.js', 'library.js']) {
  vm.runInContext(js(f), ctx, { filename: f });
}
vm.runInContext('this.GeneratePage = GeneratePage; this.SettingsPage = SettingsPage; ' +
                'this.SchedulerPage = SchedulerPage; this.LibraryPage = LibraryPage;', ctx);

const must = (cond, msg) => { if (!cond) { console.error('FAIL: ' + msg); process.exitCode = 1; } };

(async () => {
  const gen = { innerHTML: '' };
  ctx.GeneratePage.render(gen);
  must(gen.innerHTML.includes('id="gen-pacing"') && gen.innerHTML.includes('id="gen-music-source"'), 'generate selects');
  must(gen.innerHTML.includes('id="cb-strict"') && gen.innerHTML.includes('id="run-report"'), 'strict + report');
  await new Promise(r => setTimeout(r, 10));
  must(el('cb-strict').classList.contains('checkbox--checked'), 'strict pre-checked from /api/config');
  Object.assign(el('gen-topic'), { value: 'Gold' });
  el('gen-pacing').value = 'calm';
  el('gen-music-source').value = '';
  await ctx.GeneratePage.submit();
  must(ctx.posted && ctx.posted.pacing === 'calm' && ctx.posted.music_source === null && ctx.posted.strict === true,
       'generate request carries pacing/music_source/strict: ' + JSON.stringify(ctx.posted));
  ctx.sock.onmessage({ data: JSON.stringify({ type: 'complete', job_id: 'abc', result: { video_id: 'job1',
    status: 'ok', warnings: [{ code: 'music_missing', message: 'No music <i>files</i>', detail: {} }] } }) });
  const rr = el('run-report');
  must(!rr.classList.contains('hidden') && rr.innerHTML.includes('music_missing'), 'run report shown on complete');
  must(rr.innerHTML.includes('No music &lt;i&gt;files&lt;/i&gt;'), 'run report escapes messages');
  ctx.sock.onmessage({ data: JSON.stringify({ type: 'error', job_id: 'abc', error: 'strict mode',
    result: { video_id: 'job1', status: 'failed', warnings: [{ code: 'still_fallback', message: 's', detail: {} }] } }) });
  must(rr.innerHTML.includes('failed') && rr.innerHTML.includes('still_fallback'), 'run report shown on error');

  await ctx.SettingsPage.render({ innerHTML: '' });
  const s = el('settings-content').innerHTML;
  must(s.includes('data-key="pacing"') && s.includes('data-key="music_source"'), 'settings selects');
  must(s.includes('<option value="fast" selected>') && s.includes('data-toggle-key="strict"'), 'settings values');
  must(s.includes('Shot editor (off = classic)'), 'cinematic toggle relabelled');

  await ctx.SchedulerPage.render({ innerHTML: '' });
  ctx.SchedulerPage.openEditModal('j1');
  const modal = appended[appended.length - 1].innerHTML;
  must(modal.includes('id="sched-pacing"') && modal.includes('<option value="calm" selected>'), 'scheduler pacing');
  must(modal.includes('<option value="false" selected>Off</option>') && modal.includes('id="sched-music"'), 'scheduler strict/music');

  await ctx.LibraryPage.render({ innerHTML: '' });
  const lib = el('library-content').innerHTML;
  must(lib.includes('&#9888; 1'), 'library warning badge');
  ctx.LibraryPage.openDetail(0);
  const detail = appended[appended.length - 1].innerHTML;
  must(detail.includes('still_fallback') && detail.includes('Run Report Warnings'), 'library detail warnings');
  must(detail.includes('scene 1 &lt;b&gt;still&lt;/b&gt;'), 'warning message is HTML-escaped');

  console.log(process.exitCode ? 'UI smoke FAILED' : 'UI smoke OK');
})();
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node <scratchpad>/ui_smoke.js .`
Expected: several `FAIL:` lines (e.g. `generate selects`, `settings selects`, `scheduler pacing`, `library warning badge`) and `UI smoke FAILED`.

- [ ] **Step 3: `generate.js`**

1. Below `  const STAGES = ['script', 'audio', 'images', 'motion', 'assembly'];` add:

```javascript
  // Shot editor options (spec §11). The "" option means "use the Settings default".
  const PACINGS = [
    { id: 'calm',     label: 'Calm (~4 s shots)' },
    { id: 'standard', label: 'Standard (~3 s shots)' },
    { id: 'fast',     label: 'Fast (~2 s shots)' },
  ];
  const MUSIC_SOURCES = [
    { id: 'any',       label: 'Any (my tracks + generated)' },
    { id: 'mine',      label: 'My tracks only' },
    { id: 'generated', label: 'Generated library only' },
    { id: 'none',      label: 'No music' },
  ];
```

2. In `render`, between the end of the Subtitle Style group and `        <!-- Toggles -->`, i.e. replace

```javascript
        <!-- Toggles -->
```

with

```javascript
        <!-- Pacing + Music Source -->
        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Pacing</label>
            <select class="form-select" id="gen-pacing">
              <option value="">Default</option>
              ${PACINGS.map(p => `<option value="${p.id}">${p.label}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Music Source</label>
            <select class="form-select" id="gen-music-source">
              <option value="">Default</option>
              ${MUSIC_SOURCES.map(m => `<option value="${m.id}">${m.label}</option>`).join('')}
            </select>
          </div>
        </div>

        <!-- Toggles -->
```

3. Replace

```javascript
            <span class="checkbox__label">Use mock images (free, for testing)</span>
          </div>
        </div>
```

with

```javascript
            <span class="checkbox__label">Use mock images (free, for testing)</span>
          </div>
        </div>

        <!-- Strict checkbox (pre-checked from Settings by loadDefaults) -->
        <div class="form-group">
          <div class="checkbox" id="cb-strict" onclick="GeneratePage.toggleCheckbox('cb-strict')">
            <div class="checkbox__box">&#10003;</div>
            <span class="checkbox__label">Strict: fail the run instead of shipping a still when a motion clip fails</span>
          </div>
        </div>
```

4. Replace the end of `render` plus nothing else:

```javascript
        <div class="progress-log" id="progress-log"></div>
      </div>
    `;
  }
```

with

```javascript
        <div class="progress-log" id="progress-log"></div>

        <!-- Run report (spec §10): filled from the WebSocket complete/error payload -->
        <div class="hidden" id="run-report" style="margin-top:var(--space-4)"></div>
      </div>
    `;
    loadDefaults();
  }

  async function loadDefaults() {
    try {
      const cfg = await (await fetch('/api/config')).json();
      const label = (selectId, value) => {
        const opt = document.querySelector(`#${selectId} option[value=""]`);
        if (opt && value) opt.textContent = `Default (${value})`;
      };
      label('gen-pacing', cfg.pacing);
      label('gen-music-source', cfg.music_source);
      if (cfg.strict === true) document.getElementById('cb-strict')?.classList.add('checkbox--checked');
    } catch (e) {
      // Labels stay "Default"; the server applies the Settings defaults anyway.
    }
  }
```

5. Fix the subtitle-style selector (it matched the video-style card first). Replace

```javascript
    return document.querySelector('.style-card--selected')?.dataset.style || 'bold_impact';
```

with

```javascript
    return document.querySelector('#style-grid .style-card--selected')?.dataset.style || 'bold_impact';
```

6. In `submit`, replace

```javascript
      video_duration: getSelectedDuration(),
    };
```

with

```javascript
      video_duration: getSelectedDuration(),
      pacing: document.getElementById('gen-pacing').value || null,
      music_source: document.getElementById('gen-music-source').value || null,
      strict: isChecked('cb-strict'),
    };
```

and replace

```javascript
      } else {
        throw new Error('No job_id in response');
      }
```

with

```javascript
      } else {
        throw new Error(typeof data.detail === 'string' ? data.detail : 'No job_id in response');
      }
```

7. In `showProgress`, replace

```javascript
    document.getElementById('progress-panel')?.classList.remove('hidden');
    logEntries = [];
```

with

```javascript
    document.getElementById('progress-panel')?.classList.remove('hidden');
    document.getElementById('run-report')?.classList.add('hidden');
    logEntries = [];
```

8. In `listenToWs`, replace

```javascript
      addLog('Pipeline complete!');
      FVToast.show('Video generated successfully!', 'success');
      resetButton();
```

with

```javascript
      addLog('Pipeline complete!');
      const n = ((data.result && data.result.warnings) || []).length;
      FVToast.show(n ? `Video generated with ${n} warning${n === 1 ? '' : 's'} (see Run Report)`
                     : 'Video generated successfully!', n ? 'warning' : 'success');
      showRunReport(data.result, null);
      resetButton();
```

and replace

```javascript
      FVToast.show('Generation failed: ' + (data.error || 'Unknown'), 'error');
      resetButton();
```

with

```javascript
      FVToast.show('Generation failed: ' + (data.error || 'Unknown'), 'error');
      showRunReport(data.result, data.error || 'Unknown error');
      resetButton();
```

9. Immediately above `  function resetButton() {` insert:

```javascript
  function showRunReport(result, error) {
    const el = document.getElementById('run-report');
    if (!el) return;
    const warnings = (result && result.warnings) || [];
    const status = error
      ? '<span class="badge badge--red">failed</span>'
      : warnings.length
        ? `<span class="badge badge--yellow">${warnings.length} warning${warnings.length === 1 ? '' : 's'}</span>`
        : '<span class="badge badge--green">no warnings</span>';
    const rows = warnings.map(w => `
      <div class="progress-log__entry">
        <span class="badge badge--yellow">${escapeHtml(w.code)}</span> ${escapeHtml(w.message)}
      </div>`).join('');
    const where = result && result.video_id
      ? `<div style="font-size:var(--text-xs);color:var(--text-muted);margin-top:var(--space-2)">Job: ${escapeHtml(result.video_id)}</div>`
      : '';
    const open = !error && result && result.video_id
      ? `<button class="btn btn--secondary" style="margin-top:var(--space-3)" onclick="FVRouter.navigate('/library')">Open Library</button>`
      : '';
    el.innerHTML = `
      <div class="section__title"><span class="section__title-icon">&#128203;</span>Run Report ${status}</div>
      ${rows}${where}${open}`;
    el.classList.remove('hidden');
  }

```

The module's `return { ... }` line stays as is (`loadDefaults` / `showRunReport` are internal).

- [ ] **Step 4: `settings.js`**

1. In the Generation Defaults accordion, replace

```javascript
                .map(s => `<option value="${s}" ${config.subtitle_style === s ? 'selected' : ''}>${s.replace(/_/g, ' ')}</option>`).join('')}
            </select>
          </div>
        </div>
```

with

```javascript
                .map(s => `<option value="${s}" ${config.subtitle_style === s ? 'selected' : ''}>${s.replace(/_/g, ' ')}</option>`).join('')}
            </select>
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label class="form-label">Default Pacing</label>
            <select class="form-select" data-key="pacing">
              ${['calm', 'standard', 'fast']
                .map(p => `<option value="${p}" ${(config.pacing || 'standard') === p ? 'selected' : ''}>${p}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">Default Music Source</label>
            <select class="form-select" data-key="music_source">
              ${['any', 'mine', 'generated', 'none']
                .map(m => `<option value="${m}" ${(config.music_source || 'any') === m ? 'selected' : ''}>${m}</option>`).join('')}
            </select>
          </div>
        </div>
```

2. Replace `          ${settingToggle('cinematic_enabled', 'Cinematic Engine', config.cinematic_enabled !== false)}` with `          ${settingToggle('cinematic_enabled', 'Shot editor (off = classic)', config.cinematic_enabled !== false)}`.

3. Replace `          ${settingToggle('music_enabled', 'Music', config.music_enabled !== false)}` with

```javascript
          ${settingToggle('music_enabled', 'Music', config.music_enabled !== false)}
          ${settingToggle('strict', 'Strict (fail instead of a still)', config.strict === true)}
```

4. In `save`, replace

```javascript
      if (!res.ok) throw new Error('Server error');
      config = { ...config, ...updates };
```

with

```javascript
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Server error');
      }
      config = { ...config, ...updates };
```

`save` already collects every `[data-key]` select and every `[data-toggle-key]` toggle, so `pacing`, `music_source` and `strict` are sent without further changes.

- [ ] **Step 5: `scheduler.js`**

1. In `openCreateModal`, replace (the end of the Niche/Voice row and the start of the toggles row)

```javascript
                ).join('')}
              </select>
            </div>
          </div>

          <div style="display:flex;gap:var(--space-8);flex-wrap:wrap">
```

with

```javascript
                ).join('')}
              </select>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label class="form-label">Pacing</label>
              <select class="form-select" id="sched-pacing">
                <option value="">Default</option>
                ${['calm', 'standard', 'fast'].map(p =>
                  `<option value="${p}" ${config.pacing === p ? 'selected' : ''}>${p.charAt(0).toUpperCase() + p.slice(1)}</option>`
                ).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Music Source</label>
              <select class="form-select" id="sched-music-source">
                <option value="">Default</option>
                ${['any', 'mine', 'generated', 'none'].map(m =>
                  `<option value="${m}" ${config.music_source === m ? 'selected' : ''}>${m.charAt(0).toUpperCase() + m.slice(1)}</option>`
                ).join('')}
              </select>
            </div>
          </div>

          <div class="form-group">
            <label class="form-label">Strict (fail instead of a still)</label>
            <select class="form-select" id="sched-strict">
              <option value="" ${config.strict === true || config.strict === false ? '' : 'selected'}>Default</option>
              <option value="true" ${config.strict === true ? 'selected' : ''}>On</option>
              <option value="false" ${config.strict === false ? 'selected' : ''}>Off</option>
            </select>
          </div>

          <div style="display:flex;gap:var(--space-8);flex-wrap:wrap">
```

2. Replace

```javascript
              <span class="toggle__label">SFX</span>
            </div>
          </div>
        </div>
        <div class="modal__footer">
```

with

```javascript
              <span class="toggle__label">SFX</span>
            </div>
            <div class="toggle ${config.enable_music !== false ? 'toggle--active' : ''}" id="sched-music" onclick="SchedulerPage._toggleEl('sched-music')">
              <div class="toggle__track"><div class="toggle__thumb"></div></div>
              <span class="toggle__label">Music</span>
            </div>
          </div>
        </div>
        <div class="modal__footer">
```

3. In `saveJob`, replace

```javascript
    const config = {
      niche: document.getElementById('sched-niche').value,
      voice: document.getElementById('sched-voice').value,
      enable_motion: document.getElementById('sched-motion').classList.contains('toggle--active'),
      enable_sfx: document.getElementById('sched-sfx').classList.contains('toggle--active'),
    };
```

with

```javascript
    const previous = (editId && jobs.find(j => j.id === editId)?.config) || {};
    const strict = document.getElementById('sched-strict').value;
    const config = {
      ...previous,               // keep keys this form does not edit (e.g. subtitle_style set via the API)
      niche: document.getElementById('sched-niche').value,
      voice: document.getElementById('sched-voice').value,
      enable_motion: document.getElementById('sched-motion').classList.contains('toggle--active'),
      enable_sfx: document.getElementById('sched-sfx').classList.contains('toggle--active'),
      enable_music: document.getElementById('sched-music').classList.contains('toggle--active'),
      pacing: document.getElementById('sched-pacing').value || null,              // null = Settings default
      music_source: document.getElementById('sched-music-source').value || null,
      strict: strict === '' ? null : strict === 'true',
    };
```

4. Replace

```javascript
      if (!res.ok) throw new Error('Server error');

      document.getElementById('sched-modal')?.remove();
```

with

```javascript
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Server error');
      }

      document.getElementById('sched-modal')?.remove();
```

- [ ] **Step 6: `library.js`**

1. In `renderCard`, replace

```javascript
              ${niche ? `<span class="badge badge--${nicheColor}">${escapeHtml(niche)}</span>` : ''}
```

with

```javascript
              ${(video.warnings || []).length ? `<span class="badge badge--yellow" title="Run report warnings">&#9888; ${video.warnings.length}</span>` : ''}
              ${niche ? `<span class="badge badge--${nicheColor}">${escapeHtml(niche)}</span>` : ''}
```

2. In `openDetail`, replace

```javascript
              <div class="video-detail__meta-section">
                <div class="video-detail__meta-label">File Info</div>
```

with

```javascript
              ${(video.warnings || []).length ? `
                <div class="video-detail__meta-section">
                  <div class="video-detail__meta-label">Run Report Warnings</div>
                  ${video.warnings.map(w => `
                    <div class="video-detail__meta-value">
                      <span class="badge badge--yellow">${escapeHtml(w.code)}</span> ${escapeHtml(w.message)}
                    </div>`).join('')}
                </div>
              ` : ''}

              <div class="video-detail__meta-section">
                <div class="video-detail__meta-label">File Info</div>
```

- [ ] **Step 7: Verify**

Run:

```bash
for f in app/web/static/js/*.js; do node --check "$f" && echo "ok $f"; done
node <scratchpad>/ui_smoke.js .
```

Expected: seven `ok` lines, then `UI smoke OK`. If `node` is missing, report that instead of claiming the check passed. A live browser check needs fastapi (not installed here) — note it in the hand-off as a manual check for the VPS/Docker image: Generate page shows the two selects and the strict box, a run shows the Run Report panel, Settings saves pacing/music source/strict, the Library card shows the warning badge.

- [ ] **Step 8: Commit**

```bash
git add app/web/static/js/generate.js app/web/static/js/settings.js app/web/static/js/scheduler.js app/web/static/js/library.js
git commit -m "feat: web UI pacing/music source/strict controls, run report panel, library warnings; fix subtitle style pick

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Scheduler slots and the background worker go through the helper

**Files:**
- Modify: `app/scheduler.py` (`_run_job`)
- Modify: `app/generator_worker.py` (`start`)
- Test: `tests/test_generator_worker.py` (append); `app/scheduler.py` verified with `py_compile`

**Interfaces:**
- Consumes: `pipeline_kwargs`, `OptionError` (Task 1); `run_pipeline(..., music_source=)` (Phase C).
- Produces: `GeneratorWorker.start(topic, niche="", voice="bill", subtitle_style="bold_impact", enable_motion=True, enable_sfx=True, enable_music=True, pacing=None, music_source=None, strict=None) -> bool`; raises `OptionError` (status stays `"idle"`) on an invalid option.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generator_worker.py`:

```python


def test_worker_passes_sfx_and_shot_editor_options():
    """spec §11: the worker no longer hard-codes enable_sfx=False; new options reach run_pipeline."""
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/j/final.mp4") as mock_pipe:
        w.start(topic="Test", niche="tech", pacing="fast", music_source="mine", strict=True)
        w._thread.join()
    kw = mock_pipe.call_args.kwargs
    assert kw["enable_sfx"] is True and kw["enable_music"] is True
    assert (kw["pacing"], kw["music_source"], kw["strict"]) == ("fast", "mine", True)
    assert kw["topic"] == "Test" and kw["niche"] == "tech"


def test_worker_defaults_leave_options_to_settings():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/j/final.mp4") as mock_pipe:
        w.start(topic="Test")
        w._thread.join()
    kw = mock_pipe.call_args.kwargs
    assert (kw["pacing"], kw["music_source"], kw["strict"]) == (None, None, None)
    assert kw["enable_sfx"] is True


def test_worker_rejects_bad_option_before_going_busy():
    import pytest
    from app.run_options import OptionError
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline") as mock_pipe:
        with pytest.raises(OptionError):
            w.start(topic="Test", pacing="warp")
    assert w.status == "idle" and not mock_pipe.called
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_generator_worker.py -q --tb=line`
Expected: the three new tests fail with `TypeError: GeneratorWorker.start() got an unexpected keyword argument 'pacing'` (first and third) and `KeyError: 'pacing'` (second); the six existing tests pass.

- [ ] **Step 3: `app/generator_worker.py`**

1. Replace `from main import run_pipeline, resolve_voice` with

```python
from app.run_options import pipeline_kwargs
from main import run_pipeline, resolve_voice
```

2. Replace

```python
    def start(self, topic: str, niche: str = "", voice: str = "bill",
              subtitle_style: str = "bold_impact",
              enable_motion: bool = True) -> bool:
        """Start generation. Returns False if already busy."""
        if self.status == "running":
            return False
```

with

```python
    def start(self, topic: str, niche: str = "", voice: str = "bill",
              subtitle_style: str = "bold_impact",
              enable_motion: bool = True, enable_sfx: bool = True, enable_music: bool = True,
              pacing: Optional[str] = None, music_source: Optional[str] = None,
              strict: Optional[bool] = None) -> bool:
        """Start generation. Returns False if already busy. pacing / music_source / strict = None
        use the Settings defaults; an invalid value raises OptionError before the worker goes busy."""
        if self.status == "running":
            return False
        options = pipeline_kwargs({
            "niche": niche, "subtitle_style": subtitle_style, "enable_motion": enable_motion,
            "enable_sfx": enable_sfx, "enable_music": enable_music,
            "pacing": pacing, "music_source": music_source, "strict": strict,
        })
```

3. Replace

```python
        self._kwargs = dict(
            topic=topic,
            enable_motion=enable_motion,
            subtitle_style=subtitle_style,
            enable_sfx=False,
            voice=voice_id,
            niche=niche or None,
        )
```

with

```python
        self._kwargs = dict(topic=topic, voice=voice_id, **options)
```

- [ ] **Step 4: `app/scheduler.py`**

In `_run_job`, replace

```python
        try:
            from main import run_pipeline, resolve_voice
            topic = config.get("topic", "")
```

with

```python
        try:
            from main import run_pipeline, resolve_voice
            from app.run_options import pipeline_kwargs
            options = pipeline_kwargs(config)          # spec §11: slot options; missing = Settings default
            topic = config.get("topic", "")
```

and replace

```python
            result = run_pipeline(
                topic=topic, niche=niche, voice=voice,
                enable_motion=config.get("enable_motion", True),
                subtitle_style=config.get("subtitle_style", "bold_impact"),
                enable_sfx=config.get("enable_sfx", True),
            )
```

with

```python
            result = run_pipeline(topic=topic, voice=voice, **options)
```

(`niche` stays a local: it is still used for `resolve_voice` and topic discovery; `options["niche"]` carries it to `run_pipeline`.) An invalid stored option raises `OptionError` inside the existing `try`, so the run is recorded as `failed` with the message, like any other error.

- [ ] **Step 5: Run tests and compile**

Run:

```bash
.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_generator_worker.py tests/test_run_options.py -q
.venv/Scripts/python.exe -m py_compile app/scheduler.py && echo "ok scheduler"
grep -n "enable_sfx=False\|bold_impact" app/generator_worker.py app/scheduler.py
```

Expected: tests pass; `ok scheduler`; the grep shows only the `subtitle_style: str = "bold_impact"` default in `generator_worker.py` (no `enable_sfx=False`, nothing in `scheduler.py`).

- [ ] **Step 6: Commit**

```bash
git add app/scheduler.py app/generator_worker.py tests/test_generator_worker.py
git commit -m "feat: scheduler slots and generator worker pass pacing/music_source/strict; worker keeps SFX on

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Housekeeping — job-folder local images, bounded faststart read, robust loudnorm parse, dead code

**Files:**
- Modify: `app/asset_manager.py` (imports, `_generate_images_local`)
- Modify: `app/encoding.py` (imports, `faststart_ok`, `measure_loudness`)
- Modify: `main.py` (imports, `generate_output_filename`)
- Modify: `app/config.py` (`cinematic_enabled` comment)
- Delete: `app/cin/audio_analysis.py`, `app/cin/depth.py`, `app/cin/parallax.py`, `app/cin/kinetic_text.py`, `tests/test_cin_audio.py`, `tests/test_cin_depth.py`
- Test: `tests/test_asset_manager.py`, `tests/test_encoding.py`, `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `app.encoding.FASTSTART_SCAN_BYTES = 4 * 1024 * 1024`; `measure_loudness` returns `None` (never raises, never NaN/inf) for unparseable or non-finite output; local image provider writes into `output_dir`.

- [ ] **Step 1: Confirm the modules are dead**

Run: `grep -rn "audio_analysis\|cin.depth\|cin import depth\|estimate_depth\|parallax\|kinetic_text" --include=*.py app main.py scripts src tests`
Expected: hits only inside the four modules themselves, `tests/test_cin_audio.py`, `tests/test_cin_depth.py`, the comment `app/config.py` (`cinematic_enabled ... depth parallax`), and unrelated words (`app/content_engine.py` prompt text "subtle parallax", `app/local_video_gen.py` docstring "parallax effects"). If anything else imports one of the four modules, stop and report it.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_asset_manager.py`:

```python


def test_local_images_are_written_into_the_job_folder_not_shared_temp(tmp_path, monkeypatch):
    """spec §4: intermediates live in the job folder. The real LocalImageGenerator needs torch,
    so a stand-in module replaces app.local_image_gen."""
    import sys
    import types
    from app.config import settings
    seen = {}

    class FakeLocalGen:
        def __init__(self, model_id=None):
            pass

        def generate_batch(self, prompts, width, height, output_dir):
            seen["dir"] = Path(output_dir)
            out = []
            for i, _ in enumerate(prompts):
                p = Path(output_dir) / f"scene_{i:03d}.png"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"png%d" % i)
                out.append(str(p))
            return out

        def unload(self):
            seen["unloaded"] = True

    shared = tmp_path / "shared_temp"
    monkeypatch.setitem(sys.modules, "app.local_image_gen", types.SimpleNamespace(LocalImageGenerator=FakeLocalGen))
    monkeypatch.setattr(settings, "image_provider", "local")
    monkeypatch.setattr(AssetManager, "TEMP_DIR", shared)
    images = tmp_path / "job" / "sources" / "images"
    paths = AssetManager().generate_images(["a", "b"], use_mock=False, output_dir=images)
    assert paths == [str(images / "scene00.png"), str(images / "scene01.png")]
    assert (images / "scene01.png").read_bytes() == b"png1"
    assert seen["dir"] == images and seen["unloaded"] is True
    assert not list(images.glob("scene_*.png"))                 # renamed in place, no leftovers
    assert not list(shared.glob("*.png"))                       # shared temp untouched
```

Append to `tests/test_encoding.py` (`Path`, `pytest`, `faststart_ok` are already imported there):

```python


def test_faststart_ok_reads_only_the_head(tmp_path, monkeypatch):
    import app.encoding as enc
    front = tmp_path / "front.mp4"
    front.write_bytes(b"\x00\x00\x00\x18ftyp" + b"moov" + b"\x00" * 64 + b"mdat" + b"\x00" * 64)
    back = tmp_path / "back.mp4"
    back.write_bytes(b"\x00\x00\x00\x18ftyp" + b"mdat" + b"\x00" * 64 + b"moov")
    late = tmp_path / "late.mp4"
    late.write_bytes(b"ftyp" + b"\x00" * (enc.FASTSTART_SCAN_BYTES + 16) + b"moov")

    def whole_file(self):
        raise AssertionError("faststart_ok must not read the whole file")

    monkeypatch.setattr(Path, "read_bytes", whole_file)
    assert faststart_ok(front) is True
    assert faststart_ok(back) is False
    assert faststart_ok(late) is False                          # moov beyond the scanned head


_GOOD_LOUDNORM = ('{\n "input_i" : "-20.10", "input_tp" : "-3.00", "input_lra" : "4.00",\n'
                  ' "input_thresh" : "-30.50", "output_i" : "-14.0", "target_offset" : "0.20"\n}')


def _stderr_run(stderr):
    import subprocess

    def run(cmd, timeout=600):
        return subprocess.CompletedProcess(cmd, 0, "", stderr)
    return run


def test_measure_loudness_parses_ffmpeg_json(monkeypatch):
    import app.encoding as enc
    monkeypatch.setattr(enc, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(enc, "_run", _stderr_run("[Parsed_loudnorm_0 @ 0x1]\n" + _GOOD_LOUDNORM))
    out = enc.measure_loudness("x.wav")
    assert out == {"input_i": -20.1, "input_tp": -3.0, "input_lra": 4.0, "input_thresh": -30.5,
                   "target_offset": 0.2}


@pytest.mark.parametrize("stderr", [
    '{ "input_i" : "-20.1", "input_tp" : -3.0 oops }',            # malformed JSON: used to raise
    _GOOD_LOUDNORM.replace('"-20.10"', '"nan"'),                    # NaN used to pass the < -70 check
    _GOOD_LOUDNORM.replace('"0.20"', '"inf"'),
    _GOOD_LOUDNORM.replace('"-20.10"', '"-inf"'),                  # silence
    _GOOD_LOUDNORM.replace('"-3.00"', 'null'),
])
def test_measure_loudness_rejects_unusable_output(monkeypatch, stderr):
    import app.encoding as enc
    monkeypatch.setattr(enc, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(enc, "_run", _stderr_run(stderr))
    assert enc.measure_loudness("x.wav") is None
```

Append to `tests/test_cli.py`:

```python


def test_main_module_has_no_unused_imports_or_dead_helpers():
    """Housekeeping guard (Phase D): every top-level import in main.py is referenced."""
    import ast
    from pathlib import Path
    import main
    tree = ast.parse(Path(main.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            imported |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {(a.asname or a.name).split(".")[0] for a in node.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert imported - used == set()
    assert not hasattr(main, "generate_output_filename")


def test_superseded_cinematic_modules_are_gone():
    import importlib.util
    for name in ("audio_analysis", "depth", "parallax", "kinetic_text"):
        assert importlib.util.find_spec(f"app.cin.{name}") is None, name
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_asset_manager.py tests/test_encoding.py tests/test_cli.py -q --tb=line -m "not render"`
Expected failures: `test_local_images_are_written_into_the_job_folder_not_shared_temp` (images generated in `shared_temp`), `test_faststart_ok_reads_only_the_head` (`AttributeError: ... FASTSTART_SCAN_BYTES`), four of the five `test_measure_loudness_rejects_unusable_output` cases (malformed raises `JSONDecodeError`; `nan`, `inf`, `null` return a dict), `test_main_module_has_no_unused_imports_or_dead_helpers` (`{'datetime', 'ScriptGeneratorError', 'AssetManagerError', 'VideoEditorError'}`), `test_superseded_cinematic_modules_are_gone`. Two new cases already pass (they pin existing behaviour): `test_measure_loudness_parses_ffmpeg_json` and the `-inf` silence case. The unused-import test reads the real `main.py`: if its set also contains a name Phase C introduced, that import is dead too — remove it in Step 6 and note it in the progress log.

- [ ] **Step 4: Local image provider writes into the job folder (`app/asset_manager.py`)**

1. Below `import os` add `import shutil` (`os` stays: `os.environ['FAL_KEY']` uses it).
2. In `_generate_images_local`, replace

```python
            paths = gen.generate_batch(enhanced, self.IMAGE_WIDTH, self.IMAGE_HEIGHT, str(self.TEMP_DIR))
            if output_dir is None:
                return paths
            moved = []
            for i, path in enumerate(paths):
                dest = self._image_path(i, output_dir)
                os.replace(path, dest)
                moved.append(str(dest))
            return moved
```

with

```python
            # Write straight into the job folder (spec §4: never a shared temp path), then rename
            # scene_000.png -> scene00.png in place. shutil.move also works across drives.
            target = Path(output_dir) if output_dir is not None else self.TEMP_DIR
            paths = gen.generate_batch(enhanced, self.IMAGE_WIDTH, self.IMAGE_HEIGHT, str(target))
            if output_dir is None:
                return paths
            moved = []
            for i, path in enumerate(paths):
                dest = self._image_path(i, output_dir)
                if Path(path).resolve() != dest.resolve():
                    shutil.move(str(path), str(dest))
                moved.append(str(dest))
            return moved
```

- [ ] **Step 5: `app/encoding.py`**

1. Below `import logging` add `import math`.
2. Directly above `_LOUDNORM_JSON = re.compile(...)` add:

```python
FASTSTART_SCAN_BYTES = 4 * 1024 * 1024   # moov must appear in the first 4 MiB
```

3. In `faststart_ok`, replace `    head = Path(video_path).read_bytes()[:4 * 1024 * 1024]` with

```python
    with open(video_path, "rb") as f:
        head = f.read(FASTSTART_SCAN_BYTES)
```

4. In `measure_loudness`, replace

```python
    raw = json.loads(m.group(0))
    try:
        out = {k: float(raw[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, ValueError):
        return None
    if out["input_i"] == float("-inf") or out["input_i"] < -70:
        return None
    return out
```

with

```python
    try:
        raw = json.loads(m.group(0))
        out = {k: float(raw[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
    except (KeyError, TypeError, ValueError) as e:     # JSONDecodeError is a ValueError
        logger.warning("loudnorm output unparseable (%s): %s", e, m.group(0)[:300])
        return None
    # -inf (silence) and nan (degenerate input) must never reach the second loudnorm pass
    if not all(math.isfinite(v) for v in out.values()) or out["input_i"] < -70:
        return None
    return out
```

- [ ] **Step 6: `main.py` dead helper and unused imports**

1. Delete the line `from datetime import datetime`.
2. Replace

```python
from app.content_engine import ScriptGenerator, ScriptGeneratorError, normalize_prompt_counts
from app.asset_manager import AssetManager, AssetManagerError
from app.video_editor import VideoEditor, VideoEditorError
```

with

```python
from app.content_engine import ScriptGenerator, normalize_prompt_counts
from app.asset_manager import AssetManager
from app.video_editor import VideoEditor
```

3. Delete the whole `def generate_output_filename(topic: str) -> str:` function (from its `def` line through `    return f"{safe_topic}_{timestamp}.mp4"`) and one of the two blank lines that followed it.

Run `grep -rn "generate_output_filename\|ScriptGeneratorError\|AssetManagerError\|VideoEditorError" main.py app/web app/scheduler.py app/generator_worker.py tests scripts` — expected: no `main.py` hits and no `from main import` of these names anywhere.

- [ ] **Step 7: Delete the dead modules and fix the stale comment**

```bash
git rm app/cin/audio_analysis.py app/cin/depth.py app/cin/parallax.py app/cin/kinetic_text.py tests/test_cin_audio.py tests/test_cin_depth.py
```

In `app/config.py`, replace

```python
    cinematic_enabled: bool = True          # Use cinematic engine (depth parallax, multi-shot, etc.)
```

with

```python
    cinematic_enabled: bool = True          # False = classic Ken Burns editor for every run (as --classic)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_asset_manager.py tests/test_encoding.py tests/test_cli.py tests/test_pipeline.py tests/test_cin_editor.py -q`
Expected: all pass (including the `render`-marked encode tests, which exercise the real ffmpeg loudnorm path).

- [ ] **Step 9: Commit**

```bash
git add app/asset_manager.py app/encoding.py main.py app/config.py tests/test_asset_manager.py tests/test_encoding.py tests/test_cli.py
git commit -m "chore: local images into job folder, bounded faststart read, robust loudnorm parse, remove dead code

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(The `git rm` in Step 7 already staged the deletions; they go into this commit.)

---

### Task 7: Docs, spec amendment, full verification

**Files:**
- Modify: `CLAUDE.md` (Commands block)
- Modify: `docs/superpowers/specs/2026-10-02-shot-based-editor-design.md` (§10 first bullet)
- Modify: `.claude/memory.md` (progress note)

**Interfaces:**
- Consumes: everything above. Produces: documentation only.

- [ ] **Step 1: `CLAUDE.md`**

1. Remove the stale Series example (the flags are parsed but `main()` never reads them):

```bash
# Series mode
python main.py --series "History of Money" --parts 3

```

2. Replace

```bash
python main.py --auto --classic              # old Ken Burns editor
```

with

```bash
python main.py --auto --classic              # old Ken Burns editor (also used for persona runs
                                             # and when the cinematic_enabled setting is off)
```

3. Replace

```bash
# Web UI
python main.py --serve
```

with

```bash
# Web UI. Generate form, Scheduler slots and Settings page carry pacing, music source and strict
# ("Default" = the Settings value; Settings persist in data/config.json and are re-applied at start).
# After a run the Generate page shows output/<job>/run_report.json warnings; the Library flags them.
python main.py --serve
```

Leave Phase C's `--music-source` / `--build-*-library` lines (after the `--rerender` example) as they are. Check: `grep -n "dashboard\|streamlit\|--series" CLAUDE.md` prints nothing.

- [ ] **Step 2: Spec §10 wording amendment (controller ruling)**

In `docs/superpowers/specs/2026-10-02-shot-based-editor-design.md`, replace

```markdown
- Renderer exceptions fail the run with the error (sources kept; fix and `--rerender`).
  The classic editor is reachable only with `--classic`.
```

with

```markdown
- Renderer exceptions fail the run with the error (sources kept; fix and `--rerender`); they never
  fall back to the classic editor. The classic editor is used only with `--classic`, for persona runs
  (talking-head hybrid), or when the `cinematic_enabled` setting is off (Settings page "Shot editor"
  toggle). *(Amended 2026-10-03, Phase D, controller ruling.)*
```

- [ ] **Step 3: `.claude/memory.md`**

Append after the "Shot editor Phase B" section (and after Phase C's note):

```markdown

## Shot editor Phase D - done (<date>)
- Options plumbing: app/run_options.py (pipeline_kwargs: missing/None/"" = Settings default; bool strings parsed;
  OptionError -> HTTP 422). Web /api/generate, scheduler slots, GeneratorWorker (SFX no longer forced off) all use it.
- Run report surfaced: app/cin/report.load_summary (never raises); WS complete/error carry {video_id, status, warnings};
  failed run_pipeline exceptions carry job_dir; report writes use save_quietly. Library shows warning badges.
- data/config.json is now applied at server start (apply_saved_settings skips bad values).
- Housekeeping: local images into job folder, faststart bounded read, loudnorm NaN/JSON guard, dead cin modules
  (audio_analysis, depth, parallax, kinetic_text) and main.generate_output_filename removed.
- Not verifiable locally (no fastapi/apscheduler): routes/scheduler only py_compiled; UI checked with node --check +
  a DOM smoke script. Live browser check pending on Docker/VPS.
```

- [ ] **Step 4: Full verification**

1. Run: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py --tb=no -rf`
   Expected: exactly the 12 baseline failures; passed = Phase D baseline (Task 1 Step 1) − 6 (deleted tests) + 55 (new tests in Tasks 1–6: 33 in test_run_options.py, 22 appended elsewhere). Any other failure is a regression: fix it before continuing.
2. Compile every touched Python file that tests cannot import:
   `for f in app/web/server.py app/web/ws.py app/web/routes/api_generate.py app/web/routes/api_config.py app/web/routes/api_scheduler.py app/scheduler.py; do .venv/Scripts/python.exe -m py_compile "$f" && echo "ok $f"; done` — six `ok` lines.
3. `for f in app/web/static/js/*.js; do node --check "$f" && echo "ok $f"; done` and `node <scratchpad>/ui_smoke.js .` — seven `ok` lines and `UI smoke OK`.
4. Offline end-to-end with the new payload code (zero API calls; uses the mocked pipeline from the tests):
   `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_pipeline.py::test_mock_run_end_to_end tests/test_pipeline.py::test_failed_run_exposes_job_dir_without_changing_exception_type -q` — both pass.
5. Spec coverage spot-check: `grep -n "pacing\|music_source\|strict" app/web/routes/api_generate.py app/web/routes/api_config.py app/web/static/js/generate.js app/web/static/js/settings.js app/web/static/js/scheduler.js` hits in every file; `grep -n "enable_sfx=False" app/generator_worker.py` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-10-02-shot-based-editor-design.md .claude/memory.md
git commit -m "docs: Phase D web options and run report; classic-editor wording amended in spec §10

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (done while writing)

**Spec coverage:**
- §13 D "options plumbing (web, CLI, scheduler)": CLI flags already exist (`--pacing`, `--strict` from Phase A; `--music-source` from Phase C). Web request model + form → Tasks 3, 4. Scheduler slot config → Tasks 3 (422 validation), 4 (modal), 5 (`_run_job`). Settings default → Tasks 3 (`GET`/`PUT /api/config`, startup apply), 4 (Settings page). Background worker → Task 5.
- §11 options table (`pacing` calm/standard/fast default standard; `music_source` mine/generated/any/none default any; `strict` bool default false) → Task 1 constants and tests, defaults stay in `Settings` (Phase A / Phase C).
- §10 "`/api/generate` returns the report's `warnings` with the result" → Task 2 (`load_summary`, `run_result`, `run_failure`, `job_dir`), Task 3 (WS payloads), Task 4 (Run Report panel). Library warnings (requested extra) → Tasks 3, 4.
- §11 housekeeping: `generator_worker.py` stops hard-coding `enable_sfx=False` → Task 5. `CLAUDE.md` stale `app/dashboard.py` → already fixed (recorded in decisions); new flags/options documented and stale Series example removed → Task 7. `extra="ignore"` and per-model clip pricing were done in Phase A.
- §10 amendment (classic editor also for persona runs and `cinematic_enabled` off) → Task 7 Step 2; the Settings toggle label now says so (Task 4) and the config comment (Task 6).
- Phase A deferred minors chosen for D → Task 2 (`report.save` masking) and Task 6 (local images, faststart, loudnorm, dead modules, `generate_output_filename` + unused imports).

**Placeholder scan:** every code step carries the code; `<scratchpad>` and `<date>` are runtime values the executor fills (session scratchpad path, today's date).

**Type consistency:** `pipeline_kwargs` keys match `run_pipeline` parameter names (`use_mock_images`, `enable_subtitles`, `enable_motion`, `enable_sfx`, `enable_music`, `subtitle_style`, `niche`, `video_style`, `video_duration`, `pacing`, `music_source`, `strict`); `run_result` / `run_failure` both return `video_id` + `load_summary` keys, which `generate.js` (`result.warnings`, `result.video_id`) and `library.js` (`video.warnings`) read; `send_error(job_id, error, result)` matches its one caller; `OptionError` is a `ValueError`, so existing `except ValueError` callers still catch it.

**Known limits (accepted):** route, WebSocket and scheduler code are verified by compilation and the pure-helper tests only; a live browser pass needs the Docker image or VPS (fastapi present there). The web form sends `strict` explicitly; if `/api/config` fails to load, the box starts unchecked and the run is not strict even when the Settings default is on (the form says what it will do). Scheduler run history does not show warnings; the Library does for every finished job.
