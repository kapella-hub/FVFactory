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

# Options
python main.py --auto --no-motion --subtitle-style neon_glow
python main.py --auto --mock  # Use mock images (free)
python main.py --auto --no-sfx --no-music

# Web UI. Generate form, Scheduler slots and Settings page carry pacing, music source, strict, quality tier and max cost
# ("Default" = the Settings value; Settings persist in data/config.json and are re-applied at start).
# After a run the Generate page shows output/<job>/run_report.json warnings; the Library flags them.
python main.py --serve

# Quality tiers: the motion model per video (every shot stays motion). Default: settings.quality_tier
python main.py --auto --tier standard        # MiniMax H3 Max Turbo, 768p (~$2-2.7 of motion for a medium video)
python main.py --auto --tier premium         # Kling v3 Pro (~$5.6)
python main.py --auto --tier custom          # settings.fal_video_model: kling | kling-pro | hailuo | h3-turbo | h3
python main.py --auto --max-cost 5           # stop before the next paid stage if the estimate exceeds $5 (0 = no cap)
# Estimates (pre_tts, pre_clips) and the cap land in output/<job>/run_report.json "cost". List prices
# live in settings.clip_pricing; a cap never swaps in stills or a cheaper model.

# Shot editor options (default pacing: standard)
python main.py --auto --pacing fast          # calm | standard | fast
python main.py --auto --strict               # fail instead of shipping a still when a clip fails
python main.py --auto --classic              # old Ken Burns editor (also used for persona runs
                                             # and when the cinematic_enabled setting is off)

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

**Script LLM** (`app/llm.py`): `LLM_PROVIDER` = `claude_cli` (Claude Code headless, default) | `codex` (Codex CLI
headless) | `openai` (paid API). `LLM_FALLBACK` (default `codex,openai`; `none` = off) is tried in order when it
fails. Models: `CLAUDE_CLI_MODEL`, `CODEX_MODEL`, `OPENAI_MODEL`. The provider that answered is recorded at
`run_report.json` `script.llm_provider` and picks the LLM cost-log item. A provider that fails, or answers with empty
or invalid JSON, falls through to the next. The Docker image installs both CLIs; auth via `CLAUDE_CODE_OAUTH_TOKEN`
(`claude setup-token`) and `codex login` (mounted `~/.codex`) or `CODEX_API_KEY`, all in `.env` (no compose
`env_file`). The CLIs never inherit `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `CODEX_API_KEY` /
`CLAUDE_CODE_OAUTH_TOKEN` from the environment; each gets only its own setting. Model names are restricted to
`[A-Za-z0-9._:-]` (the Windows `codex.cmd` shim runs through cmd.exe). Web UI CORS is off unless `CORS_ORIGINS`
lists origins; `CORS_ORIGINS` and the two CLI tokens cannot be set from the Settings page.
