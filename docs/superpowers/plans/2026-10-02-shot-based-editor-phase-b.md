# Shot-Based Editor — Phase B (Captions + Fonts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Phase A karaoke adapter in the shot-editor path with speech-timed caption groups rendered from bundled OFL fonts inside the cross-platform safe zone, plus a top-band hook headline for the first 2.5 s.

**Architecture:** Three new units. `app/fonts.py` loads preset font *files* from `assets/fonts/` (Montserrat is a variable font; its weight axis is set per instance with Pillow, no new dependency). `app/cin/caption_groups.py` is pure: aligned script tokens → 1–3-word `CaptionGroup`s, and hook text → `hook_headline` dict. `app/cin/captions.py` lays each group out once on a single line that fits its box, rasterizes it once per highlight state, and alpha-composites it inside `ShotRenderer.frame_at`. `render_job` builds the layer and records `font_fallback`; `main.py` fills `plan.hook_headline`; `rebuild_plan` carries it across `--rerender`. The `--classic` editor keeps `VideoEditor._create_karaoke_clips` and only gains the bundled fonts.

**Tech Stack:** Python 3.14 venv (Docker 3.12), Pillow 11.3 (FreeType 2.13.3, variable-font axes via `FreeTypeFont.set_variation_by_axes`), NumPy, MoviePy 2.1.2, ffmpeg (PATH, imageio-ffmpeg fallback), pytest 9.

**Spec:** `docs/superpowers/specs/2026-10-02-shot-based-editor-design.md` (Phase B = §13 B; requirements in §7, report codes in §10, render test in §12)

## Global Constraints

- Run everything with the venv from the repo root in Git Bash: `.venv/Scripts/python.exe -m pytest ...`.
- Full-suite runs use `--ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py` (they fail at import for missing `apscheduler`/`fastapi` — out of scope).
- **Baseline (measured 2026-10-03 on `feat/shot-editor-phase-a` @ `93d7223`, clean tracked tree): 314 passed, 12 failed, all pre-existing and out of scope** — `test_local_image_gen.py::test_generate_creates_image`, `test_trend_scout.py::test_fetch_youtube_trending_with_api_key`, `test_trends.py::TestTrendScorer::{test_score_bounds,test_breakdown_keys,test_blocklist_blocks,test_recency_decay,test_niche_match_scoring}`, `test_trends.py::TestOrchestratorResilience::test_continues_on_source_failure`, `test_uploader.py::TestYouTubeUploader::{test_upload_missing_video_raises,test_auth_missing_secrets_raises,test_get_authenticated_service_no_token_raises,test_upload_success}`. (`tests/test_trends.py` is untracked; its 6 failures still count.) Do not chase them. "Full suite green" in this plan means: only these 12 fail. (An earlier run showed 313 passed / 13 failed: the 13th, `test_cin_editor.py::test_locked_final_swap_writes_timestamped_file_and_warns`, came from another session committing `app/cin/editor.py` changes mid-run; the re-run at `93d7223` is the baseline above.)
- Never print, paste or commit `.env` values. No test reads `.env`; tests that build `Settings` pass `_env_file=None`.
- Code must also run on Python 3.12 (Docker): no PEP 695 syntax; `from __future__ import annotations` is fine.
- **No new dependencies.** `fontTools` is not installed and is not added; `cv2` stays optional. Pillow's bundled FreeType handles the variable font on Windows (measured); the Linux wheels in the `python:3.12-slim` image are expected to behave the same but this is not yet measured — see the next line.
- **Linux parity:** the variable-font weight axis depends on Pillow's bundled FreeType. It is verified on Windows by `tests/test_fonts.py::test_montserrat_weight_axis_is_applied_per_instance` (fails loudly, never renders Thin silently); Task 6 Step 5 repeats the check inside the `python:3.12-slim` Docker image before the first VPS deploy.
- **Tests make zero network calls.** The font download in Task 1 is a one-time implementer step with `curl`; the fonts are committed and tests only read them from disk.
- Spec §7 values (verbatim): fonts bundled in `assets/fonts/` (Montserrat ExtraBold, Anton, Bebas Neue), presets reference font files, not system names; groups of **1–3 words** from aligned script tokens; break at punctuation and gaps **> 0.25 s**; never split a number or capitalized name sequence; active word in the preset's active colour scaled **1.0 → `active_scale` over 80 ms**; `bottom` captions centred at **y ≈ 1325 (range 1250–1400)**, block never below **y = 1410** or right of **x = 990**; captions from frame one (no suppression window); hook headline in the top band **y ≈ 250–450 for [0, 2.5 s]**, text = the hook's first sentence if **≤ 8 words**, otherwise omitted; each group rasterized once per highlight state and composited inside the frame function; `bold_impact`, `clean_minimal`, `neon_glow`, `fire` keep their colours and stay selectable; a missing font logs a warning and is recorded as `font_fallback` in the run report.
- Frame size is 1080×1920; all box coordinates below are in that space, end-exclusive `(x0, y0, x1, y1)`.
- Line numbers cite the tree at `93d7223`. Once an earlier task edits a file, the quoted text anchors in each step are authoritative.
- A parallel Phase C plan (`docs/superpowers/plans/2026-10-02-shot-based-editor-phase-c.md`, untracked) also edits `render_job` (the `"mix"` stage) and `rebuild_plan` (it carries `plan.music`). Whichever phase lands second keeps both sides: `rebuild_plan` must copy both `hook_headline` and `music` from the old plan.
- Commit only the files each task lists (the working tree has many unrelated untracked files). End every commit message with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not commit this plan file.

**Phase B decisions and deviations (read before starting):**
- **Montserrat ExtraBold comes from the variable font.** google/fonts no longer ships static Montserrat (`ofl/montserrat/static/Montserrat-ExtraBold.ttf` returns 404) and `fontTools` is not installed, so we bundle `ofl/montserrat/Montserrat[wght].ttf` and set the weight axis with Pillow. Measured: at 75 px, `"WILSDORF"` is 438 px wide with the axis at 800 — identical to the upstream static `Montserrat-ExtraBold.ttf` (438 px) and wider than the default instance (417 px). Two gotchas the code handles: the axis is per `FreeTypeFont` instance, so `load_font` applies it on every load at every size; and `getname()` keeps returning `('Montserrat', 'Thin')` after the axis is set, so tests pin the weight by glyph width, never by name. The file is saved as `Montserrat-Variable.ttf` because `[wght]` is a glob pattern in Git Bash and Docker shells.
- **Preset → font file:** `bold_impact` → `Montserrat-Variable.ttf` @ 800 (ExtraBold); `clean_minimal` → `Montserrat-Variable.ttf` @ 600 (SemiBold, the clean face); `neon_glow` → `BebasNeue-Regular.ttf`; `fire` → `Anton-Regular.ttf`. Colours, sizes, `active_scale`, strokes and `position` are unchanged. The preset key `"font"` (system name) is replaced by `"font_file"` + `"font_weight"`.
- **`center` "keeps its current position" cannot be honoured literally:** no code reads `preset["position"]` — every style, `clean_minimal` included, is placed at `("center", self.HEIGHT - 350)` = y 1570 (`app/video_editor.py:478`, preset at `app/subtitle_styles.py:32`). In the shot editor `center` therefore means what the preset name says: the caption block is centred on the frame's vertical centre (box y 886–1034). The classic editor's placement is unchanged.
- **Highlight state = (active word, ramp step).** At 30 fps the 80 ms ramp spans 2–3 frames with intermediate sizes, so the ramp is quantized into `RAMP_STEPS = 4` steps (scale = 1 + (active_scale − 1)·step/4). A 3-word group is rasterized at most 3 × 5 = 15 times, each state exactly once (cached; the cache is dropped when the next group starts).
- **Safe-zone boxes carry codec margin.** Bottom box `(94, 1254, 986, 1402)` (centre y = 1328), centre box `(94, 886, 986, 1034)`, headline box `(94, 258, 986, 442)`. The 4–8 px inside the spec's numbers absorb H.264 4:2:0 chroma bleed, so decoded `final.mp4` frames also pass the spec's 1250–1410 / x ≤ 990 check. Captions are one line: two lines of `fire` (80 px × 1.25 + 5 px stroke) do not fit the 148 px box. The layout shrinks the font until `base width + (active_scale − 1) × widest word + 2 × stroke` fits the width and the active-size ink (stroke included) fits the height; each gap between words reserves half of the larger neighbour's growth so the scaled word never touches its neighbours. Every sprite is clipped to its box as a hard guarantee.
- **Group display window:** group *i* is shown from `0.0` (first group — "from frame one") or its first word's `t0`, until the next group's `t0` or its last word's `t1 + 0.4 s`, whichever is first. The active word is the last word whose `t0 ≤ t` (the first word before it starts).
- **Atomic units are capped at 3 tokens.** A capitalized run ("Hans Wilsdorf", "ELON MUSK") or a number run (a token with a digit followed by `million`/`percent`/… — "1 million", "40 percent"; "$1,000,000" is already one script token) never straddles two groups. A run longer than 3 tokens ("Martin Luther King Jr", an all-caps sentence) is split after 3 tokens, so no group ever exceeds 3 words. Sentence-initial capitals are not excluded: "A German" joining is harmless, while excluding them would split "Hans Wilsdorf" at a sentence start.
- **Characters the font cannot draw are dropped** (emoji, CJK in a Latin font): they rasterize as the font's `.notdef` box, which `drawable()` detects by comparing glyph masks. A word that empties is skipped; a group that empties is not shown. Accented Latin ("CAFÉ") is kept.
- **Hook headline:** set in `main.py` from `script.hook` right after `build_shot_plan` — not inside `build_shot_plan`, which stays hook-agnostic (`tests/test_cin_segments.py:62` pins `hook_headline is None` for the planner). Drawn in the preset's font, upper-case, white with a black stroke, up to 2 lines, shrunk to fit the band; hidden from `t1` on. A trailing full stop is dropped, `?`/`!` kept. The headline is drawn even when `enable_subtitles` is false (it is a title, not a caption). `rebuild_plan` copies it from the saved plan; Phase A jobs have `null` and re-render without one.
- **Inactive colours keep their alpha** (e.g. `#FFFFFF80`): unchanged look, semi-transparent inactive words.
- `caption_overlays` (`app/cin/renderer.py:166-176`) and the `overlays` parameter of `ShotRenderer.render` are deleted; the shot editor no longer uses MoviePy `ImageClip`s for captions.
- Out of scope for B: music/SFX libraries, ducking, voice polish (Phase C); web form / scheduler / generator-worker plumbing and `/api/generate` warnings (Phase D); script changes and a dedicated `hook_headline` field (sub-project 2). `font_fallback` is already in `WARNING_CODES` (`app/cin/report.py:19`) — no change there.

## Review Focus

