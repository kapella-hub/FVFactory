"""Clip sourcing: chaining, retry -> fallback -> failure, parallelism (spec §6.4, §10)."""
import sys
import threading
import time
from pathlib import Path

from PIL import Image

from app.cin.clip_sourcing import generate_segment_clips
from app.cin.job import create_job
from app.cin.report import RunReport
from app.cin.shot_plan import build_shot_plan, plan_segments
from tests.conftest import fixture_alignment, make_test_clip


class FakeGenerator:
    """Stands in for MotionGenerator.generate_clip. fail(start_name, out_name, model_key) -> bool."""

    def __init__(self, fail=lambda start, out, model: False, delay=0.0, length=None):
        self.fail, self.delay, self.length = fail, delay, length
        self.calls = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def generate_clip(self, image_path, prompt, output_path, duration=None, model_key=None):
        with self._lock:
            self.calls.append((Path(image_path).name, Path(output_path).name, model_key))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            if self.fail(Path(image_path).name, Path(output_path).name, model_key):
                return None
            make_test_clip(output_path, self.length or duration)
            return output_path
        finally:
            with self._lock:
                self.active -= 1


def gold_job(tmp_path, durations=(6.0,)):
    job = create_job("gold", tmp_path / "output")
    alignment = fixture_alignment("words_gold_8s.json")
    images = []
    for i in range(len(alignment.scenes)):
        Image.new("RGB", (108, 192), (200, 30 * i, 30)).save(job.image(i))
        images.append(str(job.image(i)))
    return job, alignment, plan_segments(alignment, durations), images


def run(job, segs, images, gen, **kw):
    report = RunReport(job=job.name)
    specs = generate_segment_clips(segs, images, ["push in", "orbit"], job, report, generator=gen, **kw)
    return specs, report


def test_chained_segment_starts_from_previous_last_frame(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    specs, report = run(job, segs, images, FakeGenerator())
    assert [(s.scene, s.index) for s in specs] == [(0, 0), (1, 0), (1, 1)]
    assert specs[2].start_image == "sources/clips/scene01_a_last.png"
    assert (job.root / specs[2].start_image).exists()
    assert specs[1].path == "sources/clips/scene01_a.mp4"
    assert abs(specs[1].duration - 6.0) < 0.1
    assert report.clips == {"requested": 3, "generated": 3, "failed": 0, "by_model": {"hailuo": 3}}


def test_retry_then_fallback_model(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    gen = FakeGenerator(fail=lambda start, out, model: out == "scene00_a.mp4" and model == "hailuo")
    specs, report = run(job, segs, images, gen, fallback_model="kling")
    assert [c[2] for c in gen.calls if c[1] == "scene00_a.mp4"] == ["hailuo", "hailuo", "kling"]
    assert specs[0].model == "kling" and specs[0].attempts == 3 and specs[0].path
    assert [w["code"] for w in report.warnings] == ["clip_retry"]


def test_failed_first_segment_chains_from_scene_image(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    specs, _ = run(job, segs, images, FakeGenerator(fail=lambda start, out, model: out == "scene01_a.mp4"))
    assert specs[1].failed and specs[1].path is None
    assert specs[2].start_image == "sources/images/scene01.png"


def test_all_clips_failing_never_raises(tmp_path):
    job, alignment, segs, images = gold_job(tmp_path)
    specs, report = run(job, segs, images, FakeGenerator(fail=lambda *a: True))
    assert all(s.failed and s.path is None for s in specs)
    assert report.clips["failed"] == 3 and report.clips["generated"] == 0
    plan = build_shot_plan(alignment, "standard", specs)
    assert all(s.source.type == "still" for s in plan.shots)
    assert [w["code"] for w in plan.warnings] == ["still_fallback"] * 3


def test_motion_disabled_makes_no_calls(tmp_path):
    job, _, _, images = gold_job(tmp_path)
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), None)
    gen = FakeGenerator()
    specs, report = run(job, segs, images, gen, enable_motion=False)
    assert gen.calls == []
    assert all(s.path is None and not s.failed for s in specs)
    assert report.clips["requested"] == 0


def test_scenes_run_in_parallel(tmp_path):
    job, _, _, images = gold_job(tmp_path)
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), (10.0,))   # 2 scenes, 1 segment each
    gen = FakeGenerator(delay=0.3, length=1.0)
    run(job, segs, images, gen, concurrency=4)
    assert gen.max_active == 2


def test_short_clip_reports_real_duration(tmp_path):
    job, _, segs, images = gold_job(tmp_path)
    specs, _ = run(job, segs, images, FakeGenerator(length=2.0))
    assert all(abs(s.duration - 2.0) < 0.1 for s in specs)
