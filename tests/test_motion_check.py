"""Low-motion check of generated clips (user feedback 2026-10-03: "why is it not full motion?").
Synthetic clips: a solid colour never changes (score 0), testsrc2 moves across the whole frame."""
import subprocess

import pytest

from app.cin.shot_plan import ClipSpec
from app.cin.job import JobPaths
from app.cin.motion_check import check_clip_motion, clip_motion_score
from app.cin.report import RunReport
from tests.conftest import ffmpeg_exe, make_color_clip


def make_moving_clip(path, seconds: float = 1.0, size: str = "108x192", rate: int = 24):
    subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@pytest.fixture
def job(tmp_path):
    return JobPaths(tmp_path / "job").ensure()


def spec(job, name, scene, path=True):
    s = ClipSpec(scene, 0, 0.0, 1.0, 5.0, f"sources/images/scene{scene:02d}.png")
    if path:
        s.path = job.rel(job.clip(name))
    return s


def test_solid_colour_clip_scores_zero(tmp_path):
    assert clip_motion_score(make_color_clip(tmp_path / "still.mp4", 1.0, "blue")) == 0.0


def test_moving_clip_scores_high(tmp_path):
    assert clip_motion_score(make_moving_clip(tmp_path / "moving.mp4")) > 2.0


@pytest.mark.parametrize("content", [None, b"", b"not a video"])
def test_missing_or_unreadable_file_is_none(tmp_path, content):
    path = tmp_path / "bad.mp4"
    if content is not None:
        path.write_bytes(content)
    assert clip_motion_score(path) is None


def test_ffmpeg_timeout_or_crash_is_none(tmp_path, monkeypatch):
    clip = make_color_clip(tmp_path / "still.mp4", 1.0, "blue")

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))
    monkeypatch.setattr("app.cin.motion_check.subprocess.run", boom)
    assert clip_motion_score(clip) is None


def test_ffmpeg_is_called_with_list_args_and_a_timeout(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(cmd=cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, "frame:0\nlavfi.signalstats.YDIF=0\n"
                                                   "frame:1\nlavfi.signalstats.YDIF=1.5\n"
                                                   "frame:2\nlavfi.signalstats.YDIF=0.5\n", "")
    clip = tmp_path / "a b.mp4"
    clip.write_bytes(b"x")
    monkeypatch.setattr("app.cin.motion_check.subprocess.run", fake_run)
    assert clip_motion_score(clip) == 1.0          # frame 0 (no predecessor, always 0) is excluded
    assert isinstance(seen["cmd"], list) and str(clip) in seen["cmd"]
    assert "scale=270:-2" in " ".join(seen["cmd"]) and seen["timeout"] == 30
    assert not seen.get("shell")


def test_low_clips_get_one_warning_with_scores(job):
    make_color_clip(job.clip("scene00_a"), 1.0, "blue")
    make_moving_clip(job.clip("scene01_a"))
    make_color_clip(job.clip("scene02_a"), 1.0, "red")
    specs = [spec(job, "scene00_a", 0), spec(job, "scene01_a", 1), spec(job, "scene02_a", 2),
             spec(job, "scene03_a", 3, path=False)]          # a failed clip (still) is not scored
    report = RunReport(job="j")
    low = check_clip_motion(specs, job, report, threshold=1.2)
    assert low == [("scene00_a", 0.0), ("scene02_a", 0.0)]
    assert len(report.warnings) == 1
    w = report.warnings[0]
    assert w["code"] == "low_motion"
    assert w["message"] == "2 of 3 clips barely move (scene00_a 0.00, scene02_a 0.00)"
    assert w["detail"]["threshold"] == 1.2 and w["detail"]["scored"] == 3
    assert w["detail"]["clips"] == [{"clip": "scene00_a", "score": 0.0}, {"clip": "scene02_a", "score": 0.0}]
    scores = report.clips["motion_scores"]
    assert set(scores) == {"scene00_a", "scene01_a", "scene02_a"} and scores["scene01_a"] > 2.0


def test_no_warning_when_every_clip_moves(job):
    make_moving_clip(job.clip("scene00_a"))
    report = RunReport(job="j")
    assert check_clip_motion([spec(job, "scene00_a", 0)], job, report, threshold=1.2) == []
    assert report.warnings == [] and report.clips["motion_scores"]["scene00_a"] > 2.0


def test_threshold_zero_disables_the_check(job):
    calls = []
    report = RunReport(job="j")
    low = check_clip_motion([spec(job, "scene00_a", 0)], job, report, threshold=0,
                            scorer=lambda p: calls.append(p) or 0.0)
    assert low == [] and calls == [] and report.warnings == [] and "motion_scores" not in report.clips


def test_unscorable_and_crashing_clips_never_raise_or_warn(job):
    def scorer(path):
        if path.stem == "scene00_a":
            raise RuntimeError("probe exploded")
        return None
    report = RunReport(job="j")
    low = check_clip_motion([spec(job, "scene00_a", 0), spec(job, "scene01_a", 1)], job, report,
                            threshold=1.2, scorer=scorer)
    assert low == [] and report.warnings == []
