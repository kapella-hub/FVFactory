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
from app.cin.audio_dsp import speech_windows
from app.cin.audio_io import SR, AudioDecodeError, decode_audio
from app.cin.mix import mix_tracks
from app.cin.music_library import UsageStore, asset_key, asset_path, list_tracks, select_track
from app.cin.sfx_library import SfxFile, place_sfx, scan_sfx
from app.cin.captions import build_caption_layer
from app.cin.renderer import ShotRenderer
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
    music_source: str = "any"          # mine | generated | any | none (spec §8.1)
    strict: bool = False

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: Optional[dict]) -> "RenderOptions":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


MIN_TRACK_SECONDS = 3.0     # shorter "tracks" (blips, jingles) are skipped, never looped as a bed


def music_wanted(options: RenderOptions) -> bool:
    return bool(options.enable_music and settings.music_enabled and options.music_source != "none")


def _usable_track(path: Path, report: RunReport) -> bool:
    try:
        head = decode_audio(path, max_seconds=MIN_TRACK_SECONDS + 0.5)
    except AudioDecodeError as e:
        report.warn("music_track_skipped", f"Unreadable music file skipped: {Path(path).name}",
                    {"file": asset_key(path), "reason": str(e)[:300]})
        return False
    if len(head) < MIN_TRACK_SECONDS * SR:
        report.warn("music_track_skipped",
                    f"Music file shorter than {MIN_TRACK_SECONDS:.0f}s skipped: {Path(path).name}",
                    {"file": asset_key(path), "seconds": round(len(head) / SR, 2)})
        return False
    return True


def pick_music(options: RenderOptions, report: RunReport, keep: Optional[str] = None) -> Optional[Path]:
    """spec §8.1: least-recently-used usable track for options.music_mood / music_source.
    keep (a re-render's previous track) is reused as-is when it still exists and decodes."""
    if not music_wanted(options):
        return None
    if keep and asset_path(keep).is_file() and _usable_track(asset_path(keep), report):
        return asset_path(keep)
    candidates = list_tracks(settings.music_dir, options.music_mood, options.music_source)
    path = select_track(candidates, UsageStore(), accept=lambda p: _usable_track(p, report))
    if path is None:
        report.warn("music_missing",
                    f"No usable music for mood '{options.music_mood or 'any'}' "
                    f"(music_source={options.music_source}) under {settings.music_dir}; "
                    "add tracks or run --build-music-library",
                    {"mood": options.music_mood, "music_source": options.music_source,
                     "candidates": len(candidates)})
    return path


def sfx_pool(report: RunReport) -> dict:
    """{kind: [SfxFile]} from settings.sfx_dir; unreadable files are skipped with a warning."""
    pool = {}
    for kind, paths in scan_sfx(settings.sfx_dir).items():
        files = []
        for p in paths:
            try:
                frames = len(decode_audio(p, channels=1, max_seconds=60.0))
            except AudioDecodeError as e:
                report.warn("sfx_file_skipped", f"Unreadable SFX file skipped: {p.name}",
                            {"file": asset_key(p), "reason": str(e)[:300]})
                continue
            files.append(SfxFile(p, kind, frames / SR))
        pool[kind] = files
    return pool


def _speech_spans(job: JobPaths, plan: ShotPlan) -> list:
    """Word (t0, t1) timings for ducking: alignment.json tokens, else the plan's caption words."""
    if job.alignment.exists():
        try:
            al = Alignment.from_json(json.loads(job.alignment.read_text(encoding="utf-8")))
            return [(t.t0, t.t1) for t in al.tokens]
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("alignment.json unreadable for ducking (%s); using caption timings", e)
    return [(w.t0, w.t1) for g in plan.captions for w in g.words]


