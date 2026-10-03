"""
LLM wrapper - provider pattern for the script LLM.

Providers (settings.llm_provider / settings.llm_fallback names):
  - "claude_cli" ClaudeCLIProvider: headless `claude -p`, prompt on stdin, --output-format json envelope
  - "codex"      CodexCLIProvider: headless `codex exec`, prompt on stdin, answer read from the -o file
  - "openai"     OpenAIProvider: OpenAI chat completions API (paid)

Module-level generate() / generate_json() try settings.llm_provider first, then each provider named in
settings.llm_fallback, in order. last_provider() tells the calling thread which provider answered.
"""

import json
import logging
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

PROVIDER_NAMES = ("claude_cli", "codex", "openai")
CLI_COMMANDS = {"claude_cli": "claude", "codex": "codex"}      # providers that need a CLI on PATH
JSON_INSTRUCTION = "\n\nRespond with valid JSON only, no markdown fences or other text."


def _cli(name: str) -> str:
    """Full path of a CLI. On Windows npm installs `codex` as codex.cmd, which CreateProcess does not
    find from the bare name; shutil.which resolves it. Unresolved = the bare name (FileNotFoundError)."""
    return shutil.which(name) or name


def _full_prompt(prompt: str, system: Optional[str], json_mode: bool) -> str:
    full = f"{system}\n\n" if system else ""
    full += prompt
    if json_mode:
        full += JSON_INSTRUCTION
    return full


def _tail(text: Optional[str], limit: int = 200) -> str:
    """Short, single-line excerpt of a CLI's stderr: the end, where the error is (banners come first)."""
    return " ".join((text or "").split())[-limit:]


# ---------------------------------------------------------------------------
# Provider classes
# ---------------------------------------------------------------------------

