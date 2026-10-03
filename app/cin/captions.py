"""Caption + hook-headline layer for the shot renderer (spec §7).

Each caption group is laid out once (one line, shrunk to fit its box) and rasterized once per
highlight state, then alpha-composited inside ShotRenderer.frame_at. A highlight state is
(active word, ramp step): the 80 ms 1.0 -> active_scale ramp is quantized into RAMP_STEPS steps,
so a 3-word group is rasterized at most 3 x (RAMP_STEPS + 1) times. Every sprite is clipped to its
box, so no caption pixel can leave the safe zone whatever the text.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.fonts import load_font

logger = logging.getLogger(__name__)

REF_W, REF_H = 1080, 1920
# Boxes are (x0, y0, x1, y1) at 1080x1920, end-exclusive. Spec §7: bottom captions centred at
# y ~ 1325 (1250-1400), never below y = 1410 or right of x = 990. 4-8 px are left as margin for
# H.264 4:2:0 chroma bleed, so decoded frames also stay inside the spec's numbers.
BOTTOM_BOX = (94, 1254, 986, 1402)
CENTER_BOX = (94, 886, 986, 1034)          # "center" preset: vertical frame centre
HEADLINE_BOX = (94, 258, 986, 442)          # spec §7: top band y ~ 250-450
RAMP_SECONDS = 0.08                         # spec §7: 1.0 -> active_scale over 80 ms
RAMP_STEPS = 4
HOLD = 0.4                                  # a group stays up to 0.4 s after its last word ...
                                            # ... but never past the next group's start
MIN_FONT = 12
HEADLINE_SCALE = 1.6                        # headline starts at caption size x 1.6, then shrinks to fit
HEADLINE_MAX_LINES = 2


def _rgba(hex_color: Optional[str]) -> Optional[tuple]:
    if not hex_color:
        return None
    h = hex_color.lstrip("#")
    if len(h) == 6:
        h += "FF"
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4, 6))


@dataclass
class CaptionStyle:
    name: str
    font_file: str
    font_weight: Optional[int]
    font_size: int
    active_scale: float
    active: tuple
    inactive: tuple
    stroke: Optional[tuple]
    stroke_width: int
    position: str
    bg: Optional[tuple]
    font_fallback: bool = False

    @classmethod
    def from_preset(cls, name: str) -> "CaptionStyle":
        from app.subtitle_styles import SUBTITLE_PRESETS
        if name not in SUBTITLE_PRESETS:
            logger.warning("Unknown subtitle style %r, using 'bold_impact'", name)
            name = "bold_impact"
        p = SUBTITLE_PRESETS[name]
        style = cls(name=name, font_file=p["font_file"], font_weight=p.get("font_weight"),
                    font_size=p["font_size"], active_scale=float(p.get("active_scale", 1.0)),
                    active=_rgba(p["active_color"]), inactive=_rgba(p["inactive_color"]),
                    stroke=_rgba(p.get("stroke_color")), stroke_width=int(p.get("stroke_width") or 0),
                    position=p.get("position", "bottom"),
                    bg=_rgba(p.get("bg_color", "#00000080")) if p.get("bg_box") else None)
        _, style.font_fallback = load_font(style.font_file, style.font_size, style.font_weight)
        return style

    def font(self, size: int):
        return load_font(self.font_file, max(MIN_FONT, int(round(size))), self.font_weight)[0]


def scale_box(box: tuple, width: int, height: int) -> tuple:
    sx, sy = width / REF_W, height / REF_H
    return (round(box[0] * sx), round(box[1] * sy), round(box[2] * sx), round(box[3] * sy))


def drawable(text: str, font) -> str:
    """Upper-cased text with every character the font cannot draw removed (emoji, CJK in a Latin
    font). A missing glyph rasterizes as the font's .notdef box, so compare against that."""
    tofu = font.getmask("\U0010FFFD")
    tofu_key = (tofu.size, bytes(tofu))
    out = []
    for ch in text.upper():
        if ch.isspace():
            out.append(" ")
            continue
        m = font.getmask(ch)
        if (m.size, bytes(m)) != tofu_key:
            out.append(ch)
    return "".join(out).strip()


@dataclass
class LineLayout:
    size: int                 # fitted base font size
    words: list               # drawable upper-case words (non-empty)
    index: list               # caption word index for each laid-out word
    xs: list                  # left x of each word, box-local, at base size
    widths: list
    baseline: int             # box-local y of the text baseline


def _ink_extent(font, text: str, stroke: int) -> tuple:
    """(top, bottom) of the ink relative to the baseline, stroke included."""
    x0, y0, x1, y1 = font.getbbox(text, anchor="ls", stroke_width=stroke)
    return y0, y1


def layout_line(words: list, style: CaptionStyle, box_w: int, box_h: int, size: Optional[int] = None) -> LineLayout:
    """Fit a single caption line: base width plus the widest word's highlight growth must fit box_w,
    and the active-size ink (stroke included) must fit box_h. words: raw caption word texts."""
    size = int(size or style.font_size)
    base_font = style.font(size)
    texts, index = [], []
    for i, w in enumerate(words):
        d = drawable(w, base_font)
        if d:
            texts.append(d)
            index.append(i)
    sw = style.stroke_width
    while True:
        font = style.font(size)
        active = style.font(size * style.active_scale)
        widths = [font.getlength(t) for t in texts]
        grow = style.active_scale - 1.0
        space = font.getlength(" ")
        # Only one word is scaled at a time: each gap absorbs half the larger neighbour's growth,
        # so the active word never touches the words beside it.
        gaps = [space + 2 * sw + grow * max(a, b) / 2 for a, b in zip(widths, widths[1:])]
        text_w = sum(widths) + sum(gaps)
        need_w = text_w + grow * max(widths, default=0) + 2 * sw
        tops, bottoms = zip(*[_ink_extent(active, t, sw) for t in texts]) if texts else ((0,), (0,))
        need_h = max(bottoms) - min(tops)
        if (need_w <= box_w and need_h <= box_h) or size <= MIN_FONT:
            break
        factor = min(box_w / max(need_w, 1), box_h / max(need_h, 1), 0.97)
        size = max(MIN_FONT, int(size * factor))
    x = (box_w - text_w) / 2
    xs = []
    for w, gap in zip(widths, gaps + [0.0]):
        xs.append(round(x))
        x += w + gap
    baseline = round(box_h / 2 - (min(tops) + max(bottoms)) / 2)
    return LineLayout(size, texts, index, xs, [round(w) for w in widths], baseline)
