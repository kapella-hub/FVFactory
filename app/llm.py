"""
LLM wrapper - provider pattern with Claude CLI and OpenAI API support.

Providers:
  - ClaudeCLIProvider: Uses `claude -p` with --output-format json envelope
  - OpenAIProvider: Uses OpenAI chat completions API

Module-level generate() / generate_json() functions are backward-compatible
and try the configured provider first, falling back to the other on failure.
"""

import json
import logging
import subprocess
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider classes
# ---------------------------------------------------------------------------

class ClaudeCLIProvider:
    """LLM provider that shells out to the Claude CLI."""

    def __init__(self, timeout: Optional[int] = None):
        self.timeout = timeout if timeout is not None else settings.claude_cli_timeout

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        """Generate text via Claude CLI.

        Returns the text result.
        Raises RuntimeError on failure.
        """
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

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise RuntimeError("Claude CLI not found")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Claude CLI timed out after {self.timeout}s")

        if result.returncode != 0:
            raise RuntimeError(
                f"Claude CLI failed (exit {result.returncode}): {result.stderr[:200]}"
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Claude CLI response parse error: {e}")

        if data.get("is_error"):
            raise RuntimeError(f"Claude CLI error: {data.get('result', 'unknown')}")

        response_text = data.get("result", "")
        cost = data.get("total_cost_usd", 0)
        logger.info(f"Claude CLI response (${cost:.4f})")

        return response_text

    def generate_json(self, prompt: str, system: Optional[str] = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict:
        """Generate and parse a JSON response via Claude CLI."""
        raw = self.generate(prompt, system, temperature, max_tokens, json_mode=True)
        return _strip_and_parse_json(raw)


class OpenAIProvider:
    """LLM provider that uses the OpenAI chat completions API."""

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        """Generate text via OpenAI API.

        Returns the text result.
        Raises RuntimeError on failure.
        """
        from openai import OpenAI

        if not settings.openai_api_key:
            raise RuntimeError("OpenAI API key not configured")

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

    def generate_json(self, prompt: str, system: Optional[str] = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict:
        """Generate and parse a JSON response via OpenAI API."""
        raw = self.generate(prompt, system, temperature, max_tokens, json_mode=True)
        return _strip_and_parse_json(raw)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_provider(name: Optional[str] = None):
    """Return a provider instance by name.

    Args:
        name: "claude_cli" | "openai". Defaults to settings.llm_provider.

    Raises:
        ValueError: If the name is not recognised.
    """
    if name is None:
        name = settings.llm_provider

    if name == "claude_cli":
        return ClaudeCLIProvider()
    elif name == "openai":
        return OpenAIProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {name!r}. Choose 'claude_cli' or 'openai'.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_and_parse_json(raw: str) -> dict:
    """Strip markdown fences from a string and parse as JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [line for line in lines if not line.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\nRaw response: {raw[:500]}")


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------

def generate(prompt: str, system: Optional[str] = None, temperature: float = 0.7,
             max_tokens: int = 1500, json_mode: bool = False) -> str:
    """Generate text using the configured LLM provider with automatic fallback.

    Tries the configured provider first (settings.llm_provider), then falls
    back to the other provider on failure.

    Args:
        prompt: The user prompt
        system: Optional system prompt
        temperature: Creativity level
        max_tokens: Max output tokens
        json_mode: If True, instruct the model to return valid JSON

    Returns:
        The generated text response
    """
    primary_name = settings.llm_provider
    fallback_name = "openai" if primary_name == "claude_cli" else "claude_cli"

    primary = get_provider(primary_name)
    try:
        return primary.generate(prompt, system, temperature, max_tokens, json_mode)
    except Exception as e:
        logger.warning(f"Primary provider ({primary_name}) failed: {e}. Falling back to {fallback_name}.")

    fallback = get_provider(fallback_name)
    return fallback.generate(prompt, system, temperature, max_tokens, json_mode)


def generate_json(prompt: str, system: Optional[str] = None, temperature: float = 0.7,
                  max_tokens: int = 1500) -> dict:
    """Generate and parse a JSON response with automatic provider fallback.

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If response is not valid JSON
    """
    raw = generate(prompt, system, temperature, max_tokens, json_mode=True)
    return _strip_and_parse_json(raw)
