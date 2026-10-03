"""Job folder layout, naming, path handling and pruning (spec §9.2)."""
import os
import threading
import time
from datetime import datetime

import pytest

from app.cin.job import JobPaths, create_job, open_job, prune_sources, slugify

NOW = datetime(2026, 10, 2, 14, 30, 5)


def test_create_job_layout(tmp_path):
    job = create_job("History of Rolex", tmp_path / "output", now=NOW)
    assert job.name == "20261002_143005_history_of_rolex"
    assert job.images.is_dir() and job.clips.is_dir()
    assert job.narration == job.root / "sources" / "narration.mp3"
    assert job.shot_plan.name == "shot_plan.json" and job.mix.name == "mix.wav"
    assert job.final == job.root / "final.mp4" and job.report == job.root / "run_report.json"
    assert job.image(3).name == "scene03.png"
    assert job.clip("scene03_b").name == "scene03_b.mp4"
    assert job.last_frame("scene03_a").name == "scene03_a_last.png"


def test_create_job_is_unique_under_concurrency(tmp_path):
    out = tmp_path / "output"
    jobs = []
    threads = [threading.Thread(target=lambda: jobs.append(create_job("same topic", out, now=NOW)))
               for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    names = sorted(j.name for j in jobs)
    assert len(set(names)) == 8
    assert "20261002_143005_same_topic" in names and "20261002_143005_same_topic_8" in names


def test_slug_is_windows_safe():
    slug = slugify('Rolex: "Why?" <CON>/..\\x | 100%')
    assert slug == "rolex_why_con_x_100"
    assert slugify("CON") == "con_"
    assert slugify("???") == "video"
    assert len(slugify("a" * 200)) == 40


def test_rel_and_resolve_are_posix_and_relative(tmp_path):
    job = create_job("x", tmp_path / "out dir with spaces", now=NOW)
    rel = job.rel(job.clip("scene00_a"))
    assert rel == "sources/clips/scene00_a.mp4"
    assert job.resolve(rel) == job.clip("scene00_a")
    outside = tmp_path / "elsewhere.mp3"
    assert job.rel(outside) == outside.as_posix()


def test_open_job_requires_sources(tmp_path):
    job = create_job("x", tmp_path, now=NOW)
    assert open_job(job.root) == JobPaths(job.root)
    with pytest.raises(FileNotFoundError):
        open_job(tmp_path / "not_a_job")


def _finished_job(out, topic, age_days):
    job = create_job(topic, out, now=NOW)
    job.final.write_bytes(b"mp4")
    job.report.write_text("{}", encoding="utf-8")
    old = time.time() - age_days * 86400
    os.utime(job.sources, (old, old))
    return job


def test_prune_removes_only_old_sources(tmp_path):
    out = tmp_path / "output"
    old = _finished_job(out, "old", 20)
    fresh = _finished_job(out, "fresh", 1)
    (out / "metadata").mkdir()
    legacy = out / "legacy_job"
    (legacy / "sources").mkdir(parents=True)          # no run_report.json: not ours, never touched
    os.utime(legacy / "sources", (0, 0))

    removed = prune_sources(out, keep_days=14)

    assert removed == [old.sources]
    assert not old.sources.exists() and old.final.exists() and old.report.exists()
    assert fresh.sources.exists()
    assert (out / "metadata").exists() and (legacy / "sources").exists()


def test_prune_disabled_with_zero_days(tmp_path):
    old = _finished_job(tmp_path, "old", 400)
    assert prune_sources(tmp_path, keep_days=0) == []
    assert old.sources.exists()
