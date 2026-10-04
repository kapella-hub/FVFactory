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
    for needle in ('"hook_headline"', '"scene_roles"', "OPEN LOOP", "RE-HOOK", "PAYOFF", "6. ENDING",
                   '"In this video"', '"Have you ever wondered"', '"Did you know"', "\"Let's talk about\""):
        assert needle in prompt, needle
    assert "like a documentary narrator or a TED talk" not in prompt   # the old tone instruction is gone
    assert "sophisticated and knowledgeable" not in prompt


def test_cartoon_style_still_replaces_the_photoreal_image_rules():
    for v2 in (False, True):
        prompt = ScriptGenerator()._build_system_prompt(enable_v2=v2, video_style="cartoon")
        assert "MUST describe a photorealistic scene" not in prompt
        assert "MUST describe a CARTOON style scene" in prompt
        assert 'NEVER use words like "cartoon"' not in prompt


def test_motion_prompts_must_describe_the_subjects_action():
    """User feedback 2026-10-03: camera-drift prompts gave near-static clips. Prompts name what moves."""
    prompt = ScriptGenerator()._build_system_prompt(enable_v2=True)
    bullet = prompt[prompt.index('- "motion_prompts"'):prompt.index('- "pacing_hints"')]
    assert "visible physical action" in bullet and "what moves and how" in bullet
    assert "ONE camera move" in bullet
    assert "NEVER" in bullet and "static" in bullet and "parallax" in bullet
    assert "rust flakes crumble off the chain as it swings" in bullet
    for old in ("static shot with subtle parallax", "how the camera moves", "slow zoom in on the subject",
                "One camera/motion description"):
        assert old not in prompt, old


def test_generic_motion_prompt_is_action_first():
    from app.content_engine import GENERIC_MOTION_PROMPT
    assert GENERIC_MOTION_PROMPT.startswith("the main subject moves")
    for word in ("subtle", "slight", "slow", "drift", "parallax"):
        assert word not in GENERIC_MOTION_PROMPT, word


def test_duration_guide_matches_word_budget():
    from app.script_quality import word_budget
    for preset in ("short", "medium", "long"):
        b = word_budget(preset)
        guide = ScriptGenerator.DURATION_GUIDE[preset]
        assert f"{b.target} words" in guide and f"{b.lo} to {b.hi}" in guide
        assert f"{b.scenes[0]}-{b.scenes[1]} scenes" in guide



def test_mascot_never_added_to_photoreal_prompts(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "mascot_prompt", "A cute robot")
    gen = ScriptGenerator()
    assert "A cute robot" not in gen._build_system_prompt(video_style="photorealistic", mascot=True)
    assert "A cute robot" in gen._build_system_prompt(video_style="cartoon", mascot=True)


# ------------------------------------------------------------------ mascot is a per-video choice

ROBOT = "A cute robot with glowing blue eyes"


def _mascot_settings(monkeypatch, enabled=True):
    from app.config import settings
    monkeypatch.setattr(settings, "mascot_enabled", enabled)   # the global must no longer be read here
    monkeypatch.setattr(settings, "mascot_prompt", ROBOT)


def test_anime_prompt_has_no_mascot_when_the_run_says_no(monkeypatch):
    _mascot_settings(monkeypatch, enabled=True)
    for v2 in (False, True):
        prompt = ScriptGenerator()._build_system_prompt(enable_v2=v2, video_style="anime", mascot=False)
        assert ROBOT not in prompt and "COMPANION" not in prompt
    assert ROBOT not in ScriptGenerator()._build_system_prompt(video_style="anime")    # default: off


def test_anime_prompt_gets_the_softened_companion_when_asked(monkeypatch):
    _mascot_settings(monkeypatch, enabled=False)
    prompt = ScriptGenerator()._build_system_prompt(enable_v2=True, video_style="anime", mascot=True)
    assert ROBOT in prompt and "companion" in prompt.lower()
    assert "MAIN SUBJECT" in prompt and "Never replace" in prompt
    for old in ("MUST prominently feature", "main focus of each image", "vector"):
        assert old not in prompt


def _capture_llm(monkeypatch):
    systems = []

    def fake(prompt, system=None, **kwargs):
        systems.append(system)
        n = prompt.count('\n "') or 9
        return {"hook": "Baba Yaga lives in a hut that walks.", "body": " ".join(["forest"] * 90),
                "title": "Baba Yaga", "hook_headline": "THE WALKING HUT",
                "image_prompts": [f"img {i}" for i in range(n)], "motion_prompts": ["trees sway"] * n,
                "keywords": ["folklore"], "scene_roles": []}
    monkeypatch.setattr("app.content_engine.generate_json", fake)
    return systems


def test_topic_write_script_threads_mascot_to_draft_and_revision(monkeypatch):
    _mascot_settings(monkeypatch, enabled=False)
    systems = _capture_llm(monkeypatch)
    ScriptGenerator().write_script("baba yaga", video_style="anime", video_duration="short", mascot=True)
    assert len(systems) == 2                                   # draft + length revision (90+ words for short)
    assert all(ROBOT in s for s in systems)
    systems.clear()
    ScriptGenerator().write_script("baba yaga", video_style="anime", video_duration="short", mascot=False)
    assert systems and not any(ROBOT in s for s in systems)


def test_story_never_gets_the_mascot(monkeypatch):
    _mascot_settings(monkeypatch, enabled=True)
    systems = _capture_llm(monkeypatch)
    story = "Baba Yaga lives deep in the forest. Her hut stands on chicken legs. It turns to face visitors."
    gen = ScriptGenerator()
    gen.write_story_script(story, mode="verbatim", video_style="anime")
    gen.write_story_script(story, mode="adapt", video_style="anime")
    assert len(systems) >= 2 and not any(ROBOT in s for s in systems)
    systems.clear()
    gen.generate_script("Baba Yaga", video_style="anime", story=story, mascot=True)   # belt and braces
    assert systems and ROBOT not in systems[0]
