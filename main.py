"""
FVFactory - Automated short-form video creation

Pipeline: Topic -> Script -> Audio/Images or Animated Portrait -> MP4
"""

import argparse
import json
import logging
import math
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app import llm
from app.config import settings
from app.content_engine import ScriptGenerator
from app.asset_manager import AssetManager
from app.video_editor import VideoEditor
from app.animator import PortraitAnimator, AnimatorError
from app.trend_scout import TrendScout
from app.motion_gen import CLASSIC_CLIP_SECONDS, MotionGenerator, clip_model_for, snap_duration
from app.cost_tracker import CostTracker
from app.metadata_gen import MetadataGenerator
from app.uploader import YouTubeUploader, UploaderError
from app.cin.align import align
from app.cin.clip_sourcing import StrictModeError, generate_segment_clips
from app.cin.editor import RenderOptions, render_job
from app.cin.job import create_job, prune_sources
from app.cin.motion_check import check_clip_motion
from app.cin.report import RunReport
from app.cin.caption_groups import make_hook_headline, script_headline_text
from app.cin.shot_plan import PACING, build_shot_plan, plan_segments
from app.cin.music_library import MOODS, MUSIC_SOURCES
from app.cin.cost_estimate import (CostCapError, estimate_classic, estimate_pre_clips, estimate_pre_tts, exceeds_cap, llm_calls,
                                   llm_cost_item, stage_costs, tts_cost_item, tts_units)
from app.cin.tiers import QUALITY_TIERS, resolve_clip_model

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


def validate_config(use_mock: bool = False, enable_motion: bool = True) -> bool:
    """Validate that required API keys are configured for selected providers.
    --mock makes no image or motion API calls, so those keys are not required then."""
    errors = []

    # LLM: only need OpenAI key if using OpenAI provider
    if settings.llm_provider == "openai" or settings.provider_mode == "api":
        if not settings.openai_api_key:
            errors.append("OPENAI_API_KEY is required when llm_provider=openai or provider_mode=api")
    cli = llm.CLI_COMMANDS.get(settings.llm_provider)
    if cli and not shutil.which(cli):            # not an error: the fallback chain may still answer
        fallback = llm.provider_chain()[1:]
        logger.warning("LLM provider %s: the %r CLI is not on PATH; scripts will use the fallback chain: %s",
                       settings.llm_provider, cli,
                       ", ".join(fallback) if fallback else "none (script generation will fail)")

    if not use_mock:
        # Image: check key for selected provider
        if settings.image_provider == "fal":
            if not settings.fal_api_key:
                errors.append("FAL_API_KEY is required when image_provider=fal")
        elif settings.image_provider == "replicate":
            if not settings.replicate_api_token:
                errors.append("REPLICATE_API_TOKEN is required when image_provider=replicate")

    if not use_mock and enable_motion:
        # Motion: check key for selected provider
        if settings.motion_provider == "fal":
            if not settings.fal_api_key:
                errors.append("FAL_API_KEY is required when motion_provider=fal")
        elif settings.motion_provider == "replicate":
            if not settings.replicate_api_token:
                errors.append("REPLICATE_API_TOKEN is required when motion_provider=replicate")

    # TTS: always needs at least one TTS key
    if not settings.elevenlabs_api_key and not settings.openai_api_key:
        errors.append("ELEVENLABS_API_KEY or OPENAI_API_KEY required for audio")

    if errors:
        for error in errors:
            logger.error(error)
        return False

    return True


def resolve_voice(voice: Optional[str] = None, niche: Optional[str] = None,
                   video_style: Optional[str] = None) -> Optional[str]:
    """Resolve a voice preset name or 'auto' to an ElevenLabs voice ID.

    When voice is 'auto', picks based on niche and video style:
    - Niche mapping is primary (stoicism→bill, tech→daniel, etc.)
    - Video style adjusts the default when niche has no specific mapping:
      energetic styles (cartoon, anime, pixel_art, comic_book) → josh
      dramatic styles (noir, oil_painting) → bill
      artistic styles (watercolor, illustration, stop_motion) → george
      technical styles (3d_render, photorealistic) → daniel

    Returns None to use the default from config.
    """
    if not voice:
        return None

    if voice == "auto":
        niche_key = (niche or "").lower().strip()

        # First try niche-specific mapping
        preset = settings.voice_niche_map.get(niche_key)

        # If no niche match, use video style to pick voice
        if not preset and video_style:
            STYLE_VOICE = {
                "cartoon": "josh",
                "anime": "josh",
                "pixel_art": "josh",
                "comic_book": "josh",
                "noir": "bill",
                "oil_painting": "bill",
                "watercolor": "george",
                "illustration": "george",
                "stop_motion": "george",
                "3d_render": "daniel",
                "photorealistic": "daniel",
            }
            preset = STYLE_VOICE.get(video_style)

        preset = preset or "george"  # safe default
        voice_id = settings.voice_presets.get(preset)
        logger.info(f"Auto-selected voice '{preset}' for niche='{niche_key}' style='{video_style or ''}'")
        return voice_id

    # Direct preset name
    if voice.lower() in settings.voice_presets:
        return settings.voice_presets[voice.lower()]

    # Assume it's a raw ElevenLabs voice ID
    return voice


