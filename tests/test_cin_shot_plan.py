"""Shot planner: pacing, cut placement, framing, speed rule, stills, transitions (spec §6)."""
import pytest

from app.cin.align import align_words
from app.cin.shot_plan import (
    FRAMINGS, PACING, ClipSpec, build_shot_plan, plan_segments, word_gaps,
)
from tests.conftest import fixture_alignment

HAILUO = (6.0,)
KLING = (5.0, 10.0)


def specs_for(segs, length=lambda s: s.requested_len, path=True, failed=False):
    return [ClipSpec(s.scene, s.index, s.t0, s.t1, s.requested_len, f"sources/images/scene{s.scene:02d}.png",
                     path=f"sources/clips/{s.name}.mp4" if path else None,
                     duration=length(s) if path else 0.0,
                     last_frame=f"sources/clips/{s.name}_last.png" if path else None,
                     failed=failed)
            for s in segs]


def rolex_plan(pacing):
    a = fixture_alignment("words_rolex_40s.json")
    segs = plan_segments(a, HAILUO)
    return a, segs, build_shot_plan(a, pacing, specs_for(segs))


def assert_contiguous(plan):
    assert plan.shots[0].t0 == 0.0
    assert plan.shots[-1].t1 == plan.duration
    assert all(a.t1 == b.t0 for a, b in zip(plan.shots, plan.shots[1:]))
    assert all(s.t1 > s.t0 for s in plan.shots)


@pytest.mark.parametrize("pacing", sorted(PACING))
def test_shots_respect_pacing_bounds(pacing):
    a, segs, plan = rolex_plan(pacing)
    target, lo, hi = PACING[pacing]
    assert_contiguous(plan)
    seg_bounds = {(s.t0, s.t1) for s in segs}
    for shot in plan.shots:
        length = shot.t1 - shot.t0
        whole_segment = (shot.t0, shot.t1) in seg_bounds
        assert whole_segment or lo * 0.8 - 1e-6 <= length <= hi * 1.25 + 1e-6, (pacing, shot)


def test_faster_pacing_means_more_shots():
    counts = {p: len(rolex_plan(p)[2].shots) for p in PACING}
    assert counts["calm"] < counts["standard"] < counts["fast"]


def test_cuts_land_on_word_gaps_or_segment_boundaries():
    a, segs, plan = rolex_plan("fast")
    allowed = {g.t for g in word_gaps(a)} | {s.t0 for s in segs} | {40.12}
    assert all(s.t0 in allowed for s in plan.shots)


def test_long_segment_with_awkward_gaps_is_still_cut():
    # gold scene 1 is 5.68 s; strict fast bounds [1.8, 2.5] admit no cut set, relaxed bounds do
    a = fixture_alignment("words_gold_8s.json")
    plan = build_shot_plan(a, "fast", specs_for(plan_segments(a, KLING)))
    assert [(s.t0, s.t1) for s in plan.shots] == [(0.0, 2.32), (2.32, 4.245), (4.245, 5.885), (5.885, 8.0)]


def test_adjacent_shots_from_same_source_never_share_framing():
    for pacing in PACING:
        _, _, plan = rolex_plan(pacing)
        for x, y in zip(plan.shots, plan.shots[1:]):
            if x.source.path == y.source.path:
                assert x.framing != y.framing
        assert {s.framing for s in plan.shots} <= set(FRAMINGS)


def test_shot_plays_its_segment_clip_window():
    a = fixture_alignment("words_gold_8s.json")
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, HAILUO)))
    last = plan.shots[-1]
    assert last.source.path == "sources/clips/scene01_b.mp4"
    assert last.source.clip_t0 == pytest.approx(0.0)
    assert last.source.clip_t1 == pytest.approx(8.0 - 5.885)


def test_footage_short_by_at_most_15_percent_is_slowed():
    a = fixture_alignment("words_gold_8s.json")
    segs = plan_segments(a, KLING)
    plan = build_shot_plan(a, "standard", specs_for(segs, length=lambda s: (s.t1 - s.t0) * 0.9))
    assert all(s.source.speed == pytest.approx(0.9) for s in plan.shots)
    assert plan.shots[-1].source.clip_t1 == pytest.approx((8.0 - 2.32) * 0.9)
    assert [w["code"] for w in plan.warnings] == ["speed_adjusted", "speed_adjusted"]


