# On-Demand Video Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add on-demand video generation to the Streamlit library UI so users can generate videos from the browser without SSH.

**Architecture:** Add a "Generate" tab to the library UI with a form (topic, niche, voice, options). On submit, run `run_pipeline()` in a background thread and stream logs to the UI. The library container already has all dependencies — no new services needed.

**Tech Stack:** Streamlit, Python threading, existing `run_pipeline()` from main.py

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `app/library.py` | Modify | Add navigation (Library / Generate), render generate form, show generation status |
| `app/generator_worker.py` | Create | Background worker that runs `run_pipeline()` in a thread, captures logs, reports status |
| `tests/test_generator_worker.py` | Create | Tests for worker state management and log capture |
| `docker-compose.yml` | Modify | Ensure library container has write access to output/ and assets/temp/ |

---

### Task 1: Create generator_worker.py — background pipeline runner

**Files:**
- Create: `app/generator_worker.py`
- Create: `tests/test_generator_worker.py`

- [ ] **Step 1: Write failing tests for GeneratorWorker**

```python
# tests/test_generator_worker.py
"""Tests for background video generation worker."""
import time
from unittest.mock import patch, MagicMock
from app.generator_worker import GeneratorWorker


def test_worker_initial_state():
    w = GeneratorWorker()
    assert w.status == "idle"
    assert w.logs == []
    assert w.result is None
    assert w.error is None


def test_worker_is_busy_while_running():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline") as mock_pipe:
        mock_pipe.side_effect = lambda **kw: time.sleep(0.5)
        w.start(topic="Test", niche="stoicism")
        assert w.status == "running"
        w._thread.join()


def test_worker_captures_result():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/test.mp4"):
        w.start(topic="Test", niche="stoicism")
        w._thread.join()
        assert w.status == "done"
        assert w.result == "/output/test.mp4"


def test_worker_captures_error():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", side_effect=Exception("boom")):
        w.start(topic="Test", niche="stoicism")
        w._thread.join()
        assert w.status == "error"
        assert "boom" in w.error


def test_worker_rejects_while_busy():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline") as mock_pipe:
        mock_pipe.side_effect = lambda **kw: time.sleep(1)
        w.start(topic="A")
        ok = w.start(topic="B")
        assert ok is False
        w._thread.join()


def test_worker_reset():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/test.mp4"):
        w.start(topic="Test")
        w._thread.join()
        w.reset()
        assert w.status == "idle"
        assert w.logs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_generator_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.generator_worker'`

- [ ] **Step 3: Implement GeneratorWorker**

```python
# app/generator_worker.py
"""Background worker for on-demand video generation."""

import logging
import threading
from typing import Optional

from main import run_pipeline, resolve_voice


class _LogCapture(logging.Handler):
    """Captures log records into a list."""
    def __init__(self, target: list):
        super().__init__()
        self.target = target

    def emit(self, record):
        self.target.append(self.format(record))


class GeneratorWorker:
    """Runs run_pipeline() in a background thread with log capture."""

    def __init__(self):
        self.status: str = "idle"  # idle, running, done, error
        self.logs: list[str] = []
        self.result: Optional[str] = None
        self.error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._kwargs: dict = {}

    def start(self, topic: str, niche: str = "", voice: str = "bill",
              subtitle_style: str = "bold_impact",
              enable_motion: bool = True) -> bool:
        """Start generation. Returns False if already busy."""
        if self.status == "running":
            return False

        self.status = "running"
        self.logs = []
        self.result = None
        self.error = None

        voice_id = resolve_voice(voice, niche=niche) if voice else None

        self._kwargs = dict(
            topic=topic,
            enable_motion=enable_motion,
            subtitle_style=subtitle_style,
            enable_sfx=False,
            voice=voice_id,
            niche=niche or None,
        )

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def _run(self):
        handler = _LogCapture(self.logs)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)

        try:
            self.result = run_pipeline(**self._kwargs)
            self.status = "done"
        except Exception as e:
            self.error = str(e)
            self.status = "error"
        finally:
            root_logger.removeHandler(handler)

    def reset(self):
        """Reset to idle state."""
        if self.status != "running":
            self.status = "idle"
            self.logs = []
            self.result = None
            self.error = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_generator_worker.py -v`
Expected: All 6 PASS

- [ ] **Step 5: Commit**

```bash
git add app/generator_worker.py tests/test_generator_worker.py
git commit -m "feat: add background generator worker for on-demand video generation"
```

---

### Task 2: Add Generate page to library UI

**Files:**
- Modify: `app/library.py`

- [ ] **Step 1: Add navigation state and topbar tabs**

