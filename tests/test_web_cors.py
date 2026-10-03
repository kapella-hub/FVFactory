"""CORS origins for the web UI (pure helper; fastapi is not installed in every test environment)."""
import pytest

from app.web.cors import cors_origin_list


@pytest.mark.parametrize("value, expected", [
    ("", []),
    ("   ", []),
    (None, []),
    ("http://localhost:3000", ["http://localhost:3000"]),
    (" http://a.example , https://b.example:8443/ ,,", ["http://a.example", "https://b.example:8443"]),
    ("http://a.example,http://a.example", ["http://a.example"]),
])
def test_cors_origin_list(value, expected):
    assert cors_origin_list(value) == expected


def test_server_has_no_wildcard_cors():
    from pathlib import Path
    src = (Path(__file__).parents[1] / "app/web/server.py").read_text(encoding="utf-8")
    assert 'allow_origins=["*"]' not in src
    assert "cors_origin_list(settings.cors_origins)" in src
