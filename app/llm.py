"""
LLM wrapper - calls Claude CLI for all text generation needs.

Uses `claude -p` in print mode with Sonnet for cost efficiency.
Falls back to OpenAI API if claude CLI is not available.
"""

import json
import logging
import subprocess
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def generate(prompt: str, system: Optional[str] = None, temperature: float = 0.7,
             max_tokens: int = 1500, json_mode: bool = False) -> str:
    """Generate text using Claude CLI, falling back to OpenAI API.

    Args:
        prompt: The user prompt
        system: Optional system prompt (prepended to user prompt for CLI)
        temperature: Creativity level (not supported by CLI, used for API fallback)
        max_tokens: Max output tokens (used for API fallback)
        json_mode: If True, instruct the model to return valid JSON

    Returns:
        The generated text response
    """
    # Try Claude CLI first
    result = _call_claude_cli(prompt, system, json_mode)
    if result is not None:
        return result

    # Fallback to OpenAI API
    return _call_openai_api(prompt, system, temperature, max_tokens, json_mode)


def generate_json(prompt: str, system: Optional[str] = None, temperature: float = 0.7,
                  max_tokens: int = 1500) -> dict:
    """Generate and parse a JSON response.

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If response is not valid JSON
    """
    raw = generate(prompt, system, temperature, max_tokens, json_mode=True)

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json) and last line (```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nRaw response: {raw[:500]}")


def _call_claude_cli(prompt: str, system: Optional[str] = None,
                     json_mode: bool = False) -> Optional[str]:
    """Call Claude CLI in print mode. Returns None if CLI not available."""
    try:
        # Build the full prompt
        full_prompt = ""
        if system:
            full_prompt += f"{system}\n\n"
        full_prompt += prompt
        if json_mode:
            full_prompt += "\n\nRespond with valid JSON only, no markdown fences or other text."

        cmd = [
            "claude", "-p",
            full_prompt,
            "--model", "sonnet",
            "--output-format", "json",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.warning(f"Claude CLI failed (exit {result.returncode}): {result.stderr[:200]}")
            return None

        # Parse the CLI JSON envelope
        data = json.loads(result.stdout)
        if data.get("is_error"):
            logger.warning(f"Claude CLI error: {data.get('result', 'unknown')}")
            return None

        response_text = data.get("result", "")
        cost = data.get("total_cost_usd", 0)
        logger.info(f"Claude CLI response (${cost:.4f})")

        return response_text

    except FileNotFoundError:
        logger.info("Claude CLI not found, falling back to OpenAI API")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI timed out after 120s")
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Claude CLI response parse error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Claude CLI unexpected error: {e}")
        return None


def _call_openai_api(prompt: str, system: Optional[str] = None,
                     temperature: float = 0.7, max_tokens: int = 1500,
                     json_mode: bool = False) -> str:
    """Fallback: call OpenAI API directly."""
    from openai import OpenAI

    if not settings.openai_api_key:
        raise RuntimeError("Neither Claude CLI nor OpenAI API available")

    client = OpenAI(api_key=settings.openai_api_key)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs = {
        "model": "gpt-5.4-mini-2026-03-17",
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content

    if not content:
        raise RuntimeError("Empty response from OpenAI")

    logger.info("OpenAI API response received")
    return content
