import numpy as np
from app.subtitle_styles import SubtitleRenderer, SUBTITLE_PRESETS


def test_presets_exist():
    assert "bold_impact" in SUBTITLE_PRESETS
    assert "clean_minimal" in SUBTITLE_PRESETS
    assert "neon_glow" in SUBTITLE_PRESETS
    assert "fire" in SUBTITLE_PRESETS


def test_preset_has_required_keys():
    for name, preset in SUBTITLE_PRESETS.items():
        assert "active_color" in preset, f"{name} missing active_color"
        assert "inactive_color" in preset, f"{name} missing inactive_color"
        assert "font_size" in preset, f"{name} missing font_size"
        assert "position" in preset, f"{name} missing position"


def test_render_subtitle_frame_returns_rgba():
    renderer = SubtitleRenderer(style="bold_impact", width=1080, height=1920)
    frame = renderer.render_subtitle_frame(
        words=["Hello", "world", "test"],
        active_index=1,
    )
    assert isinstance(frame, np.ndarray)
    assert frame.shape[2] == 4  # RGBA
    assert frame.shape[1] == 1080
    assert frame.shape[0] < 400


def test_render_subtitle_frame_different_styles():
    for style_name in SUBTITLE_PRESETS:
        renderer = SubtitleRenderer(style=style_name, width=1080, height=1920)
        frame = renderer.render_subtitle_frame(
            words=["Hello", "world"],
            active_index=0,
        )
        assert isinstance(frame, np.ndarray)


def test_unknown_style_defaults_to_bold_impact():
    renderer = SubtitleRenderer(style="nonexistent", width=1080, height=1920)
    assert renderer.preset == SUBTITLE_PRESETS["bold_impact"]
