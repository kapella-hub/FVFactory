"""Scheduler module for FVFactory — stub implementation for Task 10."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_scheduler_instance: "Scheduler | None" = None


class Scheduler:
    """Simple cron-based job scheduler (stub — full implementation in Task 10)."""

    def __init__(self, db_path: str = "data/scheduler.json"):
        self.db_path = Path(db_path)
        self._jobs: dict[str, dict] = {}
        self._history: list[dict] = []
        self._load()

    def _load(self):
        if self.db_path.exists():
            try:
                data = json.loads(self.db_path.read_text())
                self._jobs = data.get("jobs", {})
                self._history = data.get("history", [])
            except Exception:
                pass

    def _save(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(json.dumps(
            {"jobs": self._jobs, "history": self._history}, indent=2
        ))

    def list_jobs(self) -> list[dict]:
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def add_job(self, name: str, cron_expression: str, config: dict, enabled: bool = True) -> dict:
        job_id = str(uuid.uuid4())[:8]
        job = {
            "id": job_id,
            "name": name,
            "cron_expression": cron_expression,
            "enabled": enabled,
            "config": config,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._jobs[job_id] = job
        self._save()
        return job

    def update_job(self, job_id: str, updates: dict) -> dict | None:
        if job_id not in self._jobs:
            return None
        self._jobs[job_id].update(updates)
        self._save()
        return self._jobs[job_id]

    def delete_job(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        del self._jobs[job_id]
        self._save()
        return True

    def run_now(self, job_id: str) -> bool:
        if job_id not in self._jobs:
            return False
        entry = {
            "job_id": job_id,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
            "status": "triggered",
        }
        self._history.append(entry)
        self._save()
        logger.info("Job %s triggered manually", job_id)
        return True

    def get_history(self) -> list[dict]:
        return self._history


def get_scheduler() -> Scheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = Scheduler()
    return _scheduler_instance
