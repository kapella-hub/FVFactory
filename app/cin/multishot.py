"""Multi-shot editor — extracts multiple shots from a single image
and plans cuts synced to audio emphasis."""

import logging
import random

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

SHOT_DEFS = {
    "wide": (0.0, 0.0, 1.0, 1.0),
    "medium": (0.1, 0.05, 0.8, 0.65),
    "close_up": (0.15, 0.15, 0.7, 0.5),
    "detail_top": (0.1, 0.0, 0.6, 0.4),
    "detail_bottom": (0.2, 0.5, 0.7, 0.5),
    "ultra_close": (0.25, 0.25, 0.5, 0.35),
}


def extract_shots(img_arr: np.ndarray, out_w: int = 1080,
                  out_h: int = 1920) -> list[dict]:
    h, w = img_arr.shape[:2]
    shots = []
    for shot_type, (xf, yf, wf, hf) in SHOT_DEFS.items():
        x1 = int(w * xf)
        y1 = int(h * yf)
        cw = max(int(w * wf), 1)
        ch = max(int(h * hf), 1)
        x2 = min(x1 + cw, w)
        y2 = min(y1 + ch, h)
        crop = img_arr[y1:y2, x1:x2]
        resized = np.array(Image.fromarray(crop).resize((out_w, out_h), Image.LANCZOS))
        shots.append({"type": shot_type, "crop": resized})
    return shots


def plan_cuts(scene_duration: float, emphasis_points: list[float] = None,
              min_shot_duration: float = 0.8) -> list[dict]:
    if not emphasis_points:
        emphasis_points = []
    cuts = [{"time": 0.0, "shot_type": "wide", "duration": 0.0}]
    close_shots = ["close_up", "detail_top", "detail_bottom", "medium", "ultra_close"]
    last_cut_time = 0.0
    for emp_time in emphasis_points:
        if emp_time < last_cut_time + min_shot_duration:
            continue
        if emp_time >= scene_duration - min_shot_duration:
            break
        shot = random.choice(close_shots)
        cuts.append({"time": emp_time, "shot_type": shot, "duration": 0.0})
        last_cut_time = emp_time
    if len(cuts) == 1 and scene_duration > 2.0:
        interval = scene_duration / 3
        cuts.append({"time": interval, "shot_type": "medium", "duration": 0.0})
        if scene_duration > 4.0:
            cuts.append({"time": interval * 2, "shot_type": "close_up", "duration": 0.0})
    for i in range(len(cuts)):
        if i + 1 < len(cuts):
            cuts[i]["duration"] = cuts[i + 1]["time"] - cuts[i]["time"]
        else:
            cuts[i]["duration"] = scene_duration - cuts[i]["time"]
    return cuts
