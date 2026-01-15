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

    # Output settings
    output_dir: str = "output"
    assets_dir: str = "assets"

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


settings = Settings()
