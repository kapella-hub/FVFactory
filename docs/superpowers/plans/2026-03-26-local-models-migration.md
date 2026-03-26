# Local Models Migration + Scheduler + UI Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Replicate API (Flux images, Minimax video) with local models, add a job scheduler, and overhaul the Streamlit UI to FastAPI + vanilla HTML/JS SPA.

**Architecture:** Provider abstraction layer wraps each generation service (LLM, image, video) behind a Protocol interface, allowing runtime switching between local and API backends via config. FastAPI serves a vanilla JS SPA with WebSocket progress updates. APScheduler runs jobs in background threads with SQLite persistence.

**Tech Stack:** Python 3.14, FastAPI, diffusers (FLUX.2 Klein, Wan2.1), APScheduler 3.x, SQLite, vanilla HTML/CSS/JS, WebSocket

**Spec:** `docs/superpowers/specs/2026-03-26-local-models-migration-design.md`

---

## File Map

### New Files

| File | Responsibility |
|---|---|
| `app/providers.py` | Protocol definitions for LLM, Image, Video providers |
| `app/local_image_gen.py` | FLUX.2 Klein 4B local image generation via diffusers |
| `app/local_video_gen.py` | Wan2.1 I2V local video generation via diffusers |
| `app/web/server.py` | FastAPI app, lifespan, CORS, static files, catch-all SPA route |
| `app/web/ws.py` | WebSocket manager for real-time progress broadcasting |
| `app/web/routes/api_generate.py` | POST /api/generate — on-demand video generation |
| `app/web/routes/api_library.py` | GET /api/library — list videos, metadata, thumbnails |
| `app/web/routes/api_scheduler.py` | CRUD endpoints for scheduled jobs |
| `app/web/routes/api_config.py` | GET/PUT /api/config — settings management |
| `app/web/static/index.html` | SPA shell with sidebar navigation |
| `app/web/static/css/tokens.css` | Design tokens (colors, spacing, typography) |
| `app/web/static/css/styles.css` | Main stylesheet |
| `app/web/static/js/app.js` | SPA router, navigation, shared state |
| `app/web/static/js/ws.js` | WebSocket client |
| `app/web/static/js/dashboard.js` | Dashboard page |
| `app/web/static/js/generate.js` | Generate page |
| `app/web/static/js/library.js` | Library page |
| `app/web/static/js/scheduler.js` | Scheduler page |
| `app/web/static/js/settings.js` | Settings page |
| `app/scheduler.py` | APScheduler integration, SQLite job store, job runner |
| `data/config.json` | UI-managed settings (created at runtime) |
| `tests/test_providers.py` | Provider abstraction tests |
| `tests/test_local_image_gen.py` | Local image gen tests |
| `tests/test_local_video_gen.py` | Local video gen tests |
| `tests/test_scheduler.py` | Scheduler tests |
| `tests/test_web_api.py` | FastAPI route tests |

### Modified Files

| File | Changes |
|---|---|
| `app/config.py` | Add provider_mode, image_provider, motion_provider, llm_provider, wan_model_size, data_dir settings |
| `app/llm.py` | Refactor to use LLMProvider protocol, make provider configurable |
| `app/asset_manager.py` | Add ImageProvider abstraction, route to local or Replicate |
| `app/motion_gen.py` | Add VideoProvider abstraction, route to local or Replicate |
| `app/cost_tracker.py` | Add $0.00 entries for local providers, track compute time |
| `main.py` | Update validate_config() for optional API keys, add --serve flag, add --local/--api flags |
| `requirements.txt` | Add diffusers, transformers, accelerate, safetensors, fastapi, uvicorn, websockets, apscheduler |

### Removed Files (Phase 3)

| File | Reason |
|---|---|
| `app/dashboard.py` | Replaced by FastAPI SPA |
| `app/library.py` | Replaced by FastAPI SPA |

---

## Task 1: Provider Protocol Definitions

**Files:**
- Create: `app/providers.py`
- Create: `tests/test_providers.py`

- [ ] **Step 1: Write the provider protocol tests**

```python
# tests/test_providers.py
"""Tests for provider protocol definitions."""
import pytest
from app.providers import LLMProvider, ImageProvider, VideoProvider


class MockLLM:
    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        return "mock response"

    def generate_json(self, prompt: str, system: str | None = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict:
        return {"mock": True}


class MockImage:
    def generate(self, prompt: str, width: int, height: int,
                 output_path: str) -> str:
        return output_path

    def generate_batch(self, prompts: list[str], width: int, height: int,
                       output_dir: str) -> list[str]:
        return [f"{output_dir}/{i}.png" for i in range(len(prompts))]


class MockVideo:
    def generate(self, image_path: str, prompt: str,
                 output_path: str, duration: float = 5.0) -> str:
        return output_path


def test_llm_provider_protocol():
    """MockLLM satisfies LLMProvider protocol."""
    provider: LLMProvider = MockLLM()
    assert provider.generate("hello") == "mock response"
    assert provider.generate_json("hello") == {"mock": True}


def test_image_provider_protocol():
    """MockImage satisfies ImageProvider protocol."""
    provider: ImageProvider = MockImage()
    assert provider.generate("a cat", 1080, 1920, "/tmp/out.png") == "/tmp/out.png"


def test_video_provider_protocol():
    """MockVideo satisfies VideoProvider protocol."""
    provider: VideoProvider = MockVideo()
    assert provider.generate("/img.png", "zoom in", "/tmp/out.mp4") == "/tmp/out.mp4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.providers'`

- [ ] **Step 3: Write provider protocols**

```python
# app/providers.py
"""Provider protocol definitions for pluggable backends."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for text generation providers."""

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str: ...

    def generate_json(self, prompt: str, system: str | None = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict: ...


@runtime_checkable
class ImageProvider(Protocol):
    """Protocol for image generation providers."""

    def generate(self, prompt: str, width: int, height: int,
                 output_path: str) -> str: ...

    def generate_batch(self, prompts: list[str], width: int, height: int,
                       output_dir: str) -> list[str]: ...


@runtime_checkable
class VideoProvider(Protocol):
    """Protocol for image-to-video motion providers."""

    def generate(self, image_path: str, prompt: str,
                 output_path: str, duration: float = 5.0) -> str: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_providers.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/providers.py tests/test_providers.py
git commit -m "feat: add provider protocol definitions for LLM, image, and video"
```

---

## Task 2: Config Updates

