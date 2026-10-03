"""Captions + hook headline inside the shot renderer and render_job (spec §7, §12)."""
import subprocess

import numpy as np
import pytest
from PIL import Image

from app.cin.captions import CaptionLayer, build_caption_layer
from app.cin.editor import RenderOptions, rebuild_plan, render_job
from app.cin.job import create_job
from app.cin.renderer import ShotRenderer
from app.cin.report import RunReport
from app.cin.shot_plan import Scene, Segment, Shot, ShotPlan, ShotSource, build_shot_plan, group_captions
from app.subtitle_styles import SUBTITLE_PRESETS
from tests.conftest import build_gold_job, ffmpeg_exe, fixture_alignment, make_color_clip, make_silence, make_test_clip

HEADLINE = {"text": "Gold is heavier than you think", "t0": 0.0, "t1": 2.5}


def ink(frame, threshold=0):
    ys, xs = np.nonzero(frame.max(axis=2) > threshold)
    if len(ys) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def black_still_plan(job, duration=8.0):
    """One full-length still shot of a black image, gold captions, the hook headline."""
    job.image(0).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1920), (0, 0, 0)).save(job.image(0))
    alignment = fixture_alignment("words_gold_8s.json")
    return ShotPlan(
        duration=duration, fps=30, pacing="standard", alignment={},
        scenes=[Scene(0, 0.0, duration, "gold", [Segment(0.0, duration, None, 6.0, job.rel(job.image(0)))])],
        shots=[Shot(0, 0, 0.0, duration, ShotSource("still", job.rel(job.image(0)), move="push_in"), 1.0)],
        captions=group_captions(alignment.tokens), hook_headline=dict(HEADLINE))


def test_frame_at_composites_captions_and_headline(tmp_path):
    job = create_job("cap", tmp_path)
    plan = black_still_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book", captions=build_caption_layer(plan, "fire"))
    try:
        first = r.frame_at(0.0)
        top, bottom = first[:1000], first[1000:]
        assert ink(top) is not None and ink(bottom) is not None          # headline + caption from frame one
        x0, y0, x1, y1 = ink(top)
        assert 250 <= y0 and y1 <= 450 and x1 <= 990
        later = r.frame_at(4.0)
        assert ink(later[:1000]) is None                                  # headline gone after 2.5 s
        bx0, by0, bx1, by1 = ink(later)
        assert 1250 <= by0 and by1 <= 1410 and bx1 <= 990
    finally:
        r.sources.close()


def test_captions_do_not_burn_into_cached_source_frames(tmp_path):
    """frame 0 of an unzoomed still IS the cached array; compositing into it would stamp every frame."""
    job = create_job("cap", tmp_path)
    plan = black_still_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book", captions=build_caption_layer(plan, "bold_impact"))
    try:
        r.frame_at(0.0)
        assert r.sources.still(job.rel(job.image(0))).max() == 0          # cached black still untouched
    finally:
        r.sources.close()


def test_subtitles_off_keeps_headline_only(tmp_path):
    job = create_job("cap", tmp_path)
    plan = black_still_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book",
                     captions=build_caption_layer(plan, "fire", enable_subtitles=False))
    try:
        assert ink(r.frame_at(1.0)[1000:]) is None
        assert ink(r.frame_at(1.0)[:1000]) is not None
    finally:
        r.sources.close()


def test_rebuild_plan_keeps_hook_headline(tmp_path):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, "standard", specs)
    plan.hook_headline = dict(HEADLINE)
    plan.save(job.shot_plan)
    assert rebuild_plan(job, "fast").hook_headline == HEADLINE


class _CaptureRenderer:
    """Stands in for ShotRenderer inside render_job: records kwargs, writes a tiny clip."""
    seen: dict = {}

    def __init__(self, plan, job, **kwargs):
        self.plan = plan
        _CaptureRenderer.seen = kwargs

    def render(self, out_path):
        return make_test_clip(out_path, self.plan.duration)


