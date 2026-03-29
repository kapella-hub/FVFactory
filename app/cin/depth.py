"""Depth estimation using Depth Anything v2 Small.

Model: ~24MB, runs in <1s per image on Apple Silicon MPS.
Falls back to gradient-based pseudo-depth if model unavailable.
"""

import logging
import numpy as np
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

_depth_pipeline = None


def _get_depth_pipeline():
    global _depth_pipeline
    if _depth_pipeline is not None:
        return _depth_pipeline
    try:
        from transformers import pipeline
        _depth_pipeline = pipeline(
            "depth-estimation",
            model="depth-anything/Depth-Anything-V2-Small-hf",
            device="mps",
        )
        logger.info("Depth Anything v2 Small loaded on MPS")
    except Exception as e:
        logger.warning("Depth model unavailable (%s), using gradient fallback", e)
        _depth_pipeline = "fallback"
    return _depth_pipeline


def estimate_depth(image_path: str) -> np.ndarray:
    img = Image.open(image_path).convert("RGB")
    pipe = _get_depth_pipeline()
    if pipe != "fallback" and pipe is not None:
        try:
            result = pipe(img)
            depth = np.array(result["depth"]).astype(np.float32)
            if depth.shape[:2] != (img.height, img.width):
                depth_img = Image.fromarray(depth).resize((img.width, img.height), Image.BILINEAR)
                depth = np.array(depth_img).astype(np.float32)
        except Exception as e:
            logger.warning("Depth estimation failed: %s, using fallback", e)
            depth = _gradient_depth(img.width, img.height)
    else:
        depth = _gradient_depth(img.width, img.height)
    dmin, dmax = depth.min(), depth.max()
    if dmax > dmin:
        depth = (depth - dmin) / (dmax - dmin)
    else:
        depth = np.zeros_like(depth)
    return depth


def _gradient_depth(width: int, height: int) -> np.ndarray:
    return np.linspace(0.0, 1.0, height, dtype=np.float32)[:, np.newaxis].repeat(width, axis=1)


def split_into_layers(img_arr: np.ndarray, depth: np.ndarray,
                      num_layers: int = 3) -> list[dict]:
    h, w = img_arr.shape[:2]
    layers = []
    for i in range(num_layers):
        lo = i / num_layers
        hi = (i + 1) / num_layers
        mask = ((depth >= lo) & (depth < hi)).astype(np.float32)
        mask_img = Image.fromarray((mask * 255).astype(np.uint8))
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=3))
        mask = np.array(mask_img).astype(np.float32) / 255.0
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[:, :, :3] = img_arr[:, :, :3]
        rgba[:, :, 3] = (mask * 255).astype(np.uint8)
        speed = 0.3 + (i / max(num_layers - 1, 1)) * 1.4
        layers.append({"rgba": rgba, "depth_range": (lo, hi), "speed": speed})
    return layers


def unload_depth_model():
    global _depth_pipeline
    if _depth_pipeline is not None and _depth_pipeline != "fallback":
        del _depth_pipeline
    _depth_pipeline = None
    logger.info("Depth model unloaded")
