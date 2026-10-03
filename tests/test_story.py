"""app.story: "Your story" text rules (validation, sentence split, local scene split). Pure: no LLM, no I/O."""
import pytest

from app.cin.cost_estimate import llm_calls
from app.script_quality import SCENE_RANGE, count_words
from app.story import (MAX_SCENES, MAX_STORY_CHARS, StoryError, check_story, default_title, normalize_story,
                       scene_count, split_scenes, split_sentences)

STORY = ("The lighthouse keeper found the bottle on a Tuesday. It was green, and sealed with red wax. "
         "Inside was a map of the island, drawn by hand. Nobody on the island could read the writing. "
         "So he rowed to the mainland that night. The librarian there went pale when she saw it. "
         "It was her grandmother's handwriting.")


def test_normalize_collapses_whitespace_only():
    assert normalize_story("  Hello,\r\n\n  world!\t It's me.  ") == "Hello, world! It's me."
    assert normalize_story(None) == ""


@pytest.mark.parametrize("story", ["", "   \n\t "])
def test_empty_story_is_rejected(story):
    with pytest.raises(StoryError, match="empty"):
        check_story(story)


def test_story_over_the_limit_is_rejected_with_the_numbers():
    with pytest.raises(StoryError, match=f"{MAX_STORY_CHARS}"):
        check_story("a" * (MAX_STORY_CHARS + 1))


def test_limit_counts_the_normalized_text():
    """A story padded with blank lines is judged by what will be spoken, as the UI counter shows."""
    text, mode = check_story(("word " * 700) + "\n" * 2000)
    assert len(text) <= MAX_STORY_CHARS and mode == "verbatim"


def test_story_mode_default_and_validation():
    assert check_story("Once upon a time.")[1] == "verbatim"
    assert check_story("Once upon a time.", " Adapt ")[1] == "adapt"
    with pytest.raises(StoryError, match="story_mode"):
        check_story("Once upon a time.", "rewrite")


def test_default_title_is_the_first_eight_words_without_trailing_punctuation():
    assert default_title(STORY) == "The lighthouse keeper found the bottle on a"
    assert default_title("Short one.") == "Short one"
    assert default_title("") == ""


def test_sentences_split_at_terminal_punctuation_and_keep_every_character():
    s = split_sentences('He said "Run!" Then silence. Dr. Smith waited... Why? Because.')
    assert s == ['He said "Run!"', "Then silence.", "Dr. Smith waited...", "Why?", "Because."]
    assert " ".join(s) == normalize_story('He said "Run!" Then silence. Dr. Smith waited... Why? Because.')


def test_scene_count_uses_five_second_scenes_clamped_to_the_preset_when_the_story_fits():
    # 99 words = 45 s at 2.2 words/s -> 9 scenes, inside medium's 9-11
    assert scene_count(99, "medium") == 9
    # 70 words fit "short" (57-75 words): 70/2.2/5 = 6.4 -> 6, inside 6-8
    assert scene_count(70, "short") == 6
    lo, hi = SCENE_RANGE["long"]
    assert lo <= scene_count(140, "long") <= hi


def test_scene_count_is_proportional_when_the_story_does_not_fit_the_preset():
    assert scene_count(22, "medium") == 2               # 10 s story -> 2 scenes, not clamped up to 9
    assert scene_count(176, "short") == 16              # 80 s story on a 30 s preset: not clamped down to 8
    assert scene_count(3, "medium") == 1


def test_scene_count_is_capped_at_the_script_schema_limit():
    assert MAX_SCENES == 20
    assert scene_count(700, "long") == MAX_SCENES       # ~318 s story: 20 longer scenes, not 64


def test_split_scenes_never_changes_the_words():
    for n in range(1, 12):
        scenes = split_scenes(STORY, n)
        assert " ".join(scenes) == normalize_story(STORY)
        assert all(sc.strip() == sc and sc for sc in scenes)


def test_split_scenes_cuts_only_at_sentence_boundaries():
    sentences = split_sentences(STORY)
    for n in (2, 3, 4):
        scenes = split_scenes(STORY, n)
        assert len(scenes) == n
        for sc in scenes:            # every scene is a run of whole sentences
            assert sc.endswith((".", "!", "?"))
            assert any(sc.startswith(s) for s in sentences)


def test_split_scenes_balances_words():
    scenes = split_scenes(STORY, 3)
    counts = [count_words(s) for s in scenes]
    assert max(counts) - min(counts) <= 8, counts


def test_split_scenes_is_deterministic():
    assert split_scenes(STORY, 4) == split_scenes(STORY, 4)


def test_more_scenes_than_sentences_keeps_short_sentences_whole():
    scenes = split_scenes("One two three. Four five six.", 4)
    assert scenes == ["One two three.", "Four five six."]


def test_a_sentence_longer_than_two_scenes_is_split_at_word_boundaries_preferring_commas():
    long = ("The ship left the harbour at dawn, crossed the grey sea for nine long days, lost its mast in a storm, "
            "drifted past three islands, and finally ran aground on a beach that no map had ever shown.")
    scenes = split_scenes(long + " Then it was gone.", 4)
    assert " ".join(scenes) == normalize_story(long + " Then it was gone.")
    assert len(scenes) == 4
    assert scenes[0].endswith(",")                     # the cut inside the long sentence lands after a comma


def test_not_applicable_revision_is_one_llm_call():
    """Verbatim stories make one LLM call; the cost estimate and log must not count a revision."""
    assert llm_calls("not_applicable") == 1
    assert llm_calls("accepted") == 2 and llm_calls("not_needed") == 1


def test_full_width_sentence_ends_split_a_japanese_story():
    story = "昨日、私は海へ行きました。 波がとても高かった！ でも楽しかった？ 帰り道に虹が見えた．"
    sentences = split_sentences(story)
    assert len(sentences) == 4 and " ".join(sentences) == story
    scenes = split_scenes(story, 3)
    assert len(scenes) > 1 and " ".join(scenes) == story
