"""Music library (spec §8.1): user tracks in assets/music/<mood>/, generated tracks in
assets/music/<mood>/generated/, least-recently-used selection tracked in data/music_usage.json.

Library paths are cwd-relative (or absolute) asset paths such as "assets/music/epic/a.mp3".
They are NOT job-relative: never pass them through JobPaths.rel()/resolve()."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

logger = logging.getLogger(__name__)

MOODS = ("chill", "cinematic", "dark", "epic", "upbeat")
MUSIC_SOURCES = ("mine", "generated", "any", "none")
MUSIC_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
GENERATED_DIR = "generated"
USAGE_FILE = "music_usage.json"

_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def asset_path(p) -> Path:
    """Inverse of asset_key(): a cwd-relative or absolute library path."""
    return Path(p)


def asset_key(path) -> str:
    """Posix string stored in shot_plan.json and music_usage.json."""
    return Path(path).as_posix()


def default_usage_path() -> Path:
    from app.config import settings
    return Path(settings.data_dir) / USAGE_FILE


def _audio_files(folder: Path) -> list:
    if not folder.is_dir():
        return []
    return [p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in MUSIC_EXTENSIONS and not p.name.startswith(".")]


def list_tracks(music_dir, mood: str, source: str) -> list:
    """Candidate tracks for a mood and music_source. mood "" (no niche/style match) = every mood."""
    if source not in MUSIC_SOURCES:
        raise ValueError(f"Unknown music_source {source!r}; choose one of {MUSIC_SOURCES}")
    if source == "none":
        return []
    root = Path(music_dir)
    out = []
    for m in ([mood] if mood else list(MOODS)):
        if source in ("mine", "any"):
            out += _audio_files(root / m)
        if source in ("generated", "any"):
            out += _audio_files(root / m / GENERATED_DIR)
    return sorted(out, key=asset_key)


def lru_order(candidates: Iterable, usage: dict) -> list:
    """Never-used tracks first, then oldest last_used; ties broken by path (deterministic)."""
    def key(p):
        rec = usage.get(asset_key(p)) or {}
        last = rec.get("last_used", 0.0)
        return (last if isinstance(last, (int, float)) else 0.0, asset_key(p))
    return sorted(candidates, key=key)


class UsageStore:
    """data/music_usage.json: {"version": 1, "tracks": {key: {"last_used": epoch_s, "count": n}}}.
    A missing or corrupt file reads as empty (logged, never raised). Writes are atomic; one lock per
    file serialises select-and-record inside this process only (no cross-process lock: known gap)."""

    def __init__(self, path=None):
        self.path = Path(path) if path else default_usage_path()
        with _LOCKS_GUARD:
            self.lock = _LOCKS.setdefault(str(self.path.resolve()), threading.Lock())

    def read(self):
        """(tracks, readable). readable=False means a transient I/O failure: the history is unknown,
        so callers must not overwrite the file. Corrupt content reads as ({}, True) (history restarts)."""
        data = None
        for attempt in range(3):
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                break
            except FileNotFoundError:
                return {}, True
            except PermissionError as e:            # Windows: a writer is mid-os.replace
                if attempt == 2:
                    logger.warning("Cannot read %s (%s); LRU history left untouched", self.path, e)
                    return {}, False
                time.sleep(0.1)
            except OSError as e:
                logger.warning("Cannot read %s (%s); LRU history left untouched", self.path, e)
                return {}, False
            except ValueError as e:
                logger.warning("Ignoring corrupt %s (%s); LRU history restarts", self.path, e)
                return {}, True
        tracks = data.get("tracks") if isinstance(data, dict) else None
        if not isinstance(tracks, dict):
            logger.warning("Ignoring malformed %s; LRU history restarts", self.path)
            return {}, True
        return {k: v for k, v in tracks.items() if isinstance(v, dict)}, True

    def load(self) -> dict:
        return self.read()[0]

    def save(self, tracks: dict) -> bool:
        """Atomic write; bookkeeping must never fail a render, so OSError is logged, not raised."""
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"version": 1, "tracks": tracks}, indent=1), encoding="utf-8")
            for attempt in range(5):
                try:
                    os.replace(tmp, self.path)
                    return True
                except PermissionError:             # Windows: another process has it open
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        except OSError as e:
            logger.warning("Could not update %s (%s); selection not recorded", self.path, e)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def select_track(candidates: Iterable, store: UsageStore, *, accept: Optional[Callable] = None,
                 now: Optional[float] = None) -> Optional[Path]:
    """Least-recently-used candidate that `accept(path)` approves; records its use.
    Select-and-record is atomic per usage file within this process (accept runs under the lock)."""
    candidates = list(candidates)
    if not candidates:
        return None
    with store.lock:
        usage, readable = store.read()
        for path in lru_order(candidates, usage):
            if accept is not None and not accept(path):
                continue
            rec = usage.get(asset_key(path)) or {}
            count = rec.get("count", 0)
            usage[asset_key(path)] = {"last_used": time.time() if now is None else now,
                                      "count": (count if isinstance(count, int) else 0) + 1}
            if readable:                    # never overwrite history we could not read
                store.save(usage)
            return Path(path)
    return None
