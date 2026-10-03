"""Caption + hook-headline layer for the shot renderer (spec §7).

Each caption group is laid out once (one line, shrunk to fit its box) and rasterized once per
highlight state, then alpha-composited inside ShotRenderer.frame_at. A highlight state is
(active word, ramp step): the 80 ms 1.0 -> active_scale ramp is quantized into RAMP_STEPS steps,
so a 3-word group is rasterized at most 3 x (RAMP_STEPS + 1) times. Every sprite is clipped to its
box, so no caption pixel can leave the safe zone whatever the text.
"""
from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw

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


class _Sprite:
    """A rasterized RGBA strip cropped to its ink, stored as float32 rgb + alpha for blending."""

    def __init__(self, img: Image.Image, origin: tuple, clip: tuple):
        arr = np.asarray(img)
        ys, xs = np.nonzero(arr[:, :, 3])
        if len(ys) == 0:
            self.empty = True
            return
        self.empty = False
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        ox, oy = origin
        cx0, cy0, cx1, cy1 = clip
        fx0, fy0 = max(ox + x0, cx0), max(oy + y0, cy0)
        fx1, fy1 = min(ox + x1, cx1), min(oy + y1, cy1)
        if fx0 >= fx1 or fy0 >= fy1:
            self.empty = True
            return
        crop = arr[fy0 - oy:fy1 - oy, fx0 - ox:fx1 - ox]
        self.box = (fx0, fy0, fx1, fy1)
        self.rgb = crop[:, :, :3].astype(np.float32)
        self.alpha = crop[:, :, 3:4].astype(np.float32) / 255.0

    def blend(self, frame: np.ndarray) -> None:
        if self.empty:
            return
        x0, y0, x1, y1 = self.box
        region = frame[y0:y1, x0:x1].astype(np.float32)
        frame[y0:y1, x0:x1] = (region * (1.0 - self.alpha) + self.rgb * self.alpha).astype(np.uint8)


