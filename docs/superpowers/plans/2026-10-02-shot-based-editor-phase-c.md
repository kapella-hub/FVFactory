# Shot-Based Editor — Phase C (Music/SFX Libraries, Ducking, Voice Polish) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every shot-editor video gets a least-recently-used music track from a per-mood library (user or ElevenLabs-generated), ducked under the voice from word timings, plus whoosh/impact/riser SFX placed from the shot plan, a polished voice, and a 48 kHz `mix.wav` that the existing Phase A loudnorm + mux delivers; two CLI builders fill the libraries via ElevenLabs.

**Architecture:** Pure cores, no I/O: `app/cin/music_library.py` (listing, LRU order), `app/cin/sfx_library.py` (`place_sfx(plan, pool)`), `app/cin/audio_dsp.py` (speech windows, duck curve, fades, equal-power loop). I/O edges: `app/cin/audio_io.py` (ffmpeg decode to NumPy, stdlib WAV write), `app/cin/mix.py::mix_tracks` (voice + music + SFX → `sources/mix.wav`), `app/cin/library_builder.py` (ElevenLabs HTTP, estimate, confirm). `render_job` fills `plan.music` / `plan.sfx` in memory and the callers save `shot_plan.json` after the render. The classic editor (`app/sfx.py`, `VideoEditor` music helpers) is untouched and keeps working under `--classic`.

**Tech Stack:** Python 3.14 venv (Docker 3.12), NumPy 2.3, ffmpeg/ffprobe 8 on PATH (imageio-ffmpeg fallback via `app.encoding.find_ffmpeg`), stdlib `wave`, `requests` 2.32, pydantic-settings 2.12, pytest 9. No SciPy or soundfile in the venv (checked); none added.

**Spec:** `docs/superpowers/specs/2026-10-02-shot-based-editor-design.md` (Phase C = §13 C; §8.1, §8.2, §8.3, §6.6 `sfx`/`music` keys, §9.3 `--music-source`, §11 `music_source` option)