class ClaudeCLIProvider:
    """LLM provider that shells out to the Claude CLI (Claude Code, headless)."""

    def __init__(self, timeout: Optional[int] = None):
        self.timeout = timeout if timeout is not None else settings.claude_cli_timeout

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        """Generate text via Claude CLI. The prompt goes on stdin (Windows argv limits and quoting).

        Returns the text result.
        Raises RuntimeError on failure.
        """
        cmd = [
            _cli("claude"), "-p",
            "--model", settings.claude_cli_model,
            "--output-format", "json",
        ]

        try:
            result = subprocess.run(
                cmd,
                input=_full_prompt(prompt, system, json_mode),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
        except FileNotFoundError:
            raise RuntimeError("Claude CLI not found")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Claude CLI timed out after {self.timeout}s")

        if result.returncode != 0:
            raise RuntimeError(
                f"Claude CLI failed (exit {result.returncode}): {(result.stderr or result.stdout or '')[:200]}"
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


class CodexCLIProvider:
    """LLM provider that shells out to the OpenAI Codex CLI (`codex exec`, headless).

    Runs in a fresh temp directory (never the repo) with a read-only sandbox and no saved session;
    the final answer is read from the -o file in that directory, which is always removed."""

    def __init__(self, timeout: Optional[int] = None):
        self.timeout = timeout if timeout is not None else settings.codex_cli_timeout

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        """Generate text via Codex CLI. temperature / max_tokens are not exposed by `codex exec`.

        Returns the text result.
        Raises RuntimeError on failure.
        """
        with tempfile.TemporaryDirectory(prefix="fvf-codex-", ignore_cleanup_errors=True) as tmp:
            answer_file = Path(tmp) / "answer.txt"
            cmd = [
                _cli("codex"), "exec",
                "--skip-git-repo-check",
                "--sandbox", "read-only",
                "--ephemeral",
                "--color", "never",
                "-o", str(answer_file),
            ]
            if settings.codex_model:
                cmd += ["-m", settings.codex_model]
            cmd.append("-")                      # instructions from stdin

            try:
                result = subprocess.run(
                    cmd,
                    input=_full_prompt(prompt, system, json_mode),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout,
                    cwd=tmp,
                )
            except FileNotFoundError:
                raise RuntimeError("Codex CLI not found")
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"Codex CLI timed out after {self.timeout}s")

            if result.returncode != 0:
                raise RuntimeError(f"Codex CLI failed (exit {result.returncode}): {_tail(result.stderr)}")

            answer = ""
            if answer_file.is_file():
                answer = answer_file.read_text(encoding="utf-8", errors="replace").strip()

        if not answer:
            raise RuntimeError(f"Codex CLI returned no answer: {_tail(result.stderr) or 'empty output'}")

        logger.info("Codex CLI response received")
        return answer

    def generate_json(self, prompt: str, system: Optional[str] = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict:
        """Generate and parse a JSON response via Codex CLI."""
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
            "model": settings.openai_model,
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
# Factory and fallback chain
# ---------------------------------------------------------------------------

_PROVIDERS = {
    "claude_cli": ClaudeCLIProvider,
    "codex": CodexCLIProvider,
    "openai": OpenAIProvider,
}


def get_provider(name: Optional[str] = None):
    """Return a provider instance by name.

    Args:
        name: "claude_cli" | "codex" | "openai". Defaults to settings.llm_provider.

    Raises:
        ValueError: If the name is not recognised.
    """
    if name is None:
        name = settings.llm_provider
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {name!r}. Choose one of: {', '.join(PROVIDER_NAMES)}.")
    return cls()


def provider_chain() -> list:
    """Providers generate() tries, in order: settings.llm_provider, then each name in the comma list
    settings.llm_fallback, skipping the primary and duplicates. "" or "none" = no fallback. Unknown
    names are ignored with one warning (never an error)."""
    chain = [settings.llm_provider]
    raw = (settings.llm_fallback or "").strip()
    if raw.lower() == "none":
        return chain
    unknown = []
    for name in raw.split(","):
        name = name.strip().lower()
        if not name or name == "none" or name in chain:
            continue
        if name not in PROVIDER_NAMES:
            unknown.append(name)
            continue
        chain.append(name)
    if unknown:
        logger.warning("Ignoring unknown llm_fallback provider(s) %s (known: %s)",
                       ", ".join(unknown), ", ".join(PROVIDER_NAMES))
    return chain


_local = threading.local()


def last_provider() -> Optional[str]:
    """Name of the provider that answered this thread's last successful generate(); None = none yet
    (or reset). Per thread, so concurrent runs (web UI, scheduler) never see each other's value."""
    return getattr(_local, "provider", None)


def reset_last_provider() -> None:
    """Forget this thread's last provider (run_pipeline calls it before the script stage)."""
    _local.provider = None


def _set_last_provider(name: Optional[str]) -> None:
    _local.provider = name


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
    """Generate text with the configured provider chain (see provider_chain()).

    Tries each provider in order; the first answer wins and is recorded for last_provider().

    Args:
        prompt: The user prompt
        system: Optional system prompt
        temperature: Creativity level
        max_tokens: Max output tokens
        json_mode: If True, instruct the model to return valid JSON

    Returns:
        The generated text response

    Raises:
        RuntimeError: every provider failed; the message names each provider and its error.
    """
    chain = provider_chain()
    errors = []
    for i, name in enumerate(chain):
        try:
            text = get_provider(name).generate(prompt, system, temperature, max_tokens, json_mode)
        except Exception as e:  # noqa: BLE001 - any provider failure moves on to the next one
            errors.append(f"{name}: {e}")
            nxt = chain[i + 1] if i + 1 < len(chain) else None
            logger.warning("LLM provider %s failed: %s.%s", name, e,
                           f" Falling back to {nxt}." if nxt else "")
            continue
        _set_last_provider(name)
        logger.info("Script LLM answered by %s", name)
        return text
    raise RuntimeError("All LLM providers failed: " + "; ".join(errors))


def generate_json(prompt: str, system: Optional[str] = None, temperature: float = 0.7,
                  max_tokens: int = 1500) -> dict:
    """Generate and parse a JSON response with the provider fallback chain.

    Returns:
        Parsed JSON dict

    Raises:
        ValueError: If response is not valid JSON
    """
    raw = generate(prompt, system, temperature, max_tokens, json_mode=True)
    return _strip_and_parse_json(raw)
