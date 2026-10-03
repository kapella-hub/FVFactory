"""Bundled OFL caption fonts (spec §7). Presets name a file in assets/fonts/, never a system font,
so Windows and the Linux VPS rasterize identically. A missing or unreadable file falls back to a
system font and reports fell_back=True (the shot editor records it as font_fallback)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import ImageFont

logger = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
SYSTEM_FALLBACKS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # Docker image: fonts-dejavu-core
    "DejaVuSans-Bold.ttf",
    "arialbd.ttf",                                             # Windows
    "arial.ttf",
)


def font_path(file: str) -> Path:
    return FONTS_DIR / file


def system_fallback(size: int) -> ImageFont.ImageFont:
    for name in SYSTEM_FALLBACKS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def load_font(file: str, size: int, weight: Optional[int] = None):
    """(font, fell_back). weight sets the 'wght' axis of a variable font (Montserrat-Variable.ttf).
    The axis is per FreeTypeFont instance, so it is applied on every load, at every size.
    Note: getname() keeps reporting the default instance ("Thin") after the axis is set."""
    size = max(1, int(size))
    path = font_path(file)
    try:
        font = ImageFont.truetype(str(path), size)
    except OSError:
        logger.warning("Caption font %s not found or unreadable; using a system font", path)
        return system_fallback(size), True
    if weight is not None:
        try:
            font.set_variation_by_axes([weight])
        except (OSError, AttributeError) as e:   # not variable / FreeType built without MM support
            logger.warning("Cannot set weight %s on %s (%s); using a system font", weight, path, e)
            return system_fallback(size), True
    return font, False
