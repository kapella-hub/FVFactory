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


def test_job_folder_entries_carry_run_report_warnings(tmp_path):
    from app.cin.report import RunReport
    job = tmp_path / "20261003_0900_gold"
    _touch(job / "final.mp4")
    report = RunReport(job=job.name, status="ok")
    report.warn("still_fallback", "scene 2 is a still", {"scene": 2})
    report.save(job / "run_report.json")
    _touch(tmp_path / "legacy.mp4")
    by_id = {v["id"]: v for v in find_videos(tmp_path)}
    assert by_id[job.name]["status"] == "ok"
    assert [w["code"] for w in by_id[job.name]["warnings"]] == ["still_fallback"]
    assert by_id["legacy"]["warnings"] == [] and by_id["legacy"]["status"] is None


def test_missing_or_corrupt_report_never_breaks_the_listing(tmp_path):
    _touch(tmp_path / "a" / "final.mp4")                      # no run_report.json
    _touch(tmp_path / "b" / "final.mp4")
    (tmp_path / "b" / "run_report.json").write_bytes(b"{truncated")
    videos = {v["id"]: v for v in find_videos(tmp_path)}
    assert videos["a"]["status"] == "unknown" and videos["a"]["warnings"] == []
    assert videos["b"]["status"] == "unknown" and videos["b"]["warnings"] == []


def _meta(root: Path, video_id: str, data: dict) -> None:
    (root / "metadata").mkdir(exist_ok=True)
    (root / "metadata" / f"{video_id}.json").write_text(json.dumps(data), encoding="utf-8")


def test_title_prefers_youtube_then_tiktok_title(tmp_path):
    _touch(tmp_path / "20261003_153038_why_gold_never_rusts" / "final.mp4")
    _touch(tmp_path / "20261003_000841_history_of_rolex" / "final.mp4")
    _meta(tmp_path, "20261003_153038_why_gold_never_rusts",
          {"title_youtube": "Why Gold Never Rusts", "title_tiktok": "gold never rusts?! #science"})
    _meta(tmp_path, "20261003_000841_history_of_rolex", {"title_tiktok": "The Rolex story"})
    titles = {v["id"]: v["title"] for v in find_videos(tmp_path)}
    assert titles == {"20261003_153038_why_gold_never_rusts": "Why Gold Never Rusts",
                      "20261003_000841_history_of_rolex": "The Rolex story"}


def test_title_falls_back_to_run_topic_then_folder_name(tmp_path):
    job = tmp_path / "20261003_120000_gold_facts"
    _touch(job / "final.mp4")
    (job / "run_report.json").write_text(json.dumps({"status": "ok", "options": {"topic": "Gold facts!"}}),
                                         encoding="utf-8")
    _touch(tmp_path / "20261002_2142_history_of_adp" / "final.mp4")      # no metadata, no report
    _touch(tmp_path / "my_old_video.mp4")                                  # legacy flat file
    titles = {v["id"]: v["title"] for v in find_videos(tmp_path)}
    assert titles == {"20261003_120000_gold_facts": "Gold facts!",
                      "20261002_2142_history_of_adp": "History of adp",
                      "my_old_video": "My old video"}


def test_download_name_is_the_job_not_final(tmp_path):
    _touch(tmp_path / "20261003_120000_gold_facts" / "final.mp4")
    _touch(tmp_path / "legacy_clip.mp4")
    names = {v["id"]: v["download_name"] for v in find_videos(tmp_path)}
    assert names == {"20261003_120000_gold_facts": "20261003_120000_gold_facts.mp4",
                     "legacy_clip": "legacy_clip.mp4"}
