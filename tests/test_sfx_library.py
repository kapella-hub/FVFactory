"""SFX classification and placement from the shot plan (spec §8.2)."""
from pathlib import Path

from app.cin.sfx_library import SfxFile, place_sfx, scan_sfx, sfx_kind
from app.cin.shot_plan import ClipSpec, Scene, Shot, ShotPlan, ShotSource, build_shot_plan, plan_segments
from tests.conftest import fixture_alignment


def touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x")
    return p


def sf(name, kind, dur):
    return SfxFile(Path(f"assets/sfx/generated/{name}"), kind, dur)


POOL = {"whoosh": [sf("whoosh_1.mp3", "whoosh", 1.0), sf("whoosh_2.mp3", "whoosh", 1.0)],
        "impact": [sf("impact_1.mp3", "impact", 1.5)],
        "riser": [sf("riser_1.mp3", "riser", 2.5)]}


def plan3(duration=8.0):
    """3 scenes; scene 1 has an intra-scene cut at 3.5; styled transitions at 2.0 and 5.0."""
    scenes = [Scene(0, 0.0, 2.0, "a"), Scene(1, 2.0, 5.0, "b"), Scene(2, 5.0, duration, "c")]
    src = ShotSource("still", "sources/images/scene00.png")
    shots = [Shot(0, 0, 0.0, 2.0, src), Shot(1, 1, 2.0, 3.5, src, transition_in="flash"),
             Shot(2, 1, 3.5, 5.0, src), Shot(3, 2, 5.0, duration, src, transition_in="whip_pan")]
    return ShotPlan(duration, 30, "standard", {}, scenes, shots, [])


def test_sfx_kind_by_prefix():
    assert sfx_kind("whoosh.mp3") == "whoosh"          # legacy SFXMixer name
    assert sfx_kind("Impact Big.WAV") == "impact"
    assert sfx_kind("riser_2.mp3") == "riser"
    assert sfx_kind("music.mp3") is None


def test_scan_user_and_generated(tmp_path):
    w = touch(tmp_path / "whoosh.mp3")
    g = touch(tmp_path / "generated" / "whoosh_1.mp3")
    i = touch(tmp_path / "Impact Big.WAV")
    touch(tmp_path / "music.mp3")
    touch(tmp_path / "generated" / "riser_1.mp3.part")
    pool = scan_sfx(tmp_path)
    assert pool["whoosh"] == sorted([w, g], key=lambda p: p.as_posix())
    assert pool["impact"] == [i] and pool["riser"] == []
    assert scan_sfx(tmp_path / "missing") == {"whoosh": [], "impact": [], "riser": []}


def test_place_sfx_rules():
    ev = place_sfx(plan3(), POOL)
    assert [(e["t"], e["kind"], e["file"]) for e in ev] == [
        (0.0, "impact", "assets/sfx/generated/impact_1.mp3"),
        (0.0, "riser", "assets/sfx/generated/riser_1.mp3"),     # 2.5 s riser ending at 2.0
        (1.85, "whoosh", "assets/sfx/generated/whoosh_1.mp3"),  # 0.15 s before scene 1
        (2.5, "riser", "assets/sfx/generated/riser_1.mp3"),     # ends at the 5.0 transition
        (4.85, "whoosh", "assets/sfx/generated/whoosh_2.mp3"),  # variants rotate
    ]
    assert {e["kind"]: e["gain_db"] for e in ev} == {"impact": -6.0, "riser": -12.0, "whoosh": -10.0}


def test_riser_before_zero_gets_offset():
    ev = [e for e in place_sfx(plan3(), POOL) if e["kind"] == "riser"]
    assert ev[0]["t"] == 0.0 and ev[0]["offset"] == 0.5
    assert "offset" not in ev[1]


def test_intra_scene_cuts_get_no_whoosh():
    ev = place_sfx(plan3(), POOL)
    assert sorted(e["t"] for e in ev if e["kind"] == "whoosh") == [1.85, 4.85]   # not 3.35


def test_missing_kinds_and_empty_pool():
    assert place_sfx(plan3(), {}) == []
    only_whoosh = place_sfx(plan3(), {"whoosh": POOL["whoosh"]})
    assert {e["kind"] for e in only_whoosh} == {"whoosh"}


def test_events_at_or_after_duration_are_dropped():
    plan = plan3(duration=5.0)
    plan.scenes[2] = Scene(2, 5.2, 5.2, "c")
    plan.shots[3] = Shot(3, 2, 5.2, 5.2, plan.shots[3].source, transition_in="whip_pan")
    ev = place_sfx(plan, POOL)
    assert all(e["t"] < 5.0 for e in ev)
    # scene 2's whoosh would land at 5.05 (>= duration) and must be dropped; scene 1's survives
    assert [e["t"] for e in ev if e["kind"] == "whoosh"] == [1.85]


def test_gold_plan_whoosh_per_scene_boundary():
    alignment = fixture_alignment("words_gold_8s.json")
    specs = [ClipSpec(s.scene, s.index, s.t0, s.t1, s.requested_len, f"sources/images/scene{s.scene:02d}.png")
             for s in plan_segments(alignment, None)]
    plan = build_shot_plan(alignment, "fast", specs)
    ev = place_sfx(plan, POOL)
    assert sum(e["kind"] == "whoosh" for e in ev) == len(plan.scenes) - 1
    assert sum(e["kind"] == "riser" for e in ev) == sum(s.transition_in != "cut" for s in plan.shots)
