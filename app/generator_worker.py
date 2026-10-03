"""Background worker for on-demand video generation."""

import logging
import threading
from typing import Optional

from app.run_options import pipeline_kwargs
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
              enable_motion: bool = True, enable_sfx: bool = True, enable_music: bool = True,
              pacing: Optional[str] = None, music_source: Optional[str] = None,
              strict: Optional[bool] = None, quality_tier: Optional[str] = None,
              max_cost: Optional[float] = None) -> bool:
        """Start generation. Returns False if already busy. pacing / music_source / strict /
        quality_tier / max_cost = None use the Settings defaults; an invalid value raises OptionError
        before the worker goes busy."""
        if self.status == "running":
            return False
        options = pipeline_kwargs({
            "niche": niche, "subtitle_style": subtitle_style, "enable_motion": enable_motion,
            "enable_sfx": enable_sfx, "enable_music": enable_music,
            "pacing": pacing, "music_source": music_source, "strict": strict,
            "quality_tier": quality_tier, "max_cost": max_cost,
        })

        self.status = "running"
        self.logs = []
        self.result = None
        self.error = None

        voice_id = resolve_voice(voice, niche=niche) if voice else None

        self._kwargs = dict(topic=topic, voice=voice_id, **options)

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