class CaptionLayer:
    def __init__(self, groups: list, style: CaptionStyle, duration: float, *,
                 headline: Optional[dict] = None, width: int = REF_W, height: int = REF_H):
        self.style, self.duration, self.w, self.h = style, duration, width, height
        self.k = width / REF_W
        self.box = scale_box(CENTER_BOX if style.position == "center" else BOTTOM_BOX, width, height)
        bw, bh = self.box[2] - self.box[0], self.box[3] - self.box[1]
        self.groups, self.layouts = [], []
        for g in groups:
            if not g.words:
                continue
            lay = layout_line([w.text for w in g.words], style, bw, bh, size=style.font_size * self.k)
            if lay.words:
                self.groups.append(g)
                self.layouts.append(lay)
        self.windows = self._windows()
        self._starts = [w[0] for w in self.windows]
        self._cache: dict = {}
        self._cache_group = -1
        self.headline = headline if headline and headline.get("text") else None
        self._headline_sprite = self._render_headline() if self.headline else None

    # ------------------------------------------------------------ timing

    def _windows(self) -> list:
        out = []
        n = len(self.groups)
        for i, g in enumerate(self.groups):
            start = 0.0 if i == 0 else g.t0                       # spec §7: captions from frame one
            nxt = self.groups[i + 1].t0 if i + 1 < n else self.duration
            end = min(nxt, g.t1 + HOLD) if i + 1 < n else min(self.duration, g.t1 + HOLD)
            out.append((start, max(end, start + 1e-3), i))
        return out

    def group_at(self, t: float) -> Optional[int]:
        j = bisect.bisect_right(self._starts, t) - 1
        if j < 0:
            return None
        start, end, gi = self.windows[j]
        return gi if start <= t < end else None

    def state_at(self, gi: int, t: float) -> tuple:
        """(laid-out active word position, ramp step). Active = last word whose t0 <= t (the first
        word before it starts), so zero-length or equal-t0 words never break monotonicity."""
        g, lay = self.groups[gi], self.layouts[gi]
        active_word = 0
        for i, w in enumerate(g.words):
            if w.t0 <= t:
                active_word = i
        if active_word not in lay.index:
            return (-1, 0)                                       # active word had no drawable glyphs
        dt = t - g.words[active_word].t0
        step = min(RAMP_STEPS, max(0, int(dt / RAMP_SECONDS * RAMP_STEPS + 1e-6)))
        return (lay.index.index(active_word), step)

    # ------------------------------------------------------------ raster

    def _draw_word(self, draw, xy, text, font, fill, anchor):
        st = self.style
        if st.stroke and st.stroke_width:
            draw.text(xy, text, font=font, fill=fill, anchor=anchor,
                      stroke_width=max(1, round(st.stroke_width * self.k)), stroke_fill=st.stroke)
        else:
            draw.text(xy, text, font=font, fill=fill, anchor=anchor)

    def _rasterize(self, gi: int, active: int, step: int) -> _Sprite:
        lay, st = self.layouts[gi], self.style
        bw, bh = self.box[2] - self.box[0], self.box[3] - self.box[1]
        img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        base = st.font(lay.size)
        if st.bg:
            pad = round(20 * self.k)
            left, right = lay.xs[0] - pad, lay.xs[-1] + lay.widths[-1] + pad
            top, bottom = _ink_extent(base, " ".join(lay.words), 0)
            draw.rounded_rectangle([left, lay.baseline + top - pad // 2, right, lay.baseline + bottom + pad // 2],
                                   radius=round(10 * self.k), fill=st.bg)
        for j, text in enumerate(lay.words):
            if j != active:
                self._draw_word(draw, (lay.xs[j], lay.baseline), text, base, st.inactive, "ls")
        if active >= 0:
            scale = 1.0 + (st.active_scale - 1.0) * step / RAMP_STEPS
            font = st.font(lay.size * scale)
            cx = lay.xs[active] + lay.widths[active] / 2
            self._draw_word(draw, (cx, lay.baseline), lay.words[active], font, st.active, "ms")
        return _Sprite(img, (self.box[0], self.box[1]), self.box)

    def sprite(self, gi: int, state: tuple) -> _Sprite:
        if gi != self._cache_group:                              # groups only move forward: drop the old one
            self._cache.clear()
            self._cache_group = gi
        if state not in self._cache:
            self._cache[state] = self._rasterize(gi, *state)
        return self._cache[state]

    def _render_headline(self) -> _Sprite:
        st = self.style
        box = scale_box(HEADLINE_BOX, self.w, self.h)
        bw, bh = box[2] - box[0], box[3] - box[1]
        sw = max(4, st.stroke_width)
        size = int(st.font_size * HEADLINE_SCALE * self.k)
        words = drawable(self.headline["text"], st.font(size)).split()
        while True:
            font = st.font(size)
            lines = _wrap(words, font, bw - 2 * sw, HEADLINE_MAX_LINES)
            asc, desc = font.getmetrics()
            line_h = asc + desc + 2 * sw
            if lines is not None and line_h * len(lines) <= bh:
                break
            if size <= MIN_FONT:
                lines = [" ".join(words)]                      # clipped to the band by _Sprite
                break
            size = max(MIN_FONT, int(size * 0.92))
        img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        y = (bh - line_h * len(lines)) / 2 + sw
        for line in lines:
            draw.text((bw / 2, y), line, font=font, fill=(255, 255, 255, 255), anchor="ma",
                      stroke_width=sw, stroke_fill=(0, 0, 0, 255))
            y += line_h
        return _Sprite(img, (box[0], box[1]), box)

    # ------------------------------------------------------------ per frame

    def composite(self, frame: np.ndarray, t: float) -> np.ndarray:
        if self.headline and self.headline["t0"] <= t < self.headline["t1"]:
            self._headline_sprite.blend(frame)
        gi = self.group_at(t)
        if gi is not None:
            self.sprite(gi, self.state_at(gi, t)).blend(frame)
        return frame


def _wrap(words: list, font, max_w: float, max_lines: int) -> Optional[list]:
    """Greedy wrap into at most max_lines lines no wider than max_w; None when it cannot."""
    lines, cur = [], []
    for w in words:
        trial = " ".join(cur + [w])
        if cur and font.getlength(trial) > max_w:
            lines.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(" ".join(cur))
    if len(lines) > max_lines or any(font.getlength(l) > max_w for l in lines):
        return None
    return lines


def build_caption_layer(plan, subtitle_style: str, *, report=None, enable_subtitles: bool = True,
                        width: int = REF_W, height: int = REF_H) -> Optional[CaptionLayer]:
    """CaptionLayer for a ShotPlan, or None when there is nothing to draw. A missing bundled font
    is recorded once as font_fallback in the run report."""
    if not enable_subtitles:                      # subtitles off means no burned-in text at all
        return None
    groups = plan.captions
    if not groups and not plan.hook_headline:
        return None
    style = CaptionStyle.from_preset(subtitle_style)
    if style.font_fallback and report is not None:
        report.warn("font_fallback", f"Caption font {style.font_file} missing; using a system font",
                    {"style": style.name, "font_file": style.font_file})
    return CaptionLayer(groups, style, plan.duration, headline=plan.hook_headline, width=width, height=height)
