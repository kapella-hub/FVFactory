# FVFactory: Local Models Migration + Scheduler + UI Overhaul

**Date:** 2026-03-26
**Status:** Draft

---

## 1. Goals

1. Replace expensive API services (Replicate Flux, Replicate Minimax, OpenAI LLM) with local models and Claude CLI
2. Add a Python-based job scheduler for automated video generation, configurable from the UI
3. Overhaul the UI from Streamlit to FastAPI + vanilla HTML/JS with full configuration management
4. Maintain the ability to switch back to API providers via config

## 2. Non-Goals

- Replacing ElevenLabs TTS (stays as API)
- Replacing OpenAI TTS fallback (stays as API)
- Auto-uploading to YouTube (scheduler generates only)
- Mobile or multi-user support
- Authentication (local tool, single user)

## 3. Provider Migration

### 3.1 Script Generation: OpenAI GPT → Claude CLI

**Current:** `app/llm.py` calls OpenAI `chat.completions.create()` with `gpt-5.4-mini`.

**New:** Subprocess call to `claude -p "<prompt>"` with `--output-format json` where needed.

**Implementation:**
- Add `ClaudeCLIProvider` class in `app/llm.py` alongside existing `OpenAIProvider`
- Provider selected by `settings.llm_provider` (`claude_cli` | `openai`)
- Claude CLI invoked via `subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, timeout=120)`
- System prompts prepended to the user prompt as context
- JSON output parsed from stdout; retry once on parse failure
- Timeout: 120 seconds per call (configurable)

**Affected files:**
- `app/llm.py` — Add provider abstraction + Claude CLI provider
- `app/config.py` — Add `llm_provider` setting

**Risk:** Claude CLI output format may vary. Mitigation: validate JSON structure, retry with explicit "respond only with JSON" instruction on failure.

### 3.2 Image Generation: Replicate Flux 1.1 Pro → FLUX.2 Klein 4B (Local)

**Current:** `app/replicate_api.py` and `app/asset_manager.py` call Replicate API for Flux 1.1 Pro.

**New:** Local inference via Hugging Face `diffusers` library with MPS (Metal Performance Shaders) backend.

**Model:** `black-forest-labs/FLUX.2-klein-4B`
- ~13GB memory footprint
- Optimized for Apple Silicon MPS
- 5-15 seconds per image on M-series chips

**Implementation:**
- New file: `app/local_image_gen.py`
  - `LocalImageGenerator` class
  - Loads model on first call, keeps in memory for batch efficiency
  - `generate(prompt: str, width: int, height: int, output_path: str) -> str`
  - Default aspect ratio: 9:16 (1080x1920) for vertical short-form video
  - Uses `torch.mps` device, attention slicing enabled for memory efficiency
  - Calls `torch.mps.empty_cache()` between generations to prevent memory buildup
- Add `LocalFluxProvider` in `app/asset_manager.py` alongside existing Replicate provider
- Provider selected by `settings.image_provider` (`local` | `replicate`)

**Affected files:**
- `app/local_image_gen.py` — New file
- `app/asset_manager.py` — Add provider abstraction for image generation
- `app/config.py` — Add `image_provider` setting

**Model download:** Automatic on first run via `diffusers` to `~/.cache/huggingface/`. ~8GB download.

### 3.3 Motion Video: Replicate Minimax → Wan2.1 14B I2V (Local)

**Current:** `app/replicate_api.py` and `app/motion_gen.py` call Replicate API for Minimax image-to-video.

**New:** Local inference via Hugging Face `diffusers` with Wan2.1 14B image-to-video model.

**Model:** `Wan-AI/Wan2.1-I2V-14B-720P`
- ~40GB memory with FP8 quantization and offloading
- Fits in 48GB unified memory with aggressive memory management
- Expect 15-30 minutes per clip (speed not a concern per user)

**Implementation:**
- New file: `app/local_video_gen.py`
  - `LocalVideoGenerator` class
  - Loads model with CPU offloading for T5 text encoder (`--t5_cpu` equivalent)
  - FP8 quantization enabled to fit in 48GB
  - `generate(image_path: str, prompt: str, output_path: str, duration: float = 5.0) -> str`
  - Output: MP4 video clip, 480p-720p depending on memory pressure
  - Ken Burns fallback if generation fails or OOMs
- Add `LocalWanProvider` in `app/motion_gen.py` alongside existing Replicate provider
- Provider selected by `settings.motion_provider` (`local` | `replicate`)

**Affected files:**
- `app/local_video_gen.py` — New file
- `app/motion_gen.py` — Add provider abstraction for motion generation
- `app/config.py` — Add `motion_provider` setting

**Memory management:**
- T5 encoder offloaded to CPU during diffusion steps
- Model unloaded after batch completion if memory pressure detected
- `torch.mps.empty_cache()` between clips
- Attention slicing enabled

**Risk:** 14B model on 48GB is tight. Mitigation: automatic fallback to Ken Burns effect if OOM occurs. Config option to use 1.3B model instead (`settings.wan_model_size`: `14b` | `1.3b`).

