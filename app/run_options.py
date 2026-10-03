"""Per-video options shared by the web form, the scheduler and the background worker (spec §11).

Pure: no FastAPI / APScheduler imports, so it is unit-tested in the local venv (which has neither).
The rule everywhere is the CLI's: an option that is missing, None or "" means "use the Settings
default", which run_pipeline applies (pacing / music_source / strict / mascot default to None there).
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Annotated, Any, Mapping, Optional, Union

from pydantic import StrictFloat, StrictInt, TypeAdapter, ValidationError

from app.cin.music_library import MUSIC_SOURCES
from app.cin.report import load_summary
from app.cin.shot_plan import PACING
from app.cin.tiers import QUALITY_TIERS
from app.config import settings
from app.story import StoryError, check_story

logger = logging.getLogger(__name__)

# Request-model type of max_cost. Strict numbers: a plain float/str union would coerce JSON `true`
# to 1.0 (a silent $1 cap); with this, `true`/`false` is a 422. Text still reaches to_max_cost.
MaxCostInput = Optional[Union[StrictFloat, StrictInt, str]]

PACING_CHOICES = tuple(PACING)                 # ("calm", "standard", "fast"), spec §6.1 order
MUSIC_SOURCE_CHOICES = tuple(MUSIC_SOURCES)    # ("mine", "generated", "any", "none"), spec §8.1
TIER_CHOICES = QUALITY_TIERS                   # ("standard", "premium", "custom"), spec 2026-10-03 §4

# Settings that only .env may set: secrets for the CLI children and the web UI's own CORS policy (a
# web-settable CORS policy would let any page widen it). PUT /api/config and config.json refuse them.
ENV_ONLY_SETTINGS = frozenset({"cors_origins", "claude_code_oauth_token", "codex_api_key"})

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
        "mascot": to_bool("mascot", config.get("mascot"), None),      # None = settings.mascot_enabled
    }


TITLE_MAX_CHARS = 120
PERSONA_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")      # app.animator.PortraitAnimator's list


def story_options(config: Mapping[str, Any]) -> Optional[dict]:
    """The "Your story" part of a Generate request -> {"story", "story_mode", "title"}, or None for a topic /
    auto-discover run. Intent rule: a story_mode with an empty story, or a story that is only whitespace, is
    an empty story (OptionError, HTTP 422), as are a story over app.story.MAX_STORY_CHARS, an unknown mode,
    a story together with auto-discover and a title over TITLE_MAX_CHARS. The story comes back normalised."""
    config = dict(config or {})
    story, mode = config.get("story"), config.get("story_mode")
    if story is None or story == "":
        if not _blank(mode):
            raise OptionError("Story is empty: paste the narration you want spoken")
        return None
    if not isinstance(story, str):
        raise OptionError("story must be text")
    try:
        text, mode = check_story(story, None if _blank(mode) else str(mode))
    except StoryError as e:
        raise OptionError(str(e)) from None
    if to_bool("auto_topic", config.get("auto_topic"), False):
        raise OptionError("Choose either auto-discover or a story, not both")
    title = _text(config.get("title"))
    if len(title) > TITLE_MAX_CHARS:
        raise OptionError(f"title must be {TITLE_MAX_CHARS} characters or fewer")
    return {"story": text, "story_mode": mode, "title": title}


def available_personas(directory) -> list:
    """Persona image file names in `directory` (sorted). A missing folder is an empty list; it is never
    created (PortraitAnimator() would mkdir it)."""
    path = Path(directory)
    if not path.is_dir():
        return []
    return sorted(p.name for p in path.iterdir() if p.is_file() and p.suffix.lower() in PERSONA_EXTENSIONS)


def generate_extras(config: Mapping[str, Any]) -> dict:
    """Generate-page options that are not scheduler slot options (pipeline_kwargs stays the slot contract):
    classic editor, persona (+ chroma key) and YouTube upload. A persona must be one of
    available_personas(settings.personas_dir), so no path can reach the animator. Raises OptionError."""
    config = dict(config or {})
    persona = _text(config.get("persona")) or None
    if persona is not None and persona not in available_personas(settings.personas_dir):
        raise OptionError(f"Unknown persona {persona!r}; add the image to {settings.personas_dir} first")
    return {
        "classic": to_bool("classic", config.get("classic"), False),
        "persona": persona,
        "use_chroma_key": bool(persona) and to_bool("use_chroma_key", config.get("use_chroma_key"), False),
        "upload": to_bool("upload", config.get("upload"), False),
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
    if "max_cost_per_video" in cleaned:      # blank / text forms; validate_settings_updates checks ge=0 too
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
        if key in ENV_ONLY_SETTINGS:
            errors[key] = "can only be set in .env"
            continue
        # field.annotation alone drops Annotated / Field constraints (patterns, ge=...): re-attach them
        annotation = Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation
        try:
            valid[key] = TypeAdapter(annotation).validate_python(value)
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
