"""Atmospheric particle system — dust, embers, bokeh, snow."""

import math
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PARTICLE_PRESETS = {
    "dust": {"count": 40, "size_range": (2, 6), "opacity_range": (30, 80),
             "color": (255, 255, 240), "speed": 0.3, "blur": 1},
    "embers": {"count": 25, "size_range": (3, 8), "opacity_range": (60, 160),
               "color": (255, 120, 30), "speed": 0.6, "blur": 2},
    "bokeh": {"count": 15, "size_range": (15, 40), "opacity_range": (20, 60),
              "color": (255, 255, 255), "speed": 0.15, "blur": 4},
    "snow": {"count": 60, "size_range": (3, 8), "opacity_range": (80, 180),
             "color": (230, 240, 255), "speed": 0.5, "blur": 1},
    "none": {"count": 0},
}

STYLE_PARTICLES = {
    "photorealistic": "dust",
    "cartoon": "bokeh",
    "anime": "bokeh",
    "stop_motion": "dust",
    "comic_book": "none",
    "3d_render": "dust",
    "pixel_art": "none",
    "watercolor": "dust",
    "oil_painting": "dust",
    "noir": "dust",
}


class ParticleSystem:
    def __init__(self, preset: str = "dust", width: int = 1080, height: int = 1920,
                 seed: int = 42):
        self.width = width
        self.height = height
        self.config = PARTICLE_PRESETS.get(preset, PARTICLE_PRESETS["dust"])
        if self.config["count"] == 0:
            self.particles = []
            return
        random.seed(seed)
        self.particles = []
        for _ in range(self.config["count"]):
            self.particles.append({
                "x": random.uniform(0, width),
                "y": random.uniform(0, height),
                "size": random.uniform(*self.config["size_range"]),
                "opacity": random.randint(*self.config["opacity_range"]),
                "dx": random.uniform(-0.3, 0.3) * self.config["speed"],
                "dy": random.uniform(-0.5, -0.1) * self.config["speed"],
                "phase": random.uniform(0, 2 * math.pi),
            })

    def render_frame(self, t: float) -> np.ndarray:
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        if not self.particles:
            return np.array(img)
        draw = ImageDraw.Draw(img)
        color = self.config["color"]
        for p in self.particles:
            x = (p["x"] + p["dx"] * t * 60) % self.width
            y = (p["y"] + p["dy"] * t * 60) % self.height
            x += math.sin(t * 2 + p["phase"]) * 3
            opacity = int(p["opacity"] * (0.6 + 0.4 * math.sin(t * 3 + p["phase"])))
            opacity = max(0, min(255, opacity))
            r = p["size"]
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color + (opacity,))
        blur_radius = self.config.get("blur", 1)
        if blur_radius > 0:
            img = img.filter(ImageFilter.GaussianBlur(radius=blur_radius))
        return np.array(img)