### 3.4 Unchanged Components

| Component | Status | Notes |
|---|---|---|
| ElevenLabs TTS | Keep API | Primary voice generation |
| OpenAI TTS | Keep API | Fallback voice generation |
| Whisper | Already local | No changes needed |
| Google Trends | Keep (no auth) | Free, no API key |
| Reddit scraping | Keep (no auth) | Free, no API key |
| YouTube upload | Keep API | OAuth2, unchanged |
| Video editor | Unchanged | MoviePy + ffmpeg |

## 4. Job Scheduler

### 4.1 Overview

A Python-based scheduler that runs video generation jobs on configurable schedules. Runs as a background thread within the FastAPI server process.

### 4.2 Scheduler Engine

**Library:** `APScheduler` (Advanced Python Scheduler) v3.x
- Supports cron-style scheduling
- Persistent job store via SQLite (survives restarts)
- Thread-based executor (one job at a time to avoid memory contention with local models)

### 4.3 Data Model

```python
class ScheduledJob:
    id: str                  # UUID
    name: str                # User-friendly name, e.g. "Daily Stoicism Video"
    cron_expression: str     # e.g. "0 9 * * *" (9am daily)
    enabled: bool            # Toggle on/off
    config: VideoConfig      # Full generation config (niche, scenes, style, etc.)
    last_run: datetime | None
    last_status: str | None  # "success" | "failed" | "running"
    created_at: datetime
```

### 4.4 Job Store

SQLite database at `data/scheduler.db`:
- `scheduled_jobs` — Job definitions and schedules
- `job_runs` — Execution history (start time, end time, status, output path, error message)

### 4.5 Execution Flow

1. APScheduler triggers job at scheduled time
2. Job runner loads `VideoConfig` from the job definition
3. Runs the same pipeline as `main.py --auto` with that config
4. Logs result to `job_runs` table
5. On failure: logs error, does not retry (next scheduled run will try again)

### 4.6 Concurrency

Single-threaded executor — only one job runs at a time. If a job is still running when the next trigger fires, the new trigger is skipped (coalesce). This prevents memory contention with local models.

### 4.7 API Endpoints

```
GET    /api/scheduler/jobs          — List all scheduled jobs
POST   /api/scheduler/jobs          — Create a new scheduled job
GET    /api/scheduler/jobs/{id}     — Get job details
PUT    /api/scheduler/jobs/{id}     — Update job (schedule, config, enabled)
DELETE /api/scheduler/jobs/{id}     — Delete job
POST   /api/scheduler/jobs/{id}/run — Trigger immediate run
GET    /api/scheduler/history       — Job execution history
```

## 5. UI Overhaul

### 5.1 Technology Stack

- **Backend:** FastAPI (Python)
- **Frontend:** Vanilla HTML + CSS + JavaScript (no build step, no Node.js)
- **Templating:** Static HTML files served from `app/web/static/`
- **API communication:** Fetch API, JSON
- **Real-time updates:** WebSocket for job status and generation progress
- **Styling:** CSS custom properties (design tokens), responsive layout

### 5.2 Page Structure

#### Dashboard (Home)
- Overview cards: total videos generated, cost savings (local vs API), recent activity
- Active job status with real-time progress (WebSocket)
- Quick actions: "Generate Now", "View Library"

#### Video Library
- Grid view of generated videos with thumbnails
- Filter by date, niche, status
- Click to view details: metadata, cost breakdown, generation log
- Play video inline

#### Generate
- On-demand video generation form
- Topic input (manual or auto-discover)
- Niche selector
- Scene count slider
- Provider toggles (local vs API for each component)
- Subtitle style picker
- "Generate" button with real-time progress via WebSocket

#### Scheduler
- List of scheduled jobs with status indicators (enabled/disabled, last run, next run)
- Create/edit job modal with cron builder (friendly UI, not raw cron syntax)
  - Presets: "Every day at 9am", "Twice daily", "Weekdays only", etc.
  - Custom cron input for power users
- Job history timeline
- Enable/disable toggle per job
- "Run Now" button

#### Settings
All configuration parameters exposed in a clean, grouped settings panel:

**Provider Settings**
- LLM provider toggle (Claude CLI / OpenAI)
- Image provider toggle (Local FLUX / Replicate)
- Motion provider toggle (Local Wan2.1 / Replicate)
- TTS provider (ElevenLabs config, voice selection)

**Generation Defaults**
- Default niche
- Scene count (min/max/default)
- Subtitle style
- Motion enabled/disabled
- SFX and music toggles
- Image style (photorealistic, illustration, etc.)

**Model Settings**
- Wan model size (14B / 1.3B)
- FLUX model variant
- Whisper model size
- Claude CLI timeout

**API Keys**
- OpenAI API key (masked input)
- ElevenLabs API key (masked input)
- Replicate API token (masked input)
- YouTube OAuth status

**Output Settings**
- Output directory
- Video resolution
- Thumbnail generation toggle

