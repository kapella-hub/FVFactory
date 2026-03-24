"""Tests for background video generation worker."""
import time
from unittest.mock import patch, MagicMock
from app.generator_worker import GeneratorWorker


def test_worker_initial_state():
    w = GeneratorWorker()
    assert w.status == "idle"
    assert w.logs == []
    assert w.result is None
    assert w.error is None


def test_worker_is_busy_while_running():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline") as mock_pipe:
        mock_pipe.side_effect = lambda **kw: time.sleep(0.5)
        w.start(topic="Test", niche="stoicism")
        assert w.status == "running"
        w._thread.join()


def test_worker_captures_result():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/test.mp4"):
        w.start(topic="Test", niche="stoicism")
        w._thread.join()
        assert w.status == "done"
        assert w.result == "/output/test.mp4"


def test_worker_captures_error():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", side_effect=Exception("boom")):
        w.start(topic="Test", niche="stoicism")
        w._thread.join()
        assert w.status == "error"
        assert "boom" in w.error


def test_worker_rejects_while_busy():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline") as mock_pipe:
        mock_pipe.side_effect = lambda **kw: time.sleep(1)
        w.start(topic="A")
        ok = w.start(topic="B")
        assert ok is False
        w._thread.join()


def test_worker_reset():
    w = GeneratorWorker()
    with patch("app.generator_worker.run_pipeline", return_value="/output/test.mp4"):
        w.start(topic="Test")
        w._thread.join()
        w.reset()
        assert w.status == "idle"
        assert w.logs == []
