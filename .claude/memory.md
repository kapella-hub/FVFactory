# Claude Memory

This file stores progress and context for Claude across sessions.

## Current Progress

**Status:** Full MVP with Web UI - Streamlit dashboard complete

## Completed Work

- [x] Project structure created (/app, /output, /assets, /assets/music)
- [x] requirements.txt with dependencies (including Whisper, Streamlit)
- [x] config.py with Pydantic settings for API keys + mascot + music
- [x] Dockerfile with ffmpeg, imagemagick, fonts
- [x] ImageMagick policy.xml fix for text processing
- [x] main.py CLI orchestrator with full pipeline
- [x] Word-level subtitle engine using Whisper
- [x] Mascot integration for visual branding consistency
- [x] Background music with audio ducking
- [x] Streamlit web dashboard (app/dashboard.py)

## Project Overview

- **Name:** FVFactory
- **Purpose:** Automated short-form video creation (TikTok/Shorts)
- **Pipeline:** Topic -> Script -> Audio/Images -> MP4
- **Python:** 3.14 (Docker uses 3.12-slim until 3.14 image available)
- **Interfaces:** CLI (main.py) + Web UI (dashboard.py)

## Current Task

None - Full MVP complete with both CLI and Web UI

## Completed Modules

- [x] Script Generator with Mascot (app/content_engine.py)
- [x] Asset Manager with Style Consistency (app/asset_manager.py)
- [x] Video Editor with Subtitles + Music (app/video_editor.py)
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

### Streamlit Dashboard (app/dashboard.py)
- **Sidebar Configuration:**
  - Niche/Persona dropdown with preset mascots
  - Video topic input field
  - Options: mock images, subtitles, music
  - Generate Script button
- **Script Review Stage:**
  - Editable hook and body text areas
  - Editable image prompts
  - Character count and estimated duration
  - Approve & Generate Assets button
- **Asset Review Stage:**
  - Audio preview player
  - Image grid (3 columns)
  - Regenerate button per image
  - Render Video button
- **Video Preview Stage:**
  - Video player
  - Download button
  - Video details (resolution, FPS, file size)
- **Niche Presets:**
  - Default Robot, Finance Guru, Tech Explainer
  - History Buff, Science Explainer, No Mascot

## Configuration (config.py)

```python
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
