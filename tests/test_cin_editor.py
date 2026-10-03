"""render_job: shot render -> mix -> two-pass loudnorm -> mux -> checks (spec §9)."""
import json
from pathlib import Path

import pytest

from app.cin.editor import RenderOptions, pick_music, render_job
from app.cin.report import RunReport
from app.cin.shot_plan import build_shot_plan
from app.encoding import faststart_ok, probe_video
from tests.conftest import build_gold_job, make_silence, make_test_clip, make_tone, make_tone_wav


def _stream_durations(path):
    import json
    import subprocess
    from app.encoding import find_ffprobe
    out = subprocess.run([find_ffprobe(), "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
                         capture_output=True, text=True, check=True).stdout
    streams = {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}
    return streams["video"], streams["audio"]


def test_render_options_roundtrip_ignores_unknown_keys():
    opts = RenderOptions(pacing="fast", color_grade="tech")
    assert RenderOptions.from_json({**opts.to_json(), "topic": "x"}) == opts
    assert RenderOptions.from_json(None) == RenderOptions()


def test_pick_music_reports_missing_library(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "music_dir", str(tmp_path / "music"))
    monkeypatch.setattr(settings, "music_enabled", True)
    (tmp_path / "music" / "epic").mkdir(parents=True)
    report = RunReport(job="j")
    assert pick_music(RenderOptions(music_mood="epic"), report) is None
    assert [w["code"] for w in report.warnings] == ["music_missing"]
    assert pick_music(RenderOptions(enable_music=False), RunReport(job="j")) is None


class _TinyRenderer:
    """Stands in for ShotRenderer: writes a small clip instead of rendering frames."""

    def __init__(self, plan, job, **kwargs):
        self.plan = plan

    def render(self, out_path, overlays=None):
        return make_test_clip(out_path, self.plan.duration)


def test_silent_mix_skips_loudnorm_and_keeps_previous_final(tmp_path, monkeypatch):
    job, alignment, specs = build_gold_job(tmp_path)
    make_silence(job.narration, 8.0)
    job.final.write_bytes(b"old render")
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    report = RunReport(job=job.name)
    plan = build_shot_plan(alignment, "standard", specs)
    render_job(job, plan, RenderOptions(enable_music=False, enable_sfx=False, enable_subtitles=False), report)
    assert "loudness_skipped" in [w["code"] for w in report.warnings]
    assert job.final_prev.read_bytes() == b"old render"
    assert probe_video(job.final)["has_audio"] is True
    assert not job.render_tmp.exists()
    assert job.mix.exists()


def test_mix_is_trimmed_or_padded_to_plan_duration(tmp_path, monkeypatch):
    """Narration longer or shorter than the plan must not leave an audio/video tail."""
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    for narration_len in (9.5, 6.5):
        job, alignment, specs = build_gold_job(tmp_path / f"n{narration_len}")
        make_silence(job.narration, narration_len)
        plan = build_shot_plan(alignment, "standard", specs)
        render_job(job, plan, RenderOptions(enable_music=False, enable_sfx=False, enable_subtitles=False),
                   RunReport(job=job.name))
        video, audio = _stream_durations(job.final)
        assert abs(audio - video) <= 0.05, (narration_len, video, audio)
        assert abs(audio - plan.duration) <= 0.05


@pytest.mark.render
def test_render_job_full_size_meets_delivery_spec(tmp_path):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, "standard", specs)
    plan.shots[1].transition_in = "zoom_through"
    report = RunReport(job=job.name)
    final = render_job(job, plan, RenderOptions(enable_music=False, enable_sfx=False, color_grade="tech"), report)

    info = probe_video(final)
    assert (info["width"], info["height"], info["fps"]) == (1080, 1920, 30.0)
    assert info["pixel_format"] == "yuv420p" and info["color_primaries"] == "bt709"
    assert info["audio_codec"] == "aac" and info["audio_sample_rate"] == 48000
    assert abs(info["duration"] - 8.0) <= 0.05
    video, audio = _stream_durations(final)
    assert abs(audio - video) <= 0.05
    assert faststart_ok(final)
    assert -15.0 <= report.loudness["I"] <= -13.0
    assert report.loudness["TP"] <= -1.0
    assert report.platform_safe == {"ok": True, "issues": []}
    assert set(report.durations) >= {"render", "mix", "encode"}


