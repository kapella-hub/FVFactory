"""Tests for LLM provider abstraction."""
import pytest
from unittest.mock import patch, MagicMock
import json
import logging
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from app.config import Settings, settings


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


@patch("app.llm.subprocess.run")
def test_claude_cli_decodes_utf8_explicitly(mock_run):
    """Windows default (cp1252) cannot decode the CLI's UTF-8 output."""
    from app.llm import ClaudeCLIProvider
    envelope = json.dumps({"result": "café — ok", "is_error": False}, ensure_ascii=False)
    mock_run.return_value = MagicMock(returncode=0, stdout=envelope, stderr="")
    assert ClaudeCLIProvider(timeout=30).generate("x") == "café — ok"
    kwargs = mock_run.call_args.kwargs
    assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"


# ---------------------------------------------------------------------------
# Configurable providers: claude_cli, codex, openai (brief 2026-10-03)
# ---------------------------------------------------------------------------



@pytest.fixture
def llm_settings(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(settings, "llm_fallback", "codex,openai")
    monkeypatch.setattr(settings, "claude_cli_model", "sonnet")
    monkeypatch.setattr(settings, "codex_model", "")
    monkeypatch.setattr(settings, "codex_reasoning_effort", "")
    monkeypatch.setattr(settings, "codex_cli_timeout", 300)
    monkeypatch.setattr(settings, "openai_model", "gpt-5.4-mini-2026-03-17")
    import app.llm
    app.llm.reset_last_provider()
    yield settings
    app.llm.reset_last_provider()


def _codex_run(seen, answer="hello", returncode=0, stderr=""):
    """Fake subprocess.run for codex: writes `answer` to the -o file (None = writes nothing)."""
    def fake_run(cmd, **kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        seen.update(cmd=list(cmd), kwargs=kwargs, out=out, cwd=Path(kwargs["cwd"]))
        seen["cwd_existed"] = seen["cwd"].is_dir()
        if answer is not None:
            out.write_text(answer, encoding="utf-8")
        return MagicMock(returncode=returncode, stdout="", stderr=stderr)
    return fake_run


def test_settings_defaults_for_the_llm_chain():
    s = Settings(_env_file=None)
    assert s.llm_provider == "claude_cli"
    assert s.llm_fallback == "codex,openai"
    assert s.claude_cli_model == "sonnet"
    assert s.codex_model == "gpt-5.5"              # a ChatGPT-login Codex rejects most other model names
    assert s.codex_reasoning_effort == "medium"   # gpt-5.5 rejects the "max" effort some configs set
    assert s.openai_model == "gpt-5.4-mini-2026-03-17"
    assert s.codex_cli_timeout == 300
    assert s.cost_codex_cli == 0.0


def test_settings_put_rejects_an_unknown_llm_provider():
    from app.run_options import validate_settings_updates
    valid, errors = validate_settings_updates(settings, {"llm_provider": "ollama"})
    assert "llm_provider" in errors and not valid
    valid, errors = validate_settings_updates(settings, {"llm_provider": "codex", "llm_fallback": "openai"})
    assert valid == {"llm_provider": "codex", "llm_fallback": "openai"} and not errors


def test_get_provider_codex():
    from app.llm import get_provider, CodexCLIProvider
    assert isinstance(get_provider("codex"), CodexCLIProvider)


def test_get_provider_invalid_lists_the_names():
    from app.llm import get_provider
    with pytest.raises(ValueError, match="Unknown LLM provider.*claude_cli.*codex.*openai"):
        get_provider("ollama")


# --- Codex CLI -------------------------------------------------------------

def test_codex_argv_stdin_and_output_file(llm_settings):
    from app.llm import CodexCLIProvider
    seen = {}
    with patch("app.llm.subprocess.run", side_effect=_codex_run(seen, answer="  hello  \n")):
        result = CodexCLIProvider().generate("Write it", system="Be brief", json_mode=True)
    assert result == "hello"
    cmd = seen["cmd"]
    assert os.path.basename(cmd[0]).lower().startswith("codex")
    assert cmd[1:] == ["exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral",
                       "--color", "never", "-o", str(seen["out"]), "-"]
    assert "-m" not in cmd                                    # codex_model "" = the CLI's default model
    kwargs = seen["kwargs"]
    prompt = kwargs["input"]
    assert prompt.index("Be brief") < prompt.index("Write it") < prompt.index("Respond with valid JSON only")
    assert "Write it" not in " ".join(cmd)                    # the prompt never travels on argv
    assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
    assert kwargs["timeout"] == 300 and kwargs["capture_output"] is True


def test_codex_runs_in_a_temp_dir_that_is_removed(llm_settings):
    from app.llm import CodexCLIProvider
    seen = {}
    with patch("app.llm.subprocess.run", side_effect=_codex_run(seen)):
        CodexCLIProvider().generate("x")
    cwd = seen["cwd"]
    assert seen["cwd_existed"]
    assert Path(tempfile.gettempdir()).resolve() in cwd.resolve().parents
    assert cwd.resolve() != Path.cwd().resolve()              # never the repo
    assert seen["out"].parent == cwd
    assert not cwd.exists() and not seen["out"].exists()


def test_codex_model_flag_only_when_set(llm_settings, monkeypatch):
    from app.llm import CodexCLIProvider
    monkeypatch.setattr(settings, "codex_model", "gpt-5.5")
    monkeypatch.setattr(settings, "codex_cli_timeout", 42)
    seen = {}
    with patch("app.llm.subprocess.run", side_effect=_codex_run(seen)):
        CodexCLIProvider().generate("x")
    cmd = seen["cmd"]
    assert cmd[cmd.index("-m") + 1] == "gpt-5.5" and cmd[-1] == "-"
    assert "-c" not in cmd                                   # effort "" = the Codex config value
    assert seen["kwargs"]["timeout"] == 42


def test_codex_reasoning_effort_override(llm_settings, monkeypatch):
    from app.llm import CodexCLIProvider
    monkeypatch.setattr(settings, "codex_reasoning_effort", "medium")
    seen = {}
    with patch("app.llm.subprocess.run", side_effect=_codex_run(seen)):
        CodexCLIProvider().generate("x")
    cmd = seen["cmd"]
    assert cmd[cmd.index("-c") + 1] == 'model_reasoning_effort="medium"' and cmd[-1] == "-"


def test_codex_generate_json(llm_settings):
    from app.llm import CodexCLIProvider
    seen = {}
    with patch("app.llm.subprocess.run", side_effect=_codex_run(seen, answer='```json\n{"ok": true}\n```')):
        assert CodexCLIProvider().generate_json("x") == {"ok": True}


@pytest.mark.parametrize("error, match", [
    (FileNotFoundError("codex"), "Codex CLI not found"),
    (subprocess.TimeoutExpired(cmd="codex", timeout=300), "Codex CLI timed out after 300s"),
])
def test_codex_launch_errors(llm_settings, error, match):
    from app.llm import CodexCLIProvider
    with patch("app.llm.subprocess.run", side_effect=error):
        with pytest.raises(RuntimeError, match=match):
            CodexCLIProvider().generate("x")


def test_codex_nonzero_exit_reports_stderr_and_cleans_up(llm_settings):
    from app.llm import CodexCLIProvider
    seen = {}
    banner = "OpenAI Codex v0.153.4 (research preview)\n--------\nworkdir: C:/tmp\n" * 20
    with patch("app.llm.subprocess.run",
               side_effect=_codex_run(seen, answer=None, returncode=1, stderr=banner + "ERROR: not logged in\n")):
        with pytest.raises(RuntimeError, match=r"Codex CLI failed \(exit 1\): .*ERROR: not logged in$") as exc:
            CodexCLIProvider().generate("x")
    assert len(str(exc.value)) < 300                          # the tail of stderr (the banner comes first)
    assert not seen["cwd"].exists()


@pytest.mark.parametrize("answer", [None, "", "   \n"])
def test_codex_empty_output_is_an_error(llm_settings, answer):
    from app.llm import CodexCLIProvider
    seen = {}
    with patch("app.llm.subprocess.run", side_effect=_codex_run(seen, answer=answer)):
        with pytest.raises(RuntimeError, match="Codex CLI returned no answer"):
            CodexCLIProvider().generate("x")
    assert not seen["cwd"].exists()


# --- Claude CLI ------------------------------------------------------------

@patch("app.llm.subprocess.run")
def test_claude_cli_prompt_on_stdin_and_model_setting(mock_run, llm_settings, monkeypatch):
    from app.llm import ClaudeCLIProvider
    monkeypatch.setattr(settings, "claude_cli_model", "opus")
    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")
    assert ClaudeCLIProvider(timeout=30).generate("Say hello", system="Be kind", json_mode=True) == "ok"
    cmd = mock_run.call_args.args[0]
    assert os.path.basename(cmd[0]).lower().startswith("claude")
    assert cmd[1:] == ["-p", "--model", "opus", "--output-format", "json", "--strict-mcp-config"]
    cwd = mock_run.call_args.kwargs["cwd"]                     # an empty temp dir, never the repo
    assert os.path.basename(cwd).startswith("fvf-claude-") and not os.path.exists(cwd)
    prompt = mock_run.call_args.kwargs["input"]
    assert prompt.index("Be kind") < prompt.index("Say hello") < prompt.index("Respond with valid JSON only")
    assert mock_run.call_args.kwargs["timeout"] == 30


# --- OpenAI ----------------------------------------------------------------

def test_openai_model_from_settings(llm_settings, monkeypatch):
    from app.llm import OpenAIProvider
    monkeypatch.setattr(settings, "openai_api_key", "x")
    monkeypatch.setattr(settings, "openai_model", "my-model")
    client = MagicMock()
    client.chat.completions.create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="hi"))])
    with patch("openai.OpenAI", return_value=client):
        assert OpenAIProvider().generate("x") == "hi"
    assert client.chat.completions.create.call_args.kwargs["model"] == "my-model"