def resolve_music_mood(niche: Optional[str] = None, video_style: Optional[str] = None) -> str:
    """Pick a music mood based on niche and video style.

    Returns a mood string matching a subfolder in assets/music/:
      epic, chill, upbeat, dark, cinematic

    Falls back to empty string (root music dir) if no match.
    """
    # Style takes priority for mood
    STYLE_MOOD = {
        "cartoon": "upbeat",
        "anime": "epic",
        "pixel_art": "upbeat",
        "comic_book": "epic",
        "stop_motion": "upbeat",
        "noir": "dark",
        "oil_painting": "cinematic",
        "watercolor": "chill",
        "illustration": "chill",
        "3d_render": "cinematic",
        "photorealistic": "cinematic",
    }

    NICHE_MOOD = {
        "stoicism": "cinematic",
        "philosophy": "chill",
        "self-improvement": "epic",
        "motivation": "epic",
        "history": "cinematic",
        "science": "cinematic",
        "tech": "upbeat",
        "technology": "upbeat",
        "finance": "cinematic",
        "crypto": "dark",
        "gaming": "upbeat",
        "entertainment": "upbeat",
        "pop culture": "upbeat",
        "health": "chill",
        "lifestyle": "chill",
    }

    mood = ""
    if video_style:
        mood = STYLE_MOOD.get(video_style, "")
    if not mood and niche:
        mood = NICHE_MOOD.get(niche.lower().strip(), "")

    logger.info(f"Music mood: '{mood}' for niche='{niche or ''}' style='{video_style or ''}'")
    return mood


def resolve_subtitle_style(subtitle_style: str, video_style: Optional[str] = None) -> str:
    """Auto-select subtitle style based on video style when set to 'auto' or default.

    Available styles: bold_impact, clean_minimal, neon_glow, fire
    """
    if subtitle_style == "auto" and video_style:
        STYLE_SUBTITLE = {
            "cartoon": "bold_impact",
            "anime": "neon_glow",
            "pixel_art": "neon_glow",
            "comic_book": "bold_impact",
            "stop_motion": "bold_impact",
            "noir": "clean_minimal",
            "oil_painting": "clean_minimal",
            "watercolor": "clean_minimal",
            "3d_render": "neon_glow",
            "illustration": "clean_minimal",
            "photorealistic": "fire",
        }
        resolved = STYLE_SUBTITLE.get(video_style, "bold_impact")
        logger.info(f"Auto-selected subtitle style '{resolved}' for video style '{video_style}'")
        return resolved
    return subtitle_style


def _print_script(script) -> None:
    print()
    print("=" * 50)
    print("GENERATED SCRIPT")
    print("=" * 50)
    print(f"\nHOOK: {script.hook}")
    print(f"\nBODY:\n{script.body}")
    print("\nIMAGE PROMPTS:")
    for i, prompt in enumerate(script.image_prompts, 1):
        print(f"  {i}. {prompt}")
    print(f"\nKEYWORDS: {', '.join(script.keywords)}")
    print("=" * 50)
    print()


def _record_narration(report: RunReport, seconds: float) -> None:
    """Actual narration length vs the word budget's target (spec 2026-10-03 §7). Report only, no gate."""
    s = report.script
    s["narration_seconds"] = round(seconds, 2)
    if s.get("target_seconds"):
        s["seconds_vs_target"] = round(seconds - s["target_seconds"], 2)
    if s.get("words") and seconds > 0:
        s["words_per_second"] = round(s["words"] / seconds, 2)


def _cost_checkpoint(report: RunReport, estimate, max_cost: float, job) -> None:
    """Store an estimate in run_report.json; over the cap -> cost_cap_exceeded + CostCapError, before
    the next paid stage. Never degrades to stills or a cheaper model (spec 2026-10-03 §4.5, §8)."""
    report.cost["estimated"][estimate.stage] = estimate.to_json()
    logger.info("Cost estimate (%s): $%.2f total, $%.2f motion (%s)", estimate.stage, estimate.total,
                estimate.clips, estimate.model)
    if not exceeds_cap(estimate.total, max_cost):
        return
    report.warn("cost_cap_exceeded",
                f"Estimated cost ${estimate.total:.2f} exceeds the ${max_cost:.2f} cap at {estimate.stage}",
                {"stage": estimate.stage, "estimate": estimate.total, "cap": max_cost})
    if estimate.stage == "pre_tts":
        where = "stopped before text-to-speech; only the script was generated"
    else:
        where = f"stopped before the motion clips; script, narration and images are kept in {job.root}"
    raise CostCapError(f"Estimated cost ${estimate.total:.2f} exceeds the ${max_cost:.2f} per-video cap "
                       f"({estimate.stage}, model {estimate.model}): {where}")