def _tiny_render(tmp_path, monkeypatch):
    job, alignment, specs = build_gold_job(tmp_path)
    make_silence(job.narration, 8.0)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    plan = build_shot_plan(alignment, "standard", specs)
    opts = RenderOptions(enable_music=False, enable_sfx=False, enable_subtitles=False)
    return job, plan, opts


def test_locked_final_swap_writes_timestamped_file_and_warns(tmp_path, monkeypatch):
    import os
    import app.cin.editor as editor
    job, plan, opts = _tiny_render(tmp_path, monkeypatch)
    job.final.write_bytes(b"old render")
    real_replace = os.replace

    def locked(src, dst, *a, **k):
        if os.fspath(src) == os.fspath(job.final) or os.fspath(dst) == os.fspath(job.final_prev):
            raise PermissionError("locked by player")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(editor.os, "replace", locked)
    monkeypatch.setattr(editor.time, "sleep", lambda s: None)
    report = RunReport(job=job.name)
    out = render_job(job, plan, opts, report)
    assert out != job.final and out.parent == job.root and out.name.startswith("final.")
    assert probe_video(out)["has_audio"] is True
    assert job.final.read_bytes() == b"old render"
    warn = [w for w in report.warnings if w["code"] == "final_swap_failed"]
    assert warn and warn[0]["detail"]["path"] == str(out)


def test_platform_check_failure_is_warned(tmp_path, monkeypatch):
    job, plan, opts = _tiny_render(tmp_path, monkeypatch)
    monkeypatch.setattr("app.cin.editor.is_platform_safe", lambda p: (False, ["bad tp"]))
    report = RunReport(job=job.name)
    render_job(job, plan, opts, report)
    warn = [w for w in report.warnings if w["code"] == "platform_check_failed"]
    assert warn and warn[0]["detail"]["issues"] == ["bad tp"]


def test_new_warning_codes_registered():
    from app.cin.report import WARNING_CODES
    assert {"platform_check_failed", "final_swap_failed", "music_track_skipped", "sfx_file_skipped"} <= set(WARNING_CODES)


def _audio_library(tmp_path, monkeypatch, music=True, sfx=True):
    from app.config import settings
    music_dir, sfx_dir = tmp_path / "lib" / "music", tmp_path / "lib" / "sfx"
    (music_dir / "cinematic").mkdir(parents=True)
    (sfx_dir / "generated").mkdir(parents=True)
    if music:
        make_tone_wav(music_dir / "cinematic" / "track_a.wav", 12.0, 1000, 0.4)
    if sfx:
        make_tone_wav(sfx_dir / "generated" / "whoosh_1.wav", 0.8, 3000, 0.4)
        make_tone_wav(sfx_dir / "generated" / "impact_1.wav", 1.2, 80, 0.4)
        make_tone_wav(sfx_dir / "generated" / "riser_1.wav", 20.0, 2000, 0.4)   # longer than the video
    monkeypatch.setattr(settings, "music_dir", str(music_dir))
    monkeypatch.setattr(settings, "sfx_dir", str(sfx_dir))
    monkeypatch.setattr(settings, "music_enabled", True)
    monkeypatch.setattr(settings, "enable_sfx", True)
    return music_dir, sfx_dir


def test_pick_music_skips_short_and_corrupt_tracks(tmp_path, monkeypatch):
    music_dir, _ = _audio_library(tmp_path, monkeypatch, music=False, sfx=False)
    epic = music_dir / "epic"
    epic.mkdir()
    make_tone_wav(epic / "a_blip.wav", 0.5, 440, 0.3)             # shorter than 1 s
    (epic / "b_broken.mp3").write_bytes(b"\x00not an mp3" * 300)  # corrupt download
    good = make_tone_wav(epic / "c_good.wav", 5.0, 440, 0.3)
    report = RunReport(job="j")
    assert pick_music(RenderOptions(music_mood="epic"), report) == good
    skipped = [w for w in report.warnings if w["code"] == "music_track_skipped"]
    assert [Path(w["detail"]["file"]).name for w in skipped] == ["a_blip.wav", "b_broken.mp3"]
    good.unlink()
    report = RunReport(job="j")
    assert pick_music(RenderOptions(music_mood="epic"), report) is None
    assert [w["code"] for w in report.warnings][-1] == "music_missing"