# --- Provider chain --------------------------------------------------------

@pytest.mark.parametrize("primary, fallback, chain", [
    ("claude_cli", "codex,openai", ["claude_cli", "codex", "openai"]),
    ("codex", "codex,openai", ["codex", "openai"]),                       # the primary is skipped
    ("codex", " openai , claude_cli,openai ", ["codex", "openai", "claude_cli"]),   # duplicates skipped
    ("openai", "", ["openai"]),
    ("openai", "none", ["openai"]),
    ("claude_cli", " None ", ["claude_cli"]),
])
def test_provider_chain(llm_settings, monkeypatch, primary, fallback, chain):
    from app.llm import provider_chain
    monkeypatch.setattr(settings, "llm_provider", primary)
    monkeypatch.setattr(settings, "llm_fallback", fallback)
    assert provider_chain() == chain


def test_provider_chain_ignores_an_unknown_name_with_one_warning(llm_settings, monkeypatch, caplog):
    from app.llm import provider_chain
    monkeypatch.setattr(settings, "llm_fallback", "ollama,openai")
    with caplog.at_level(logging.WARNING, logger="app.llm"):
        assert provider_chain() == ["claude_cli", "openai"]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "ollama" in warnings[0].getMessage()


class _FakeProvider:
    def __init__(self, name, calls, error=None):
        self.name, self.calls, self.error = name, calls, error

    def generate(self, prompt, system=None, temperature=0.7, max_tokens=1500, json_mode=False):
        self.calls.append(self.name)
        if self.error:
            raise RuntimeError(self.error)
        return f"answer from {self.name}"


