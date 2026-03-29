"""Library API endpoints."""
import json
import os
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.config import settings

router = APIRouter()


@router.get("/library")
async def list_videos():
    output_dir = Path(settings.output_dir)
    videos = []
    if not output_dir.exists():
        return {"videos": []}

    for mp4 in sorted(output_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True):
        video_id = mp4.stem
        meta_path = output_dir / "metadata" / f"{video_id}.json"
        thumb_path = output_dir / "thumbnails" / f"{video_id}.png"

        entry = {
            "id": video_id,
            "filename": mp4.name,
            "created": os.path.getmtime(str(mp4)),
            "size_mb": round(mp4.stat().st_size / 1024 / 1024, 1),
            "has_thumbnail": thumb_path.exists(),
            "metadata": None,
        }
        if meta_path.exists():
            try:
                entry["metadata"] = json.loads(meta_path.read_text())
            except json.JSONDecodeError:
                pass
        videos.append(entry)

    return {"videos": videos}


@router.get("/library/{video_id}/video")
async def get_video(video_id: str):
    path = Path(settings.output_dir) / f"{video_id}.mp4"
    if not path.exists():
        return {"error": "Video not found"}
    return FileResponse(path, media_type="video/mp4")


@router.get("/library/{video_id}/thumbnail")
async def get_thumbnail(video_id: str):
    path = Path(settings.output_dir) / "thumbnails" / f"{video_id}.png"
    if not path.exists():
        return {"error": "Thumbnail not found"}
    return FileResponse(path, media_type="image/png")
