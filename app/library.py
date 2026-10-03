"""Locate rendered videos for the web library: job folders and legacy flat files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_SAFE_ID = re.compile(r"[A-Za-z0-9_.\- ]+")


def _entry(output_dir: Path, video_id: str, mp4: Path) -> dict:
    meta_path = output_dir / "metadata" / f"{video_id}.json"
    thumb_path = output_dir / "thumbnails" / f"{video_id}.png"
    metadata = None
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            metadata = None
    stat = mp4.stat()
    return {
        "id": video_id,
        "filename": mp4.name,
        "path": str(mp4),
        "created": stat.st_mtime,
        "size_mb": round(stat.st_size / 1024 / 1024, 1),
        "has_thumbnail": thumb_path.exists(),
        "metadata": metadata,
    }


def find_videos(output_dir: Path) -> list[dict]:
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return []
    entries = [_entry(output_dir, mp4.stem, mp4) for mp4 in output_dir.glob("*.mp4")]
    entries += [_entry(output_dir, final.parent.name, final) for final in output_dir.glob("*/final.mp4")]
    return sorted(entries, key=lambda e: e["created"], reverse=True)


def resolve_video(output_dir: Path, video_id: str) -> Optional[Path]:
    if not _SAFE_ID.fullmatch(video_id) or ".." in video_id:
        return None
    output_dir = Path(output_dir)
    for candidate in (output_dir / video_id / "final.mp4", output_dir / f"{video_id}.mp4"):
        if candidate.is_file():
            return candidate
    return None
