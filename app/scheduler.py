"""Job scheduler using APScheduler with SQLite persistence."""

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_scheduler_instance = None


class FVScheduler:
    """Manages scheduled video generation jobs."""

    def __init__(self, db_path: str = "data/scheduler.db"):
        self.db_path = db_path
        self._init_db()
        self.scheduler = BackgroundScheduler(
            executors={"default": ThreadPoolExecutor(1)},
            job_defaults={"coalesce": True, "max_instances": 1},
        )

    def _init_db(self):
        import os
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cron_expression TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                config TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT DEFAULT 'running',
                output_path TEXT,
                error TEXT,
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            )
        """)
        conn.commit()
        conn.close()

    def start(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs WHERE enabled = 1").fetchall()
        conn.close()

        for row in rows:
            self._schedule_job(dict(row))

        if not self.scheduler.running:
            self.scheduler.start()
        logger.info("Scheduler started with %d active jobs", len(rows))

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _schedule_job(self, job: dict):
        try:
            trigger = CronTrigger.from_crontab(job["cron_expression"])
            self.scheduler.add_job(
                self._run_job, trigger,
                id=job["id"], args=[job["id"]],
                replace_existing=True,
            )
        except Exception as e:
            logger.error("Failed to schedule job %s: %s", job["id"], e)

    def _run_job(self, job_id: str):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            conn.close()
            return

        config = json.loads(row["config"])
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO job_runs (job_id, started_at, status) VALUES (?, ?, 'running')",
            (job_id, now),
        )
        conn.commit()
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        try:
            from main import run_pipeline, resolve_voice
            from app.run_options import pipeline_kwargs
            options = pipeline_kwargs(config)          # spec §11: slot options; missing = Settings default
            topic = config.get("topic", "")
            niche = config.get("niche", "")
            voice = resolve_voice(config.get("voice", "auto"), niche)

            if not topic:
                from app.trend_scout import TrendScout
                scout = TrendScout()
                topics = scout.discover_topics(niche=niche, count=1)
                topic = topics[0].title if topics else "Interesting facts"

            result = run_pipeline(topic=topic, voice=voice, **options)

            finished = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE job_runs SET status='success', finished_at=?, output_path=? WHERE id=?",
                (finished, result, run_id),
            )
            logger.info("Job %s completed: %s", job_id, result)
        except Exception as e:
            finished = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "UPDATE job_runs SET status='failed', finished_at=?, error=? WHERE id=?",
                (finished, str(e), run_id),
            )
            logger.exception("Job %s failed", job_id)
        finally:
            conn.commit()
            conn.close()

    def add_job(self, name: str, cron_expression: str, config: dict,
                enabled: bool = True) -> dict:
        job_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO jobs (id, name, cron_expression, enabled, config, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, name, cron_expression, int(enabled), json.dumps(config), now),
        )
        conn.commit()
        conn.close()

        job = {"id": job_id, "name": name, "cron_expression": cron_expression,
               "enabled": enabled, "config": config, "created_at": now}

        if enabled and self.scheduler.running:
            self._schedule_job(job)

        return job

    def list_jobs(self) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
        conn.close()

        jobs = []
        for row in rows:
            job = dict(row)
            job["enabled"] = bool(job["enabled"])
            job["config"] = json.loads(job["config"])
            ap_job = self.scheduler.get_job(job["id"]) if self.scheduler.running else None
            job["next_run"] = str(ap_job.next_run_time) if ap_job else None
            # Get last run
            conn2 = sqlite3.connect(self.db_path)
            conn2.row_factory = sqlite3.Row
            last = conn2.execute(
                "SELECT * FROM job_runs WHERE job_id = ? ORDER BY started_at DESC LIMIT 1",
                (job["id"],)
            ).fetchone()
            conn2.close()
            job["last_run"] = dict(last) if last else None
            jobs.append(job)

        return jobs

    def get_job(self, job_id: str) -> dict | None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        if not row:
            return None
        job = dict(row)
        job["enabled"] = bool(job["enabled"])
        job["config"] = json.loads(job["config"])
        return job

    def update_job(self, job_id: str, updates: dict) -> dict | None:
        job = self.get_job(job_id)
        if not job:
            return None

        conn = sqlite3.connect(self.db_path)
        if "name" in updates:
            conn.execute("UPDATE jobs SET name = ? WHERE id = ?", (updates["name"], job_id))
        if "cron_expression" in updates:
            conn.execute("UPDATE jobs SET cron_expression = ? WHERE id = ?", (updates["cron_expression"], job_id))
        if "enabled" in updates:
            conn.execute("UPDATE jobs SET enabled = ? WHERE id = ?", (int(updates["enabled"]), job_id))
        if "config" in updates:
            conn.execute("UPDATE jobs SET config = ? WHERE id = ?", (json.dumps(updates["config"]), job_id))
        conn.commit()
        conn.close()

        updated = self.get_job(job_id)
        if self.scheduler.running:
            existing = self.scheduler.get_job(job_id)
            if existing:
                self.scheduler.remove_job(job_id)
            if updated and updated["enabled"]:
                self._schedule_job(updated)

        return updated

    def delete_job(self, job_id: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.execute("DELETE FROM job_runs WHERE job_id = ?", (job_id,))
        conn.commit()
        conn.close()

        if self.scheduler.running:
            existing = self.scheduler.get_job(job_id)
            if existing:
                self.scheduler.remove_job(job_id)

        return cursor.rowcount > 0

    def run_now(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job:
            return False
        threading.Thread(target=self._run_job, args=(job_id,), daemon=True).start()
        return True

    def get_history(self, limit: int = 50) -> list[dict]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT r.*, j.name as job_name FROM job_runs r LEFT JOIN jobs j ON r.job_id = j.id "
            "ORDER BY r.started_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def get_scheduler() -> FVScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = FVScheduler()
        _scheduler_instance.start()
    return _scheduler_instance
