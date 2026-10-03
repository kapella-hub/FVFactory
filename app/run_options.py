"""Per-video options shared by the web form, the scheduler and the background worker (spec §11).

Pure: no FastAPI / APScheduler imports, so it is unit-tested in the local venv (which has neither).
The rule everywhere is the CLI's: an option that is missing, None or "" means "use the Settings
default", which run_pipeline applies (pacing / music_source / strict default to None there).
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Mapping, Optional

from pydantic import TypeAdapter, ValidationError

from app.cin.music_library import MUSIC_SOURCES
from app.cin.report import load_summary
from app.cin.shot_plan import PACING
from app.cin.tiers import QUALITY_TIERS
from app.config import settings

logger = logging.getLogger(__name__)

PACING_CHOICES = tuple(PACING)                 # ("calm", "standard", "fast"), spec §6.1 order
MUSIC_SOURCE_CHOICES = tuple(MUSIC_SOURCES)    # ("mine", "generated", "any", "none"), spec §8.1
TIER_CHOICES = QUALITY_TIERS                   # ("standard", "premium", "custom"), spec 2026-10-03 §4

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


def to_max_cost(name: str, value: Any, default: Optional[float]) -> Optional[float]:
    """A per-video cap in USD: a number or numeric string >= 0 (0 = no cap); blank -> default.
    Booleans, NaN, infinity, negatives and non-numeric text are rejected."""
    if _blank(value):
        return default
    number = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            number = None
    if number is None or not math.isfinite(number) or number < 0:
        raise OptionError(f"{name} must be a number of USD >= 0 (0 = no cap), got {value!r}")
    return number


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
        "quality_tier": _choice("quality_tier", config.get("quality_tier"), TIER_CHOICES),
        "max_cost": to_max_cost("max_cost", config.get("max_cost"), None),
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
    if "quality_tier" in cleaned:
        if _blank(cleaned["quality_tier"]):
            raise OptionError(f"quality_tier must be one of {', '.join(TIER_CHOICES)}")
        cleaned["quality_tier"] = _choice("quality_tier", cleaned["quality_tier"], TIER_CHOICES)
    if "max_cost_per_video" in cleaned:      # Field(ge=0) is not seen by validate_settings_updates
        if _blank(cleaned["max_cost_per_video"]):
            raise OptionError("max_cost_per_video must be a number of USD >= 0 (0 = no cap)")
        cleaned["max_cost_per_video"] = to_max_cost("max_cost_per_video", cleaned["max_cost_per_video"], None)
    return cleaned


def validate_settings_updates(target, updates: Mapping[str, Any]) -> tuple:
    """Check every key against the Settings model: the key must be a declared field and the value
    must validate against that field's type (pydantic-settings does not validate setattr, and
    hasattr() also matches methods such as model_dump). Returns (valid {key: coerced value},
    errors {key: message}); never raises."""
    fields = type(target).model_fields
    valid, errors = {}, {}
    for key, value in (updates or {}).items():
        field = fields.get(key)
        if field is None:
            errors[key] = "unknown setting"
            continue
        try:
            valid[key] = TypeAdapter(field.annotation).validate_python(value)
        except ValidationError as e:
            errors[key] = e.errors()[0]["msg"]
    return valid, errors


def apply_settings_updates(target, updates: Mapping[str, Any]) -> list:
    """setattr every update that is a Settings field with a valid value; skip (with a warning)
    anything else. Never raises. Returns the applied keys."""
    valid, errors = validate_settings_updates(target, updates)
    for key, msg in errors.items():
        logger.warning("Ignoring setting %s: %s", key, msg)
    for key, value in valid.items():
        setattr(target, key, value)
    return list(valid)


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
