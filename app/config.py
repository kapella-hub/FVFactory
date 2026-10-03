import re
from typing import Annotated, Literal

from pydantic import Field, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

# Model names travel on a CLI's argv; on Windows the npm `codex` shim is a .cmd that cmd.exe parses, so
# a name may only use characters cmd.exe treats literally (no & | < > ^ % " ! ( ) or whitespace).
ModelName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]*$")]      # "" allowed
RequiredModelName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]+$")]


_SECRET_FIELD = re.compile(r"(api_key|api_token|_token$|password|_secret$)")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # legacy .env keys (e.g. AYRSHARE_API_KEY) must not break startup
    )

    def __repr_args__(self):
        """Mask secret values: pytest and tracebacks print this object, and a leaked repr once put live
        API keys into a session log. Set secrets show as '***'; unset ones stay ''."""
        for name, value in super().__repr_args__():
            if name and _SECRET_FIELD.search(name) and isinstance(value, str) and value:
                value = "***"
            yield name, value

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

    # Mascot settings for visual branding consistency. Never applied to photorealistic runs
    # (spec 2026-10-03 §9): a cartoon robot cannot appear in a photographic scene.
    mascot_enabled: bool = False
    mascot_prompt: str = (
        "A cute, futuristic robot with glowing blue eyes and a cracked screen, "
        "vector art style"
    )
    # Extra style keywords appended to every image prompt. "" = derive from the run's video_style
    # (asset_manager.STYLE_SUFFIX: one set of keywords per video style).
    image_style: str = ""

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
        # josh / rachel used to be library voices, which a free ElevenLabs plan cannot use via the API
        # (402 paid_plan_required, checked 2026-10-03); premade voices work on every plan.
        "josh": "TX3LPaxmHKxFdv7VOQHJ",        # Liam - energetic young male: trending, pop culture, gaming
        "rachel": "EXAVITQu4vr4xnSDxMaL",      # Sarah - clear confident female: health, lifestyle, education
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
    # Motion clip pricing per model: {"per_clip": usd} or {"per_second": usd}. Every CLIP_MODELS key
    # needs an entry. fal list prices (audio off) checked 2026-10-03, subject to change; no promo prices.
    clip_pricing: dict = {
        "kling": {"per_second": 0.084},          # Kling v3 Standard
        "kling-pro": {"per_second": 0.112},      # Kling v3 Pro
        "hailuo": {"per_clip": 0.50},            # Minimax video-01, 6 s fixed
        "h3-turbo": {"per_second": 0.04},        # MiniMax H3 Max Turbo 768P
        "h3": {"per_second": 0.08},              # MiniMax H3 Max 768P
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
    # Script LLM: the primary provider, then each llm_fallback name in order (skipping the primary and
    # duplicates; "" or "none" = no fallback). claude_cli / codex are the headless CLIs (subscription
    # logins, $0 in the cost log); openai is the paid API.
    llm_provider: Literal["claude_cli", "codex", "openai"] = "claude_cli"
    llm_fallback: str = "codex,openai"
    claude_cli_model: ModelName = "sonnet"  # claude -p --model; "" = the Claude CLI default
    codex_model: ModelName = "gpt-5.5"      # codex exec -m; "" = the Codex CLI default (from ~/.codex/config.toml,
                                            # which may name a model a ChatGPT login cannot use)
    # -c model_reasoning_effort; "" = the Codex config value (gpt-5.5 rejects the "max" some configs set)
    codex_reasoning_effort: Literal["", "none", "low", "medium", "high", "xhigh"] = "medium"
    openai_model: RequiredModelName = "gpt-5.4-mini-2026-03-17"
    codex_cli_timeout: int = 300            # seconds
    # CLI auth, passed only to its own CLI's environment (every CLI child gets ANTHROPIC_API_KEY,
    # OPENAI_API_KEY, CODEX_API_KEY and CLAUDE_CODE_OAUTH_TOKEN stripped first). .env only, never the web UI.
    claude_code_oauth_token: str = ""       # `claude setup-token`: bills the Claude subscription
    codex_api_key: str = ""                 # Codex API-key auth (else the `codex login` in ~/.codex)
    image_provider: str = "fal"             # "fal" | "local" | "replicate"
    motion_provider: str = "fal"            # "fal" | "replicate" | "local"

    # fal.ai settings
    fal_api_key: str = ""                   # fal.ai API key (or set FAL_KEY env var)
    fal_video_model: str = "hailuo"         # custom tier model: kling | kling-pro | hailuo | h3-turbo | h3
    fal_image_model: str = "fal-ai/flux/schnell"  # fal.ai image generation endpoint

    # Local model settings
    wan_model_size: str = "enhanced"        # "enhanced" (CPU motion effects, no GPU needed)
    flux_local_model: str = "black-forest-labs/FLUX.1-schnell"
    claude_cli_timeout: int = 120           # seconds

    # Video style and duration
    video_style: str = "photorealistic"     # "photorealistic" | "cartoon" | "illustration"
    video_duration: str = "medium"          # "short" (~30s, 6-8 scenes) | "medium" (~45s, 9-11) | "long" (~60s, 11-14)
    cinematic_enabled: bool = True          # False = classic Ken Burns editor for every run (as --classic)

    # === Shot-based editor (spec 2026-10-02) ===
    whisper_model: str = "small"            # "base" is a valid, lighter choice for small VPSes
    motion_concurrency: int = 4             # parallel motion-clip generations
    keep_sources_days: int = 14             # prune output/<job>/sources/ older than this; <= 0 disables
    fal_video_fallback_model: str = ""      # e.g. "kling"; "" = no fallback model
    pacing: Literal["calm", "standard", "fast"] = "standard"
    strict: bool = False                    # True: fail the run instead of shipping a still shot
    music_source: Literal["mine", "generated", "any", "none"] = "any"   # spec §8.1

    # === Quality tiers (spec 2026-10-03) ===
    # standard = MiniMax H3 Max Turbo, premium = Kling v3 Pro, custom = fal_video_model. Tiers change the
    # motion model only; every shot stays motion footage.
    quality_tier: Literal["standard", "premium", "custom"] = "standard"
    # USD per video. A run whose estimate exceeds it stops before the next paid stage (never degrades
    # to stills or a cheaper model). 0 = no cap.
    max_cost_per_video: float = Field(0.0, ge=0, allow_inf_nan=False)
    # Warn (low_motion) about generated clips whose mean luma frame difference (ffmpeg signalstats YDIF at
    # 270 px wide) is below this; 0 = off. Kling v3 "rusty chains" clip: 0.95; clearly moving clips: 2.5+.
    low_motion_threshold: float = Field(1.2, ge=0, allow_inf_nan=False)

    # ElevenLabs music / SFX library builders (spec §8.1-8.2). Prices: https://elevenlabs.io/pricing/api
    elevenlabs_music_model: str = "music_v1"        # API default; "music_v2" / "music_v2_5" also accepted
    cost_elevenlabs_music_per_minute: float = 0.15
    cost_elevenlabs_sfx_per_minute: float = 0.12

    # Data directory (scheduler DB, config.json)
    data_dir: str = "data"

    # Web UI: comma list of extra origins allowed to call the API cross-origin. "" = no CORS headers at
    # all (the bundled UI is same-origin). .env only, never the web UI.
    cors_origins: str = ""

    # Local provider cost tracking (compute time in seconds)
    cost_local_image: float = 0.0
    cost_local_video: float = 0.0
    cost_claude_cli: float = 0.0
    cost_codex_cli: float = 0.0


settings = Settings()
