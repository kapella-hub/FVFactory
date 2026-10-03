"""--rerender: rebuild final.mp4 from sources/ with zero API calls (spec §9.3)."""
import shutil
import sys

import pytest

from app.cin.editor import RenderOptions, clip_specs_from_plan, rebuild_plan, render_job, rerender_job
from app.cin.job import open_job
from app.cin.report import RunReport
from app.cin.shot_plan import ShotPlan, build_shot_plan
from app.encoding import probe_video
from tests.conftest import build_gold_job


def saved_job(tmp_path, pacing="standard"):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, pacing, specs)
    plan.save(job.shot_plan)
    opts = RenderOptions(pacing=pacing, enable_music=False, enable_sfx=False)
    RunReport(job=job.name, options={**opts.to_json(), "enable_motion": True}).save(job.report)
    return job, plan


def test_rebuild_plan_changes_cuts_not_scenes(tmp_path):
    job, old = saved_job(tmp_path)
    new = rebuild_plan(job, "fast")
    assert len(old.shots) == 3 and len(new.shots) == 4
    assert [(s.t0, s.t1) for s in new.scenes] == [(s.t0, s.t1) for s in old.scenes]
    assert [g.clip for s in new.scenes for g in s.segments] == [g.clip for s in old.scenes for g in s.segments]


def test_missing_clip_becomes_failed_segment(tmp_path):
    job, old = saved_job(tmp_path)
    job.clip("scene01_a").unlink()
    specs = clip_specs_from_plan(old, job, enable_motion=True)
    assert specs[1].path is None and specs[1].failed is True
    assert specs[0].path == "sources/clips/scene00_a.mp4" and abs(specs[0].duration - 5.0) < 0.1


def test_rebuild_plan_after_moving_job_folder(tmp_path):
    job, old = saved_job(tmp_path)
    moved = shutil.move(str(job.root), str(tmp_path / "moved dir with spaces" / job.name))
    new = rebuild_plan(open_job(moved), "standard")
    assert [s.source.path for s in new.shots] == [s.source.path for s in old.shots]
    assert all(s.source.type == "clip" for s in new.shots)


def test_rerender_requires_a_job_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        rerender_job(tmp_path / "nope")


@pytest.mark.render
def test_rerender_fast_pacing_zero_network(tmp_path, monkeypatch):
    import requests

    def no_network(*args, **kwargs):
        raise AssertionError("network call during rerender")

    monkeypatch.setattr(requests, "get", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    monkeypatch.setitem(sys.modules, "fal_client", None)
    monkeypatch.setattr("app.cin.align.transcribe_words", no_network)

    job, old = saved_job(tmp_path)
    render_job(job, old, RenderOptions(enable_music=False, enable_sfx=False), RunReport(job=job.name))
    first = job.final.stat().st_mtime_ns

    out = rerender_job(job.root, pacing="fast")

    assert out == str(job.final)
    assert job.final_prev.exists() and job.final.stat().st_mtime_ns >= first
    new = ShotPlan.load(job.shot_plan)
    assert new.pacing == "fast" and len(new.shots) == 4
    assert [(s.t0, s.t1) for s in new.scenes] == [(s.t0, s.t1) for s in old.scenes]
    report = RunReport.load(job.report)
    assert report.status == "ok" and report.options["pacing"] == "fast" and report.options["rerender"] is True
    info = probe_video(job.final)
    assert (info["width"], info["height"], info["fps"]) == (1080, 1920, 30.0)


def test_failed_rerender_keeps_old_plan_and_saves_prev_report(tmp_path, monkeypatch):
    job, plan = saved_job(tmp_path)
    old_plan = job.shot_plan.read_bytes()
    old_report = job.report.read_bytes()

    def boom(*a, **k):
        raise RuntimeError("render died")

    monkeypatch.setattr("app.cin.editor.render_job", boom)
    with pytest.raises(RuntimeError):
        rerender_job(job.root, pacing="fast")
    assert job.shot_plan.read_bytes() == old_plan
    prev = job.root / "run_report.prev.json"
    assert prev.exists() and prev.read_bytes() == old_report
