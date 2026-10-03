"""Per-run job folder (spec §9.2): output/<job>/final.mp4, run_report.json, sources/...

All paths written into JSON are job-relative posix strings ("sources/clips/scene00_a.mp4") so a
job folder can be moved, zipped or re-rendered on another OS.
"""
from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                     *(f"lpt{i}" for i in range(1, 10))}
SLUG_MAX = 40


def slugify(topic: str, max_len: int = SLUG_MAX) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")[:max_len].strip("_")
    if not slug:
        return "video"
    return slug + "_" if slug in _WINDOWS_RESERVED else slug


@dataclass(frozen=True)
class JobPaths:
    root: Path

    @property
    def name(self) -> str:
        return self.root.name

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def images(self) -> Path:
        return self.sources / "images"

    @property
    def clips(self) -> Path:
        return self.sources / "clips"

    @property
    def narration(self) -> Path:
        return self.sources / "narration.mp3"

    @property
    def words(self) -> Path:
        return self.sources / "words.json"

    @property
    def alignment(self) -> Path:
        return self.sources / "alignment.json"

    @property
    def shot_plan(self) -> Path:
        return self.sources / "shot_plan.json"

    @property
    def mix(self) -> Path:
        return self.sources / "mix.wav"

    @property
    def final(self) -> Path:
        return self.root / "final.mp4"

    @property
    def final_prev(self) -> Path:
        return self.root / "final.prev.mp4"

    @property
    def report(self) -> Path:
        return self.root / "run_report.json"

    @property
    def render_tmp(self) -> Path:
        return self.root / "_render"

    def image(self, scene: int) -> Path:
        return self.images / f"scene{scene:02d}.png"

    def clip(self, name: str) -> Path:
        return self.clips / f"{name}.mp4"

    def last_frame(self, name: str) -> Path:
        return self.clips / f"{name}_last.png"

    def rel(self, path) -> str:
        """Job-relative posix path for JSON; paths outside the job are returned as posix as-is."""
        p = Path(path)
        try:
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return p.as_posix()

    def resolve(self, rel: str) -> Path:
        """Inverse of rel(): works for posix strings on Windows and for absolute paths."""
        p = Path(rel)
        return p if p.is_absolute() else self.root.joinpath(*rel.split("/"))

    def ensure(self) -> "JobPaths":
        for d in (self.images, self.clips):
            d.mkdir(parents=True, exist_ok=True)
        return self


def create_job(topic: str, output_dir="output", now: Optional[datetime] = None) -> JobPaths:
    """Claim a fresh output/<YYYYMMDD_HHMMSS>_<slug>[_N]/ folder. mkdir(exist_ok=False) is the
    atomic claim, so concurrent jobs started in the same second never share a folder."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = f"{(now or datetime.now()).strftime('%Y%m%d_%H%M%S')}_{slugify(topic)}"
    for n in range(1, 1000):
        root = out / (base if n == 1 else f"{base}_{n}")
        try:
            root.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return JobPaths(root).ensure()
    raise RuntimeError(f"Could not create a job folder for {base!r}")


def open_job(job_dir) -> JobPaths:
    root = Path(job_dir)
    if not (root / "sources").is_dir():
        raise FileNotFoundError(f"Not a job folder (no sources/ inside): {root}")
    return JobPaths(root)


def prune_sources(output_dir, keep_days: int, now: Optional[float] = None) -> list:
    """Delete output/<job>/sources/ older than keep_days (spec §9.2). Only folders that contain a
    run_report.json are touched; final.mp4 and run_report.json are kept. keep_days <= 0 disables."""
    if keep_days <= 0:
        return []
    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    removed = []
    for src in Path(output_dir).glob("*/sources"):
        if not src.is_dir() or not (src.parent / "run_report.json").is_file():
            continue
        try:
            if src.stat().st_mtime < cutoff:
                shutil.rmtree(src)
                removed.append(src)
                logger.info("Pruned old sources: %s", src)
        except OSError as e:  # file locked by a player on Windows, permissions, ...
            logger.warning("Could not prune %s: %s", src, e)
    return removed