1. **A word too long for the width** ("Supercalifragilisticexpialidocious", a URL, a German compound): the font shrinks until the line fits, and the right edge stays ≤ x 990 even at the frame where the *last* word is at full highlight scale — pinned in Task 3 (`test_layout_fits_box_including_highlight_growth`, `test_short_group_keeps_preset_size_long_word_shrinks`) and Task 4 (`test_bottom_captions_stay_in_safe_zone_at_peak_highlight`).
2. **Numbers and money** ("$1,000,000", "1 million", "40 percent" where Whisper gave both tokens the same `t0`): one group, every glyph drawn, highlight never jumps backwards — pinned in Task 2 (`test_number_runs_never_split`, `test_money_token_is_one_word`), Task 3 (`test_drawable_uppercases_and_drops_missing_glyphs`) and Task 4 (`test_equal_start_times_never_go_backwards`).
3. **All-caps names and all-caps scripts** ("ELON MUSK", "Martin Luther King Jr", "THIS IS THE BIGGEST SECRET IN HISTORY"): names stay together, and an all-caps sentence never becomes one giant group — pinned in Task 2 (`test_all_caps_name_stays_together`, `test_long_units_are_capped_at_three_words`).
4. **Emoji and non-ASCII in narration** ("café", "so 🔥 hot"): accented letters render, emoji vanish instead of drawing tofu boxes, and an emoji-only word drops out without breaking the highlight index — pinned in Task 3 (`test_drawable_uppercases_and_drops_missing_glyphs`, `test_word_with_no_drawable_glyphs_is_dropped_from_layout`).
5. **A missing font file or nothing to caption** (fonts not copied into the Docker image, `--no-subtitles`, an empty caption list): a system font is used and `font_fallback` is reported once, the headline still draws with no captions, and nothing at all means no layer — pinned in Task 1 (`test_missing_font_file_falls_back_with_flag`, `test_classic_renderer_flags_missing_font`), Task 4 (`test_missing_font_records_font_fallback`, `test_empty_caption_list_still_draws_headline`, `test_build_layer_none_when_nothing_to_draw`) and Task 5 (`test_render_job_reports_missing_caption_font`).

## File Map

| File | Status | Responsibility |
|---|---|---|
| `assets/fonts/{Montserrat-Variable,Anton-Regular,BebasNeue-Regular}.ttf`, `assets/fonts/OFL-{Montserrat,Anton,BebasNeue}.txt` | create | bundled OFL fonts + licences |
| `app/fonts.py` | create | `load_font(file, size, weight) -> (font, fell_back)` |
| `app/subtitle_styles.py` | modify | presets reference font files; `SubtitleRenderer` loads through `app.fonts` |
| `app/cin/caption_groups.py` | create | `CaptionWord`, `CaptionGroup`, `group_captions`, `hook_headline_text`, `make_hook_headline` (pure) |
| `app/cin/shot_plan.py` | modify | re-export caption dataclasses; `build_shot_plan` uses `group_captions` |
| `app/cin/captions.py` | create | `CaptionStyle`, `drawable`, `layout_line`, `CaptionLayer`, `build_caption_layer` |
| `app/cin/renderer.py` | modify | `captions=` kwarg, composite in `frame_at`; delete `caption_overlays` and `render(overlays)` |
| `app/cin/editor.py` | modify | `render_job` builds the layer (`font_fallback`); `rebuild_plan` keeps `hook_headline` |
| `main.py` | modify | `plan.hook_headline = make_hook_headline(script.hook, plan.duration)` |
| `tests/test_fonts.py`, `tests/test_cin_caption_groups.py`, `tests/test_cin_captions.py`, `tests/test_cin_captions_render.py` | create | tests |
| `tests/test_cin_shot_plan.py`, `tests/test_pipeline.py` | modify | one test each |
| `CLAUDE.md`, `.claude/memory.md` | modify | fonts note, progress |

## Task Order and Dependencies

1 → 3 → 4 → 5 → 6. 2 is independent of 1 and can run in parallel with it; 4 needs 2 (`CaptionGroup`); 5 needs 2 and 4. Task 6 needs everything.

`render`-marked tests encode real 1080×1920 frames (≈ 8 s each for the new one on the dev box). They run by default; skip them with `-m "not render"`.

---

### Task 1: Bundled OFL fonts, font loader, presets reference files

**Files:**
- Create: `assets/fonts/Montserrat-Variable.ttf`, `assets/fonts/Anton-Regular.ttf`, `assets/fonts/BebasNeue-Regular.ttf`, `assets/fonts/OFL-Montserrat.txt`, `assets/fonts/OFL-Anton.txt`, `assets/fonts/OFL-BebasNeue.txt`
- Create: `app/fonts.py`
- Modify: `app/subtitle_styles.py:7` (imports), `:16`, `:27`, `:39`, `:50` (preset font keys), `:88-104` (`__init__` font loading + `_load_font`), `:145-146` (shrink path)
- Test: `tests/test_fonts.py` (create)

**Interfaces:**
- Produces: `app.fonts.FONTS_DIR: Path`; `app.fonts.load_font(file: str, size: int, weight: Optional[int] = None) -> tuple[ImageFont.FreeTypeFont, bool]` (second item `True` = fell back to a system font); `SUBTITLE_PRESETS[name]["font_file"]: str` and `["font_weight"]: Optional[int]`; `SubtitleRenderer.font_fallback: bool`.

- [ ] **Step 1: Download the fonts and licences (one-time; the only network step in this plan)**

Run from the repo root (Git Bash):

```bash
mkdir -p assets/fonts
curl -fsSL -o assets/fonts/Montserrat-Variable.ttf "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf"
curl -fsSL -o assets/fonts/Anton-Regular.ttf       "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf"
curl -fsSL -o assets/fonts/BebasNeue-Regular.ttf   "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf"
curl -fsSL -o assets/fonts/OFL-Montserrat.txt      "https://github.com/google/fonts/raw/main/ofl/montserrat/OFL.txt"
curl -fsSL -o assets/fonts/OFL-Anton.txt           "https://github.com/google/fonts/raw/main/ofl/anton/OFL.txt"
curl -fsSL -o assets/fonts/OFL-BebasNeue.txt       "https://github.com/google/fonts/raw/main/ofl/bebasneue/OFL.txt"
sha256sum assets/fonts/*
```

Expected (verified 2026-10-03; all six URLs returned HTTP 200):

```
a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab *assets/fonts/Anton-Regular.ttf
08e4623805102d819f58601e46e345648846075e363b2ceb23313c2d1c83ec73 *assets/fonts/BebasNeue-Regular.ttf
0f7b311b2f3279e4eef9b2f968bcdbab6e28f4daeb1f049f4f278a902bcd82f7 *assets/fonts/Montserrat-Variable.ttf
ee67e6ee22790b7929f1a3769ca2801d565c64b5a9096942c1adf5596de9c9e4 *assets/fonts/OFL-Anton.txt
72082f6cb4d04be2ecf7cc7d9e1e7d73787f0af8a5a278a47cade70c16b78341 *assets/fonts/OFL-BebasNeue.txt
8b7141c03fa4f8d44e6345d5d4931709290f0f67875e452e95ac1fd3a027802e *assets/fonts/OFL-Montserrat.txt
```

Sizes: 744 936, 170 812, 61 400 bytes for the three `.ttf`. If a hash differs, upstream updated the file: keep it only if Step 5's tests pass, and put the new hash in the commit message. Never fetch fonts from a test.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_fonts.py`:

```python
"""Bundled OFL fonts (spec §7): presets reference files, a missing file falls back and says so."""
import numpy as np
import pytest

from app.fonts import FONTS_DIR, load_font
from app.subtitle_styles import SUBTITLE_PRESETS, SubtitleRenderer

BUNDLED = ("Montserrat-Variable.ttf", "Anton-Regular.ttf", "BebasNeue-Regular.ttf")
LICENSES = ("OFL-Montserrat.txt", "OFL-Anton.txt", "OFL-BebasNeue.txt")


def test_bundled_fonts_and_licenses_are_present():
    for name in BUNDLED + LICENSES:
        assert (FONTS_DIR / name).is_file(), name
    for name in LICENSES:
        assert "SIL Open Font License" in (FONTS_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("file", BUNDLED)
def test_bundled_fonts_load_without_fallback(file):
    font, fell_back = load_font(file, 75)
    assert fell_back is False
    assert font.getbbox("WILSDORF")[2] > 150


def test_montserrat_weight_axis_is_applied_per_instance():
    """getname() still says 'Thin' after set_variation_by_axes: pin the weight by glyph width."""
    thin, _ = load_font("Montserrat-Variable.ttf", 75, 100)
    extra_bold, _ = load_font("Montserrat-Variable.ttf", 75, 800)
    other_size, _ = load_font("Montserrat-Variable.ttf", 150, 800)
    assert extra_bold.getbbox("WILSDORF")[2] - thin.getbbox("WILSDORF")[2] >= 15
    assert other_size.getbbox("WILSDORF")[2] >= 2 * extra_bold.getbbox("WILSDORF")[2] - 4


def test_missing_font_file_falls_back_with_flag(caplog):
    with caplog.at_level("WARNING", logger="app.fonts"):
        font, fell_back = load_font("Nope-Regular.ttf", 60)
    assert fell_back is True
    assert font.getbbox("ABC")[2] > 0
    assert "Nope-Regular.ttf" in caplog.text


def test_presets_reference_bundled_files_and_keep_colours():
    assert {k: (v["font_file"], v["font_weight"]) for k, v in SUBTITLE_PRESETS.items()} == {
        "bold_impact": ("Montserrat-Variable.ttf", 800),
        "clean_minimal": ("Montserrat-Variable.ttf", 600),
        "neon_glow": ("BebasNeue-Regular.ttf", None),
        "fire": ("Anton-Regular.ttf", None),
    }
    colours = {k: (v["active_color"], v["inactive_color"]) for k, v in SUBTITLE_PRESETS.items()}
    assert colours == {"bold_impact": ("#FFFF00", "#FFFFFF80"), "clean_minimal": ("#FFFFFF", "#FFFFFF60"),
                       "neon_glow": ("#00FF88", "#FFFFFF40"), "fire": ("#FF4500", "#FFD70080")}
    assert all("font" not in v for v in SUBTITLE_PRESETS.values())   # no system font names left


def test_classic_renderer_uses_bundled_font_including_shrink_path():
    r = SubtitleRenderer(style="fire")
    assert r.font_fallback is False and r._font.getname()[0] == "Anton"
    wide = r.render_subtitle_frame(["Supercalifragilisticexpialidocious", "antidisestablishmentarianism"], 0)
    assert isinstance(wide, np.ndarray) and wide.shape[1] == 1080


def test_classic_renderer_flags_missing_font(monkeypatch):
    monkeypatch.setitem(SUBTITLE_PRESETS["bold_impact"], "font_file", "Gone.ttf")
    r = SubtitleRenderer(style="bold_impact")
    assert r.font_fallback is True
    assert r.render_subtitle_frame(["still", "renders"], 1).shape[2] == 4
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fonts.py -q -p no:cacheprovider`
Expected: `1 error` during collection — `ModuleNotFoundError: No module named 'app.fonts'`.

- [ ] **Step 4: Implement `app/fonts.py` and switch the presets**

Create `app/fonts.py`:

