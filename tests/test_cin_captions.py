"""Caption layout + layer (spec §7): safe zone, highlight ramp, frame-one captions, hook headline."""
import numpy as np
import pytest

from app.cin.caption_groups import CaptionGroup, CaptionWord, group_captions
from app.cin.captions import (BOTTOM_BOX, HEADLINE_BOX, RAMP_SECONDS, CaptionLayer, CaptionStyle,
                              build_caption_layer, drawable, layout_line, scale_box)
from app.cin.report import RunReport
from app.cin.shot_plan import ShotPlan
from app.subtitle_styles import SUBTITLE_PRESETS
from tests.conftest import fixture_alignment

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


def group(*words, t=0.0, step=0.3):
    ws = [CaptionWord(w, round(t + i * step, 3), round(t + (i + 1) * step - 0.02, 3)) for i, w in enumerate(words)]
    return CaptionGroup(ws[0].t0, ws[-1].t1, ws)


def ink(frame):
    """(x0, y0, x1, y1) end-exclusive bbox of non-black pixels, or None."""
    ys, xs = np.nonzero(frame.max(axis=2) > 0)
    if len(ys) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def black():
    return np.zeros((1920, 1080, 3), np.uint8)


def plan_with(captions, duration=8.0, hook_headline=None):
    return ShotPlan(duration=duration, fps=30, pacing="standard", alignment={}, scenes=[], shots=[],
                    captions=captions, hook_headline=hook_headline)


# ---------------------------------------------------------------- layer: placement

@pytest.mark.parametrize("style_name", BOTTOM_STYLES)
def test_bottom_captions_stay_in_safe_zone_at_peak_highlight(style_name):
    """The widest moment is the LAST word at full scale (t = last.t0 + 80 ms), not a random frame."""
    for words in (("Hans", "Wilsdorf", "founded"), ("waterproof", "wristwatch", "the"), (LONG,),
                  ("$1,000,000", "in", "1999")):
        g = group(*words)
        layer = CaptionLayer([g], CaptionStyle.from_preset(style_name), 8.0)
        for w in g.words:
            box = ink(layer.composite(black(), w.t0 + RAMP_SECONDS + 0.001))
            assert box is not None
            x0, y0, x1, y1 = box
            assert 1250 <= y0 and y1 <= 1410, (style_name, words, box)     # spec §7 vertical zone
            assert x0 >= 90 and x1 <= 990, (style_name, words, box)         # never right of x = 990
            assert 1250 <= (y0 + y1) / 2 <= 1400                            # block centre in 1250-1400


def test_center_preset_sits_at_frame_centre():
    layer = CaptionLayer([group("clean", "minimal")], CaptionStyle.from_preset("clean_minimal"), 8.0)
    x0, y0, x1, y1 = ink(layer.composite(black(), 0.1))
    assert 880 <= y0 and y1 <= 1040 and x1 <= 990


# ---------------------------------------------------------------- layer: timing

def test_captions_show_from_frame_one():
    g = group("Gold", "is", "heavier", t=0.05)
    layer = CaptionLayer([g], CaptionStyle.from_preset("bold_impact"), 8.0)
    assert ink(layer.composite(black(), 0.0)) is not None


def test_group_hides_after_hold_and_yields_to_next_group():
    a, b = group("one", "two", t=0.0), group("three", t=3.0)
    layer = CaptionLayer([a, b], CaptionStyle.from_preset("bold_impact"), 8.0)
    assert layer.group_at(0.3) == 0
    assert layer.group_at(a.t1 + 0.2) == 0
    assert layer.group_at(a.t1 + 0.5) is None
    assert layer.group_at(3.05) == 1
    assert layer.group_at(7.9) is None


def test_active_word_ramps_over_80ms_then_holds():
    g = group("Gold", "is", "heavy")
    layer = CaptionLayer([g], CaptionStyle.from_preset("fire"), 8.0)
    w = g.words[1]
    assert layer.state_at(0, w.t0) == (1, 0)
    assert layer.state_at(0, w.t0 + RAMP_SECONDS / 2) == (1, 2)
    assert layer.state_at(0, w.t0 + RAMP_SECONDS) == (1, 4)
    assert layer.state_at(0, w.t0 + 0.2) == (1, 4)
    small = ink(layer.composite(black(), w.t0))
    big = ink(layer.composite(black(), w.t0 + RAMP_SECONDS))
    assert (big[3] - big[1]) > (small[3] - small[1])                 # the active word really grows


