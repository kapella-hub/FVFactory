"""Motion Generator — fal.ai Minimax Hailuo (default), Replicate, or local fallback."""

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClipModel:
    """A motion model and the clip lengths it can return (spec §6.4)."""
    key: str
    endpoint: Optional[str]                    # fal endpoint; None for non-fal providers
    durations: Optional[Tuple[float, ...]]     # supported lengths in seconds; None = any length
    sends_duration: bool = False               # pass a "duration" argument to the endpoint


# Kling v1 / v1.5 fal endpoints are marked deprecated on fal.ai (checked 2026-10-02); they stay
# for existing configs. Sub-project 3 replaces this table with current models.
CLIP_MODELS = {
    "hailuo": ClipModel("hailuo", "fal-ai/minimax-video/image-to-video", (6.0,)),
    "kling": ClipModel("kling", "fal-ai/kling-video/v1/standard/image-to-video", (5.0, 10.0), True),
    "kling-pro": ClipModel("kling-pro", "fal-ai/kling-video/v1.5/pro/image-to-video", (5.0, 10.0), True),
    "replicate-minimax": ClipModel("replicate-minimax", None, (6.0,)),
    "local": ClipModel("local", None, None),
}

# fal.ai model endpoints (kept for older call sites)
FAL_MODELS = {key: m.endpoint for key, m in CLIP_MODELS.items() if m.endpoint}


def clip_model_for(provider: str, fal_model: str) -> ClipModel:
    if provider == "local":
        return CLIP_MODELS["local"]
    if provider == "replicate":
        return CLIP_MODELS["replicate-minimax"]
    return CLIP_MODELS.get(fal_model, CLIP_MODELS["hailuo"])


def max_duration(durations: Optional[Tuple[float, ...]]) -> float:
    return math.inf if durations is None else max(durations)


def snap_duration(needed: float, durations: Optional[Tuple[float, ...]]) -> Optional[float]:
    """Smallest supported length >= needed; None when even the longest is too short."""
    if durations is None:
        return round(needed, 2)
    for d in sorted(durations):
        if d + 1e-6 >= needed:
            return d
    return None