**Written against the uncommitted working tree of 2026-10-03.** `app/cin/editor.py`, `app/cin/report.py`, `tests/test_cin_editor.py` and `tests/test_rerender.py` carry uncommitted Phase A review fixes (`_swap_final`, `platform_check_failed`, `rerender_job` saving the plan *after* `render_job`). Every step quotes text anchors; line numbers are hints only. A parallel Phase B (captions) plan also edits `render_job` (the `"render"` stage) and may edit `rebuild_plan`; this plan touches only `pick_music`, the `"mix"` stage, `RenderOptions.music_source`, `rebuild_plan`'s last line and `rerender_job`'s signature. Concrete overlaps with the Phase B plan (`docs/superpowers/plans/2026-10-02-shot-based-editor-phase-b.md`): (1) both replace `rebuild_plan`'s `return build_shot_plan(...)` line — the merged body must copy **both** `plan.hook_headline = old.hook_headline` and `plan.music = old.music` before `return plan`; (2) Phase B changes `ShotRenderer.render(out_path)` (drops `overlays`) — the stand-in renderers in this plan's tests already accept `render(self, out_path, overlays=None)`; (3) both add lines to `main.py` around `_run_shot_editor` (`plan.hook_headline` after `build_shot_plan`; this plan's second `plan.save` after `render_job`) — keep both. Phase B adds no warning codes, so `test_new_warning_codes_registered` is edited only here.

**Dry-run evidence (2026-10-03):** every step of Tasks 1–7 was applied mechanically (by text anchor) to a scratch copy of this tree under `%TEMP%`; the full suite there gave **12 failed (the baseline list) / 378 passed** (+64 new tests). The repo itself was not modified.

## Global Constraints

- Run everything with the venv: `.venv/Scripts/python.exe` (Git Bash). Test prefix: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider`.
- **Precondition before Task 1:** the pending Phase A review changes (`git status` shows `app/cin/editor.py`, `app/cin/report.py`, `app/library.py`, `app/motion_gen.py`, `app/web/routes/api_library.py`, `tests/test_cin_editor.py`, `tests/test_library.py`, `tests/test_motion_gen.py`, `tests/test_rerender.py` modified) must be committed (or stashed) first. This plan's anchors assume that fixed text, and Tasks 1 and 5 `git add` four of those files — committing them unreviewed would sweep the Phase A fixes into a Phase C commit.
- Full-suite command: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py --tb=no -rf`. **Baseline measured 2026-10-03 on this tree, with the uncommitted Phase A fixes applied: 12 failed, 314 passed (181 s)** — exactly Phase A's 12 out-of-scope failures: `test_local_image_gen.py::test_generate_creates_image`, `test_trend_scout.py::test_fetch_youtube_trending_with_api_key`, `test_trends.py::TestTrendScorer::{test_score_bounds,test_breakdown_keys,test_blocklist_blocks,test_recency_decay,test_niche_match_scoring}`, `test_trends.py::TestOrchestratorResilience::test_continues_on_source_failure`, and 4 in `test_uploader.py`. "Full suite green" means only these 12 fail.
- Never print, paste or commit `.env` values. Tests that build `Settings` pass `_env_file=None`; run failing-config steps with `--tb=no`. Builder output must never contain the API key (a test asserts it).
- Tests make **zero network calls**: every builder test injects a fake `post`; any test touching the builders also replaces `requests.post` with a function that raises. Never run a builder with `--yes` during verification.
- Code must run on Python 3.12: no PEP 695 syntax; `from __future__ import annotations` is fine. No new dependencies.
- ffmpeg is always located with `app.encoding.find_ffmpeg()` (PATH, then imageio-ffmpeg), never `shutil.which`.
- Music layout (spec §8.1, verbatim): `assets/music/<mood>/*.mp3|wav` (user tracks) and `assets/music/<mood>/generated/*`. Moods: chill, cinematic, dark, epic, upbeat.
- `music_source`: `mine` | `generated` | `any` (default) | `none`. Selection: least-recently-used track in the mood, tracked in `data/music_usage.json`. Empty pool for a non-`none` source: warning + `music_missing` in the run report.
- SFX (spec §8.2, verbatim): whoosh ×3, impact ×2, riser ×2 via ElevenLabs `POST /v1/sound-generation` into `assets/sfx/generated/`; user files in `assets/sfx/` are also used. Placement: whoosh 0.15 s before each scene boundary (not intra-scene cuts), impact at 0.0 s, riser ending at each styled transition. Variants rotate. Honour `enable_sfx`.
- Voice polish (spec §8.3, verbatim): ffmpeg `highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=10:release=150`.
- Ducking (spec §8.3, verbatim): music gain envelope from word timings: −22 dB under speech, −14 dB in gaps ≥ 0.5 s and over the final 1.0 s; 150 ms attack, 300 ms release; fade in 0.3 s, fade out 1.5 s.
- Looping: tracks shorter than the video loop with a 1.0 s equal-power crossfade. Mix voice + music + SFX to a 48 kHz WAV in the job folder (`sources/mix.wav`); the Phase A two-pass loudnorm (`app.encoding.LOUDNORM = "I=-14:TP=-1.5:LRA=11"`) + copy-mux then applies unchanged.
- ElevenLabs Music (verified 2026-10-03, https://elevenlabs.io/docs/api-reference/music/compose): `POST https://api.elevenlabs.io/v1/music`, query `output_format`, JSON body `prompt` (string), `music_length_ms` (3000–600000, prompt only), `model_id` (`music_v1` default, `music_v2`, `music_v2_5`), `force_instrumental` (bool, prompt only); response 200 = audio file bytes; 422 = `{"detail": [{loc, msg, type}]}`. API access requires a paid plan; commercial use needs Starter+ (https://elevenlabs.io/docs/overview/capabilities/music, https://elevenlabs.io/pricing/api).
- ElevenLabs Sound Effects (verified 2026-10-03, https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert): `POST https://api.elevenlabs.io/v1/sound-generation`, query `output_format`, JSON body `text` (required), `duration_seconds` (0.5–30, null = auto), `prompt_influence` (0–1, default 0.3), `loop` (bool, default false, v2 model only), `model_id` (`eleven_text_to_sound_v2`, the only value); response 200 = MP3 bytes.
- Both builders request `output_format=mp3_44100_128` (192 kbps MP3 is Creator-tier gated per the SFX docs). Auth header `xi-api-key` (same as `app/asset_manager.py` TTS).
- Prices (https://elevenlabs.io/pricing/api, 2026-10-03): Music $0.15/min, Sound Effects $0.12/min. 25 × 60 s tracks = **$3.75** (spec: ≈ $4). Builders print the estimate and ask for confirmation unless `--yes`; they skip files that already exist; 401/402/403 stop the build with a "check your key / permission / plan" message that includes the response `detail` text; they never crash the main pipeline (they are never imported by it).
- Commit only the files each task lists (the working tree has many unrelated untracked/modified files). End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not commit this plan file.

**Phase C decisions (read before starting):**
- **Level reference.** The spec gives −22/−14 dB without a reference. 0 dB = RMS of the *polished* voice over the speech windows. Music (after looping) and every SFX are RMS-normalized to that reference before their gain is applied, so user tracks mastered at −8 or −20 LUFS sit at the same depth. A silent or missing voice (RMS < −60 dBFS) uses a −20 dBFS reference.
- **Attack is look-ahead.** Word timings are known in advance, so the 150 ms attack ramp *finishes* at the speech onset; the 300 ms release *starts* at the speech end. The final 1.0 s is treated as a gap whose release ramp finishes exactly at `duration − 1.0`.
- **Mood `""`** (what `main.resolve_music_mood` returns when neither style nor niche matches) means the union of all five mood folders. Root-level files in `assets/music/` are not part of the spec layout and are ignored by the shot editor (the classic editor still uses them).
- **Music on/off precedence:** music plays only if `settings.music_enabled` and `options.enable_music` and `options.music_source != "none"`. `none` produces no `music_missing` warning.
- **Unusable tracks.** A candidate that ffmpeg cannot decode, or that is shorter than `MIN_TRACK_SECONDS = 3.0`, is skipped with a `music_track_skipped` warning and the next LRU candidate is tried; only an exhausted pool yields `music_missing`. Unreadable SFX files are skipped with `sfx_file_skipped`.
- **Library paths are asset paths, not job paths.** `shot_plan.json` stores them as given (cwd-relative posix, e.g. `assets/sfx/generated/impact_1.mp3`, as in spec §6.6; absolute posix if the setting is absolute). `JobPaths.resolve()` (`app/cin/job.py`, `def resolve`) joins every relative path onto the job root, so library paths must go through `music_library.asset_path()` / `asset_key()` only.
- **SFX kinds** come from the filename prefix (case-insensitive): `whoosh*`, `impact*`, `riser*` — this also picks up the legacy `SFXMixer.SFX_FILES` names (`whoosh.mp3`, `riser.mp3`, `impact.mp3`). At a styled transition both the whoosh (scene boundary) and the riser fire (spec literal). A riser longer than the time before its transition starts at 0.0 with an `offset` into the file so it still ends on the transition. SFX gains relative to the voice reference: whoosh −10 dB, impact −6 dB (spec §6.6 example), riser −12 dB.
- **Re-render and music.** `rebuild_plan` carries the old plan's `music` entry. Without `--music-source`, `render_job` reuses that file if it still exists and decodes (no LRU bump); with `--music-source` (or a missing file) it re-selects. SFX are always re-placed from the new plan.
- **Plan save timing.** `render_job` fills `plan.music` / `plan.sfx` in memory and never saves. `rerender_job` already saves after `render_job`; `_run_shot_editor` (`main.py`) keeps its pre-render save (so a failed render can be re-rendered) and adds a second save after `render_job`.
- **WAV format.** `mix.wav` is 48 kHz stereo `pcm_s16le`, written with stdlib `wave` at exactly `round(duration × 48000)` frames, with a −1 dBFS peak guard (uniform scale-down; loudnorm restores level). Phase A's `_fit_duration` and its MoviePy mix are removed.
- **Builders** run in `main()` before `validate_config()` (like `--rerender`): they need only `ELEVENLABS_API_KEY`. Music model default `music_v1` (the documented API default during the v2 transition), configurable via `ELEVENLABS_MUSIC_MODEL`. Tracks are named `<mood>_NN.mp3`, SFX `whoosh_1.mp3` … `riser_2.mp3`; downloads are written to `*.part` and renamed, so a killed build never leaves a half file that the library would pick up.
- **Out of scope:** captions/fonts/hook headline (Phase B); web form, scheduler slot config, `generator_worker.py`, `/api/generate` warnings (Phase D — this plan adds `music_source` to `RenderOptions`, `run_pipeline`, the CLI and `Settings` only); cost-tracker entries for library builds (one-off spend, printed by the builder).

## Review Focus

1. **A user track shorter than 1 s (or a 2 s jingle) in `assets/music/epic/`:** it must be skipped with `music_track_skipped` and the next LRU track used; a looped sub-second track must never be the bed — pinned in Task 5 (`test_pick_music_skips_short_and_corrupt_tracks`) and Task 3 (`test_loop_very_short_track_does_not_crash`).
2. **A corrupt or renamed non-audio `.mp3` in the music or SFX library** (interrupted download, `notes.mp3`): skipped with a warning, render completes; an all-bad pool yields `music_missing` — pinned in Task 5 (`test_pick_music_skips_short_and_corrupt_tracks`, `test_render_job_survives_corrupt_music_and_sfx`) and Task 4 (`test_corrupt_music_reports_error_and_still_mixes_voice`).
3. **`data/music_usage.json` corrupt, missing its folder, or two jobs selecting at once** (web UI threads, scheduler): a corrupt file is logged and rewritten, never raised; concurrent selections in one process get distinct tracks — pinned in Task 1 (`test_corrupt_usage_file_is_ignored_and_rewritten`, `test_usage_folder_is_created`, `test_concurrent_selection_picks_distinct_tracks`).
4. **Narration with no gaps ≥ 0.5 s** (fast talker; alignment fallback with contiguous tokens): music stays at −22 dB from the start until it rises to −14 dB exactly at `duration − 1.0`, with no pumping — pinned in Task 3 (`test_no_gaps_ducks_everything_but_the_tail`) and Task 4 (`test_continuous_speech_keeps_music_at_minus_22`).
5. **An SFX file longer than the video** (a user's 20 s riser on an 8 s video) or longer than the time before the first transition: truncated at the video end, offset into the file before 0.0, mix length still exactly the plan duration — pinned in Task 2 (`test_riser_before_zero_gets_offset`) and Task 4 (`test_sfx_longer_than_video_is_truncated`).

## File Map

| File | Status | Responsibility |
|---|---|---|
| `app/config.py` | modify | `music_source`, `elevenlabs_music_model`, music/SFX price settings |
| `app/cin/report.py` | modify | register `music_track_skipped`, `sfx_file_skipped` |
| `app/cin/music_library.py` | create | `list_tracks`, `lru_order`, `UsageStore`, `select_track`, `asset_path/asset_key` |
| `app/cin/sfx_library.py` | create | `scan_sfx`, `SfxFile`, `place_sfx` (pure) |
| `app/cin/audio_dsp.py` | create | `speech_windows`, `duck_curve_db`, `fade_gain`, `music_gain`, `loop_to_length`, `rms_db` (pure NumPy) |
| `app/cin/audio_io.py` | create | `decode_audio` (ffmpeg → float32), `write_wav` (stdlib, s16), `VOICE_POLISH` |
| `app/cin/mix.py` | rewrite | `mix_tracks` (Task 4); old `mix_audio`/`_fit_duration` removed (Task 5) |
| `app/cin/editor.py` | modify | `RenderOptions.music_source`, `pick_music`, `sfx_pool`, mix stage, `rebuild_plan`, `rerender_job(music_source=)` |
| `app/cin/library_builder.py` | create | ElevenLabs music/SFX builders: plan items, estimate, confirm, fetch |
| `main.py` | modify | `run_pipeline(music_source=)`, post-render plan save, classic `none`, `--music-source`, builder flags |
| `tests/conftest.py` | modify | autouse isolation of `data/music_usage.json`; `make_tone_wav` helper |
| `tests/test_music_library.py`, `test_sfx_library.py`, `test_audio_dsp.py`, `test_cin_mix.py`, `test_library_builder.py` | create | unit + mix tests |
| `tests/test_cin_editor.py`, `test_rerender.py`, `test_pipeline.py`, `test_cli.py` | modify | wiring tests; update the exact-kwargs rerender CLI test |
| `CLAUDE.md`, `.claude/memory.md` | modify | new flags; progress note |

## Task Order and Dependencies

1 → 5. 2 → 5. 3 → 4 → 5. 6 is independent of 2–5 (needs 1 for settings and `music_library` constants). 7 needs 5 and 6. Tasks 2, 3 and 6 can run in parallel after Task 1.

---

### Task 1: Settings, options, warning codes and the music library (LRU)

**Files:**
- Modify: `app/config.py` (after the `strict: bool = False` line in the "Shot-based editor" block)
- Modify: `app/cin/report.py` (`WARNING_CODES`)
- Modify: `app/cin/editor.py` (`RenderOptions`)
- Create: `app/cin/music_library.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_music_library.py`

**Interfaces:**
- Consumes: `app.config.settings.data_dir` (existing, `"data"`), `settings.music_dir` (existing, `"assets/music"`).
- Produces:
  - `MOODS: tuple`, `MUSIC_SOURCES = ("mine", "generated", "any", "none")`, `MUSIC_EXTENSIONS: tuple`, `GENERATED_DIR = "generated"`
  - `asset_path(p) -> Path`, `asset_key(path) -> str`, `default_usage_path() -> Path`
  - `list_tracks(music_dir, mood: str, source: str) -> list[Path]` (raises `ValueError` on unknown source)
  - `lru_order(candidates, usage: dict) -> list[Path]`
  - `class UsageStore(path=None)` with `.path`, `.lock`, `.load() -> dict`, `.save(tracks: dict) -> None`
  - `select_track(candidates, store: UsageStore, *, accept=None, now=None) -> Optional[Path]`
  - `RenderOptions.music_source: str = "any"`; `Settings.music_source`, `Settings.elevenlabs_music_model`, `Settings.cost_elevenlabs_music_per_minute`, `Settings.cost_elevenlabs_sfx_per_minute`
  - Warning codes `music_track_skipped`, `sfx_file_skipped`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_music_library.py`:

```python
"""Music library listing and least-recently-used selection (spec §8.1)."""
import json
import threading
from pathlib import Path

import pytest

from app.cin.music_library import (UsageStore, list_tracks, lru_order, select_track)


def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def test_list_tracks_by_source(tmp_path):
    a = touch(tmp_path / "epic" / "a.mp3")
    g = touch(tmp_path / "epic" / "generated" / "epic_01.mp3")
    touch(tmp_path / "epic" / "notes.txt")
    touch(tmp_path / "epic" / "generated" / "epic_02.mp3.part")      # interrupted download
    d = touch(tmp_path / "dark" / "d.wav")
    assert list_tracks(tmp_path, "epic", "mine") == [a]
    assert list_tracks(tmp_path, "epic", "generated") == [g]
    assert list_tracks(tmp_path, "epic", "any") == [a, g]
    assert list_tracks(tmp_path, "epic", "none") == []
    assert set(list_tracks(tmp_path, "", "any")) == {a, g, d}      # mood "" = every mood
    assert list_tracks(tmp_path / "missing", "epic", "any") == []


def test_unknown_source_rejected(tmp_path):
    with pytest.raises(ValueError):
        list_tracks(tmp_path, "epic", "spotify")


def test_lru_order_never_used_first_then_oldest():
    a, b, c = Path("m/a.mp3"), Path("m/b.mp3"), Path("m/c.mp3")
    assert lru_order([c, b, a], {}) == [a, b, c]
    usage = {"m/a.mp3": {"last_used": 50.0}, "m/b.mp3": {"last_used": 10.0}}
    assert lru_order([a, b, c], usage) == [c, b, a]
    assert lru_order([a, b], {"m/a.mp3": {"last_used": "garbage"}}) == [a, b]


def test_select_track_rotates_and_records(tmp_path):
    a, b = Path("m/a.mp3"), Path("m/b.mp3")
    store = UsageStore(tmp_path / "u.json")
    assert [select_track([a, b], store, now=t) for t in (1.0, 2.0, 3.0)] == [a, b, a]
    tracks = json.loads((tmp_path / "u.json").read_text(encoding="utf-8"))["tracks"]
    assert tracks["m/a.mp3"] == {"last_used": 3.0, "count": 2}
    assert select_track([], store) is None


def test_select_track_skips_rejected_candidates(tmp_path):
    a, b = Path("m/a.mp3"), Path("m/b.mp3")
    store = UsageStore(tmp_path / "u.json")
    assert select_track([a, b], store, accept=lambda p: p != a, now=1.0) == b
    assert "m/a.mp3" not in store.load()
    assert select_track([a], store, accept=lambda p: False) is None


def test_corrupt_usage_file_is_ignored_and_rewritten(tmp_path):
    usage = tmp_path / "music_usage.json"
    a = Path("m/a.mp3")
    for junk in ("{not json", "[1, 2]", '{"tracks": "nope"}'):
        usage.write_text(junk, encoding="utf-8")
        store = UsageStore(usage)
        assert store.load() == {}
        assert select_track([a], store, now=7.0) == a
        assert json.loads(usage.read_text(encoding="utf-8"))["tracks"]["m/a.mp3"]["count"] == 1


def test_usage_folder_is_created(tmp_path):
    usage = tmp_path / "data" / "nested" / "music_usage.json"
    assert select_track([Path("m/a.mp3")], UsageStore(usage), now=1.0) is not None
    assert usage.exists()


def test_concurrent_selection_picks_distinct_tracks(tmp_path):
    tracks = [Path(f"m/{i}.mp3") for i in range(4)]
    path = tmp_path / "u.json"
    got, barrier = [], threading.Barrier(4)

    def job():
        barrier.wait()
        got.append(select_track(tracks, UsageStore(path)))

    threads = [threading.Thread(target=job) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(got) == sorted(tracks)


def test_default_usage_path_is_isolated_in_tests(tmp_path):
    from app.cin import music_library
    assert "music_usage.json" in str(music_library.default_usage_path())
    assert Path(music_library.default_usage_path()).parent.name == "data"
    assert Path("data/music_usage.json").resolve() != Path(music_library.default_usage_path()).resolve()


def test_settings_music_source_default_and_validation():
    from pydantic import ValidationError
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.music_source == "any" and s.elevenlabs_music_model == "music_v1"
    assert s.cost_elevenlabs_music_per_minute == 0.15 and s.cost_elevenlabs_sfx_per_minute == 0.12
    with pytest.raises(ValidationError):
        Settings(_env_file=None, music_source="spotify")


def test_render_options_music_source_roundtrip():
    from app.cin.editor import RenderOptions
    assert RenderOptions().music_source == "any"
    opts = RenderOptions(music_source="generated")
    assert RenderOptions.from_json(opts.to_json()).music_source == "generated"


def test_phase_c_warning_codes_registered():
    from app.cin.report import WARNING_CODES
    assert {"music_missing", "sfx_missing", "music_track_skipped", "sfx_file_skipped"} <= set(WARNING_CODES)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_music_library.py -q --tb=no`
Expected: collection error `ModuleNotFoundError: No module named 'app.cin.music_library'`.

- [ ] **Step 3: Settings, codes, RenderOptions**

In `app/config.py`, directly after the line `    strict: bool = False                    # True: fail the run instead of shipping a still shot` add:

```python
    music_source: Literal["mine", "generated", "any", "none"] = "any"   # spec §8.1

    # ElevenLabs music / SFX library builders (spec §8.1-8.2). Prices: https://elevenlabs.io/pricing/api
    elevenlabs_music_model: str = "music_v1"        # API default; "music_v2" / "music_v2_5" also accepted
    cost_elevenlabs_music_per_minute: float = 0.15
    cost_elevenlabs_sfx_per_minute: float = 0.12
```

In `app/cin/report.py`, extend the tuple: replace `    "platform_check_failed", "final_swap_failed",` with

```python
    "platform_check_failed", "final_swap_failed", "music_track_skipped", "sfx_file_skipped",
```

In `app/cin/editor.py`, in `class RenderOptions`, replace `    music_mood: str = ""` with

```python
    music_mood: str = ""
    music_source: str = "any"          # mine | generated | any | none (spec §8.1)
```

- [ ] **Step 4: Create `app/cin/music_library.py`**

```python
"""Music library (spec §8.1): user tracks in assets/music/<mood>/, generated tracks in
assets/music/<mood>/generated/, least-recently-used selection tracked in data/music_usage.json.

Library paths are cwd-relative (or absolute) asset paths such as "assets/music/epic/a.mp3".
They are NOT job-relative: never pass them through JobPaths.rel()/resolve()."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

MOODS = ("chill", "cinematic", "dark", "epic", "upbeat")
MUSIC_SOURCES = ("mine", "generated", "any", "none")
MUSIC_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
GENERATED_DIR = "generated"
USAGE_FILE = "music_usage.json"

_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def asset_path(p) -> Path:
    """Inverse of asset_key(): a cwd-relative or absolute library path."""
    return Path(p)


def asset_key(path) -> str:
    """Posix string stored in shot_plan.json and music_usage.json."""
    return Path(path).as_posix()


def default_usage_path() -> Path:
    from app.config import settings
    return Path(settings.data_dir) / USAGE_FILE


def _audio_files(folder: Path) -> list:
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in MUSIC_EXTENSIONS and not p.name.startswith(".")]


def list_tracks(music_dir, mood: str, source: str) -> list:
    """Candidate tracks for a mood and music_source. mood "" (no niche/style match) = every mood."""
    if source not in MUSIC_SOURCES:
        raise ValueError(f"Unknown music_source {source!r}; choose one of {MUSIC_SOURCES}")
    if source == "none":
        return []
    root = Path(music_dir)
    out = []
    for m in ([mood] if mood else list(MOODS)):
        if source in ("mine", "any"):
            out += _audio_files(root / m)
        if source in ("generated", "any"):
            out += _audio_files(root / m / GENERATED_DIR)
    return sorted(out, key=asset_key)


def lru_order(candidates: Iterable, usage: dict) -> list:
    """Never-used tracks first, then oldest last_used; ties broken by path (deterministic)."""
    def key(p):
        rec = usage.get(asset_key(p)) or {}
        last = rec.get("last_used", 0.0)
        return (last if isinstance(last, (int, float)) else 0.0, asset_key(p))
    return sorted(candidates, key=key)


class UsageStore:
    """data/music_usage.json: {"version": 1, "tracks": {key: {"last_used": epoch_s, "count": n}}}.
    A missing or corrupt file reads as empty (logged, never raised). Writes are atomic; one lock per
    file serialises select-and-record inside this process."""

    def __init__(self, path=None):
        self.path = Path(path) if path else default_usage_path()
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(str(self.path.resolve()), threading.Lock())

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as e:
            logger.warning("Ignoring unreadable %s (%s); LRU history restarts", self.path, e)
            return {}
        tracks = data.get("tracks") if isinstance(data, dict) else None
        if not isinstance(tracks, dict):
            logger.warning("Ignoring malformed %s; LRU history restarts", self.path)
            return {}
        return {k: v for k, v in tracks.items() if isinstance(v, dict)}

    def save(self, tracks: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"version": 1, "tracks": tracks}, indent=1), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:                 # Windows: another process has it open
                time.sleep(0.05 * (attempt + 1))
        tmp.unlink(missing_ok=True)
        logger.warning("Could not update %s (file locked); selection not recorded", self.path)


def select_track(candidates: Iterable, store: UsageStore, *, accept: Optional[Callable] = None,
                 now: Optional[float] = None) -> Optional[Path]:
    """Least-recently-used candidate that `accept(path)` approves; records its use.
    Select-and-record is atomic per usage file within this process (accept runs under the lock)."""
    candidates = list(candidates)
    if not candidates:
        return None
    with store.lock:
        usage = store.load()
        for path in lru_order(candidates, usage):
            if accept is not None and not accept(path):
                continue
            rec = usage.get(asset_key(path)) or {}
            count = rec.get("count", 0)
            usage[asset_key(path)] = {"last_used": time.time() if now is None else now,
                                      "count": (count if isinstance(count, int) else 0) + 1}
            store.save(usage)
            return Path(path)
    return None
```

- [ ] **Step 5: Isolate the usage file in every test**

In `tests/conftest.py`, after the `gold` fixture, add:

```python
@pytest.fixture(autouse=True)
def _isolated_music_usage(tmp_path, monkeypatch):
    """No test may write the real data/music_usage.json."""
    monkeypatch.setattr("app.cin.music_library.default_usage_path",
                        lambda: tmp_path / "data" / "music_usage.json")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_music_library.py tests/test_config.py tests/test_cin_editor.py -q -m "not render"`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/config.py app/cin/report.py app/cin/editor.py app/cin/music_library.py tests/conftest.py tests/test_music_library.py
git commit -m "feat: music library listing and LRU selection; music_source setting and option

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: SFX library scan and placement from the shot plan

**Files:**
- Create: `app/cin/sfx_library.py`
- Test: `tests/test_sfx_library.py`

**Interfaces:**
- Consumes: `app.cin.music_library.asset_key`; `ShotPlan` (`.duration`, `.scenes[i].t0`, `.shots[i].t0`, `.shots[i].transition_in`) from `app/cin/shot_plan.py`.
- Produces:
  - `SFX_KINDS = ("whoosh", "impact", "riser")`, `SFX_GAIN_DB = {"whoosh": -10.0, "impact": -6.0, "riser": -12.0}`, `WHOOSH_LEAD = 0.15`
  - `@dataclass(frozen=True) class SfxFile: path: Path; kind: str; duration: float`
  - `sfx_kind(path) -> Optional[str]`
  - `scan_sfx(sfx_dir) -> dict[str, list[Path]]` (keys: all three kinds)
  - `place_sfx(plan, pool: dict[str, list[SfxFile]]) -> list[dict]` — entries `{"t", "kind", "file", "gain_db"}` plus `"offset"` only when > 0, sorted by `t`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sfx_library.py`:

```python
"""SFX classification and placement from the shot plan (spec §8.2)."""
from pathlib import Path

from app.cin.sfx_library import SfxFile, place_sfx, scan_sfx, sfx_kind
from app.cin.shot_plan import ClipSpec, Scene, Shot, ShotPlan, ShotSource, build_shot_plan, plan_segments
from tests.conftest import fixture_alignment


def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def sf(name, kind, dur):
    return SfxFile(Path(f"assets/sfx/generated/{name}"), kind, dur)


POOL = {"whoosh": [sf("whoosh_1.mp3", "whoosh", 1.0), sf("whoosh_2.mp3", "whoosh", 1.0)],
        "impact": [sf("impact_1.mp3", "impact", 1.5)],
        "riser": [sf("riser_1.mp3", "riser", 2.5)]}


def plan3(duration=8.0):
    """3 scenes; scene 1 has an intra-scene cut at 3.5; styled transitions at 2.0 and 5.0."""
    scenes = [Scene(0, 0.0, 2.0, "a"), Scene(1, 2.0, 5.0, "b"), Scene(2, 5.0, duration, "c")]
    src = ShotSource("still", "sources/images/scene00.png")
    shots = [Shot(0, 0, 0.0, 2.0, src), Shot(1, 1, 2.0, 3.5, src, transition_in="flash"),
             Shot(2, 1, 3.5, 5.0, src), Shot(3, 2, 5.0, duration, src, transition_in="whip_pan")]
    return ShotPlan(duration, 30, "standard", {}, scenes, shots, [])


def test_sfx_kind_by_prefix():
    assert sfx_kind("whoosh.mp3") == "whoosh"          # legacy SFXMixer name
    assert sfx_kind("Impact Big.WAV") == "impact"
    assert sfx_kind("riser_2.mp3") == "riser"
    assert sfx_kind("music.mp3") is None


def test_scan_user_and_generated(tmp_path):
    w = touch(tmp_path / "whoosh.mp3")
    g = touch(tmp_path / "generated" / "whoosh_1.mp3")
    i = touch(tmp_path / "Impact Big.WAV")
    touch(tmp_path / "music.mp3")
    touch(tmp_path / "generated" / "riser_1.mp3.part")
    pool = scan_sfx(tmp_path)
    assert pool["whoosh"] == sorted([w, g], key=lambda p: p.as_posix())
    assert pool["impact"] == [i] and pool["riser"] == []
    assert scan_sfx(tmp_path / "missing") == {"whoosh": [], "impact": [], "riser": []}


def test_place_sfx_rules():
    ev = place_sfx(plan3(), POOL)
    assert [(e["t"], e["kind"], e["file"]) for e in ev] == [
        (0.0, "impact", "assets/sfx/generated/impact_1.mp3"),
        (0.0, "riser", "assets/sfx/generated/riser_1.mp3"),     # 2.5 s riser ending at 2.0
        (1.85, "whoosh", "assets/sfx/generated/whoosh_1.mp3"),  # 0.15 s before scene 1
        (2.5, "riser", "assets/sfx/generated/riser_1.mp3"),     # ends at the 5.0 transition
        (4.85, "whoosh", "assets/sfx/generated/whoosh_2.mp3"),  # variants rotate
    ]
    assert {e["kind"]: e["gain_db"] for e in ev} == {"impact": -6.0, "riser": -12.0, "whoosh": -10.0}


def test_riser_before_zero_gets_offset():
    ev = [e for e in place_sfx(plan3(), POOL) if e["kind"] == "riser"]
    assert ev[0]["t"] == 0.0 and ev[0]["offset"] == 0.5
    assert "offset" not in ev[1]


def test_intra_scene_cuts_get_no_whoosh():
    ev = place_sfx(plan3(), POOL)
    assert sorted(e["t"] for e in ev if e["kind"] == "whoosh") == [1.85, 4.85]   # not 3.35


def test_missing_kinds_and_empty_pool():
    assert place_sfx(plan3(), {}) == []
    only_whoosh = place_sfx(plan3(), {"whoosh": POOL["whoosh"]})
    assert {e["kind"] for e in only_whoosh} == {"whoosh"}


def test_events_at_or_after_duration_are_dropped():
    plan = plan3(duration=5.0)
    plan.scenes[2] = Scene(2, 5.0, 5.0, "c")
    plan.shots[3] = Shot(3, 2, 5.0, 5.0, plan.shots[3].source, transition_in="whip_pan")
    assert all(e["t"] < 5.0 for e in place_sfx(plan, POOL))


def test_gold_plan_whoosh_per_scene_boundary():
    alignment = fixture_alignment("words_gold_8s.json")
    specs = [ClipSpec(s.scene, s.index, s.t0, s.t1, s.requested_len, f"sources/images/scene{s.scene:02d}.png")
             for s in plan_segments(alignment, None)]
    plan = build_shot_plan(alignment, "fast", specs)
    ev = place_sfx(plan, POOL)
    assert sum(e["kind"] == "whoosh" for e in ev) == len(plan.scenes) - 1
    assert sum(e["kind"] == "riser" for e in ev) == sum(s.transition_in != "cut" for s in plan.shots)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_sfx_library.py -q --tb=no`
Expected: `ModuleNotFoundError: No module named 'app.cin.sfx_library'`.

- [ ] **Step 3: Create `app/cin/sfx_library.py`**

```python
"""SFX library and placement (spec §8.2). User files in assets/sfx/ and generated files in
assets/sfx/generated/ are classified by filename prefix: whoosh*, impact*, riser*.
place_sfx is pure: (ShotPlan, pool) -> shot_plan.json "sfx" entries (spec §6.6)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.cin.music_library import asset_key

SFX_KINDS = ("whoosh", "impact", "riser")
SFX_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac")
SFX_GAIN_DB = {"whoosh": -10.0, "impact": -6.0, "riser": -12.0}   # relative to the voice reference
WHOOSH_LEAD = 0.15
GENERATED_DIR = "generated"


@dataclass(frozen=True)
class SfxFile:
    path: Path
    kind: str
    duration: float


def sfx_kind(path) -> Optional[str]:
    stem = Path(path).stem.lower()
    return next((k for k in SFX_KINDS if stem.startswith(k)), None)


def scan_sfx(sfx_dir) -> dict:
    """{kind: [Path, ...]} from sfx_dir/ (user) and sfx_dir/generated/, sorted by path."""
    root = Path(sfx_dir)
    pool = {k: [] for k in SFX_KINDS}
    for folder in (root, root / GENERATED_DIR):
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            kind = sfx_kind(p)
            if p.is_file() and kind and p.suffix.lower() in SFX_EXTENSIONS:
                pool[kind].append(p)
    return {k: sorted(v, key=asset_key) for k, v in pool.items()}


def place_sfx(plan, pool: dict) -> list:
    """Impact at 0.0; whoosh WHOOSH_LEAD s before every scene boundary (never intra-scene cuts);
    a riser ending at every styled transition (offset into the file when it would start before 0).
    Variants of each kind rotate. pool: {kind: [SfxFile, ...]}."""
    events, used = [], {k: 0 for k in SFX_KINDS}

    def take(kind):
        files = pool.get(kind) or []
        if not files:
            return None
        f = files[used[kind] % len(files)]
        used[kind] += 1
        return f

    def add(f, t, offset=0.0):
        if t >= plan.duration:
            return
        ev = {"t": round(max(0.0, t), 3), "kind": f.kind, "file": asset_key(f.path),
              "gain_db": SFX_GAIN_DB[f.kind]}
        if offset > 0:
            ev["offset"] = round(offset, 3)
        events.append(ev)

    f = take("impact")
    if f:
        add(f, 0.0)
    for sc in plan.scenes[1:]:
        f = take("whoosh")
        if f:
            add(f, sc.t0 - WHOOSH_LEAD)
    for shot in plan.shots:
        if shot.transition_in == "cut" or shot.t0 <= 0:
            continue
        f = take("riser")
        if f:
            start = shot.t0 - f.duration
            add(f, start, offset=max(0.0, -start))
    return sorted(events, key=lambda e: (e["t"], e["kind"]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_sfx_library.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add app/cin/sfx_library.py tests/test_sfx_library.py
git commit -m "feat: SFX library scan and shot-plan placement (whoosh/impact/riser, rotating variants)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Pure DSP — speech windows, duck curve, fades, equal-power loop

**Files:**
- Create: `app/cin/audio_dsp.py`
- Test: `tests/test_audio_dsp.py`

**Interfaces:**
- Consumes: nothing (NumPy only).
- Produces (all pure):
  - constants `SR = 48000`, `SPEECH_DB = -22.0`, `GAP_DB = -14.0`, `MIN_GAP = 0.5`, `TAIL = 1.0`, `ATTACK = 0.150`, `RELEASE = 0.300`, `FADE_IN = 0.3`, `FADE_OUT = 1.5`, `LOOP_XFADE = 1.0`, `CONTROL_RATE = 1000`
  - `db_to_gain(db) -> ndarray|float`, `rms_db(x) -> float` (`-inf` for empty/silent)
  - `speech_windows(tokens: iterable[(t0, t1)], duration: float, min_gap=MIN_GAP) -> list[[a, b]]`
  - `duck_curve_db(windows, duration, rate=CONTROL_RATE) -> ndarray` (dB at 1 kHz)
  - `fade_gain(n, sr=SR, fade_in=FADE_IN, fade_out=FADE_OUT) -> ndarray`
  - `music_gain(windows, duration, sr=SR) -> ndarray` (linear, length `round(duration*sr)`)
  - `loop_to_length(x: ndarray(frames, ch), n: int, sr=SR, xfade=LOOP_XFADE) -> ndarray(n, ch) float32`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audio_dsp.py`:

```python
"""Ducking envelope and looping (spec §8.3) — pure NumPy, no media."""
import numpy as np
import pytest

from app.cin.audio_dsp import (CONTROL_RATE, SR, duck_curve_db, fade_gain, loop_to_length, music_gain,
                               rms_db, speech_windows)

WINDOWS = [[0.2, 2.0], [3.0, 5.0], [5.8, 7.2]]


def at(curve, t):
    return curve[int(round(t * CONTROL_RATE))]


def test_speech_windows_merge_short_gaps_keep_long_ones():
    toks = [(0.2, 0.5), (0.6, 1.0), (1.2, 2.0),      # gaps 0.1, 0.2 -> one window
            (3.0, 3.4), (3.9, 5.0),                   # gap 0.5 exactly -> kept apart
            (7.0, 7.0), (8.5, 9.5)]                   # zero-length dropped; clipped to duration
    assert speech_windows(toks, 9.0) == [[0.2, 2.0], [3.0, 3.4], [3.9, 5.0], [8.5, 9.0]]
    assert speech_windows([], 5.0) == []


def test_duck_curve_levels():
    c = duck_curve_db(WINDOWS, 8.0)
    assert at(c, 0.0) == -14                 # 0.2 s of lead-in is not ducked yet ...
    assert at(c, 0.2) == -22                 # ... but the attack finishes at the onset
    assert at(c, 1.0) == -22
    assert -22 < at(c, 2.15) < -14           # releasing over 300 ms
    assert at(c, 2.31) == -14 and at(c, 2.5) == -14
    assert at(c, 2.80) == -14 and at(c, 3.0) == -22     # attack starts 150 ms before speech
    assert at(c, 7.5) == -14


def test_attack_and_release_slopes():
    c = duck_curve_db([[1.0, 2.0]], 5.0)
    assert at(c, 0.84) == -14 and at(c, 0.925) == pytest.approx(-18.0, abs=0.1)
    assert at(c, 2.15) == pytest.approx(-18.0, abs=0.1) and at(c, 2.3) == -14


def test_no_gaps_ducks_everything_but_the_tail():
    toks = [(i * 0.3, i * 0.3 + 0.29) for i in range(30)]       # continuous speech to 9.0 s
    w = speech_windows(toks, 9.0)
    assert w == [[0.0, 8.99]]
    c = duck_curve_db(w, 9.0)
    assert at(c, 0.0) == -22 and at(c, 4.0) == -22 and at(c, 7.69) == -22
    assert at(c, 8.0) == -14 and at(c, 8.99) == -14              # -14 reached exactly at D - 1.0
    assert np.all(np.diff(c[: int(7.7 * CONTROL_RATE)]) == 0)    # no pumping


def test_no_speech_is_all_gap_level():
    c = duck_curve_db([], 3.0)
    assert np.all(c == -14)


def test_fades_and_music_gain_length():
    g = fade_gain(SR * 4)
    assert g[0] == 0.0 and g[int(0.3 * SR)] == 1.0 and g[-1] == 0.0
    assert g[int(2.5 * SR)] == 1.0 and 0.0 < g[int(3.5 * SR)] < 1.0
    mg = music_gain(WINDOWS, 8.0)
    assert len(mg) == 8 * SR
    assert 20 * np.log10(mg[int(1.0 * SR)]) == pytest.approx(-22.0, abs=0.01)
    assert 20 * np.log10(mg[int(2.5 * SR)]) == pytest.approx(-14.0, abs=0.01)
    assert len(music_gain([], 0.01)) == 480


def test_loop_exact_length_and_starts_with_original():
    x = np.arange(SR * 3, dtype=np.float32).reshape(-1, 1) / (SR * 3)
    y = loop_to_length(x, SR * 10)
    assert y.shape == (SR * 10, 1) and y.dtype == np.float32
    assert np.array_equal(y[: SR * 2], x[: SR * 2])             # untouched before the first crossfade


def test_loop_crossfade_is_equal_power_on_uncorrelated_audio():
    """Noise, not a tone: equal-power fades keep power constant only for uncorrelated content
    (an in-phase sine would bump by up to +3 dB in the overlap, which is expected)."""
    rng = np.random.default_rng(1)
    x = (rng.standard_normal((3 * SR, 2)) * 0.1).astype(np.float32)
    y = loop_to_length(x, 10 * SR)
    body = rms_db(y[int(0.5 * SR):int(1.5 * SR)])
    for centre in (2.5, 4.5, 6.5, 8.5):                          # copy k starts at 2k s, overlaps 1 s
        seg = y[int((centre - 0.3) * SR):int((centre + 0.3) * SR)]
        assert abs(rms_db(seg) - body) < 1.5


def test_loop_very_short_track_does_not_crash():
    y = loop_to_length(np.ones((100, 2), np.float32), 1000)
    assert y.shape == (1000, 2)
    y1 = loop_to_length(np.ones(2, np.float32), 7)              # mono 1-D input, crossfade 0
    assert y1.shape == (7, 1)


def test_loop_longer_track_is_truncated_and_empty_rejected():
    x = np.ones((SR * 5, 2), np.float32)
    assert loop_to_length(x, SR).shape == (SR, 2)
    with pytest.raises(ValueError):
        loop_to_length(np.zeros((0, 2), np.float32), 10)


def test_rms_db():
    assert rms_db(np.zeros(10)) == float("-inf") and rms_db(np.zeros(0)) == float("-inf")
    assert rms_db(np.full(100, 0.5)) == pytest.approx(-6.02, abs=0.01)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_audio_dsp.py -q --tb=no`
Expected: `ModuleNotFoundError: No module named 'app.cin.audio_dsp'`.

- [ ] **Step 3: Create `app/cin/audio_dsp.py`**

```python
"""Pure NumPy audio helpers for the Phase C mix (spec §8.3). No I/O.

Envelope: SPEECH_DB under speech windows, GAP_DB in gaps >= MIN_GAP and over the final TAIL s.
Word timings are known in advance, so the ATTACK ramp ends exactly at a speech onset (look-ahead)
and the RELEASE ramp starts at the speech end. The tail is a gap whose release ends at D - TAIL."""
from __future__ import annotations

import numpy as np

SR = 48000
SPEECH_DB = -22.0
GAP_DB = -14.0
MIN_GAP = 0.5
TAIL = 1.0
ATTACK = 0.150
RELEASE = 0.300
FADE_IN = 0.3
FADE_OUT = 1.5
LOOP_XFADE = 1.0
CONTROL_RATE = 1000        # the envelope is computed at 1 kHz, then interpolated to SR


def db_to_gain(db):
    return np.power(10.0, np.asarray(db, dtype=np.float64) / 20.0)


def rms_db(x) -> float:
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        return float("-inf")
    r = float(np.sqrt(np.mean(np.square(x))))
    return float(20.0 * np.log10(r)) if r > 0 else float("-inf")


def speech_windows(tokens, duration: float, min_gap: float = MIN_GAP) -> list:
    """Merge (t0, t1) word timings into speech windows; silences shorter than min_gap count as speech."""
    spans = sorted((max(0.0, float(a)), min(float(duration), float(b))) for a, b in tokens)
    out = []
    for a, b in spans:
        if b <= a:
            continue
        if out and a - out[-1][1] < min_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 4), round(b, 4)] for a, b in out]


def duck_curve_db(windows, duration: float, rate: int = CONTROL_RATE) -> np.ndarray:
    """Music gain in dB sampled at `rate` Hz, with linear ATTACK/RELEASE ramps (slew-limited)."""
    n = max(1, int(round(duration * rate)))
    t = np.arange(n) / rate
    tail_start = max(0.0, duration - TAIL - RELEASE)   # release finishes exactly at duration - TAIL
    ducked = np.zeros(n, dtype=bool)
    for a, b in windows:
        b = min(b, tail_start)
        if b <= a:
            continue
        ducked |= (t >= a - ATTACK) & (t < b)
    target = np.where(ducked, SPEECH_DB, GAP_DB)
    down = (GAP_DB - SPEECH_DB) / (ATTACK * rate)      # dB per tick
    up = (GAP_DB - SPEECH_DB) / (RELEASE * rate)
    out = np.empty(n)
    cur = target[0]
    for i in range(n):
        tgt = target[i]
        if tgt < cur:
            cur = max(tgt, cur - down)
        elif tgt > cur:
            cur = min(tgt, cur + up)
        out[i] = cur
    return out


def fade_gain(n: int, sr: int = SR, fade_in: float = FADE_IN, fade_out: float = FADE_OUT) -> np.ndarray:
    g = np.ones(n)
    fi = min(n, int(round(fade_in * sr)))
    fo = min(n, int(round(fade_out * sr)))
    if fi:
        g[:fi] *= np.linspace(0.0, 1.0, fi, endpoint=False)
    if fo:
        g[n - fo:] *= np.linspace(1.0, 0.0, fo)
    return g


def music_gain(windows, duration: float, sr: int = SR) -> np.ndarray:
    """Per-sample linear gain for the music bed: duck curve x fades. Length = round(duration * sr)."""
    n = int(round(duration * sr))
    curve = duck_curve_db(windows, duration)
    tc = np.arange(len(curve)) / CONTROL_RATE
    ts = np.arange(n) / sr
    return db_to_gain(np.interp(ts, tc, curve)) * fade_gain(n, sr)


def loop_to_length(x: np.ndarray, n: int, sr: int = SR, xfade: float = LOOP_XFADE) -> np.ndarray:
    """Repeat x (frames x channels) to exactly n frames with equal-power (sin/cos) crossfades of
    `xfade` seconds; the crossfade shrinks to a third of the track for very short tracks."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if len(x) == 0:
        raise ValueError("empty track")
    if len(x) >= n:
        return x[:n].copy()
    xf = int(min(xfade * sr, len(x) // 3))
    if xf <= 0:
        return np.tile(x, (int(np.ceil(n / len(x))), 1))[:n]
    theta = np.linspace(0.0, np.pi / 2, xf, endpoint=False, dtype=np.float32)[:, None]
    fade_in, fade_out = np.sin(theta), np.cos(theta)
    out = np.zeros((n + len(x), x.shape[1]), dtype=np.float32)
    out[:len(x)] = x
    pos = len(x)                                   # end of the copy written last
    while pos < n:
        start = pos - xf
        out[start:pos] *= fade_out
        seg = x.copy()
        seg[:xf] *= fade_in
        out[start:start + len(x)] += seg
        pos = start + len(x)
    return out[:n]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_audio_dsp.py -q`
Expected: 11 passed. (The core of this module was prototyped on 2026-10-03; levels hit −22.00/−14.00 exactly.)

- [ ] **Step 5: Commit**

```bash
git add app/cin/audio_dsp.py tests/test_audio_dsp.py
git commit -m "feat: ducking envelope, fades and equal-power loop (pure NumPy)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Audio I/O and `mix_tracks` (voice polish + ducked music + SFX → 48 kHz WAV)

**Files:**
- Create: `app/cin/audio_io.py`
- Modify: `app/cin/mix.py` (add `mix_tracks`; the Phase A `mix_audio` stays until Task 5)
- Modify: `tests/conftest.py` (add `make_tone_wav`)
- Test: `tests/test_cin_mix.py`

**Interfaces:**
- Consumes: `app.encoding.find_ffmpeg`; everything in `app/cin/audio_dsp.py` (Task 3).
- Produces:
  - `audio_io.SR = 48000`, `audio_io.VOICE_POLISH` (spec string), `class AudioDecodeError(Exception)`
  - `decode_audio(path, sr=SR, channels=2, af=None, max_seconds=None) -> ndarray(frames, channels) float32` (raises `AudioDecodeError` on failure or zero samples)
  - `write_wav(path, x, sr=SR) -> None` (16-bit PCM, atomic)
  - `mix.mix_tracks(narration, out_wav, duration, *, music_path=None, duck_windows=(), sfx=()) -> dict` where each `sfx` item is a `place_sfx` entry plus `"path": Path`; returns `{"music": posix | None, "music_error": str, "sfx": int, "sfx_errors": [{"file", "reason"}], "voice_ref_db": float}`. Output WAV has exactly `round(duration*48000)` frames. Narration decode failure raises `AudioDecodeError`.
  - `tests.conftest.make_tone_wav(path, seconds, freq, amp, windows=None) -> Path`

- [ ] **Step 1: Add the test helper**

In `tests/conftest.py`, after `make_silence`, add:

```python
def make_tone_wav(path, seconds: float, freq: float, amp: float, windows=None) -> Path:
    """Stereo 48 kHz sine written with the stdlib; silent outside `windows` ([[t0, t1], ...]) if given."""
    import numpy as np
    from app.cin.audio_io import write_wav
    t = np.arange(int(round(seconds * 48000))) / 48000
    x = amp * np.sin(2 * np.pi * freq * t)
    if windows is not None:
        mask = np.zeros_like(t, dtype=bool)
        for a, b in windows:
            mask |= (t >= a) & (t < b)
        x = x * mask
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_wav(path, np.stack([x, x], axis=1))
    return Path(path)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_cin_mix.py`:

```python
"""Phase C mix (spec §8.3): voice polish, ducking depth, loop, SFX, 48 kHz, exact length."""
import wave

import numpy as np
import pytest

from app.cin.audio_io import AudioDecodeError, decode_audio, write_wav
from app.cin.mix import mix_tracks
from tests.conftest import make_tone, make_tone_wav

SR = 48000
WINDOWS = [[0.2, 2.0], [3.0, 5.0], [5.8, 7.2]]   # gap 2.0-3.0 (>= 0.5 s)


def read_wav(path):
    with wave.open(str(path)) as w:
        assert w.getframerate() == 48000 and w.getsampwidth() == 2 and w.getnchannels() == 2
        frames = w.getnframes()
        x = np.frombuffer(w.readframes(frames), "<i2").reshape(-1, 2) / 32767.0
    return x, frames


def band_db(x, freq, t0, t1):
    """Energy (dB, relative) in a +-30 Hz band; compare only equal-length windows."""
    seg = x[int(t0 * SR):int(t1 * SR), 0]
    spec = np.fft.rfft(seg * np.hanning(len(seg)))
    f = np.fft.rfftfreq(len(seg), 1 / SR)
    band = (f > freq - 30) & (f < freq + 30)
    return 10 * np.log10(np.sum(np.abs(spec[band]) ** 2) + 1e-20)


def test_decode_rejects_corrupt_and_respects_max_seconds(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio" * 200)
    with pytest.raises(AudioDecodeError):
        decode_audio(bad)
    tone = make_tone(tmp_path / "t.wav", 4.0)
    assert decode_audio(tone, max_seconds=1.0).shape == (SR, 2)
    assert decode_audio(tone, channels=1).shape == (4 * SR, 1)


def test_write_wav_is_s16_48k_exact_frames(tmp_path):
    write_wav(tmp_path / "o.wav", np.zeros((12345, 2)))
    _, frames = read_wav(tmp_path / "o.wav")
    assert frames == 12345


def test_ducking_depth_and_format(tmp_path):
    """Music is a 1 kHz tone LONGER than the video: a looped tone would add the expected +3 dB
    equal-power bump on correlated content and blur the depth measurement."""
    nar = make_tone_wav(tmp_path / "n.wav", 8.0, 220, 0.3, WINDOWS)
    mus = make_tone_wav(tmp_path / "m.wav", 12.0, 1000, 0.5)
    info = mix_tracks(nar, tmp_path / "mix.wav", 8.0, music_path=mus, duck_windows=WINDOWS)
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 8 * SR
    voice = band_db(x, 220, 3.5, 4.5)
    assert band_db(x, 1000, 3.5, 4.5) - voice == pytest.approx(-22.0, abs=2.0)          # under speech
    assert band_db(x, 1000, 2.35, 2.85) - band_db(x, 220, 3.5, 4.0) == pytest.approx(-14.0, abs=2.0)  # gap
    assert band_db(x, 1000, 7.0, 7.4) - band_db(x, 220, 3.5, 3.9) < -14.0               # fading out
    assert info["music"] == mus.as_posix() and info["sfx"] == 0


def test_continuous_speech_keeps_music_at_minus_22(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 8.0, 220, 0.3)
    mus = make_tone_wav(tmp_path / "m.wav", 12.0, 1000, 0.5)
    mix_tracks(nar, tmp_path / "mix.wav", 8.0, music_path=mus, duck_windows=[[0.0, 8.0]])
    x, _ = read_wav(tmp_path / "mix.wav")
    for t0 in (1.0, 3.0, 5.0, 6.0):
        assert band_db(x, 1000, t0, t0 + 0.5) - band_db(x, 220, t0, t0 + 0.5) == pytest.approx(-22.0, abs=2.0)


def test_short_music_is_looped_to_full_length(tmp_path):
    rng = np.random.default_rng(3)
    write_wav(tmp_path / "m.wav", (rng.standard_normal((4 * SR, 2)) * 0.1))
    nar = make_tone_wav(tmp_path / "n.wav", 10.0, 220, 0.3, [[0.5, 3.0]])
    mix_tracks(nar, tmp_path / "mix.wav", 10.0, music_path=tmp_path / "m.wav", duck_windows=[[0.5, 3.0]])
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 10 * SR
    assert np.sqrt(np.mean(x[int(6 * SR):int(8 * SR)] ** 2)) > 1e-3                    # music after 4 s


def test_sfx_longer_than_video_is_truncated(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 8.0, 220, 0.3, [[0.0, 3.0]])
    riser = make_tone_wav(tmp_path / "riser_long.wav", 20.0, 3000, 0.5)
    ev = [{"t": 2.0, "kind": "riser", "file": "x", "gain_db": -12.0, "path": riser}]
    info = mix_tracks(nar, tmp_path / "mix.wav", 8.0, duck_windows=[[0.0, 3.0]], sfx=ev)
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 8 * SR and info["sfx"] == 1
    assert band_db(x, 3000, 1.0, 1.9) < band_db(x, 3000, 7.0, 7.9) - 30                 # starts at 2.0, runs to the end


def test_sfx_offset_and_gain(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 6.0, 220, 0.3, [[0.0, 6.0]])
    hit = make_tone_wav(tmp_path / "impact.wav", 2.0, 2000, 0.5, [[0.0, 1.0]])           # 1 s on, 1 s silent
    ev = [{"t": 0.0, "kind": "impact", "file": "a", "gain_db": -6.0, "path": hit, "offset": 1.0}]
    mix_tracks(nar, tmp_path / "mix.wav", 6.0, duck_windows=[[0.0, 6.0]], sfx=ev)
    x, _ = read_wav(tmp_path / "mix.wav")
    assert band_db(x, 2000, 0.1, 0.9) < band_db(x, 220, 0.1, 0.9) - 30                  # offset skipped the tone
    ev[0].pop("offset")
    mix_tracks(nar, tmp_path / "mix2.wav", 6.0, duck_windows=[[0.0, 6.0]], sfx=ev)
    x2, _ = read_wav(tmp_path / "mix2.wav")
    # RMS-normalised to the voice over the whole 2 s file, then -6 dB: the 1 s burst is ~ -3 dB rel. voice
    assert band_db(x2, 2000, 0.1, 0.9) - band_db(x2, 220, 0.1, 0.9) == pytest.approx(-3.0, abs=2.0)


def test_corrupt_music_reports_error_and_still_mixes_voice(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 4.0, 220, 0.3, [[0.0, 4.0]])
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"\x00garbage" * 500)
    bad_sfx = tmp_path / "whoosh_bad.mp3"
    bad_sfx.write_bytes(b"junk" * 100)
    info = mix_tracks(nar, tmp_path / "mix.wav", 4.0, music_path=bad, duck_windows=[[0.0, 4.0]],
                      sfx=[{"t": 1.0, "kind": "whoosh", "file": "w", "gain_db": -10.0, "path": bad_sfx}])
    assert info["music"] is None and info["music_error"]
    assert info["sfx"] == 0 and info["sfx_errors"][0]["file"] == bad_sfx.as_posix()
    x, frames = read_wav(tmp_path / "mix.wav")
    assert frames == 4 * SR and np.max(np.abs(x)) > 0.05


def test_silent_voice_uses_fallback_reference(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 3.0, 220, 0.0)
    mus = make_tone_wav(tmp_path / "m.wav", 5.0, 1000, 0.5)
    info = mix_tracks(nar, tmp_path / "mix.wav", 3.0, music_path=mus, duck_windows=[])
    assert info["voice_ref_db"] == -20.0
    x, _ = read_wav(tmp_path / "mix.wav")
    assert np.max(np.abs(x)) > 0.01


def test_peak_guard_and_missing_narration(tmp_path):
    nar = make_tone_wav(tmp_path / "n.wav", 3.0, 220, 0.99, [[0.0, 3.0]])
    hit = make_tone_wav(tmp_path / "impact.wav", 3.0, 220, 0.99)
    mix_tracks(nar, tmp_path / "mix.wav", 3.0, duck_windows=[[0.0, 3.0]],
               sfx=[{"t": 0.0, "kind": "impact", "file": "i", "gain_db": 6.0, "path": hit}])
    x, _ = read_wav(tmp_path / "mix.wav")
    assert np.max(np.abs(x)) <= 0.8913 + 1e-3
    with pytest.raises(AudioDecodeError):
        mix_tracks(tmp_path / "nope.mp3", tmp_path / "m.wav", 3.0)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cin_mix.py -q --tb=no`
Expected: `ModuleNotFoundError: No module named 'app.cin.audio_io'`.

- [ ] **Step 4: Create `app/cin/audio_io.py`**

```python
"""ffmpeg-backed decode to NumPy and stdlib WAV write for the Phase C mix (spec §8.3)."""
from __future__ import annotations

import os
import subprocess
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from app.encoding import EncodingError, find_ffmpeg

SR = 48000
VOICE_POLISH = "highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=10:release=150"   # spec §8.3


class AudioDecodeError(Exception):
    pass


def decode_audio(path, sr: int = SR, channels: int = 2, af: Optional[str] = None,
                 max_seconds: Optional[float] = None) -> np.ndarray:
    """Decode any ffmpeg-readable file to float32 (frames, channels) at `sr`.
    Raises AudioDecodeError when ffmpeg fails or yields no samples (corrupt / non-audio files)."""
    name = Path(path).name
    try:
        cmd = [find_ffmpeg(), "-hide_banner", "-v", "error", "-nostdin", "-i", str(path)]
    except EncodingError as e:
        raise AudioDecodeError(str(e)) from e
    if max_seconds:
        cmd += ["-t", f"{max_seconds:.3f}"]
    if af:
        cmd += ["-af", af]
    cmd += ["-vn", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AudioDecodeError(f"{name}: {e}") from e
    if res.returncode != 0:
        raise AudioDecodeError(f"{name}: {res.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    data = np.frombuffer(res.stdout, dtype="<f4")
    frames = len(data) // channels
    if frames == 0:
        raise AudioDecodeError(f"{name}: no audio samples")
    return data[: frames * channels].reshape(frames, channels).copy()


def write_wav(path, x: np.ndarray, sr: int = SR) -> None:
    """16-bit PCM WAV (clipped to [-1, 1]); written to a temp file and renamed."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).round().astype("<i2")
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    os.replace(tmp, path)
```

- [ ] **Step 5: Add `mix_tracks` to `app/cin/mix.py`**

Add these imports below the existing ones (`from app.encoding import EncodingError, find_ffmpeg`):

```python
import logging

import numpy as np

from app.cin.audio_dsp import SR, db_to_gain, loop_to_length, music_gain, rms_db
from app.cin.audio_io import VOICE_POLISH, AudioDecodeError, decode_audio, write_wav

logger = logging.getLogger(__name__)

REF_DB = -20.0            # voice reference when the narration is silent
SILENCE_DB = -60.0
PEAK_CEILING = 0.8913     # -1 dBFS; loudnorm restores the level afterwards
MUSIC_DECODE_PAD = 5.0    # decode only what the video needs (+ margin) from long tracks
```

Append at the end of the file:

```python
def _fit(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - len(x), x.shape[1]), dtype=x.dtype)])


def _speech_mask(windows, n: int) -> np.ndarray:
    mask = np.zeros(n, dtype=bool)
    for a, b in windows:
        mask[int(a * SR):int(b * SR)] = True
    return mask


def mix_tracks(narration, out_wav, duration: float, *, music_path: Optional[Path] = None,
               duck_windows=(), sfx=()) -> dict:
    """spec §8.3: polished voice + looped, ducked music + SFX -> 48 kHz s16 WAV of exactly `duration`.
    0 dB reference = polished voice RMS over duck_windows (REF_DB if silent). Music and SFX are
    RMS-normalised to it before their gains. Unreadable music/SFX are reported, never raised."""
    n = int(round(duration * SR))
    voice = _fit(decode_audio(narration, af=VOICE_POLISH), n)
    mask = _speech_mask(duck_windows, n)
    ref = rms_db(voice[mask]) if mask.any() else float("-inf")
    if not np.isfinite(ref) or ref < SILENCE_DB:
        ref = REF_DB
    mix = voice.astype(np.float32)
    info = {"music": None, "music_error": "", "sfx": 0, "sfx_errors": [], "voice_ref_db": round(float(ref), 2)}

    if music_path is not None:
        try:
            bed = loop_to_length(decode_audio(music_path, max_seconds=duration + MUSIC_DECODE_PAD), n)
            level = rms_db(bed)
            if not np.isfinite(level) or level < SILENCE_DB:
                raise AudioDecodeError(f"{Path(music_path).name}: silent track")
            gain = music_gain(duck_windows, duration) * db_to_gain(ref - level)
            mix += (bed * gain[:, None]).astype(np.float32)
            info["music"] = Path(music_path).as_posix()
        except AudioDecodeError as e:
            info["music_error"] = str(e)[:300]
            logger.warning("Music skipped in mix: %s", e)

    cache = {}
    for ev in sfx:
        path = Path(ev["path"])
        try:
            if path not in cache:
                cache[path] = decode_audio(path, max_seconds=duration + 60.0)
        except AudioDecodeError as e:
            info["sfx_errors"].append({"file": path.as_posix(), "reason": str(e)[:300]})
            cache[path] = None
        clip = cache[path]
        if clip is None:
            continue
        clip = clip[int(round(float(ev.get("offset", 0.0)) * SR)):]
        level = rms_db(clip)
        start = int(round(float(ev["t"]) * SR))
        if not np.isfinite(level) or level < SILENCE_DB or start >= n:
            continue
        end = min(n, start + len(clip))
        mix[start:end] += (clip[: end - start] * db_to_gain(ref - level + float(ev.get("gain_db", -6.0)))
                           ).astype(np.float32)
        info["sfx"] += 1

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > PEAK_CEILING:
        mix *= PEAK_CEILING / peak
    write_wav(out_wav, mix)
    return info
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cin_mix.py tests/test_audio_dsp.py -q`
Expected: all pass. If `test_ducking_depth_and_format` is off by more than 2 dB, print `band_db` values and check the music tone length (must exceed the video) before touching the DSP.

- [ ] **Step 7: Commit**

```bash
git add app/cin/audio_io.py app/cin/mix.py tests/conftest.py tests/test_cin_mix.py
git commit -m "feat: Phase C mix - voice polish, ducked looped music, SFX to 48 kHz WAV

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Wire music/SFX into `render_job`, re-render and the pipeline (`--music-source`)

**Files:**
- Modify: `app/cin/editor.py` (`pick_music`, new `sfx_pool`/`_speech_spans`/`music_wanted`, the `"mix"` stage of `render_job`, `rebuild_plan`, `rerender_job`)
- Modify: `app/cin/mix.py` (delete Phase A `mix_audio` and `_fit_duration`; update docstring)
- Modify: `main.py` (`run_pipeline`, `_run_shot_editor`, `_run_classic`, `parse_args`, `run_auto_mode`, `run_interactive_mode`, `main`)
- Test: `tests/test_cin_editor.py`, `tests/test_rerender.py`, `tests/test_pipeline.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: Task 1 (`list_tracks`, `select_track`, `UsageStore`, `asset_path`, `asset_key`, `MUSIC_SOURCES`), Task 2 (`scan_sfx`, `SfxFile`, `place_sfx`), Task 3 (`speech_windows`), Task 4 (`mix_tracks`, `decode_audio`, `AudioDecodeError`, `SR`).
- Produces:
  - `editor.MIN_TRACK_SECONDS = 3.0`, `music_wanted(options) -> bool`
  - `pick_music(options, report, keep: Optional[str] = None) -> Optional[Path]` (signature-compatible with Phase A)
  - `sfx_pool(report) -> dict[str, list[SfxFile]]`
  - `render_job(...)` now sets `plan.music = {"file", "mood", "source", "duck_windows"} | None` and `plan.sfx = [...]` in memory (never saves)
  - `rerender_job(job_dir, *, pacing, subtitle_style, no_sfx, no_music, color_grade, music_source: Optional[str] = None)`
  - `main.run_pipeline(..., music_source: Optional[str] = None)`; CLI `--music-source {mine,generated,any,none}`

- [ ] **Step 1: Write the failing tests**

In `tests/test_cin_editor.py`, add `import json`, `from pathlib import Path` and extend the conftest import to `from tests.conftest import build_gold_job, make_silence, make_test_clip, make_tone, make_tone_wav`. Then append:

```python
def _audio_library(tmp_path, monkeypatch, music=True, sfx=True):
    from app.config import settings
    music_dir, sfx_dir = tmp_path / "lib" / "music", tmp_path / "lib" / "sfx"
    (music_dir / "cinematic").mkdir(parents=True)
    (sfx_dir / "generated").mkdir(parents=True)
    if music:
        make_tone_wav(music_dir / "cinematic" / "track_a.wav", 12.0, 1000, 0.4)
    if sfx:
        make_tone_wav(sfx_dir / "generated" / "whoosh_1.wav", 0.8, 3000, 0.4)
        make_tone_wav(sfx_dir / "generated" / "impact_1.wav", 1.2, 80, 0.4)
        make_tone_wav(sfx_dir / "generated" / "riser_1.wav", 20.0, 2000, 0.4)   # longer than the video
    monkeypatch.setattr(settings, "music_dir", str(music_dir))
    monkeypatch.setattr(settings, "sfx_dir", str(sfx_dir))
    monkeypatch.setattr(settings, "music_enabled", True)
    monkeypatch.setattr(settings, "enable_sfx", True)
    return music_dir, sfx_dir


def test_pick_music_skips_short_and_corrupt_tracks(tmp_path, monkeypatch):
    music_dir, _ = _audio_library(tmp_path, monkeypatch, music=False, sfx=False)
    epic = music_dir / "epic"
    epic.mkdir()
    make_tone_wav(epic / "a_blip.wav", 0.5, 440, 0.3)             # shorter than 1 s
    (epic / "b_broken.mp3").write_bytes(b"\x00not an mp3" * 300)  # corrupt download
    good = make_tone_wav(epic / "c_good.wav", 5.0, 440, 0.3)
    report = RunReport(job="j")
    assert pick_music(RenderOptions(music_mood="epic"), report) == good
    skipped = [w for w in report.warnings if w["code"] == "music_track_skipped"]
    assert [Path(w["detail"]["file"]).name for w in skipped] == ["a_blip.wav", "b_broken.mp3"]
    good.unlink()
    report = RunReport(job="j")
    assert pick_music(RenderOptions(music_mood="epic"), report) is None
    assert [w["code"] for w in report.warnings][-1] == "music_missing"


def test_music_source_none_and_disabled_give_no_warning(tmp_path, monkeypatch):
    _audio_library(tmp_path, monkeypatch)
    for opts in (RenderOptions(music_source="none"), RenderOptions(enable_music=False)):
        report = RunReport(job="j")
        assert pick_music(opts, report) is None and report.warnings == []


def test_pick_music_honours_source_and_keep(tmp_path, monkeypatch):
    music_dir, _ = _audio_library(tmp_path, monkeypatch)
    gen = make_tone_wav(music_dir / "cinematic" / "generated" / "cinematic_01.wav", 6.0, 500, 0.3)
    mine = music_dir / "cinematic" / "track_a.wav"
    assert pick_music(RenderOptions(music_mood="cinematic", music_source="generated"), RunReport(job="j")) == gen
    assert pick_music(RenderOptions(music_mood="cinematic", music_source="mine"), RunReport(job="j")) == mine
    kept = pick_music(RenderOptions(music_mood="cinematic"), RunReport(job="j"), keep=gen.as_posix())
    assert kept == gen


def test_render_job_fills_plan_music_and_sfx(tmp_path, monkeypatch):
    music_dir, sfx_dir = _audio_library(tmp_path, monkeypatch)
    job, alignment, specs = build_gold_job(tmp_path)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    plan = build_shot_plan(alignment, "standard", specs)
    for shot in plan.shots:
        shot.transition_in = "cut"
    plan.shots[1].transition_in = "flash"
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(music_mood="cinematic", enable_subtitles=False), report)
    assert plan.music["file"] == (music_dir / "cinematic" / "track_a.wav").as_posix()
    assert plan.music["duck_windows"] and plan.music["source"] == "any"
    kinds = [e["kind"] for e in plan.sfx]
    assert kinds.count("impact") == 1 and kinds.count("whoosh") == len(plan.scenes) - 1
    assert kinds.count("riser") == 1
    assert report.options["music_file"] == plan.music["file"]
    assert not [w for w in report.warnings if w["code"] in ("music_missing", "sfx_missing")]
    import wave
    with wave.open(str(job.mix)) as w:
        assert w.getframerate() == 48000 and abs(w.getnframes() - round(plan.duration * 48000)) <= 1
    assert -15.0 <= report.loudness["I"] <= -13.0 and report.loudness["TP"] <= -1.0
    video, audio = _stream_durations(job.final)
    assert abs(audio - plan.duration) <= 0.05
    json.dumps(plan.to_json())                                     # serialisable contract


def test_render_job_survives_corrupt_music_and_sfx(tmp_path, monkeypatch):
    music_dir, sfx_dir = _audio_library(tmp_path, monkeypatch, music=False, sfx=False)
    (music_dir / "cinematic" / "bad.mp3").write_bytes(b"junk" * 500)
    (sfx_dir / "whoosh_bad.mp3").write_bytes(b"junk" * 50)
    job, alignment, specs = build_gold_job(tmp_path)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    plan = build_shot_plan(alignment, "standard", specs)
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(music_mood="cinematic", enable_subtitles=False), report)
    codes = [w["code"] for w in report.warnings]
    assert {"music_track_skipped", "music_missing", "sfx_file_skipped", "sfx_missing"} <= set(codes)
    assert plan.music is None and plan.sfx == [] and job.final.exists()


def test_sfx_disabled_by_setting_or_option(tmp_path, monkeypatch):
    from app.config import settings
    _audio_library(tmp_path, monkeypatch)
    job, alignment, specs = build_gold_job(tmp_path)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    monkeypatch.setattr(settings, "enable_sfx", False)
    plan = build_shot_plan(alignment, "standard", specs)
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(music_source="none", enable_subtitles=False), report)
    assert plan.sfx == [] and plan.music is None
    assert not [w for w in report.warnings if w["code"] in ("music_missing", "sfx_missing", "sfx_file_skipped")]
```

Replace `test_new_warning_codes_registered` body's assertion line with:

```python
    assert {"platform_check_failed", "final_swap_failed", "music_track_skipped", "sfx_file_skipped"} <= set(WARNING_CODES)
```

In `tests/test_rerender.py` append:

```python
def _music_lib(tmp_path, monkeypatch):
    from app.config import settings
    from tests.conftest import make_tone_wav
    music = tmp_path / "lib" / "music"
    a = make_tone_wav(music / "cinematic" / "a.wav", 10.0, 900, 0.3)
    b = make_tone_wav(music / "cinematic" / "generated" / "cinematic_01.wav", 10.0, 700, 0.3)
    monkeypatch.setattr(settings, "music_dir", str(music))
    monkeypatch.setattr(settings, "music_enabled", True)
    monkeypatch.setattr(settings, "enable_sfx", False)
    return a, b


class _Tiny:
    def __init__(self, plan, job, **kwargs):
        self.plan = plan

    def render(self, out_path, overlays=None):
        from tests.conftest import make_test_clip
        return make_test_clip(out_path, self.plan.duration)


def _music_job(tmp_path, monkeypatch, root="a"):
    job, alignment, specs = build_gold_job(tmp_path / root)
    plan = build_shot_plan(alignment, "standard", specs)
    opts = RenderOptions(music_mood="cinematic", enable_sfx=False, enable_subtitles=False)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _Tiny)
    render_job(job, plan, opts, RunReport(job=job.name))
    plan.save(job.shot_plan)
    RunReport(job=job.name, options={**opts.to_json(), "enable_motion": True}).save(job.report)
    return job, plan


def test_rerender_keeps_music_without_override(tmp_path, monkeypatch):
    a, b = _music_lib(tmp_path, monkeypatch)
    job, plan = _music_job(tmp_path, monkeypatch)
    assert plan.music["file"] == a.as_posix()
    rerender_job(job.root, pacing="fast")
    assert ShotPlan.load(job.shot_plan).music["file"] == a.as_posix()      # no LRU re-pick


def test_rerender_music_source_override_reselects(tmp_path, monkeypatch):
    a, b = _music_lib(tmp_path, monkeypatch)
    job, plan = _music_job(tmp_path, monkeypatch)
    rerender_job(job.root, music_source="generated")
    new = ShotPlan.load(job.shot_plan)
    assert new.music["file"] == b.as_posix() and new.music["source"] == "generated"
    assert RunReport.load(job.report).options["music_source"] == "generated"
    rerender_job(job.root, no_music=True)
    assert ShotPlan.load(job.shot_plan).music is None


def test_rerender_moved_job_keeps_repo_relative_music(tmp_path, monkeypatch):
    """Library paths are cwd-relative asset paths, never resolved against the job folder."""
    from app.config import settings
    monkeypatch.chdir(tmp_path)
    from tests.conftest import make_tone_wav
    make_tone_wav(tmp_path / "assets" / "music" / "cinematic" / "rel.wav", 10.0, 800, 0.3)
    monkeypatch.setattr(settings, "music_dir", "assets/music")
    monkeypatch.setattr(settings, "music_enabled", True)
    monkeypatch.setattr(settings, "enable_sfx", False)
    job, plan = _music_job(tmp_path, monkeypatch)
    assert plan.music["file"] == "assets/music/cinematic/rel.wav"
    moved = tmp_path / "moved" / job.name
    shutil.copytree(job.root, moved)
    rerender_job(moved, pacing="fast")
    assert ShotPlan.load(open_job(moved).shot_plan).music["file"] == "assets/music/cinematic/rel.wav"
```

In `tests/test_pipeline.py` append:

```python
def test_music_source_reaches_render_and_plan_saved_after_render(offline, monkeypatch):
    seen = {}

    def render_with_music(job, plan, options, report):
        seen["music_source"] = options.music_source
        plan.music = {"file": "assets/music/epic/x.mp3", "mood": "", "source": options.music_source,
                      "duck_windows": [[0.0, 1.0]]}
        plan.sfx = [{"t": 0.0, "kind": "impact", "file": "assets/sfx/impact.mp3", "gain_db": -6.0}]
        return fake_render(job, plan, options, report)

    monkeypatch.setattr(main, "render_job", render_with_music)
    main.run_pipeline("Gold facts", use_mock_images=True, music_source="generated")
    job = only_job(offline.out)
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert seen["music_source"] == "generated"
    assert plan["music"]["source"] == "generated" and plan["sfx"][0]["kind"] == "impact"
    assert report_of(job)["options"]["music_source"] == "generated"


def test_music_source_defaults_to_settings_and_rejects_unknown(offline, monkeypatch):
    seen = {}
    monkeypatch.setattr(settings, "music_source", "mine")
    monkeypatch.setattr(main, "render_job",
                        lambda job, plan, options, report: seen.update(src=options.music_source) or fake_render(job, plan, options, report))
    main.run_pipeline("Gold facts", use_mock_images=True)
    assert seen["src"] == "mine"
    with pytest.raises(ValueError):
        main.run_pipeline("Gold facts", use_mock_images=True, music_source="spotify")
```

In `tests/test_cli.py`: in `test_main_rerender_skips_config_validation` replace the final assertion with

```python
    assert calls == {"job_dir": "output/job", "pacing": "fast", "subtitle_style": None,
                     "no_sfx": True, "no_music": False, "color_grade": None, "music_source": None}
```

and append:

```python
def test_music_source_flag():
    import pytest
    assert parse_args([]).music_source is None
    assert parse_args(["--music-source", "generated"]).music_source == "generated"
    assert parse_args(["--rerender", "output/j", "--music-source", "none"]).music_source == "none"
    with pytest.raises(SystemExit):
        parse_args(["--music-source", "spotify"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cin_editor.py tests/test_rerender.py tests/test_pipeline.py tests/test_cli.py -q --tb=line -m "not render"`
Expected: the new tests fail (`TypeError: pick_music() got an unexpected keyword argument 'keep'`, `unexpected keyword argument 'music_source'`, missing `--music-source`, `plan.music is None`); pre-existing tests pass.

- [ ] **Step 3: Editor — imports, helpers, `pick_music`, `sfx_pool`**

In `app/cin/editor.py` replace the import line `from app.cin.mix import mix_audio` with:

```python
from app.cin.audio_dsp import speech_windows
from app.cin.audio_io import SR, AudioDecodeError, decode_audio
from app.cin.mix import mix_tracks
from app.cin.music_library import UsageStore, asset_key, asset_path, list_tracks, select_track
from app.cin.sfx_library import SfxFile, place_sfx, scan_sfx
```

Replace the whole Phase A `def pick_music(...)` function (from `def pick_music(options: RenderOptions, report: RunReport) -> Optional[Path]:` through its `return path`) with:

```python
MIN_TRACK_SECONDS = 3.0     # shorter "tracks" (blips, jingles) are skipped, never looped as a bed


def music_wanted(options: RenderOptions) -> bool:
    return bool(options.enable_music and settings.music_enabled and options.music_source != "none")


def _usable_track(path: Path, report: RunReport) -> bool:
    try:
        head = decode_audio(path, max_seconds=MIN_TRACK_SECONDS + 0.5)
    except AudioDecodeError as e:
        report.warn("music_track_skipped", f"Unreadable music file skipped: {Path(path).name}",
                    {"file": asset_key(path), "reason": str(e)[:300]})
        return False
    if len(head) < MIN_TRACK_SECONDS * SR:
        report.warn("music_track_skipped",
                    f"Music file shorter than {MIN_TRACK_SECONDS:.0f}s skipped: {Path(path).name}",
                    {"file": asset_key(path), "seconds": round(len(head) / SR, 2)})
        return False
    return True


def pick_music(options: RenderOptions, report: RunReport, keep: Optional[str] = None) -> Optional[Path]:
    """spec §8.1: least-recently-used usable track for options.music_mood / music_source.
    keep (a re-render's previous track) is reused as-is when it still exists and decodes."""
    if not music_wanted(options):
        return None
    if keep and asset_path(keep).is_file() and _usable_track(asset_path(keep), report):
        return asset_path(keep)
    candidates = list_tracks(settings.music_dir, options.music_mood, options.music_source)
    path = select_track(candidates, UsageStore(), accept=lambda p: _usable_track(p, report))
    if path is None:
        report.warn("music_missing",
                    f"No usable music for mood '{options.music_mood or 'any'}' "
                    f"(music_source={options.music_source}) under {settings.music_dir}; "
                    "add tracks or run --build-music-library",
                    {"mood": options.music_mood, "music_source": options.music_source,
                     "candidates": len(candidates)})
    return path


def sfx_pool(report: RunReport) -> dict:
    """{kind: [SfxFile]} from settings.sfx_dir; unreadable files are skipped with a warning."""
    pool = {}
    for kind, paths in scan_sfx(settings.sfx_dir).items():
        files = []
        for p in paths:
            try:
                frames = len(decode_audio(p, channels=1, max_seconds=60.0))
            except AudioDecodeError as e:
                report.warn("sfx_file_skipped", f"Unreadable SFX file skipped: {p.name}",
                            {"file": asset_key(p), "reason": str(e)[:300]})
                continue
            files.append(SfxFile(p, kind, frames / SR))
        pool[kind] = files
    return pool


def _speech_spans(job: JobPaths, plan: ShotPlan) -> list:
    """Word (t0, t1) timings for ducking: alignment.json tokens, else the plan's caption words."""
    if job.alignment.exists():
        try:
            al = Alignment.from_json(json.loads(job.alignment.read_text(encoding="utf-8")))
            return [(t.t0, t.t1) for t in al.tokens]
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("alignment.json unreadable for ducking (%s); using caption timings", e)
    return [(w.t0, w.t1) for g in plan.captions for w in g.words]
```

- [ ] **Step 4: Editor — the `"mix"` stage of `render_job`**

Replace the whole block that starts with `    with report.stage("mix"):` and ends with the line `            report.warn("sfx_missing", f"No SFX files under {settings.sfx_dir}", {})` with:

```python
    with report.stage("mix"):
        sfx_on = options.enable_sfx and settings.enable_sfx
        windows = speech_windows(_speech_spans(job, plan), plan.duration)
        music_path = pick_music(options, report, keep=(plan.music or {}).get("file"))
        pool = sfx_pool(report) if sfx_on else {}
        plan.sfx = place_sfx(plan, pool) if sfx_on else []
        if sfx_on and not any(pool.values()):
            report.warn("sfx_missing", f"No usable SFX files under {settings.sfx_dir} "
                        "(add whoosh*/impact*/riser* files or run --build-sfx-library)", {})
        info = mix_tracks(job.narration, job.mix, plan.duration, music_path=music_path,
                          duck_windows=windows, sfx=[{**e, "path": asset_path(e["file"])} for e in plan.sfx])
        for err in info["sfx_errors"]:
            report.warn("sfx_file_skipped", f"SFX file failed to decode during the mix: {err['file']}", err)
        if music_path is not None and info["music"] is None:
            report.warn("music_missing", f"Music file failed during the mix: {music_path.name}",
                        {"file": asset_key(music_path), "reason": info["music_error"]})
        plan.music = ({"file": asset_key(music_path), "mood": options.music_mood,
                       "source": options.music_source, "duck_windows": windows}
                      if info["music"] else None)
        report.options["music_file"] = plan.music["file"] if plan.music else None
```

- [ ] **Step 5: Editor — `rebuild_plan` and `rerender_job`**

In `rebuild_plan`, replace `    return build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))` with:

```python
    plan = build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))
    plan.music = old.music          # same track unless --music-source asks for a new one (spec §9.3)
    return plan
```

Change the `rerender_job` signature line to:

```python
def rerender_job(job_dir, *, pacing: Optional[str] = None, subtitle_style: Optional[str] = None,
                 no_sfx: bool = False, no_music: bool = False, color_grade: Optional[str] = None,
                 music_source: Optional[str] = None) -> str:
```

After the block `    if color_grade is not None:\n        opts.color_grade = color_grade` add:

```python
    if music_source:
        opts.music_source = music_source
```

After the line `            plan = rebuild_plan(job, opts.pacing, enable_motion=bool(prev.options.get("enable_motion", True)))` add (same indentation as that line's `with` block body):

```python
        if music_source:
            plan.music = None       # re-select from the requested source
```

- [ ] **Step 6: Remove the Phase A mix**

In `app/cin/mix.py` delete `def _fit_duration(...)` and `def mix_audio(...)` entirely, delete the now-unused imports `os`, `subprocess`, `from app.config import settings` and `from app.encoding import EncodingError, find_ffmpeg`, and replace the module docstring with:

```python
"""Phase C audio mix (spec §8.3): polished voice + looped, ducked music + SFX, written as a
48 kHz WAV to sources/mix.wav. Loudness normalization happens later, in app.encoding.mux_final."""
```

Run: `grep -rn "mix_audio\|_fit_duration" app main.py tests` — expected: only `app/video_editor.py: def _mix_audio` (classic editor, unrelated).

- [ ] **Step 7: `main.py` — pipeline, classic, CLI**

1. Imports: below `from app.cin.shot_plan import PACING, build_shot_plan, plan_segments` add `from app.cin.music_library import MUSIC_SOURCES`.
2. `_run_shot_editor`: replace

```python
    final = render_job(job, plan, options, report)
    return str(final), image_paths, specs
```

with

```python
    final = render_job(job, plan, options, report)
    plan.save(job.shot_plan)               # again: render_job filled plan.music / plan.sfx
    return str(final), image_paths, specs
```

3. `_run_classic`: as the first line of the function body add `    classic_music = options.enable_music and options.music_source != "none"` and replace both occurrences of `enable_music=options.enable_music` inside `_run_classic` with `enable_music=classic_music`.
4. `run_pipeline` signature: after `    classic: bool = False,` add `    music_source: Optional[str] = None,`. In the body, after the line `    strict = settings.strict if strict is None else strict` add:

```python
    music_source = music_source or settings.music_source
    if music_source not in MUSIC_SOURCES:
        raise ValueError(f"Unknown music_source {music_source!r}; choose one of {list(MUSIC_SOURCES)}")
```

and in the `RenderOptions(` call replace `enable_sfx=enable_sfx, music_mood=resolve_music_mood(niche, video_style), strict=strict,` with

```python
        enable_sfx=enable_sfx, music_mood=resolve_music_mood(niche, video_style), music_source=music_source,
        strict=strict,
```

Also add one line to the docstring: `music_source defaults to settings.music_source (mine | generated | any | none).`
5. `parse_args`: after the `--color-grade` argument add:

```python
    parser.add_argument("--music-source", choices=list(MUSIC_SOURCES), default=None,
                        help="Music pool: mine, generated, any or none (default: settings.music_source; "
                             "with --rerender: keep the job's track)")
```

6. `run_auto_mode` and `run_interactive_mode`: in each `run_pipeline(` call add `music_source=args.music_source,` after `classic=args.classic,`.
7. `main()`: in the `rerender_job(` call replace `no_sfx=args.no_sfx, no_music=args.no_music, color_grade=args.color_grade)` with

```python
                               no_sfx=args.no_sfx, no_music=args.no_music, color_grade=args.color_grade,
                               music_source=args.music_source)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cin_editor.py tests/test_rerender.py tests/test_pipeline.py tests/test_cli.py tests/test_cin_mix.py tests/test_sfx.py tests/test_video_editor.py -q`
Expected: all pass, including the `render`-marked tests (`test_render_job_full_size_meets_delivery_spec`, `test_rerender_fast_pacing_zero_network`, `test_mock_run_end_to_end`). `test_sfx.py` / `test_video_editor.py` prove the classic path is untouched.

- [ ] **Step 9: Commit**

```bash
git add app/cin/editor.py app/cin/mix.py main.py tests/test_cin_editor.py tests/test_rerender.py tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: LRU music, SFX placement and ducked mix in render_job; --music-source for runs and --rerender

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: ElevenLabs music and SFX library builders

**Files:**
- Create: `app/cin/library_builder.py`
- Test: `tests/test_library_builder.py`

**Interfaces:**
- Consumes: `settings.elevenlabs_api_key`, `settings.music_dir`, `settings.sfx_dir`, `settings.elevenlabs_music_model`, `settings.cost_elevenlabs_music_per_minute`, `settings.cost_elevenlabs_sfx_per_minute` (Task 1); `music_library.MOODS`, `GENERATED_DIR`, `MUSIC_EXTENSIONS` (Task 1).
- Produces:
  - `MUSIC_URL = "https://api.elevenlabs.io/v1/music"`, `SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"`, `OUTPUT_FORMAT = "mp3_44100_128"`, `TRACK_SECONDS = 60`, `SFX_SPECS` (7 entries)
  - `class LibraryAccessError(Exception)`; `@dataclass LibraryItem(path, url, payload, seconds, timeout)`
  - `plan_music_items(music_dir, moods, per_mood) -> (todo, skipped)`, `plan_sfx_items(sfx_dir) -> (todo, skipped)`
  - `estimate_cost(items) -> float`
  - `fetch_item(item, api_key, *, post=None, sleep=None) -> None`
  - `build_music_library(*, per_mood=5, moods=None, yes=False, input_fn=input, post=None, sleep=None, out=print) -> int` and `build_sfx_library(*, yes=False, input_fn=input, post=None, sleep=None, out=print) -> int` — exit codes: 0 done/nothing to do, 1 declined or some items failed, 2 no key or access refused (401/402/403).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_library_builder.py`:

```python
"""--build-music-library / --build-sfx-library (spec §8.1-8.2). HTTP is always a fake `post`."""
import pytest
import requests

from app.cin import library_builder as lb
from app.config import settings

FAKE_KEY = "test-key-not-real"


class Resp:
    def __init__(self, status, content=b"", js=None, text=""):
        self.status_code, self.content, self._js, self.text = status, content, js, text

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "music_dir", str(tmp_path / "music"))
    monkeypatch.setattr(settings, "sfx_dir", str(tmp_path / "sfx"))
    monkeypatch.setattr(settings, "elevenlabs_api_key", FAKE_KEY)
    monkeypatch.setattr(settings, "elevenlabs_music_model", "music_v1")

    def no_network(*a, **k):
        raise AssertionError("real network call")

    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setattr(requests, "get", no_network)
    return tmp_path


def recorder(responses=None):
    responses = list(responses or [])
    calls = []

    def post(url, **kw):
        calls.append((url, kw))
        return responses.pop(0) if responses else Resp(200, b"ID3fake-audio")
    return post, calls


def test_music_build_requests_estimate_and_files(env):
    post, calls = recorder()
    lines = []
    code = lb.build_music_library(per_mood=5, yes=True, post=post, sleep=lambda s: None, out=lines.append)
    assert code == 0 and len(calls) == 25
    assert any("$3.75" in line for line in lines)                      # 25 x 60 s x $0.15/min
    url, kw = calls[0]
    assert url == "https://api.elevenlabs.io/v1/music"
    assert kw["params"] == {"output_format": "mp3_44100_128"}
    body = kw["json"]
    assert body["music_length_ms"] == 60000 and body["force_instrumental"] is True
    assert body["model_id"] == "music_v1" and "no vocals" in body["prompt"]
    assert kw["headers"]["xi-api-key"] == FAKE_KEY
    assert (env / "music" / "epic" / "generated" / "epic_05.mp3").read_bytes() == b"ID3fake-audio"
    assert not list((env / "music").rglob("*.part"))
    assert all(FAKE_KEY not in line for line in lines)


def test_existing_files_are_skipped(env):
    post, calls = recorder()
    lb.build_music_library(per_mood=2, moods=["dark"], yes=True, post=post, out=lambda s: None)
    post2, calls2 = recorder()
    lines = []
    assert lb.build_music_library(per_mood=3, moods=["dark"], yes=True, post=post2, out=lines.append) == 0
    assert len(calls2) == 1 and calls2[0][1]["json"]["prompt"]                 # only dark_03
    assert sum("skip (exists)" in line for line in lines) == 2


def test_confirmation_declined_or_no_tty(env):
    post, calls = recorder()
    assert lb.build_sfx_library(input_fn=lambda prompt: "n", post=post, out=lambda s: None) == 1

    def eof(prompt):
        raise EOFError

    assert lb.build_sfx_library(input_fn=eof, post=post, out=lambda s: None) == 1
    assert calls == []
    assert lb.build_sfx_library(input_fn=lambda prompt: "y", post=post, out=lambda s: None) == 0
    assert len(calls) == 7


def test_plan_or_permission_refusal_stops_with_clear_message(env):
    for status in (401, 402, 403):
        post, calls = recorder([Resp(status, js={"detail": {"status": "missing_permissions",
                                                            "message": "Music requires a paid plan"}})])
        lines = []
        code = lb.build_music_library(per_mood=2, moods=["epic"], yes=True, post=post,
                                      sleep=lambda s: None, out=lines.append)
        assert code == 2 and len(calls) == 1
        msg = " ".join(lines)
        assert f"HTTP {status}" in msg and "paid plan" in msg and "plan" in msg and FAKE_KEY not in msg
    assert not list((env / "music").rglob("*.mp3"))


def test_rate_limit_retries_and_bad_prompt_continues(env):
    post, calls = recorder([Resp(429, text="busy"), Resp(200, b"ok"),
                            Resp(422, js={"detail": [{"msg": "prompt rejected"}]})])
    sleeps, lines = [], []
    code = lb.build_music_library(per_mood=3, moods=["chill"], yes=True, post=post,
                                  sleep=sleeps.append, out=lines.append)
    assert code == 1 and len(calls) == 4 and sleeps == [5]       # 429 retried; 422 not retried
    assert any("prompt rejected" in line for line in lines)
    assert sorted(p.name for p in (env / "music" / "chill" / "generated").iterdir()) == ["chill_01.mp3", "chill_03.mp3"]


def test_network_errors_retry_then_fail(env):
    def flaky(url, **kw):
        raise requests.ConnectionError("down")
    lines = []
    code = lb.build_sfx_library(yes=True, post=flaky, sleep=lambda s: None, out=lines.append)
    assert code == 1 and any("network error" in line for line in lines)


def test_sfx_build_requests(env):
    post, calls = recorder()
    assert lb.build_sfx_library(yes=True, post=post, sleep=lambda s: None, out=lambda s: None) == 0
    assert len(calls) == 7 and calls[0][0] == "https://api.elevenlabs.io/v1/sound-generation"
    body = calls[0][1]["json"]
    assert body["model_id"] == "eleven_text_to_sound_v2" and 0.5 <= body["duration_seconds"] <= 30
    assert body["loop"] is False and "text" in body
    names = sorted(p.name for p in (env / "sfx" / "generated").iterdir())
    assert names == ["impact_1.mp3", "impact_2.mp3", "riser_1.mp3", "riser_2.mp3",
                     "whoosh_1.mp3", "whoosh_2.mp3", "whoosh_3.mp3"]


def test_missing_key_never_calls_api(env, monkeypatch):
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")
    post, calls = recorder()
    lines = []
    assert lb.build_music_library(per_mood=1, moods=["epic"], yes=True, post=post, out=lines.append) == 2
    assert calls == [] and any("ELEVENLABS_API_KEY" in line for line in lines)


def test_default_post_resolves_requests_at_call_time(env):
    """The env fixture patched requests.post; a builder call without `post` must hit the patch."""
    with pytest.raises(AssertionError, match="real network call"):
        lb.fetch_item(lb.plan_sfx_items(settings.sfx_dir)[0][0], FAKE_KEY, sleep=lambda s: None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_library_builder.py -q --tb=no`
Expected: `ImportError: cannot import name 'library_builder'`.

- [ ] **Step 3: Create `app/cin/library_builder.py`**

```python
"""--build-music-library / --build-sfx-library (spec §8.1, §8.2) via the ElevenLabs API.

Endpoints (verified 2026-10-03):
  POST https://api.elevenlabs.io/v1/music             https://elevenlabs.io/docs/api-reference/music/compose
  POST https://api.elevenlabs.io/v1/sound-generation  https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert
Prices: https://elevenlabs.io/pricing/api (Music $0.15/min, Sound Effects $0.12/min).
Never imported by the render path. Tests always inject `post`."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from app.cin.music_library import GENERATED_DIR, MOODS, MUSIC_EXTENSIONS
from app.config import settings

logger = logging.getLogger(__name__)

API_ROOT = "https://api.elevenlabs.io/v1"
MUSIC_URL = f"{API_ROOT}/music"
SFX_URL = f"{API_ROOT}/sound-generation"
OUTPUT_FORMAT = "mp3_44100_128"        # 192 kbps output is Creator-tier gated
TRACK_SECONDS = 60
SFX_MODEL = "eleven_text_to_sound_v2"
MAX_ATTEMPTS = 3                       # for 429 / 5xx / network errors
MUSIC_TIMEOUT = 300
SFX_TIMEOUT = 120

MOOD_PROMPTS = {
    "chill": "calm lo-fi ambient groove, soft electric piano, warm pads, gentle brushed drums",
    "cinematic": "cinematic documentary underscore, strings and piano, steady pulse, curious and hopeful",
    "dark": "dark suspenseful underscore, low drones, ticking percussion, tense synth pulses",
    "epic": "epic orchestral trailer bed, driving percussion, brass swells, heroic strings",
    "upbeat": "upbeat modern pop instrumental, bright plucks, claps, punchy bass, positive energy",
}
VARIATIONS = (
    "medium tempo around 100 BPM",
    "slightly faster, around 120 BPM",
    "minimal arrangement with more space",
    "fuller arrangement with layered textures",
    "rhythmic and percussive",
)
LOOP_HINT = ("Instrumental background music for a short narrated video. Constant energy from start "
             "to finish, no intro build-up, no ending, no vocals, seamless loop.")

SFX_SPECS = (   # (file stem, prompt, seconds) - spec §8.2: whoosh x3, impact x2, riser x2
    ("whoosh_1", "fast cinematic whoosh transition, air swish, clean", 1.0),
    ("whoosh_2", "short deep whoosh pass-by, smooth, no tail", 0.8),
    ("whoosh_3", "quick bright swish transition sound", 1.2),
    ("impact_1", "deep cinematic impact boom hit with short tail", 1.5),
    ("impact_2", "punchy trailer hit, sub bass thump", 1.2),
    ("riser_1", "tension riser swelling upward, ends abruptly", 2.0),
    ("riser_2", "short synth sweep riser building up, ends on a peak", 2.5),
)


class LibraryAccessError(Exception):
    """401/402/403 from ElevenLabs: key invalid, missing permission, or plan lacks the API."""


@dataclass
class LibraryItem:
    path: Path
    url: str
    payload: dict
    seconds: float
    timeout: int


def _existing_stems(folder: Path) -> set:
    if not folder.is_dir():
        return set()
    return {p.stem for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_EXTENSIONS}


def plan_music_items(music_dir, moods, per_mood: int) -> tuple:
    """(todo, skipped): assets/music/<mood>/generated/<mood>_NN.mp3 for NN in 1..per_mood."""
    todo, skipped = [], []
    for mood in moods:
        folder = Path(music_dir) / mood / GENERATED_DIR
        have = _existing_stems(folder)
        for n in range(1, per_mood + 1):
            stem = f"{mood}_{n:02d}"
            path = folder / f"{stem}.mp3"
            if stem in have:
                skipped.append(path)
                continue
            prompt = f"{MOOD_PROMPTS[mood]}, {VARIATIONS[(n - 1) % len(VARIATIONS)]}. {LOOP_HINT}"
            todo.append(LibraryItem(path, MUSIC_URL, {
                "prompt": prompt, "music_length_ms": TRACK_SECONDS * 1000,
                "model_id": settings.elevenlabs_music_model, "force_instrumental": True,
            }, TRACK_SECONDS, MUSIC_TIMEOUT))
    return todo, skipped


def plan_sfx_items(sfx_dir) -> tuple:
    folder = Path(sfx_dir) / GENERATED_DIR
    have = _existing_stems(folder)
    todo, skipped = [], []
    for stem, text, seconds in SFX_SPECS:
        path = folder / f"{stem}.mp3"
        if stem in have:
            skipped.append(path)
            continue
        todo.append(LibraryItem(path, SFX_URL, {
            "text": text, "duration_seconds": seconds, "prompt_influence": 0.5,
            "loop": False, "model_id": SFX_MODEL,
        }, seconds, SFX_TIMEOUT))
    return todo, skipped


def estimate_cost(items) -> float:
    total = 0.0
    for it in items:
        rate = (settings.cost_elevenlabs_music_per_minute if it.url == MUSIC_URL
                else settings.cost_elevenlabs_sfx_per_minute)
        total += it.seconds / 60.0 * rate
    return round(total, 2)


def _detail(resp) -> str:
    """Human-readable error text from an ElevenLabs error body (never contains the request key)."""
    try:
        d = resp.json().get("detail")
    except Exception:  # noqa: BLE001
        d = None
    if isinstance(d, dict):
        d = d.get("message") or d.get("status") or str(d)
    elif isinstance(d, list):
        d = "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
    text = str(d) if d else (getattr(resp, "text", "") or "")
    return text.strip()[:300]


def fetch_item(item: LibraryItem, api_key: str, *, post: Optional[Callable] = None,
               sleep: Optional[Callable] = None) -> None:
    """Download one item to item.path via a .part file. Raises LibraryAccessError on 401/402/403,
    RuntimeError on any other failure after MAX_ATTEMPTS (429/5xx/network are retried)."""
    post = post or requests.post          # resolved per call so patched requests.post is honoured
    sleep = sleep or time.sleep
    headers = {"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = post(item.url, params={"output_format": OUTPUT_FORMAT}, json=item.payload,
                        headers=headers, timeout=item.timeout)
        except requests.RequestException as e:
            last = f"network error: {type(e).__name__}"
        else:
            if resp.status_code == 200 and resp.content:
                item.path.parent.mkdir(parents=True, exist_ok=True)
                part = item.path.with_name(item.path.name + ".part")
                part.write_bytes(resp.content)
                os.replace(part, item.path)
                return
            if resp.status_code in (401, 402, 403):
                raise LibraryAccessError(
                    f"ElevenLabs refused the request (HTTP {resp.status_code}): {_detail(resp)}. "
                    "Check that ELEVENLABS_API_KEY is valid, that the key has the music / sound-effects "
                    "permission, and that your ElevenLabs plan includes this API (Music needs a paid plan).")
            last = f"HTTP {resp.status_code}: {_detail(resp)}"
            if resp.status_code != 429 and resp.status_code < 500:
                break                       # 400/422 (e.g. a rejected prompt): retrying will not help
        if attempt < MAX_ATTEMPTS:
            sleep(5 * attempt)
    raise RuntimeError(last or "empty response")


def run_library_build(kind: str, todo: list, skipped: list, *, yes: bool = False,
                      input_fn: Callable = input, post: Optional[Callable] = None,
                      sleep: Optional[Callable] = None, out: Callable = print) -> int:
    """estimate -> confirm -> fetch. 0 ok / nothing to do, 1 declined or failures, 2 no key / refused."""
    for p in skipped:
        out(f"  skip (exists): {p.as_posix()}")
    if not todo:
        out(f"{kind}: nothing to generate ({len(skipped)} file(s) already present).")
        return 0
    if not settings.elevenlabs_api_key:
        out("ELEVENLABS_API_KEY is not set in .env; cannot build the library.")
        return 2
    seconds = sum(it.seconds for it in todo)
    out(f"{kind}: {len(todo)} file(s), ~{seconds / 60:.1f} min of audio, estimated ${estimate_cost(todo):.2f} "
        "(ElevenLabs API list price; subscription plans bill credits instead).")
    if not yes:
        try:
            answer = input_fn("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer not in ("y", "yes"):
            out("Cancelled; nothing generated.")
            return 1
    failed = 0
    for i, item in enumerate(todo, 1):
        try:
            fetch_item(item, settings.elevenlabs_api_key, post=post, sleep=sleep)
            out(f"  [{i}/{len(todo)}] wrote {item.path.as_posix()}")
        except LibraryAccessError as e:
            out(str(e))
            return 2
        except Exception as e:  # noqa: BLE001 - one bad prompt must not stop the batch
            failed += 1
            out(f"  [{i}/{len(todo)}] FAILED {item.path.name}: {e}")
    out(f"{kind}: {len(todo) - failed} generated, {failed} failed, {len(skipped)} skipped.")
    return 1 if failed else 0


def build_music_library(*, per_mood: int = 5, moods: Optional[list] = None, **kw) -> int:
    todo, skipped = plan_music_items(settings.music_dir, moods or list(MOODS), per_mood)
    return run_library_build("Music library", todo, skipped, **kw)


def build_sfx_library(**kw) -> int:
    todo, skipped = plan_sfx_items(settings.sfx_dir)
    return run_library_build("SFX library", todo, skipped, **kw)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_library_builder.py -q`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add app/cin/library_builder.py tests/test_library_builder.py
git commit -m "feat: ElevenLabs music and SFX library builders (estimate, confirm, skip existing, clear plan errors)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Builder CLI flags, docs, full verification

**Files:**
- Modify: `main.py` (`parse_args`, `main`)
- Modify: `CLAUDE.md` (Commands block), `.claude/memory.md` (progress note)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_music_library`, `build_sfx_library` (Task 6), `MOODS` (Task 1).
- Produces: CLI `--build-music-library`, `--build-sfx-library`, `--per-mood N` (1–20, default 5), `--moods epic,dark`, `--yes`; `main.parse_moods(text) -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_library_builder_flags():
    import pytest
    args = parse_args(["--build-music-library", "--per-mood", "3", "--moods", "epic, dark", "--yes"])
    assert args.build_music_library is True and args.per_mood == 3
    assert args.moods == ["epic", "dark"] and args.yes is True
    d = parse_args([])
    assert d.build_music_library is False and d.build_sfx_library is False
    assert d.per_mood == 5 and d.moods is None and d.yes is False
    for bad in (["--moods", "epic,jazz"], ["--per-mood", "0"], ["--per-mood", "50"]):
        with pytest.raises(SystemExit):
            parse_args(bad)


def test_main_builders_skip_config_validation(monkeypatch):
    import sys
    import pytest
    import main
    calls = []

    def must_not_validate(*a, **k):
        raise AssertionError("validate_config must not run for library builders")

    monkeypatch.setattr(main, "validate_config", must_not_validate)
    monkeypatch.setattr("app.cin.library_builder.build_sfx_library",
                        lambda **kw: calls.append(("sfx", kw)) or 0)
    monkeypatch.setattr("app.cin.library_builder.build_music_library",
                        lambda **kw: calls.append(("music", kw)) or 1)
    monkeypatch.setattr(sys, "argv", ["main.py", "--build-sfx-library", "--build-music-library",
                                      "--moods", "epic", "--per-mood", "2", "--yes"])
    with pytest.raises(SystemExit) as exit_info:
        main.main()
    assert exit_info.value.code == 1                       # worst of the two exit codes
    assert calls == [("sfx", {"yes": True}), ("music", {"per_mood": 2, "moods": ["epic"], "yes": True})]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cli.py -q --tb=line`
Expected: the two new tests fail (`unrecognized arguments: --build-music-library`).

- [ ] **Step 3: Implement the flags**

In `main.py`, add the import `from app.cin.music_library import MOODS, MUSIC_SOURCES` (replacing the Task 5 import of `MUSIC_SOURCES` alone). Above `def parse_args`, add:

```python
def parse_moods(text: str) -> list:
    moods = [m.strip().lower() for m in text.split(",") if m.strip()]
    unknown = [m for m in moods if m not in MOODS]
    if not moods or unknown:
        raise argparse.ArgumentTypeError(f"unknown mood(s) {unknown or text!r}; choose from {', '.join(MOODS)}")
    return moods


def _per_mood(text: str) -> int:
    n = int(text)
    if not 1 <= n <= 20:
        raise argparse.ArgumentTypeError("--per-mood must be between 1 and 20")
    return n
```

In `parse_args`, after the `--music-source` argument, add:

```python
    parser.add_argument("--build-music-library", action="store_true",
                        help="Generate ~60 s instrumental tracks per mood via ElevenLabs Music "
                             "(prints a cost estimate and asks first)")
    parser.add_argument("--build-sfx-library", action="store_true",
                        help="Generate whoosh x3, impact x2, riser x2 via ElevenLabs Sound Effects")
    parser.add_argument("--per-mood", type=_per_mood, default=5,
                        help="Tracks per mood for --build-music-library (default 5)")
    parser.add_argument("--moods", type=parse_moods, default=None,
                        help=f"Comma-separated moods for --build-music-library (default: {','.join(MOODS)})")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the cost confirmation prompt of the library builders")
```

In `main()`, directly after `args = parse_args()` (before the `--rerender` block) add:

```python
    # Library builders need only ELEVENLABS_API_KEY: handle them before validate_config().
    if args.build_music_library or args.build_sfx_library:
        from app.cin import library_builder
        code = 0
        if args.build_sfx_library:
            code = max(code, library_builder.build_sfx_library(yes=args.yes))
        if args.build_music_library:
            code = max(code, library_builder.build_music_library(per_mood=args.per_mood, moods=args.moods,
                                                                 yes=args.yes))
        sys.exit(code)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_cli.py -q`
Expected: all pass.

- [ ] **Step 5: Docs**

In `CLAUDE.md`, after the `--rerender` example line (`python main.py --rerender output/<job> --pacing fast --subtitle-style neon_glow --color-grade tech`) add:

```bash
python main.py --rerender output/<job> --music-source generated   # re-pick music from another pool

# Music / SFX (shot editor). Libraries: assets/music/<mood>/ (yours), assets/music/<mood>/generated/,
# assets/sfx/ (yours: whoosh*, impact*, riser*), assets/sfx/generated/. LRU history: data/music_usage.json
python main.py --auto --music-source mine    # mine | generated | any (default) | none
python main.py --build-sfx-library           # ElevenLabs Sound Effects, ~$0.02, asks first
python main.py --build-music-library --per-mood 5 --moods epic,dark   # ElevenLabs Music, $0.15/track, asks first (--yes skips)
```

In `.claude/memory.md`, append under the shot-editor progress section:

```markdown
- Phase C (music/SFX/ducking/voice polish) implemented per docs/superpowers/plans/2026-10-02-shot-based-editor-phase-c.md.
  Libraries are empty until the user adds tracks or runs the builders (ElevenLabs Music needs a paid plan).
```

- [ ] **Step 6: Full verification**

1. Run: `.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py --tb=no -rf`
   Expected: exactly the 12 baseline failures listed in Global Constraints; every new test passes.
2. Builder dry check without spending (answers "n"; no request is sent before confirmation):
   `echo n | .venv/Scripts/python.exe main.py --build-music-library --moods epic --per-mood 1`
   Expected: one line with `estimated $0.15`, then `Cancelled; nothing generated.`, exit code 1 — or `ELEVENLABS_API_KEY is not set` and exit code 2 if the key is absent. Do not run with `--yes`.
3. Offline audio check on a real job: build a throwaway library with ffmpeg tones in a temp folder and re-render the newest existing job (zero API calls):

```bash
T=$(mktemp -d)
mkdir -p "$T/music/cinematic" "$T/sfx"
ffmpeg -v error -f lavfi -i "sine=frequency=330:duration=45" -ac 2 "$T/music/cinematic/tone.wav"
ffmpeg -v error -f lavfi -i "anoisesrc=d=0.8:a=0.3" -ac 2 "$T/sfx/whoosh_test.wav"
JOB=$(ls -d output/*/sources 2>/dev/null | tail -1 | xargs -r dirname)
echo "job: $JOB"
[ -n "$JOB" ] && MUSIC_DIR="$T/music" SFX_DIR="$T/sfx" .venv/Scripts/python.exe main.py --rerender "$JOB" --music-source mine
```

   Expected (if a job exists): `Re-rendered: .../final.mp4`; `sources/shot_plan.json` has `"music": {"file": ".../tone.wav", ...}` and whoosh entries; `run_report.json` loudness I within −15..−13 and `platform_safe.ok` true. Listen to `final.mp4`: the tone dips under speech and rises in pauses. If no job folder exists, skip this item and say so in the hand-off. `MUSIC_DIR`/`SFX_DIR` env vars override settings for that process only; they do not touch `.env`.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_cli.py CLAUDE.md .claude/memory.md
git commit -m "feat: --build-music-library / --build-sfx-library CLI flags; docs for Phase C audio

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review (done while writing)

**Spec coverage:**
- §8.1 layout, moods, `music_source` values/default, LRU in `data/music_usage.json`, `music_missing` → Task 1 (listing, LRU, settings), Task 5 (`pick_music`, warnings). `--build-music-library [--per-mood 5] [--moods epic,dark]`, ≈60 s instrumental loop-friendly, estimate + confirm unless `--yes` → Tasks 6–7 (25 tracks = $3.75 asserted).
- §8.2 SFX builder (whoosh ×3, impact ×2, riser ×2, `/v1/sound-generation`, `assets/sfx/generated/`), user files in `assets/sfx/`, placement rules, rotation, `enable_sfx` → Tasks 2, 5, 6.
- §8.3 voice polish string, ducking levels/timings, fades, 1.0 s equal-power loop, 48 kHz WAV in the job folder → Tasks 3–5; Phase A loudnorm/mux unchanged (asserted in `test_render_job_fills_plan_music_and_sfx`).
- §6.6 `sfx` / `music` (`file`, `duck_windows`) filled and saved → Task 5 (`render_job`, post-render save in `_run_shot_editor`, rerender save already after render).
- §9.3 `--music-source` on `--rerender` → Task 5. §11 `music_source` option in `Settings`, CLI, `run_pipeline`, `RenderOptions` → Tasks 1, 5 (web/scheduler = Phase D).
- §12 "LRU music selection; SFX placement" unit tests → Tasks 1, 2.

**Placeholder scan:** none; every code step carries code, every test step carries test code.

**Type consistency:** `mix_tracks` sfx items = `place_sfx` entries + `"path"` (Task 4 ↔ Task 5); `SfxFile(path, kind, duration)` (Task 2 ↔ `sfx_pool` Task 5); `select_track(..., accept=)` (Task 1 ↔ Task 5); `pick_music(options, report, keep=None)` keeps the Phase A call shape; `rerender_job(..., music_source=)` matches `main()` and the updated CLI test; `MUSIC_SOURCES` used by `Settings` Literal, `list_tracks`, `run_pipeline`, `--music-source`.

**Known limits (accepted):** LRU selection is atomic within one process only; two separate processes can rarely pick the same track (atomic rename prevents file corruption). Music track RMS normalisation uses the whole looped bed, so a track with a long quiet intro sits slightly hot after it. Library builds are not written to `cost_log.json`.
