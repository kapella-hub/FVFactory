"""Shot renderer (spec §6, §13 A). Plays shot_plan shots back to back from one frame function:
source lookup -> framing crop -> colour grade -> particles. Styled transitions blend moving
frames of both neighbouring shots. Video only; audio is mixed and muxed by app.cin.editor.
"""
from __future__ import annotations

import bisect
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from app.cin.particles import STYLE_PARTICLES, ParticleSystem
from app.cin.shot_plan import TRANSITION_LEN, ShotPlan
from app.cin.transitions import TRANSITIONS
from app.encoding import write_video

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1920
PUSH_IN_END = 1.08          # still shots zoom 1.00 -> 1.08 across the shot
UPPER_BIAS = 0.42           # punch-in crop sits slightly above centre (0.5 = centred)

try:  # spec §14: use cv2.resize when available
    import cv2  # type: ignore
except ImportError:  # cv2 is optional; not installed in the dev venv
    cv2 = None


class RenderError(RuntimeError):
    pass


def _resize(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    if arr.shape[1] == w and arr.shape[0] == h:
        return arr
    if cv2 is not None:
        return cv2.resize(arr, (w, h), interpolation=cv2.INTER_LINEAR)
    return np.asarray(Image.fromarray(arr).resize((w, h), Image.BILINEAR))


def cover_fit(frame: np.ndarray, w: int, h: int) -> np.ndarray:
    """Scale to cover w x h and centre-crop. Never stretches (fal clips may not be 9:16)."""
    fh, fw = frame.shape[:2]
    scale = max(w / fw, h / fh)
    nw, nh = max(w, round(fw * scale)), max(h, round(fh * scale))
    big = _resize(frame, nw, nh)
    x, y = (nw - w) // 2, (nh - h) // 2
    return big[y:y + h, x:x + w]


def apply_framing(frame: np.ndarray, zoom: float, w: int, h: int) -> np.ndarray:
    if zoom <= 1.0001:
        return frame
    cw, ch = max(1, round(w / zoom)), max(1, round(h / zoom))
    x = (w - cw) // 2
    y = int((h - ch) * UPPER_BIAS)
    return _resize(np.ascontiguousarray(frame[y:y + ch, x:x + cw]), w, h)


class _Sources:
    """Opens each clip once. Per-reader access is monotonic, so MoviePy never re-seeks."""

    def __init__(self, job, w: int, h: int):
        self.job, self.w, self.h = job, w, h
        self._readers: dict = {}
        self._stills: dict = {}

    def clip_frame(self, rel: str, t: float) -> np.ndarray:
        from moviepy import VideoFileClip
        reader = self._readers.get(rel)
        if reader is None:
            path = self.job.resolve(rel)
            if not path.is_file():
                raise RenderError(f"Clip missing: {rel}")
            reader = self._readers[rel] = VideoFileClip(str(path), audio=False)
        # The planner may ask up to 0.25 s past the clip's end: hold the last decodable frame.
        last = max(0.0, (reader.duration or 0.0) - 1.0 / (reader.fps or 30))
        frame = reader.get_frame(min(max(t, 0.0), last))
        return cover_fit(np.asarray(frame)[:, :, :3], self.w, self.h)

    def still(self, rel: str) -> np.ndarray:
        if rel not in self._stills:
            path = self.job.resolve(rel) if rel else None
            if path is None or not path.is_file():
                logger.warning("Still image missing (%r): rendering a black frame", rel)
                self._stills[rel] = np.zeros((self.h, self.w, 3), np.uint8)
            else:
                self._stills[rel] = cover_fit(np.asarray(Image.open(path).convert("RGB")), self.w, self.h)
        return self._stills[rel]

    def close(self) -> None:
        for reader in self._readers.values():
            try:
                reader.close()
            except Exception:  # noqa: BLE001
                pass
        self._readers.clear()


class ShotRenderer:
    def __init__(self, plan: ShotPlan, job, *, video_style: str = "photorealistic",
                 color_grade: Optional[str] = None, width: int = WIDTH, height: int = HEIGHT,
                 captions=None):
        self.plan, self.job, self.w, self.h = plan, job, width, height
        self.captions = captions          # app.cin.captions.CaptionLayer or None
        self.sources = _Sources(job, width, height)
        self.particles = ParticleSystem(preset=STYLE_PARTICLES.get(video_style, "dust"),
                                        width=width, height=height)
        self.color_grade = color_grade or None
        self._starts = [s.t0 for s in plan.shots]
        self._styled = [(plan.shots[i].t0, plan.shots[i].transition_in, i)
                        for i in range(1, len(plan.shots)) if plan.shots[i].transition_in != "cut"]

    def shot_frame(self, i: int, t: float) -> np.ndarray:
        shot = self.plan.shots[i]
        src = shot.source
        if src.type == "clip":
            frame = self.sources.clip_frame(src.path, src.clip_t0 + (t - shot.t0) * src.speed)
            return apply_framing(frame, shot.framing, self.w, self.h)
        progress = min(max((t - shot.t0) / max(shot.t1 - shot.t0, 1e-6), 0.0), 1.0)
        zoom = shot.framing * (1.0 + (PUSH_IN_END - 1.0) * progress)
        return apply_framing(self.sources.still(src.path), zoom, self.w, self.h)

    def base_frame(self, t: float) -> np.ndarray:
        half = TRANSITION_LEN / 2
        for boundary, name, j in self._styled:
            if boundary - half <= t < boundary + half:
                progress = (t - (boundary - half)) / TRANSITION_LEN
                return TRANSITIONS[name](self.shot_frame(j - 1, t), self.shot_frame(j, t), progress)
        i = min(max(bisect.bisect_right(self._starts, t) - 1, 0), len(self._starts) - 1)
        return self.shot_frame(i, t)

    def frame_at(self, t: float) -> np.ndarray:
        frame = self.base_frame(t)
        if self.color_grade:
            from app.video_editor import apply_color_grade
            frame = apply_color_grade(frame, self.color_grade)
        overlay = self.particles.render_frame(t)
        if overlay.size and overlay.shape[2] == 4 and overlay[:, :, 3].any():
            alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
            frame = (frame.astype(np.float32) * (1 - alpha) + overlay[:, :, :3] * alpha).astype(np.uint8)
        frame = np.ascontiguousarray(frame, dtype=np.uint8)
        if self.captions is not None:                     # spec §7: composited inside the frame function
            # Copy first: an unzoomed still or clip frame can be the cached source array itself.
            frame = self.captions.composite(frame.copy(), t)
        return frame

    def render(self, out_path) -> Path:
        from moviepy import VideoClip
        clip = None
        try:
            # Built inside the try: a first-frame failure (VideoClip samples one) must still close
            # opened clip readers and surface as RenderError.
            clip = VideoClip(self.frame_at, duration=self.plan.duration).with_fps(self.plan.fps)
            write_video(clip, out_path, fps=self.plan.fps)
        except RenderError:
            raise
        except Exception as e:  # noqa: BLE001 - spec §10: renderer errors fail the run
            raise RenderError(f"Render failed: {e}") from e
        finally:
            self.sources.close()
            if clip is not None:
                clip.close()
        return Path(out_path)
