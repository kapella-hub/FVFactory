import json
from unittest.mock import patch, MagicMock
from app.content_engine import ScriptOutput, ScriptGenerator


def test_script_output_backward_compatible():
    script = ScriptOutput(
        hook="Did you know?",
        body="Some body text here.",
        image_prompts=["p1", "p2", "p3", "p4", "p5"],
        keywords=["test"],
    )
    assert script.hook == "Did you know?"
    assert script.motion_prompts == []
    assert script.pacing_hints == []
    assert script.hook_variants == []
    assert script.hook_viral_score == 0
    assert script.emoji_subtitles == []


def test_script_output_v2_fields():
    script = ScriptOutput(
        hook="Did you know?",
        hook_variants=["Alt 1", "Alt 2", "Alt 3"],
        hook_viral_score=8,
        body="Some body text here.",
        image_prompts=["p1", "p2", "p3", "p4", "p5"],
        motion_prompts=["zoom in", "pan left", "tilt up", "zoom out", "static"],
        pacing_hints=["fast", "normal", "slow", "dramatic_pause", "normal"],
        keywords=["test"],
        emoji_subtitles=["Did you know? 🤔", "Mind blown 🤯"],
    )
    assert len(script.motion_prompts) == 5
    assert len(script.pacing_hints) == 5
    assert script.hook_viral_score == 8


def test_v2_system_prompt_includes_motion():
    gen = ScriptGenerator.__new__(ScriptGenerator)
    gen.client = MagicMock()
    gen.model = "gpt-4o"

    prompt = gen._build_system_prompt(enable_v2=True)
    assert "motion_prompts" in prompt
    assert "pacing_hints" in prompt
    assert "hook_variants" in prompt
    assert "hook_viral_score" in prompt


def test_v1_system_prompt_no_motion():
    gen = ScriptGenerator.__new__(ScriptGenerator)
    gen.client = MagicMock()
    gen.model = "gpt-4o"

    prompt = gen._build_system_prompt(enable_v2=False)
    assert "motion_prompts" not in prompt