def _render_with_capture(tmp_path, monkeypatch, **opts):
    job, alignment, specs = build_gold_job(tmp_path)
    make_silence(job.narration, 8.0)
    monkeypatch.setattr("app.cin.editor.ShotRenderer", _CaptureRenderer)
    plan = build_shot_plan(alignment, "standard", specs)
    report = RunReport(job=job.name)
    render_job(job, plan, RenderOptions(enable_music=False, enable_sfx=False, **opts), report)
    return plan, report, _CaptureRenderer.seen


def test_render_job_hands_caption_layer_to_renderer(tmp_path, monkeypatch):
    plan, report, seen = _render_with_capture(tmp_path, monkeypatch, subtitle_style="fire")
    assert isinstance(seen["captions"], CaptionLayer)
    assert len(seen["captions"].groups) == len(plan.captions)
    assert "font_fallback" not in [w["code"] for w in report.warnings]


def test_render_job_without_subtitles_or_headline_passes_no_layer(tmp_path, monkeypatch):
    _, _, seen = _render_with_capture(tmp_path, monkeypatch, enable_subtitles=False)
    assert seen["captions"] is None


def test_render_job_reports_missing_caption_font(tmp_path, monkeypatch):
    monkeypatch.setitem(SUBTITLE_PRESETS["fire"], "font_file", "Gone.ttf")
    _, report, seen = _render_with_capture(tmp_path, monkeypatch, subtitle_style="fire")
    assert [w["code"] for w in report.warnings].count("font_fallback") == 1
    assert seen["captions"] is not None                               # still renders, with a system font


def test_cached_still_unchanged_across_caption_states(tmp_path):
    """Two frames of the same still shot at different caption states: cache untouched, frames differ."""
    job = create_job("cap", tmp_path)
    plan = black_still_plan(job)
    r = ShotRenderer(plan, job, video_style="comic_book", captions=build_caption_layer(plan, "bold_impact"))
    try:
        a = r.frame_at(0.5).copy()
        b = r.frame_at(5.0).copy()
        assert r.sources.still(job.rel(job.image(0))).max() == 0
        assert not np.array_equal(a, b)
        assert np.array_equal(r.frame_at(0.5), a)         # deterministic, nothing leaked between frames
    finally:
        r.sources.close()


def _frame(path, t):
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(1920, 1080, 3)


@pytest.mark.render
@pytest.mark.parametrize("style", ["bold_impact", "fire"])
def test_render_job_caption_pixels_stay_in_safe_zone(tmp_path, style):
    """Black clips, no particles: every bright pixel in the decoded final.mp4 is caption or headline."""
    job, alignment, specs = build_gold_job(tmp_path)
    for spec in specs:
        make_color_clip(job.resolve(spec.path), spec.requested_len, "black", size="360x640")
    plan = build_shot_plan(alignment, "standard", specs)
    plan.hook_headline = dict(HEADLINE)
    report = RunReport(job=job.name)
    final = render_job(job, plan, RenderOptions(subtitle_style=style, video_style="comic_book",
                                                enable_music=False, enable_sfx=False), report)
    assert "font_fallback" not in [w["code"] for w in report.warnings]
    peak_times = [g.words[-1].t0 + 0.09 for g in plan.captions]           # widest state of every group
    for t in [0.0, 1.0] + peak_times:
        f = _frame(final, t)
        top, bottom = ink(f[:1000], 40), ink(f[1000:], 40)
        assert bottom is not None, t
        x0, y0, x1, y1 = bottom
        assert 1250 <= y0 + 1000 and y1 + 1000 <= 1410 and x1 <= 990, (style, t, bottom)
        if t < 2.4:
            assert top is not None and 250 <= top[1] and top[3] <= 450, (style, t, top)
        elif t > 2.6:
            assert top is None, (style, t, top)
