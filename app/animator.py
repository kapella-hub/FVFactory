"""
Animator - Audio-driven portrait animation using Hedra or Replicate LivePortrait
"""

import logging
import time
from pathlib import Path
from typing import Optional, List
import base64

import requests

from app.config import settings

logger = logging.getLogger(__name__)


class AnimatorError(Exception):
    """Base exception for animator errors"""
    pass


class PortraitAnimator:
    """
    Animates portrait images with audio using AI services.

    Supports:
    - Hedra API (primary)
    - Replicate LivePortrait model (fallback)
    """

    TEMP_DIR = Path("assets/temp")

    # Hedra API endpoints
    HEDRA_API_BASE = "https://api.hedra.com/v1"
    HEDRA_UPLOAD_URL = f"{HEDRA_API_BASE}/audio"
    HEDRA_GENERATE_URL = f"{HEDRA_API_BASE}/characters"
    HEDRA_PROJECT_URL = f"{HEDRA_API_BASE}/projects"

    # Replicate API
    REPLICATE_API_BASE = "https://api.replicate.com/v1"
    REPLICATE_MODEL = "fofr/live-portrait"
    REPLICATE_VERSION = "latest"

    # Polling settings
    MAX_POLL_ATTEMPTS = 120  # 10 minutes at 5 second intervals
    POLL_INTERVAL = 5  # seconds

    def __init__(self):
        self.personas_dir = Path(settings.personas_dir)
        self.personas_dir.mkdir(parents=True, exist_ok=True)
        self.TEMP_DIR.mkdir(parents=True, exist_ok=True)

    def get_available_personas(self) -> List[str]:
        """
        Get list of available persona images.

        Returns:
            List of persona image filenames
        """
        if not self.personas_dir.exists():
            return []

        image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
        personas = [
            f.name for f in self.personas_dir.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        ]
        return sorted(personas)

    def get_persona_path(self, persona_name: str) -> Optional[Path]:
        """
        Get the full path to a persona image.

        Args:
            persona_name: Name of the persona file

        Returns:
            Path to the persona image, or None if not found
        """
        persona_path = self.personas_dir / persona_name
        if persona_path.exists():
            return persona_path
        return None

    def animate_portrait(
        self,
        audio_path: str,
        persona_image_path: str,
        output_filename: Optional[str] = None
    ) -> str:
        """
        Animate a portrait image with audio using AI services.

        Args:
            audio_path: Path to the audio file (narration)
            persona_image_path: Path to the persona master image
            output_filename: Optional output filename

        Returns:
            str: Path to the generated animated video

        Raises:
            AnimatorError: If animation fails
        """
        if not Path(audio_path).exists():
            raise AnimatorError(f"Audio file not found: {audio_path}")

        if not Path(persona_image_path).exists():
            raise AnimatorError(f"Persona image not found: {persona_image_path}")

        # Try Hedra first, then Replicate
        if settings.hedra_api_key:
            try:
                return self._animate_with_hedra(
                    audio_path, persona_image_path, output_filename
                )
            except Exception as e:
                logger.warning(f"Hedra failed, trying Replicate: {e}")

        if settings.replicate_api_token:
            return self._animate_with_replicate(
                audio_path, persona_image_path, output_filename
            )

        raise AnimatorError(
            "No animation API configured. Set HEDRA_API_KEY or REPLICATE_API_TOKEN"
        )

    def _animate_with_hedra(
        self,
        audio_path: str,
        image_path: str,
        output_filename: Optional[str] = None
    ) -> str:
        """
        Animate portrait using Hedra API.

        Hedra workflow:
        1. Upload audio to get audio URL
        2. Upload image to get avatar URL
        3. Create character generation project
        4. Poll for completion
        5. Download result
        """
        headers = {
            "X-API-Key": settings.hedra_api_key,
        }

        # Step 1: Upload audio
        logger.info("Uploading audio to Hedra...")
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        audio_response = requests.post(
            self.HEDRA_UPLOAD_URL,
            headers=headers,
            files={"file": ("audio.mp3", audio_data, "audio/mpeg")}
        )

        if audio_response.status_code != 200:
            raise AnimatorError(f"Hedra audio upload failed: {audio_response.text}")

        audio_url = audio_response.json().get("url")
        if not audio_url:
            raise AnimatorError("Hedra did not return audio URL")

        # Step 2: Upload image (as avatar)
        logger.info("Uploading persona image to Hedra...")
        with open(image_path, "rb") as f:
            image_data = f.read()

        image_ext = Path(image_path).suffix.lower()
        mime_type = "image/png" if image_ext == ".png" else "image/jpeg"

        avatar_response = requests.post(
            f"{self.HEDRA_API_BASE}/portrait",
            headers=headers,
            files={"file": (f"avatar{image_ext}", image_data, mime_type)}
        )

        if avatar_response.status_code != 200:
            raise AnimatorError(f"Hedra image upload failed: {avatar_response.text}")

        avatar_url = avatar_response.json().get("url")
        if not avatar_url:
            raise AnimatorError("Hedra did not return avatar URL")

        # Step 3: Create generation project
        logger.info("Starting Hedra generation...")
        generation_payload = {
            "avatarImage": avatar_url,
            "audioSource": "audio",
            "voiceUrl": audio_url,
            "aspectRatio": "9:16",  # Vertical for shorts
        }

        gen_response = requests.post(
            self.HEDRA_GENERATE_URL,
            headers={**headers, "Content-Type": "application/json"},
            json=generation_payload
        )

        if gen_response.status_code not in [200, 201]:
            raise AnimatorError(f"Hedra generation failed: {gen_response.text}")

        project_id = gen_response.json().get("jobId") or gen_response.json().get("projectId")
        if not project_id:
            raise AnimatorError("Hedra did not return project ID")

        # Step 4: Poll for completion
        logger.info(f"Waiting for Hedra generation (project: {project_id})...")
        video_url = self._poll_hedra_status(project_id, headers)

        # Step 5: Download result
        output_path = self._download_video(video_url, output_filename, "hedra")
        logger.info(f"Hedra animation complete: {output_path}")

        return output_path

    def _poll_hedra_status(self, project_id: str, headers: dict) -> str:
        """Poll Hedra for project completion."""
        for attempt in range(self.MAX_POLL_ATTEMPTS):
            response = requests.get(
                f"{self.HEDRA_PROJECT_URL}/{project_id}",
                headers=headers
            )

            if response.status_code != 200:
                raise AnimatorError(f"Hedra status check failed: {response.text}")

            data = response.json()
            status = data.get("status", "").lower()

            if status == "completed" or status == "complete":
                video_url = data.get("videoUrl") or data.get("video_url")
                if video_url:
                    return video_url
                raise AnimatorError("Hedra completed but no video URL returned")

            if status in ["failed", "error"]:
                error_msg = data.get("error", "Unknown error")
                raise AnimatorError(f"Hedra generation failed: {error_msg}")

            logger.info(f"Hedra status: {status} (attempt {attempt + 1}/{self.MAX_POLL_ATTEMPTS})")
            time.sleep(self.POLL_INTERVAL)

        raise AnimatorError("Hedra generation timed out")

    def _animate_with_replicate(
        self,
        audio_path: str,
        image_path: str,
        output_filename: Optional[str] = None
    ) -> str:
        """
        Animate portrait using Replicate LivePortrait model.

        Uses fofr/live-portrait model on Replicate.
        """
        headers = {
            "Authorization": f"Token {settings.replicate_api_token}",
            "Content-Type": "application/json",
        }

        # Read and encode files as base64 data URIs
        logger.info("Preparing files for Replicate...")

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        image_ext = Path(image_path).suffix.lower()
        image_mime = "image/png" if image_ext == ".png" else "image/jpeg"
        image_uri = f"data:{image_mime};base64,{image_data}"

        with open(audio_path, "rb") as f:
            audio_data = base64.b64encode(f.read()).decode("utf-8")
        audio_uri = f"data:audio/mpeg;base64,{audio_data}"

        # Create prediction
        logger.info("Starting Replicate LivePortrait generation...")
        prediction_payload = {
            "version": self.REPLICATE_VERSION,
            "input": {
                "face_image": image_uri,
                "driving_audio": audio_uri,
                "live_portrait_dsize": 512,
                "live_portrait_scale": 2.3,
                "video_frame_load_cap": 128,
                "flag_pasteback": True,
                "flag_do_crop": True,
                "flag_do_rot": True,
            }
        }

        # Get the model version first
        model_response = requests.get(
            f"{self.REPLICATE_API_BASE}/models/{self.REPLICATE_MODEL}",
            headers=headers
        )

        if model_response.status_code == 200:
            model_data = model_response.json()
            latest_version = model_data.get("latest_version", {}).get("id")
            if latest_version:
                prediction_payload["version"] = latest_version

        create_response = requests.post(
            f"{self.REPLICATE_API_BASE}/predictions",
            headers=headers,
            json=prediction_payload
        )

        if create_response.status_code not in [200, 201]:
            raise AnimatorError(f"Replicate prediction failed: {create_response.text}")

        prediction_data = create_response.json()
        prediction_id = prediction_data.get("id")
        if not prediction_id:
            raise AnimatorError("Replicate did not return prediction ID")

        # Poll for completion
        logger.info(f"Waiting for Replicate generation (prediction: {prediction_id})...")
        video_url = self._poll_replicate_status(prediction_id, headers)

        # Download result
        output_path = self._download_video(video_url, output_filename, "replicate")
        logger.info(f"Replicate animation complete: {output_path}")

        return output_path

    def _poll_replicate_status(self, prediction_id: str, headers: dict) -> str:
        """Poll Replicate for prediction completion."""
        for attempt in range(self.MAX_POLL_ATTEMPTS):
            response = requests.get(
                f"{self.REPLICATE_API_BASE}/predictions/{prediction_id}",
                headers=headers
            )

            if response.status_code != 200:
                raise AnimatorError(f"Replicate status check failed: {response.text}")

            data = response.json()
            status = data.get("status", "").lower()

            if status == "succeeded":
                output = data.get("output")
                if isinstance(output, str):
                    return output
                elif isinstance(output, list) and output:
                    return output[0]
                raise AnimatorError("Replicate completed but no output returned")

            if status == "failed":
                error_msg = data.get("error", "Unknown error")
                raise AnimatorError(f"Replicate prediction failed: {error_msg}")

            if status == "canceled":
                raise AnimatorError("Replicate prediction was canceled")

            logger.info(f"Replicate status: {status} (attempt {attempt + 1}/{self.MAX_POLL_ATTEMPTS})")
            time.sleep(self.POLL_INTERVAL)

        raise AnimatorError("Replicate generation timed out")

    def _download_video(
        self,
        video_url: str,
        output_filename: Optional[str],
        source: str
    ) -> str:
        """Download the generated video."""
        logger.info(f"Downloading animated video from {source}...")

        response = requests.get(video_url, stream=True)
        if response.status_code != 200:
            raise AnimatorError(f"Failed to download video: {response.status_code}")

        if output_filename:
            output_path = self.TEMP_DIR / output_filename
        else:
            output_path = self.TEMP_DIR / f"animated_{source}.mp4"

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return str(output_path)


def animate_portrait(
    audio_path: str,
    persona_image_path: str,
    output_filename: Optional[str] = None
) -> str:
    """
    Convenience function to animate a portrait.

    Args:
        audio_path: Path to the audio file
        persona_image_path: Path to the persona master image
        output_filename: Optional output filename

    Returns:
        str: Path to the animated video
    """
    animator = PortraitAnimator()
    return animator.animate_portrait(audio_path, persona_image_path, output_filename)
