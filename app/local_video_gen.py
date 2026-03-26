"""Local video generation using Wan2.1 I2V via Hugging Face diffusers."""

import logging
import os

logger = logging.getLogger(__name__)

try:
    import torch
    from diffusers import WanImageToVideoPipeline
    from diffusers.utils import export_to_video, load_image
    HAS_DIFFUSERS = True
except ImportError:
    HAS_DIFFUSERS = False
    WanImageToVideoPipeline = None
    export_to_video = None
    load_image = None

WAN_MODELS = {
    "1.3b": "Wan-AI/Wan2.1-I2V-1.3B-480P-Diffusers",
    "14b": "Wan-AI/Wan2.1-I2V-14B-720P-Diffusers",
}


class LocalVideoGenerator:
    """Generates motion video clips locally using Wan2.1 I2V."""

    def __init__(self, model_size: str = "1.3b"):
        if not HAS_DIFFUSERS:
            raise RuntimeError(
                "diffusers package not installed. "
                "Run: pip install diffusers transformers accelerate safetensors torch"
            )
        if model_size not in WAN_MODELS:
            raise ValueError(f"Unknown Wan model size: {model_size}. Use '1.3b' or '14b'.")

        self.model_id = WAN_MODELS[model_size]
        self.model_size = model_size
        self.device = self._get_device()

        logger.info("Loading Wan2.1 %s model on %s...", model_size, self.device)

        dtype = torch.float16 if self.device != "cpu" else torch.float32
        self.pipe = WanImageToVideoPipeline.from_pretrained(
            self.model_id, torch_dtype=dtype,
        )

        if self.device == "mps":
            self.pipe = self.pipe.to("mps")
            self.pipe.enable_attention_slicing()
        elif self.device == "cuda":
            self.pipe.enable_model_cpu_offload()
        else:
            self.pipe = self.pipe.to("cpu")

        logger.info("Wan2.1 model loaded.")

    @staticmethod
    def _get_device() -> str:
        import torch
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def generate(self, image_path: str, prompt: str,
                 output_path: str, duration: float = 5.0) -> str:
        """Generate a motion video clip from a static image."""
        import torch

        logger.info("Generating motion clip: %s", prompt[:80])
        image = load_image(image_path)

        if self.model_size == "14b":
            image = image.resize((720, 1280))
        else:
            image = image.resize((480, 854))

        num_frames = int(duration * 16)
        num_frames = min(max(num_frames, 16), 81)

        output = self.pipe(
            image=image, prompt=prompt,
            num_frames=num_frames, guidance_scale=5.0,
            num_inference_steps=30,
        )

        export_to_video(output.frames[0], output_path, fps=16)

        if self.device == "mps":
            torch.mps.empty_cache()

        logger.info("Motion clip saved: %s", output_path)
        return output_path

    def unload(self):
        """Free model from memory."""
        import torch
        del self.pipe
        self.pipe = None
        if self.device == "mps":
            torch.mps.empty_cache()
        elif self.device == "cuda":
            torch.cuda.empty_cache()
        logger.info("Wan2.1 model unloaded.")
