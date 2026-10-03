"""Clip segment planning + shot_plan.json contract (spec §6.4, §6.6)."""
import json

from app.cin.shot_plan import (
    CaptionGroup, CaptionWord, Scene, Segment, Shot, ShotPlan, ShotSource, plan_segments,
)
from tests.conftest import fixture_alignment

HAILUO = (6.0,)
KLING = (5.0, 10.0)


def test_short_scene_snaps_up_to_fixed_model_length():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), HAILUO)
    assert (segs[0].scene, segs[0].t0, segs[0].t1, segs[0].requested_len) == (0, 0.0, 2.32, 6.0)


def test_scene_longer_than_model_max_splits_at_best_gap_near_middle():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), HAILUO)
    scene1 = [s for s in segs if s.scene == 1]
    # 5.68 s + 0.5 s handle > 6 s: split at the comma pause after "car," (5.81 -> 5.96)
    assert [(s.t0, s.t1) for s in scene1] == [(2.32, 5.885), (5.885, 8.0)]
    assert [s.chained for s in scene1] == [False, True]
    assert [s.name for s in scene1] == ["scene01_a", "scene01_b"]
    assert all(s.requested_len == 6.0 for s in scene1)


def test_choice_model_snaps_to_smallest_sufficient_length():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), KLING)
    assert [(s.scene, s.requested_len) for s in segs] == [(0, 5.0), (1, 10.0)]


def test_unlimited_model_requests_exact_length_and_never_splits():
    segs = plan_segments(fixture_alignment("words_gold_8s.json"), None)
    assert [(s.scene, s.requested_len) for s in segs] == [(0, 2.82), (1, 6.18)]


def test_rolex_every_segment_fits_hailuo():
    segs = plan_segments(fixture_alignment("words_rolex_40s.json"), HAILUO)
    assert len(segs) == 11
    assert all(s.t1 - s.t0 + 0.5 <= 6.0 + 1e-6 for s in segs)
    assert segs[0].t0 == 0.0 and segs[-1].t1 == 40.12
    assert all(a.t1 == b.t0 for a, b in zip(segs, segs[1:]))


def _sample_plan() -> ShotPlan:
    return ShotPlan(
        duration=2.21, fps=30, pacing="standard",
        alignment={"method": "whisper+script", "fallback": False, "match_ratio": 0.94},
        scenes=[Scene(0, 0.0, 2.21, "This watch costs more than a car.",
                      [Segment(0.0, 2.21, "sources/clips/scene00_a.mp4", 6.0, "sources/images/scene00.png")])],
        shots=[Shot(0, 0, 0.0, 1.10, ShotSource("clip", "sources/clips/scene00_a.mp4", 0.0, 1.10, 1.0), 1.0, "cut"),
               Shot(1, 0, 1.10, 2.21, ShotSource("still", "sources/images/scene00.png", move="push_in"), 1.18, "cut")],
        captions=[CaptionGroup(0.0, 0.62, [CaptionWord("THIS", 0.0, 0.21)])],
    )


def test_shot_plan_json_matches_contract_keys():
    d = _sample_plan().to_json()
    assert set(d) == {"version", "duration", "fps", "pacing", "alignment", "scenes", "shots",
                      "captions", "sfx", "music", "hook_headline"}
    assert d["version"] == 1 and d["sfx"] == [] and d["music"] is None and d["hook_headline"] is None
    assert set(d["scenes"][0]) == {"index", "t0", "t1", "text", "segments"}
    assert set(d["scenes"][0]["segments"][0]) == {"t0", "t1", "clip", "requested_len", "start_image"}
    assert set(d["shots"][0]) == {"index", "scene", "t0", "t1", "source", "framing", "transition_in"}
    assert set(d["shots"][0]["source"]) == {"type", "path", "clip_t0", "clip_t1", "speed"}
    assert d["shots"][1]["source"] == {"type": "still", "path": "sources/images/scene00.png", "move": "push_in"}
    assert d["captions"][0] == {"t0": 0.0, "t1": 0.62, "words": [{"text": "THIS", "t0": 0.0, "t1": 0.21}]}


def test_shot_plan_roundtrip_through_file(tmp_path):
    plan = _sample_plan()
    path = tmp_path / "shot_plan.json"
    plan.save(path)
    assert "\\" not in path.read_text(encoding="utf-8")       # job-relative posix paths only
    assert ShotPlan.load(path).to_json() == json.loads(path.read_text(encoding="utf-8"))
