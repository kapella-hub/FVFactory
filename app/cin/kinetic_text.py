"""Kinetic typography — animated text for key moments."""

import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ["Impact", "Arial-Bold", "/System/Library/Fonts/Helvetica.ttc"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_slam_in(word: str, t: float, width: int = 1080, height: int = 1920,
                   color: tuple = (255, 255, 255)) -> np.ndarray:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if t < 0.5:
        scale = 3.0 - t * 4.0
    else:
        bounce = math.sin((t - 0.5) * math.pi * 2) * 0.15
        scale = 1.0 + bounce * (1.0 - t)
    scale = max(0.5, scale)
    font_size = int(120 * scale)
    font = _load_font(font_size)
    word_upper = word.upper()
    bbox = font.getbbox(word_upper)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = height // 2 - th // 2
    opacity = min(255, int(t * 10 * 255))
    stroke_w = max(3, int(4 * scale))
    for dx in range(-stroke_w, stroke_w + 1):
        for dy in range(-stroke_w, stroke_w + 1):
            if dx * dx + dy * dy <= stroke_w * stroke_w:
                draw.text((x + dx, y + dy), word_upper, font=font, fill=(0, 0, 0, opacity))
    draw.text((x, y), word_upper, font=font, fill=color + (opacity,))
    return np.array(img)


def render_pop(word: str, t: float, width: int = 1080, height: int = 1920,
               color: tuple = (255, 69, 0)) -> np.ndarray:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if t < 0.01:
        scale = 0.0
    else:
        p = t
        scale = 1.0 + (2 ** (-10 * p)) * math.sin((p * 10 - 0.75) * (2 * math.pi / 3)) * -1
        scale = max(0.0, min(1.5, scale))
    if scale < 0.01:
        return np.array(img)
    font_size = int(100 * scale)
    font = _load_font(max(font_size, 10))
    word_upper = word.upper()
    bbox = font.getbbox(word_upper)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (width - tw) // 2
    y = height // 2 - th // 2
    for dx in range(-4, 5):
        for dy in range(-4, 5):
            if dx * dx + dy * dy <= 16:
                draw.text((x + dx, y + dy), word_upper, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), word_upper, font=font, fill=color + (255,))
    return np.array(img)