def _run_shot_editor(job, script, narration: str, duration: float, options: RenderOptions,
                     report: RunReport, asset_manager: AssetManager, use_mock_images: bool,
                     motion_on: bool, model, max_cost: float = 0.0, llm_n: int = 1,
                     paid: Optional[dict] = None):
    """Spec §4 order: (align || images) -> segments -> cost checkpoint 2 -> clips -> shot plan ->
    render + encode. model is the run's resolved ClipModel (app.cin.tiers.resolve_clip_model)."""

    def make_images():
        start = time.perf_counter()
        try:
            return asset_manager.generate_images(script.image_prompts, use_mock=use_mock_images,
                                                 output_dir=job.images)
        finally:
            report.durations["images"] = round(time.perf_counter() - start, 2)

    with ThreadPoolExecutor(max_workers=1) as pool:
        images_future = pool.submit(make_images)
        with report.stage("align"):
            alignment, words = align(job.narration, script.scene_texts, narration, duration,
                                     num_scenes=len(script.image_prompts))
        image_paths = images_future.result()
    job.words.write_text(json.dumps(words, indent=1), encoding="utf-8")
    job.alignment.write_text(json.dumps(alignment.to_json(), indent=1), encoding="utf-8")
    if alignment.fallback:
        report.warn("alignment_fallback", f"Scene timing fell back to word counts ({alignment.reason})",
                    {"reason": alignment.reason, "match_ratio": round(alignment.match_ratio, 4)})

    requests_ = plan_segments(alignment, model.durations if motion_on else None)
    costs = stage_costs(narration_chars=len(narration), image_count=len(image_paths),
                        mock_images=use_mock_images, llm_calls=llm_n, llm_provider=report.script.get("llm_provider"))
    _cost_checkpoint(report, estimate_pre_clips(requests_, model=model, motion_on=motion_on, costs=costs),
                     max_cost, job)
    with report.stage("clips"):
        specs = generate_segment_clips(
            requests_, image_paths, script.motion_prompts, job, report,
            enable_motion=motion_on, model_key=model.key,
            fallback_model=settings.fal_video_fallback_model if settings.motion_provider == "fal" else None,
        )
    if paid is not None:
        paid["specs"] = specs            # paid for now, even if the render below fails
    if motion_on and settings.low_motion_threshold > 0:
        with report.stage("motion_check"):
            try:
                check_clip_motion(specs, job, report, settings.low_motion_threshold)
            except Exception as e:  # noqa: BLE001 - an advisory check must never fail a paid run
                logger.warning("Low-motion check failed: %s", e)
    plan = build_shot_plan(alignment, options.pacing, specs, roles=script.scene_roles or None)
    plan.hook_headline = make_hook_headline(script.hook, plan.duration, headline=script.hook_headline)
    if options.enable_subtitles and script_headline_text(script.hook_headline) is None:   # headline is drawn only with captions
        report.warn("hook_headline_fallback",
                    "Script hook_headline missing or longer than 6 words; "
                    + ("using the hook's first sentence" if plan.hook_headline else "no headline shown"),
                    {"hook_headline": script.hook_headline})
    for w in plan.warnings:
        report.warn(w["code"], w["message"], w["detail"])
    plan.save(job.shot_plan)
    if options.strict and any(w["code"] == "still_fallback" for w in plan.warnings):
        raise StrictModeError("strict mode: the plan contains still-fallback shots (see run_report.json); "
                              f"sources kept in {job.root} for --rerender")
    final = render_job(job, plan, options, report)
    try:
        plan.save(job.shot_plan)           # again: render_job filled plan.music / plan.sfx
    except Exception as e:  # noqa: BLE001 - final.mp4 exists; a locked plan file must not fail the run
        logger.warning("Could not save shot_plan.json after render: %s", e)
        report.warn("plan_save_failed", f"shot_plan.json not updated after render ({e})", {"error": str(e)})
    return str(final), image_paths, specs


