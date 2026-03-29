"""Configuration API endpoints."""
import json
import logging
from pathlib import Path
from fastapi import APIRouter
from app.config import settings

router = APIRouter()
CONFIG_PATH = Path("data/config.json")
logger = logging.getLogger(__name__)


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def _save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


@router.get("/config")
async def get_config():
    saved = _load_config()
    current = {
        "provider_mode": settings.provider_mode,
        "llm_provider": settings.llm_provider,
        "image_provider": settings.image_provider,
        "motion_provider": settings.motion_provider,
        "wan_model_size": settings.wan_model_size,
        "flux_local_model": settings.flux_local_model,
        "claude_cli_timeout": settings.claude_cli_timeout,
        "niche": settings.niche,
        "video_style": settings.video_style,
        "video_duration": settings.video_duration,
        "subtitle_style": settings.subtitle_style,
        "enable_motion": settings.enable_motion,
        "enable_sfx": settings.enable_sfx,
        "music_enabled": settings.music_enabled,
        "music_volume": settings.music_volume,
        "elevenlabs_voice_id": settings.elevenlabs_voice_id,
        "output_dir": settings.output_dir,
        "youtube_privacy": settings.youtube_privacy,
        "has_openai_key": bool(settings.openai_api_key),
        "has_elevenlabs_key": bool(settings.elevenlabs_api_key),
        "has_replicate_key": bool(settings.replicate_api_token),
        "has_youtube_key": bool(settings.youtube_api_key),
    }
    current.update(saved)
    return current


@router.put("/config")
async def update_config(updates: dict):
    config = _load_config()
    config.update(updates)
    _save_config(config)
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return {"status": "ok", "config": config}


@router.post("/config/reset")
async def reset_config():
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    return {"status": "ok"}
