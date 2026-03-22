"""
Replicate HTTP API wrapper - bypasses the replicate SDK which is broken on Python 3.14.
Calls the Replicate API directly via requests.
"""

import base64
import logging
import time
from pathlib import Path
from typing import Any, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

REPLICATE_API_BASE = "https://api.replicate.com/v1"


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.replicate_api_token}",
        "Content-Type": "application/json",
    }


def replicate_run(model: str, input_data: dict, timeout: int = 300) -> Any:
    """
    Run a Replicate model and return the output.

    Args:
        model: Model identifier (e.g., "black-forest-labs/flux-1.1-pro")
        input_data: Input parameters for the model. File paths are auto-converted to data URIs.
        timeout: Max seconds to wait for completion

    Returns:
        The model output (usually a URL string or list of URLs)
    """
    if not settings.replicate_api_token:
        raise RuntimeError("REPLICATE_API_TOKEN not configured")

    # Convert any file paths in input to data URIs
    processed_input = {}
    for key, value in input_data.items():
        if isinstance(value, str) and Path(value).exists():
            processed_input[key] = _file_to_url(value)
        else:
            processed_input[key] = value

    # Create prediction
    url = f"{REPLICATE_API_BASE}/models/{model}/predictions"
    payload = {"input": processed_input}

    logger.debug(f"Replicate: creating prediction for {model}")

    # Retry on 429 rate limits
    max_retries = 5
    for attempt in range(max_retries):
        response = requests.post(url, json=payload, headers=_get_headers(), timeout=120)

        if response.status_code in (200, 201):
            prediction = response.json()
            break
        elif response.status_code == 429:
            retry_after = int(response.json().get("retry_after", 10))
            logger.warning(f"Replicate rate limited, retrying in {retry_after}s (attempt {attempt+1}/{max_retries})")
            time.sleep(retry_after + 1)
        else:
            raise RuntimeError(f"Replicate API error {response.status_code}: {response.text}")
    else:
        raise RuntimeError("Replicate rate limit: max retries exceeded")

    # If we got a completed result immediately (sync mode)
    status = prediction.get("status")
    if status == "succeeded":
        return _extract_output(prediction)

    # Otherwise poll for completion
    prediction_url = prediction.get("urls", {}).get("get") or f"{REPLICATE_API_BASE}/predictions/{prediction['id']}"

    poll_headers = _get_headers()
    poll_headers.pop("Prefer", None)  # Don't use wait mode for polling

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(3)
        poll_response = requests.get(prediction_url, headers=poll_headers, timeout=30)

        if poll_response.status_code != 200:
            raise RuntimeError(f"Replicate poll error {poll_response.status_code}: {poll_response.text}")

        prediction = poll_response.json()
        status = prediction.get("status")

        if status == "succeeded":
            return _extract_output(prediction)
        elif status in ("failed", "canceled"):
            error = prediction.get("error", "Unknown error")
            raise RuntimeError(f"Replicate prediction failed: {error}")

        logger.debug(f"Replicate: status={status}, elapsed={time.time()-start:.0f}s")

    raise RuntimeError(f"Replicate prediction timed out after {timeout}s")


def _extract_output(prediction: dict) -> Any:
    """Extract the output from a completed prediction."""
    output = prediction.get("output")
    if isinstance(output, list) and len(output) == 1:
        return output[0]
    return output


def _file_to_url(file_path: str) -> str:
    """Upload a local file to Replicate's file API and return a URL."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".mp4": "video/mp4",
    }
    mime = mime_types.get(suffix, "application/octet-stream")

    # Use Replicate's file upload API
    upload_url = f"{REPLICATE_API_BASE}/files"
    headers = {
        "Authorization": f"Bearer {settings.replicate_api_token}",
    }

    with open(path, "rb") as f:
        response = requests.post(
            upload_url,
            headers=headers,
            files={"content": (path.name, f, mime)},
            timeout=60,
        )

    if response.status_code in (200, 201):
        data = response.json()
        url = data.get("urls", {}).get("get", data.get("url", ""))
        logger.debug(f"Uploaded {path.name} -> {url[:80]}")
        return url
    else:
        # Fall back to data URI for small files
        logger.warning(f"File upload failed ({response.status_code}), using data URI")
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{encoded}"