**Files:**
- Modify: `app/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write config tests for new settings**

Add to `tests/test_config.py`:

```python
def test_provider_settings_defaults():
    """New provider settings have correct defaults."""
    from app.config import Settings
    s = Settings(openai_api_key="test", elevenlabs_api_key="test")
    assert s.provider_mode == "local"
    assert s.llm_provider == "claude_cli"
    assert s.image_provider == "local"
    assert s.motion_provider == "local"
    assert s.wan_model_size == "1.3b"
    assert s.data_dir == "data"
    assert s.claude_cli_timeout == 120


def test_provider_mode_sets_individual_providers():
    """provider_mode 'api' should be readable."""
    from app.config import Settings
    s = Settings(openai_api_key="test", provider_mode="api")
    assert s.provider_mode == "api"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_config.py -v`
Expected: FAIL — Settings has no attribute `provider_mode`

- [ ] **Step 3: Add new settings to config.py**

Add the following block after the `# === V2 Settings ===` section in `app/config.py`:

```python
    # === V3 Settings: Provider Configuration ===

    # Provider mode: "local" (all local), "api" (all API), "mixed" (per-provider)
    provider_mode: str = "local"

    # Individual provider selection (used when provider_mode="mixed" or to override)
    llm_provider: str = "claude_cli"        # "claude_cli" | "openai"
    image_provider: str = "local"           # "local" | "replicate"
    motion_provider: str = "local"          # "local" | "replicate"

    # Local model settings
    wan_model_size: str = "1.3b"            # "1.3b" | "14b"
    flux_local_model: str = "black-forest-labs/FLUX.1-schnell"
    claude_cli_timeout: int = 120           # seconds

    # Data directory (scheduler DB, config.json)
    data_dir: str = "data"

    # Local provider cost tracking (compute time in seconds)
    cost_local_image: float = 0.0
    cost_local_video: float = 0.0
    cost_claude_cli: float = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_config.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add v3 provider configuration settings"
```

---

## Task 3: Refactor LLM Module to Provider Pattern

**Files:**
- Modify: `app/llm.py`
- Create: `tests/test_llm_provider.py`

- [ ] **Step 1: Write tests for provider-based LLM**

```python
# tests/test_llm_provider.py
"""Tests for LLM provider abstraction."""
import pytest
from unittest.mock import patch, MagicMock
from app.llm import ClaudeCLIProvider, OpenAIProvider, get_provider


def test_get_provider_claude_cli():
    provider = get_provider("claude_cli")
    assert isinstance(provider, ClaudeCLIProvider)


def test_get_provider_openai():
    provider = get_provider("openai")
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_invalid():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("invalid")


@patch("app.llm.subprocess.run")
def test_claude_cli_generate(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout="Hello world", stderr=""
    )
    provider = ClaudeCLIProvider(timeout=30)
    result = provider.generate("Say hello")
    assert result == "Hello world"
    mock_run.assert_called_once()


@patch("app.llm.subprocess.run")
def test_claude_cli_generate_json(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout='{"answer": 42}', stderr=""
    )
    provider = ClaudeCLIProvider(timeout=30)
    result = provider.generate_json("Give me JSON")
    assert result == {"answer": 42}


@patch("app.llm.subprocess.run")
def test_claude_cli_strips_markdown_fences(mock_run):
    mock_run.return_value = MagicMock(
        returncode=0, stdout='```json\n{"answer": 42}\n```', stderr=""
    )
    provider = ClaudeCLIProvider(timeout=30)
    result = provider.generate_json("Give me JSON")
    assert result == {"answer": 42}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_llm_provider.py -v`
Expected: FAIL — cannot import ClaudeCLIProvider

- [ ] **Step 3: Refactor app/llm.py to provider classes**

Rewrite `app/llm.py` to:

```python
"""
LLM provider abstraction — Claude CLI primary, OpenAI API fallback.

Providers implement the LLMProvider protocol from app.providers.
"""

import json
import logging
import re
import subprocess
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class ClaudeCLIProvider:
    """LLM provider using Claude CLI subprocess."""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        full_prompt = prompt
        if system:
            full_prompt = f"{system}\n\n{prompt}"
        if json_mode:
            full_prompt += "\n\nRespond with valid JSON only. No markdown fences."

        try:
            result = subprocess.run(
                ["claude", "-p", full_prompt, "--model", "sonnet"],
                capture_output=True, text=True, timeout=self.timeout
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            logger.warning("Claude CLI failed (rc=%d): %s", result.returncode, result.stderr[:200])
        except FileNotFoundError:
            logger.warning("Claude CLI not found in PATH")
        except subprocess.TimeoutExpired:
            logger.warning("Claude CLI timed out after %ds", self.timeout)
        raise RuntimeError("Claude CLI generation failed")

    def generate_json(self, prompt: str, system: Optional[str] = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict:
        text = self.generate(prompt, system=system, temperature=temperature,
                             max_tokens=max_tokens, json_mode=True)
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)


class OpenAIProvider:
    """LLM provider using OpenAI API."""

    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-5.4-mini-2026-03-17"

    def generate(self, prompt: str, system: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content.strip()

    def generate_json(self, prompt: str, system: Optional[str] = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict:
        text = self.generate(prompt, system=system, temperature=temperature,
                             max_tokens=max_tokens, json_mode=True)
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)


def get_provider(name: Optional[str] = None) -> "ClaudeCLIProvider | OpenAIProvider":
    """Get LLM provider by name. Defaults to settings.llm_provider."""
    name = name or settings.llm_provider
    if name == "claude_cli":
        return ClaudeCLIProvider(timeout=settings.claude_cli_timeout)
    elif name == "openai":
        return OpenAIProvider()
    else:
        raise ValueError(f"Unknown LLM provider: {name}")


# Module-level convenience functions (backward compatible)
_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def generate(prompt: str, system: Optional[str] = None, temperature: float = 0.7,
             max_tokens: int = 1500, json_mode: bool = False) -> str:
    """Generate text. Tries configured provider, falls back to other."""
    try:
        return _get_provider().generate(prompt, system, temperature, max_tokens, json_mode)
    except Exception as e:
        logger.warning("Primary LLM failed (%s), trying fallback: %s", type(e).__name__, e)
        fallback_name = "openai" if settings.llm_provider == "claude_cli" else "claude_cli"
        try:
            return get_provider(fallback_name).generate(prompt, system, temperature, max_tokens, json_mode)
        except Exception:
            raise


def generate_json(prompt: str, system: Optional[str] = None, temperature: float = 0.7,
                  max_tokens: int = 1500) -> dict:
    """Generate JSON response. Tries configured provider, falls back to other."""
    try:
        return _get_provider().generate_json(prompt, system, temperature, max_tokens)
    except Exception as e:
        logger.warning("Primary LLM JSON failed (%s), trying fallback: %s", type(e).__name__, e)
        fallback_name = "openai" if settings.llm_provider == "claude_cli" else "claude_cli"
        try:
            return get_provider(fallback_name).generate_json(prompt, system, temperature, max_tokens)
        except Exception:
            raise
```

