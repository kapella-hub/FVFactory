# Claude Memory

This file stores progress and context for Claude across sessions.

## Current Progress

**Status:** Full MVP with SadTalker Animation - Phase 13 complete

## Completed Work

- [x] Project structure created (/app, /output, /assets, /assets/music, /assets/personas)
- [x] requirements.txt with dependencies (including Whisper, Streamlit)
- [x] config.py with Pydantic settings for API keys + mascot + music + animation
- [x] Dockerfile with ffmpeg, imagemagick, fonts
- [x] ImageMagick policy.xml fix for text processing
- [x] main.py CLI orchestrator with full pipeline
- [x] Word-level subtitle engine using Whisper
- [x] Mascot integration for visual branding consistency
- [x] Background music with audio ducking
- [x] Streamlit web dashboard (app/dashboard.py)
- [x] Portrait animator module (app/animator.py) - Hedra & Replicate APIs
- [x] Hybrid compositor - Background images + Talking head overlay

## Project Overview

- **Name:** FVFactory
- **Purpose:** Automated short-form video creation (TikTok/Shorts)
- **Pipeline:** Topic -> Script -> Audio/Images -> MP4
- **Python:** 3.14 (Docker uses 3.12-slim until 3.14 image available)
- **Interfaces:** CLI (main.py) + Web UI (dashboard.py)

## Current Task

None - Full MVP complete with CLI, Web UI, and Hybrid Compositor

## Completed Modules

- [x] Script Generator with Mascot (app/content_engine.py)
- [x] Asset Manager with Style Consistency (app/asset_manager.py)
- [x] Video Editor with Subtitles + Music (app/video_editor.py)
- [x] Portrait Animator with Hedra/Replicate (app/animator.py)
- [x] CLI Orchestrator (main.py)
- [x] Streamlit Dashboard (app/dashboard.py)

## Module Details

### Script Generator (app/content_engine.py)
- `ScriptGenerator` class using OpenAI GPT-4o
- Outputs: hook, body, 5 image prompts, keywords
- Pydantic validation for structured output
- **Mascot Integration:**
  - `_build_system_prompt()` dynamically adds mascot instructions
  - Instructs LLM to include mascot character in every image prompt
  - Character performs actions related to the scene
  - Configurable via `MASCOT_ENABLED` and `MASCOT_PROMPT`

### Asset Manager (app/asset_manager.py)
- `AssetManager` class for audio and image generation
- Audio: ElevenLabs primary, OpenAI TTS fallback
- Images: DALL-E 3 or mock placeholders
- **Style Consistency:**
  - `_enhance_prompt_with_style()` appends style keywords
  - Prevents style drift between scenes
  - Configurable via `IMAGE_STYLE` setting
- Temp file management with cleanup

### Video Editor (app/video_editor.py)
- `VideoEditor` class with `assemble_video()` method
- Ken Burns effect: slow zoom (1.0 -> 1.1) for dynamic visuals
- **Subtitle Engine:**
  - `generate_subtitles(audio_path)` - Whisper transcription
  - Word-level timestamps grouped into 3-word chunks
  - Style: Yellow text, black stroke (viral TikTok style)
  - Lazy-loaded Whisper 'base' model
- **Background Music:**
  - `_get_random_music_file()` - Picks random MP3 from assets/music/
  - `_prepare_background_music()` - Loops or trims to match duration
  - `_mix_audio()` - Combines voice + music with CompositeAudioClip
  - Audio ducking: Music at 10%, Voice at 100%
- Output: 1080x1920 vertical HD, 24fps, libx264 codec
- **Hybrid Compositor (Phase 12):**
  - `assemble_hybrid_video()` - Professional multi-layer composition
  - Layer 1: Background images with Ken Burns effect
  - Layer 2: Talking head overlay (bottom-right, 30% screen width)
  - Layer 3: Word-level subtitles on top
  - Circle crop: `_apply_circle_crop()` for round talking head overlay
  - Chroma key: `_apply_chroma_key()` for green screen removal
  - Audio from talking head video mixed with background music

### Portrait Animator (app/animator.py)
- `PortraitAnimator` class for audio-driven portrait animation
- **Two Animation APIs:**
  - Hedra API (primary) - Full portrait animation service
  - Replicate SadTalker (fallback) - Audio-driven lip-sync model
- **SadTalker Settings (Phase 13):**
  - Model: `cjwbw/sadtalker`
  - `still=True` - Reduces head movement for stable focus
  - `enhancer="gfpgan"` - Makes face sharp, not blurry
  - Uses `replicate` Python library for simpler API calls
- **Content Filter Handling:**
  - Returns `None` if content filter blocks realistic faces
  - Callers fall back to standard slideshow mode gracefully
- **Persona Management:**
  - `get_available_personas()` - Lists images in assets/personas/
  - `get_persona_path()` - Returns full path to persona image
  - Supports PNG, JPG, JPEG, WEBP formats
