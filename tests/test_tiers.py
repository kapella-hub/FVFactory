"""Quality tier -> clip model (spec 2026-10-03 §6). Compare .key, never ClipModel identity:
tests/test_motion_gen.py reloads app.motion_gen, which creates new ClipModel objects."""
import pytest

from app.cin.tiers import QUALITY_TIERS, TIER_MODELS, fal_model_keys, resolve_clip_model
from app.motion_gen import CLIP_MODELS


def test_tier_table():
    assert QUALITY_TIERS == ("standard", "premium", "custom")
    assert TIER_MODELS == {"standard": "h3-turbo", "premium": "kling-pro"}
    assert all(CLIP_MODELS[key].endpoint for key in TIER_MODELS.values())


@pytest.mark.parametrize("tier, custom, expected", [
    ("standard", "hailuo", "h3-turbo"), ("premium", "hailuo", "kling-pro"), ("custom", "kling", "kling"),
    ("custom", "hailuo", "hailuo"), ("custom", "h3-turbo", "h3-turbo"), ("custom", "kling-pro", "kling-pro"),
])
def test_fal_tiers_resolve(tier, custom, expected):
    assert resolve_clip_model(tier, "fal", custom).key == expected


@pytest.mark.parametrize("tier", QUALITY_TIERS)
def test_local_and_replicate_ignore_the_tier(tier):
    assert resolve_clip_model(tier, "local", "kling").key == "local"
    assert resolve_clip_model(tier, "replicate", "kling").key == "replicate-minimax"


@pytest.mark.parametrize("custom", ["sora", "", "local", "replicate-minimax"])
def test_unknown_or_non_fal_custom_model_raises_naming_the_choices(custom):
    with pytest.raises(ValueError) as info:
        resolve_clip_model("custom", "fal", custom)
    assert "kling-pro" in str(info.value) and "h3-turbo" in str(info.value)


def test_unknown_tier_raises():
    with pytest.raises(ValueError, match="choose one of standard, premium, custom"):
        resolve_clip_model("gold", "fal", "kling")


def test_fal_model_keys_are_the_models_with_an_endpoint():
    assert fal_model_keys() == ["kling", "kling-pro", "hailuo", "h3-turbo", "h3"]