def test_music_source_none_and_disabled_give_no_warning(tmp_path, monkeypatch):
    _audio_library(tmp_path, monkeypatch)
    for opts in (RenderOptions(music_source="none"), RenderOptions(enable_music=False)):
        report = RunReport(job="j")
        assert pick_music(opts, report) is None and report.warnings == []


def test_pick_music_honours_source_and_keep(tmp_path, monkeypatch):
    music_dir, _ = _audio_library(tmp_path, monkeypatch)
    gen = make_tone_wav(music_dir / "cinematic" / "generated" / "cinematic_01.wav", 6.0, 500, 0.3)
    mine = music_dir / "cinematic" / "track_a.wav"
    assert pick_music(RenderOptions(music_mood="cinematic", music_source="generated"), RunReport(job="j")) == gen
    assert pick_music(RenderOptions(music_mood="cinematic", music_source="mine"), RunReport(job="j")) == mine
    kept = pick_music(RenderOptions(music_mood="cinematic"), RunReport(job="j"), keep=mine.as_posix())
    assert kept == mine


def test_render_job_fills_plan_music_and_sfx(tmp_path, monkeypatch):
    music_dir, sfx_dir = _audio_library(tmp_path, monkeypatch)
    job, alignment, specs = build_gold_job(tmp_path)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    plan = build_shot_plan(alignment, "standard", specs)
    for shot in plan.shots:
        shot.transition_in = "cut"
    plan.shots[1].transition_in = "flash"
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(music_mood="cinematic", enable_subtitles=False), report)
    assert plan.music["file"] == (music_dir / "cinematic" / "track_a.wav").as_posix()
    assert plan.music["duck_windows"] and plan.music["source"] == "any"
    kinds = [e["kind"] for e in plan.sfx]
    assert kinds.count("impact") == 1 and kinds.count("whoosh") == len(plan.scenes) - 1
    assert kinds.count("riser") == 1
    assert report.options["music_file"] == plan.music["file"]
    assert not [w for w in report.warnings if w["code"] in ("music_missing", "sfx_missing")]
    import wave
    with wave.open(str(job.mix)) as w:
        assert w.getframerate() == 48000 and abs(w.getnframes() - round(plan.duration * 48000)) <= 1
    assert -15.0 <= report.loudness["I"] <= -13.0 and report.loudness["TP"] <= -1.0
    video, audio = _stream_durations(job.final)
    assert abs(audio - plan.duration) <= 0.05
    json.dumps(plan.to_json())                                     # serialisable contract


def test_render_job_survives_corrupt_music_and_sfx(tmp_path, monkeypatch):
    music_dir, sfx_dir = _audio_library(tmp_path, monkeypatch, music=False, sfx=False)
    (music_dir / "cinematic" / "bad.mp3").write_bytes(b"junk" * 500)
    (sfx_dir / "whoosh_bad.mp3").write_bytes(b"junk" * 50)
    job, alignment, specs = build_gold_job(tmp_path)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    plan = build_shot_plan(alignment, "standard", specs)
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(music_mood="cinematic", enable_subtitles=False), report)
    codes = [w["code"] for w in report.warnings]
    assert {"music_track_skipped", "music_missing", "sfx_file_skipped", "sfx_missing"} <= set(codes)
    assert plan.music is None and plan.sfx == [] and job.final.exists()


def test_sfx_disabled_by_setting_or_option(tmp_path, monkeypatch):
    from app.config import settings
    _audio_library(tmp_path, monkeypatch)
    job, alignment, specs = build_gold_job(tmp_path)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _TinyRenderer)
    monkeypatch.setattr(settings, "enable_sfx", False)
    plan = build_shot_plan(alignment, "standard", specs)
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(music_source="none", enable_subtitles=False), report)
    assert plan.sfx == [] and plan.music is None
    assert not [w for w in report.warnings if w["code"] in ("music_missing", "sfx_missing", "sfx_file_skipped")]
