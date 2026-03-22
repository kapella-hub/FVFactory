# FVFactory v2 — "Super Awesome" Design Spec

## Goal

Transform FVFactory from a prototype into a professional-grade automated short-form video factory. Output should be indistinguishable from videos made with CapCut/Premiere by experienced creators. Priority: voice quality, subtitle styling, and polished production value.

## Quality North Star

- **Voice**: ElevenLabs Multilingual v2 (`eleven_multilingual_v2`) as primary (natural, expressive), OpenAI TTS as fallback
- **Subtitles**: Karaoke-style word-by-word highlighting with multiple style presets — this is the single biggest visual quality signal
- **Images**: Flux via Replicate — high-quality, consistent style across scenes
- **Motion**: Minimax image-to-video via Replicate — scenes come alive with camera movement
- **Transitions**: Smooth cross-fades between scenes, not hard cuts
- **Audio mix**: Background music with ducking + SFX transitions (whoosh, riser)
- **Pacing**: Dynamic scene duration based on content, not equal splits

---

## Architecture Overview

```
Topic (manual or auto-discovered)
  |
  v
[Trend Scout] ---> trending topics from Google Trends + Reddit
  |
  v
[Content Engine] ---> script + motion prompts + hook variants + viral score
  |
  v
[Asset Manager] ---> Flux images + Minimax motion clips + ElevenLabs audio
  |
  v
[Video Editor] ---> Ken Burns / motion clips + karaoke subs + SFX + music + transitions
  |
  v
[Metadata Gen] ---> title, description, hashtags, thumbnail
  |
  v
output/*.mp4 + output/metadata/*.json + output/thumbnails/*.png
```

### Files

| File | Status | Purpose |
|------|--------|---------|
| `app/config.py` | Modify | Add new settings (Replicate models, subtitle presets, SFX, pacing) |
| `app/content_engine.py` | Modify | Motion-aware prompts, hook A/B variants, viral scoring, series mode, emoji injection |
| `app/asset_manager.py` | Modify | Flux image gen, Minimax video gen, ElevenLabs v2.5, parallel generation |
| `app/video_editor.py` | Modify | Karaoke subtitles, cross-fades, SFX layer, dynamic pacing, color grading, intro/outro |
| `app/animator.py` | Modify | Keep as-is for talking head mode, minor cleanup |
| `app/trend_scout.py` | **New** | Google Trends + Reddit trending topic discovery |
| `app/motion_gen.py` | **New** | Minimax image-to-video generation via Replicate |
| `app/cost_tracker.py` | **New** | Per-video API cost logging |
| `app/metadata_gen.py` | **New** | Title, description, hashtags, thumbnail extraction |
| `app/subtitle_styles.py` | **New** | Karaoke subtitle renderer with multiple presets |
| `app/sfx.py` | **New** | Sound effects library (whoosh, riser, impact) |
| `main.py` | Modify | Add --auto, --batch, --series CLI args |
| `app/dashboard.py` | Modify | Update Streamlit UI for new features |
| `requirements.txt` | Modify | Add new dependencies |
| `assets/sfx/` | **New** | Bundled royalty-free SFX files |

---

## Feature Specifications

### 1. Flux Image Generation (replaces DALL-E)

**Module**: `app/asset_manager.py`

- Use `black-forest-labs/flux-1.1-pro` on Replicate
- 9:16 aspect ratio (1080x1920) for vertical video
- Style consistency via prompt suffix from `config.image_style`
- Cost: ~$0.03/image vs $0.04-0.08 DALL-E
- Parallel generation: generate all 5 images concurrently with `concurrent.futures.ThreadPoolExecutor`

**Migration strategy:**
- DALL-E code path is **removed** entirely (Flux is strictly better and cheaper)
- `use_mock` parameter is **kept** for development/testing without API costs
- `generate_images()` signature stays the same: `(prompts, use_mock=False) -> List[str]`
- Default changes from `use_mock=True` to `use_mock=False` (Flux is cheap enough for regular use)

```python
def _generate_image_flux(self, prompt: str, output_path: Path) -> None:
    """Generate image using Flux 1.1 Pro on Replicate. Downloads to output_path."""
    import replicate
    output = replicate.run(
        "black-forest-labs/flux-1.1-pro",
        input={
            "prompt": self._enhance_prompt_with_style(prompt),
            "aspect_ratio": "9:16",
            "output_format": "png",
            "safety_tolerance": 2,
        }
    )
    # output is a URL — download to output_path
    response = requests.get(str(output))
    with open(output_path, "wb") as f:
        f.write(response.content)
```

### 2. Minimax Image-to-Video Motion Clips

**Module**: `app/motion_gen.py` (new)

