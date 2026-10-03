import json
import os
import time
from pathlib import Path

from app.library import find_videos, resolve_video


def _touch(path: Path, data: bytes = b"x", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_finds_job_folder_and_legacy_videos_newest_first(tmp_path):
    now = time.time()
    _touch(tmp_path / "old_flat.mp4", mtime=now - 100)
    _touch(tmp_path / "20261002_1200_rolex" / "final.mp4", mtime=now)
    _touch(tmp_path / "20261002_1200_rolex" / "final.prev.mp4", mtime=now)
    (tmp_path / "metadata").mkdir()
    (tmp_path / "metadata" / "20261002_1200_rolex.json").write_text(json.dumps({"title": "Rolex"}))
    _touch(tmp_path / "thumbnails" / "20261002_1200_rolex.png")

    videos = find_videos(tmp_path)

    assert [v["id"] for v in videos] == ["20261002_1200_rolex", "old_flat"]
    assert videos[0]["metadata"] == {"title": "Rolex"}
    assert videos[0]["has_thumbnail"] is True
    assert videos[1]["metadata"] is None


def test_folder_without_final_is_ignored(tmp_path):
    _touch(tmp_path / "20261002_1300_failed" / "sources" / "narration.mp3")
    assert find_videos(tmp_path) == []


def test_resolve_prefers_job_folder_then_legacy(tmp_path):
    job = _touch(tmp_path / "abc" / "final.mp4")
    flat = _touch(tmp_path / "legacy.mp4")
    assert resolve_video(tmp_path, "abc") == job
    assert resolve_video(tmp_path, "legacy") == flat
    assert resolve_video(tmp_path, "missing") is None


def test_resolve_rejects_path_traversal(tmp_path):
    _touch(tmp_path.parent / "secret" / "final.mp4")
    assert resolve_video(tmp_path, "../secret") is None
    assert resolve_video(tmp_path, r"..\secret") is None


def test_missing_output_dir_returns_empty(tmp_path):
    assert find_videos(tmp_path / "nope") == []


def test_safe_id_rejects_trailing_newline_directly():
    from app.library import _SAFE_ID
    assert _SAFE_ID.fullmatch("abc") and not _SAFE_ID.fullmatch("abc\n")


def test_resolve_rejects_trailing_newline(tmp_path):
    _touch(tmp_path / "abc" / "final.mp4")
    assert resolve_video(tmp_path, "abc") is not None
    assert resolve_video(tmp_path, "abc\n") is None
