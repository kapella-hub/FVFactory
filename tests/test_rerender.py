"""--rerender: rebuild final.mp4 from sources/ with zero API calls (spec §9.3)."""
import json
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


def _music_lib(tmp_path, monkeypatch):
    from app.config import settings
    from tests.conftest import make_tone_wav
    music = tmp_path / "lib" / "music"
    a = make_tone_wav(music / "cinematic" / "a.wav", 10.0, 900, 0.3)
    b = make_tone_wav(music / "cinematic" / "generated" / "cinematic_01.wav", 10.0, 700, 0.3)
    monkeypatch.setattr(settings, "music_dir", str(music))
    monkeypatch.setattr(settings, "music_enabled", True)
    monkeypatch.setattr(settings, "enable_sfx", False)
    return a, b


class _Tiny:
    def __init__(self, plan, job, **kwargs):
        self.plan = plan

    def render(self, out_path, overlays=None):
        from tests.conftest import make_test_clip
        return make_test_clip(out_path, self.plan.duration)


def _music_job(tmp_path, monkeypatch, root="a"):
    job, alignment, specs = build_gold_job(tmp_path / root)
    plan = build_shot_plan(alignment, "standard", specs)
    opts = RenderOptions(music_mood="cinematic", enable_sfx=False, enable_subtitles=False)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _Tiny)
    render_job(job, plan, opts, RunReport(job=job.name))
    plan.save(job.shot_plan)
    RunReport(job=job.name, options={**opts.to_json(), "enable_motion": True}).save(job.report)
    return job, plan


def test_rerender_keeps_music_without_override(tmp_path, monkeypatch):
    a, b = _music_lib(tmp_path, monkeypatch)
    job, plan = _music_job(tmp_path, monkeypatch)
    assert plan.music["file"] == a.as_posix()
    rerender_job(job.root, pacing="fast")
    assert ShotPlan.load(job.shot_plan).music["file"] == a.as_posix()      # no LRU re-pick


def test_rerender_music_source_override_reselects(tmp_path, monkeypatch):
    a, b = _music_lib(tmp_path, monkeypatch)
    job, plan = _music_job(tmp_path, monkeypatch)
    rerender_job(job.root, music_source="generated")
    new = ShotPlan.load(job.shot_plan)
    assert new.music["file"] == b.as_posix() and new.music["source"] == "generated"
    assert RunReport.load(job.report).options["music_source"] == "generated"
    rerender_job(job.root, no_music=True)
    assert ShotPlan.load(job.shot_plan).music is None


def test_rerender_moved_job_keeps_repo_relative_music(tmp_path, monkeypatch):
    """Library paths are cwd-relative asset paths, never resolved against the job folder."""
    from app.config import settings
    monkeypatch.chdir(tmp_path)
    from tests.conftest import make_tone_wav
    make_tone_wav(tmp_path / "assets" / "music" / "cinematic" / "rel.wav", 10.0, 800, 0.3)
    monkeypatch.setattr(settings, "music_dir", "assets/music")
    monkeypatch.setattr(settings, "music_enabled", True)
    monkeypatch.setattr(settings, "enable_sfx", False)
    job, plan = _music_job(tmp_path, monkeypatch)
    assert plan.music["file"] == "assets/music/cinematic/rel.wav"
    moved = tmp_path / "moved" / job.name
    shutil.copytree(job.root, moved)
    rerender_job(moved, pacing="fast")
    assert ShotPlan.load(open_job(moved).shot_plan).music["file"] == "assets/music/cinematic/rel.wav"


