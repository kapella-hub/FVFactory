"""Tests for APScheduler integration."""
import pytest
from app.scheduler import FVScheduler


@pytest.fixture
def scheduler(tmp_path):
    db_path = str(tmp_path / "test_scheduler.db")
    s = FVScheduler(db_path=db_path)
    s.start()
    yield s
    s.shutdown()


def test_add_and_list_jobs(scheduler):
    job = scheduler.add_job("Test Job", "0 9 * * *", {"niche": "tech"})
    assert job["name"] == "Test Job"
    assert job["cron_expression"] == "0 9 * * *"
    jobs = scheduler.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["name"] == "Test Job"


def test_delete_job(scheduler):
    job = scheduler.add_job("Delete Me", "0 9 * * *", {})
    assert scheduler.delete_job(job["id"])
    assert len(scheduler.list_jobs()) == 0


def test_update_job(scheduler):
    job = scheduler.add_job("Update Me", "0 9 * * *", {})
    updated = scheduler.update_job(job["id"], {"enabled": False})
    assert updated["enabled"] is False


def test_get_history_empty(scheduler):
    history = scheduler.get_history()
    assert history == []


def test_get_nonexistent_job(scheduler):
    assert scheduler.get_job("nonexistent") is None


def test_run_now(scheduler):
    job = scheduler.add_job("Run Me", "0 9 * * *", {})
    assert scheduler.run_now(job["id"]) is True
    assert scheduler.run_now("nonexistent") is False