- Use `minimax/image-to-video` on Replicate
- Takes each Flux-generated image + a motion prompt
- Generates 5-second motion clips per scene
- Motion prompts come from Content Engine (e.g., "slow zoom in, particles floating upward")
- Falls back to Ken Burns static effect if Minimax fails or is disabled

```python
class MotionGenerator:
    MODEL = "minimax/image-to-video"

    def generate_motion_clip(self, image_path: str, motion_prompt: str) -> str:
        """Generate a 5s motion clip from a static image."""

    def generate_all_clips(self, image_paths: list, motion_prompts: list) -> list:
        """Generate all clips in parallel."""
```

### 3. Trend Scout — Auto Topic Discovery

**Module**: `app/trend_scout.py` (new)

- **Google Trends**: Use `pytrends` to get trending searches by region
- **Reddit**: Use Reddit JSON API (no auth needed) to scrape hot posts from configurable subreddits (r/todayilearned, r/technology, r/science, r/explainlikeimfive)
- Score topics by: trend velocity, Reddit engagement, topic freshness
- Filter by niche relevance using GPT
- Return top 5 ranked topics

```python
class TrendScout:
    def discover_topics(self, niche: str = None, count: int = 5) -> list[TrendTopic]:
        """Discover trending topics from multiple sources."""

    def _fetch_google_trends(self) -> list[TrendTopic]:
    def _fetch_reddit_hot(self, subreddits: list[str]) -> list[TrendTopic]:
    def _rank_topics(self, topics: list[TrendTopic], niche: str) -> list[TrendTopic]:
```

### 4. Motion-Aware Script Prompts + Viral Scoring

**Module**: `app/content_engine.py` (modify)

**Enhanced ScriptOutput model** (new fields have defaults for backward compatibility):
```python
class ScriptOutput(BaseModel):
    hook: str                                        # Catchy opening
    hook_variants: List[str] = []                    # 3 hook alternatives (optional)
    hook_viral_score: int = 0                        # 1-10 scroll-stopping score (optional)
    body: str                                        # Main content
    image_prompts: List[str]                         # 5 visual descriptions
    motion_prompts: List[str] = []                   # 5 camera/motion descriptions (optional)
    pacing_hints: List[str] = []                     # 5 pacing values (optional, defaults to "normal")
    keywords: List[str]                              # SEO keywords
    emoji_subtitles: List[str] = []                  # Key phrases with contextual emojis (optional)
```

When `motion_prompts` is empty, the pipeline falls back to Ken Burns. When `pacing_hints` is empty, equal pacing is used. This preserves full backward compatibility with the existing GPT prompt — the enhanced prompt is only used when motion/v2 features are enabled.

**Hook A/B system:**
- GPT generates 3 hook variants
- Each gets a viral score 1-10
- `--auto` mode picks the highest; interactive mode lets user choose
- If best score < 7, GPT auto-regenerates with feedback

**Series mode:**
- `--series "History of Money" --parts 3`
- GPT generates connected scripts with cliffhanger endings for parts 1-2
- Consistent mascot/style across all parts
- Auto-numbering: "Part 1/3" overlay

### 5. Karaoke-Style Subtitles

**Module**: `app/subtitle_styles.py` (new)

This is the most impactful visual upgrade. Modern viral videos use word-by-word highlighting where:
- The active word is large, colored, and slightly scaled up
- Surrounding words are visible but dimmer
- Text appears in 3-4 word chunks synced to audio

**Presets:**
```python
SUBTITLE_PRESETS = {
    "bold_impact": {
        "active_color": "#FFFF00",       # Yellow
        "inactive_color": "#FFFFFF80",   # White 50% opacity
        "font": "Arial-Bold",
        "font_size": 75,
        "active_scale": 1.15,            # Active word 15% bigger
        "stroke_color": "#000000",
        "stroke_width": 4,
        "position": "bottom",
        "bg_box": False,
    },
    "clean_minimal": {
        "active_color": "#FFFFFF",
        "inactive_color": "#FFFFFF60",
        "font": "Helvetica",
        "font_size": 60,
        "active_scale": 1.0,
        "stroke_color": None,
        "stroke_width": 0,
        "position": "center",
        "bg_box": True,                  # Semi-transparent box behind text
        "bg_color": "#00000080",
    },
    "neon_glow": {
        "active_color": "#00FF88",       # Neon green
        "inactive_color": "#FFFFFF40",
        "font": "Arial-Bold",
        "font_size": 70,
        "active_scale": 1.2,
        "stroke_color": "#00FF88",
        "stroke_width": 2,
        "glow": True,                    # Neon glow effect
        "position": "bottom",
    },
    "fire": {
        "active_color": "#FF4500",       # Orange-red
        "inactive_color": "#FFD70080",   # Gold dimmed
        "font": "Impact",
        "font_size": 80,
        "active_scale": 1.25,
        "stroke_color": "#000000",
        "stroke_width": 5,
        "position": "bottom",
    },
}
```