def test_rerender_report_write_failure_does_not_mask_render_error(tmp_path, monkeypatch):
    job, plan = saved_job(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("render died")

    def disk_full(self, path):
        raise OSError("disk full")

    monkeypatch.setattr("app.cin.editor.render_job", boom)
    monkeypatch.setattr(RunReport, "save", disk_full)
    with pytest.raises(RuntimeError, match="render died"):
        rerender_job(job.root, pacing="fast")


def _set_fallback(job, fallback, reason=""):
    data = json.loads(job.alignment.read_text(encoding="utf-8"))
    data["fallback"], data["reason"] = fallback, reason
    job.alignment.write_text(json.dumps(data), encoding="utf-8")


def test_rerender_rederives_alignment_fallback_from_alignment_json(tmp_path, monkeypatch):
    job, _ = saved_job(tmp_path)
    _set_fallback(job, True, "match ratio 0.41")
    monkeypatch.setattr("app.cin.editor.render_job", lambda *a, **k: job.final)
    rerender_job(job.root)
    found = [w for w in RunReport.load(job.report).warnings if w["code"] == "alignment_fallback"]
    assert len(found) == 1 and found[0]["detail"]["reason"] == "match ratio 0.41"


def test_rerender_drops_stale_alignment_fallback(tmp_path, monkeypatch):
    job, _ = saved_job(tmp_path)
    prev = RunReport.load(job.report)
    prev.warn("alignment_fallback", "old", {"reason": "old"})
    prev.save(job.report)
    monkeypatch.setattr("app.cin.editor.render_job", lambda *a, **k: job.final)
    rerender_job(job.root)
    assert not [w for w in RunReport.load(job.report).warnings if w["code"] == "alignment_fallback"]


def test_rerender_post_render_plan_save_failure_warns(tmp_path, monkeypatch):
    job, _ = saved_job(tmp_path)
    monkeypatch.setattr("app.cin.editor.render_job", lambda *a, **k: job.final)

    def locked(self, path):
        raise PermissionError("shot_plan.json locked")

    monkeypatch.setattr(ShotPlan, "save", locked)
    assert rerender_job(job.root) == str(job.final)
    rep = RunReport.load(job.report)
    assert rep.status == "ok" and [w["code"] for w in rep.warnings].count("plan_save_failed") == 1


def test_rebuild_plan_keeps_roles_and_beat_transitions(tmp_path):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, "standard", specs, roles=["hook", "loop"])
    plan.save(job.shot_plan)
    new = rebuild_plan(job, "fast")
    assert [s.role for s in new.scenes] == ["hook", "loop"]
    assert [(s.scene, s.transition_in) for s in new.shots if s.transition_in != "cut"] == \
        [(s.scene, s.transition_in) for s in plan.shots if s.transition_in != "cut"]


def test_rebuild_legacy_plan_without_roles_keeps_pause_transitions(tmp_path):
    job, old = saved_job(tmp_path)                       # saved before roles existed: no "role" keys
    assert all("role" not in s for s in json.loads(job.shot_plan.read_text(encoding="utf-8"))["scenes"])
    new = rebuild_plan(job, "standard")
    assert all(s.role is None for s in new.scenes)
    assert [s.transition_in for s in new.shots] == [s.transition_in for s in old.shots]



def test_rerender_carries_script_section_and_script_warnings(tmp_path, monkeypatch):
    job, _ = saved_job(tmp_path)
    prev = RunReport.load(job.report)
    prev.script = {"preset": "medium", "words": 150, "narration_seconds": 58.1}
    for code in ("script_length_off_target", "scene_roles_derived", "hook_headline_fallback"):
        prev.warn(code, code)
    prev.save(job.report)
    monkeypatch.setattr("app.cin.editor.render_job", lambda *a, **k: job.final)
    rerender_job(job.root, pacing="fast")
    rep = RunReport.load(job.report)
    assert rep.script == {"preset": "medium", "words": 150, "narration_seconds": 58.1}
    assert [w["code"] for w in rep.warnings] == ["script_length_off_target", "scene_roles_derived",
                                                 "hook_headline_fallback"]


def test_rerender_of_a_kling_plan_makes_no_generator_calls(tmp_path, monkeypatch):
    """Quality tiers (spec 2026-10-03 §4.2): "kling" now names Kling v3; a re-render of an old plan
    that names it reuses the saved clips and never calls a motion generator."""
    job, plan = saved_job(tmp_path)                 # build_gold_job made every clip with model "kling"
    prev = RunReport.load(job.report)
    prev.clips = {"requested": 2, "generated": 2, "failed": 0, "by_model": {"kling": 2}}
    prev.save(job.report)

    def no_generation(*args, **kwargs):
        raise AssertionError("motion generator called during rerender")

    monkeypatch.setattr("app.motion_gen.MotionGenerator.generate_clip", no_generation)
    monkeypatch.setattr("app.motion_gen.MotionGenerator._generate_fal", no_generation)
    monkeypatch.setattr("app.cin.clip_sourcing.generate_segment_clips", no_generation)
    monkeypatch.setitem(sys.modules, "fal_client", None)
    monkeypatch.setattr("app.cin.editor.render_job", lambda *a, **k: job.final)
    assert rerender_job(job.root, pacing="fast") == str(job.final)
    assert all(s.source.type == "clip" for s in ShotPlan.load(job.shot_plan).shots)
    assert RunReport.load(job.report).clips["by_model"] == {"kling": 2}
