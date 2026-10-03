"""SFX library and placement (spec §8.2). User files in assets/sfx/ and generated files in
assets/sfx/generated/ are classified by filename prefix: whoosh*, impact*, riser*.
place_sfx is pure: (ShotPlan, pool) -> shot_plan.json "sfx" entries (spec §6.6)."""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.cin.music_library import asset_key

SFX_KINDS = ("whoosh", "impact", "riser")
SFX_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac")
SFX_GAIN_DB = {"whoosh": -10.0, "impact": -6.0, "riser": -12.0}   # relative to the voice reference
WHOOSH_LEAD = 0.15
GENERATED_DIR = "generated"


@dataclass(frozen=True)
class SfxFile:
    path: Path
    kind: str
    duration: float


def sfx_kind(path) -> Optional[str]:
    stem = Path(path).stem.lower()
    return next((k for k in SFX_KINDS if stem.startswith(k)), None)


def scan_sfx(sfx_dir) -> dict:
    """{kind: [Path, ...]} from sfx_dir/ (user) and sfx_dir/generated/, sorted by path."""
    root = Path(sfx_dir)
    pool = {k: [] for k in SFX_KINDS}
    for folder in (root, root / GENERATED_DIR):
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            kind = sfx_kind(p)
            if p.is_file() and kind and p.suffix.lower() in SFX_EXTENSIONS:
                pool[kind].append(p)
    return {k: sorted(v, key=asset_key) for k, v in pool.items()}


def place_sfx(plan, pool: dict, seed: str = "") -> list:
    """Impact at 0.0; whoosh WHOOSH_LEAD s before every scene boundary (never intra-scene cuts);
    a riser ending at every styled transition (offset into the file when it would start before 0).
    Variants of each kind rotate; a non-empty seed (the job name) picks the starting variant per kind so
    consecutive videos do not all open on the same whoosh. pool: {kind: [SfxFile, ...]}."""
    events = []
    used = {k: (zlib.crc32(f"{seed}:{k}".encode()) if seed else 0) for k in SFX_KINDS}

    def take(kind):
        files = pool.get(kind) or []
        if not files:
            return None
        f = files[used[kind] % len(files)]
        used[kind] += 1
        return f

    def add(f, t, offset=0.0):
        if t >= plan.duration:
            return
        ev = {"t": round(max(0.0, t), 3), "kind": f.kind, "file": asset_key(f.path),
              "gain_db": SFX_GAIN_DB[f.kind]}
        if offset > 0:
            ev["offset"] = round(offset, 3)
        events.append(ev)

    f = take("impact")
    if f:
        add(f, 0.0)
    for sc in plan.scenes[1:]:
        f = take("whoosh")
        if f:
            add(f, sc.t0 - WHOOSH_LEAD)
    for shot in plan.shots:
        if shot.transition_in == "cut" or shot.t0 <= 0:
            continue
        f = take("riser")
        if f:
            start = shot.t0 - f.duration
            add(f, start, offset=max(0.0, -start))
    return sorted(events, key=lambda e: (e["t"], e["kind"]))
