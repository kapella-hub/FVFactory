"""Library API endpoints."""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.config import settings
from app.library import find_videos, resolve_video

router = APIRouter()


@router.get("/library")
async def list_videos():
    videos = find_videos(Path(settings.output_dir))
    for v in videos:
        v.pop("path", None)
    return {"videos": videos}


@router.get("/library/{video_id}/video")
async def get_video(video_id: str):
    path = resolve_video(Path(settings.output_dir), video_id)
    if path is None:
        return {"error": "Video not found"}
    return FileResponse(path, media_type="video/mp4")


@router.get("/library/{video_id}/thumbnail")
async def get_thumbnail(video_id: str):
    path = Path(settings.output_dir) / "thumbnails" / f"{video_id}.png"
    if not path.exists():
        return {"error": "Thumbnail not found"}
    return FileResponse(path, media_type="image/png")