- Configurable via HEDRA_API_KEY or REPLICATE_API_TOKEN

### Streamlit Dashboard (app/dashboard.py)
- **Sidebar Configuration:**
  - **Video Mode Selection:** Image Slideshow vs Hybrid (Images + Talking Head)
  - Persona dropdown with preview + chroma key option (if hybrid mode)
  - Niche/Mascot dropdown with preset mascots
  - Video topic input field
  - Options: mock images, subtitles, music
  - Generate Script button
- **Script Review Stage:**
  - Editable hook and body text areas
  - Editable image prompts (always shown for both modes)
  - Character count and estimated duration
  - Approve & Generate Assets button
- **Asset Review Stage:**
  - Audio preview player
  - Background images grid (3 columns) with regenerate buttons
  - Talking head preview (if hybrid mode)
  - Render Video button
- **Video Preview Stage:**
  - Video player
  - Download button
  - Video details (resolution, FPS, file size, mode used)
- **Niche Presets:**
  - Default Robot, Finance Guru, Tech Explainer
  - History Buff, Science Explainer, No Mascot

## Configuration (config.py)

```python
# Portrait Animation APIs
hedra_api_key: str = ""
replicate_api_token: str = ""

# Persona settings (talking head mode)
personas_dir: str = "assets/personas"
use_persona: bool = False
default_persona: str = ""

# Mascot settings
mascot_enabled: bool = False  # never on photoreal (sub-project 2)
mascot_prompt: str = "A cute, futuristic robot with glowing blue eyes..."
image_style: str = ""  # "" = derived from video_style

# Background music settings
music_enabled: bool = True
music_dir: str = "assets/music"
music_volume: float = 0.1   # 10% for background
voice_volume: float = 1.0   # 100% for voiceover
```

## Dependencies

```
openai
moviepy
requests
python-dotenv
pydantic
pydantic-settings
Pillow
openai-whisper
setuptools-rust
torch
streamlit
replicate
```

## Usage

### CLI Interface
```bash
python main.py
```

### Web Interface
```bash
streamlit run app/dashboard.py
```

## Next Steps (Future Enhancements)

- Multiple voice options
- Batch processing
- Video templates/presets
- Custom subtitle styling options
- Dynamic audio ducking based on voice detection
- User authentication for multi-user support
- Additional portrait animation providers
- Talking head position options (corners, center)
- Custom overlay sizes and shapes

## Shot editor Phase A - done (2026-10-03)

- Landed: shot-based editor (alignment, cut DP, framing, clip sourcing, shot renderer, two-pass loudnorm mux), job folders `output/<job>/{final.mp4,run_report.json,sources/}`, `--pacing/--strict/--classic`, `--rerender <job>` (zero API calls).
- Verified: full suite = 12 known unrelated failures (4 test_uploader, 6 test_trends, 1 test_trend_scout, 1 test_local_image_gen); mock end-to-end and fast re-render OK.
- Fixed since: alignment works (ffmpeg decode, 97.2% match on real narration); final true peak is now -1.38 dBTP (loudnorm target -1.5); Claude CLI output is decoded as UTF-8 (no PYTHONUTF8 needed).
- Next: Phase B (hook headline, caption rewrite/safe zone), Phase C (music/SFX libraries, ducking, voice polish), Phase D (web/scheduler plumbing).

## Shot editor Phase B - done (2026-10-03)

- Shot editor Phase B (captions + fonts) done: app/fonts.py, app/cin/caption_groups.py, app/cin/captions.py;
  captions composited in ShotRenderer.frame_at inside y 1254-1402 / x 94-986; hook headline top band
  [0, 2.5 s] set in main._run_shot_editor and kept by --rerender; font_fallback reported. Next: Phase C.
- Verified: render-marked end-to-end test (bold_impact, fire) passes on decoded final.mp4; full suite = only the 12 known failures.
- OWED before first VPS deploy: Linux font check inside the Docker image (Docker daemon was not running on the dev box, so it was skipped). Command:
  docker compose --profile generate run --rm --build generator python -c "from app.fonts import load_font; w=lambda f: f.getbbox('WILSDORF')[2]; t,_=load_font('Montserrat-Variable.ttf',75,100); b,fb=load_font('Montserrat-Variable.ttf',75,800); a,fa=load_font('Anton-Regular.ttf',75); n,fn=load_font('BebasNeue-Regular.ttf',75); print('fallback', fb, fa, fn, 'thin', w(t), 'extrabold', w(b)); assert not (fb or fa or fn) and w(b) - w(t) >= 15"
  Expected: fallback False False False thin 417 extrabold 438 (+-1 px). Windows equivalent already passes (FreeType 2.13.3, axis Weight 100-900).

## Shot editor Phase C - done (2026-10-03)

- Phase C (music/SFX/ducking/voice polish) implemented per docs/superpowers/plans/2026-10-02-shot-based-editor-phase-c.md.
  Libraries are empty until the user adds tracks or runs the builders (ElevenLabs Music needs a paid plan).
