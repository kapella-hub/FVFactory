"""Render orchestration for one job (spec §9): shot render -> mix -> loudnorm + copy-mux -> checks.
Shared by run_pipeline (main.py) and --rerender."""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

from app.cin.align import Alignment
from app.cin.clip_sourcing import probe_clip_duration
from app.cin.job import JobPaths, open_job
from app.cin.mix import mix_audio
from app.cin.renderer import ShotRenderer, caption_overlays
from app.cin.report import RunReport
from app.cin.shot_plan import ClipSpec, SegmentRequest, ShotPlan, build_shot_plan
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
        written = _swap_final(job, final_tmp, report)
        loud = measure_loudness(written)
        report.loudness = ({"I": loud["input_i"], "TP": loud["input_tp"], "LRA": loud["input_lra"]}
                           if loud else None)
        ok, issues = is_platform_safe(written)
        report.platform_safe = {"ok": ok, "issues": issues}
        if not ok:
            report.warn("platform_check_failed", f"Platform check failed: {issues}", {"issues": list(issues)})
            logger.warning("Platform check failed for %s: %s", written, issues)

    shutil.rmtree(job.render_tmp, ignore_errors=True)
    logger.info("Rendered %s", written)
    return written


def _swap_final(job: JobPaths, final_tmp: Path, report: RunReport, tries: int = 3, delay: float = 0.5) -> Path:
    """Move final_tmp into place, keeping the old final as final.prev.mp4. On Windows either file may
    be open in a player; retry briefly, then keep the render as final.<timestamp>.mp4 (never discard it)."""
    for attempt in range(tries):
        try:
            if job.final.exists():
                os.replace(job.final, job.final_prev)
            os.replace(final_tmp, job.final)
            return job.final
        except PermissionError:
            if attempt < tries - 1:
                time.sleep(delay)
    alt = job.root / f"final.{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
    os.replace(final_tmp, alt)
    report.warn("final_swap_failed", f"final.mp4 is locked; render kept as {alt.name}", {"path": str(alt)})
    logger.warning("final.mp4 locked (open in a player?); new render written to %s", alt)
    return alt


# ---------------------------------------------------------------- re-render (spec §9.3)

_CARRIED_WARNINGS = ("alignment_fallback", "prompt_count_normalized", "clip_retry")


def clip_specs_from_plan(plan: ShotPlan, job: JobPaths, enable_motion: bool = True) -> list:
    """Rebuild ClipSpecs from a saved plan. Clip lengths are re-probed; missing clip files
    become failed segments (stills) when motion was enabled for the job."""
    specs = []
    for sc in plan.scenes:
        for i, seg in enumerate(sc.segments):
            # Naming lives in SegmentRequest.name (Task 5); do not re-implement it here.
            name = SegmentRequest(sc.index, i, seg.t0, seg.t1, seg.requested_len, chained=i > 0).name
            path = seg.clip if seg.clip and job.resolve(seg.clip).exists() else None
            last = job.last_frame(name)
            specs.append(ClipSpec(
                sc.index, i, seg.t0, seg.t1, seg.requested_len, seg.start_image,
                path=path,
                duration=probe_clip_duration(job.resolve(path)) if path else 0.0,
                last_frame=job.rel(last) if path and last.exists() else None,
                failed=enable_motion and path is None,
            ))
    return specs


def rebuild_plan(job: JobPaths, pacing: str, enable_motion: bool = True) -> ShotPlan:
    """Same scenes and clips, new cuts: --pacing only changes cuts within scenes (spec §9.3)."""
    alignment = Alignment.from_json(json.loads(job.alignment.read_text(encoding="utf-8")))
    old = ShotPlan.load(job.shot_plan)
    return build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))


def rerender_job(job_dir, *, pacing: Optional[str] = None, subtitle_style: Optional[str] = None,
                 no_sfx: bool = False, no_music: bool = False, color_grade: Optional[str] = None) -> str:
    """Rebuild final.mp4 from sources/ with zero API calls (spec §9.3)."""
    job = open_job(job_dir)
    prev = RunReport.load(job.report) if job.report.exists() else RunReport(job=job.name)
    opts = RenderOptions.from_json(prev.options)
    if pacing:
        opts.pacing = pacing
    if subtitle_style:
        opts.subtitle_style = subtitle_style
    if no_sfx:
        opts.enable_sfx = False
    if no_music:
        opts.enable_music = False
    if color_grade is not None:
        opts.color_grade = color_grade

    report = RunReport(job=job.name, options={**prev.options, **opts.to_json(), "rerender": True})
    report.cost = prev.cost                      # no new spend
    report.clips = prev.clips
    report.warnings = [w for w in prev.warnings if w.get("code") in _CARRIED_WARNINGS]
    if job.report.exists():                      # keep the good render's record next to final.prev.mp4
        shutil.copy2(job.report, job.root / "run_report.prev.json")
    try:
        with report.stage("plan"):
            plan = rebuild_plan(job, opts.pacing, enable_motion=bool(prev.options.get("enable_motion", True)))
        for w in plan.warnings:
            report.warn(w["code"], w["message"], w["detail"])
        final = render_job(job, plan, opts, report)
        plan.save(job.shot_plan)             # only once the new render exists
        report.status = "ok"
        return str(final)
    except Exception as e:
        report.status = "failed"
        report.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        report.save(job.report)
