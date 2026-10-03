"""Prompt-count normalization after the LLM call, before paid generation (spec §10)."""
from app.content_engine import GENERIC_MOTION_PROMPT, ScriptOutput, normalize_prompt_counts


def make(images=6, motion=6, scenes=6, hints=0):
    return ScriptOutput(
        hook="Hook.", body="Body.", keywords=["k"],
        image_prompts=[f"img {i}" for i in range(images)],
        motion_prompts=[f"move {i}" for i in range(motion)],
        scene_texts=[f"Scene {i}." for i in range(scenes)],
        pacing_hints=["fast"] * hints,
    )


def test_equal_counts_unchanged():
    script = make()
    out, change = normalize_prompt_counts(script)
    assert out is script
    assert change is None


def test_missing_motion_prompts_padded_with_generic_move():
    out, change = normalize_prompt_counts(make(motion=4))
    assert len(out.motion_prompts) == 6
    assert out.motion_prompts[4:] == [GENERIC_MOTION_PROMPT, GENERIC_MOTION_PROMPT]
    assert change["before"]["motion_prompts"] == 4 and change["after"]["motion_prompts"] == 6


def test_extra_motion_prompts_truncated():
    out, _ = normalize_prompt_counts(make(motion=8))
    assert out.motion_prompts == [f"move {i}" for i in range(6)]


def test_fewer_scene_texts_truncate_image_prompts_below_validator_minimum():
    out, change = normalize_prompt_counts(make(scenes=4))       # 4 < ScriptOutput's min of 5
    assert out.image_prompts == ["img 0", "img 1", "img 2", "img 3"]
    assert len(out.motion_prompts) == 4
    assert change["after"]["image_prompts"] == 4


def test_extra_scene_texts_merge_into_last_scene():
    script = make(scenes=8)
    out, _ = normalize_prompt_counts(script)
    assert len(out.scene_texts) == 6
    assert out.scene_texts[-1] == "Scene 5. Scene 6. Scene 7."
    assert " ".join(out.scene_texts) == " ".join(script.scene_texts)   # narration preserved


def test_missing_scene_texts_keep_image_count():
    out, _ = normalize_prompt_counts(make(scenes=0))
    assert len(out.image_prompts) == 6 and out.scene_texts == []


def test_empty_motion_prompts_all_generic():
    out, change = normalize_prompt_counts(make(motion=0))
    assert out.motion_prompts == [GENERIC_MOTION_PROMPT] * 6
    assert change is not None


def test_pacing_hints_padded_only_when_present():
    assert normalize_prompt_counts(make(hints=3))[0].pacing_hints == ["fast"] * 3 + ["normal"] * 3
    assert normalize_prompt_counts(make(hints=0))[0].pacing_hints == []
