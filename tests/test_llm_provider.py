"""Tests for LLM provider abstraction."""
import pytest
from unittest.mock import patch, MagicMock
import json


def test_get_provider_claude_cli():
    from app.llm import get_provider, ClaudeCLIProvider
    provider = get_provider("claude_cli")
    assert isinstance(provider, ClaudeCLIProvider)


def test_get_provider_openai():
    from app.llm import get_provider, OpenAIProvider
    provider = get_provider("openai")
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_invalid():
    from app.llm import get_provider
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("invalid")


@patch("app.llm.subprocess.run")
def test_claude_cli_generate(mock_run):
    from app.llm import ClaudeCLIProvider
    # Claude CLI returns JSON envelope with --output-format json
    envelope = json.dumps({"result": "Hello world", "is_error": False, "total_cost_usd": 0.001})
    mock_run.return_value = MagicMock(returncode=0, stdout=envelope, stderr="")
    provider = ClaudeCLIProvider(timeout=30)
    result = provider.generate("Say hello")
    assert result == "Hello world"


@patch("app.llm.subprocess.run")
def test_claude_cli_generate_json(mock_run):
    from app.llm import ClaudeCLIProvider
    envelope = json.dumps({"result": '{"answer": 42}', "is_error": False, "total_cost_usd": 0.001})
    mock_run.return_value = MagicMock(returncode=0, stdout=envelope, stderr="")
    provider = ClaudeCLIProvider(timeout=30)
    result = provider.generate_json("Give me JSON")
    assert result == {"answer": 42}


@patch("app.llm.subprocess.run")
def test_claude_cli_strips_markdown_fences(mock_run):
    from app.llm import ClaudeCLIProvider
    envelope = json.dumps({"result": '```json\n{"answer": 42}\n```', "is_error": False, "total_cost_usd": 0.001})
    mock_run.return_value = MagicMock(returncode=0, stdout=envelope, stderr="")
    provider = ClaudeCLIProvider(timeout=30)
    result = provider.generate_json("Give me JSON")
    assert result == {"answer": 42}