def test_footage_short_by_more_than_15_percent_gets_a_still_tail():
    a = fixture_alignment("words_gold_8s.json")
    segs = plan_segments(a, KLING)
    plan = build_shot_plan(a, "standard", specs_for(segs, length=lambda s: (s.t1 - s.t0) * 0.5))
    assert_contiguous(plan)
    assert [(s.t0, s.t1, s.source.type) for s in plan.shots] == [
        (0.0, 1.16, "clip"), (1.16, 2.32, "still"), (2.32, 5.195, "clip"), (5.195, 8.0, "still")]
    assert plan.shots[1].source.path == "sources/clips/scene00_a_last.png"
    assert [w["code"] for w in plan.warnings] == ["still_fallback", "still_fallback"]


def test_failed_clips_become_push_in_stills_with_warnings():
    a = fixture_alignment("words_gold_8s.json")
    segs = plan_segments(a, HAILUO)
    plan = build_shot_plan(a, "standard", specs_for(segs, path=False, failed=True))
    assert all(s.source.type == "still" and s.source.move == "push_in" for s in plan.shots)
    assert {s.source.path for s in plan.shots} == {"sources/images/scene00.png", "sources/images/scene01.png"}
    assert [w["code"] for w in plan.warnings] == ["still_fallback"] * len(segs)


def test_motion_disabled_stills_are_not_reported_as_failures():
    a = fixture_alignment("words_gold_8s.json")
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None), path=False))
    assert all(s.source.type == "still" for s in plan.shots)
    assert plan.warnings == []


def _synthetic(pauses):
    """len(pauses)+1 one-sentence scenes; the pause before scene k is pauses[k-1]."""
    words, t, texts = [], 0.0, []
    for k in range(len(pauses) + 1):
        sentence = [f"w{k}a", f"w{k}b", f"w{k}c", f"w{k}d."]
        texts.append(" ".join(sentence))
        for i, w in enumerate(sentence):
            words.append({"word": " " + w, "start": round(t, 3), "end": round(t + 0.5, 3)})
            t += 0.55
        if k < len(pauses):
            t += pauses[k]
    narration = " ".join(texts)
    return align_words(words, texts, narration, round(t + 0.3, 3))


def test_transitions_go_to_longest_pauses_max_three():
    a = _synthetic([0.9, 0.2, 0.6, 0.4])
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)))
    styled = [(s.scene, s.transition_in) for s in plan.shots if s.transition_in != "cut"]
    assert styled == [(1, "flash"), (3, "zoom_through"), (4, "whip_pan")]   # 0.2 s pause loses
    assert plan.shots[0].transition_in == "cut"
    assert all(s.t0 == plan.scenes[s.scene].t0 for s in plan.shots if s.transition_in != "cut")


def test_very_short_narration_is_one_shot():
    a = align_words([{"word": " Hi", "start": 0.1, "end": 0.4}, {"word": " there.", "start": 0.45, "end": 0.9}],
                    ["Hi there."], "Hi there.", 1.2)
    plan = build_shot_plan(a, "fast", specs_for(plan_segments(a, HAILUO)))
    assert [(s.t0, s.t1) for s in plan.shots] == [(0.0, 1.2)]


def test_scene_shorter_than_min_is_one_shot():
    a = _synthetic([0.1, 0.1, 0.1])        # 2.25 s scenes
    plan = build_shot_plan(a, "calm", specs_for(plan_segments(a, None)))
    assert len(plan.shots) == len(plan.scenes)


def test_captions_use_script_spelling_in_groups_of_three():
    _, _, plan = rolex_plan("standard")
    words = [w.text for g in plan.captions for w in g.words]
    assert "Wilsdorf" in words and "Wils" not in words
    assert all(1 <= len(g.words) <= 3 for g in plan.captions)
    assert [w.text for w in plan.captions[0].words] == ["This", "watch", "costs"]


def test_unknown_pacing_rejected():
    a = fixture_alignment("words_gold_8s.json")
    with pytest.raises(ValueError):
        build_shot_plan(a, "hyper", specs_for(plan_segments(a, None)))
