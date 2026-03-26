"""Scheduler API endpoints."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class JobCreate(BaseModel):
    name: str
    cron_expression: str
    enabled: bool = True
    config: dict = {}


class JobUpdate(BaseModel):
    name: str | None = None
    cron_expression: str | None = None
    enabled: bool | None = None
    config: dict | None = None


@router.get("/scheduler/jobs")
async def list_jobs():
    from app.scheduler import get_scheduler
    return {"jobs": get_scheduler().list_jobs()}


@router.post("/scheduler/jobs")
async def create_job(req: JobCreate):
    from app.scheduler import get_scheduler
    return get_scheduler().add_job(req.name, req.cron_expression, req.config, req.enabled)


@router.get("/scheduler/jobs/{job_id}")
async def get_job(job_id: str):
    from app.scheduler import get_scheduler
    job = get_scheduler().get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.put("/scheduler/jobs/{job_id}")
async def update_job(job_id: str, req: JobUpdate):
    from app.scheduler import get_scheduler
    job = get_scheduler().update_job(job_id, req.model_dump(exclude_none=True))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.delete("/scheduler/jobs/{job_id}")
async def delete_job(job_id: str):
    from app.scheduler import get_scheduler
    if not get_scheduler().delete_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "deleted"}


@router.post("/scheduler/jobs/{job_id}/run")
async def run_job_now(job_id: str):
    from app.scheduler import get_scheduler
    if not get_scheduler().run_now(job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "triggered"}


@router.get("/scheduler/history")
async def job_history():
    from app.scheduler import get_scheduler
    return {"history": get_scheduler().get_history()}
