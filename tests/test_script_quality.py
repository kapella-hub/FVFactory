"""Word budget and scene roles (spec 2026-10-03 §5, §7)."""
import pytest

from app.script_quality import (
    SCENE_ROLES, canonical_role, check_roles, count_words, derived_roles, word_budget,
)


@pytest.mark.parametrize("preset, seconds, target, lo, hi, scenes", [
    ("short", 30, 78, 67, 89, (6, 8)),
    ("medium", 45, 117, 100, 134, (9, 11)),
    ("long", 60, 156, 133, 179, (11, 14)),
])
def test_word_budget_table(preset, seconds, target, lo, hi, scenes):
    b = word_budget(preset)
    assert (b.preset, b.seconds, b.target, b.lo, b.hi, b.scenes) == (preset, seconds, target, lo, hi, scenes)
    assert b.contains(lo) and b.contains(hi) and not b.contains(lo - 1) and not b.contains(hi + 1)


@pytest.mark.parametrize("value", ["", None, "epic", "MEDIUM"])
def test_unknown_or_empty_preset_uses_medium(value):
    assert word_budget(value).preset == "medium"


def test_count_words_ignores_punctuation_only_tokens():
    assert count_words("This watch costs more than a car — and nobody notices.") == 10
    assert count_words("It cost $1,000,000 in 1969.") == 5
    assert count_words("") == 0 and count_words(None) == 0


@pytest.mark.parametrize("raw, expected", [
    ("hook", "hook"), ("Re-hook", "rehook"), ("re hook", "rehook"), ("REHOOK", "rehook"),
    ("Open loop", "open_loop"), ("open-loop", "open_loop"), ("loop ending", "loop"),
    (" payoff ", "payoff"), ("climax", None), ("", None), (None, None), (3, None),
])
def test_canonical_role(raw, expected):
    assert canonical_role(raw) == expected


def test_derived_roles_shapes():
    assert derived_roles(0) == []
    assert derived_roles(1) == ["hook"]
    assert derived_roles(2) == ["hook", "loop"]
    assert derived_roles(5) == ["hook", "body", "body", "body", "loop"]


def test_valid_roles_are_canonicalized_without_a_reason():
    roles, reason = check_roles(["Hook", "open loop", "body", "Re-hook", "payoff", "loop"], 6)
    assert roles == ["hook", "open_loop", "body", "rehook", "payoff", "loop"]
    assert reason is None
    assert set(roles) <= set(SCENE_ROLES)


@pytest.mark.parametrize("roles, n, reason_part", [
    ([], 4, "missing"),
    (["body", "hook", "payoff", "loop"], 4, "not 'hook'"),
    (["hook", "climax", "payoff", "loop"], 4, "unknown roles"),
    (["hook", "payoff", "loop"], 4, "expected 4 roles"),
])
def test_invalid_roles_are_derived_with_a_reason(roles, n, reason_part):
    out, reason = check_roles(roles, n)
    assert out == derived_roles(n)
    assert reason_part in reason
