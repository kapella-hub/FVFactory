"""Local image generation using FLUX via Hugging Face diffusers."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import torch
    from diffusers import FluxPipeline
    HAS_DIFFUSERS = True
except ImportError:
    HAS_DIFFUSERS = False
    FluxPipeline = None


class LocalImageGenerator:
    """Generates images locally using FLUX model via diffusers."""

    def __init__(self, model_id: str = "black-forest-labs/FLUX.1-schnell"):
        if not HAS_DIFFUSERS:
            raise RuntimeError(
                "diffusers package not installed. "
                "Run: pip install diffusers transformers accelerate safetensors torch"
            )
        self.model_id = model_id
        self.device = self._get_device()
        logger.info("Loading FLUX model %s on %s...", model_id, self.device)
        self.pipe = FluxPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if self.device != "cpu" else torch.float32,
        )
        if self.device == "mps":
            self.pipe = self.pipe.to("mps")
            self.pipe.enable_attention_slicing()
        elif self.device == "cuda":
            self.pipe = self.pipe.to("cuda")
        logger.info("FLUX model loaded.")

    @staticmethod
    def _get_device() -> str:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    @staticmethod
    def _snap_to_16(value: int) -> int:
        """Round down to nearest multiple of 16 (required by FLUX)."""
        return (value // 16) * 16

    def generate(self, prompt: str, width: int, height: int,
                 output_path: str) -> str:
        """Generate a single image. Generates at reduced resolution then upscales."""
        import torch
        from PIL import Image

        # Generate at ~half resolution for speed, then upscale
        # 768x1344 is 9:16, divisible by 16, ~4x faster than 1080x1920
        gen_w = min(self._snap_to_16(width), 768)
        gen_h = self._snap_to_16(int(gen_w * (height / width)))

        logger.info("Generating image (%dx%d -> %dx%d): %s", gen_w, gen_h, width, height, prompt[:80])
        result = self.pipe(
            prompt=prompt,
            width=gen_w,
            height=gen_h,
            num_inference_steps=4,
            guidance_scale=0.0,
        )
        img = result.images[0]
        # Upscale to target resolution
        if gen_w != width or gen_h != height:
            img = img.resize((width, height), Image.LANCZOS)
        img.save(output_path)
        if self.device == "mps":
            torch.mps.empty_cache()
        logger.info("Image saved: %s", output_path)
        return output_path

    def generate_batch(self, prompts: list[str], width: int, height: int,
                       output_dir: str) -> list[str]:
        """Generate multiple images sequentially."""
        os.makedirs(output_dir, exist_ok=True)
        results = []
        for i, prompt in enumerate(prompts):
            path = os.path.join(output_dir, f"scene_{i:03d}.png")
            self.generate(prompt, width, height, path)
            results.append(path)
        return results

    def unload(self):
        """Free model from memory."""
        import torch
        del self.pipe
        self.pipe = None
        if self.device == "mps":
            torch.mps.empty_cache()
        elif self.device == "cuda":
            torch.cuda.empty_cache()
        logger.info("FLUX model unloaded.")
