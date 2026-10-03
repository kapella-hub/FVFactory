"""Shot planner (spec §6). Pure functions — no I/O, no rendering.

Two phases around clip generation:
  plan_segments(alignment, durations)  -> [SegmentRequest]  (what clips to ask for)
  build_shot_plan(alignment, pacing, clip_specs) -> ShotPlan  (how to cut what came back)
ShotPlan.to_json() is the shot_plan.json contract (spec §6.6).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.cin.align import Alignment
from app.motion_gen import max_duration, snap_duration

# spec §6.1 — (target, min, max) seconds
PACING = {
    "calm": (4.2, 3.5, 5.0),
    "standard": (2.8, 2.2, 3.5),
    "fast": (2.1, 1.8, 2.5),
}
HANDLE = 0.5                 # spec §6.4: requested clip length = scene length + 0.5 s
MIN_SPEED = 0.87             # spec §6.4: footage short by <= 15 % is slowed, never below 0.87x
FPS = 30
FRAMINGS = (1.0, 1.18)       # spec §6.3: full frame / punch-in
TRANSITION_LEN = 0.3         # spec §6.5
MAX_TRANSITIONS = 3
TRANSITION_CYCLE = ("flash", "zoom_through", "whip_pan")
STILL_MOVE = "push_in"
MIN_PIECE = 0.25             # never emit a footage/still sliver shorter than this
# When gap positions make [min, max] infeasible for a segment longer than max, relax the bounds
# step by step instead of leaving one over-long shot (spec §6.2 only defines the short-scene case).
RELAX_STEPS = ((1.0, 1.0), (0.8, 1.25), (0.0, 1.5))
_EPS = 1e-6


# ------------------------------------------------------------------ data types

@dataclass
class Gap:
    t: float          # cut time (middle of the silence between two words)
    length: float     # silence length in seconds
    score: float      # spec §6.2: gap + 0.5 sentence end + 0.25 comma


@dataclass
class SegmentRequest:
    """One clip to generate (spec §6.4). Planned before any paid generation."""
    scene: int
    index: int               # 0 -> "a", 1 -> "b", ...
    t0: float
    t1: float
    requested_len: float
    chained: bool            # True: start image is the previous segment's last frame

    @property
    def name(self) -> str:
        return f"scene{self.scene:02d}_{'abcdefghijklmnopqrstuvwxyz'[self.index]}"


@dataclass
class ClipSpec:
    """What clip generation produced for one segment — the input to build_shot_plan."""
    scene: int
    index: int
    t0: float
    t1: float
    requested_len: float
    start_image: str                  # job-relative posix path
    path: Optional[str] = None        # job-relative posix path of the clip; None = no footage
    duration: float = 0.0             # real clip length (s)
    last_frame: Optional[str] = None  # job-relative posix path of the clip's last frame PNG
    failed: bool = False              # generation was attempted and failed -> still_fallback
    model: str = ""                   # model that produced the clip (cost logging)
    attempts: int = 0


@dataclass
class Segment:
    t0: float
    t1: float
    clip: Optional[str]
    requested_len: float
    start_image: str

    def to_json(self) -> dict:
        return {"t0": round(self.t0, 3), "t1": round(self.t1, 3), "clip": self.clip,
                "requested_len": round(self.requested_len, 3), "start_image": self.start_image}


@dataclass
class Scene:
    index: int
    t0: float
    t1: float
    text: str
    segments: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"index": self.index, "t0": round(self.t0, 3), "t1": round(self.t1, 3),
                "text": self.text, "segments": [s.to_json() for s in self.segments]}


@dataclass
class ShotSource:
    type: str                 # "clip" | "still"
    path: str                 # job-relative posix path
    clip_t0: float = 0.0
    clip_t1: float = 0.0
    speed: float = 1.0
    move: str = ""            # stills only

    def to_json(self) -> dict:
        if self.type == "still":
            return {"type": "still", "path": self.path, "move": self.move or STILL_MOVE}
        return {"type": "clip", "path": self.path, "clip_t0": round(self.clip_t0, 3),
                "clip_t1": round(self.clip_t1, 3), "speed": round(self.speed, 4)}


@dataclass
class Shot:
    index: int
    scene: int
    t0: float
    t1: float
    source: ShotSource
    framing: float = 1.0
    transition_in: str = "cut"

    def to_json(self) -> dict:
        return {"index": self.index, "scene": self.scene, "t0": round(self.t0, 3),
                "t1": round(self.t1, 3), "source": self.source.to_json(),
                "framing": self.framing, "transition_in": self.transition_in}


@dataclass
class CaptionWord:
    text: str
    t0: float
    t1: float


@dataclass
class CaptionGroup:
    t0: float
    t1: float
    words: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"t0": round(self.t0, 3), "t1": round(self.t1, 3),
                "words": [{"text": w.text, "t0": round(w.t0, 3), "t1": round(w.t1, 3)} for w in self.words]}


@dataclass
class ShotPlan:
    duration: float
    fps: int
    pacing: str
    alignment: dict
    scenes: list
    shots: list
    captions: list
    sfx: list = field(default_factory=list)          # Phase C fills this
    music: Optional[dict] = None                      # Phase C fills this
    hook_headline: Optional[dict] = None              # Phase B fills this
    version: int = 1
    warnings: list = field(default_factory=list)      # planner warnings for run_report; not serialized

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "duration": round(self.duration, 3),
            "fps": self.fps,
            "pacing": self.pacing,
            "alignment": self.alignment,
            "scenes": [s.to_json() for s in self.scenes],
            "shots": [s.to_json() for s in self.shots],
            "captions": [c.to_json() for c in self.captions],
            "sfx": self.sfx,
            "music": self.music,
            "hook_headline": self.hook_headline,
        }

    @classmethod
    def from_json(cls, d: dict) -> "ShotPlan":
        scenes = [Scene(s["index"], s["t0"], s["t1"], s["text"],
                        [Segment(g["t0"], g["t1"], g["clip"], g["requested_len"], g["start_image"])
                         for g in s["segments"]]) for s in d["scenes"]]
        shots = []
        for s in d["shots"]:
            src = s["source"]
            if src["type"] == "still":
                source = ShotSource("still", src["path"], move=src.get("move", STILL_MOVE))
            else:
                source = ShotSource("clip", src["path"], src["clip_t0"], src["clip_t1"], src["speed"])
            shots.append(Shot(s["index"], s["scene"], s["t0"], s["t1"], source, s["framing"], s["transition_in"]))
        captions = [CaptionGroup(c["t0"], c["t1"], [CaptionWord(w["text"], w["t0"], w["t1"]) for w in c["words"]])
                    for c in d["captions"]]
        return cls(duration=d["duration"], fps=d["fps"], pacing=d["pacing"], alignment=d["alignment"],
                   scenes=scenes, shots=shots, captions=captions, sfx=d.get("sfx", []),
                   music=d.get("music"), hook_headline=d.get("hook_headline"), version=d.get("version", 1))

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_json(), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "ShotPlan":
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------------ gaps

def word_gaps(alignment: Alignment) -> list:
    """Candidate cut points: the silence between every pair of consecutive tokens."""
    gaps = []
    toks = alignment.tokens
    for a, b in zip(toks, toks[1:]):
        length = max(0.0, b.t0 - a.t1)
        score = length + (0.5 if a.sentence_end else 0.0) + (0.25 if a.comma else 0.0)
        gaps.append(Gap(t=round(a.t1 + length / 2, 4), length=length, score=score))
    return gaps


def _inside(gaps: list, t0: float, t1: float, margin: float = 0.0) -> list:
    return [g for g in gaps if t0 + margin + _EPS < g.t < t1 - margin - _EPS]


# ------------------------------------------------------------------ segments (spec §6.4)

def _best_cut_near_middle(t0: float, t1: float, gaps: list) -> float:
    length = t1 - t0
    mid = t0 + length / 2
    window = [g for g in gaps if t0 + 0.3 * length <= g.t <= t0 + 0.7 * length]
    if window:
        return max(window, key=lambda g: (g.score, -abs(g.t - mid))).t
    inner = _inside(gaps, t0, t1, margin=0.5)
    if inner:
        return min(inner, key=lambda g: abs(g.t - mid)).t
    return mid


def _split_span(t0: float, t1: float, gaps: list, limit: float) -> list:
    if (t1 - t0) + HANDLE <= limit + _EPS:
        return [(t0, t1)]
    cut = _best_cut_near_middle(t0, t1, _inside(gaps, t0, t1))
    return _split_span(t0, cut, gaps, limit) + _split_span(cut, t1, gaps, limit)


def plan_segments(alignment: Alignment, durations) -> list:
    """One clip per scene of scene_len + HANDLE, snapped up to a supported model length.
    Scenes too long for the model's longest clip are split at the best word gap near the middle.
    durations=None means any length (local model or motion disabled)."""
    gaps = word_gaps(alignment)
    limit = max_duration(durations)
    out = []
    for sc in alignment.scenes:
        for i, (a, b) in enumerate(_split_span(sc.t0, sc.t1, gaps, limit)):
            req = snap_duration(b - a + HANDLE, durations)
            out.append(SegmentRequest(sc.index, i, round(a, 4), round(b, 4), req, chained=i > 0))
    return out