**System**
- Model cache location
- Memory usage monitor (current GPU/unified memory usage)
- Model download status (which models are cached locally)

### 5.3 Design Principles

- **Dark theme** with high contrast — professional video production aesthetic
- **Responsive** — works on laptop screens, no mobile optimization needed
- **Minimal clicks** — common actions are one click from dashboard
- **Progressive disclosure** — simple defaults shown first, advanced options expandable
- **Real-time feedback** — WebSocket-driven progress for all generation tasks
- **No page reloads** — SPA-like navigation via client-side routing (History API)

### 5.4 Layout

```
┌─────────────────────────────────────────────────┐
│  FVFactory          Dashboard │ Library │ ...    │
├────────┬────────────────────────────────────────┤
│        │                                        │
│  Nav   │           Main Content                 │
│        │                                        │
│  Home  │                                        │
│  Gen   │                                        │
│  Lib   │                                        │
│  Sched │                                        │
│  Set   │                                        │
│        │                                        │
└────────┴────────────────────────────────────────┘
```

Sidebar navigation, fixed. Main content area scrolls. Sidebar collapses to icons on narrow viewports.

## 6. Configuration Persistence

### 6.1 Approach

All settings stored in a JSON config file: `data/config.json`. The existing `.env` / Pydantic Settings approach remains for API keys and secrets. Non-secret configuration (provider choices, generation defaults, UI preferences) moves to `data/config.json` for easy UI editing.

### 6.2 Config Hierarchy (highest to lowest priority)

1. CLI flags (`--local`, `--api`, etc.)
2. `data/config.json` (UI-managed settings)
3. `.env` file (API keys, secrets)
4. `app/config.py` defaults

### 6.3 API Endpoints

```
GET  /api/config          — Get all current configuration
PUT  /api/config          — Update configuration (partial update, merge)
POST /api/config/reset    — Reset to defaults
```

## 7. FastAPI Server Structure

### 7.1 File Organization

```
app/
  web/
    server.py            — FastAPI app, lifespan, WebSocket manager
    routes/
      api_generate.py    — /api/generate endpoints
      api_library.py     — /api/library endpoints
      api_scheduler.py   — /api/scheduler endpoints
      api_config.py      — /api/config endpoints
      ws.py              — WebSocket endpoint for real-time updates
    static/
      index.html         — SPA shell
      css/
        styles.css       — Main stylesheet
        tokens.css       — Design tokens (colors, spacing, typography)
      js/
        app.js           — Router, navigation, shared state
        dashboard.js     — Dashboard page
        generate.js      — Generate page
        library.js       — Library page
        scheduler.js     — Scheduler page
        settings.js      — Settings page
        ws.js            — WebSocket client
```

### 7.2 Server Startup

```bash
# New entry point
python -m app.web.server

# Or via main.py
python main.py --serve
```

Starts FastAPI on `http://localhost:8000`. Opens browser automatically.

### 7.3 CLI Remains Functional

`main.py` CLI continues to work for headless/scripted use. The web UI calls the same pipeline code — no duplication.

## 8. New Dependencies

```
# Local model inference
diffusers>=0.32.0
transformers>=4.47.0
accelerate>=1.2.0
safetensors>=0.4.0

# Web server
fastapi>=0.115.0
uvicorn>=0.34.0
websockets>=14.0

# Scheduler
apscheduler>=3.10.0

# Database (scheduler persistence)
aiosqlite>=0.20.0
```

## 9. Migration Strategy

### Phase 1: Provider Abstraction
- Refactor `llm.py`, `asset_manager.py`, `motion_gen.py` with provider pattern
- Add config flags for provider selection
- Existing API behavior unchanged (default providers = API)

### Phase 2: Local Model Providers
- Implement `local_image_gen.py` (FLUX.2 Klein 4B)
- Implement `local_video_gen.py` (Wan2.1 14B)
- Implement Claude CLI provider in `llm.py`
- Add model download/cache management

### Phase 3: FastAPI Server + UI
- Build FastAPI server with API routes
- Build frontend SPA (HTML/CSS/JS)
- Implement all settings pages
- Wire up WebSocket for real-time progress

### Phase 4: Scheduler
- Implement APScheduler integration
- Build scheduler UI (job list, cron builder, history)
- SQLite persistence for jobs and history

### Phase 5: Integration Testing
- End-to-end test: scheduled job → local models → video output
- Memory profiling on M5 Pro with 48GB
- Fallback testing (OOM → Ken Burns, provider switching)

## 10. Open Questions

1. **Model warm-up strategy:** Keep models loaded in memory between jobs (faster, uses ~40GB constantly) or load/unload per job (slower, frees memory between runs)?
   - **Recommendation:** Load on demand, unload after idle timeout (5 min). Balances memory and speed.

2. **Wan2.1 14B feasibility:** May OOM on 48GB with other processes running. Need to test early and have 1.3B fallback ready.

3. **Claude CLI rate limits:** Unknown if there are per-minute limits on `claude -p` calls. Need to test with batch generation.
