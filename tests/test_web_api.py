"""Tests for FastAPI web server."""
import pytest
from fastapi.testclient import TestClient
from app.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_real_generation(monkeypatch):
    """POST /api/generate must never start a real run from a test (a 200 where a 422 was expected would
    otherwise run the paid pipeline in the background): background tasks are captured, never scheduled,
    and run_pipeline / trend discovery raise. Tests that run the captured task patch run_pipeline again."""
    import main
    import app.web.routes.api_generate as api

    def no_run(*args, **kwargs):
        raise AssertionError("a test reached the real run_pipeline")

    def capture(coro):
        coro.close()                       # never scheduled; _capture_task overrides this to keep them
    monkeypatch.setattr(main, "run_pipeline", no_run)
    monkeypatch.setattr(api.asyncio, "create_task", capture)
    monkeypatch.setattr("app.trend_scout.TrendScout.discover_topics", no_run)


def test_root(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_config_endpoint(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "provider_mode" in data


def test_library_endpoint(client):
    resp = client.get("/api/library")
    assert resp.status_code == 200
    assert "videos" in resp.json()


def test_scheduler_jobs_endpoint(client):
    resp = client.get("/api/scheduler/jobs")
    assert resp.status_code == 200
    assert "jobs" in resp.json()


def test_web_client_never_touches_the_real_scheduler_db(client):
    import os
    from pathlib import Path
    real = Path("data/scheduler.db")
    before = (real.exists(), real.stat().st_mtime_ns, real.stat().st_size) if real.exists() else (False,)
    assert client.get("/api/scheduler/jobs").status_code == 200
    import app.scheduler as sched
    assert sched._scheduler_instance is None                 # the real singleton was never created/started
    after = (real.exists(), real.stat().st_mtime_ns, real.stat().st_size) if real.exists() else (False,)
    assert before == after


# ---------------------------------------------------------------- no stale builds

@pytest.mark.parametrize("path", ["/", "/generate", "/library", "/static/js/app.js", "/static/css/styles.css",
                                  "/static/index.html"])
def test_ui_files_are_revalidated_on_every_load(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/", "/generate", "/library"])
def test_index_links_carry_a_version_so_old_cached_files_are_never_used(client, path):
    """Browsers that cached styles.css/js before no-cache existed kept the old layout (brand overlapping the
    page title); a version query on every asset link forces fresh files after each update."""
    import re
    html = client.get(path).text
    links = re.findall(r'(?:href|src)="(/static/[^"]+)"', html)
    assert links and all(re.search(r"\?v=[0-9a-f]{8,}$", link) for link in links), links


def test_asset_version_changes_when_a_ui_file_changes(client, tmp_path, monkeypatch):
    import re
    import shutil
    import app.web.server as server
    static = tmp_path / "static"
    shutil.copytree(server.STATIC_DIR, static)
    monkeypatch.setattr(server, "STATIC_DIR", static)
    first = re.search(r"\?v=([0-9a-f]+)", client.get("/").text).group(1)
    css = static / "css" / "styles.css"
    css.write_text(css.read_text(encoding="utf-8") + "/* change */", encoding="utf-8")
    second = re.search(r"\?v=([0-9a-f]+)", client.get("/").text).group(1)
    assert first != second


def test_static_files_still_answer_304_when_unchanged(client):
    first = client.get("/static/js/generate.js")
    again = client.get("/static/js/generate.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


# ---------------------------------------------------------------- Generate page: options + "Your story"

def test_generate_options_endpoint(client, monkeypatch, tmp_path):
    from app.config import settings
    personas = tmp_path / "personas"
    monkeypatch.setattr(settings, "personas_dir", str(personas))
    monkeypatch.setattr(settings, "youtube_client_secrets", str(tmp_path / "client_secrets.json"))
    data = client.get("/api/generate/options").json()
    assert data["personas"] == [] and not personas.exists()
    assert data["upload_ready"] is False
    assert data["story_max_chars"] == 4000 and data["story_modes"] == ["verbatim", "adapt"]
    assert data["words_per_second"] == 2.2


@pytest.mark.parametrize("body, message", [
    ({"story": "", "story_mode": "verbatim"}, "empty"),
    ({"story": "   "}, "empty"),
    ({"story": "x" * 4001}, "4000"),
    ({"story": "Once.", "story_mode": "remix"}, "story_mode"),
    ({"persona": "nobody.png"}, "persona"),
])
def test_bad_story_or_extras_are_422(client, body, message):
    resp = client.post("/api/generate", json={"topic": "x", **body})
    assert resp.status_code == 422
    assert message in resp.json()["detail"]


def _capture_task(monkeypatch):
    import app.web.routes.api_generate as api
    tasks = []
    monkeypatch.setattr(api.asyncio, "create_task", lambda coro: tasks.append(coro))
    return tasks


def _run_task(monkeypatch, coro):
    import asyncio
    from app.web.ws import ws_manager

    async def quiet(*args, **kwargs):
        return None
    for name in ("send_progress", "send_complete", "send_error"):
        monkeypatch.setattr(ws_manager, name, quiet)
    asyncio.run(coro)


def test_story_request_runs_the_pipeline_with_the_story(client, monkeypatch):
    import main
    seen = {}
    monkeypatch.setattr(main, "run_pipeline", lambda **kw: seen.update(kw) or "output/j/final.mp4")
    monkeypatch.setattr("app.trend_scout.TrendScout.discover_topics",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no trend discovery for a story")))
    tasks = _capture_task(monkeypatch)
    resp = client.post("/api/generate", json={
        "topic": "", "story": "The bottle washed up.\n\nIt held a map.", "story_mode": "adapt", "title": "Bottle",
        "enable_subtitles": False, "classic": True, "use_mock": True, "upload": False})
    assert resp.status_code == 200 and len(tasks) == 1
    _run_task(monkeypatch, tasks[0])
    assert seen["story"] == "The bottle washed up. It held a map."
    assert seen["story_mode"] == "adapt" and seen["topic"] == "Bottle" and seen["source"] == "story"
    assert seen["enable_subtitles"] is False and seen["classic"] is True and seen["use_mock_images"] is True
    assert seen["persona"] is None and seen["upload"] is False


def test_topic_request_records_its_source(client, monkeypatch):
    import main
    seen = {}
    monkeypatch.setattr(main, "run_pipeline", lambda **kw: seen.update(kw) or "output/j/final.mp4")
    tasks = _capture_task(monkeypatch)
    client.post("/api/generate", json={"topic": "Gold facts"})
    _run_task(monkeypatch, tasks[0])
    assert seen["topic"] == "Gold facts" and seen["source"] == "topic" and seen["story"] == ""