- [ ] **Step 4: Run new tests + existing tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_llm_provider.py -v`
Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/llm.py tests/test_llm_provider.py
git commit -m "refactor: llm module to provider pattern with Claude CLI and OpenAI classes"
```

---

## Task 4: Image Provider Abstraction + Local FLUX Implementation

**Files:**
- Create: `app/local_image_gen.py`
- Modify: `app/asset_manager.py`
- Create: `tests/test_local_image_gen.py`

- [ ] **Step 1: Write tests for local image generator**

```python
# tests/test_local_image_gen.py
"""Tests for local FLUX image generation."""
import pytest
from unittest.mock import patch, MagicMock
from app.local_image_gen import LocalImageGenerator


@patch("app.local_image_gen.HAS_DIFFUSERS", True)
@patch("app.local_image_gen.FluxPipeline")
def test_generate_creates_image(mock_pipeline_cls, tmp_path):
    mock_pipe = MagicMock()
    mock_image = MagicMock()
    mock_pipe.return_value.images = [mock_image]
    mock_pipeline_cls.from_pretrained.return_value = mock_pipe

    gen = LocalImageGenerator.__new__(LocalImageGenerator)
    gen.pipe = mock_pipe
    gen.device = "cpu"

    output_path = str(tmp_path / "test.png")
    result = gen.generate("a sunset", 1080, 1920, output_path)
    assert result == output_path
    mock_image.save.assert_called_once_with(output_path)


@patch("app.local_image_gen.HAS_DIFFUSERS", True)
@patch("app.local_image_gen.FluxPipeline")
def test_generate_batch(mock_pipeline_cls, tmp_path):
    mock_pipe = MagicMock()
    mock_image = MagicMock()
    mock_pipe.return_value.images = [mock_image]
    mock_pipeline_cls.from_pretrained.return_value = mock_pipe

    gen = LocalImageGenerator.__new__(LocalImageGenerator)
    gen.pipe = mock_pipe
    gen.device = "cpu"

    results = gen.generate_batch(["cat", "dog"], 1080, 1920, str(tmp_path))
    assert len(results) == 2


def test_generate_without_diffusers():
    """Graceful error when diffusers not installed."""
    with patch("app.local_image_gen.HAS_DIFFUSERS", False):
        with pytest.raises(RuntimeError, match="diffusers"):
            LocalImageGenerator()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_local_image_gen.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement local image generator**

```python
# app/local_image_gen.py
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

    def generate(self, prompt: str, width: int, height: int,
                 output_path: str) -> str:
        """Generate a single image."""
        import torch
        logger.info("Generating image: %s", prompt[:80])
        result = self.pipe(
            prompt=prompt,
            width=width,
            height=height,
            num_inference_steps=4,  # schnell is fast with 4 steps
            guidance_scale=0.0,     # schnell doesn't use guidance
        )
        result.images[0].save(output_path)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_local_image_gen.py -v`
Expected: 3 tests PASS

- [ ] **Step 5: Update asset_manager.py with image provider routing**

In `app/asset_manager.py`, modify `generate_images()` to route based on `settings.image_provider`:

Add at top of file:
```python
from app.config import settings as app_settings
```

Replace the existing `generate_images` method body. After the mock-image early return, add local provider routing:

```python
    # After mock image handling, before Flux API call:
    if app_settings.image_provider == "local" or (
        app_settings.provider_mode == "local" and app_settings.image_provider != "replicate"
    ):
        return self._generate_images_local(prompts)
    # ... existing Flux API code ...
```

Add new method:
```python
    def _generate_images_local(self, prompts: list[str]) -> list[str]:
        """Generate images using local FLUX model."""
        from app.local_image_gen import LocalImageGenerator

        gen = LocalImageGenerator(model_id=app_settings.flux_local_model)
        try:
            enhanced = [self._enhance_prompt_with_style(p) for p in prompts]
            paths = gen.generate_batch(enhanced, 1080, 1920, self.temp_dir)
            return paths
        finally:
            gen.unload()
```

- [ ] **Step 6: Run all asset_manager tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_asset_manager.py tests/test_local_image_gen.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add app/local_image_gen.py app/asset_manager.py tests/test_local_image_gen.py
git commit -m "feat: add local FLUX image generation with provider routing"
```

---

## Task 5: Video Provider Abstraction + Local Wan2.1 Implementation

**Files:**
- Create: `app/local_video_gen.py`
- Modify: `app/motion_gen.py`
- Create: `tests/test_local_video_gen.py`

- [ ] **Step 1: Write tests for local video generator**

```python
# tests/test_local_video_gen.py
"""Tests for local Wan2.1 video generation."""
import pytest
from unittest.mock import patch, MagicMock
from app.local_video_gen import LocalVideoGenerator


@patch("app.local_video_gen.HAS_DIFFUSERS", True)
def test_generate_creates_video(tmp_path):
    gen = LocalVideoGenerator.__new__(LocalVideoGenerator)
    gen.pipe = MagicMock()
    gen.device = "cpu"
    gen.model_id = "test"

    # Mock the pipeline output
    import numpy as np
    mock_frames = [np.zeros((480, 720, 3), dtype=np.uint8)] * 16
    gen.pipe.return_value.frames = [mock_frames]

    with patch("app.local_video_gen.export_to_video") as mock_export:
        output_path = str(tmp_path / "test.mp4")
        result = gen.generate("/tmp/img.png", "zoom in slowly", output_path)
        assert result == output_path
        mock_export.assert_called_once()


def test_generate_without_diffusers():
    """Graceful error when diffusers not installed."""
    with patch("app.local_video_gen.HAS_DIFFUSERS", False):
        with pytest.raises(RuntimeError, match="diffusers"):
            LocalVideoGenerator()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_local_video_gen.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement local video generator**

```python
# app/local_video_gen.py
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