def _fake_providers(monkeypatch, errors):
    import app.llm
    calls = []
    monkeypatch.setattr(app.llm, "get_provider",
                        lambda name=None: _FakeProvider(name, calls, errors.get(name)))
    return calls


def test_generate_falls_back_in_order_and_records_the_answering_provider(llm_settings, monkeypatch, caplog):
    import app.llm
    calls = _fake_providers(monkeypatch, {"claude_cli": "Claude CLI not found"})
    with caplog.at_level(logging.INFO, logger="app.llm"):
        assert app.llm.generate("x") == "answer from codex"
    assert calls == ["claude_cli", "codex"]                   # openai never tried
    assert app.llm.last_provider() == "codex"
    assert any("codex" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records)


def test_generate_without_fallback_raises_the_primary_error(llm_settings, monkeypatch):
    import app.llm
    monkeypatch.setattr(settings, "llm_fallback", "none")
    calls = _fake_providers(monkeypatch, {"claude_cli": "boom"})
    with pytest.raises(RuntimeError, match="claude_cli: boom"):
        app.llm.generate("x")
    assert calls == ["claude_cli"]
    assert app.llm.last_provider() is None


def test_generate_all_fail_names_every_provider(llm_settings, monkeypatch):
    import app.llm
    calls = _fake_providers(monkeypatch, {"claude_cli": "not found", "codex": "timed out",
                                          "openai": "no key"})
    with pytest.raises(RuntimeError) as exc:
        app.llm.generate("x")
    assert calls == ["claude_cli", "codex", "openai"]
    msg = str(exc.value)
    assert "claude_cli: not found" in msg and "codex: timed out" in msg and "openai: no key" in msg