**Rendering approach:**
- Use Whisper word-level timestamps (already have this)
- For each timestamp window, render the full chunk but with the active word styled differently
- Use PIL to render text frames (more control than MoviePy TextClip)
- Composite as transparent overlay on video

### 6. Sound Effects Layer

**Module**: `app/sfx.py` (new)

**Bundled SFX** (royalty-free, generated or sourced):
- `whoosh.mp3` — scene transition swoosh
- `riser.mp3` — tension build before hook
- `impact.mp3` — dramatic reveal
- `pop.mp3` — subtitle pop-in

**Placement logic:**
- Whoosh between every scene transition (synced to cross-fade)
- Riser in first 0.5s (before hook lands)
- Impact at hook delivery (0.5s mark)
- Pop on each subtitle chunk appearance (subtle, low volume)

```python
class SFXMixer:
    def build_sfx_track(self, scene_timestamps: list, subtitle_timestamps: list, total_duration: float) -> AudioFileClip:
        """Build composite SFX track synced to scene and subtitle timing."""
```

### 7. Dynamic Scene Pacing

**Module**: `app/video_editor.py` (modify)

Instead of `duration / num_images` equal splits:
- Content Engine provides `pacing_hints` per scene: `fast` (0.7x), `normal` (1.0x), `slow` (1.3x), `dramatic_pause` (1.5x)
- Video Editor calculates weighted durations that sum to total audio duration
- Result: exciting moments move fast, emotional moments breathe

```python
PACING_WEIGHTS = {
    "fast": 0.7,
    "normal": 1.0,
    "slow": 1.3,
    "dramatic_pause": 1.5,
}
```

### 8. Cross-Fade Transitions

**Module**: `app/video_editor.py` (modify)

- Configurable cross-fade duration (default 0.8s) via `config.crossfade_duration`
- Synced with whoosh SFX
- Use MoviePy's `crossfadein`/`crossfadeout` with CompositeVideoClip overlap

**Updated `assemble_video` signature:**
```python
def assemble_video(
    self,
    audio_path: str,
    image_paths: List[str],
    output_filename: str,
    hook_text: Optional[str] = None,
    enable_subtitles: bool = True,
    enable_music: bool = True,
    # New v2 parameters (all optional with sensible defaults)
    motion_clip_paths: Optional[List[str]] = None,  # Minimax clips (None = use Ken Burns)
    pacing_hints: Optional[List[str]] = None,        # Per-scene pacing (None = equal)
    subtitle_style: str = "bold_impact",              # Subtitle preset name
    color_grade: Optional[str] = None,                # Niche color grade (None = no grading)
    enable_sfx: bool = True,                          # Sound effects
    enable_intro: bool = False,                       # Intro/outro animations
    sfx_config: Optional[dict] = None,                # SFX timing overrides
) -> str:
```

When `motion_clip_paths` is provided, those clips are used instead of Ken Burns images. The `assemble_hybrid_video` method gains the same new parameters.

### 9. Color Grading

**Module**: `app/video_editor.py` (modify)

Per-niche color grading applied as numpy transforms:
```python
COLOR_GRADES = {
    "tech": {"contrast": 1.1, "saturation": 1.2, "blue_shift": 10},
    "finance": {"contrast": 1.05, "saturation": 0.9, "warmth": 15},
    "history": {"contrast": 1.0, "saturation": 0.8, "sepia": 0.3},
    "science": {"contrast": 1.1, "saturation": 1.3, "brightness": 5},
    "default": {"contrast": 1.05, "saturation": 1.1},
}
```

### 10. Intro/Outro Animations

**Module**: `app/video_editor.py` (modify)

- **Intro** (1.5s): Channel name/logo fade-in with scale animation
- **Outro** (2s): "Follow for more" CTA with subscribe animation
- Configurable via `config.py` (channel_name, logo_path)
- Can be disabled

### 11. ElevenLabs Multilingual v2

**Module**: `app/asset_manager.py` (modify)

- Upgrade model from `eleven_monolingual_v1` to `eleven_multilingual_v2` (better quality, multilingual support)
- Add voice selection config via `config.py` (not just Rachel — support voice ID override)
- Keep OpenAI TTS as fallback
- Note: `replicate_api_token` field already exists in `config.py` — reuse it for Flux and Minimax (no new config needed)

### 12. Parallel Asset Generation

**Module**: `app/asset_manager.py` (modify)

