"""Motion-clip sourcing for planned segments (spec §6.4, §10).

Scenes are generated in parallel (settings.motion_concurrency). Segments inside a scene run in
order, because a chained segment starts from the previous segment's last frame (or the scene
image when that clip failed). Per segment: model, retry once, settings.fal_video_fallback_model,
then give up — build_shot_plan turns a failed segment into a push-in still (still_fallback).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from PIL import Image

from app.cin.shot_plan import ClipSpec

logger = logging.getLogger(__name__)


class StrictModeError(RuntimeError):
    """strict=True and the plan would ship a still-fallback shot (spec §10)."""


def probe_clip_duration(path) -> float:
    from moviepy import VideoFileClip
    clip = VideoFileClip(str(path), audio=False)
    try:
        return float(clip.duration or 0.0)
    finally:
        clip.close()


def extract_last_frame(clip_path, png_path) -> Optional[str]:
    from moviepy import VideoFileClip
    try:
        clip = VideoFileClip(str(clip_path), audio=False)
        try:
            t = max(0.0, (clip.duration or 0.0) - 1.5 / (clip.fps or 30))
            Image.fromarray(clip.get_frame(t)[:, :, :3]).save(png_path)
        finally:
            clip.close()
        return str(png_path)
    except Exception as e:  # noqa: BLE001 - a missing last frame only loses chaining
        logger.warning("Could not extract last frame of %s: %s", clip_path, e)
        return None


def _requested_for(key: str, requested_len: float) -> float:
    """The length model `key` is actually asked for: build_fal_arguments snaps the request up to the
    model's supported lengths (a 3 s Kling request becomes 5 s on H3)."""
    from app.motion_gen import CLIP_MODELS, snap_duration     # late: tests reload app.motion_gen
    model = CLIP_MODELS.get(key)
    if model is None or model.durations is None:
        return requested_len
    return snap_duration(requested_len, model.durations) or max(model.durations)


def _attempt_models(model_key: str, fallback_model: Optional[str]) -> list:
    keys = [model_key, model_key]                       # first try + one retry
    if fallback_model and fallback_model != model_key:
        keys.append(fallback_model)
    return keys


def generate_segment_clips(requests: list, image_paths: list, motion_prompts: list, job, report, *,
                           enable_motion: bool = True, generator=None, model_key: str = "hailuo",
                           fallback_model: Optional[str] = None,
                           concurrency: Optional[int] = None) -> list:
    """Generate one clip per SegmentRequest. Never raises for clip failures; returns ClipSpecs
    in (scene, index) order with job-relative posix paths."""
    from app.config import settings

    if enable_motion and generator is None:
        from app.motion_gen import MotionGenerator
        generator = MotionGenerator(temp_dir=str(job.clips))

    by_scene: dict = {}
    for req in requests:
        by_scene.setdefault(req.scene, []).append(req)

    def run_scene(scene_reqs: list) -> list:
        specs, prev_last = [], None
        for req in sorted(scene_reqs, key=lambda r: r.index):
            start = None
            try:
                start = prev_last if (req.chained and prev_last) else image_paths[req.scene]
                spec = ClipSpec(req.scene, req.index, req.t0, req.t1, req.requested_len, job.rel(start))
                prev_last = None
                if enable_motion:
                    prompt = motion_prompts[req.scene] if req.scene < len(motion_prompts) else ""
                    out = job.clip(req.name)
                    for n, key in enumerate(_attempt_models(model_key, fallback_model), start=1):
                        spec.attempts = n
                        if generator.generate_clip(str(start), prompt, str(out),
                                                   duration=req.requested_len, model_key=key):
                            spec.path, spec.model = job.rel(out), key
                            spec.billed_len = _requested_for(key, req.requested_len)
                            break
                    if spec.path:
                        try:
                            spec.duration = probe_clip_duration(out)
                        except Exception as e:  # noqa: BLE001 - corrupt download counts as a failure
                            logger.warning("Unreadable clip %s: %s", out, e)
                            spec.path, spec.model = None, ""
                    if spec.path:
                        last = extract_last_frame(out, job.last_frame(req.name))
                        spec.last_frame = job.rel(last) if last else None
                        prev_last = last
                    else:
                        spec.failed = True
            except Exception as e:  # noqa: BLE001 - one bad segment must not sink the other scenes
                logger.error("Clip segment %s failed unexpectedly: %s", req.name, e)
                prev_last = None
                try:   # the still fallback needs a real image; never let this lookup re-raise
                    fallback_image = job.rel(start if start is not None else image_paths[req.scene])
                except Exception:  # noqa: BLE001
                    fallback_image = ""
                spec = ClipSpec(req.scene, req.index, req.t0, req.t1, req.requested_len,
                                fallback_image, failed=True)
            specs.append(spec)
        return specs

    workers = max(1, concurrency or settings.motion_concurrency)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run_scene, [by_scene[k] for k in sorted(by_scene)]))
    specs = [s for scene_specs in results for s in scene_specs]

    by_model: dict = {}
    for s in specs:
        if s.path:
            by_model[s.model] = by_model.get(s.model, 0) + 1
            if s.attempts > 1:
                report.warn("clip_retry", f"scene {s.scene} segment {s.index} needed {s.attempts} attempts",
                            {"scene": s.scene, "segment": s.index, "model": s.model, "attempts": s.attempts})
    report.clips = {
        "requested": len(specs) if enable_motion else 0,
        "generated": sum(1 for s in specs if s.path),
        "failed": sum(1 for s in specs if s.failed),
        "by_model": by_model,
    }
    return specs
