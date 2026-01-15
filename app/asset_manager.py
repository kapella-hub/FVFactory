"""
Asset Manager - Audio and image generation for video creation
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests
from openai import OpenAI
from moviepy import AudioFileClip

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AudioResult:
    """Result of audio generation"""
    file_path: str
    duration: float  # Duration in seconds


class AssetManagerError(Exception):
    """Base exception for asset management errors"""
    pass


class AssetManager:
    """Manages generation of audio and image assets"""

    TEMP_DIR = Path("assets/temp")

    # ElevenLabs settings
    ELEVENLABS_API_URL = "https://api.elevenlabs.io/v1/text-to-speech"
    DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel voice

    # Image settings for 9:16 vertical video
    IMAGE_WIDTH = 1080
    IMAGE_HEIGHT = 1920

    def __init__(self):
        self.openai_client = None
        if settings.openai_api_key:
            self.openai_client = OpenAI(api_key=settings.openai_api_key)

        # Ensure temp directory exists
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)

    def _enhance_prompt_with_style(self, prompt: str) -> str:
        """
        Enhance an image prompt with consistent style keywords.
        Prevents style drift between scenes.
        """
        # Check if style keywords are already present (avoid duplication)
        style = settings.image_style
        if style and style.lower() not in prompt.lower():
            return f"{prompt}, {style}"
        return prompt

    def generate_audio(
        self,
        text: str,
        voice_id: Optional[str] = None
    ) -> AudioResult:
        """
        Generate audio from text using ElevenLabs or OpenAI TTS fallback.

        Args:
            text: The text to convert to speech
            voice_id: ElevenLabs voice ID (optional)

        Returns:
            AudioResult: Contains file_path and duration in seconds

        Raises:
            AssetManagerError: If audio generation fails
        """
        if not text or not text.strip():
            raise AssetManagerError("Text cannot be empty")

        output_path = self.TEMP_DIR / "audio.mp3"

        # Try ElevenLabs first
        if settings.elevenlabs_api_key:
            try:
                return self._generate_audio_elevenlabs(
                    text, voice_id or self.DEFAULT_VOICE_ID, output_path
                )
            except Exception as e:
                logger.warning(f"ElevenLabs failed, falling back to OpenAI TTS: {e}")

        # Fallback to OpenAI TTS
        if self.openai_client:
            return self._generate_audio_openai(text, output_path)

        raise AssetManagerError(
            "No TTS service available. Configure ELEVENLABS_API_KEY or OPENAI_API_KEY"
        )

    def _generate_audio_elevenlabs(
        self,
        text: str,
        voice_id: str,
        output_path: Path
    ) -> AudioResult:
        """Generate audio using ElevenLabs API"""
        url = f"{self.ELEVENLABS_API_URL}/{voice_id}"

        headers = {
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json"
        }

        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            raise AssetManagerError(
                f"ElevenLabs API error: {response.status_code} - {response.text}"
            )

        with open(output_path, "wb") as f:
            f.write(response.content)

        duration = self._get_audio_duration(output_path)

        return AudioResult(file_path=str(output_path), duration=duration)

    def _generate_audio_openai(self, text: str, output_path: Path) -> AudioResult:
        """Generate audio using OpenAI TTS API"""
        response = self.openai_client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text
        )

        response.stream_to_file(str(output_path))

        duration = self._get_audio_duration(output_path)

        return AudioResult(file_path=str(output_path), duration=duration)

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Get the duration of an audio file in seconds"""
        try:
            with AudioFileClip(str(audio_path)) as audio:
                return audio.duration
        except Exception as e:
            raise AssetManagerError(f"Failed to get audio duration: {e}")

    def generate_images(
        self,
        prompts: List[str],
        use_mock: bool = True
    ) -> List[str]:
        """
        Generate images from prompts with consistent styling.

        Args:
            prompts: List of image description prompts
            use_mock: If True, generate placeholder images. If False, use DALL-E 3.

        Returns:
            List of file paths to generated images

        Raises:
            AssetManagerError: If image generation fails
        """
        if not prompts:
            raise AssetManagerError("Prompts list cannot be empty")

        file_paths = []

        for i, prompt in enumerate(prompts):
            output_path = self.TEMP_DIR / f"image_{i}.png"

            # Enhance prompt with style keywords for consistency
            styled_prompt = self._enhance_prompt_with_style(prompt)
            logger.debug(f"Image {i+1} prompt: {styled_prompt[:100]}...")

            if use_mock:
                self._generate_mock_image(styled_prompt, output_path, i)
            else:
                self._generate_image_dalle(styled_prompt, output_path)

            file_paths.append(str(output_path))

        return file_paths

    def _generate_mock_image(
        self,
        prompt: str,
        output_path: Path,
        index: int
    ) -> None:
        """Generate a placeholder image with text overlay"""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            raise AssetManagerError(
                "Pillow is required for mock images. Install with: pip install Pillow"
            )

        # Create a gradient background for visual variety
        colors = [
            (41, 128, 185),   # Blue
            (142, 68, 173),   # Purple
            (39, 174, 96),    # Green
            (231, 76, 60),    # Red
            (243, 156, 18),   # Orange
        ]
        bg_color = colors[index % len(colors)]

        img = Image.new("RGB", (self.IMAGE_WIDTH, self.IMAGE_HEIGHT), bg_color)
        draw = ImageDraw.Draw(img)

        # Add mascot indicator if enabled
        mascot_text = ""
        if settings.mascot_enabled:
            mascot_text = f"\n[MASCOT: {settings.mascot_prompt[:50]}...]"

        # Add prompt text (truncated)
        text = f"Scene {index + 1}{mascot_text}\n\n{prompt[:100]}..."

        # Use default font
        try:
            font = ImageFont.truetype("arial.ttf", 36)
        except OSError:
            font = ImageFont.load_default()

        # Center text
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (self.IMAGE_WIDTH - text_width) // 2
        y = (self.IMAGE_HEIGHT - text_height) // 2

        draw.text((x, y), text, fill="white", font=font)

        img.save(output_path, "PNG")

    def _generate_image_dalle(self, prompt: str, output_path: Path) -> None:
        """Generate image using OpenAI DALL-E 3 with style consistency"""
        if not self.openai_client:
            raise AssetManagerError("OpenAI API key not configured for DALL-E")

        # Build enhanced prompt for vertical video format
        # Style keywords are already added by _enhance_prompt_with_style
        enhanced_prompt = (
            f"{prompt}. "
            "Vertical composition suitable for TikTok/Shorts (9:16 aspect ratio). "
            "High quality, consistent lighting."
        )

        logger.info(f"DALL-E prompt: {enhanced_prompt[:100]}...")

        response = self.openai_client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            size="1024x1792",  # Closest to 9:16 available in DALL-E 3
            quality="standard",
            n=1
        )

        image_url = response.data[0].url

        # Download and save the image
        img_response = requests.get(image_url)
        if img_response.status_code != 200:
            raise AssetManagerError("Failed to download DALL-E image")

        with open(output_path, "wb") as f:
            f.write(img_response.content)

    def cleanup_temp(self) -> None:
        """Remove all temporary files"""
        for file in self.TEMP_DIR.iterdir():
            if file.name != ".gitkeep":
                file.unlink()
