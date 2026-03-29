"""Smart transitions between scenes — whip-pan, flash, zoom-through."""

import numpy as np
from PIL import Image, ImageFilter


def whip_pan(frame_a: np.ndarray, frame_b: np.ndarray, t: float,
             direction: str = "right") -> np.ndarray:
    if t < 0.5:
        blur_amount = int(t * 2 * 80)
        if blur_amount > 0:
            pil = Image.fromarray(frame_a)
            pil = pil.filter(ImageFilter.BoxBlur(blur_amount))
            return np.array(pil)
        return frame_a
    else:
        blur_amount = int((1.0 - t) * 2 * 80)
        if blur_amount > 0:
            pil = Image.fromarray(frame_b)
            pil = pil.filter(ImageFilter.BoxBlur(blur_amount))
            return np.array(pil)
        return frame_b


def flash_transition(frame_a: np.ndarray, frame_b: np.ndarray,
                     t: float) -> np.ndarray:
    if t < 0.3:
        brightness = t / 0.3
        white = np.full_like(frame_a, 255)
        return (frame_a.astype(float) * (1 - brightness) +
                white.astype(float) * brightness).astype(np.uint8)
    elif t < 0.5:
        return np.full_like(frame_a, 255)
    else:
        brightness = (1.0 - t) / 0.5
        white = np.full_like(frame_b, 255)
        return (frame_b.astype(float) * (1 - brightness) +
                white.astype(float) * brightness).astype(np.uint8)


def zoom_through(frame_a: np.ndarray, frame_b: np.ndarray,
                 t: float) -> np.ndarray:
    h, w = frame_a.shape[:2]
    if t < 0.5:
        zoom = 1.0 + t * 6
        crop_w = max(int(w / zoom), 1)
        crop_h = max(int(h / zoom), 1)
        x1 = (w - crop_w) // 2
        y1 = (h - crop_h) // 2
        crop = frame_a[y1:y1+crop_h, x1:x1+crop_w]
        return np.array(Image.fromarray(crop).resize((w, h), Image.LANCZOS))
    else:
        zoom = 1.0 + (1.0 - t) * 6
        crop_w = max(int(w / zoom), 1)
        crop_h = max(int(h / zoom), 1)
        x1 = (w - crop_w) // 2
        y1 = (h - crop_h) // 2
        crop = frame_b[y1:y1+crop_h, x1:x1+crop_w]
        return np.array(Image.fromarray(crop).resize((w, h), Image.LANCZOS))


TRANSITIONS = {
    "whip_pan": whip_pan,
    "flash": flash_transition,
    "zoom_through": zoom_through,
}