```python
"""Bundled OFL caption fonts (spec §7). Presets name a file in assets/fonts/, never a system font,
so Windows and the Linux VPS rasterize identically. A missing or unreadable file falls back to a
system font and reports fell_back=True (the shot editor records it as font_fallback)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import ImageFont

logger = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
SYSTEM_FALLBACKS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # Docker image: fonts-dejavu-core
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",                                             # Windows
    "arial.ttf",
)


def font_path(file: str) -> Path:
    return FONTS_DIR / file


def system_fallback(size: int) -> ImageFont.ImageFont:
    for name in SYSTEM_FALLBACKS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def load_font(file: str, size: int, weight: Optional[int] = None):
    """(font, fell_back). weight sets the 'wght' axis of a variable font (Montserrat-Variable.ttf).
    The axis is per FreeTypeFont instance, so it is applied on every load, at every size.
    Note: getname() keeps reporting the default instance ("Thin") after the axis is set."""
    size = max(1, int(size))
    path = font_path(file)
    try:
        font = ImageFont.truetype(str(path), size)
    except OSError:
        logger.warning("Caption font %s not found or unreadable; using a system font", path)
        return system_fallback(size), True
    if weight is not None:
        try:
            font.set_variation_by_axes([weight])
        except (OSError, AttributeError) as e:   # not variable / FreeType built without MM support
            logger.warning("Cannot set weight %s on %s (%s); using a system font", weight, path, e)
            return system_fallback(size), True
    return font, False
```

In `app/subtitle_styles.py`:

1. After `from PIL import Image, ImageDraw, ImageFont` (line 7) add a blank line and `from app.fonts import load_font`.
2. Replace the four `"font": ...` lines (and, for `neon_glow`/`fire`, keep the following `"font_size"` line unchanged):

```python
    "bold_impact": {
        "active_color": "#FFFF00",
        "inactive_color": "#FFFFFF80",
        "font_file": "Montserrat-Variable.ttf",
        "font_weight": 800,
        "font_size": 75,
```

```python
    "clean_minimal": {
        "active_color": "#FFFFFF",
        "inactive_color": "#FFFFFF60",
        "font_file": "Montserrat-Variable.ttf",
        "font_weight": 600,
        "font_size": 60,
```

```python
    "neon_glow": {
        "active_color": "#00FF88",
        "inactive_color": "#FFFFFF40",
        "font_file": "BebasNeue-Regular.ttf",
        "font_weight": None,
        "font_size": 70,
```

```python
    "fire": {
        "active_color": "#FF4500",
        "inactive_color": "#FFD70080",
        "font_file": "Anton-Regular.ttf",
        "font_weight": None,
        "font_size": 80,
```

3. Replace lines 88-104 (from `self._font = self._load_font(self.preset["font"], ...` through the end of the old `_load_font`, the line `return ImageFont.load_default()`) with:

```python
        self.font_fallback = False
        self._font = self._load_font(self.preset["font_size"])
        active_size = int(self.preset["font_size"] * self.preset.get("active_scale", 1.0))
        self._active_font = self._load_font(active_size)

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        """The preset's bundled font file (app.fonts); a missing file falls back to a system font."""
        font, fell_back = load_font(self.preset["font_file"], size, self.preset.get("font_weight"))
        self.font_fallback = self.font_fallback or fell_back
        return font
```

4. In the shrink path (lines 145-146) replace

```python
            scaled_font = self._load_font(self.preset["font"], scaled_font_size)
            scaled_active_font = self._load_font(self.preset["font"], scaled_active_size)
```

with

```python
            scaled_font = self._load_font(scaled_font_size)
            scaled_active_font = self._load_font(scaled_active_size)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_fonts.py tests/test_subtitle_styles.py tests/test_video_editor.py -q -p no:cacheprovider`
Expected: all pass (`14 passed` for the first two files plus the existing `test_video_editor.py` count, no failures).

- [ ] **Step 6: Commit**

```bash
git add assets/fonts/Montserrat-Variable.ttf assets/fonts/Anton-Regular.ttf assets/fonts/BebasNeue-Regular.ttf \
        assets/fonts/OFL-Montserrat.txt assets/fonts/OFL-Anton.txt assets/fonts/OFL-BebasNeue.txt \
        app/fonts.py app/subtitle_styles.py tests/test_fonts.py
git commit -m "feat: bundle OFL caption fonts; presets reference font files

Montserrat (variable, wght 800/600 via Pillow), Anton, Bebas Neue from google/fonts with OFL texts.
Missing files fall back to a system font and are flagged.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Caption grouping and hook headline text (pure)

**Files:**
- Create: `app/cin/caption_groups.py`
- Modify: `app/cin/shot_plan.py:16` (import), `:139-155` (delete `CaptionWord`/`CaptionGroup`), `:355-365` (delete `_captions`), `:419` (`captions=`)
- Test: `tests/test_cin_caption_groups.py` (create), `tests/test_cin_shot_plan.py` (add one test after `test_captions_use_script_spelling_in_groups_of_three`, line 162)

**Interfaces:**
- Consumes: `app.cin.align.AlignedToken` fields `text, t0, t1, sentence_end, comma`.
- Produces: `app.cin.caption_groups.CaptionWord(text: str, t0: float, t1: float)`, `CaptionGroup(t0: float, t1: float, words: list[CaptionWord])` with `.to_json()` (same JSON as Phase A); `group_captions(tokens: list) -> list[CaptionGroup]`; `hook_headline_text(hook: Optional[str]) -> Optional[str]`; `make_hook_headline(hook: Optional[str], duration: float) -> Optional[dict]` returning `{"text": str, "t0": 0.0, "t1": min(2.5, duration)}`; constants `MAX_WORDS = 3`, `GAP_BREAK = 0.25`, `HOOK_MAX_WORDS = 8`, `HOOK_SECONDS = 2.5`. `app.cin.shot_plan` re-exports `CaptionWord`, `CaptionGroup`, `group_captions`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_caption_groups.py`:

```python
"""Caption grouping + hook headline text (spec §7). Pure: aligned tokens in, groups out."""
from app.cin.align import AlignedToken
from app.cin.caption_groups import (GAP_BREAK, group_captions, hook_headline_text, make_hook_headline)
from tests.conftest import fixture_alignment


def toks(spec: str, step: float = 0.3, gap: float = 0.02):
    """'Hans Wilsdorf founded, a' -> AlignedTokens 0.3 s long with 0.02 s gaps; a trailing
    '.'/'!'/'?' sets sentence_end, ','/';' sets comma. '|' inserts a 0.5 s pause."""
    out, t = [], 0.0
    for raw in spec.split():
        if raw == "|":
            t += 0.5
            continue
        text = raw.rstrip(".,!?;")
        out.append(AlignedToken(text, round(t, 3), round(t + step, 3), True,
                                raw.endswith((".", "!", "?")), raw.endswith((",", ";"))))
        t += step + gap
    return out


def texts(groups):
    return [" ".join(w.text for w in g.words) for g in groups]


def test_groups_hold_one_to_three_words_and_keep_timing():
    groups = group_captions(toks("one two three four five six seven"))
    assert texts(groups) == ["one two three", "four five six", "seven"]
    assert groups[0].t0 == 0.0 and groups[0].t1 == groups[0].words[-1].t1
    assert all(w.t0 < w.t1 for g in groups for w in g.words)       # real per-word timing, not an even split


def test_break_after_sentence_end_and_comma():
    assert texts(group_captions(toks("It sank. Then, it rose again"))) == ["It sank", "Then", "it rose again"]


def test_break_at_gap_longer_than_quarter_second():
    assert texts(group_captions(toks("wait for | it now"))) == ["wait for", "it now"]
    tight = toks("a b c")
    tight[1].t0 = tight[0].t1 + GAP_BREAK          # exactly 0.25 s is not a break
    tight[1].t1 = tight[1].t0 + 0.3
    tight[2].t0, tight[2].t1 = tight[1].t1 + 0.02, tight[1].t1 + 0.3
    assert texts(group_captions(tight)) == ["a b c"]


def test_name_runs_never_split():
    assert texts(group_captions(toks("a German orphan named Hans Wilsdorf founded it"))) == \
        ["a German orphan", "named Hans Wilsdorf", "founded it"]


def test_all_caps_name_stays_together():
    assert texts(group_captions(toks("then ELON MUSK said no"))) == ["then ELON MUSK", "said no"]


def test_number_runs_never_split():
    assert texts(group_captions(toks("Rolex makes about 1 million watches"))) == \
        ["Rolex makes about", "1 million watches"]
    assert texts(group_captions(toks("sell for 40 percent above retail"))) == \
        ["sell for", "40 percent above", "retail"]


def test_money_token_is_one_word():
    assert texts(group_captions(toks("it sold for $1,000,000 in 1999."))) == ["it sold for", "$1,000,000 in 1999"]


def test_long_units_are_capped_at_three_words():
    """A 4-word name or an all-caps sentence must not become one oversized group."""
    assert texts(group_captions(toks("Martin Luther King Jr spoke"))) == ["Martin Luther King", "Jr spoke"]
    shouting = group_captions(toks("THIS IS THE BIGGEST SECRET IN HISTORY"))
    assert all(1 <= len(g.words) <= 3 for g in shouting)
    assert sum(len(g.words) for g in shouting) == 7


def test_empty_token_list_gives_no_groups():
    assert group_captions([]) == []


def test_rolex_fixture_groups():
    a = fixture_alignment("words_rolex_40s.json")
    groups = group_captions(a.tokens)
    flat = [w.text for g in groups for w in g.words]
    assert flat == [t.text for t in a.tokens]                       # nothing dropped or reordered
    assert all(1 <= len(g.words) <= 3 for g in groups)
    joined = texts(groups)
    assert "named Hans Wilsdorf" in joined
    assert any(j.startswith("1 million") for j in joined)
    assert any("40 percent" in j for j in joined)
    assert any(j.endswith("English Channel") for j in joined)
    i = 0
    for g in groups:                                                # punctuation only ever ends a group
        inner = a.tokens[i:i + len(g.words) - 1]
        assert not any(t.sentence_end or t.comma for t in inner), texts([g])
        i += len(g.words)


def test_gold_fixture_groups():
    a = fixture_alignment("words_gold_8s.json")
    assert texts(group_captions(a.tokens)) == [
        "Gold is heavier", "than you think", "A single cube", "this size weighs", "as much as",
        "a small car", "and it fits", "in your hand"]


def test_hook_headline_text_rules():
    assert hook_headline_text("This watch costs more than a car. And nobody knows why.") == \
        "This watch costs more than a car"
    assert hook_headline_text("Why is gold so heavy? Here is the answer.") == "Why is gold so heavy?"
    assert hook_headline_text("one two three four five six seven eight.") == "one two three four five six seven eight"
    assert hook_headline_text("one two three four five six seven eight nine.") is None
    assert hook_headline_text("") is None and hook_headline_text(None) is None and hook_headline_text("   ") is None
    assert hook_headline_text("No punctuation at all here") == "No punctuation at all here"


def test_make_hook_headline_window():
    assert make_hook_headline("Gold is heavy.", 40.0) == {"text": "Gold is heavy", "t0": 0.0, "t1": 2.5}
    assert make_hook_headline("Gold is heavy.", 1.8) == {"text": "Gold is heavy", "t0": 0.0, "t1": 1.8}
    assert make_hook_headline("a b c d e f g h i", 40.0) is None
```