def test_generate_json_uses_the_chain(llm_settings, monkeypatch):
    import app.llm
    monkeypatch.setattr(settings, "llm_provider", "codex")
    calls = []

    class JsonProvider(_FakeProvider):
        def generate(self, *args, **kwargs):
            self.calls.append(self.name)
            return '{"by": "%s"}' % self.name

    monkeypatch.setattr(app.llm, "get_provider", lambda name=None: JsonProvider(name, calls))
    assert app.llm.generate_json("x") == {"by": "codex"}
    assert app.llm.last_provider() == "codex"


def test_last_provider_is_thread_local(llm_settings, monkeypatch):
    import app.llm
    _fake_providers(monkeypatch, {})
    app.llm.generate("x")
    assert app.llm.last_provider() == "claude_cli"
    seen = {}

    def worker():
        seen["before"] = app.llm.last_provider()
        app.llm._set_last_provider("openai")
        seen["after"] = app.llm.last_provider()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert seen == {"before": None, "after": "openai"}
    assert app.llm.last_provider() == "claude_cli"
    app.llm.reset_last_provider()
    assert app.llm.last_provider() is None


# --- Cost items --------------------------------------------------------------

@pytest.mark.parametrize("provider, item", [("openai", "openai_gpt4o"), ("codex", "codex_cli"),
                                            ("claude_cli", "claude_cli")])
def test_llm_cost_item_maps_the_provider(provider, item):
    from app.cin.cost_estimate import llm_cost_item
    assert llm_cost_item(provider) == item


def test_llm_cost_item_defaults_to_the_setting(monkeypatch):
    from app.cin.cost_estimate import llm_cost_item
    monkeypatch.setattr(settings, "llm_provider", "codex")
    assert llm_cost_item() == "codex_cli"
    monkeypatch.setattr(settings, "llm_provider", "openai")
    assert llm_cost_item() == "openai_gpt4o"


def test_codex_cli_cost_item_and_stage_costs(monkeypatch):
    from app.cin.cost_estimate import stage_costs
    from app.cost_tracker import unit_costs
    monkeypatch.setattr(settings, "cost_codex_cli", 0.0)
    monkeypatch.setattr(settings, "cost_openai_gpt4o", 0.005)
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    assert unit_costs()["codex_cli"] == 0.0
    kw = dict(narration_chars=10, image_count=0, mock_images=True, llm_calls=2)
    assert stage_costs(**kw)["llm"] == 0.0
    assert stage_costs(**kw, llm_provider="openai")["llm"] == 0.01      # the provider that answered
    assert stage_costs(**kw, llm_provider="codex")["llm"] == 0.0


