"""run_report.json writer (spec §10). Phase A: warnings, loudness, platform check, cost, stage
durations, clip counts. Phase D surfaces it through /api/generate."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Codes used in Phase A (spec §10 list plus clip_retry / loudness_skipped).
WARNING_CODES = (
    "still_fallback", "alignment_fallback", "font_fallback", "music_missing", "sfx_missing",
    "speed_adjusted", "prompt_count_normalized", "clip_retry", "loudness_skipped",
    "platform_check_failed", "final_swap_failed",
)


@dataclass
class RunReport:
    job: str
    options: dict = field(default_factory=dict)
    status: str = "running"                  # running | ok | failed
    error: Optional[str] = None
    warnings: list = field(default_factory=list)
    loudness: Optional[dict] = None          # {"I", "TP", "LRA"} measured on final.mp4
    platform_safe: Optional[dict] = None     # {"ok": bool, "issues": [...]}
    cost: dict = field(default_factory=lambda: {"estimated": None, "actual": [], "total": 0.0})
    durations: dict = field(default_factory=dict)
    clips: dict = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        self._lock = threading.Lock()

    def warn(self, code: str, message: str, detail: Optional[dict] = None) -> None:
        with self._lock:
            self.warnings.append({"code": code, "message": message, "detail": detail or {}})
        logger.warning("[%s] %s", code, message)

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            with self._lock:
                self.durations[name] = round(self.durations.get(name, 0.0) + elapsed, 2)

    def to_json(self) -> dict:
        d = asdict(self)
        d.pop("_lock", None)
        return d

    def save(self, path) -> None:
        path = Path(path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_json(), indent=1), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path) -> "RunReport":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
