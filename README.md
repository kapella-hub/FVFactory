# FVFactory

Automated short-form video creation for TikTok, YouTube Shorts and Instagram Reels. Every shot is AI motion
footage; captions, voiceover, music and loudness are handled for you.

**Pipeline:** topic / your story → script (Claude, Codex or OpenAI) → voiceover (ElevenLabs) → images (FLUX) →
motion clips (fal.ai: MiniMax H3 / Kling v3) → shot editor (cuts on speech, captions, music, SFX) → 1080×1920 MP4

## Requirements

| What | Version / notes |
|---|---|
| Python | 3.12 or newer (3.14 works) |
| ffmpeg + ffprobe | on `PATH` (`ffmpeg -version` must work) |
| Disk | ~2 GB for Python packages, ~0.5 GB for the Whisper model (downloaded on first run), ~50 MB per video |
| OS | Windows, Linux or macOS. A GPU is optional (only for local image/motion models) |
| Script writer (pick one) | **Claude Code CLI** (`claude`, logged in) or **Codex CLI** (`codex`, logged in) — no API cost — or an OpenAI API key |

Optional: Node.js 22 to install the CLIs (`npm install -g @anthropic-ai/claude-code @openai/codex`).

## Install

```bash
git clone https://github.com/kapella-hub/FVFactory.git
cd FVFactory
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux / macOS
pip install -r requirements.txt
cp .env.example .env              # then fill in the keys below
```

## API keys (`.env`)

| Key | Needed for | Required? | Where to get it |
|---|---|---|---|
| `FAL_API_KEY` | Motion clips (every shot), images when `IMAGE_PROVIDER=fal` | **Yes** | https://fal.ai/dashboard/keys (add credit under Billing) |
| `ELEVENLABS_API_KEY` | Voiceover (Multilingual v2) | Recommended | https://elevenlabs.io → Profile → API keys. The free plan works with the premade voices (Bill, George, Daniel, Liam/“josh”, Sarah/“rachel”), 10,000 characters/month; commercial use needs a paid plan |
| `OPENAI_API_KEY` | Voiceover fallback (OpenAI TTS); scripts only if `LLM_PROVIDER=openai` | Optional | https://platform.openai.com/api-keys |
| `REPLICATE_API_TOKEN` | Images when `IMAGE_PROVIDER=replicate` (FLUX 1.1 Pro, higher quality) | Optional | https://replicate.com/account/api-tokens |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude CLI auth where you cannot log in interactively (servers, Docker) | Optional | run `claude setup-token` |
| `CODEX_API_KEY` | Codex CLI API-key auth instead of `codex login` | Optional | OpenAI dashboard |
| `YOUTUBE_API_KEY`, `client_secrets.json` | Trend discovery from YouTube / `--upload` to YouTube | Optional | Google Cloud console |
| `HEDRA_API_KEY` | Persona (talking head) mode | Optional | https://hedra.com |

Never commit `.env`; it is git-ignored. Script writing uses your **logged-in** Claude Code or Codex CLI by
default (`LLM_PROVIDER=claude_cli`, fallback `codex,openai`), so it costs nothing extra.

### What a video costs (list prices, Oct 2026)

| Quality tier | Motion model | ~45 s video, total |
|---|---|---|
| Standard (default) | MiniMax H3 Max Turbo, $0.04/s | ~$2.70 |
| Premium | Kling v3 Pro, $0.112/s | ~$5.90 |
| Custom | `FAL_VIDEO_MODEL` (`hailuo`, `kling`, `kling-pro`, `h3`, `h3-turbo`) | varies |

The run checks the estimated cost before any paid call and again before the clips; set a cap with
`--max-cost 4` (or Settings → Max cost) and a run over the cap stops instead of degrading to stills.

## Run it

### Web UI (recommended)

```bash
python main.py --serve
```

Opens http://localhost:8000:

- **Generate** — Source: *Auto-discover*, *Topic* or *Your story* (paste your own narration; *Verbatim* keeps
  your exact words, *Adapt* turns it into a script). Choose voice, video style (photorealistic, anime,
  cartoon, …), duration, subtitles, pacing, music, quality tier, max cost, mascot.
- **Library** — every video with its title, warnings and download.
- **Scheduler** — recurring generation slots.
- **Settings** — script writer (Claude / Codex / OpenAI) and models, image/motion providers, defaults. Saved
  in `data/config.json`.

The UI has no login and listens on all interfaces: keep it on a trusted network.

### Command line

```bash
python main.py                                   # interactive
python main.py --auto --topic "Why gold never rusts"
python main.py --auto --niche tech               # discover a trending topic
python main.py --story-file story.txt --title "Baba Yaga" --story-mode verbatim
python main.py --auto --topic "History of Seiko" --tier premium --max-cost 7
python main.py --batch 5 --niche finance
python main.py --auto --mock                     # free dry run (placeholder images, no motion)
python main.py --rerender output/<job> --pacing fast --subtitle-style neon_glow   # re-edit, zero API calls
```

Useful flags: `--pacing calm|standard|fast`, `--subtitle-style`, `--voice bill|george|daniel|josh|rachel|auto`,
`--music-source mine|generated|any|none`, `--no-music`, `--no-sfx`, `--no-motion`, `--strict`,
`--mascot/--no-mascot`, `--classic` (old Ken Burns editor). `python main.py --help` lists everything.

### Output

Each video gets its own folder:

```
output/<YYYYMMDD_HHMMSS_topic>/
  final.mp4          1080×1920, 30 fps, -14 LUFS
  run_report.json    options, script stats, cost estimate vs actual, warnings
  sources/           narration, images, clips, shot plan (used by --rerender)
```

### Music and sound effects (optional)

Put your own tracks in `assets/music/<mood>/` and SFX in `assets/sfx/` (`whoosh*`, `impact*`, `riser*`), or
generate a library once with ElevenLabs (paid plan):

```bash
python main.py --build-sfx-library                       # ~$0.02
python main.py --build-music-library --per-mood 5        # $0.15 per track, asks first
```

## Tests

```bash
python -m pytest tests/ -q
```

Tests are offline: no API keys, LLM calls or paid generations.

## Project layout

```
app/          pipeline modules (script, assets, motion, shot editor in app/cin/, web UI in app/web/)
main.py       CLI and pipeline entry point
assets/       fonts, music, SFX, personas
data/         Settings (config.json), scheduler DB — git-ignored
output/       generated videos (job folders are git-ignored; cost_log.json is tracked)
docs/         design specs and plans
tests/        unit tests
```

Docker files (`Dockerfile`, `docker-compose.yml`) exist but the local Docker setup is not finished yet; run it
directly with Python for now.
