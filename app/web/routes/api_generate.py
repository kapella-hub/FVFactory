"""Video generation API endpoints."""
import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.run_options import OptionError, pipeline_kwargs, run_failure, run_result
from app.web.ws import ws_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    topic: str = ""
    niche: str = ""
    voice: str = "auto"
    subtitle_style: str = "bold_impact"
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


class GenerateResponse(BaseModel):
    job_id: str
    status: str


@router.post("/generate")
async def generate_video(req: GenerateRequest) -> GenerateResponse:
    try:
        options = pipeline_kwargs(req.model_dump())       # reject bad options before starting
    except OptionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    job_id = str(uuid.uuid4())[:8]

    async def _run():
        try:
            await ws_manager.send_progress(job_id, "starting", 0.0, "Starting pipeline...")
            from main import run_pipeline, resolve_voice
            from app.trend_scout import TrendScout

            topic = req.topic
            if req.auto_topic or not topic:
                scout = TrendScout()
                topics = scout.discover_topics(niche=req.niche, count=1)
                topic = topics[0].title if topics else "Interesting facts about the world"

            voice_id = resolve_voice(req.voice, req.niche, req.video_style)
            await ws_manager.send_progress(job_id, "script", 0.1, f"Topic: {topic}")

            result = await asyncio.to_thread(run_pipeline, topic=topic, voice=voice_id, **options)

            # spec §10: the result carries the run report's warnings
            await ws_manager.send_complete(job_id, run_result(result))
        except Exception as e:
            logger.exception("Generation failed for job %s", job_id)
            await ws_manager.send_error(job_id, str(e), run_failure(e))

    asyncio.create_task(_run())
    return GenerateResponse(job_id=job_id, status="started")
