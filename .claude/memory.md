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
mascot_enabled: bool = True
mascot_prompt: str = "A cute, futuristic robot with glowing blue eyes..."
image_style: str = "vector art style, vibrant colors, clean lines"

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