class MotionGenerator:
    """Generates motion clips from static images."""

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = Path(temp_dir or "assets/temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def generate_motion_clip(
        self, image_path: str, motion_prompt: str, index: int = 0
    ) -> Optional[str]:
        """Generate a motion clip from a static image.
        Returns path to clip, or None on failure (caller uses Ken Burns fallback).
        """
        provider = settings.motion_provider

        try:
            if provider == "fal":
                return self._generate_fal(image_path, motion_prompt, index)
            elif provider == "replicate":
                return self._generate_replicate(image_path, motion_prompt, index)
            elif provider == "local":
                return self._generate_local(image_path, motion_prompt, index)
            else:
                # Default: try fal first, fall back to replicate
                return self._generate_fal(image_path, motion_prompt, index)

        except Exception as e:
            logger.warning(f"Motion clip {index} generation failed (non-fatal): {e}")
            return None

    def generate_clip(self, image_path: str, prompt: str, output_path: str,
                      duration: Optional[float] = None, model_key: Optional[str] = None) -> Optional[str]:
        """One generation attempt for the shot editor. Returns output_path, or None on any failure
        (missing fal_client, HTTP error, quota...). Retries/fallbacks live in app.cin.clip_sourcing."""
        provider = settings.motion_provider
        try:
            if provider == "replicate":
                return self._generate_replicate(image_path, prompt, 0, output_path=output_path)
            if provider == "local":
                return self._generate_local(image_path, prompt, 0, output_path=output_path, duration=duration)
            return self._generate_fal(image_path, prompt, 0, output_path=output_path,
                                      duration=duration, model_key=model_key)
        except Exception as e:  # noqa: BLE001
            logger.warning("Motion clip %s failed: %s", Path(output_path).name, e)
            return None

    def _generate_fal(self, image_path: str, motion_prompt: str, index: int,
                      output_path: Optional[str] = None, duration: Optional[float] = None,
                      model_key: Optional[str] = None) -> Optional[str]:
        """Generate motion clip using fal.ai (Minimax Hailuo default)."""
        if model_key is not None:
            requested = CLIP_MODELS.get(model_key)
            if requested is None or requested.endpoint is None:
                logger.error("Unknown or non-fal clip model %r; refusing to substitute another model", model_key)
                return None

        import fal_client

        # Set API key from config or env
        fal_key = settings.fal_api_key
        if fal_key:
            os.environ['FAL_KEY'] = fal_key

        model = CLIP_MODELS.get(model_key or settings.fal_video_model, CLIP_MODELS["hailuo"])
        if model.endpoint is None:
            model = CLIP_MODELS["hailuo"]
        endpoint = model.endpoint

        logger.info(f"Generating motion clip {index} via fal.ai ({model.key}): {motion_prompt[:50]}...")

        # Upload image to fal
        image_url = fal_client.upload_file(image_path)

        # Build arguments
        args = {
            "prompt": motion_prompt,
            "image_url": image_url,
        }

        # Kling takes a length ("5"/"10") and an aspect ratio; Minimax/hailuo takes neither
        if model.sends_duration:
            length = snap_duration(duration or min(model.durations), model.durations) or max(model.durations)
            args["duration"] = str(int(length))
            args["aspect_ratio"] = "9:16"

        def on_queue_update(update):
            if isinstance(update, fal_client.InProgress):
                logger.info(f"  Motion clip {index}: generating...")

        result = fal_client.subscribe(
            endpoint, arguments=args,
            with_logs=True,
            on_queue_update=on_queue_update,
        )

        # Extract video URL
        video_url = result["video"]["url"]

        # Download video
        output_path = Path(output_path) if output_path else self.temp_dir / f"motion_{index:03d}.mp4"
        response = requests.get(video_url, timeout=120)
        if response.status_code != 200:
            logger.warning(f"Motion clip {index}: download failed ({response.status_code})")
            return None

        with open(output_path, "wb") as f:
            f.write(response.content)

        logger.info(f"Motion clip {index} saved: {output_path} ({len(response.content) // 1024}KB)")
        return str(output_path)

    def _generate_replicate(self, image_path: str, motion_prompt: str, index: int,
                            output_path: Optional[str] = None) -> Optional[str]:
        """Generate motion clip using Replicate API (legacy)."""
        from app.replicate_api import replicate_run

        logger.info(f"Generating motion clip {index} via Replicate: {motion_prompt[:50]}...")

        output = replicate_run(
            settings.minimax_model,
            {"first_frame_image": image_path, "prompt": motion_prompt},
            timeout=600,
        )

        video_url = output if isinstance(output, str) else str(output)
        output_path = Path(output_path) if output_path else self.temp_dir / f"motion_{index:03d}.mp4"
        response = requests.get(video_url, stream=True, timeout=120)

        if response.status_code != 200:
            return None

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Motion clip {index} saved: {output_path}")
        return str(output_path)

    def _generate_local(self, image_path: str, motion_prompt: str, index: int,
                        output_path: Optional[str] = None, duration: Optional[float] = None) -> Optional[str]:
        """Generate motion clip using local enhanced motion effects."""
        from app.local_video_gen import LocalVideoGenerator

        output_path = str(output_path or self.temp_dir / f"motion_{index:03d}.mp4")
        gen = LocalVideoGenerator()
        gen.generate(image_path, motion_prompt, output_path, duration=duration or 5.0)
        logger.info("Local motion clip %d saved: %s", index, output_path)
        return output_path

    def generate_all_clips(
        self, image_paths: List[str], motion_prompts: List[str]
    ) -> List[Optional[str]]:
        """Generate motion clips for all images sequentially."""
        if len(image_paths) != len(motion_prompts):
            raise ValueError("image_paths and motion_prompts must have same length")

        results: List[Optional[str]] = [None] * len(image_paths)

        for i, (img, prompt) in enumerate(zip(image_paths, motion_prompts)):
            logger.info(f"Motion clip {i + 1}/{len(image_paths)}")
            results[i] = self.generate_motion_clip(img, prompt, index=i)

        success = sum(1 for r in results if r is not None)
        logger.info(f"Motion clips: {success}/{len(results)} generated successfully")
        return results
