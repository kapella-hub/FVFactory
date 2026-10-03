"""Video generation API endpoints."""
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.run_options import (MaxCostInput, OptionError, available_personas, generate_extras, pipeline_kwargs,
                             run_failure, run_result, story_options)
from app.script_quality import DURATION_SECONDS, WORDS_PER_SECOND
from app.story import MAX_STORY_CHARS, SCENE_SECONDS, STORY_MODES, default_title
from app.web.ws import ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    topic: str = ""
    niche: str = ""
    voice: str = "auto"
    subtitle_style: str = "bold_impact"
    enable_subtitles: bool = True
    enable_motion: bool = True
    enable_sfx: bool = True
    enable_music: bool = True
    use_mock: bool = False
    auto_topic: bool = False
    video_style: str = "photorealistic"
    video_duration: str = "medium"
    # Shot editor (spec §11). None / "" = the Settings default, like the CLI.
    pacing: Optional[str] = None            # calm | standard | fast
    music_source: Optional[str] = None      # mine | generated | any | none
    strict: Optional[bool] = None
    # Quality tiers (spec 2026-10-03 §9). Text is accepted so pipeline_kwargs gives one message for
    # blank ("" = Settings default), negative and non-numeric caps.
    quality_tier: Optional[str] = None      # standard | premium | custom
    max_cost: MaxCostInput = None   # USD, 0 = no cap
    # "Your story" (app.story): story "" = a topic / auto-discover run. title is optional.
    story: Optional[str] = ""
    story_mode: Optional[str] = None        # verbatim (default) | adapt
    title: str = ""
    # Advanced (run_options.generate_extras)
    classic: bool = False
    persona: str = ""
    use_chroma_key: bool = False
    upload: bool = False


class GenerateResponse(BaseModel):
    job_id: str
    status: str


@router.get("/generate/options")
async def generate_options() -> dict:
    """What the Generate page needs beyond /api/config: personas, whether persona / upload can work on this
    machine, and the story limits (the page's character counter and length estimate use the same numbers)."""
    return {
        "personas": available_personas(settings.personas_dir),
        "persona_ready": bool(settings.hedra_api_key or settings.replicate_api_token),
        "upload_ready": Path(settings.youtube_client_secrets).is_file(),
        "story_max_chars": MAX_STORY_CHARS,
        "story_modes": list(STORY_MODES),
        "words_per_second": WORDS_PER_SECOND,
        "scene_seconds": SCENE_SECONDS,
        "duration_seconds": DURATION_SECONDS,
    }


@router.post("/generate")
async def generate_video(req: GenerateRequest) -> GenerateResponse:
    try:
        body = req.model_dump()
        options = pipeline_kwargs(body)       # reject bad options before starting
        options.update(generate_extras(body))
        story = story_options(body)
    except OptionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    job_id = str(uuid.uuid4())[:8]

    async def _run():
        try:
            await ws_manager.send_progress(job_id, "starting", 0.0, "Starting pipeline...")
            from main import run_pipeline, resolve_voice

            if story:                         # never trend discovery for a story
                topic, source = story["title"], "story"
                extra = {"story": story["story"], "story_mode": story["story_mode"]}
                label = f"Story: {topic or default_title(story['story'])} ({story['story_mode']})"
            else:
                topic, source, extra = req.topic, "topic", {"story": ""}
                if req.auto_topic or not topic:
                    from app.trend_scout import TrendScout
                    topics = TrendScout().discover_topics(niche=req.niche, count=1)
                    topic = topics[0].title if topics else "Interesting facts about the world"
                    source = "auto"
                label = f"Topic: {topic}"

            voice_id = resolve_voice(req.voice, req.niche, req.video_style)
            await ws_manager.send_progress(job_id, "script", 0.1, label)

            result = await asyncio.to_thread(run_pipeline, topic=topic, voice=voice_id, source=source,
                                             **extra, **options)

            # spec §10: the result carries the run report's warnings
            await ws_manager.send_complete(job_id, run_result(result))
        except Exception as e:
            logger.exception("Generation failed for job %s", job_id)
            await ws_manager.send_error(job_id, str(e), run_failure(e))

    asyncio.create_task(_run())
    return GenerateResponse(job_id=job_id, status="started")
