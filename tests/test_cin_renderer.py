"""Shot renderer: sources, framing, still push-in, transitions, output format (spec §6, §9.1)."""
import random

import numpy as np
import pytest

from app.cin.job import create_job
from app.cin.particles import ParticleSystem
from app.cin.renderer import RenderError, ShotRenderer, apply_framing, cover_fit
from app.cin.shot_plan import Scene, Segment, Shot, ShotPlan, ShotSource
from app.encoding import probe_video
from tests.conftest import make_color_clip

W, H = 108, 192


def test_cover_fit_crops_instead_of_stretching():
    landscape = np.zeros((100, 300, 3), np.uint8)
    landscape[:, :100] = (255, 0, 0)
    landscape[:, 100:200] = (0, 255, 0)
    landscape[:, 200:] = (0, 0, 255)
    out = cover_fit(landscape, W, H)
    assert out.shape == (H, W, 3)
    assert (out[:, :, 1] > 200).all() and (out[:, :, 0] < 50).all()   # only the green middle survives


def test_apply_framing_keeps_size():
    frame = np.random.randint(0, 255, (H, W, 3), np.uint8)
    assert apply_framing(frame, 1.0, W, H) is frame
    assert apply_framing(frame, 1.18, W, H).shape == (H, W, 3)


def test_particles_do_not_reseed_global_random():
    random.seed(1)
    expected = random.random()
    random.seed(1)
    ParticleSystem(preset="dust", width=W, height=H)
    assert random.random() == expected


def two_shot_plan(job, transition="cut", second_type="clip"):
    red = make_color_clip(job.clip("scene00_a"), 1.5, "red")
    blue = make_color_clip(job.clip("scene01_a"), 1.5, "blue")
    second = (ShotSource("clip", job.rel(blue), 0.0, 1.0, 1.0) if second_type == "clip"
              else ShotSource("still", "sources/images/scene01.png", move="push_in"))
    if second_type == "still":
        from PIL import Image
        _gradient_image(job.image(1))
    return ShotPlan(
        duration=2.0, fps=30, pacing="standard", alignment={"method": "whisper+script", "fallback": False, "match_ratio": 1.0},
        scenes=[Scene(0, 0.0, 1.0, "a", [Segment(0.0, 1.0, job.rel(red), 6.0, "sources/images/scene00.png")]),
                Scene(1, 1.0, 2.0, "b", [Segment(1.0, 2.0, job.rel(blue), 6.0, "sources/images/scene01.png")])],
        shots=[Shot(0, 0, 0.0, 1.0, ShotSource("clip", job.rel(red), 0.0, 1.0, 1.0), 1.0, "cut"),
               Shot(1, 1, 1.0, 2.0, second, 1.0, transition)],
        captions=[],
    )


def _gradient_image(path):
    """Blue image with a bright centre square, so a push-in visibly changes the frame."""
    from PIL import Image
    img = Image.new("RGB", (W, H), (0, 0, 255))
    img.paste((255, 255, 0), (W // 2 - 10, H // 2 - 10, W // 2 + 10, H // 2 + 10))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def renderer(job, plan):
    return ShotRenderer(plan, job, video_style="comic_book", width=W, height=H)   # comic_book: no particles


def test_frames_follow_the_shot_list(tmp_path):
    job = create_job("r", tmp_path)
    r = renderer(job, two_shot_plan(job))
    try:
        a, b = r.frame_at(0.5).mean(axis=(0, 1)), r.frame_at(1.5).mean(axis=(0, 1))
    finally:
        r.sources.close()
    assert a[0] > 200 and a[2] < 60
    assert b[2] > 200 and b[0] < 60


def test_flash_transition_uses_both_moving_shots(tmp_path):
    job = create_job("r", tmp_path)
    r = renderer(job, two_shot_plan(job, transition="flash"))
    try:
        assert r.frame_at(0.97).mean() > 250                        # white peak inside the 0.3 s window
        assert r.frame_at(0.80).mean(axis=(0, 1))[0] > 200          # before the window: plain red
        assert r.frame_at(1.20).mean(axis=(0, 1))[2] > 200          # after the window: plain blue
    finally:
        r.sources.close()


def test_still_shot_pushes_in(tmp_path):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job, second_type="still")
    r = renderer(job, plan)
    try:
        first, last = r.frame_at(1.0), r.frame_at(1.99)
        assert last.shape == (H, W, 3)
        assert not np.array_equal(first, last)                      # the push-in actually moves
    finally:
        r.sources.close()


def test_source_time_past_clip_end_is_clamped(tmp_path):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job)
    plan.shots[1].source.clip_t1 = 5.0
    plan.shots[1].source.speed = 4.0                                 # asks for 4 s of a 1.5 s clip
    r = renderer(job, plan)
    try:
        frame = r.frame_at(1.99)
        assert frame.shape == (H, W, 3)
        assert frame.mean(axis=(0, 1))[2] > 200                      # held the (blue) last frame
    finally:
        r.sources.close()


def test_missing_still_renders_black_with_warning(tmp_path, caplog):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job)
    plan.shots[1].source = ShotSource("still", "", move="push_in")
    r = renderer(job, plan)
    try:
        with caplog.at_level("WARNING", logger="app.cin.renderer"):
            frame = r.frame_at(1.5)
            plan.shots[1].source = ShotSource("still", "sources/images/nope.png", move="push_in")
            gone = r.frame_at(1.6)
    finally:
        r.sources.close()
    assert frame.shape == (H, W, 3) and frame.max() == 0
    assert gone.shape == (H, W, 3) and gone.max() == 0
    assert "black" in caplog.text.lower()


def test_render_writes_30fps_video(tmp_path):
    job = create_job("r", tmp_path)
    out = renderer(job, two_shot_plan(job, transition="whip_pan")).render(tmp_path / "video.mp4")
    info = probe_video(out)
    assert (info["width"], info["height"], info["fps"], info["pixel_format"]) == (W, H, 30.0, "yuv420p")
    assert abs(info["duration"] - 2.0) <= 0.05
    assert info["has_audio"] is False


def test_missing_clip_raises_render_error(tmp_path):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job)
    plan.shots[0].source.path = "sources/clips/missing.mp4"
    with pytest.raises(RenderError):
        renderer(job, plan).render(tmp_path / "video.mp4")


def test_first_frame_failure_closes_readers_and_raises_render_error(tmp_path, monkeypatch):
    job = create_job("r", tmp_path)
    plan = two_shot_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book", color_grade="history", width=W, height=H)

    def boom(frame, grade):
        raise ValueError("grade exploded")
    monkeypatch.setattr("app.video_editor.apply_color_grade", boom)
    with pytest.raises(RenderError):
        r.render(tmp_path / "video.mp4")
    assert r.sources._readers == {}                                  # clip files closed, no leaked handles
