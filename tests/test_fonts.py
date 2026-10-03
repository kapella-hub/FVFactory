"""Bundled OFL fonts (spec §7): presets reference files, a missing file falls back and says so."""
import numpy as np
import pytest

from app.fonts import FONTS_DIR, load_font
from app.subtitle_styles import SUBTITLE_PRESETS, SubtitleRenderer

BUNDLED = ("Montserrat-Variable.ttf", "Anton-Regular.ttf", "BebasNeue-Regular.ttf")
LICENSES = ("OFL-Montserrat.txt", "OFL-Anton.txt", "OFL-BebasNeue.txt")


def test_bundled_fonts_and_licenses_are_present():
    for name in BUNDLED + LICENSES:
        assert (FONTS_DIR / name).is_file(), name
    for name in LICENSES:
        assert "SIL Open Font License" in (FONTS_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("file", BUNDLED)
def test_bundled_fonts_load_without_fallback(file):
    font, fell_back = load_font(file, 75)
    assert fell_back is False
    assert font.getbbox("WILSDORF")[2] > 150


def test_montserrat_weight_axis_is_applied_per_instance():
    """getname() still says 'Thin' after set_variation_by_axes: pin the weight by glyph width."""
    thin, _ = load_font("Montserrat-Variable.ttf", 75, 100)
    extra_bold, _ = load_font("Montserrat-Variable.ttf", 75, 800)
    other_size, _ = load_font("Montserrat-Variable.ttf", 150, 800)
    assert extra_bold.getbbox("WILSDORF")[2] - thin.getbbox("WILSDORF")[2] >= 15
    assert other_size.getbbox("WILSDORF")[2] >= 2 * extra_bold.getbbox("WILSDORF")[2] - 4


def test_missing_font_file_falls_back_with_flag(caplog):
    with caplog.at_level("WARNING", logger="app.fonts"):
        font, fell_back = load_font("Nope-Regular.ttf", 60)
    assert fell_back is True
    assert font.getbbox("ABC")[2] > 0
    assert "Nope-Regular.ttf" in caplog.text


def test_presets_reference_bundled_files_and_keep_colours():
    assert {k: (v["font_file"], v["font_weight"]) for k, v in SUBTITLE_PRESETS.items()} == {
        "bold_impact": ("Montserrat-Variable.ttf", 800),
        "clean_minimal": ("Montserrat-Variable.ttf", 600),
        "neon_glow": ("BebasNeue-Regular.ttf", None),
        "fire": ("Anton-Regular.ttf", None),
    }
    colours = {k: (v["active_color"], v["inactive_color"]) for k, v in SUBTITLE_PRESETS.items()}
    assert colours == {"bold_impact": ("#FFFF00", "#FFFFFF80"), "clean_minimal": ("#FFFFFF", "#FFFFFF60"),
                       "neon_glow": ("#00FF88", "#FFFFFF40"), "fire": ("#FF4500", "#FFD70080")}
    assert all("font" not in v for v in SUBTITLE_PRESETS.values())   # no system font names left


def test_classic_renderer_uses_bundled_font_including_shrink_path():
    r = SubtitleRenderer(style="fire")
    assert r.font_fallback is False and r._font.getname()[0] == "Anton"
    wide = r.render_subtitle_frame(["Supercalifragilisticexpialidocious", "antidisestablishmentarianism"], 0)
    assert isinstance(wide, np.ndarray) and wide.shape[1] == 1080


def test_classic_renderer_flags_missing_font(monkeypatch):
    monkeypatch.setitem(SUBTITLE_PRESETS["bold_impact"], "font_file", "Gone.ttf")
    r = SubtitleRenderer(style="bold_impact")
    assert r.font_fallback is True
    assert r.render_subtitle_frame(["still", "renders"], 1).shape[2] == 4


def test_missing_font_warns_once_and_is_cached(caplog):
    import logging
    import app.fonts as fonts
    fonts.clear_font_cache()
    with caplog.at_level(logging.WARNING, logger="app.fonts"):
        results = [load_font("Nope-Missing.ttf", 40, 700) for _ in range(50)]
    assert all(fb is True for _, fb in results)
    assert len([r for r in caplog.records if "Nope-Missing.ttf" in r.getMessage()]) == 1


def test_repeated_load_returns_cached_object():
    import app.fonts as fonts
    fonts.clear_font_cache()
    a, _ = load_font("Montserrat-Variable.ttf", 60, 700)
    b, _ = load_font("Montserrat-Variable.ttf", 60, 700)
    c, _ = load_font("Montserrat-Variable.ttf", 60, 400)
    assert a is b and a is not c


def test_not_implemented_variation_falls_back(monkeypatch):
    import app.fonts as fonts
    fonts.clear_font_cache()
    real = fonts.ImageFont.truetype

    class NoMM:
        def set_variation_by_axes(self, axes):
            raise NotImplementedError("no MM support")

    def fake(name, size, *a, **k):
        return NoMM() if str(name).endswith("Stub.ttf") else real(name, size, *a, **k)

    monkeypatch.setattr(fonts.ImageFont, "truetype", fake)
    font, fell_back = load_font("Stub.ttf", 40, 700)
    assert fell_back is True and not isinstance(font, NoMM)