def _run_classic(job, script, audio_result, options: RenderOptions, asset_manager: AssetManager,
                 use_mock_images: bool, enable_motion: bool, persona: Optional[str], use_chroma_key: bool,
                 paid: Optional[dict] = None):
    """The pre-shot-editor path (--classic, or persona hybrid mode), writing into the job folder."""
    classic_music = options.enable_music and options.music_source != "none"
    image_paths = asset_manager.generate_images(script.image_prompts, use_mock=use_mock_images,
                                                output_dir=job.images)
    motion_clip_paths = None
    if enable_motion and script.motion_prompts and not use_mock_images:
        motion_clip_paths = MotionGenerator(temp_dir=str(job.clips)).generate_all_clips(
            image_paths, script.motion_prompts)
        if paid is not None:
            paid["classic_clips"] = motion_clip_paths

    video_editor = VideoEditor(music_mood=options.music_mood)
    video_editor.output_dir = job.root

    if persona:
        animator = PortraitAnimator()
        persona_path = animator.get_persona_path(persona)
        if not persona_path:
            raise AnimatorError(f"Persona not found: {persona}")
        animated = animator.animate_portrait(audio_path=audio_result.file_path,
                                             persona_image_path=str(persona_path),
                                             output_filename=f"animated_{job.name}.mp4")
        if animated:
            output = video_editor.assemble_hybrid_video(
                audio_path=audio_result.file_path, image_paths=image_paths, talking_head_path=animated,
                output_filename="final.mp4", enable_subtitles=options.enable_subtitles,
                enable_music=classic_music, use_chroma_key=use_chroma_key)
            return output, image_paths, motion_clip_paths
        logger.warning("Portrait animation failed (content filter), falling back to standard mode")

    output = video_editor.assemble_video(
        audio_path=audio_result.file_path, image_paths=image_paths, output_filename="final.mp4",
        hook_text=script.hook, enable_subtitles=options.enable_subtitles, enable_music=classic_music,
        motion_clip_paths=motion_clip_paths, pacing_hints=script.pacing_hints or None,
        subtitle_style=options.subtitle_style, color_grade=options.color_grade or None,
        enable_sfx=options.enable_sfx, title=script.hook, scene_texts=script.scene_texts or None,
    )
    return output, image_paths, motion_clip_paths