- Use `concurrent.futures.ThreadPoolExecutor` to run image generation + audio generation concurrently
- Generate all 5 images in parallel (5 threads)
- Then generate all 5 motion clips in parallel
- ~2x faster pipeline overall

### 13. Cost Tracker

**Module**: `app/cost_tracker.py` (new)

```python
class CostTracker:
    COSTS = {
        "flux_image": 0.03,
        "minimax_video": 0.10,
        "elevenlabs_tts": 0.01,  # per 1000 chars
        "openai_gpt4o": 0.005,   # per script
        "openai_tts": 0.015,     # per 1000 chars
        "whisper": 0.00,         # local
    }

    def log_cost(self, video_id: str, item: str, quantity: int = 1) -> None:
    def get_video_cost(self, video_id: str) -> float:
    def get_total_costs(self) -> dict:
```

Output: `output/cost_log.json`

### 14. Metadata Generator

**Module**: `app/metadata_gen.py` (new)

After video render, GPT generates:
- **Title**: Optimized for each platform (TikTok vs YouTube)
- **Description**: With keywords and hashtags
- **Hashtags**: 5-10 trending + niche-relevant
- **Best posting time**: Based on niche/audience
- **Thumbnail**: Extract best frame from video + add text overlay with PIL

Output: `output/metadata/{video_id}.json` + `output/thumbnails/{video_id}.png`

### 15. CLI Modes

**Module**: `main.py` (modify)

```bash
# Interactive (existing)
python main.py

# Auto mode: discover trend, generate, render — zero interaction
python main.py --auto

# Auto with niche filter
python main.py --auto --niche tech

# Batch: generate N videos
python main.py --batch 5 --niche finance

# Series: multi-part connected videos
python main.py --series "History of Money" --parts 3

# Options
python main.py --auto --no-motion      # Skip Minimax, use Ken Burns
python main.py --auto --subtitle-style neon_glow
python main.py --auto --no-sfx         # Skip sound effects
python main.py --auto --no-music       # Skip background music
```

Use `argparse` for CLI parsing.

---

## Cost Estimate Per Video

| Component | Cost |
|-----------|------|
| GPT-4o script | ~$0.005 |
| ElevenLabs TTS | ~$0.01 |
| 5x Flux images | ~$0.15 |
| 5x Minimax motion | ~$0.50 |
| Whisper (local) | $0.00 |
| **Total** | **~$0.67/video** |
| Without motion clips | **~$0.17/video** |

---

## Risk Mitigations

- **`pytrends` instability**: `pytrends` is an unofficial scraper that breaks frequently. Trend Scout treats it as best-effort — if it fails, Reddit-only mode is used. TrendScout.discover_topics() never raises on pytrends failure.
- **Reddit rate limiting**: Use proper `User-Agent` header (`FVFactory/2.0`). Limit to 5 requests per run. No OAuth needed at this volume.
- **Replicate concurrency**: `ThreadPoolExecutor(max_workers=3)` to avoid rate limits. Replicate allows ~10 concurrent predictions on most plans.
- **SFX pop sound**: Remove the per-subtitle pop sound (reviewer correctly flagged it as annoying). SFX only on scene transitions (whoosh) and hook delivery (impact/riser).
- **Karaoke subtitle complexity**: Use PIL for text rendering but keep it pragmatic — no glow effects in v2.0. Start with active word color + inactive word color + stroke. Glow can be added later.
- **Cost tracker staleness**: Move per-unit costs to `config.py` as settings so they can be overridden via .env.
- **Minimax failure handling**: If a clip fails, fall back to Ken Burns for that scene. Partial failures are OK — log the failure, continue with mixed clips.

## Dependencies (new)

```
replicate          # Flux + Minimax (already in requirements.txt)
pytrends           # Google Trends (best-effort, graceful failure)
requests           # Reddit API (already in requirements.txt, no httpx needed)
concurrent.futures # Parallel generation (stdlib)
argparse           # CLI (stdlib)
```

---

## Output Directory Structure

```
output/
  ├── *.mp4                    # Generated videos
  ├── cost_log.json            # Cumulative cost log (schema v1)
  ├── metadata/
  │   └── {video_id}.json      # Per-video metadata (title, description, hashtags)
  └── thumbnails/
      └── {video_id}.png       # Auto-generated thumbnails
```

Video ID format: `{safe_topic}_{timestamp}` (same as current filename pattern, minus `.mp4`).
Subdirectories are auto-created on first use.

## Non-Goals

- Auto-publish to TikTok/YouTube (complex OAuth, separate tool)
- Voice cloning (ElevenLabs paid tier, legal concerns)
- AI-generated background music (current royalty-free approach is fine)
- Real-time preview in Streamlit (too complex, render-then-preview is fine)