In `library.py`, update session state init in `main()` to add a `page` variable, and update `render_topbar()` to show Library / Generate navigation. Add the generate form render function.

Key changes to `main()`:
```python
def main():
    if "selected_video" not in st.session_state:
        st.session_state.selected_video = None
    if "page" not in st.session_state:
        st.session_state.page = "library"
    if "worker" not in st.session_state:
        st.session_state.worker = GeneratorWorker()

    videos = scan_videos()
    costs = load_costs()

    render_topbar()

    if st.session_state.page == "generate":
        render_generate_page()
    elif not videos:
        # empty state
    elif st.session_state.selected_video:
        render_detail(video, costs)
    else:
        render_grid(videos, costs)
```

Update `render_topbar()` to include clickable Library/Generate nav buttons.

- [ ] **Step 2: Implement render_generate_page()**

Add a function that renders:
- Topic input (text field, or "Auto" checkbox to use niche topic generation)
- Niche selector (stoicism, self-improvement, philosophy, motivation, psychology, custom)
- Voice selector (bill, george, daniel, josh, rachel)
- Motion clips toggle
- "Generate" button
- While running: show live log output with `st.status()` and auto-refresh
- On completion: show success with link to view in library
- On error: show error message with retry button

```python
def render_generate_page():
    st.markdown('<div class="detail-title">Generate Video</div>', unsafe_allow_html=True)

    worker = st.session_state.worker

    if worker.status == "running":
        render_generation_progress(worker)
        return

    if worker.status == "done":
        render_generation_complete(worker)
        return

    if worker.status == "error":
        render_generation_error(worker)
        return

    # Form
    auto_topic = st.checkbox("Auto-generate topic from niche", value=True)

    if auto_topic:
        topic = ""
    else:
        topic = st.text_input("Topic", placeholder="e.g., Why the Roman Empire Really Fell")

    niche = st.selectbox("Niche", ["stoicism", "self-improvement", "philosophy", "motivation", "psychology"])
    voice = st.selectbox("Voice", ["bill", "george", "daniel", "josh", "rachel"])
    motion = st.checkbox("Motion clips", value=True)

    can_generate = auto_topic or bool(topic.strip())

    if st.button("Generate Video", type="primary", disabled=not can_generate, use_container_width=True):
        if auto_topic:
            scout = TrendScout()
            topics = scout.discover_topics(niche=niche, count=1)
            topic = topics[0].title if topics else f"{niche} insights"

        worker.start(topic=topic, niche=niche, voice=voice, enable_motion=motion)
        st.rerun()
```

- [ ] **Step 3: Implement progress, complete, and error views**

```python
def render_generation_progress(worker):
    st.info(f"Generating video... ({len(worker.logs)} steps completed)")
    with st.container(height=400):
        st.code("\n".join(worker.logs[-30:]), language=None)
    time.sleep(2)
    st.rerun()

def render_generation_complete(worker):
    st.success(f"Video generated: {worker.result}")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("View in Library", use_container_width=True):
            worker.reset()
            st.session_state.page = "library"
            st.rerun()
    with c2:
        if st.button("Generate Another", use_container_width=True):
            worker.reset()
            st.rerun()

def render_generation_error(worker):
    st.error(f"Generation failed: {worker.error}")
    if st.button("Try Again", use_container_width=True):
        worker.reset()
        st.rerun()
```

- [ ] **Step 4: Test manually**

Run: `streamlit run app/library.py`
Verify: Navigate to Generate tab, fill in form, click Generate, see logs streaming, see completion.

- [ ] **Step 5: Commit**

```bash
git add app/library.py
git commit -m "feat: add on-demand video generation page to library UI"
```

---

### Task 3: Deploy to VPS

**Files:**
- Modify: None (rsync + docker rebuild)

- [ ] **Step 1: Sync files to VPS**

```bash
rsync -avz --exclude='.venv/' --exclude='.git/' --exclude='__pycache__/' --exclude='.env' \
  --exclude='client_secrets.json' --exclude='youtube_token.json' \
  --exclude='output/*.mp4' --exclude='output/thumbnails/' --exclude='output/metadata/' \
  --exclude='output/tracking.json' --exclude='output/cost_log.json' \
  --exclude='assets/temp/' --exclude='.idea/' --exclude='.pytest_cache/' --exclude='*.pyc' \
  /Users/moganes/Projects/FVFactory/ root@31.97.212.55:/opt/FVFactory/
```

- [ ] **Step 2: Rebuild and restart library container**

```bash
ssh root@31.97.212.55 "cd /opt/FVFactory && docker compose build library && docker compose up -d library"
```

- [ ] **Step 3: Verify on VPS**

Open `http://31.97.212.55:8501`, click Generate tab, submit a test generation.
