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

FVFactory is an automated short-form video creation system (TikTok/Shorts).

**Pipeline:** Topic -> Script -> Audio/Images -> MP4

**APIs Used:**
- OpenAI - Script generation
- ElevenLabs - Text-to-speech
- Leonardo/Midjourney - Image generation

## Project Structure

```
/app        - Application modules
/output     - Generated videos
/assets     - Static assets (fonts, images)
```

## Development Environment

- Python 3.14 (Docker: 3.12-slim)
- Virtual environment: `.venv/`
- IDE: PyCharm

## Commands

```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Run the application
python main.py

# Install dependencies
pip install -r requirements.txt

# Docker build
docker build -t fvfactory .

# Docker run
docker run --env-file .env -v ./output:/workspace/output fvfactory
```

## Configuration

Copy `.env.example` to `.env` and add your API keys.
