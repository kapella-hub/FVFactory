from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # legacy .env keys (e.g. AYRSHARE_API_KEY) must not break startup
    )

    # OpenAI - Script generation
    openai_api_key: str = ""

    # ElevenLabs - Text-to-speech
    elevenlabs_api_key: str = ""

    # Image generation (Leonardo or Midjourney)
    leonardo_api_key: str = ""
    midjourney_api_key: str = ""

    # Portrait Animation APIs
    hedra_api_key: str = ""           # Hedra API for portrait animation
    replicate_api_token: str = ""     # Replicate API (for LivePortrait model)

    # Output settings
    output_dir: str = "output"
    assets_dir: str = "assets"

    # Persona settings (talking head mode)
    personas_dir: str = "assets/personas"
    use_persona: bool = False         # If True, use animated portrait instead of images
    default_persona: str = ""         # Default persona image filename (e.g., "alex_master.png")

    # Mascot settings for visual branding consistency
    mascot_enabled: bool = True
    mascot_prompt: str = (
        "A cute, futuristic robot with glowing blue eyes and a cracked screen, "
        "vector art style"
    )
    # Style keywords appended to all image prompts for consistency
    image_style: str = "vector art style, vibrant colors, clean lines"

    # Background music settings
    music_enabled: bool = True
    music_dir: str = "assets/music"
    music_volume: float = 0.1      # 10% volume for background music
    voice_volume: float = 1.0      # 100% volume for voiceover

    # === V2 Settings ===

    # Replicate models
    flux_model: str = "black-forest-labs/flux-1.1-pro"
    minimax_model: str = "minimax/image-to-video"

    # ElevenLabs v2
    elevenlabs_model: str = "eleven_multilingual_v2"
    elevenlabs_voice_id: str = "pqHfZKP75CvOlQylNhV4"  # Bill (default)

    # Voice presets: name -> ElevenLabs voice ID
    # Use --voice <name> to select, or "auto" to pick based on niche
    voice_presets: dict = {
        "bill": "pqHfZKP75CvOlQylNhV4",       # Deep, confident elder - stoicism, philosophy
        "george": "JBFqnCBsd6RMkjVDRZzb",      # Warm British narrator - general, history
        "daniel": "onwK4e9ZLuTAKqWW03F9",      # Authoritative British - science, tech, finance
        "josh": "TxGEqnHWrfWFTfGW9XjX",        # Energetic young - trending, pop culture, gaming
        "rachel": "21m00Tcm4TlvDq8ikWAM",      # Clear female - health, lifestyle, education
    }

    # Niche -> voice preset mapping for auto voice selection
    voice_niche_map: dict = {
        "stoicism": "bill",
        "philosophy": "bill",
        "self-improvement": "bill",
        "motivation": "bill",
        "history": "george",
        "science": "daniel",
        "tech": "daniel",
        "technology": "daniel",
        "finance": "daniel",
        "crypto": "daniel",
        "gaming": "josh",
        "entertainment": "josh",
        "pop culture": "josh",
        "health": "rachel",
        "lifestyle": "rachel",
    }

    # Subtitle styling
    subtitle_style: str = "bold_impact"

    # Transitions
    crossfade_duration: float = 0.8  # seconds

    # SFX
    enable_sfx: bool = True
    sfx_dir: str = "assets/sfx"

    # Motion clips
    enable_motion: bool = True

    # Intro/Outro
    enable_intro: bool = False
    channel_name: str = ""
    logo_path: str = ""

    # Color grading
    color_grade: str = ""  # niche name or empty for no grading
    niche: str = ""

    # Parallel generation
    max_parallel_workers: int = 3

    # Cost tracking (overridable via .env)
    cost_flux_image: float = 0.03
    # Motion clip pricing per model: {"per_clip": usd} or {"per_second": usd}.
    # fal list prices checked 2026-10-02 — verify against billing.
    clip_pricing: dict = {
        "hailuo": {"per_clip": 0.50},
        "kling": {"per_second": 0.045},
        "kling-pro": {"per_second": 0.10},
        "replicate-minimax": {"per_clip": 0.50},
        "local": {"per_clip": 0.0},
    }
    cost_elevenlabs_per_1k_chars: float = 0.01
    cost_openai_gpt4o: float = 0.005
    cost_openai_tts_per_1k_chars: float = 0.015

    # Trend Scout
    reddit_subreddits: str = "todayilearned,Damnthatsinteresting,interestingasfuck,space,technology,science,Futurology"
    trend_count: int = 5

    # YouTube
    youtube_client_secrets: str = "client_secrets.json"
    youtube_token_path: str = "youtube_token.json"
    youtube_privacy: str = "public"  # public, unlisted, or private
    youtube_api_key: str = ""  # API key for reading public video stats (no OAuth needed)

    # === V3 Settings: Provider Configuration ===

    # Provider mode: "local" (all local), "api" (all API), "mixed" (per-provider)
    provider_mode: str = "api"

    # Individual provider selection
    llm_provider: str = "claude_cli"        # "claude_cli" | "openai"
    image_provider: str = "fal"             # "fal" | "local" | "replicate"
    motion_provider: str = "fal"            # "fal" | "replicate" | "local"

    # fal.ai settings
    fal_api_key: str = ""                   # fal.ai API key (or set FAL_KEY env var)
    fal_video_model: str = "hailuo"         # "hailuo" | "kling" | "kling-pro"
    fal_image_model: str = "fal-ai/flux/schnell"  # fal.ai image generation endpoint

    # Local model settings
    wan_model_size: str = "enhanced"        # "enhanced" (CPU motion effects, no GPU needed)
    flux_local_model: str = "black-forest-labs/FLUX.1-schnell"
    claude_cli_timeout: int = 120           # seconds

    # Video style and duration
    video_style: str = "photorealistic"     # "photorealistic" | "cartoon" | "illustration"
    video_duration: str = "medium"          # "short" (~30s, 5-7 scenes) | "medium" (~60s, 8-10) | "long" (~90s, 11-14)
    cinematic_enabled: bool = True          # False = classic Ken Burns editor for every run (as --classic)

    # === Shot-based editor (spec 2026-10-02) ===
    whisper_model: str = "small"            # "base" is a valid, lighter choice for small VPSes
    motion_concurrency: int = 4             # parallel motion-clip generations
    keep_sources_days: int = 14             # prune output/<job>/sources/ older than this; <= 0 disables
    fal_video_fallback_model: str = ""      # e.g. "kling"; "" = no fallback model
    pacing: Literal["calm", "standard", "fast"] = "standard"
    strict: bool = False                    # True: fail the run instead of shipping a still shot
    music_source: Literal["mine", "generated", "any", "none"] = "any"   # spec §8.1

    # ElevenLabs music / SFX library builders (spec §8.1-8.2). Prices: https://elevenlabs.io/pricing/api
    elevenlabs_music_model: str = "music_v1"        # API default; "music_v2" / "music_v2_5" also accepted
    cost_elevenlabs_music_per_minute: float = 0.15
    cost_elevenlabs_sfx_per_minute: float = 0.12

    # Data directory (scheduler DB, config.json)
    data_dir: str = "data"

    # Local provider cost tracking (compute time in seconds)
    cost_local_image: float = 0.0
    cost_local_video: float = 0.0
    cost_claude_cli: float = 0.0


settings = Settings()
