"""ScriptGenerator.write_script: word-budget gate, one revision call, scene roles (spec 2026-10-03 §7).
The LLM is a fake: zero network, zero subprocesses."""
import pytest

from app.content_engine import ScriptGenerator, ScriptGeneratorError

ROLES8 = ["hook", "open_loop", "body", "body", "rehook", "body", "payoff", "loop"]
HOOK = "This watch costs more than your house."        # 7 words


def script_data(words, scenes=8, roles=ROLES8, headline="$2M FOR A WATCH?"):
    return {"hook": HOOK, "body": " ".join(["tick"] * (words - 7)),
            "image_prompts": [f"close-up of a watch part {i}" for i in range(scenes)],
            "motion_prompts": ["slow push-in"] * scenes,
            "keywords": ["watches"], "hook_headline": headline, "scene_roles": list(roles)}


class FakeLLM:
    """generate_json stand-in: returns queued responses in order and records every prompt."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def __call__(self, prompt, system=None, temperature=0.7, max_tokens=1500):
        self.prompts.append(prompt)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def llm(monkeypatch):
    def install(*responses):
        fake = FakeLLM(*responses)
        monkeypatch.setattr("app.content_engine.generate_json", fake)
        return fake
    return install


def codes(result):
    return [w["code"] for w in result.warnings]


def test_on_target_draft_needs_one_call_and_no_warnings(llm):
    fake = llm(script_data(117))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert len(fake.prompts) == 1
    assert "117 words" in fake.prompts[0] and "100 to 134" in fake.prompts[0]
    assert result.warnings == []
    assert result.length == {"preset": "medium", "target_seconds": 45, "target_words": 117,
                             "word_range": [100, 134], "draft_words": 117, "words": 117,
                             "revision": "not_needed"}
    assert result.script.scene_roles == ROLES8 and result.script.hook_headline == "$2M FOR A WATCH?"


def test_too_long_draft_is_revised_once_with_explicit_feedback(llm):
    fake = llm(script_data(200), script_data(120))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert len(fake.prompts) == 2
    revise = fake.prompts[1]
    assert "is 200 words" in revise and "Rewrite it to 117 words" in revise and "100 to 134" in revise
    assert "Cut filler" in revise and '"hook_headline"' in revise          # current script JSON included
    assert result.length["draft_words"] == 200 and result.length["words"] == 120
    assert result.length["revision"] == "accepted"
    assert "script_length_off_target" not in codes(result)


def test_too_short_draft_asks_for_specifics_not_filler(llm):
    fake = llm(script_data(40), script_data(110))
    ScriptGenerator().write_script("watches", video_duration="medium")
    assert "is 40 words" in fake.prompts[1] and "Add concrete specifics" in fake.prompts[1]


def test_still_off_target_after_revision_warns_and_proceeds(llm):
    llm(script_data(200), script_data(150))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.length["words"] == 150 and result.length["revision"] == "accepted"
    [w] = [w for w in result.warnings if w["code"] == "script_length_off_target"]
    assert w["detail"] == {"words": 150, "target": 117, "range": [100, 134], "revision": "accepted"}


def test_revision_further_from_target_keeps_the_draft(llm):
    llm(script_data(150), script_data(230))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.length["words"] == 150 and result.length["revision"] == "kept_draft"
    assert codes(result) == ["script_length_off_target"]


def test_failed_revision_call_keeps_the_draft_and_never_raises(llm):
    llm(script_data(200), RuntimeError("claude CLI timed out"))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.length["words"] == 200 and result.length["revision"] == "failed"
    assert codes(result) == ["script_length_off_target"]


def test_invalid_revision_json_keeps_the_draft(llm):
    llm(script_data(200), {"hook": "only a hook"})
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.length["revision"] == "failed" and result.length["words"] == 200


def test_failed_first_draft_still_fails_the_run(llm):
    llm(RuntimeError("no LLM available"))
    with pytest.raises(ScriptGeneratorError):
        ScriptGenerator().write_script("watches")


def test_short_preset_uses_the_short_budget(llm):
    fake = llm(script_data(117, scenes=6, roles=["hook", "open_loop", "rehook", "body", "payoff", "loop"]),
               script_data(80, scenes=6, roles=["hook", "open_loop", "rehook", "body", "payoff", "loop"]))
    result = ScriptGenerator().write_script("watches", video_duration="short")
    assert "78 words" in fake.prompts[0] and "6-8 scenes" in fake.prompts[0]
    assert "Rewrite it to 78 words" in fake.prompts[1]
    assert result.length["preset"] == "short" and result.length["words"] == 80


def test_unknown_duration_falls_back_to_medium(llm):
    fake = llm(script_data(117))
    result = ScriptGenerator().write_script("watches", video_duration="epic")
    assert result.length["preset"] == "medium" and "117 words" in fake.prompts[0]


def test_bad_roles_are_derived_with_a_warning_not_a_failure(llm):
    llm(script_data(117, roles=["intro", "body", "body", "body", "body", "body", "body", "outro"]))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.script.scene_roles == ["hook"] + ["body"] * 6 + ["loop"]
    [w] = result.warnings
    assert w["code"] == "scene_roles_derived" and "unknown roles" in w["detail"]["reason"]
    assert w["detail"]["llm_roles"][0] == "intro"


def test_missing_roles_are_derived(llm):
    data = script_data(117)
    del data["scene_roles"]
    llm(data)
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.script.scene_roles == ["hook"] + ["body"] * 6 + ["loop"]
    assert codes(result) == ["scene_roles_derived"]


def test_role_casing_variants_are_accepted_silently(llm):
    roles = ["Hook", "Open loop", "body", "body", "Re-hook", "body", "PAYOFF", "loop"]
    llm(script_data(117, roles=roles))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.script.scene_roles == ROLES8 and result.warnings == []


def test_warnings_come_from_the_script_that_is_used(llm):
    """Draft roles are bad; the accepted revision's roles are fine -> no scene_roles_derived warning."""
    llm(script_data(200, roles=["body"] * 8), script_data(118))
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert result.length["revision"] == "accepted" and result.warnings == []


def test_null_roles_and_headline_never_fail_the_run(llm):
    llm(script_data(117) | {"scene_roles": None, "hook_headline": None})
    result = ScriptGenerator().write_script("watches", video_duration="medium")
    assert codes(result) == ["scene_roles_derived"]
    assert result.script.hook_headline == ""


def test_script_output_coerces_mistyped_retention_fields():
    from app.content_engine import ScriptOutput
    base = {k: v for k, v in script_data(117).items() if k not in ("scene_roles", "hook_headline")}
    s = ScriptOutput(**base, scene_roles="hook, body", hook_headline=["A", "B"], hook_variants=None)
    assert s.scene_roles == [] and s.hook_headline == "" and s.hook_variants == []
    s = ScriptOutput(**base, scene_roles=["hook", None, 3], hook_headline=42)
    assert s.scene_roles == ["hook", "3"] and s.hook_headline == ""