In `tests/test_cin_shot_plan.py`, after `test_captions_use_script_spelling_in_groups_of_three` add (Phase A's grouping produced `"sell for 40"` / `"percent above retail"` here, so this fails today):

```python
def test_plan_captions_keep_number_runs_together():
    _, _, plan = rolex_plan("standard")
    joined = [" ".join(w.text for w in g.words) for g in plan.captions]
    assert "40 percent above" in joined and "sell for" in joined
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_caption_groups.py tests/test_cin_shot_plan.py -q -p no:cacheprovider`
Expected: `1 error` collecting `tests/test_cin_caption_groups.py` (`ModuleNotFoundError: No module named 'app.cin.caption_groups'`) and `FAILED tests/test_cin_shot_plan.py::test_plan_captions_keep_number_runs_together`.

- [ ] **Step 3: Implement `app/cin/caption_groups.py` and wire it into the planner**

Create `app/cin/caption_groups.py`:

```python
"""Caption grouping and hook headline text (spec §7). Pure functions, no fonts, no I/O.

Groups hold 1-3 aligned script tokens. A group ends after punctuation (the token's sentence_end /
comma flag) and before a silence > GAP_BREAK. Numbers ("1 million", "40 percent") and capitalized
name runs ("Hans Wilsdorf", "ELON MUSK") are atomic units that never straddle two groups; a unit is
capped at MAX_WORDS tokens, so an all-caps sentence or a 4-word name degrades to 3-word groups
instead of one oversized group.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

MAX_WORDS = 3
GAP_BREAK = 0.25                 # spec §7: break at gaps > 0.25 s
HOOK_MAX_WORDS = 8               # spec §7: headline only if the hook's first sentence is <= 8 words
HOOK_SECONDS = 2.5               # spec §7: headline shown for [0, 2.5 s]
_EPS = 1e-6
NUMBER_WORDS = frozenset({
    "hundred", "thousand", "million", "billion", "trillion", "percent", "%",
    "dollars", "dollar", "euros", "pounds", "years", "kg", "km", "mph",
})
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")


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


def _is_number(text: str) -> bool:
    return any(c.isdigit() for c in text)


def _is_capitalized(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and letters[0].isupper()


def _joins(tokens: list, i: int, unit_len: int) -> bool:
    """True when token i continues the atomic unit that ends at token i-1."""
    prev, cur = tokens[i - 1], tokens[i]
    if unit_len >= MAX_WORDS or prev.sentence_end or prev.comma:
        return False
    if (_is_number(prev.text) or prev.text.lower() in NUMBER_WORDS) and cur.text.lower() in NUMBER_WORDS:
        return True
    return _is_capitalized(prev.text) and _is_capitalized(cur.text)


def _units(tokens: list) -> list:
    """Atomic [start, end) token ranges."""
    units, start = [], 0
    for i in range(1, len(tokens) + 1):
        if i == len(tokens) or not _joins(tokens, i, i - start):
            units.append((start, i))
            start = i
    return units


def group_captions(tokens: list) -> list:
    """Aligned tokens (anything with text, t0, t1, sentence_end, comma) -> [CaptionGroup]."""
    groups, current = [], []

    def flush():
        if current:
            groups.append(CaptionGroup(current[0].t0, current[-1].t1, list(current)))
            current.clear()

    for a, b in _units(tokens):
        if current:
            prev = tokens[a - 1]
            gap = tokens[a].t0 - prev.t1
            if len(current) + (b - a) > MAX_WORDS or gap > GAP_BREAK + _EPS:
                flush()
        current.extend(CaptionWord(t.text, t.t0, t.t1) for t in tokens[a:b])
        last = tokens[b - 1]
        if last.sentence_end or last.comma:
            flush()
    flush()
    return groups


def hook_headline_text(hook: Optional[str]) -> Optional[str]:
    """The hook's first sentence if it has <= HOOK_MAX_WORDS words, else None (spec §7).
    A trailing full stop is dropped; '?' and '!' are kept."""
    hook = (hook or "").strip()
    if not hook:
        return None
    first = _SENTENCE_SPLIT.split(hook, maxsplit=1)[0].strip()
    words = first.split()
    if not words or len(words) > HOOK_MAX_WORDS:
        return None
    return first.rstrip(".…").strip() or None


def make_hook_headline(hook: Optional[str], duration: float) -> Optional[dict]:
    """shot_plan.json "hook_headline" value (spec §6.6), or None when the hook is too long."""
    text = hook_headline_text(hook)
    if text is None:
        return None
    return {"text": text, "t0": 0.0, "t1": round(min(HOOK_SECONDS, duration), 3)}
```

In `app/cin/shot_plan.py`:

1. After `from app.cin.align import Alignment` (line 16) add:

```python
from app.cin.caption_groups import CaptionGroup, CaptionWord, group_captions  # noqa: F401 (re-exported)
```

2. Delete the two dataclasses `CaptionWord` and `CaptionGroup` (lines 139-155, from `@dataclass` above `class CaptionWord:` through `CaptionGroup.to_json`'s `return`). `ShotPlan.from_json` keeps using the names — they are now the imported ones.
3. Delete `def _captions(alignment: Alignment) -> list:` and its body (lines 355-365).
4. In `build_shot_plan`'s `return ShotPlan(...)` replace `captions=_captions(alignment)` with `captions=group_captions(alignment.tokens)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_caption_groups.py tests/test_cin_shot_plan.py tests/test_cin_segments.py -q -p no:cacheprovider`
Expected: all pass (`13 passed` in the new file; `test_captions_use_script_spelling_in_groups_of_three` still passes — the first rolex group is still `This watch costs`; `test_cin_segments.py` still sees `hook_headline is None`).

- [ ] **Step 5: Commit**

```bash
git add app/cin/caption_groups.py app/cin/shot_plan.py tests/test_cin_caption_groups.py tests/test_cin_shot_plan.py
git commit -m "feat: caption grouping keeps names and numbers together; hook headline text

1-3 words, break at punctuation and gaps > 0.25 s; atomic runs capped at 3 tokens.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Caption style and single-line layout

**Files:**
- Create: `app/cin/captions.py` (style, glyph filter, layout; the layer is added in Task 4)
- Test: `tests/test_cin_captions.py` (create)

**Interfaces:**
- Consumes: `app.fonts.load_font` (Task 1); `SUBTITLE_PRESETS[...]["font_file"|"font_weight"]` (Task 1).
- Produces: constants `REF_W = 1080`, `REF_H = 1920`, `BOTTOM_BOX = (94, 1254, 986, 1402)`, `CENTER_BOX = (94, 886, 986, 1034)`, `HEADLINE_BOX = (94, 258, 986, 442)`, `RAMP_SECONDS = 0.08`, `RAMP_STEPS = 4`, `HOLD = 0.4`, `MIN_FONT = 12`; `CaptionStyle.from_preset(name: str) -> CaptionStyle` (fields `name, font_file, font_weight, font_size, active_scale, active, inactive, stroke, stroke_width, position, bg, font_fallback`; colours as RGBA tuples) and `CaptionStyle.font(size) -> FreeTypeFont`; `scale_box(box, width, height) -> tuple`; `drawable(text: str, font) -> str`; `LineLayout(size, words, index, xs, widths, baseline)`; `layout_line(words: list[str], style, box_w: int, box_h: int, size: Optional[int] = None) -> LineLayout`; private `_ink_extent(font, text, stroke) -> (top, bottom)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_captions.py`:

```python
"""Caption layout + layer (spec §7): safe zone, highlight ramp, frame-one captions, hook headline."""
import numpy as np
import pytest

from app.cin.captions import BOTTOM_BOX, CaptionStyle, drawable, layout_line
from app.subtitle_styles import SUBTITLE_PRESETS

BOTTOM_STYLES = [k for k, v in SUBTITLE_PRESETS.items() if v["position"] == "bottom"]
LONG = "Supercalifragilisticexpialidocious"


# ---------------------------------------------------------------- layout

def test_drawable_uppercases_and_drops_missing_glyphs():
    font = CaptionStyle.from_preset("fire").font(80)
    assert drawable("café", font) == "CAFÉ"
    assert drawable("fire\U0001F525", font) == "FIRE"
    assert drawable("\U0001F525\U0001F525", font) == ""
    assert drawable("$1,000,000", font) == "$1,000,000"


@pytest.mark.parametrize("style_name", list(SUBTITLE_PRESETS))
def test_layout_fits_box_including_highlight_growth(style_name):
    style = CaptionStyle.from_preset(style_name)
    bw, bh = BOTTOM_BOX[2] - BOTTOM_BOX[0], BOTTOM_BOX[3] - BOTTOM_BOX[1]
    for words in (["Gold"], ["Hans", "Wilsdorf", "founded"], ["$1,000,000", "in", "1999"], [LONG]):
        lay = layout_line(words, style, bw, bh)
        grow = (style.active_scale - 1) * max(lay.widths)
        assert lay.xs[0] - grow / 2 - style.stroke_width >= 0, (style_name, words)
        assert lay.xs[-1] + lay.widths[-1] + grow / 2 + style.stroke_width <= bw, (style_name, words)


@pytest.mark.parametrize("style_name", list(SUBTITLE_PRESETS))
def test_scaled_active_word_never_touches_its_neighbours(style_name):
    style = CaptionStyle.from_preset(style_name)
    lay = layout_line(["Hans", "Wilsdorf", "founded"], style, 892, 148)
    grow = style.active_scale - 1
    for j in range(len(lay.words) - 1):
        gap = lay.xs[j + 1] - (lay.xs[j] + lay.widths[j])
        assert gap >= grow * max(lay.widths[j], lay.widths[j + 1]) / 2 + 2 * style.stroke_width - 1


def test_short_group_keeps_preset_size_long_word_shrinks():
    style = CaptionStyle.from_preset("bold_impact")
    bw, bh = BOTTOM_BOX[2] - BOTTOM_BOX[0], BOTTOM_BOX[3] - BOTTOM_BOX[1]
    assert layout_line(["Gold", "is", "heavy"], style, bw, bh).size == 75
    assert layout_line([LONG], style, bw, bh).size < 50


def test_word_with_no_drawable_glyphs_is_dropped_from_layout():
    style = CaptionStyle.from_preset("bold_impact")
    lay = layout_line(["so", "\U0001F525", "hot"], style, 892, 148)
    assert lay.words == ["SO", "HOT"] and lay.index == [0, 2]


def test_unknown_style_uses_bold_impact():
    assert CaptionStyle.from_preset("nope").name == "bold_impact"


def test_style_colours_come_from_the_preset():
    style = CaptionStyle.from_preset("fire")
    assert style.active == (0xFF, 0x45, 0x00, 0xFF) and style.inactive == (0xFF, 0xD7, 0x00, 0x80)
    assert style.font_fallback is False and style.position == "bottom"
    assert CaptionStyle.from_preset("clean_minimal").bg == (0, 0, 0, 0x80)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_captions.py -q -p no:cacheprovider`
Expected: `1 error` during collection — `ModuleNotFoundError: No module named 'app.cin.captions'`.

- [ ] **Step 3: Implement the style and layout half of `app/cin/captions.py`**

Create `app/cin/captions.py`:

```python
"""Caption + hook-headline layer for the shot renderer (spec §7).

Each caption group is laid out once (one line, shrunk to fit its box) and rasterized once per
highlight state, then alpha-composited inside ShotRenderer.frame_at. A highlight state is
(active word, ramp step): the 80 ms 1.0 -> active_scale ramp is quantized into RAMP_STEPS steps,
so a 3-word group is rasterized at most 3 x (RAMP_STEPS + 1) times. Every sprite is clipped to its
box, so no caption pixel can leave the safe zone whatever the text.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.fonts import load_font

logger = logging.getLogger(__name__)

REF_W, REF_H = 1080, 1920
# Boxes are (x0, y0, x1, y1) at 1080x1920, end-exclusive. Spec §7: bottom captions centred at
# y ~ 1325 (1250-1400), never below y = 1410 or right of x = 990. 4-8 px are left as margin for
# H.264 4:2:0 chroma bleed, so decoded frames also stay inside the spec's numbers.
BOTTOM_BOX = (94, 1254, 986, 1402)
CENTER_BOX = (94, 886, 986, 1034)          # "center" preset: vertical frame centre
HEADLINE_BOX = (94, 258, 986, 442)          # spec §7: top band y ~ 250-450
RAMP_SECONDS = 0.08                         # spec §7: 1.0 -> active_scale over 80 ms
RAMP_STEPS = 4
HOLD = 0.4                                  # a group stays up to 0.4 s after its last word ...
                                            # ... but never past the next group's start
MIN_FONT = 12
HEADLINE_SCALE = 1.6                        # headline starts at caption size x 1.6, then shrinks to fit
HEADLINE_MAX_LINES = 2


def _rgba(hex_color: Optional[str]) -> Optional[tuple]:
    if not hex_color:
        return None
    h = hex_color.lstrip("#")
    if len(h) == 6:
        h += "FF"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))


@dataclass
class CaptionStyle:
    name: str
    font_file: str
    font_weight: Optional[int]
    font_size: int
    active_scale: float
    active: tuple
    inactive: tuple
    stroke: Optional[tuple]
    stroke_width: int
    position: str
    bg: Optional[tuple]
    font_fallback: bool = False

    @classmethod
    def from_preset(cls, name: str) -> "CaptionStyle":
        from app.subtitle_styles import SUBTITLE_PRESETS
        if name not in SUBTITLE_PRESETS:
            logger.warning("Unknown subtitle style %r, using 'bold_impact'", name)
            name = "bold_impact"
        p = SUBTITLE_PRESETS[name]
        style = cls(name=name, font_file=p["font_file"], font_weight=p.get("font_weight"),
                    font_size=p["font_size"], active_scale=float(p.get("active_scale", 1.0)),
                    active=_rgba(p["active_color"]), inactive=_rgba(p["inactive_color"]),
                    stroke=_rgba(p.get("stroke_color")), stroke_width=int(p.get("stroke_width") or 0),
                    position=p.get("position", "bottom"),
                    bg=_rgba(p.get("bg_color", "#00000080")) if p.get("bg_box") else None)
        _, style.font_fallback = load_font(style.font_file, style.font_size, style.font_weight)
        return style

    def font(self, size: int):
        return load_font(self.font_file, max(MIN_FONT, int(round(size))), self.font_weight)[0]


def scale_box(box: tuple, width: int, height: int) -> tuple:
    sx, sy = width / REF_W, height / REF_H
    return (round(box[0] * sx), round(box[1] * sy), round(box[2] * sx), round(box[3] * sy))


def drawable(text: str, font) -> str:
    """Upper-cased text with every character the font cannot draw removed (emoji, CJK in a Latin
    font). A missing glyph rasterizes as the font's .notdef box, so compare against that."""
    tofu = font.getmask("\U0010FFFD")
    tofu_key = (tofu.size, bytes(tofu))
    out = []
    for ch in text.upper():
        if ch.isspace():
            out.append(" ")
            continue
        m = font.getmask(ch)
        if (m.size, bytes(m)) != tofu_key:
            out.append(ch)
    return "".join(out).strip()


@dataclass
class LineLayout:
    size: int                 # fitted base font size
    words: list               # drawable upper-case words (non-empty)
    index: list               # caption word index for each laid-out word
    xs: list                  # left x of each word, box-local, at base size
    widths: list
    baseline: int             # box-local y of the text baseline


def _ink_extent(font, text: str, stroke: int) -> tuple:
    """(top, bottom) of the ink relative to the baseline, stroke included."""
    x0, y0, x1, y1 = font.getbbox(text, anchor="ls", stroke_width=stroke)
    return y0, y1


def layout_line(words: list, style: CaptionStyle, box_w: int, box_h: int, size: Optional[int] = None) -> LineLayout:
    """Fit a single caption line: base width plus the widest word's highlight growth must fit box_w,
    and the active-size ink (stroke included) must fit box_h. words: raw caption word texts."""
    size = int(size or style.font_size)
    base_font = style.font(size)
    texts, index = [], []
    for i, w in enumerate(words):
        d = drawable(w, base_font)
        if d:
            texts.append(d)
            index.append(i)
    sw = style.stroke_width
    while True:
        font = style.font(size)
        active = style.font(size * style.active_scale)
        widths = [font.getlength(t) for t in texts]
        grow = style.active_scale - 1.0
        space = font.getlength(" ")
        # Only one word is scaled at a time: each gap absorbs half the larger neighbour's growth,
        # so the active word never touches the words beside it.
        gaps = [space + 2 * sw + grow * max(a, b) / 2 for a, b in zip(widths, widths[1:])]
        text_w = sum(widths) + sum(gaps)
        need_w = text_w + grow * max(widths, default=0) + 2 * sw
        tops, bottoms = zip(*[_ink_extent(active, t, sw) for t in texts]) if texts else ((0,), (0,))
        need_h = max(bottoms) - min(tops)
        if (need_w <= box_w and need_h <= box_h) or size <= MIN_FONT:
            break
        factor = min(box_w / max(need_w, 1), box_h / max(need_h, 1), 0.97)
        size = max(MIN_FONT, int(size * factor))
    x = (box_w - text_w) / 2
    xs = []
    for w, gap in zip(widths, gaps + [0.0]):
        xs.append(round(x))
        x += w + gap
    baseline = round(box_h / 2 - (min(tops) + max(bottoms)) / 2)
    return LineLayout(size, texts, index, xs, [round(w) for w in widths], baseline)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_captions.py -q -p no:cacheprovider`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add app/cin/captions.py tests/test_cin_captions.py
git commit -m "feat: caption style from presets and single-line layout that fits the safe zone

Reserves room for the active word's growth; drops glyphs the font cannot draw.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Caption layer — rasterize per highlight state, timing, hook headline

**Files:**
- Modify: `app/cin/captions.py` (imports; append `_Sprite`, `CaptionLayer`, `_wrap`, `build_caption_layer`)
- Test: `tests/test_cin_captions.py` (replace the import block; append tests)

**Interfaces:**
- Consumes: Task 2 `CaptionGroup`/`CaptionWord` (`app.cin.caption_groups`), `group_captions`; Task 3 names; `app.cin.report.RunReport.warn(code, message, detail)`; `ShotPlan.captions`, `.hook_headline`, `.duration`.
- Produces: `CaptionLayer(groups: list[CaptionGroup], style: CaptionStyle, duration: float, *, headline: Optional[dict] = None, width: int = 1080, height: int = 1920)` with `.composite(frame: np.ndarray, t: float) -> np.ndarray` (blends in place into a writable HxWx3 uint8 array and returns it), `.group_at(t) -> Optional[int]`, `.state_at(gi, t) -> (int, int)`, `.groups`, `.layouts`, `._rasterize(gi, active, step)`; `build_caption_layer(plan, subtitle_style: str, *, report=None, enable_subtitles: bool = True, width: int = 1080, height: int = 1920) -> Optional[CaptionLayer]` (None when there are no captions and no headline; reports `font_fallback` once).

- [ ] **Step 1: Write the failing tests**

In `tests/test_cin_captions.py` replace the import block (the lines from `import numpy as np` through `from app.subtitle_styles import SUBTITLE_PRESETS`) with:

```python
import numpy as np
import pytest

from app.cin.caption_groups import CaptionGroup, CaptionWord, group_captions
from app.cin.captions import (BOTTOM_BOX, RAMP_SECONDS, CaptionLayer, CaptionStyle,
                              build_caption_layer, drawable, layout_line)
from app.cin.report import RunReport
from app.cin.shot_plan import ShotPlan
from app.subtitle_styles import SUBTITLE_PRESETS
from tests.conftest import fixture_alignment
```

Then append:

```python
def group(*words, t=0.0, step=0.3):
    ws = [CaptionWord(w, round(t + i * step, 3), round(t + (i + 1) * step - 0.02, 3)) for i, w in enumerate(words)]
    return CaptionGroup(ws[0].t0, ws[-1].t1, ws)


def ink(frame):
    """(x0, y0, x1, y1) end-exclusive bbox of non-black pixels, or None."""
    ys, xs = np.nonzero(frame.max(axis=2) > 0)
    if len(ys) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def black():
    return np.zeros((1920, 1080, 3), np.uint8)


def plan_with(captions, duration=8.0, hook_headline=None):
    return ShotPlan(duration=duration, fps=30, pacing="standard", alignment={}, scenes=[], shots=[],
                    captions=captions, hook_headline=hook_headline)


# ---------------------------------------------------------------- layer: placement

@pytest.mark.parametrize("style_name", BOTTOM_STYLES)
def test_bottom_captions_stay_in_safe_zone_at_peak_highlight(style_name):
    """The widest moment is the LAST word at full scale (t = last.t0 + 80 ms), not a random frame."""
    for words in (("Hans", "Wilsdorf", "founded"), ("waterproof", "wristwatch", "the"), (LONG,),
                  ("$1,000,000", "in", "1999")):
        g = group(*words)
        layer = CaptionLayer([g], CaptionStyle.from_preset(style_name), 8.0)
        for w in g.words:
            box = ink(layer.composite(black(), w.t0 + RAMP_SECONDS + 0.001))
            assert box is not None
            x0, y0, x1, y1 = box
            assert 1250 <= y0 and y1 <= 1410, (style_name, words, box)     # spec §7 vertical zone
            assert x0 >= 90 and x1 <= 990, (style_name, words, box)         # never right of x = 990
            assert 1250 <= (y0 + y1) / 2 <= 1400                            # block centre in 1250-1400


def test_center_preset_sits_at_frame_centre():
    layer = CaptionLayer([group("clean", "minimal")], CaptionStyle.from_preset("clean_minimal"), 8.0)
    x0, y0, x1, y1 = ink(layer.composite(black(), 0.1))
    assert 880 <= y0 and y1 <= 1040 and x1 <= 990


# ---------------------------------------------------------------- layer: timing

def test_captions_show_from_frame_one():
    g = group("Gold", "is", "heavier", t=0.05)
    layer = CaptionLayer([g], CaptionStyle.from_preset("bold_impact"), 8.0)
    assert ink(layer.composite(black(), 0.0)) is not None


def test_group_hides_after_hold_and_yields_to_next_group():
    a, b = group("one", "two", t=0.0), group("three", t=3.0)
    layer = CaptionLayer([a, b], CaptionStyle.from_preset("bold_impact"), 8.0)
    assert layer.group_at(0.3) == 0
    assert layer.group_at(a.t1 + 0.2) == 0
    assert layer.group_at(a.t1 + 0.5) is None
    assert layer.group_at(3.05) == 1
    assert layer.group_at(7.9) is None


def test_active_word_ramps_over_80ms_then_holds():
    g = group("Gold", "is", "heavy")
    layer = CaptionLayer([g], CaptionStyle.from_preset("fire"), 8.0)
    w = g.words[1]
    assert layer.state_at(0, w.t0) == (1, 0)
    assert layer.state_at(0, w.t0 + RAMP_SECONDS / 2) == (1, 2)
    assert layer.state_at(0, w.t0 + RAMP_SECONDS) == (1, 4)
    assert layer.state_at(0, w.t0 + 0.2) == (1, 4)
    small = ink(layer.composite(black(), w.t0))
    big = ink(layer.composite(black(), w.t0 + RAMP_SECONDS))
    assert (big[3] - big[1]) > (small[3] - small[1])                 # the active word really grows


def test_equal_start_times_never_go_backwards():
    """Rolex fixture: '40' and 'percent' share t0 = 30.46 (one Whisper word)."""
    words = [CaptionWord("40", 30.46, 30.73), CaptionWord("percent", 30.46, 30.73), CaptionWord("above", 30.77, 31.13)]
    layer = CaptionLayer([CaptionGroup(30.46, 31.13, words)], CaptionStyle.from_preset("bold_impact"), 40.0)
    seen = [layer.state_at(0, t)[0] for t in np.arange(30.40, 31.2, 1 / 30)]
    assert seen == sorted(seen) and seen[-1] == 2


def test_each_highlight_state_is_rasterized_once(monkeypatch):
    g = group("Gold", "is", "heavy")
    layer = CaptionLayer([g], CaptionStyle.from_preset("bold_impact"), 8.0)
    calls = []
    real = layer._rasterize
    monkeypatch.setattr(layer, "_rasterize", lambda *a: calls.append(a) or real(*a))
    for t in np.arange(0.0, 1.3, 1 / 30):
        layer.composite(black(), t)
    assert len(calls) == len(set(calls)) <= 3 * 5


# ---------------------------------------------------------------- headline

def test_hook_headline_in_top_band_only_for_first_2_5_seconds():
    layer = CaptionLayer([], CaptionStyle.from_preset("bold_impact"), 8.0,
                         headline={"text": "This watch costs more than a car", "t0": 0.0, "t1": 2.5})
    x0, y0, x1, y1 = ink(layer.composite(black(), 0.0))
    assert 250 <= y0 and y1 <= 450 and 90 <= x0 and x1 <= 990
    assert ink(layer.composite(black(), 2.49)) is not None
    assert ink(layer.composite(black(), 2.5)) is None


def test_eight_word_headline_wraps_inside_band():
    layer = CaptionLayer([], CaptionStyle.from_preset("fire"), 8.0,
                         headline={"text": "Nobody believed this tiny watch could survive", "t0": 0.0, "t1": 2.5})
    x0, y0, x1, y1 = ink(layer.composite(black(), 1.0))
    assert 250 <= y0 and y1 <= 450 and x1 <= 990


# ---------------------------------------------------------------- factory

def test_build_layer_none_when_nothing_to_draw():
    assert build_caption_layer(plan_with([]), "bold_impact") is None
    assert build_caption_layer(plan_with([group("a")]), "bold_impact", enable_subtitles=False) is None


def test_empty_caption_list_still_draws_headline():
    layer = build_caption_layer(plan_with([], hook_headline={"text": "Gold is heavy", "t0": 0.0, "t1": 2.5}),
                                "bold_impact")
    assert layer is not None and ink(layer.composite(black(), 1.0)) is not None


def test_missing_font_records_font_fallback(monkeypatch):
    monkeypatch.setitem(SUBTITLE_PRESETS["bold_impact"], "font_file", "Gone.ttf")
    report = RunReport(job="j")
    layer = build_caption_layer(plan_with([group("still", "renders")]), "bold_impact", report=report)
    assert [w["code"] for w in report.warnings] == ["font_fallback"]
    assert report.warnings[0]["detail"]["font_file"] == "Gone.ttf"
    box = ink(layer.composite(black(), 0.1))
    assert box is not None and 1250 <= box[1] and box[3] <= 1410


def test_rolex_fixture_every_frame_in_zone():
    """Whole 40 s fixture at 4 fps: every caption frame inside the safe zone, no exceptions."""
    a = fixture_alignment("words_rolex_40s.json")
    layer = CaptionLayer(group_captions(a.tokens), CaptionStyle.from_preset("fire"), a.duration)
    for t in np.arange(0.0, a.duration, 0.25):
        box = ink(layer.composite(black(), float(t)))
        if box:
            assert 1250 <= box[1] and box[3] <= 1410 and box[2] <= 990, (t, box)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_captions.py -q -p no:cacheprovider`
Expected: `1 error` during collection — `ImportError: cannot import name 'CaptionLayer' from 'app.cin.captions'`.

- [ ] **Step 3: Implement the layer**

In `app/cin/captions.py` replace the import block

```python
import logging
from dataclasses import dataclass
from typing import Optional

from app.fonts import load_font
```

with

```python
import bisect
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

from app.fonts import load_font
```

and append to the end of the file:

```python
class _Sprite:
    """A rasterized RGBA strip cropped to its ink, stored as float32 rgb + alpha for blending."""

    def __init__(self, img: Image.Image, origin: tuple, clip: tuple):
        arr = np.asarray(img)
        ys, xs = np.nonzero(arr[:, :, 3])
        if len(ys) == 0:
            self.empty = True
            return
        self.empty = False
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        ox, oy = origin
        cx0, cy0, cx1, cy1 = clip
        fx0, fy0 = max(ox + x0, cx0), max(oy + y0, cy0)
        fx1, fy1 = min(ox + x1, cx1), min(oy + y1, cy1)
        if fx0 >= fx1 or fy0 >= fy1:
            self.empty = True
            return
        crop = arr[fy0 - oy:fy1 - oy, fx0 - ox:fx1 - ox]
        self.box = (fx0, fy0, fx1, fy1)
        self.rgb = crop[:, :, :3].astype(np.float32)
        self.alpha = crop[:, :, 3:4].astype(np.float32) / 255.0

    def blend(self, frame: np.ndarray) -> None:
        if self.empty:
            return
        x0, y0, x1, y1 = self.box
        region = frame[y0:y1, x0:x1].astype(np.float32)
        frame[y0:y1, x0:x1] = (region * (1.0 - self.alpha) + self.rgb * self.alpha).astype(np.uint8)


class CaptionLayer:
    def __init__(self, groups: list, style: CaptionStyle, duration: float, *,
                 headline: Optional[dict] = None, width: int = REF_W, height: int = REF_H):
        self.style, self.duration, self.w, self.h = style, duration, width, height
        self.k = width / REF_W
        self.box = scale_box(CENTER_BOX if style.position == "center" else BOTTOM_BOX, width, height)
        bw, bh = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.groups, self.layouts = [], []
        for g in groups:
            if not g.words:
                continue
            lay = layout_line([w.text for w in g.words], style, bw, bh, size=style.font_size * self.k)
            if lay.words:
                self.groups.append(g)
                self.layouts.append(lay)
        self.windows = self._windows()
        self._starts = [w[0] for w in self.windows]
        self._cache: dict = {}
        self._cache_group = -1
        self.headline = headline if headline and headline.get("text") else None
        self._headline_sprite = self._render_headline() if self.headline else None

    # ------------------------------------------------------------ timing

    def _windows(self) -> list:
        out = []
        n = len(self.groups)
        for i, g in enumerate(self.groups):
            start = 0.0 if i == 0 else g.t0                       # spec §7: captions from frame one
            nxt = self.groups[i + 1].t0 if i + 1 < n else self.duration
            end = min(nxt, g.t1 + HOLD) if i + 1 < n else min(self.duration, g.t1 + HOLD)
            out.append((start, max(end, start + 1e-3), i))
        return out

    def group_at(self, t: float) -> Optional[int]:
        j = bisect.bisect_right(self._starts, t) - 1
        if j < 0:
            return None
        start, end, gi = self.windows[j]
        return gi if start <= t < end else None

    def state_at(self, gi: int, t: float) -> tuple:
        """(laid-out active word position, ramp step). Active = last word whose t0 <= t (the first
        word before it starts), so zero-length or equal-t0 words never break monotonicity."""
        g, lay = self.groups[gi], self.layouts[gi]
        active_word = 0
        for i, w in enumerate(g.words):
            if w.t0 <= t:
                active_word = i
        if active_word not in lay.index:
            return (-1, 0)                                       # active word had no drawable glyphs
        dt = t - g.words[active_word].t0
        step = min(RAMP_STEPS, max(0, int(dt / RAMP_SECONDS * RAMP_STEPS + 1e-6)))
        return (lay.index.index(active_word), step)

    # ------------------------------------------------------------ raster

    def _draw_word(self, draw, xy, text, font, fill, anchor):
        st = self.style
        if st.stroke and st.stroke_width:
            draw.text(xy, text, font=font, fill=fill, anchor=anchor,
                      stroke_width=max(1, round(st.stroke_width * self.k)), stroke_fill=st.stroke)
        else:
            draw.text(xy, text, font=font, fill=fill, anchor=anchor)

    def _rasterize(self, gi: int, active: int, step: int) -> _Sprite:
        lay, st = self.layouts[gi], self.style
        bw, bh = self.box[2] - self.box[0], self.box[3] - self.box[1]
        img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        base = st.font(lay.size)
        if st.bg:
            pad = round(20 * self.k)
            left, right = lay.xs[0] - pad, lay.xs[-1] + lay.widths[-1] + pad
            top, bottom = _ink_extent(base, " ".join(lay.words), 0)
            draw.rounded_rectangle([left, lay.baseline + top - pad // 2, right, lay.baseline + bottom + pad // 2],
                                   radius=round(10 * self.k), fill=st.bg)
        for j, text in enumerate(lay.words):
            if j != active:
                self._draw_word(draw, (lay.xs[j], lay.baseline), text, base, st.inactive, "ls")
        if active >= 0:
            scale = 1.0 + (st.active_scale - 1.0) * step / RAMP_STEPS
            font = st.font(lay.size * scale)
            cx = lay.xs[active] + lay.widths[active] / 2
            self._draw_word(draw, (cx, lay.baseline), lay.words[active], font, st.active, "ms")
        return _Sprite(img, (self.box[0], self.box[1]), self.box)

    def sprite(self, gi: int, state: tuple) -> _Sprite:
        if gi != self._cache_group:                              # groups only move forward: drop the old one
            self._cache.clear()
            self._cache_group = gi
        if state not in self._cache:
            self._cache[state] = self._rasterize(gi, *state)
        return self._cache[state]

    def _render_headline(self) -> _Sprite:
        st = self.style
        box = scale_box(HEADLINE_BOX, self.w, self.h)
        bw, bh = box[2] - box[0], box[3] - box[1]
        sw = max(4, st.stroke_width)
        size = int(st.font_size * HEADLINE_SCALE * self.k)
        words = drawable(self.headline["text"], st.font(size)).split()
        while True:
            font = st.font(size)
            lines = _wrap(words, font, bw - 2 * sw, HEADLINE_MAX_LINES)
            asc, desc = font.getmetrics()
            line_h = asc + desc + 2 * sw
            if lines is not None and line_h * len(lines) <= bh:
                break
            if size <= MIN_FONT:
                lines = [" ".join(words)]                      # clipped to the band by _Sprite
                break
            size = max(MIN_FONT, int(size * 0.92))
        img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        y = (bh - line_h * len(lines)) / 2 + sw
        for line in lines:
            draw.text((bw / 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma",
                      stroke_width=sw, stroke_fill=(0, 0, 0, 255))
            y += line_h
        return _Sprite(img, (box[0], box[1]), box)

    # ------------------------------------------------------------ per frame

    def composite(self, frame: np.ndarray, t: float) -> np.ndarray:
        if self.headline and self.headline["t0"] <= t < self.headline["t1"]:
            self._headline_sprite.blend(frame)
        gi = self.group_at(t)
        if gi is not None:
            self.sprite(gi, self.state_at(gi, t)).blend(frame)
        return frame


def _wrap(words: list, font, max_w: float, max_lines: int) -> Optional[list]:
    """Greedy wrap into at most max_lines lines no wider than max_w; None when it cannot."""
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and font.getlength(trial) > max_w:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    if len(lines) > max_lines or any(font.getlength(l) > max_w for l in lines):
        return None
    return lines


def build_caption_layer(plan, subtitle_style: str, *, report=None, enable_subtitles: bool = True,
                        width: int = REF_W, height: int = REF_H) -> Optional[CaptionLayer]:
    """CaptionLayer for a ShotPlan, or None when there is nothing to draw. A missing bundled font
    is recorded once as font_fallback in the run report."""
    groups = plan.captions if enable_subtitles else []
    if not groups and not plan.hook_headline:
        return None
    style = CaptionStyle.from_preset(subtitle_style)
    if style.font_fallback and report is not None:
        report.warn("font_fallback", f"Caption font {style.font_file} missing; using a system font",
                    {"style": style.name, "font_file": style.font_file})
    return CaptionLayer(groups, style, plan.duration, headline=plan.hook_headline, width=width, height=height)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_captions.py -q -p no:cacheprovider`
Expected: `28 passed` (≈ 6 s; the rolex sweep is the slow one).

- [ ] **Step 5: Commit**

```bash
git add app/cin/captions.py tests/test_cin_captions.py
git commit -m "feat: caption layer rasterizes each highlight state once; hook headline band

Groups show from frame one, active word ramps over 80 ms, sprites clipped to the safe zone.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Wire captions into the renderer, render_job, the pipeline and re-render

**Files:**
- Modify: `app/cin/renderer.py:104-106` (`__init__`), `:134-143` (`frame_at`), `:145-160` (`render`), `:166-176` (delete `caption_overlays`)
- Modify: `app/cin/editor.py:19` (import), `:67-70` (render stage), `:144-148` (`rebuild_plan`)
- Modify: `main.py:31` (import), `:273` (after `build_shot_plan`)
- Test: `tests/test_cin_captions_render.py` (create), `tests/test_pipeline.py` (append one test)

**Interfaces:**
- Consumes: `build_caption_layer`, `CaptionLayer.composite` (Task 4); `make_hook_headline` (Task 2); `group_captions` re-exported by `app.cin.shot_plan` (Task 2).
- Produces: `ShotRenderer(plan, job, *, video_style=..., color_grade=None, width=1080, height=1920, captions: Optional[CaptionLayer] = None)`; `ShotRenderer.render(out_path) -> Path` (the `overlays` parameter is removed); `render_job` passes `captions=` to `ShotRenderer`; `rebuild_plan(...)` returns a plan whose `hook_headline` equals the saved plan's; `shot_plan.json` written by `run_pipeline` carries `hook_headline`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cin_captions_render.py`:

```python
"""Captions + hook headline inside the shot renderer and render_job (spec §7, §12)."""
import subprocess

import numpy as np
import pytest
from PIL import Image

from app.cin.captions import CaptionLayer, build_caption_layer
from app.cin.editor import RenderOptions, rebuild_plan, render_job
from app.cin.job import create_job
from app.cin.renderer import ShotRenderer
from app.cin.report import RunReport
from app.cin.shot_plan import Scene, Segment, Shot, ShotPlan, ShotSource, build_shot_plan, group_captions
from app.subtitle_styles import SUBTITLE_PRESETS
from tests.conftest import build_gold_job, ffmpeg_exe, fixture_alignment, make_color_clip, make_silence, make_test_clip

HEADLINE = {"text": "Gold is heavier than you think", "t0": 0.0, "t1": 2.5}


def ink(frame, threshold=0):
    ys, xs = np.nonzero(frame.max(axis=2) > threshold)
    if len(ys) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def black_still_plan(job, duration=8.0):
    """One full-length still shot of a black image, gold captions, the hook headline."""
    job.image(0).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1920), (0, 0, 0)).save(job.image(0))
    alignment = fixture_alignment("words_gold_8s.json")
    return ShotPlan(
        duration=duration, fps=30, pacing="standard", alignment={},
        scenes=[Scene(0, 0.0, duration, "gold", [Segment(0.0, duration, None, 6.0, job.rel(job.image(0)))])],
        shots=[Shot(0, 0, 0.0, duration, ShotSource("still", job.rel(job.image(0)), move="push_in"), 1.0)],
        captions=group_captions(alignment.tokens), hook_headline=dict(HEADLINE))


def test_frame_at_composites_captions_and_headline(tmp_path):
    job = create_job("cap", tmp_path)
    plan = black_still_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book", captions=build_caption_layer(plan, "fire"))
    try:
        first = r.frame_at(0.0)
        top, bottom = first[:1000], first[1000:]
        assert ink(top) is not None and ink(bottom) is not None          # headline + caption from frame one
        x0, y0, x1, y1 = ink(top)
        assert 250 <= y0 and y1 <= 450 and x1 <= 990
        later = r.frame_at(4.0)
        assert ink(later[:1000]) is None                                  # headline gone after 2.5 s
        bx0, by0, bx1, by1 = ink(later)
        assert 1250 <= by0 and by1 <= 1410 and bx1 <= 990
    finally:
        r.sources.close()


def test_captions_do_not_burn_into_cached_source_frames(tmp_path):
    """frame 0 of an unzoomed still IS the cached array; compositing into it would stamp every frame."""
    job = create_job("cap", tmp_path)
    plan = black_still_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book", captions=build_caption_layer(plan, "bold_impact"))
    try:
        r.frame_at(0.0)
        assert r.sources.still(job.rel(job.image(0))).max() == 0          # cached black still untouched
    finally:
        r.sources.close()


def test_subtitles_off_keeps_headline_only(tmp_path):
    job = create_job("cap", tmp_path)
    plan = black_still_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book",
                     captions=build_caption_layer(plan, "fire", enable_subtitles=False))
    try:
        assert ink(r.frame_at(1.0)[1000:]) is None
        assert ink(r.frame_at(1.0)[:1000]) is not None
    finally:
        r.sources.close()


def test_rebuild_plan_keeps_hook_headline(tmp_path):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, "standard", specs)
    plan.hook_headline = dict(HEADLINE)
    plan.save(job.shot_plan)
    assert rebuild_plan(job, "fast").hook_headline == HEADLINE


class _CaptureRenderer:
    """Stands in for ShotRenderer inside render_job: records kwargs, writes a tiny clip."""
    seen: dict = {}

    def __init__(self, plan, job, **kwargs):
        self.plan = plan
        _CaptureRenderer.seen = kwargs

    def render(self, out_path):
        return make_test_clip(out_path, self.plan.duration)


def _render_with_capture(tmp_path, monkeypatch, **opts):
    job, alignment, specs = build_gold_job(tmp_path)
    make_silence(job.narration, 8.0)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _CaptureRenderer)
    plan = build_shot_plan(alignment, "standard", specs)
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(enable_music=False, enable_sfx=False, **opts), report)
    return plan, report, _CaptureRenderer.seen


def test_render_job_hands_caption_layer_to_renderer(tmp_path, monkeypatch):
    plan, report, seen = _render_with_capture(tmp_path, monkeypatch, subtitle_style="fire")
    assert isinstance(seen["captions"], CaptionLayer)
    assert len(seen["captions"].groups) == len(plan.captions)
    assert "font_fallback" not in [w["code"] for w in report.warnings]


def test_render_job_without_subtitles_or_headline_passes_no_layer(tmp_path, monkeypatch):
    _, _, seen = _render_with_capture(tmp_path, monkeypatch, enable_subtitles=False)
    assert seen["captions"] is None


def test_render_job_reports_missing_caption_font(tmp_path, monkeypatch):
    monkeypatch.setitem(SUBTITLE_PRESETS["fire"], "font_file", "Gone.ttf")
    _, report, seen = _render_with_capture(tmp_path, monkeypatch, subtitle_style="fire")
    assert [w["code"] for w in report.warnings].count("font_fallback") == 1
    assert seen["captions"] is not None                               # still renders, with a system font
```

Append to `tests/test_pipeline.py`:

```python
def test_shot_plan_gets_hook_headline_from_script(offline, monkeypatch):
    """Spec §7: the hook's first sentence (<= 8 words) becomes the top-band headline for [0, 2.5 s]."""
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    plan = json.loads((only_job(offline.out) / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert plan["hook_headline"] == {"text": "Gold is heavier than you think", "t0": 0.0, "t1": 2.5}
```

(`subprocess`, `pytest`, `ffmpeg_exe` and `make_color_clip` are imported now for the render test Task 6 appends.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_captions_render.py tests/test_pipeline.py::test_shot_plan_gets_hook_headline_from_script -q -p no:cacheprovider`
Expected: `8 failed` — the three `ShotRenderer` tests with `TypeError: ShotRenderer.__init__() got an unexpected keyword argument 'captions'`, `test_rebuild_plan_keeps_hook_headline` with `assert None == {'t0': 0.0, 't1': 2.5, 'text': 'Gold is heavier than you think'}`, the three `render_job` tests with `TypeError: _CaptureRenderer.render() takes 2 positional arguments but 3 were given` (Phase A still calls `render(video_tmp, overlays)`), and the pipeline test with the same `assert None == {...}`.

- [ ] **Step 3: Implement the wiring**

`app/cin/renderer.py` — replace the `ShotRenderer.__init__` signature and first line

```python
    def __init__(self, plan: ShotPlan, job, *, video_style: str = "photorealistic",
                 color_grade: Optional[str] = None, width: int = WIDTH, height: int = HEIGHT):
        self.plan, self.job, self.w, self.h = plan, job, width, height
```

with

```python
    def __init__(self, plan: ShotPlan, job, *, video_style: str = "photorealistic",
                 color_grade: Optional[str] = None, width: int = WIDTH, height: int = HEIGHT,
                 captions=None):
        self.plan, self.job, self.w, self.h = plan, job, width, height
        self.captions = captions          # app.cin.captions.CaptionLayer or None
```

In `frame_at`, replace the final line `return np.ascontiguousarray(frame, dtype=np.uint8)` with:

```python
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        if self.captions is not None:                     # spec §7: composited inside the frame function
            # Copy first: an unzoomed still or clip frame can be the cached source array itself.
            frame = self.captions.composite(frame.copy(), t)
        return frame
```

Replace the head of `render` (from `def render(self, out_path, overlays: Optional[list] = None) -> Path:` through `write_video(clip, out_path, fps=self.plan.fps)`) with:

```python
    def render(self, out_path) -> Path:
        from moviepy import VideoClip
        clip = None
        try:
            # Built inside the try: a first-frame failure (VideoClip samples one) must still close
            # opened clip readers and surface as RenderError.
            clip = VideoClip(self.frame_at, duration=self.plan.duration).with_fps(self.plan.fps)
            write_video(clip, out_path, fps=self.plan.fps)
```

(the `except RenderError` / `except Exception` / `finally` blocks below stay as they are). Delete the whole `caption_overlays` function at the end of the file (lines 166-176) and the blank lines before it.

`app/cin/editor.py` — replace `from app.cin.renderer import ShotRenderer, caption_overlays` with:

```python
from app.cin.captions import build_caption_layer
from app.cin.renderer import ShotRenderer
```

In `render_job` replace

```python
        overlays = caption_overlays(plan, options.subtitle_style) if options.enable_subtitles else []
        ShotRenderer(plan, job, video_style=options.video_style,
                     color_grade=options.color_grade or None).render(video_tmp, overlays)
```

with

```python
        captions = build_caption_layer(plan, options.subtitle_style, report=report,
                                       enable_subtitles=options.enable_subtitles)
        ShotRenderer(plan, job, video_style=options.video_style, color_grade=options.color_grade or None,
                     captions=captions).render(video_tmp)
```

In `rebuild_plan` replace

```python
    old = ShotPlan.load(job.shot_plan)
    return build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))
```

with

```python
    old = ShotPlan.load(job.shot_plan)
    plan = build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))
    plan.hook_headline = old.hook_headline        # set from script.hook at generation; not in alignment.json
    return plan
```

`main.py` — before `from app.cin.shot_plan import PACING, build_shot_plan, plan_segments` (line 31) add:

```python
from app.cin.caption_groups import make_hook_headline
```

and in `_run_shot_editor` replace

```python
    plan = build_shot_plan(alignment, options.pacing, specs)
    for w in plan.warnings:
```

with

```python
    plan = build_shot_plan(alignment, options.pacing, specs)
    plan.hook_headline = make_hook_headline(script.hook, plan.duration)
    for w in plan.warnings:
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_captions_render.py tests/test_pipeline.py tests/test_cin_renderer.py tests/test_cin_editor.py tests/test_rerender.py -q -p no:cacheprovider`
Expected: all pass (≈ 2–3 min including the existing `render`-marked tests). Then confirm nothing references the removed adapter:

Run: `grep -rn "caption_overlays\|overlays=" app main.py tests`
Expected: only `tests/test_cin_editor.py`'s `_TinyRenderer.render(self, out_path, overlays=None)` (its default keeps it compatible; leave it).

- [ ] **Step 5: Commit**

```bash
git add app/cin/renderer.py app/cin/editor.py main.py tests/test_cin_captions_render.py tests/test_pipeline.py
git commit -m "feat: shot renderer composites caption layer in frame_at; hook headline from script

render_job reports font_fallback; --rerender keeps the headline; caption_overlays adapter removed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: End-to-end safe-zone render check, full suite, docs

**Files:**
- Test: `tests/test_cin_captions_render.py` (append the `render`-marked test)
- Modify: `CLAUDE.md` (Project Structure / Configuration notes), `.claude/memory.md` (progress)

**Interfaces:**
- Consumes: everything above; `tests.conftest.build_gold_job`, `make_color_clip`, `ffmpeg_exe`.
- Produces: nothing new.

- [ ] **Step 1: Write the end-to-end test**

Append to `tests/test_cin_captions_render.py`:

```python
def _frame(path, t):
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(1920, 1080, 3)


@pytest.mark.render
@pytest.mark.parametrize("style", ["bold_impact", "fire"])
def test_render_job_caption_pixels_stay_in_safe_zone(tmp_path, style):
    """Black clips, no particles: every bright pixel in the decoded final.mp4 is caption or headline."""
    job, alignment, specs = build_gold_job(tmp_path)
    for spec in specs:
        make_color_clip(job.resolve(spec.path), spec.requested_len, "black", size="360x640")
    plan = build_shot_plan(alignment, "standard", specs)
    plan.hook_headline = dict(HEADLINE)
    report = RunReport(job=job.name)
    final = render_job(job, plan, RenderOptions(subtitle_style=style, video_style="comic_book",
                                                enable_music=False, enable_sfx=False), report)
    assert "font_fallback" not in [w["code"] for w in report.warnings]
    peak_times = [g.words[-1].t0 + 0.09 for g in plan.captions]           # widest state of every group
    for t in [0.0, 1.0] + peak_times:
        f = _frame(final, t)
        top, bottom = ink(f[:1000], 40), ink(f[1000:], 40)
        assert bottom is not None, t
        x0, y0, x1, y1 = bottom
        assert 1250 <= y0 + 1000 and y1 + 1000 <= 1410 and x1 <= 990, (style, t, bottom)
        if t < 2.4:
            assert top is not None and 250 <= top[1] and top[3] <= 450, (style, t, top)
        elif t > 2.6:
            assert top is None, (style, t, top)
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_captions_render.py -m render -v -p no:cacheprovider`
Expected: `2 passed` (≈ 8 s each). This is a check of Tasks 1–5 on real encoded frames, so it passes on first run; if it fails, the reported `(style, t, bbox)` tells you which box or time to fix — fix the code, not the bounds.

- [ ] **Step 3: Eyeball one frame (manual, no assertion)**

Run:

```bash
.venv/Scripts/python.exe - <<'EOF'
import tempfile, subprocess
from pathlib import Path
from tests.conftest import build_gold_job, ffmpeg_exe
from app.cin.editor import RenderOptions, render_job
from app.cin.report import RunReport
from app.cin.shot_plan import build_shot_plan
tmp = Path(tempfile.mkdtemp())
job, alignment, specs = build_gold_job(tmp)
plan = build_shot_plan(alignment, "standard", specs)
plan.hook_headline = {"text": "Gold is heavier than you think", "t0": 0.0, "t1": 2.5}
final = render_job(job, plan, RenderOptions(subtitle_style="fire", enable_music=False, enable_sfx=False), RunReport(job=job.name))
subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-ss", "1.0", "-i", str(final), "-frames:v", "1", "output/phase_b_check.png"], check=True)
print("wrote output/phase_b_check.png")
EOF
```

Expected: `wrote output/phase_b_check.png`. Open it: Anton captions with one orange (active) word in the lower third, white headline in the top band, nothing touching the right edge. Do not commit the PNG.

- [ ] **Step 4: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --tb=line -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py`
Expected: exactly the 12 baseline failures listed in Global Constraints and no others (≈ 3–4 min; passed count = 314 + the 61 new tests (9 + 14 + 28 + 8 + 2) = 375 if no other session has added tests).

- [ ] **Step 5: Linux font check in the Docker image (before the first VPS deploy)**

`pytest` is not in `requirements.txt`, so the image check is a one-liner. Run (Docker Desktop or the VPS):

```bash
docker compose --profile generate run --rm --build generator python -c "from app.fonts import load_font; w=lambda f: f.getbbox('WILSDORF')[2]; t,_=load_font('Montserrat-Variable.ttf',75,100); b,fb=load_font('Montserrat-Variable.ttf',75,800); a,fa=load_font('Anton-Regular.ttf',75); n,fn=load_font('BebasNeue-Regular.ttf',75); print('fallback', fb, fa, fn, 'thin', w(t), 'extrabold', w(b)); assert not (fb or fa or fn) and w(b) - w(t) >= 15"
```

Expected: `fallback False False False thin 417 extrabold 438` (± 1 px) and exit code 0. A `True`, or `extrabold` within a few px of `thin`, means the image's Pillow cannot set the axis: stop and fix before deploying (captions would fall back to DejaVu with a `font_fallback` warning on every run). If Docker is not available on the dev box, record that this step is still owed in `.claude/memory.md`.

- [ ] **Step 6: Docs**

In `CLAUDE.md`, under `## Project Structure`, change the assets line to:

```
/assets     - Static assets (fonts, music, SFX, personas). assets/fonts/ holds the bundled OFL caption
              fonts (Montserrat variable, Anton, Bebas Neue + OFL texts); subtitle presets reference
              these files, so captions render the same on Windows and the Linux VPS.
```

In `.claude/memory.md`, add under the current progress section:

```
- Shot editor Phase B (captions + fonts) done: app/fonts.py, app/cin/caption_groups.py, app/cin/captions.py;
  captions composited in ShotRenderer.frame_at inside y 1254-1402 / x 94-986; hook headline top band
  [0, 2.5 s] set in main._run_shot_editor and kept by --rerender; font_fallback reported. Next: Phase C.
```

- [ ] **Step 7: Commit**

```bash
git add tests/test_cin_captions_render.py CLAUDE.md .claude/memory.md
git commit -m "test: decoded final.mp4 caption pixels stay in the safe zone; docs for bundled fonts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage (§7, §13 B):**
- Bundled OFL fonts referenced by file → Task 1 (`assets/fonts/`, `app/fonts.py`, presets `font_file`/`font_weight`).
- Missing font → warning + `font_fallback` → Task 1 (`load_font` warns), Task 4 (`build_caption_layer` reports), Task 5 (`render_job` passes the report).
- Grouping 1–3 words from aligned script tokens, break at punctuation and gaps > 0.25 s, numbers/names never split → Task 2.
- Active word in active colour, 1.0 → `active_scale` over 80 ms → Task 4 (`state_at`, `_rasterize`).
- Bottom placement y ≈ 1325 within 1250–1400, never below 1410 / right of 990 → Task 3 (`BOTTOM_BOX`, `layout_line`), Task 4 (clipping + tests), Task 6 (decoded frames).
- `center` keeps its position → interpreted as frame centre (decision above; the literal reading is not implementable because the classic code never read `position`).
- Captions from frame one → Task 4 (`_windows`, `test_captions_show_from_frame_one`), Task 5 (`frame_at(0.0)`).
- Hook headline y ≈ 250–450 for [0, 2.5 s], first sentence ≤ 8 words else omitted → Task 2 (text), Task 4 (band + timing), Task 5 (`main.py`, `rebuild_plan`), Task 6 (decoded frames).
- Rasterize once per highlight state, composite inside the frame function, no `ImageClip` per word → Task 4 (`sprite` cache, `test_each_highlight_state_is_rasterized_once`), Task 5 (`frame_at`, `caption_overlays` removed).
- Existing presets keep colours and stay selectable → Task 1 (`test_presets_reference_bundled_files_and_keep_colours`), Task 3 (`test_style_colours_come_from_the_preset`), Task 6 (`bold_impact` and `fire` rendered).
- §12 "caption pixels only inside the safe zone" → Task 4 (layer, all bottom presets, rolex sweep) and Task 6 (encoded video).
- `--classic` keeps working → Task 1 runs `tests/test_video_editor.py` and `tests/test_subtitle_styles.py`; `_create_karaoke_clips` is untouched.

**Placeholder scan:** every code step carries the full code; every run step names the command and the expected result.

**Type consistency:** `CaptionGroup`/`CaptionWord` are defined once (Task 2) and re-exported by `shot_plan`; `CaptionLayer(groups, style, duration, *, headline, width, height)`, `build_caption_layer(plan, subtitle_style, *, report, enable_subtitles, width, height)`, `ShotRenderer(..., captions=)`, `ShotRenderer.render(out_path)`, `make_hook_headline(hook, duration)` are used with the same names and parameters in Tasks 4–6.

**Review Focus:** each of the five lines names its pinning tests, and each test lives in the task that owns the code. An additional bug found while prototyping — compositing into the cached still array stamps captions onto every later frame — is pinned in Task 5 (`test_captions_do_not_burn_into_cached_source_frames`, verified to fail without the `.copy()`).

**Prototype evidence:** every code block in this plan was extracted verbatim into a scratch copy of `93d7223` (`%TEMP%/fvf_phaseb/verify`) and run: Task 1 14 passed, Task 2 13 passed, Task 3 13 passed, Task 4 28 passed; Task 5's red step gave exactly the 8 failures listed, and its green step plus the renderer/editor/rerender/video-editor/subtitle suites gave 47 passed; Task 6's `render` tests and eyeball script ran clean. The copy's full suite showed only the baseline failures present in tracked files (the 6 from the untracked `tests/test_trends.py` were absent from the copy).
