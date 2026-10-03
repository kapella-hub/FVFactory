"""ScriptGenerator.write_story_script: "Your story" (verbatim: local scenes + one visuals LLM call;
adapt: the retention-script path with the story as source material). The LLM is a fake."""
import pytest

from app.content_engine import ScriptGenerator, ScriptGeneratorError
from app.script_quality import count_words
from app.story import normalize_story, split_scenes

STORY = ("The lighthouse keeper found the bottle on a Tuesday.  It was green, and sealed with red wax.\n\n"
         "Inside was a map of the island, drawn by hand. Nobody on the island could read the writing. "
         "So he rowed to the mainland that night. The librarian there went pale when she saw it. "
         "It was her grandmother's handwriting.")
NORMAL = normalize_story(STORY)


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, prompt, system=None, temperature=0.7, max_tokens=1500):
        self.calls.append({"prompt": prompt, "system": system, "max_tokens": max_tokens})
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


def visuals(n, **over):
    data = {"title": "The Bottle Map", "hook_headline": "A MAP IN A BOTTLE",
            "image_prompts": [f"scene image {i}" for i in range(n)],
            "motion_prompts": [f"waves crash over the rocks {i}" for i in range(n)],
            "scene_roles": ["hook"] + ["body"] * (n - 2) + ["payoff"],
            "keywords": ["lighthouse", "mystery"],
            # an LLM that tries to rewrite the narration is ignored
            "hook": "REWRITTEN HOOK", "body": "REWRITTEN BODY", "scene_texts": ["nope"] * n}
    data.update(over)
    return data


def test_verbatim_narration_is_exactly_the_users_words(llm):
    fake = llm(visuals(5))
    result = ScriptGenerator().write_story_script(STORY, mode="verbatim", video_duration="medium")
    s = result.script
    assert " ".join(s.scene_texts) == NORMAL
    assert f"{s.hook} {s.body}" == NORMAL
    assert s.hook == s.scene_texts[0] and s.body == " ".join(s.scene_texts[1:])
    assert s.scene_texts == split_scenes(STORY, 5)
    assert len(s.image_prompts) == len(s.motion_prompts) == len(s.scene_roles) == 5
    assert s.hook_headline == "A MAP IN A BOTTLE" and s.keywords == ["lighthouse", "mystery"]
    assert len(fake.calls) == 1                                   # one LLM call, never a revision


def test_verbatim_prompt_gives_the_fixed_scenes_and_the_motion_rules(llm):
    fake = llm(visuals(5))
    ScriptGenerator().write_story_script(STORY, mode="verbatim", video_duration="medium", video_style="anime")
    call = fake.calls[0]
    for scene in split_scenes(STORY, 5):
        assert scene in call["prompt"]
    assert "exactly 5" in call["prompt"]
    assert "must not change" in call["system"]
    assert "visible physical action" in call["system"]            # action-first motion rules
    assert "ANIME" in call["system"]                              # style-adjusted image rules
    assert 'First write "scene_texts"' not in call["system"]
    assert call["max_tokens"] >= 1500                             # 3000 would truncate 20 scenes


def test_verbatim_report_fields(llm):
    llm(visuals(5))
    result = ScriptGenerator().write_story_script(STORY, mode="verbatim", video_duration="medium")
    words = count_words(NORMAL)
    assert result.length["revision"] == "not_applicable"
    assert result.length["story_mode"] == "verbatim"
    assert result.length["words"] == result.length["draft_words"] == words
    assert result.length["scenes"] == 5
    assert result.length["title"] == "The Bottle Map"
    assert result.length["target_seconds"] == round(words / 2.2, 1)


def test_story_outside_the_preset_only_warns(llm):
    llm(visuals(5))
    result = ScriptGenerator().write_story_script(STORY, mode="verbatim", video_duration="long")
    codes = [w["code"] for w in result.warnings]
    assert "story_length" in codes
    detail = next(w for w in result.warnings if w["code"] == "story_length")["detail"]
    assert detail["preset"] == "long" and detail["words"] == count_words(NORMAL)


