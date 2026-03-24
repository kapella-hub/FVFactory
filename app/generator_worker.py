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
