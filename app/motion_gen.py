"""Motion Generator — fal.ai Minimax Hailuo (default), Replicate, or local fallback."""

import logging
import os
from pathlib import Path
from typing import List, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

# fal.ai model endpoints
FAL_MODELS = {
    "hailuo": "fal-ai/minimax-video/image-to-video",
    "kling": "fal-ai/kling-video/v1/standard/image-to-video",
    "kling-pro": "fal-ai/kling-video/v1.5/pro/image-to-video",
}


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

    def _generate_fal(self, image_path: str, motion_prompt: str, index: int) -> Optional[str]:
        """Generate motion clip using fal.ai (Minimax Hailuo default)."""
        import fal_client

        # Set API key from config or env
        fal_key = settings.fal_api_key
        if fal_key:
            os.environ['FAL_KEY'] = fal_key

        model = settings.fal_video_model
        endpoint = FAL_MODELS.get(model, FAL_MODELS["hailuo"])

        logger.info(f"Generating motion clip {index} via fal.ai ({model}): {motion_prompt[:50]}...")

        # Upload image to fal
        image_url = fal_client.upload_file(image_path)

        # Build arguments
        args = {
            "prompt": motion_prompt,
            "image_url": image_url,
        }

        # Kling supports extra params
        if "kling" in model:
            args["duration"] = "5"
            args["aspect_ratio"] = "9:16"

        result = fal_client.subscribe(endpoint, arguments=args)

        # Extract video URL
        video_url = result["video"]["url"]

        # Download video
        output_path = self.temp_dir / f"motion_{index:03d}.mp4"
        response = requests.get(video_url, timeout=120)
        if response.status_code != 200:
            logger.warning(f"Motion clip {index}: download failed ({response.status_code})")
            return None

        with open(output_path, "wb") as f:
            f.write(response.content)

        logger.info(f"Motion clip {index} saved: {output_path} ({len(response.content) // 1024}KB)")
        return str(output_path)

    def _generate_replicate(self, image_path: str, motion_prompt: str, index: int) -> Optional[str]:
        """Generate motion clip using Replicate API (legacy)."""
        from app.replicate_api import replicate_run

        logger.info(f"Generating motion clip {index} via Replicate: {motion_prompt[:50]}...")

        output = replicate_run(
            settings.minimax_model,
            {"first_frame_image": image_path, "prompt": motion_prompt},
            timeout=600,
        )

        video_url = output if isinstance(output, str) else str(output)
        output_path = self.temp_dir / f"motion_{index:03d}.mp4"
        response = requests.get(video_url, stream=True, timeout=120)

        if response.status_code != 200:
            return None

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Motion clip {index} saved: {output_path}")
        return str(output_path)

    def _generate_local(self, image_path: str, motion_prompt: str, index: int) -> Optional[str]:
        """Generate motion clip using local enhanced motion effects."""
        from app.local_video_gen import LocalVideoGenerator

        output_path = str(self.temp_dir / f"motion_{index:03d}.mp4")
        gen = LocalVideoGenerator()
        gen.generate(image_path, motion_prompt, output_path)
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
