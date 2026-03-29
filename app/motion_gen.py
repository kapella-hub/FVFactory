"""Motion Generator - Local Wan I2V or Replicate Minimax"""

import logging
from pathlib import Path
from typing import List, Optional

import requests

from app.config import settings
from app.replicate_api import replicate_run

logger = logging.getLogger(__name__)


class MotionGenerator:
    """Generates motion clips from static images."""

    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = Path(temp_dir or "assets/temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._local_gen = None

    def _is_local(self) -> bool:
        return settings.motion_provider == "local" or (
            settings.provider_mode == "local" and settings.motion_provider != "replicate"
        )

    def _get_local_gen(self):
        """Lazy-load local video generator — load once, reuse for all clips."""
        if self._local_gen is None:
            from app.local_video_gen import LocalVideoGenerator
            self._local_gen = LocalVideoGenerator(model_size=settings.wan_model_size)
        return self._local_gen

    def _unload_local_gen(self):
        if self._local_gen is not None:
            self._local_gen.unload()
            self._local_gen = None

    def generate_motion_clip(
        self, image_path: str, motion_prompt: str, index: int = 0
    ) -> Optional[str]:
        """
        Generate a 5s motion clip from a static image.
        Returns path to clip, or None on failure (caller uses Ken Burns fallback).
        """
        try:
            if self._is_local():
                return self._generate_local(image_path, motion_prompt, index)

            logger.info(f"Generating motion clip {index}: {motion_prompt[:50]}...")

            output = replicate_run(
                settings.minimax_model,
                {
                    "first_frame_image": image_path,
                    "prompt": motion_prompt,
                },
                timeout=600,
            )

            video_url = output if isinstance(output, str) else str(output)

            output_path = self.temp_dir / f"motion_{index}.mp4"
            response = requests.get(video_url, stream=True, timeout=120)

            if response.status_code != 200:
                logger.warning(f"Motion clip {index}: download failed ({response.status_code})")
                return None

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            logger.info(f"Motion clip {index} saved: {output_path}")
            return str(output_path)

        except Exception as e:
            logger.warning(f"Motion clip {index} generation failed (non-fatal): {e}")
            return None

    def _generate_local(self, image_path: str, motion_prompt: str, index: int) -> str | None:
        """Generate motion clip using local Wan model (reuses loaded model)."""
        output_path = str(self.temp_dir / f"motion_{index:03d}.mp4")
        try:
            gen = self._get_local_gen()
            gen.generate(image_path, motion_prompt, output_path)
            logger.info("Local motion clip %d saved: %s", index, output_path)
            return output_path
        except Exception as e:
            logger.warning("Local video gen failed for scene %d: %s", index, e)
            return None

    def generate_all_clips(
        self, image_paths: List[str], motion_prompts: List[str]
    ) -> List[Optional[str]]:
        """Generate motion clips for all images sequentially.

        Uses sequential generation (not parallel) for local models to avoid
        memory contention on Apple Silicon.
        """
        if len(image_paths) != len(motion_prompts):
            raise ValueError("image_paths and motion_prompts must have same length")

        results: List[Optional[str]] = [None] * len(image_paths)

        try:
            for i, (img, prompt) in enumerate(zip(image_paths, motion_prompts)):
                logger.info(f"Motion clip {i+1}/{len(image_paths)}")
                results[i] = self.generate_motion_clip(img, prompt, index=i)
        finally:
            # Always unload model after batch to free memory for video assembly
            self._unload_local_gen()

        success = sum(1 for r in results if r is not None)
        logger.info(f"Motion clips: {success}/{len(results)} generated successfully")
        return results