def test_equal_start_times_never_go_backwards():
    """Rolex fixture: '40' and 'percent' share t0 = 30.46 (one Whisper word)."""
    words = [CaptionWord("40", 30.46, 30.73), CaptionWord("percent", 30.46, 30.73), CaptionWord("above", 30.77, 31.13)]
    layer = CaptionLayer([CaptionGroup(30.46, 31.13, words)], CaptionStyle.from_preset("bold_impact"), 40.0)
    seen = [layer.state_at(0, t)[0] for t in np.arange(30.40, 31.2, 1 / 30)]
    assert seen == sorted(seen) and seen[-1] == 2


def test_each_highlight_state_is_rasterized_once(monkeypatch):
    g = group("Gold", "is", "heavy")
    layer = CaptionLayer([g], CaptionStyle.from_preset("bold_impact"), 8.0)
    calls = []
    real = layer._rasterize
    monkeypatch.setattr(layer, "_rasterize", lambda *a: calls.append(a) or real(*a))
    for t in np.arange(0.0, 1.3, 1 / 30):
        layer.composite(black(), t)
    assert len(calls) == len(set(calls)) <= 3 * 5


# ---------------------------------------------------------------- headline

def test_hook_headline_in_top_band_only_for_first_2_5_seconds():
    layer = CaptionLayer([], CaptionStyle.from_preset("bold_impact"), 8.0,
                         headline={"text": "This watch costs more than a car", "t0": 0.0, "t1": 2.5})
    x0, y0, x1, y1 = ink(layer.composite(black(), 0.0))
    assert 250 <= y0 and y1 <= 450 and 90 <= x0 and x1 <= 990
    assert ink(layer.composite(black(), 2.49)) is not None
    assert ink(layer.composite(black(), 2.5)) is None


def test_eight_word_headline_wraps_inside_band():
    layer = CaptionLayer([], CaptionStyle.from_preset("fire"), 8.0,
                         headline={"text": "Nobody believed this tiny watch could survive", "t0": 0.0, "t1": 2.5})
    x0, y0, x1, y1 = ink(layer.composite(black(), 1.0))
    assert 250 <= y0 and y1 <= 450 and x1 <= 990


# ---------------------------------------------------------------- factory

def test_build_layer_none_when_nothing_to_draw():
    assert build_caption_layer(plan_with([]), "bold_impact") is None
    assert build_caption_layer(plan_with([group("a")]), "bold_impact", enable_subtitles=False) is None


def test_empty_caption_list_still_draws_headline():
    layer = build_caption_layer(plan_with([], hook_headline={"text": "Gold is heavy", "t0": 0.0, "t1": 2.5}),
                                "bold_impact")
    assert layer is not None and ink(layer.composite(black(), 1.0)) is not None


def test_subtitles_off_drops_headline_too():
    plan = plan_with([group("a")], hook_headline={"text": "Gold is heavy", "t0": 0.0, "t1": 2.5})
    assert build_caption_layer(plan, "bold_impact", enable_subtitles=False) is None


def test_missing_font_records_font_fallback(monkeypatch):
    monkeypatch.setitem(SUBTITLE_PRESETS["bold_impact"], "font_file", "Gone.ttf")
    report = RunReport(job="j")
    layer = build_caption_layer(plan_with([group("still", "renders")]), "bold_impact", report=report)
    assert [w["code"] for w in report.warnings] == ["font_fallback"]
    assert report.warnings[0]["detail"]["font_file"] == "Gone.ttf"
    box = ink(layer.composite(black(), 0.1))
    assert box is not None and 1250 <= box[1] and box[3] <= 1410


def test_rolex_fixture_every_frame_in_zone():
    """Whole 40 s fixture at 4 fps: every caption frame inside the safe zone, no exceptions."""
    a = fixture_alignment("words_rolex_40s.json")
    layer = CaptionLayer(group_captions(a.tokens), CaptionStyle.from_preset("fire"), a.duration)
    for t in np.arange(0.0, a.duration, 0.25):
        box = ink(layer.composite(black(), float(t)))
        if box:
            assert 1250 <= box[1] and box[3] <= 1410 and box[2] <= 990, (t, box)


def test_pathological_word_is_clipped_to_every_box():
    """Controller ruling: a 400-char word at MIN_FONT must not put a pixel outside its box."""
    word = "W" * 400
    for style_name in SUBTITLE_PRESETS:
        style = CaptionStyle.from_preset(style_name)
        layer = CaptionLayer([group(word)], style, 8.0,
                             headline={"text": word, "t0": 0.0, "t1": 2.5})
        frame = layer.composite(black(), 0.1)
        outside = frame.copy()
        for x0, y0, x1, y1 in (layer.box, scale_box(HEADLINE_BOX, 1080, 1920)):
            outside[y0:y1, x0:x1] = 0
        assert outside.max() == 0, style_name
        assert ink(frame) is not None