# Model IDs for Wan2.1
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
            self.model_id,
            torch_dtype=dtype,
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

        # Resize to model's expected resolution
        if self.model_size == "14b":
            image = image.resize((720, 1280))  # 720p vertical
        else:
            image = image.resize((480, 854))    # 480p vertical

        num_frames = int(duration * 16)  # ~16fps for Wan
        num_frames = min(max(num_frames, 16), 81)  # clamp to valid range

        output = self.pipe(
            image=image,
            prompt=prompt,
            num_frames=num_frames,
            guidance_scale=5.0,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_local_video_gen.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: Update motion_gen.py with provider routing**

In `app/motion_gen.py`, add local provider routing to `generate_motion_clip()`:

Add at top:
```python
from app.config import settings as app_settings
```

In `generate_motion_clip()`, before the Replicate API call, add:

```python
        if app_settings.motion_provider == "local" or (
            app_settings.provider_mode == "local" and app_settings.motion_provider != "replicate"
        ):
            return self._generate_local(image_path, motion_prompt, index)
```

Add new method:
```python
    def _generate_local(self, image_path: str, motion_prompt: str, index: int) -> str | None:
        """Generate motion clip using local Wan2.1 model."""
        from app.local_video_gen import LocalVideoGenerator
        output_path = os.path.join(self.output_dir, f"motion_{index:03d}.mp4")
        try:
            gen = LocalVideoGenerator(model_size=app_settings.wan_model_size)
            gen.generate(image_path, motion_prompt, output_path)
            gen.unload()
            return output_path
        except Exception as e:
            logger.warning("Local video gen failed for scene %d: %s", index, e)
            return None
```

- [ ] **Step 6: Run all motion_gen tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_motion_gen.py tests/test_local_video_gen.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add app/local_video_gen.py app/motion_gen.py tests/test_local_video_gen.py
git commit -m "feat: add local Wan2.1 video generation with provider routing"
```

---

## Task 6: Update Cost Tracker for Local Providers

**Files:**
- Modify: `app/cost_tracker.py`
- Modify: `tests/test_cost_tracker.py`

- [ ] **Step 1: Write test for local provider cost tracking**

Add to `tests/test_cost_tracker.py`:

```python
def test_local_provider_costs_are_zero():
    """Local providers should have $0.00 cost."""
    tracker = CostTracker()
    assert tracker.unit_costs["local_image"] == 0.0
    assert tracker.unit_costs["local_video"] == 0.0
    assert tracker.unit_costs["claude_cli"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cost_tracker.py::test_local_provider_costs_are_zero -v`
Expected: FAIL — KeyError: 'local_image'

- [ ] **Step 3: Add local provider entries to cost_tracker.py**

In `app/cost_tracker.py`, add to the `unit_costs` property dict:

```python
            "local_image": settings.cost_local_image,       # $0.00
            "local_video": settings.cost_local_video,       # $0.00
            "claude_cli": settings.cost_claude_cli,         # $0.00
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cost_tracker.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/cost_tracker.py tests/test_cost_tracker.py
git commit -m "feat: add zero-cost entries for local providers in cost tracker"
```

---

## Task 7: Update validate_config() for Optional API Keys

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update validate_config**

In `main.py`, replace the `validate_config()` function:

```python
def validate_config() -> bool:
    """Validate that required API keys are configured for selected providers."""
    errors = []

    # LLM: only need OpenAI key if using OpenAI provider
    if settings.llm_provider == "openai" or settings.provider_mode == "api":
        if not settings.openai_api_key:
            errors.append("OPENAI_API_KEY is required when llm_provider=openai")

    # Image: only need Replicate key if using Replicate provider
    if settings.image_provider == "replicate" or settings.provider_mode == "api":
        if not settings.replicate_api_token:
            errors.append("REPLICATE_API_TOKEN is required when image_provider=replicate")

    # Motion: only need Replicate key if using Replicate provider
    if settings.motion_provider == "replicate" or settings.provider_mode == "api":
        if not settings.replicate_api_token:
            errors.append("REPLICATE_API_TOKEN is required when motion_provider=replicate")

    # TTS: always needs at least one TTS key
    if not settings.elevenlabs_api_key and not settings.openai_api_key:
        errors.append("ELEVENLABS_API_KEY or OPENAI_API_KEY required for audio")

    if errors:
        for error in errors:
            logger.error(error)
        return False

    return True
```

- [ ] **Step 2: Add --local, --api, --serve CLI flags to parse_args()**

In the `parse_args()` function, add:

```python
    parser.add_argument("--local", action="store_true",
                        help="Use all local models (no API calls for LLM/image/video)")
    parser.add_argument("--api", action="store_true",
                        help="Use all API models (original behavior)")
    parser.add_argument("--serve", action="store_true",
                        help="Start the FastAPI web server")
```

In the main block, after parsing args, add provider mode handling:

```python
    if args.local:
        settings.provider_mode = "local"
    elif args.api:
        settings.provider_mode = "api"
```

- [ ] **Step 3: Run existing CLI tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_cli.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: update config validation for optional API keys, add --local/--api/--serve flags"
```

---

## Task 8: Update requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add new dependencies**

Append to `requirements.txt`:

```
# === V3: Local models + Web server ===
diffusers>=0.32.0
transformers>=4.47.0
accelerate>=1.2.0
safetensors>=0.4.0
# Web server
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
websockets>=14.0
# Scheduler
apscheduler>=3.10.0,<4.0
# Database
aiosqlite>=0.20.0
```

- [ ] **Step 2: Install dependencies**

Run: `cd /Users/moganes/Projects/FVFactory && pip install -r requirements.txt`
Expected: All packages install successfully

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "feat: add v3 dependencies — diffusers, fastapi, apscheduler"
```

---

## Task 9: FastAPI Server Core

**Files:**
- Create: `app/web/__init__.py`
- Create: `app/web/server.py`
- Create: `app/web/ws.py`
- Create: `app/web/routes/__init__.py`

- [ ] **Step 1: Create package init files**

```python
# app/web/__init__.py
# app/web/routes/__init__.py
```

(Both empty)

- [ ] **Step 2: Create WebSocket manager**

```python
# app/web/ws.py
"""WebSocket manager for real-time progress broadcasting."""

import json
import logging
from datetime import datetime, timezone
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self.connections))

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)
        logger.info("WebSocket client disconnected (%d total)", len(self.connections))

    async def broadcast(self, message: dict):
        """Send message to all connected clients."""
        message["timestamp"] = datetime.now(timezone.utc).isoformat()
        data = json.dumps(message)
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)

    async def send_progress(self, job_id: str, stage: str, progress: float, message: str):
        """Send a progress update."""
        await self.broadcast({
            "type": "progress",
            "job_id": job_id,
            "stage": stage,
            "progress": progress,
            "message": message,
        })

    async def send_complete(self, job_id: str, result: dict | None = None):
        await self.broadcast({"type": "complete", "job_id": job_id, "result": result})

    async def send_error(self, job_id: str, error: str):
        await self.broadcast({"type": "error", "job_id": job_id, "error": error})