# --- Startup validation ------------------------------------------------------

def _validation_settings(monkeypatch, provider):
    monkeypatch.setattr(settings, "llm_provider", provider)
    monkeypatch.setattr(settings, "llm_fallback", "codex,openai")
    monkeypatch.setattr(settings, "provider_mode", "mixed")
    monkeypatch.setattr(settings, "elevenlabs_api_key", "x")
    monkeypatch.setattr(settings, "openai_api_key", "")


@pytest.mark.parametrize("provider", ["claude_cli", "codex"])
def test_validate_config_warns_when_the_cli_is_missing(monkeypatch, caplog, provider):
    import main
    _validation_settings(monkeypatch, provider)
    monkeypatch.setattr(main.shutil, "which", lambda name: None)
    with caplog.at_level(logging.WARNING):
        assert main.validate_config(use_mock=True, enable_motion=False) is True
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(msgs) == 1 and provider in msgs[0]
    fallback = [p for p in ("codex", "openai") if p != provider]
    assert all(p in msgs[0] for p in fallback)


def test_validate_config_quiet_when_the_cli_exists(monkeypatch, caplog):
    import main
    _validation_settings(monkeypatch, "codex")
    monkeypatch.setattr(main.shutil, "which", lambda name: f"/usr/bin/{name}")
    with caplog.at_level(logging.WARNING):
        assert main.validate_config(use_mock=True, enable_motion=False) is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_validate_config_openai_still_needs_a_key(monkeypatch):
    import main
    _validation_settings(monkeypatch, "openai")
    assert main.validate_config(use_mock=True, enable_motion=False) is False


# --- Web settings --------------------------------------------------------------

def _fastapi_stub():
    """Minimal fastapi stand-in (the web extras are not installed in every test environment)."""
    import types

    class APIRouter:
        def _route(self, *args, **kwargs):
            return lambda fn: fn
        get = put = post = delete = _route

    class HTTPException(Exception):
        def __init__(self, status_code=500, detail=None):
            super().__init__(detail)
            self.status_code, self.detail = status_code, detail

    return types.SimpleNamespace(APIRouter=APIRouter, HTTPException=HTTPException)


def test_config_api_exposes_the_llm_settings(llm_settings, monkeypatch, tmp_path):
    import asyncio
    import importlib
    import sys
    try:
        import fastapi  # noqa: F401
    except ImportError:
        monkeypatch.setitem(sys.modules, "fastapi", _fastapi_stub())
        # imported fresh against the stub; the setitem undo drops that copy again after the test
        monkeypatch.setitem(sys.modules, "app.web.routes.api_config", None)
        del sys.modules["app.web.routes.api_config"]
    api_config = importlib.import_module("app.web.routes.api_config")
    monkeypatch.setattr(api_config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(settings, "codex_model", "gpt-5.5")
    current = asyncio.run(api_config.get_config())
    assert {k: current[k] for k in ("llm_provider", "llm_fallback", "claude_cli_model", "codex_model",
                                    "openai_model", "codex_cli_timeout")} == {
        "llm_provider": "claude_cli", "llm_fallback": "codex,openai", "claude_cli_model": "sonnet",
        "codex_model": "gpt-5.5", "openai_model": "gpt-5.4-mini-2026-03-17", "codex_cli_timeout": 300}


def test_settings_js_offers_the_three_providers_and_the_fallback_input():
    js = (Path(__file__).parents[1] / "app/web/static/js/settings.js").read_text(encoding="utf-8")
    assert "'ollama'" not in js
    for key in ("'claude_cli', 'Claude Code (headless)'", "'codex', 'Codex CLI (headless)'",
                "'openai', 'OpenAI API'", 'data-key="llm_fallback"'):
        assert key in js, key
