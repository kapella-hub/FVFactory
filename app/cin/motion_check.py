"""Low-motion check of generated clips (follow-up to spec 2026-10-03 quality tiers, section 16).

User feedback on the first Standard video: "why is it not full motion?". Every shot was a clip at speed
1.0, but some clips were a slow camera drift over a near-static subject. This module scores each clip
by its mean luma frame difference and the shot editor warns (low_motion) about the ones that barely
move. It never fails a run: any ffmpeg error, timeout or unreadable file scores None (not flagged).
"""
from __future__ import annotations

import logging
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SCORE_WIDTH = 270          # px; scores are comparable across 720p and 1080p clips
SCORE_TIMEOUT = 30         # s per clip; a ~6 s clip at 270 px takes well under a second
SCORE_WORKERS = 4
_YDIF = re.compile(r"lavfi\.signalstats\.YDIF=([0-9.eE+-]+)")


def clip_motion_score(path, timeout: float = SCORE_TIMEOUT) -> Optional[float]:
    """Mean ffmpeg signalstats YDIF (mean absolute luma difference to the previous frame, 0-255)
    of the clip scaled to SCORE_WIDTH px wide, rounded to 3 decimals. Frame 0 is excluded: it has
    no predecessor and always reads 0. None on a missing / unreadable file, an ffmpeg error or a
    timeout. Measured 2026-10-03 on Kling v3 clips: rusty chains 0.95, coin opener 6.18, star
    collision 16.6."""
    try:
        path = Path(path)
        if not path.is_file():
            return None
        from app.encoding import find_ffmpeg
        cmd = [find_ffmpeg(), "-hide_banner", "-nostats", "-v", "error", "-i", str(path), "-an",
               "-vf", f"scale={SCORE_WIDTH}:-2,signalstats,"
                      "metadata=mode=print:key=lavfi.signalstats.YDIF:file=-",
               "-f", "null", "-"]
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, check=False)
    except Exception as e:  # noqa: BLE001 - a score is advisory; never raise
        logger.warning("Could not score motion of %s: %s", path, e)
        return None
    if proc.returncode != 0:
        logger.warning("Could not score motion of %s: ffmpeg exited %s", path, proc.returncode)
        return None
    values = [float(v) for v in _YDIF.findall(proc.stdout or "")][1:]
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def check_clip_motion(specs: list, job, report, threshold: float,
                      scorer: Callable[[Path], Optional[float]] = clip_motion_score,
                      workers: int = SCORE_WORKERS) -> list:
    """Score every generated clip (spec.path) and add ONE low_motion warning listing the clips whose
    score is below `threshold`. threshold <= 0 disables the check (nothing is scored). All scores land
    in report.clips["motion_scores"] ({clip name: score}). Returns [(clip name, score)] of the low
    clips. Clips that cannot be scored are skipped; a crashing scorer never raises."""
    if not threshold or threshold <= 0:
        return []
    clips = [(Path(s.path).stem, job.resolve(s.path)) for s in specs if s.path]
    if not clips:
        return []

    def score(item) -> Optional[float]:
        try:
            return scorer(item[1])
        except Exception as e:  # noqa: BLE001
            logger.warning("Motion scorer failed on %s: %s", item[1], e)
            return None

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(clips)))) as pool:
        scores = list(pool.map(score, clips))
    scored = [(name, value) for (name, _), value in zip(clips, scores) if value is not None]
    report.clips["motion_scores"] = dict(scored)
    low = [(name, value) for name, value in scored if value < threshold]
    if low:
        listing = ", ".join(f"{name} {value:.2f}" for name, value in low)
        report.warn("low_motion", f"{len(low)} of {len(scored)} clips barely move ({listing})",
                    {"threshold": threshold, "scored": len(scored),
                     "clips": [{"clip": name, "score": value} for name, value in low]})
    return low
