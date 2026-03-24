from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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
    cost_minimax_video: float = 0.10
    cost_elevenlabs_per_1k_chars: float = 0.01
    cost_openai_gpt4o: float = 0.005
    cost_openai_tts_per_1k_chars: float = 0.015

    # Trend Scout
    reddit_subreddits: str = "todayilearned,technology,science,explainlikeimfive"
    trend_count: int = 5

    # YouTube
    youtube_client_secrets: str = "client_secrets.json"
    youtube_token_path: str = "youtube_token.json"
    youtube_privacy: str = "public"  # public, unlisted, or private
    youtube_api_key: str = ""  # API key for reading public video stats (no OAuth needed)


settings = Settings()
