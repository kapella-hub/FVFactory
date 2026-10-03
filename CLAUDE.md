# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Persistence

At the start of each session, read `.claude/memory.md` to restore context from previous sessions. Before ending a session or when completing significant work, update `.claude/memory.md` with current progress, pending tasks, and any important notes.

## Implementation Planning

For large or complex prompts:

1. **Create a plan first** - Break down the work into discrete steps before writing any code
2. **Document the plan** - Write the implementation plan to `.claude/memory.md`
3. **Follow the plan** - Work through each step systematically, marking items complete as you go
4. **Update as needed** - If the plan needs adjustment during implementation, update it

## Task Completion Requirements

Before marking any task as complete:

1. **Run the code** - Execute the application or relevant tests to verify it works without errors
2. **Validate all requirements** - Review the original prompt and confirm every requested feature/change was implemented
3. **Test functionality** - Verify the implemented features behave as expected

Never hand off work until all requirements are validated and code runs successfully.

## Project Overview

FVFactory v2 is a professional-grade automated short-form video creation system (TikTok/Shorts).

**Pipeline:** Topic (auto or manual) -> Script (with motion prompts) -> Audio/Images/Motion Clips -> MP4

**APIs Used:**
- OpenAI GPT-4o - Script generation + metadata
- ElevenLabs Multilingual v2 - Text-to-speech (OpenAI TTS fallback)
- Replicate Flux - Image generation
- Replicate Minimax - Image-to-video motion clips
- Whisper (local) - Word-level transcription for subtitles

## Project Structure

```
/app        - Application modules
/output     - Generated videos, metadata, thumbnails
/assets     - Static assets (fonts, music, SFX, personas). assets/fonts/ holds the bundled OFL caption
              fonts (Montserrat variable, Anton, Bebas Neue + OFL texts); subtitle presets reference
              these files, so captions render the same on Windows and the Linux VPS.
/tests      - Unit tests
/docs       - Specs and plans
```

## Development Environment

- Python 3.14 (Docker: 3.12-slim)
- Virtual environment: `.venv/`
- IDE: PyCharm

## Commands

```bash
# Interactive mode
python main.py

# Auto mode (discover trend, generate, render)
python main.py --auto

# Auto with niche filter
python main.py --auto --niche tech

# Batch mode (5 videos)
python main.py --batch 5 --niche finance

# Series mode
python main.py --series "History of Money" --parts 3

# Options
python main.py --auto --no-motion --subtitle-style neon_glow
python main.py --auto --mock  # Use mock images (free)
python main.py --auto --no-sfx --no-music

# Web UI
python main.py --serve

# Shot editor options (default pacing: standard)
python main.py --auto --pacing fast          # calm | standard | fast
python main.py --auto --strict               # fail instead of shipping a still when a clip fails
python main.py --auto --classic              # old Ken Burns editor

# Rebuild a finished job from output/<job>/sources with zero API calls
python main.py --rerender output/<job> --pacing fast --subtitle-style neon_glow --color-grade tech
python main.py --rerender output/<job> --music-source generated   # re-pick music from another pool

# Music / SFX (shot editor). Libraries: assets/music/<mood>/ (yours), assets/music/<mood>/generated/,
# assets/sfx/ (yours: whoosh*, impact*, riser*), assets/sfx/generated/. LRU history: data/music_usage.json
python main.py --auto --music-source mine    # mine | generated | any (default) | none
python main.py --build-sfx-library           # ElevenLabs Sound Effects, ~$0.02, asks first
python main.py --build-music-library --per-mood 5 --moods epic,dark   # ElevenLabs Music, $0.15/track, asks first (--yes skips)
# The ElevenLabs music API needs a paid ElevenLabs plan (commercial use: Starter or above).

# Run tests
python -m pytest tests/ -v

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and add your API keys.
