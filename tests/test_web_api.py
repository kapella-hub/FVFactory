"""Tests for FastAPI web server."""
import pytest
from fastapi.testclient import TestClient
from app.web.server import app


@pytest.fixture
def client():
    return TestClient(app)


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
