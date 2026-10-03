"""Per-video options shared by the web form, the scheduler and the background worker (spec §11).

Pure: no FastAPI / APScheduler imports, so it is unit-tested in the local venv (which has neither).
The rule everywhere is the CLI's: an option that is missing, None or "" means "use the Settings
default", which run_pipeline applies (pacing / music_source / strict default to None there).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Optional

from app.cin.music_library import MUSIC_SOURCES
from app.cin.report import load_summary
from app.cin.shot_plan import PACING
from app.config import settings

logger = logging.getLogger(__name__)

PACING_CHOICES = tuple(PACING)                 # ("calm", "standard", "fast"), spec §6.1 order
MUSIC_SOURCE_CHOICES = tuple(MUSIC_SOURCES)    # ("mine", "generated", "any", "none"), spec §8.1

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


class OptionError(ValueError):
    """An option value the pipeline would reject. Routes turn it into HTTP 422."""


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _choice(name: str, value: Any, choices: tuple) -> Optional[str]:
    if _blank(value):
        return None
    if not isinstance(value, str) or value.strip().lower() not in choices:
        raise OptionError(f"Unknown {name} {value!r}; choose one of {', '.join(choices)}")
    return value.strip().lower()


def to_bool(name: str, value: Any, default: Optional[bool]) -> Optional[bool]:
    """JSON bools pass through; "true"/"false"-style strings (curl, form posts) are parsed;
    anything else is rejected. Never Python truthiness: bool("false") is True."""
    if _blank(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE:
            return True
        if v in _FALSE:
            return False
    raise OptionError(f"{name} must be true or false, got {value!r}")


def pipeline_kwargs(config: Mapping[str, Any]) -> dict:
    """Web request body / scheduler slot config / worker arguments -> run_pipeline keyword
    arguments (everything except topic and voice, which callers resolve). Raises OptionError."""
    config = dict(config or {})
    return {
        "use_mock_images": to_bool("use_mock", config.get("use_mock"), False),
        "enable_subtitles": to_bool("enable_subtitles", config.get("enable_subtitles"), True),
        "enable_motion": to_bool("enable_motion", config.get("enable_motion"), True),
        "enable_sfx": to_bool("enable_sfx", config.get("enable_sfx"), True),
        "enable_music": to_bool("enable_music", config.get("enable_music"), True),
        "subtitle_style": _text(config.get("subtitle_style")) or settings.subtitle_style,
        "niche": _text(config.get("niche")) or None,
        "video_style": _text(config.get("video_style")),
        "video_duration": _text(config.get("video_duration")),
        "pacing": _choice("pacing", config.get("pacing"), PACING_CHOICES),
        "music_source": _choice("music_source", config.get("music_source"), MUSIC_SOURCE_CHOICES),
        "strict": to_bool("strict", config.get("strict"), None),
    }


def clean_settings_updates(updates: Mapping[str, Any]) -> dict:
    """Validate the per-video defaults inside a Settings update (PUT /api/config). Settings
    defaults must be concrete values, so blanks are rejected too. Other keys pass through."""
    cleaned = dict(updates or {})
    if "pacing" in cleaned:
        if _blank(cleaned["pacing"]):
            raise OptionError(f"pacing must be one of {', '.join(PACING_CHOICES)}")
        cleaned["pacing"] = _choice("pacing", cleaned["pacing"], PACING_CHOICES)
    if "music_source" in cleaned:
        if _blank(cleaned["music_source"]):
            raise OptionError(f"music_source must be one of {', '.join(MUSIC_SOURCE_CHOICES)}")
        cleaned["music_source"] = _choice("music_source", cleaned["music_source"], MUSIC_SOURCE_CHOICES)
    if "strict" in cleaned:
        cleaned["strict"] = to_bool("strict", cleaned["strict"], False)
    return cleaned


def apply_settings_updates(target, updates: Mapping[str, Any]) -> list:
    """setattr every key the Settings object knows (pydantic-settings does not validate
    assignment, so callers clean first). Returns the applied keys."""
    applied = []
    for key, value in (updates or {}).items():
        if hasattr(target, key):
            setattr(target, key, value)
            applied.append(key)
    return applied


def apply_saved_settings(target, saved: Mapping[str, Any]) -> list:
    """Server startup: apply data/config.json. A bad saved value (hand edit, older version) is
    skipped with a warning; it never stops the server. Returns the applied keys."""
    applied = []
    for key, value in (saved or {}).items():
        try:
            cleaned = clean_settings_updates({key: value})
        except OptionError as e:
            logger.warning("Ignoring saved setting %s from config.json: %s", key, e)
            continue
        applied += apply_settings_updates(target, cleaned)
    return applied


def load_config_file(path) -> dict:
    """data/config.json as a dict. Missing, unreadable or non-object content is an empty config."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable %s: %s", path, e)
        return {}
    return data if isinstance(data, dict) else {}



def run_result(final_path) -> dict:
    """WebSocket 'complete' payload: library id of the job plus the run report summary
    (spec §10: /api/generate returns the report's warnings with the result)."""
    final = Path(final_path)
    return {"video_id": final.parent.name, "path": str(final),
            **load_summary(final.parent / "run_report.json")}


def run_failure(exc: BaseException) -> dict:
    """WebSocket 'error' payload extras. run_pipeline tags exceptions with job_dir (main.py);
    errors raised before a job folder exists (topic discovery) carry no report."""
    job_dir = getattr(exc, "job_dir", None)
    if not job_dir:
        return {"video_id": None, "status": "failed", "warnings": []}
    return {"video_id": Path(job_dir).name, **load_summary(Path(job_dir) / "run_report.json")}
