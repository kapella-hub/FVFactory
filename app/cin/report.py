"""run_report.json writer (spec §10). Phase A: warnings, loudness, platform check, cost, stage
durations, clip counts. load_summary() is the read side for /api/generate and the web library."""
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
    "platform_check_failed", "final_swap_failed", "music_track_skipped", "sfx_file_skipped",
    "plan_save_failed", "script_length_off_target", "scene_roles_derived", "hook_headline_fallback",
    "cost_cap_exceeded", "tier_ignored", "voice_fallback",      # quality tiers (spec 2026-10-03 §8); never carried by --rerender
    "low_motion",                             # clips that barely move (quality tiers spec §16); carried
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
    script: dict = field(default_factory=dict)  # word budget + narration timing (spec 2026-10-03 §7)
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

    def save_quietly(self, path) -> bool:
        """save() for finally-blocks: a failed write is logged, never raised, so it cannot replace
        the exception that is already propagating (or fail a finished render)."""
        try:
            self.save(path)
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Could not write run report %s", path)
            return False

    @classmethod
    def load(cls, path) -> "RunReport":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})



def load_summary(path) -> dict:
    """UI-safe view of run_report.json for /api/generate and the library. Never raises: a missing
    or unreadable report gives status "unknown" and no warnings, so a listing never fails on it."""
    path = Path(path)
    summary = {"job": path.parent.name, "status": "unknown", "error": None, "warnings": [],
               "loudness": None, "platform_safe": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return summary
    except (OSError, ValueError) as e:            # JSONDecodeError and UnicodeDecodeError are ValueErrors
        logger.warning("Unreadable run report %s: %s", path, e)
        return {**summary, "error": "run_report.json is unreadable"}
    if not isinstance(data, dict):
        return {**summary, "error": "run_report.json is not an object"}
    warnings = []
    for w in data.get("warnings") or []:
        if isinstance(w, dict):
            detail = w.get("detail")
            warnings.append({"code": str(w.get("code", "")), "message": str(w.get("message", "")),
                             "detail": detail if isinstance(detail, dict) else {}})
    return {**summary, "job": str(data.get("job") or summary["job"]),
            "status": str(data.get("status") or "unknown"), "error": data.get("error"),
            "warnings": warnings, "loudness": data.get("loudness"),
            "platform_safe": data.get("platform_safe")}
