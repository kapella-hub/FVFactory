"""Tests for APScheduler integration."""
import pytest
from app.scheduler import FVScheduler


def test_real_run_job_is_blocked_in_tests(tmp_path):
    s = FVScheduler(db_path=str(tmp_path / "x.db"))
    with pytest.raises(AssertionError, match="real scheduled run attempted in tests"):
        s._run_job("anything")


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


def test_run_now(scheduler, monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=None):
            started.append((target, args))

        def start(self):
            pass
    monkeypatch.setattr("app.scheduler.threading.Thread", FakeThread)
    job = scheduler.add_job("Run Me", "0 9 * * *", {})
    assert scheduler.run_now(job["id"]) is True
    assert started == [(scheduler._run_job, (job["id"],))]
    assert scheduler.run_now("nonexistent") is False
