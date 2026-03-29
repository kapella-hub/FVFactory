"""2.5D parallax compositor — moves depth layers at different speeds."""

import numpy as np
from PIL import Image


def render_parallax_frame(layers: list[dict], t: float,
                          camera_x: float = 0.0, camera_y: float = 0.0,
                          camera_zoom: float = 1.0,
                          out_w: int = 1080, out_h: int = 1920) -> np.ndarray:
    canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
    for layer in layers:
        rgba = layer["rgba"]
        speed = layer["speed"]
        h, w = rgba.shape[:2]
        offset_x = int(camera_x * w * 0.1 * speed)
        offset_y = int(camera_y * h * 0.05 * speed)
        layer_zoom = 1.0 + (camera_zoom - 1.0) * speed
        if layer_zoom != 1.0 or offset_x != 0 or offset_y != 0:
            crop_w = max(int(w / layer_zoom), 1)
            crop_h = max(int(h / layer_zoom), 1)
            cx = w // 2 + offset_x
            cy = h // 2 + offset_y
            x1 = max(0, min(cx - crop_w // 2, w - crop_w))
            y1 = max(0, min(cy - crop_h // 2, h - crop_h))
            crop = rgba[y1:y1+crop_h, x1:x1+crop_w]
            pil = Image.fromarray(crop).resize((out_w, out_h), Image.LANCZOS)
            layer_frame = np.array(pil)
        else:
            pil = Image.fromarray(rgba).resize((out_w, out_h), Image.LANCZOS)
            layer_frame = np.array(pil)
        alpha = layer_frame[:, :, 3:4].astype(np.float32) / 255.0
        rgb = layer_frame[:, :, :3].astype(np.float32)
        canvas_f = canvas.astype(np.float32)
        canvas = (rgb * alpha + canvas_f * (1.0 - alpha)).astype(np.uint8)
    return canvas