def test_mismatched_llm_counts_are_normalized_without_touching_the_narration(llm):
    llm(visuals(5, image_prompts=["a", "b", "c", "d"], motion_prompts=["m1"], scene_roles=["hook"]))
    result = ScriptGenerator().write_story_script(STORY, mode="verbatim", video_duration="medium")
    s = result.script
    assert len(s.image_prompts) == len(s.scene_texts) == len(s.motion_prompts) == len(s.scene_roles) == 4
    assert " ".join(s.scene_texts) == NORMAL and f"{s.hook} {s.body}" == NORMAL
    assert "prompt_count_normalized" in [w["code"] for w in result.warnings]


def test_too_many_llm_prompts_are_truncated(llm):
    llm(visuals(9))
    s = ScriptGenerator().write_story_script(STORY, mode="verbatim", video_duration="medium").script
    assert len(s.image_prompts) == len(s.scene_texts) == 5


def test_one_sentence_story_makes_a_one_scene_script(llm):
    llm(visuals(1, scene_roles=["hook"]))
    s = ScriptGenerator().write_story_script("Gold never rusts.", mode="verbatim").script
    assert s.scene_texts == ["Gold never rusts."] and s.hook == "Gold never rusts." and s.body == ""


def test_no_usable_image_prompts_fails_before_any_spend(llm):
    llm(visuals(5, image_prompts=[]))
    with pytest.raises(ScriptGeneratorError, match="image prompts"):
        ScriptGenerator().write_story_script(STORY, mode="verbatim")


def test_llm_failure_is_a_script_generator_error(llm):
    llm(RuntimeError("cli down"))
    with pytest.raises(ScriptGeneratorError):
        ScriptGenerator().write_story_script(STORY, mode="verbatim")


def test_missing_keywords_and_headline_never_fail(llm):
    llm(visuals(5, keywords=None, hook_headline=None, title=None))
    result = ScriptGenerator().write_story_script(STORY, mode="verbatim", title="Bottle")
    assert result.script.keywords and result.script.hook_headline == ""
    assert result.length["title"] == ""


def test_adapt_mode_passes_the_story_as_source_material(llm):
    hook = "A bottle washed up with a map inside."
    draft = {"hook": hook, "body": " ".join(["tide"] * (99 - count_words(hook))),
             "image_prompts": [f"img {i}" for i in range(9)], "motion_prompts": ["waves roll"] * 9,
             "keywords": ["sea"], "scene_roles": ["hook"] + ["body"] * 7 + ["loop"]}
    fake = llm(draft)
    result = ScriptGenerator().write_story_script(STORY, mode="adapt", video_duration="medium", title="The bottle")
    prompt = fake.calls[0]["prompt"]
    assert NORMAL in prompt and "SOURCE STORY" in prompt and "Do not invent" in prompt
    assert "The bottle" in prompt
    assert result.length["story_mode"] == "adapt" and result.length["revision"] == "not_needed"
    assert result.script.hook == hook


def test_adapt_revision_keeps_the_story_in_the_prompt(llm):
    short = {"hook": "A bottle.", "body": "Map.", "image_prompts": [f"img {i}" for i in range(9)],
             "keywords": ["sea"], "scene_roles": []}
    fake = llm(short, short)
    ScriptGenerator().write_story_script(STORY, mode="adapt", video_duration="medium")
    assert len(fake.calls) == 2 and NORMAL in fake.calls[1]["prompt"]


def test_topic_scripts_have_no_story_block(llm):
    hook = "This watch costs more than your house."
    fake = llm({"hook": hook, "body": " ".join(["tick"] * 92), "image_prompts": [f"i{n}" for n in range(9)],
                "keywords": ["w"], "scene_roles": []})
    ScriptGenerator().write_script("Rolex", video_duration="medium")
    assert "SOURCE STORY" not in fake.calls[0]["prompt"]


def test_unknown_story_mode_is_rejected(llm):
    with pytest.raises(ValueError):
        ScriptGenerator().write_story_script(STORY, mode="remix")