def render_job(job: JobPaths, plan: ShotPlan, options: RenderOptions, report: RunReport) -> Path:
    """Render plan into job.final. A previous final.mp4 is kept as final.prev.mp4."""
    job.render_tmp.mkdir(parents=True, exist_ok=True)
    video_tmp = job.render_tmp / "video.mp4"
    final_tmp = job.render_tmp / "final.mp4"

    with report.stage("render"):
        captions = build_caption_layer(plan, options.subtitle_style, report=report,
                                       enable_subtitles=options.enable_subtitles)
        ShotRenderer(plan, job, video_style=options.video_style, color_grade=options.color_grade or None,
                     captions=captions).render(video_tmp)

    with report.stage("mix"):
        sfx_on = options.enable_sfx and settings.enable_sfx
        windows = speech_windows(_speech_spans(job, plan), plan.duration)
        music_path = pick_music(options, report, keep=(plan.music or {}).get("file"))
        pool = sfx_pool(report) if sfx_on else {}
        plan.sfx = place_sfx(plan, pool, seed=job.name) if sfx_on else []
        if sfx_on and not any(pool.values()):
            report.warn("sfx_missing", f"No usable SFX files under {settings.sfx_dir} "
                        "(add whoosh*/impact*/riser* files or run --build-sfx-library)", {})
        info = mix_tracks(job.narration, job.mix, plan.duration, music_path=music_path,
                          duck_windows=windows, sfx=[{**e, "path": asset_path(e["file"])} for e in plan.sfx])
        for err in info["sfx_errors"]:
            report.warn("sfx_file_skipped", f"SFX file failed to decode during the mix: {err['file']}", err)
        if music_path is not None and info["music"] is None:
            report.warn("music_missing", f"Music file failed during the mix: {music_path.name}",
                        {"file": asset_key(music_path), "reason": info["music_error"]})
        plan.music = ({"file": asset_key(music_path), "mood": options.music_mood,
                       "source": options.music_source, "duck_windows": windows}
                      if info["music"] else None)
        report.options["music_file"] = plan.music["file"] if plan.music else None

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

_CARRIED_WARNINGS = ("prompt_count_normalized", "clip_retry")


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
    plan = build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))
    plan.hook_headline = old.hook_headline        # set from script.hook at generation; not in alignment.json
    plan.music = old.music          # same track unless --music-source asks for a new one (spec §9.3)
    if alignment.fallback:          # re-derived from alignment.json, never carried from the old report
        plan.warnings.append({
            "code": "alignment_fallback",
            "message": f"Scene timing fell back to word counts ({alignment.reason})",
            "detail": {"reason": alignment.reason, "match_ratio": round(alignment.match_ratio, 4)}})
    return plan


def rerender_job(job_dir, *, pacing: Optional[str] = None, subtitle_style: Optional[str] = None,
                 no_sfx: bool = False, no_music: bool = False, color_grade: Optional[str] = None,
                 music_source: Optional[str] = None) -> str:
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
    if music_source:
        opts.music_source = music_source

    report = RunReport(job=job.name, options={**prev.options, **opts.to_json(), "rerender": True})
    report.cost = prev.cost                      # no new spend
    report.clips = prev.clips
    report.warnings = [w for w in prev.warnings if w.get("code") in _CARRIED_WARNINGS]
    if job.report.exists():                      # keep the good render's record next to final.prev.mp4
        shutil.copy2(job.report, job.root / "run_report.prev.json")
    try:
        with report.stage("plan"):
            plan = rebuild_plan(job, opts.pacing, enable_motion=bool(prev.options.get("enable_motion", True)))
            if music_source:
                plan.music = None       # re-select from the requested source
        for w in plan.warnings:
            report.warn(w["code"], w["message"], w["detail"])
        final = render_job(job, plan, opts, report)
        try:
            plan.save(job.shot_plan)         # only once the new render exists
        except Exception as e:  # noqa: BLE001 - the render succeeded; keep it
            logger.warning("Could not save shot_plan.json after rerender: %s", e)
            report.warn("plan_save_failed", f"shot_plan.json not updated after rerender ({e})", {"error": str(e)})
        report.status = "ok"
        return str(final)
    except Exception as e:
        report.status = "failed"
        report.error = f"{type(e).__name__}: {e}"
        raise
    finally:
        report.save_quietly(job.report)
