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
    assert "hook_viral_score" not in prompt          # spec 2026-10-03 §4.6: no longer requested


def test_v1_system_prompt_no_motion():
    gen = ScriptGenerator.__new__(ScriptGenerator)
    gen.client = MagicMock()
    gen.model = "gpt-4o"

    prompt = gen._build_system_prompt(enable_v2=False)
    assert "motion_prompts" not in prompt


def test_script_output_retention_fields_default_empty():
    script = ScriptOutput(hook="h", body="b", image_prompts=["p"] * 5, keywords=["k"])
    assert script.hook_headline == "" and script.scene_roles == []


def test_system_prompt_asks_for_retention_structure_and_new_fields():
    prompt = ScriptGenerator()._build_system_prompt(enable_v2=False)
    for needle in ('"hook_headline"', '"scene_roles"', "OPEN LOOP", "RE-HOOK", "PAYOFF", "LOOP ENDING",
                   '"In this video"', '"Have you ever wondered"', '"Did you know"', "\"Let's talk about\""):
        assert needle in prompt, needle
    assert "like a documentary narrator or a TED talk" not in prompt   # the old tone instruction is gone
    assert "sophisticated and knowledgeable" not in prompt


def test_cartoon_style_still_replaces_the_photoreal_image_rules():
    prompt = ScriptGenerator()._build_system_prompt(video_style="cartoon")
    assert "MUST describe a photorealistic scene" not in prompt
    assert "MUST describe a CARTOON style scene" in prompt
    assert 'NEVER use words like "cartoon"' not in prompt


def test_duration_guide_matches_word_budget():
    from app.script_quality import word_budget
    for preset in ("short", "medium", "long"):
        b = word_budget(preset)
        guide = ScriptGenerator.DURATION_GUIDE[preset]
        assert f"{b.target} words" in guide and f"{b.lo} to {b.hi}" in guide
        assert f"{b.scenes[0]}-{b.scenes[1]} scenes" in guide



def test_mascot_never_added_to_photoreal_prompts(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "mascot_enabled", True)
    monkeypatch.setattr(settings, "mascot_prompt", "A cute robot, vector art style")
    gen = ScriptGenerator()
    assert "MASCOT" not in gen._build_system_prompt(video_style="photorealistic")
    assert "A cute robot" in gen._build_system_prompt(video_style="cartoon")
