"""Caption layout + layer (spec §7): safe zone, highlight ramp, frame-one captions, hook headline."""
import numpy as np
import pytest

from app.cin.captions import BOTTOM_BOX, CaptionStyle, drawable, layout_line
from app.subtitle_styles import SUBTITLE_PRESETS

BOTTOM_STYLES = [k for k, v in SUBTITLE_PRESETS.items() if v["position"] == "bottom"]
LONG = "Supercalifragilisticexpialidocious"


# ---------------------------------------------------------------- layout

def test_drawable_uppercases_and_drops_missing_glyphs():
    font = CaptionStyle.from_preset("fire").font(80)
    assert drawable("café", font) == "CAFÉ"
    assert drawable("fire\U0001F525", font) == "FIRE"
    assert drawable("\U0001F525\U0001F525", font) == ""
    assert drawable("$1,000,000", font) == "$1,000,000"


@pytest.mark.parametrize("style_name", list(SUBTITLE_PRESETS))
def test_layout_fits_box_including_highlight_growth(style_name):
    style = CaptionStyle.from_preset(style_name)
    bw, bh = BOTTOM_BOX[2] - BOTTOM_BOX[0], BOTTOM_BOX[3] - BOTTOM_BOX[1]
    for words in (["Gold"], ["Hans", "Wilsdorf", "founded"], ["$1,000,000", "in", "1999"], [LONG]):
        lay = layout_line(words, style, bw, bh)
        grow = (style.active_scale - 1) * max(lay.widths)
        assert lay.xs[0] - grow / 2 - style.stroke_width >= 0, (style_name, words)
        assert lay.xs[-1] + lay.widths[-1] + grow / 2 + style.stroke_width <= bw, (style_name, words)


@pytest.mark.parametrize("style_name", list(SUBTITLE_PRESETS))
def test_scaled_active_word_never_touches_its_neighbours(style_name):
    style = CaptionStyle.from_preset(style_name)
    lay = layout_line(["Hans", "Wilsdorf", "founded"], style, 892, 148)
    grow = style.active_scale - 1
    for j in range(len(lay.words) - 1):
        gap = lay.xs[j + 1] - (lay.xs[j] + lay.widths[j])
        assert gap >= grow * max(lay.widths[j], lay.widths[j + 1]) / 2 + 2 * style.stroke_width - 1


def test_short_group_keeps_preset_size_long_word_shrinks():
    style = CaptionStyle.from_preset("bold_impact")
    bw, bh = BOTTOM_BOX[2] - BOTTOM_BOX[0], BOTTOM_BOX[3] - BOTTOM_BOX[1]
    assert layout_line(["Gold", "is", "heavy"], style, bw, bh).size == 75
    assert layout_line([LONG], style, bw, bh).size < 50


def test_word_with_no_drawable_glyphs_is_dropped_from_layout():
    style = CaptionStyle.from_preset("bold_impact")
    lay = layout_line(["so", "\U0001F525", "hot"], style, 892, 148)
    assert lay.words == ["SO", "HOT"] and lay.index == [0, 2]


def test_unknown_style_uses_bold_impact():
    assert CaptionStyle.from_preset("nope").name == "bold_impact"


def test_style_colours_come_from_the_preset():
    style = CaptionStyle.from_preset("fire")
    assert style.active == (0xFF, 0x45, 0x00, 0xFF) and style.inactive == (0xFF, 0xD7, 0x00, 0x80)
    assert style.font_fallback is False and style.position == "bottom"
    assert CaptionStyle.from_preset("clean_minimal").bg == (0, 0, 0, 0x80)
