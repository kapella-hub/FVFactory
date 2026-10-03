"""Render orchestration for one job (spec §9): shot render -> mix -> loudnorm + copy-mux -> checks.
Shared by run_pipeline (main.py) and --rerender."""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from app.cin.job import JobPaths
from app.cin.mix import mix_audio
from app.cin.renderer import ShotRenderer, caption_overlays
from app.cin.report import RunReport
from app.cin.shot_plan import ShotPlan
from app.config import settings
from app.encoding import is_platform_safe, measure_loudness, mux_final

logger = logging.getLogger(__name__)


@dataclass
class RenderOptions:
    pacing: str = "standard"
    subtitle_style: str = "bold_impact"
    video_style: str = "photorealistic"
    color_grade: str = ""
    enable_subtitles: bool = True
    enable_music: bool = True
    enable_sfx: bool = True
    music_mood: str = ""
    strict: bool = False

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: Optional[dict]) -> "RenderOptions":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


def pick_music(options: RenderOptions, report: RunReport) -> Optional[Path]:
    """Existing music path (VideoEditor._get_random_music_file); Phase C replaces it."""
    if not (options.enable_music and settings.music_enabled):
        return None
    from app.video_editor import VideoEditor
    path = VideoEditor(music_mood=options.music_mood)._get_random_music_file(options.music_mood)
    if path is None:
        report.warn("music_missing", f"No music files for mood '{options.music_mood or 'any'}' "
                    f"under {settings.music_dir}", {"mood": options.music_mood})
    return path


def render_job(job: JobPaths, plan: ShotPlan, options: RenderOptions, report: RunReport) -> Path:
    """Render plan into job.final. A previous final.mp4 is kept as final.prev.mp4."""
    job.render_tmp.mkdir(parents=True, exist_ok=True)
    video_tmp = job.render_tmp / "video.mp4"
    final_tmp = job.render_tmp / "final.mp4"

    with report.stage("render"):
        overlays = caption_overlays(plan, options.subtitle_style) if options.enable_subtitles else []
        ShotRenderer(plan, job, video_style=options.video_style,
                     color_grade=options.color_grade or None).render(video_tmp, overlays)

    with report.stage("mix"):
        sfx_on = options.enable_sfx and settings.enable_sfx
        info = mix_audio(job.narration, job.mix, plan.duration, music_path=pick_music(options, report),
                         scene_starts=[s.t0 for s in plan.scenes], enable_sfx=sfx_on)
        report.options["music_file"] = info["music"]
        if sfx_on and not info["sfx"]:
            report.warn("sfx_missing", f"No SFX files under {settings.sfx_dir}", {})

    with report.stage("encode"):
        measured = measure_loudness(job.mix)
        if measured is None:
            report.warn("loudness_skipped", "Mix is silent or unmeasurable; loudnorm skipped", {})
        mux_final(video_tmp, job.mix, final_tmp, measured)
        if job.final.exists():
            os.replace(job.final, job.final_prev)
        os.replace(final_tmp, job.final)
        loud = measure_loudness(job.final)
        report.loudness = ({"I": loud["input_i"], "TP": loud["input_tp"], "LRA": loud["input_lra"]}
                           if loud else None)
        ok, issues = is_platform_safe(job.final)
        report.platform_safe = {"ok": ok, "issues": issues}

    shutil.rmtree(job.render_tmp, ignore_errors=True)
    logger.info("Rendered %s", job.final)
    return job.final
