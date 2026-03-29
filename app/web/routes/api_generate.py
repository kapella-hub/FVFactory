"""Video generation API endpoints."""
import asyncio
import logging
import uuid
from fastapi import APIRouter
from pydantic import BaseModel
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


class GenerateResponse(BaseModel):
    job_id: str
    status: str


@router.post("/generate")
async def generate_video(req: GenerateRequest) -> GenerateResponse:
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

            result = await asyncio.to_thread(
                run_pipeline,
                topic=topic,
                use_mock_images=req.use_mock,
                enable_motion=req.enable_motion,
                subtitle_style=req.subtitle_style,
                enable_sfx=req.enable_sfx,
                voice=voice_id,
                niche=req.niche,
                video_style=req.video_style,
                video_duration=req.video_duration,
            )

            await ws_manager.send_complete(job_id, {"video_id": result} if result else None)
        except Exception as e:
            logger.exception("Generation failed for job %s", job_id)
            await ws_manager.send_error(job_id, str(e))

    asyncio.create_task(_run())
    return GenerateResponse(job_id=job_id, status="started")
