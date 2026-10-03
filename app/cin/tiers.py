"""Quality tiers -> motion model (spec 2026-10-03 §4, §6). Pure: no I/O.

Tiers differ by motion model only; every shot is motion footage. "custom" means
settings.fal_video_model. The tier only applies to fal: local / replicate keep their own model.
"""
from __future__ import annotations

from app.motion_gen import CLIP_MODELS, ClipModel, clip_model_for

QUALITY_TIERS = ("standard", "premium", "custom")
# standard: MiniMax H3 Max Turbo ($0.04/s, 768x1344, strong subject motion; verified live 2026-10-03).
# It replaced Kling v3 Standard ($0.084/s, 724x1268), which cost twice as much for weaker motion.
TIER_MODELS = {"standard": "h3-turbo", "premium": "kling-pro"}


def fal_model_keys() -> list:
    """Clip-model keys a fal run can use (the custom tier's choices)."""
    return [key for key, model in CLIP_MODELS.items() if model.endpoint]


def resolve_clip_model(tier: str, provider: str, custom_model: str) -> ClipModel:
    """provider local/replicate -> clip_model_for(provider, ...) regardless of tier; fal:
    standard/premium -> the tier's model; custom -> CLIP_MODELS[custom_model]. An unknown tier or an
    unknown / non-fal custom key raises ValueError (never a silent hailuo substitution)."""
    if tier not in QUALITY_TIERS:
        raise ValueError(f"Unknown quality tier {tier!r}; choose one of {', '.join(QUALITY_TIERS)}")
    if provider in ("local", "replicate"):
        return clip_model_for(provider, custom_model)
    if tier in TIER_MODELS:
        return CLIP_MODELS[TIER_MODELS[tier]]
    model = CLIP_MODELS.get(custom_model)
    if model is None or model.endpoint is None:
        raise ValueError(f"Unknown fal video model {custom_model!r} for the custom tier; "
                         f"set fal_video_model to one of {', '.join(fal_model_keys())}")
    return model
