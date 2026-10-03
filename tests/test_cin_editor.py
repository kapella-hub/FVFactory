"""render_job: shot render -> mix -> two-pass loudnorm -> mux -> checks (spec §9)."""
import pytest

from app.cin.editor import RenderOptions, pick_music, render_job
from app.cin.report import RunReport
from app.cin.shot_plan import build_shot_plan
from app.encoding import faststart_ok, probe_video
from tests.conftest import build_gold_job, make_silence, make_test_clip


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