def _log_costs(video_id: str, report: RunReport, narration: str, use_mock_images: bool,
               image_count: int, specs=None, classic_clips=None, llm_n: int = 1) -> float:
    """Cost bookkeeping: after a successful render, or for what a failed run already paid
    (narration "" = no TTS yet). It must never fail the run (an unknown clip
    model or a cost-file error is logged as a warning and skipped). Units follow
    app.cin.cost_estimate.stage_costs, so the pre_clips estimate and the log agree."""
    def attempt(label: str, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - cost logging is best-effort
            logger.warning("Cost logging skipped (%s): %s", label, e)
            return None

    tracker = attempt("tracker", CostTracker)
    if tracker is None:
        return 0.0

    llm_item = llm_cost_item(report.script.get("llm_provider"))   # the provider that answered, when known
    for _ in range(llm_n):                       # the draft, plus the length revision when one was attempted
        attempt("llm", lambda: tracker.log_cost(video_id, llm_item))
    tts_item = tts_cost_item()
    if tts_item and narration:                   # "" = the run stopped before text-to-speech
        attempt("tts", lambda: tracker.log_cost(video_id, tts_item, quantity=tts_units(len(narration))))
    if not use_mock_images and image_count:
        attempt("images", lambda: tracker.log_cost(video_id, "flux_image", quantity=image_count))
    for spec in specs or []:
        if spec.path:
            attempt(f"clip {spec.model}",
                    lambda spec=spec: tracker.log_clip(video_id, spec.model, seconds=spec.billed_len or spec.requested_len))
    if classic_clips:
        done = sum(1 for c in classic_clips if c is not None)
        if done:
            def classic_cost():
                model = clip_model_for(settings.motion_provider, settings.fal_video_model)
                tracker.log_clip(video_id, model.key, count=done,
                                 seconds=snap_duration(CLASSIC_CLIP_SECONDS, model.durations) or CLASSIC_CLIP_SECONDS)
            attempt("classic clips", classic_cost)
    attempt("save", tracker.save)
    total = 0.0
    try:
        total = tracker.get_video_cost(video_id)
        report.cost.update({"actual": tracker.get_video_items(video_id), "total": total})   # keeps estimated + cap
    except Exception as e:  # noqa: BLE001
        logger.warning("Cost summary skipped: %s", e)
    logger.info(f"Total cost for this video: ${total:.2f}")
    return total


def _log_partial_costs(job, report: RunReport, paid: dict, use_mock_images: bool) -> None:
    """A failed or capped run still logs what it already paid for: the script calls, the narration
    when TTS ran, the images on disk, and any clips that were generated. Skipped when _log_costs
    already ran (a failure after cost logging) or nothing was paid yet."""
    if paid["logged"] or not paid["llm_n"]:
        return
    try:                         # best-effort: never replace the exception that failed the run
        image_count = sum(1 for p in job.images.iterdir() if p.is_file()) if job.images.is_dir() else 0
        _log_costs(job.name, report, paid["narration"], use_mock_images, image_count, paid["specs"],
                   paid["classic_clips"], llm_n=paid["llm_n"])
    except Exception as e:  # noqa: BLE001
        logger.warning("Cost logging for the failed run skipped: %s", e)


def _tag_job_dir(exc: BaseException, job_root) -> None:
    """Callers (web UI, scheduler) find run_report.json of a failed run via exc.job_dir.
    The exception type is unchanged; an exception that refuses attributes is left alone."""
    try:
        exc.job_dir = str(job_root)
    except (AttributeError, TypeError):
        pass


def run_pipeline(
    topic: str,
    use_mock_images: bool = False,
    enable_subtitles: bool = True,
    enable_music: bool = True,
    persona: Optional[str] = None,
    use_chroma_key: bool = False,
    # V2 parameters
    enable_motion: bool = True,
    subtitle_style: str = "bold_impact",
    enable_sfx: bool = True,
    voice: Optional[str] = None,
    upload: bool = False,
    niche: Optional[str] = None,
    # V3 parameters
    video_style: str = "",
    video_duration: str = "",
    # Shot editor (spec 2026-10-02)
    pacing: Optional[str] = None,
    strict: Optional[bool] = None,
    classic: bool = False,
    music_source: Optional[str] = None,
    # Quality tiers (spec 2026-10-03)
    quality_tier: Optional[str] = None,
    max_cost: Optional[float] = None,
) -> str:
    """
    Run the full video generation pipeline into output/<job>/ and return the path of final.mp4.

    Order (spec §4): script -> TTS -> (align || images) -> clip segments -> motion clips ->
    shot plan -> render -> encode. Sources stay in output/<job>/sources/ (also after a failure),
    so a fixed run can be rebuilt with `python main.py --rerender output/<job>`.
    pacing/strict default to settings.pacing / settings.strict. classic=True (or --classic, or a
    persona) uses the old VideoEditor path; renderer errors never fall back to it silently.
    music_source defaults to settings.music_source (mine | generated | any | none).
    quality_tier (standard | premium | custom) picks the motion model; max_cost (USD, 0 = no cap)
    stops the run with CostCapError at a cost checkpoint. Both default to the Settings values.
    """
    pacing = pacing or settings.pacing
    if pacing not in PACING:
        raise ValueError(f"Unknown pacing {pacing!r}; choose one of {sorted(PACING)}")
    strict = settings.strict if strict is None else strict
    music_source = music_source or settings.music_source
    if music_source not in MUSIC_SOURCES:
        raise ValueError(f"Unknown music_source {music_source!r}; choose one of {list(MUSIC_SOURCES)}")
    tier_explicit = bool(quality_tier)
    quality_tier = quality_tier or settings.quality_tier
    if quality_tier not in QUALITY_TIERS:
        raise ValueError(f"Unknown quality_tier {quality_tier!r}; choose one of {', '.join(QUALITY_TIERS)}")
    max_cost = settings.max_cost_per_video if max_cost is None else max_cost
    if isinstance(max_cost, bool) or not isinstance(max_cost, (int, float)) \
            or not math.isfinite(max_cost) or max_cost < 0:
        raise ValueError(f"max_cost must be a number >= 0 (0 = no cap), got {max_cost!r}")
    max_cost = float(max_cost)
    classic = classic or not settings.cinematic_enabled or bool(persona)
    motion_on = enable_motion and not use_mock_images
    # Classic / persona runs keep settings.fal_video_model and have no cost checkpoints (spec §8.7).
    model = clip_model_for(settings.motion_provider, settings.fal_video_model) if classic else \
        resolve_clip_model(quality_tier, settings.motion_provider, settings.fal_video_model)

    prune_sources(settings.output_dir, settings.keep_sources_days)
    job = create_job(topic, settings.output_dir)
    options = RenderOptions(
        pacing=pacing, subtitle_style=subtitle_style, video_style=video_style or settings.video_style,
        color_grade=settings.color_grade, enable_subtitles=enable_subtitles, enable_music=enable_music,
        enable_sfx=enable_sfx, music_mood=resolve_music_mood(niche, video_style), music_source=music_source,
        strict=strict,
    )
    report = RunReport(job=job.name, options={
        **options.to_json(), "topic": topic, "niche": niche or "", "enable_motion": motion_on,
        "use_mock_images": use_mock_images, "classic": classic,
        "quality_tier": quality_tier, "clip_model": model.key, "max_cost": max_cost,
    })
    report.cost = {"estimated": {}, "cap": max_cost, "actual": [], "total": 0.0}
    paid = {"llm_n": 0, "narration": "", "specs": None, "classic_clips": None, "logged": False}
    if tier_explicit and (classic or not motion_on or settings.motion_provider in ("local", "replicate")):
        report.warn("tier_ignored",
                    f"Quality tier {quality_tier!r} has no effect on this run (motion {model.key}); "
                    "tiers apply to fal motion clips in the shot editor only",
                    {"quality_tier": quality_tier, "clip_model": model.key, "classic": classic,
                     "motion": motion_on, "motion_provider": settings.motion_provider})
    logger.info(f"Job folder: {job.root}")

    try:
        logger.info("Generating script...")
        llm.reset_last_provider()                # a value left by an earlier run in this thread
        with report.stage("script"):
            result = ScriptGenerator().write_script(
                topic, enable_v2=enable_motion, video_style=video_style, video_duration=video_duration)
        script = result.script
        report.script = dict(result.length)
        report.script["llm_provider"] = llm.last_provider() or settings.llm_provider
        for w in result.warnings:
            report.warn(w["code"], w["message"], w["detail"])
        options.subtitle_style = resolve_subtitle_style(subtitle_style, video_style)
        report.options["subtitle_style"] = options.subtitle_style
        _print_script(script)
        full_narration = f"{script.hook} {script.body}"
        llm_n = llm_calls(report.script.get("revision"))
        paid["llm_n"] = llm_n
        # checkpoint 1: nothing but the script is paid yet (spec 2026-10-03 §8.2)
        costs = stage_costs(narration_chars=len(full_narration), image_count=len(script.image_prompts),
                            mock_images=use_mock_images, llm_calls=llm_n,
                            llm_provider=report.script["llm_provider"])
        if classic:              # one clip per image; the classic editor has no second checkpoint
            classic_motion = motion_on and bool(script.motion_prompts)
            estimate = estimate_classic(clip_count=len(script.image_prompts) if classic_motion else 0,
                                        model=model, motion_on=classic_motion, costs=costs)
        else:
            estimate = estimate_pre_tts(words=report.script.get("words") or 0,
                                        scene_count=len(script.image_prompts), model=model,
                                        motion_on=motion_on, costs=costs)
        _cost_checkpoint(report, estimate, max_cost, job)

        logger.info("Generating audio narration...")
        asset_manager = AssetManager(video_style=options.video_style)
        with report.stage("tts"):
            audio_result = asset_manager.generate_audio(full_narration, voice_id=voice, output_path=job.narration)
        logger.info(f"Audio generated: {audio_result.duration:.1f} seconds")
        _record_narration(report, audio_result.duration)
        if asset_manager.voice_fallback:
            report.warn("voice_fallback", "ElevenLabs cannot use the chosen voice on this plan; used the default voice",
                        dict(asset_manager.voice_fallback))
        paid["narration"] = full_narration

        specs, classic_clips = None, None
        if classic:
            output_path, image_paths, classic_clips = _run_classic(
                job, script, audio_result, options, asset_manager, use_mock_images, enable_motion,
                persona, use_chroma_key, paid=paid)
        else:
            output_path, image_paths, specs = _run_shot_editor(
                job, script, full_narration, audio_result.duration, options, report, asset_manager,
                use_mock_images, motion_on, model, max_cost=max_cost, llm_n=llm_n, paid=paid)
        logger.info(f"Video rendered successfully: {output_path}")

        video_id = job.name
        paid["logged"] = True
        _log_costs(video_id, report, full_narration, use_mock_images, len(image_paths), specs, classic_clips,
                   llm_n=llm_n)

        logger.info("Generating metadata...")
        meta_gen = MetadataGenerator()
        metadata = meta_gen.generate_metadata(topic=topic, hook=script.hook, keywords=script.keywords,
                                              niche=settings.niche)
        meta_gen.save_metadata(video_id, metadata)
        logger.info("Generating thumbnail...")
        meta_gen.generate_thumbnail(video_path=output_path, video_id=video_id,
                                    title=metadata.get("title_tiktok", topic))

        if upload:
            try:
                video_url = YouTubeUploader().upload(video_path=output_path, video_id=video_id, niche=niche)
                logger.info(f"YouTube upload complete: {video_url}")
            except UploaderError as e:
                logger.error(f"YouTube upload failed: {e}")

        report.status = "ok"
        return output_path

    except Exception as e:
        report.status = "failed"
        report.error = f"{type(e).__name__}: {e}"
        logger.error(f"Pipeline failed: {e} (sources kept in {job.root}; fix and --rerender)")
        _tag_job_dir(e, job.root)
        _log_partial_costs(job, report, paid, use_mock_images)
        raise
    finally:
        report.save_quietly(job.report)


def list_personas() -> list:
    """List available personas."""
    animator = PortraitAnimator()
    return animator.get_available_personas()


def parse_moods(text: str) -> list:
    moods = [m.strip().lower() for m in text.split(",") if m.strip()]
    unknown = [m for m in moods if m not in MOODS]
    if not moods or unknown:
        raise argparse.ArgumentTypeError(f"unknown mood(s) {unknown or text!r}; choose from {', '.join(MOODS)}")
    return moods


def _max_cost_arg(text: str) -> float:
    """--max-cost: USD >= 0 (0 = no cap). float() alone would accept "nan" and "inf"."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--max-cost must be a number of USD, got {text!r}")
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("--max-cost must be >= 0 (0 = no cap)")
    return value


def _per_mood(text: str) -> int:
    n = int(text)
    if not 1 <= n <= 20:
        raise argparse.ArgumentTypeError("--per-mood must be between 1 and 20")
    return n


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="FVFactory v2 - Short-form Video Generator"
    )

    parser.add_argument("--auto", action="store_true",
                        help="Auto mode (discover trend, generate, render)")
    parser.add_argument("--batch", type=int, default=None,
                        help="Batch mode (generate N videos)")
    parser.add_argument("--series", type=str, default=None,
                        help="Series mode topic")
    parser.add_argument("--parts", type=int, default=3,
                        help="Number of parts for series (default 3)")
    parser.add_argument("--niche", type=str, default=None,
                        help="Niche filter")
    parser.add_argument("--topic", type=str, default=None,
                        help="Provide topic directly")
    parser.add_argument("--no-motion", action="store_true",
                        help="Skip Minimax, use Ken Burns")
    parser.add_argument("--subtitle-style", type=str, default=None,
                        help="Subtitle preset (default bold_impact; with --rerender: keep the job's)")
    parser.add_argument("--no-sfx", action="store_true",
                        help="Disable SFX")
    parser.add_argument("--no-music", action="store_true",
                        help="Disable music")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock images")
    parser.add_argument("--voice", type=str, default=None,
                        help="Voice preset (bill, george, daniel, josh, rachel, auto) or ElevenLabs voice ID")
    parser.add_argument("--upload", action="store_true",
                        help="Upload to YouTube after rendering")
    parser.add_argument("--local", action="store_true",
                        help="Use all local models (no API calls for LLM/image/video)")
    parser.add_argument("--api", action="store_true",
                        help="Use all API models (original behavior)")
    parser.add_argument("--serve", action="store_true",
                        help="Start the FastAPI web server")
    parser.add_argument("--classic", action="store_true",
                        help="Use the classic Ken Burns editor instead of the shot editor")
    parser.add_argument("--pacing", choices=sorted(PACING), default=None,
                        help="Shot pacing: calm, standard or fast (default: settings.pacing)")
    parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=None,
                        help="Fail the run instead of shipping a still when a motion clip fails")
    parser.add_argument("--tier", choices=list(QUALITY_TIERS), default=None,
                        help="Motion quality: standard (MiniMax H3 Turbo), premium (Kling v3 Pro) or "
                             "custom (settings.fal_video_model) (default: settings.quality_tier)")
    parser.add_argument("--max-cost", type=_max_cost_arg, default=None, metavar="USD",
                        help="Stop the run before the next paid stage when its cost estimate exceeds "
                             "this (0 = no cap; default: settings.max_cost_per_video)")
    parser.add_argument("--rerender", type=str, default=None, metavar="JOB_DIR",
                        help="Rebuild output/<job>/final.mp4 from its sources/ with zero API calls")
    parser.add_argument("--color-grade", type=str, default=None,
                        help="Colour grade preset for --rerender (tech, finance, history, science, default; '' = none)")
    parser.add_argument("--music-source", choices=list(MUSIC_SOURCES), default=None,
                        help="Music pool: mine, generated, any or none (default: settings.music_source; "
                             "with --rerender: keep the job's track)")
    parser.add_argument("--build-music-library", action="store_true",
                        help="Generate ~60 s instrumental tracks per mood via ElevenLabs Music "
                             "(prints a cost estimate and asks first)")
    parser.add_argument("--build-sfx-library", action="store_true",
                        help="Generate whoosh x3, impact x2, riser x2 via ElevenLabs Sound Effects")
    parser.add_argument("--per-mood", type=_per_mood, default=5,
                        help="Tracks per mood for --build-music-library (default 5)")
    parser.add_argument("--moods", type=parse_moods, default=None,
                        help=f"Comma-separated moods for --build-music-library (default: {','.join(MOODS)})")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the cost confirmation prompt of the library builders")

    return parser.parse_args(argv)


def run_auto_mode(args):
    """Run in auto mode: discover trend, generate, render."""
    count = args.batch or 1

    for i in range(count):
        if args.topic:
            topic = args.topic
        else:
            scout = TrendScout()
            topics = scout.discover_topics(niche=args.niche, count=1)
            if not topics:
                logger.error("No trending topics found")
                continue
            topic = topics[0].title

        logger.info(f"[{i+1}/{count}] Auto generating: {topic}")

        # Resolve voice (supports "auto" to pick based on niche)
        voice_id = resolve_voice(args.voice, niche=args.niche)

        try:
            run_pipeline(
                topic=topic,
                use_mock_images=args.mock,
                enable_music=not args.no_music,
                enable_motion=not args.no_motion,
                subtitle_style=args.subtitle_style or settings.subtitle_style,
                enable_sfx=not args.no_sfx,
                voice=voice_id,
                upload=args.upload,
                niche=args.niche,
                pacing=args.pacing,
                strict=args.strict,
                classic=args.classic,
                music_source=args.music_source,
                quality_tier=args.tier,
                max_cost=args.max_cost,
            )
        except Exception as e:
            logger.error(f"Failed: {e}")
            continue


def run_interactive_mode(args):
    """Run in interactive mode with user prompts."""
    # Get topic from user
    try:
        topic = input("Enter video topic: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(0)

    if not topic:
        logger.error("Topic cannot be empty")
        sys.exit(1)

    print()
    logger.info(f"Starting video generation for topic: '{topic}'")
    print()

    # Check for available personas
    personas = list_personas()
    selected_persona = None
    use_chroma_key = False

    if personas and (settings.hedra_api_key or settings.replicate_api_token):
        print("Available Personas (Hybrid Mode - Background Images + Talking Head):")
        print("  0. None (use image slideshow only)")
        for i, persona in enumerate(personas, 1):
            print(f"  {i}. {persona}")

        try:
            choice = input("Select persona (0 for none): ").strip()
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(personas):
                    selected_persona = personas[idx - 1]
                    logger.info(f"Selected persona: {selected_persona}")

                    # Ask about chroma key for green screen personas
                    choice = input("Use chroma key for green screen? (y/N): ").strip().lower()
                    use_chroma_key = choice == "y"
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

        print()

    # Image generation options
    use_mock = args.mock
    if not use_mock and settings.openai_api_key:
        try:
            choice = input("Use mock images? (Y/n): ").strip().lower()
            use_mock = choice != "n"
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

    # Ask about subtitles
    enable_subs = True
    try:
        choice = input("Enable word-level subtitles? (Y/n): ").strip().lower()
        enable_subs = choice != "n"
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        sys.exit(0)

    # Ask about background music
    enable_music = not args.no_music
    if enable_music:
        try:
            choice = input("Enable background music? (Y/n): ").strip().lower()
            enable_music = choice != "n"
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            sys.exit(0)

    print()

    try:
        output_path = run_pipeline(
            topic,
            use_mock_images=use_mock,
            enable_subtitles=enable_subs,
            enable_music=enable_music,
            persona=selected_persona,
            use_chroma_key=use_chroma_key,
            enable_motion=not args.no_motion,
            subtitle_style=args.subtitle_style or settings.subtitle_style,
            enable_sfx=not args.no_sfx,
            pacing=args.pacing,
            strict=args.strict,
            classic=args.classic,
            music_source=args.music_source,
            quality_tier=args.tier,
            max_cost=args.max_cost,
        )

        print()
        print("=" * 50)
        print("  VIDEO GENERATION COMPLETE!")
        print("=" * 50)
        print(f"  Output: {output_path}")
        print("=" * 50)
        print()

    except Exception as e:
        logger.error(f"Video generation failed: {e}")
        sys.exit(1)


def main():
    """Main entry point for FVFactory."""
    args = parse_args()

    # Library builders need only ELEVENLABS_API_KEY: handle them before validate_config().
    if args.build_music_library or args.build_sfx_library:
        from app.cin import library_builder
        code = 0
        if args.build_sfx_library:
            code = max(code, library_builder.build_sfx_library(yes=args.yes))
        if args.build_music_library:
            code = max(code, library_builder.build_music_library(per_mood=args.per_mood, moods=args.moods,
                                                                 yes=args.yes))
        sys.exit(code)

    # Re-render needs no API keys and makes no API calls: handle it before validate_config().
    if args.rerender:
        from app.cin.editor import rerender_job
        try:
            out = rerender_job(args.rerender, pacing=args.pacing, subtitle_style=args.subtitle_style,
                               no_sfx=args.no_sfx, no_music=args.no_music, color_grade=args.color_grade,
                               music_source=args.music_source)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Re-render failed: {e}")
            sys.exit(1)
        print(f"Re-rendered: {out}")
        sys.exit(0)

    # Provider mode override from CLI flags
    if args.local:
        settings.provider_mode = "local"
    elif args.api:
        settings.provider_mode = "api"

    if args.classic:
        settings.cinematic_enabled = False

    # Web server mode
    if args.serve:
        from app.web.server import start_server
        start_server()
        sys.exit(0)

    print()
    print("=" * 50)
    print("  FVFactory v2 - Short-form Video Generator")
    print("  Pipeline: Topic -> Script -> Audio/Visuals -> MP4")
    print("=" * 50)
    print()

    if not validate_config(use_mock=args.mock, enable_motion=not args.no_motion):
        logger.error("Configuration validation failed. Check your .env file.")
        sys.exit(1)

    if args.auto or args.batch:
        run_auto_mode(args)
    else:
        run_interactive_mode(args)


if __name__ == "__main__":
    main()