# Global instance
ws_manager = WSManager()
```

- [ ] **Step 3: Create FastAPI server**

```python
# app/web/server.py
"""FastAPI application server for FVFactory."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.web.ws import ws_manager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR = Path("data")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Server startup and shutdown."""
    DATA_DIR.mkdir(exist_ok=True)
    logger.info("FVFactory server starting...")
    yield
    logger.info("FVFactory server shutting down...")


app = FastAPI(title="FVFactory", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# Import and register API routes
from app.web.routes.api_config import router as config_router
from app.web.routes.api_library import router as library_router
from app.web.routes.api_generate import router as generate_router
from app.web.routes.api_scheduler import router as scheduler_router

app.include_router(config_router, prefix="/api")
app.include_router(library_router, prefix="/api")
app.include_router(generate_router, prefix="/api")
app.include_router(scheduler_router, prefix="/api")

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# SPA catch-all: serve index.html for all non-API, non-static paths
@app.get("/{path:path}")
async def spa_catchall(path: str):
    # Serve actual static files directly
    file_path = STATIC_DIR / path
    if file_path.is_file():
        return FileResponse(file_path)
    # Everything else gets the SPA shell
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


def start_server(host: str = "0.0.0.0", port: int = 8000):
    """Start the server and open browser."""
    import webbrowser
    webbrowser.open(f"http://localhost:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_server()
```

- [ ] **Step 4: Create stub route files**

```python
# app/web/routes/api_config.py
"""Configuration API endpoints."""
import json
import logging
from pathlib import Path
from fastapi import APIRouter

from app.config import settings

router = APIRouter()
CONFIG_PATH = Path("data/config.json")

logger = logging.getLogger(__name__)


def _load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def _save_config(config: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


@router.get("/config")
async def get_config():
    """Get all current configuration."""
    saved = _load_config()
    # Merge saved config with current settings
    current = {
        "provider_mode": settings.provider_mode,
        "llm_provider": settings.llm_provider,
        "image_provider": settings.image_provider,
        "motion_provider": settings.motion_provider,
        "wan_model_size": settings.wan_model_size,
        "flux_local_model": settings.flux_local_model,
        "claude_cli_timeout": settings.claude_cli_timeout,
        "niche": settings.niche,
        "subtitle_style": settings.subtitle_style,
        "enable_motion": settings.enable_motion,
        "enable_sfx": settings.enable_sfx,
        "music_enabled": settings.music_enabled,
        "music_volume": settings.music_volume,
        "elevenlabs_voice_id": settings.elevenlabs_voice_id,
        "output_dir": settings.output_dir,
        "youtube_privacy": settings.youtube_privacy,
        # Masked API keys (show presence, not values)
        "has_openai_key": bool(settings.openai_api_key),
        "has_elevenlabs_key": bool(settings.elevenlabs_api_key),
        "has_replicate_key": bool(settings.replicate_api_token),
        "has_youtube_key": bool(settings.youtube_api_key),
    }
    current.update(saved)
    return current


@router.put("/config")
async def update_config(updates: dict):
    """Update configuration (partial merge)."""
    config = _load_config()
    config.update(updates)
    _save_config(config)
    # Apply to running settings
    for key, value in updates.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return {"status": "ok", "config": config}


@router.post("/config/reset")
async def reset_config():
    """Reset to defaults."""
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
    return {"status": "ok"}
```

```python
# app/web/routes/api_library.py
"""Library API endpoints."""
import json
import os
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter()


@router.get("/library")
async def list_videos():
    """List all generated videos with metadata."""
    output_dir = Path(settings.output_dir)
    videos = []

    if not output_dir.exists():
        return {"videos": []}

    # Find all MP4 files
    for mp4 in sorted(output_dir.glob("*.mp4"), reverse=True):
        video_id = mp4.stem
        meta_path = output_dir / "metadata" / f"{video_id}.json"
        thumb_path = output_dir / "thumbnails" / f"{video_id}.png"

        entry = {
            "id": video_id,
            "filename": mp4.name,
            "created": os.path.getmtime(str(mp4)),
            "size_mb": round(mp4.stat().st_size / 1024 / 1024, 1),
            "has_thumbnail": thumb_path.exists(),
            "metadata": None,
        }

        if meta_path.exists():
            try:
                entry["metadata"] = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                pass

        videos.append(entry)

    return {"videos": videos}


@router.get("/library/{video_id}/video")
async def get_video(video_id: str):
    """Stream a video file."""
    path = Path(settings.output_dir) / f"{video_id}.mp4"
    if not path.exists():
        return {"error": "Video not found"}, 404
    return FileResponse(path, media_type="video/mp4")


@router.get("/library/{video_id}/thumbnail")
async def get_thumbnail(video_id: str):
    """Get video thumbnail."""
    path = Path(settings.output_dir) / "thumbnails" / f"{video_id}.png"
    if not path.exists():
        return {"error": "Thumbnail not found"}, 404
    return FileResponse(path, media_type="image/png")
```

```python
# app/web/routes/api_generate.py
"""Video generation API endpoints."""
import asyncio
import logging
import uuid
from fastapi import APIRouter
from pydantic import BaseModel

from app.web.ws import ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    topic: str = ""
    niche: str = ""
    voice: str = "auto"
    subtitle_style: str = "bold_impact"
    enable_motion: bool = True
    enable_sfx: bool = True
    enable_music: bool = True
    use_mock: bool = False
    auto_topic: bool = False


class GenerateResponse(BaseModel):
    job_id: str
    status: str


@router.post("/generate")
async def generate_video(req: GenerateRequest) -> GenerateResponse:
    """Start an on-demand video generation job."""
    job_id = str(uuid.uuid4())[:8]

    async def _run():
        try:
            await ws_manager.send_progress(job_id, "starting", 0.0, "Starting pipeline...")
            # Import here to avoid circular imports
            from main import run_pipeline, resolve_voice
            from app.config import settings
            from app.trend_scout import TrendScout

            topic = req.topic
            if req.auto_topic or not topic:
                scout = TrendScout()
                topics = scout.discover_topics(niche=req.niche, count=1)
                if topics:
                    topic = topics[0].title
                else:
                    topic = "Interesting facts about the world"

            voice_id = resolve_voice(req.voice, req.niche)

            await ws_manager.send_progress(job_id, "script", 0.1, f"Topic: {topic}")

            # Run blocking pipeline in thread
            result = await asyncio.to_thread(
                run_pipeline,
                topic=topic,
                use_mock_images=req.use_mock,
                enable_motion=req.enable_motion,
                subtitle_style=req.subtitle_style,
                enable_sfx=req.enable_sfx,
                voice=voice_id,
                niche=req.niche,
            )

            await ws_manager.send_complete(job_id, {"video_id": result} if result else None)
        except Exception as e:
            logger.exception("Generation failed for job %s", job_id)
            await ws_manager.send_error(job_id, str(e))

    asyncio.create_task(_run())
    return GenerateResponse(job_id=job_id, status="started")
```

```python
# app/web/routes/api_scheduler.py
"""Scheduler API endpoints."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class JobCreate(BaseModel):
    name: str
    cron_expression: str
    enabled: bool = True
    config: dict = {}


class JobUpdate(BaseModel):
    name: str | None = None
    cron_expression: str | None = None
    enabled: bool | None = None
    config: dict | None = None


@router.get("/scheduler/jobs")
async def list_jobs():
    """List all scheduled jobs."""
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    return {"jobs": scheduler.list_jobs()}


@router.post("/scheduler/jobs")
async def create_job(req: JobCreate):
    """Create a new scheduled job."""
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.add_job(req.name, req.cron_expression, req.config, req.enabled)
    return job


@router.get("/scheduler/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job details."""
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.put("/scheduler/jobs/{job_id}")
async def update_job(job_id: str, req: JobUpdate):
    """Update a scheduled job."""
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    job = scheduler.update_job(job_id, req.model_dump(exclude_none=True))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/scheduler/jobs/{job_id}")
async def delete_job(job_id: str):
    """Delete a scheduled job."""
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    if not scheduler.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "deleted"}


@router.post("/scheduler/jobs/{job_id}/run")
async def run_job_now(job_id: str):
    """Trigger immediate execution of a job."""
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    if not scheduler.run_now(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "triggered"}


@router.get("/scheduler/history")
async def job_history():
    """Get job execution history."""
    from app.scheduler import get_scheduler
    scheduler = get_scheduler()
    return {"history": scheduler.get_history()}
```

- [ ] **Step 5: Write basic server test**

```python
# tests/test_web_api.py
"""Tests for FastAPI web server."""
import pytest
from fastapi.testclient import TestClient
from app.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_root_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_config_endpoint(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "provider_mode" in data


def test_library_endpoint(client):
    resp = client.get("/api/library")
    assert resp.status_code == 200
    assert "videos" in resp.json()


def test_scheduler_jobs_endpoint(client):
    resp = client.get("/api/scheduler/jobs")
    assert resp.status_code == 200
    assert "jobs" in resp.json()
```

- [ ] **Step 6: Commit**

```bash
git add app/web/ tests/test_web_api.py
git commit -m "feat: add FastAPI server with config, library, generate, scheduler API routes"
```

---

## Task 10: Scheduler Implementation

**Files:**
- Create: `app/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write scheduler tests**

```python
# tests/test_scheduler.py
"""Tests for APScheduler integration."""
import pytest
import os
from app.scheduler import FVScheduler


@pytest.fixture
def scheduler(tmp_path):
    db_path = str(tmp_path / "test_scheduler.db")
    s = FVScheduler(db_path=db_path)
    s.start()
    yield s
    s.shutdown()


def test_add_and_list_jobs(scheduler):
    job = scheduler.add_job("Test Job", "0 9 * * *", {"niche": "tech"})
    assert job["name"] == "Test Job"
    jobs = scheduler.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "Test Job"


def test_delete_job(scheduler):
    job = scheduler.add_job("Delete Me", "0 9 * * *", {})
    assert scheduler.delete_job(job["id"])
    assert len(scheduler.list_jobs()) == 0


def test_update_job(scheduler):
    job = scheduler.add_job("Update Me", "0 9 * * *", {})
    updated = scheduler.update_job(job["id"], {"enabled": False})
    assert updated["enabled"] is False


def test_get_history_empty(scheduler):
    history = scheduler.get_history()
    assert history == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement scheduler**

```python
# app/scheduler.py
"""Job scheduler using APScheduler with SQLite persistence."""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_scheduler_instance = None


class FVScheduler:
    """Manages scheduled video generation jobs."""

    def __init__(self, db_path: str = "data/scheduler.db"):
        self.db_path = db_path
        self._init_db()
        self.scheduler = BackgroundScheduler(
            executors={"default": ThreadPoolExecutor(1)},
            job_defaults={"coalesce": True, "max_instances": 1},
        )

    def _init_db(self):
        """Initialize SQLite database with WAL mode."""
        import os
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                config TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT DEFAULT 'running',
                output_path TEXT,
                error TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
        """)
        conn.commit()
        conn.close()

    def start(self):
        """Start the scheduler and load persisted jobs."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs WHERE enabled = 1").fetchall()
        conn.close()

        for row in rows:
            self._schedule_job(dict(row))

        if not self.scheduler.running:
            self.scheduler.start()
        logger.info("Scheduler started with %d active jobs", len(rows))

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _schedule_job(self, job: dict):
        """Add a job to APScheduler."""
        try:
            trigger = CronTrigger.from_crontab(job["cron_expression"])
            self.scheduler.add_job(
                self._run_job, trigger,
                id=job["id"], args=[job["id"]],
                replace_existing=True,
            )
        except Exception as e:
            logger.error("Failed to schedule job %s: %s", job["id"], e)

    def _run_job(self, job_id: str):
        """Execute a video generation job."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            conn.close()
            return

        config = json.loads(row["config"])
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO job_runs (job_id, started_at, status) VALUES (?, ?, 'running')",
            (job_id, now),
        )
        conn.commit()
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        try:
            from main import run_pipeline, resolve_voice
            topic = config.get("topic", "")
            niche = config.get("niche", "")
            voice = resolve_voice(config.get("voice", "auto"), niche)

            if not topic:
                from app.trend_scout import TrendScout
                scout = TrendScout()
                topics = scout.discover_topics(niche=niche, count=1)
                topic = topics[0].title if topics else "Interesting facts"

            result = run_pipeline(
                topic=topic,
                niche=niche,
                voice=voice,
                enable_motion=config.get("enable_motion", True),
                subtitle_style=config.get("subtitle_style", "bold_impact"),
                enable_sfx=config.get("enable_sfx", True),
            )

            finished = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE job_runs SET status='success', finished_at=?, output_path=? WHERE id=?",
                (finished, result, run_id),
            )
            logger.info("Job %s completed: %s", job_id, result)
        except Exception as e:
            finished = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE job_runs SET status='failed', finished_at=?, error=? WHERE id=?",
                (finished, str(e), run_id),
            )
            logger.exception("Job %s failed", job_id)
        finally:
            conn.commit()
            conn.close()

    def add_job(self, name: str, cron_expression: str, config: dict,
                enabled: bool = True) -> dict:
        """Create a new scheduled job."""
        job_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO jobs (id, name, cron_expression, enabled, config, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, name, cron_expression, int(enabled), json.dumps(config), now),
        )
        conn.commit()
        conn.close()

        job = {"id": job_id, "name": name, "cron_expression": cron_expression,
               "enabled": enabled, "config": config, "created_at": now}

        if enabled and self.scheduler.running:
            self._schedule_job(job)

        return job

    def list_jobs(self) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        conn.close()

        jobs = []
        for row in rows:
            job = dict(row)
            job["enabled"] = bool(job["enabled"])
            job["config"] = json.loads(job["config"])
            # Get next run time from APScheduler
            ap_job = self.scheduler.get_job(job["id"]) if self.scheduler.running else None
            job["next_run"] = str(ap_job.next_run_time) if ap_job else None
            # Get last run
            conn2 = sqlite3.connect(self.db_path)
            conn2.row_factory = sqlite3.Row
            last = conn2.execute(
                "SELECT * FROM job_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT 1",
                (job["id"],)
            ).fetchone()
            conn2.close()
            job["last_run"] = dict(last) if last else None
            jobs.append(job)

        return jobs

    def get_job(self, job_id: str) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        if not row:
            return None
        job = dict(row)
        job["enabled"] = bool(job["enabled"])
        job["config"] = json.loads(job["config"])
        return job

    def update_job(self, job_id: str, updates: dict) -> dict | None:
        job = self.get_job(job_id)
        if not job:
            return None

        conn = sqlite3.connect(self.db_path)
        if "name" in updates:
            conn.execute("UPDATE jobs SET name = ? WHERE id = ?", (updates["name"], job_id))
        if "cron_expression" in updates:
            conn.execute("UPDATE jobs SET cron_expression = ? WHERE id = ?", (updates["cron_expression"], job_id))
        if "enabled" in updates:
            conn.execute("UPDATE jobs SET enabled = ? WHERE id = ?", (int(updates["enabled"]), job_id))
        if "config" in updates:
            conn.execute("UPDATE jobs SET config = ? WHERE id = ?", (json.dumps(updates["config"]), job_id))
        conn.commit()
        conn.close()

        # Reschedule
        updated = self.get_job(job_id)
        if self.scheduler.running:
            existing = self.scheduler.get_job(job_id)
            if existing:
                self.scheduler.remove_job(job_id)
            if updated["enabled"]:
                self._schedule_job(updated)

        return updated

    def delete_job(self, job_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.execute("DELETE FROM job_runs WHERE job_id = ?", (job_id,))
        conn.commit()
        conn.close()

        if self.scheduler.running:
            existing = self.scheduler.get_job(job_id)
            if existing:
                self.scheduler.remove_job(job_id)

        return cursor.rowcount > 0

    def run_now(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        import threading
        threading.Thread(target=self._run_job, args=(job_id,), daemon=True).start()
        return True

    def get_history(self, limit: int = 50) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT r.*, j.name as job_name FROM job_runs r LEFT JOIN jobs j ON r.job_id = j.id "
            "ORDER BY r.started_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_scheduler() -> FVScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = FVScheduler()
        _scheduler_instance.start()
    return _scheduler_instance
```

- [ ] **Step 4: Run scheduler tests**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/test_scheduler.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: add APScheduler-based job scheduler with SQLite persistence"
```

---

## Task 11: Frontend SPA — HTML Shell + CSS Design System

**Files:**
- Create: `app/web/static/index.html`
- Create: `app/web/static/css/tokens.css`
- Create: `app/web/static/css/styles.css`

- [ ] **Step 1: Create design tokens**

Create `app/web/static/css/tokens.css` — dark theme color palette, typography, spacing scale. Use CSS custom properties.

Key tokens:
- Background: `#0a0a0f` (deep dark), `#12121a` (card), `#1a1a2e` (surface)
- Accent: `#00e5ff` (cyan), `#7c3aed` (purple), `#10b981` (green)
- Text: `#f0f0f5` (primary), `#9ca3af` (secondary), `#6b7280` (muted)
- Font: `"Inter", system-ui, sans-serif`
- Mono: `"JetBrains Mono", "Fira Code", monospace`

- [ ] **Step 2: Create main stylesheet**

Create `app/web/static/css/styles.css` — layout (sidebar + main), components (cards, buttons, forms, modals, tables, progress bars, toggles), responsive breakpoints.

- [ ] **Step 3: Create SPA shell**

Create `app/web/static/index.html`:
- HTML5 with dark theme meta
- Sidebar navigation with icons (SVG inline)
- Main content area with `<div id="app"></div>`
- Script tags loading all JS modules
- Links to CSS files

- [ ] **Step 4: Verify static files serve**

Run: `cd /Users/moganes/Projects/FVFactory && python -c "from app.web.server import app; print('Server imports OK')"`
Expected: "Server imports OK"

- [ ] **Step 5: Commit**

```bash
git add app/web/static/
git commit -m "feat: add SPA shell with dark theme design system"
```

---

## Task 12: Frontend JS — Router + WebSocket + Dashboard

**Files:**
- Create: `app/web/static/js/app.js`
- Create: `app/web/static/js/ws.js`
- Create: `app/web/static/js/dashboard.js`

- [ ] **Step 1: Create SPA router**

`app/web/static/js/app.js`:
- History API based router
- Route registration: `{path, title, render(container)}`
- Routes: `/` (dashboard), `/generate`, `/library`, `/scheduler`, `/settings`
- Navigation click handler (intercept `<a>` clicks)
- Active nav item highlighting
- Global state object for sharing data between pages

- [ ] **Step 2: Create WebSocket client**

`app/web/static/js/ws.js`:
- Auto-connect to `ws://localhost:8000/ws`
- Auto-reconnect with exponential backoff
- Event listener registration: `ws.on("progress", callback)`
- Parse JSON messages, dispatch to registered handlers

- [ ] **Step 3: Create dashboard page**

`app/web/static/js/dashboard.js`:
- Fetch `/api/library` for video count and recent videos
- Fetch `/api/scheduler/jobs` for active jobs
- Overview cards: total videos, active schedules, provider mode
- Recent videos list (last 5)
- Active job status (if any running)
- Quick action buttons: "Generate Now" → navigates to /generate

- [ ] **Step 4: Test manually**

Run: `cd /Users/moganes/Projects/FVFactory && python -m app.web.server`
Open `http://localhost:8000` — verify dashboard loads with sidebar navigation.

- [ ] **Step 5: Commit**

```bash
git add app/web/static/js/
git commit -m "feat: add SPA router, WebSocket client, and dashboard page"
```

---

## Task 13: Frontend JS — Generate Page

**Files:**
- Create: `app/web/static/js/generate.js`

- [ ] **Step 1: Build generate page**

`app/web/static/js/generate.js`:
- Form fields: topic (text input), niche (dropdown), voice (dropdown), scene count (slider)
- Toggle switches: motion, SFX, music, auto-topic
- Subtitle style picker (visual cards for each style)
- Provider overrides section (expandable): image provider, motion provider, LLM provider
- "Generate" button
- Progress panel (hidden until generation starts):
  - Stage indicator (script → images → audio → motion → assembly)
  - Progress bar per stage
  - Live log output area
  - Uses WebSocket for real-time updates
- POST to `/api/generate` on submit
- Voice dropdown populated from config voice_presets

- [ ] **Step 2: Test manually**

Run server, navigate to `/generate`, fill in topic, click Generate. Verify WebSocket progress appears.

- [ ] **Step 3: Commit**

```bash
git add app/web/static/js/generate.js
git commit -m "feat: add generate page with form and real-time progress"
```

---

## Task 14: Frontend JS — Library Page

**Files:**
- Create: `app/web/static/js/library.js`

- [ ] **Step 1: Build library page**

`app/web/static/js/library.js`:
- Fetch `/api/library` on load
- Grid view: video cards with thumbnail, title, date, niche badge, duration
- Filter bar: date range, niche dropdown, search text
- Click card → detail view:
  - Video player (`<video>` tag, src from `/api/library/{id}/video`)
  - Metadata panel: title, description, hashtags, best posting time
  - Cost breakdown
  - Creation date and generation settings used
- Empty state when no videos

- [ ] **Step 2: Test manually**

Run server, navigate to `/library`. Verify grid shows existing videos from `output/`.

- [ ] **Step 3: Commit**

```bash
git add app/web/static/js/library.js
git commit -m "feat: add library page with video grid and detail view"
```

---

## Task 15: Frontend JS — Scheduler Page

**Files:**
- Create: `app/web/static/js/scheduler.js`

- [ ] **Step 1: Build scheduler page**

`app/web/static/js/scheduler.js`:
- Job list table: name, schedule (human-readable), enabled toggle, last run, next run, actions
- "New Job" button → modal form:
  - Name input
  - Schedule presets: "Every day at 9am", "Twice daily (9am, 6pm)", "Weekdays only", "Every 6 hours"
  - Custom cron input (collapsible, for power users)
  - Video config: niche, voice, motion toggle, subtitle style
  - Save/Cancel buttons
- Edit existing job (same modal, pre-filled)
- Delete job (confirm dialog)
- "Run Now" button per job
- Job history section: table with date, job name, status (success/failed), duration, output
- Enable/disable toggle updates via PUT `/api/scheduler/jobs/{id}`

- [ ] **Step 2: Test manually**

Run server, navigate to `/scheduler`. Create a job, verify it appears in the list.

- [ ] **Step 3: Commit**

```bash
git add app/web/static/js/scheduler.js
git commit -m "feat: add scheduler page with job management and cron builder"
```

---

## Task 16: Frontend JS — Settings Page

**Files:**
- Create: `app/web/static/js/settings.js`

- [ ] **Step 1: Build settings page**

`app/web/static/js/settings.js`:
- Fetch `/api/config` on load, populate all fields
- Grouped sections (collapsible):
  - **Providers**: provider_mode toggle (local/api/mixed), individual provider dropdowns
  - **Generation Defaults**: niche, subtitle style, scene count, motion/SFX/music toggles
  - **Model Settings**: Wan model size (1.3b/14b), FLUX model, Whisper size, CLI timeout
  - **API Keys**: masked inputs showing key presence, update fields
  - **Output**: output directory, video resolution
  - **System**: model cache info, memory usage (if available)
- Save button → PUT `/api/config` with changed fields only
- Reset to defaults button → POST `/api/config/reset`
- Toast notification on save success/failure

- [ ] **Step 2: Test manually**

Run server, navigate to `/settings`. Change provider_mode, click save. Refresh — verify setting persisted.

- [ ] **Step 3: Commit**

```bash
git add app/web/static/js/settings.js
git commit -m "feat: add settings page with full configuration management"
```

---

## Task 17: Wire --serve Flag + Remove Streamlit

**Files:**
- Modify: `main.py`
- Delete: `app/dashboard.py`
- Delete: `app/library.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add --serve handler in main.py**

In the `if __name__ == "__main__"` block, after arg parsing:

```python
    if args.serve:
        from app.web.server import start_server
        start_server()
        sys.exit(0)
```

- [ ] **Step 2: Remove streamlit from requirements.txt**

Remove the `streamlit` line from `requirements.txt`.

- [ ] **Step 3: Delete old Streamlit files**

```bash
rm app/dashboard.py app/library.py
```

- [ ] **Step 4: Run existing tests to check nothing breaks**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/ -v --ignore=tests/test_web_api.py`
Expected: All existing tests PASS (none depend on dashboard.py or library.py)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: add --serve flag, remove Streamlit UI in favor of FastAPI SPA"
```

---

## Task 18: Integration Testing

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/moganes/Projects/FVFactory && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Test server startup**

Run: `cd /Users/moganes/Projects/FVFactory && timeout 5 python -m app.web.server || true`
Expected: Server starts, binds to port 8000, no import errors

- [ ] **Step 3: Test local image generation (manual, requires model download)**

```bash
cd /Users/moganes/Projects/FVFactory
python -c "
from app.local_image_gen import LocalImageGenerator
gen = LocalImageGenerator()
gen.generate('A beautiful sunset over mountains, photorealistic', 1080, 1920, '/tmp/test_flux.png')
gen.unload()
print('Image generation OK')
"
```

- [ ] **Step 4: Test local video generation (manual, requires model download)**

```bash
cd /Users/moganes/Projects/FVFactory
python -c "
from app.local_video_gen import LocalVideoGenerator
gen = LocalVideoGenerator(model_size='1.3b')
gen.generate('/tmp/test_flux.png', 'slow zoom in with clouds moving', '/tmp/test_wan.mp4')
gen.unload()
print('Video generation OK')
"
```

- [ ] **Step 5: Test full pipeline with local providers**

```bash
cd /Users/moganes/Projects/FVFactory
python main.py --auto --niche tech --local --no-sfx --no-music
```

- [ ] **Step 6: Test web UI end-to-end**

```bash
cd /Users/moganes/Projects/FVFactory
python main.py --serve
```

Open browser, verify: dashboard loads → generate a video → see it in library → create a schedule → check settings.

- [ ] **Step 7: Commit any fixes**

```bash
git add -A
git commit -m "fix: integration test fixes"
```