- New CLI: --music-source, --build-music-library, --build-sfx-library, --per-mood, --moods, --yes (builders run before validate_config; always confirm cost first).
- Next: Phase D (web/scheduler plumbing for music_source).

## Shot editor Phase D - done (2026-10-03)
- Options plumbing: app/run_options.py (pipeline_kwargs: missing/None/"" = Settings default; bool strings parsed;
  OptionError -> HTTP 422). Web /api/generate, scheduler slots, GeneratorWorker (SFX no longer forced off) all use it.
- Run report surfaced: app/cin/report.load_summary (never raises); WS complete/error carry {video_id, status, warnings};
  failed run_pipeline exceptions carry job_dir; report writes use save_quietly. Library shows warning badges.
- data/config.json is now applied at server start (apply_saved_settings skips bad values).
- Housekeeping: local images into job folder, faststart bounded read, loudnorm NaN/JSON guard, dead cin modules
  (audio_analysis, depth, parallax, kinetic_text) and main.generate_output_filename removed.
- Spec section 10 amended (classic editor also for persona runs and cinematic_enabled off); section 15 records implementation deviations.
- Open items: Linux/Docker font-weight check before first VPS deploy (see Phase B command);
  first live ElevenLabs music/SFX library build unverified (request shape);
  fastapi/apscheduler routes and scheduler untested locally (only py_compiled; verify in Docker/VPS, incl. live browser pass);
  a real paid end-to-end run with motion clips has not been done.
## Script upgrades (sub-project 2) - done (2026-10-03)
- app/script_quality.py: word budget 2.6 words/s +-15% (short 30 s / medium 45 s / long 60 s), scene ranges
  short 6-8 / medium 9-11 / long 11-14 (keeps a scene inside one 6 s clip), scene roles hook|open_loop|body|rehook|payoff|loop.
- ScriptGenerator.write_script -> ScriptResult(script, warnings, length): one revision call when the draft is off budget;
  never loses a valid draft. ScriptOutput gains hook_headline + scene_roles (null/mistyped values coerced, never a failure).
- Roles stored in shot_plan.json (Scene.role); styled transitions land on rehook/payoff/loop; hook headline comes from the
  script; --rerender keeps both. run_report.json has a "script" section (words, words_per_second, revision, roles).
- Image style follows video_style (STYLE_SUFFIX); explicit IMAGE_STYLE in .env overrides every style. mascot_enabled defaults
  False and the mascot is never used on photorealistic runs. Web UI duration labels show seconds.
- Spec docs/superpowers/specs/2026-10-03-script-upgrades-design.md; plan docs/superpowers/plans/2026-10-03-script-upgrades.md.
- Deferred to sub-project 3: cost-log the revision call (OpenAI fallback only); calibrate WORDS_PER_SECOND from
  run_report script.words_per_second after the first paid runs.
- Sub-project 3 (quality tiers) followed; see below.
## Quality tiers (sub-project 3) - done (2026-10-03)
- Tiers pick the motion model: standard -> kling (Kling v3 Standard, $0.084/s), premium -> kling-pro (Kling v3 Pro,
  $0.112/s), custom -> settings.fal_video_model. Kling clips are sent with generate_audio=false and whole-second lengths
  "3".."15". Old Kling v1/v1.5 endpoints were dead on fal; the keys now point at v3. h3-turbo / h3 (MiniMax H3) are opt-in
  via custom, unverified 9:16. hailuo = Minimax video-01 ($0.50/clip). Prices: settings.clip_pricing (list prices).
- app/cin/tiers.py (resolve_clip_model), app/cin/cost_estimate.py (pre_tts / pre_clips estimates, CostCapError,
  tier_estimates, clip_model_options), app/motion_gen.build_fal_arguments (per-model fal payload).
- Cap max_cost_per_video (0 = off; --max-cost, web form, scheduler slot, Settings): checked after the script (before TTS)
  and before clip generation; over cap the run fails with cost_cap_exceeded - never degrades to stills/cheaper model.
  Medium video estimate ~ $4.5 standard / $5.9 premium total (list price).
- run_report.json: cost.estimated {pre_tts, pre_clips}, cost.cap; options quality_tier / clip_model / max_cost.
  Warning tier_ignored. Classic/persona runs get checkpoint 1 too (one clip per image at 5 s; estimate_classic).
  Failed or capped runs log what they already paid (_log_partial_costs: script, narration, images on disk, clips).
- Open items (paid, need user approval): first Standard/Premium paid runs (check 9:16 + cost.actual vs estimate);
  one H3 Turbo test clip (~$0.20 at 768P) before H3 could become the Standard default (paid checks need
  FAL_API_KEY, which is not in the local .env);
  calibrate WORDS_PER_SECOND / SCENE_RANGE from run reports (Kling allows 3-15 s clips now).
