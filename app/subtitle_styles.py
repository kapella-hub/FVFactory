"""Karaoke-style subtitle renderer with multiple style presets."""

import logging
from typing import List

import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


SUBTITLE_PRESETS = {
    "bold_impact": {
        "active_color": "#FFFF00",
        "inactive_color": "#FFFFFF80",
        "font": "Arial-Bold",
        "font_size": 75,
        "active_scale": 1.15,
        "stroke_color": "#000000",
        "stroke_width": 4,
        "position": "bottom",
        "bg_box": False,
    },
    "clean_minimal": {
        "active_color": "#FFFFFF",
        "inactive_color": "#FFFFFF60",
        "font": "Helvetica",
        "font_size": 60,
        "active_scale": 1.0,
        "stroke_color": None,
        "stroke_width": 0,
        "position": "center",
        "bg_box": True,
        "bg_color": "#00000080",
    },
    "neon_glow": {
        "active_color": "#00FF88",
        "inactive_color": "#FFFFFF40",
        "font": "Arial-Bold",
        "font_size": 70,
        "active_scale": 1.2,
        "stroke_color": "#00FF88",
        "stroke_width": 2,
        "position": "bottom",
        "bg_box": False,
    },
    "fire": {
        "active_color": "#FF4500",
        "inactive_color": "#FFD70080",
        "font": "Impact",
        "font_size": 80,
        "active_scale": 1.25,
        "stroke_color": "#000000",
        "stroke_width": 5,
        "position": "bottom",
        "bg_box": False,
    },
}


def _hex_to_rgba(hex_color: str) -> tuple:
    """Convert hex color (with optional alpha) to RGBA tuple."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
        return (r, g, b, 255)
    elif len(hex_color) == 8:
        r, g, b, a = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16), int(hex_color[6:8], 16)
        return (r, g, b, a)
    return (255, 255, 255, 255)


class SubtitleRenderer:
    """Renders karaoke-style subtitle frames using PIL."""

    PADDING = 40
    LINE_HEIGHT_MULTIPLIER = 1.3

    def __init__(self, style: str = "bold_impact", width: int = 1080, height: int = 1920):
        self.width = width
        self.height = height

        if style not in SUBTITLE_PRESETS:
            logger.warning(f"Unknown subtitle style '{style}', using 'bold_impact'")
            style = "bold_impact"
        self.preset = SUBTITLE_PRESETS[style]

        self._font = self._load_font(self.preset["font"], self.preset["font_size"])
        active_size = int(self.preset["font_size"] * self.preset.get("active_scale", 1.0))
        self._active_font = self._load_font(self.preset["font"], active_size)

    def _load_font(self, font_name: str, size: int) -> ImageFont.FreeTypeFont:
        """Load a font, falling back to default if not found."""
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            for path in ["/System/Library/Fonts/Helvetica.ttc",
                         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                         "arial.ttf"]:
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
            return ImageFont.load_default()

    def render_subtitle_frame(self, words: List[str], active_index: int) -> np.ndarray:
        """
        Render a subtitle frame with karaoke highlighting.
        Returns RGBA numpy array suitable for compositing over video.
        """
        active_color = _hex_to_rgba(self.preset["active_color"])
        inactive_color = _hex_to_rgba(self.preset["inactive_color"])
        stroke_color = _hex_to_rgba(self.preset["stroke_color"]) if self.preset.get("stroke_color") else None
        stroke_width = self.preset.get("stroke_width", 0)

        # Calculate text dimensions
        text_parts = []
        total_width = 0
        max_height = 0

        for i, word in enumerate(words):
            font = self._active_font if i == active_index else self._font
            word_upper = word.upper()
            bbox = font.getbbox(word_upper)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            space_w = font.getbbox(" ")[2] if i < len(words) - 1 else 0
            text_parts.append({
                "text": word_upper,
                "font": font,
                "width": w,
                "height": h,
                "color": active_color if i == active_index else inactive_color,
                "is_active": i == active_index,
            })
            total_width += w + space_w
            max_height = max(max_height, h)

        # If text is too wide, scale everything down to fit with margin
        max_text_width = self.width - self.PADDING * 2
        if total_width > max_text_width:
            scale = max_text_width / total_width
            scaled_font_size = max(20, int(self.preset["font_size"] * scale))
            scaled_active_size = max(20, int(scaled_font_size * self.preset.get("active_scale", 1.0)))
            scaled_font = self._load_font(self.preset["font"], scaled_font_size)
            scaled_active_font = self._load_font(self.preset["font"], scaled_active_size)

            # Recalculate with scaled fonts
            text_parts = []
            total_width = 0
            max_height = 0
            for i, word in enumerate(words):
                font = scaled_active_font if i == active_index else scaled_font
                word_upper = word.upper()
                bbox = font.getbbox(word_upper)
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                space_w = font.getbbox(" ")[2] if i < len(words) - 1 else 0
                text_parts.append({
                    "text": word_upper,
                    "font": font,
                    "width": w,
                    "height": h,
                    "color": active_color if i == active_index else inactive_color,
                    "is_active": i == active_index,
                })
                total_width += w + space_w
                max_height = max(max_height, h)

        # Create transparent image
        bar_height = max_height + self.PADDING * 2
        img = Image.new("RGBA", (self.width, bar_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Optional background box
        if self.preset.get("bg_box"):
            bg_color = _hex_to_rgba(self.preset.get("bg_color", "#00000080"))
            margin = 20
            box_x1 = (self.width - total_width) // 2 - margin
            box_x2 = (self.width + total_width) // 2 + margin
            draw.rounded_rectangle(
                [box_x1, self.PADDING // 2, box_x2, bar_height - self.PADDING // 2],
                radius=10, fill=bg_color,
            )

        # Draw each word
        x = (self.width - total_width) // 2
        y = self.PADDING

        for part in text_parts:
            if stroke_color and stroke_width > 0:
                for dx in range(-stroke_width, stroke_width + 1):
                    for dy in range(-stroke_width, stroke_width + 1):
                        if dx * dx + dy * dy <= stroke_width * stroke_width:
                            draw.text((x + dx, y + dy), part["text"],
                                      font=part["font"], fill=stroke_color[:3] + (stroke_color[3],))

            draw.text((x, y), part["text"], font=part["font"], fill=part["color"])

            space_w = part["font"].getbbox(" ")[2] if part != text_parts[-1] else 0
            x += part["width"] + space_w

        return np.array(img)
