"""Speech alignment on saved Whisper word timings (spec §5, §12)."""
import json
from unittest.mock import patch

import pytest

from app.cin.align import MIN_SCENE, Alignment, align, align_words


def _align(fx, scene_texts=None, words=None):
    return align_words(words if words is not None else fx["words"],
                       scene_texts if scene_texts is not None else fx["scene_texts"],
                       fx["narration"], fx["duration"])


def test_rolex_scene_boundaries_come_from_speech(rolex):
    a = _align(rolex)
    assert a.method == "whisper+script"
    assert a.fallback is False
    assert a.match_ratio == pytest.approx(97 / 98, abs=1e-4)
    assert [s.t0 for s in a.scenes] == [0.0, 2.78, 9.14, 16.24, 24.71, 28.69, 35.61]
    assert a.scenes[-1].t1 == 40.12
    assert [(s.first_token, s.last_token) for s in a.scenes] == [
        (0, 7), (7, 22), (22, 39), (39, 60), (60, 69), (69, 88), (88, 98)]


def test_misheard_name_keeps_script_spelling_with_interpolated_timing(rolex):
    a = _align(rolex)
    tok = next(t for t in a.tokens if t.text == "Wilsdorf")
    assert tok.matched is False
    assert (tok.t0, tok.t1) == (5.36, 6.1)   # between "Hans" (ends 5.36) and "founded" (starts 6.10)


def test_numbers_match_across_digit_and_word_forms(rolex):
    a = _align(rolex)
    by_text = {t.text: t for t in a.tokens}
    assert by_text["1"].matched and by_text["1"].t0 == 26.46          # script "1", whisper "one"
    assert by_text["40"].matched and by_text["40"].t0 == 30.46        # script "40 percent", whisper "40%"
    assert by_text["percent"].matched and by_text["percent"].t1 == 30.73
    assert by_text["1926"].comma is True


def test_scene_texts_that_do_not_join_fall_back_to_word_count(rolex):
    scene_texts = list(rolex["scene_texts"])
    scene_texts[2] = "By 1926 he built the Oyster."          # LLM paraphrased one scene
    a = _align(rolex, scene_texts=scene_texts)
    assert a.fallback is True
    assert a.method == "word_count"
    assert a.reason == "scene_texts_do_not_join"
    assert len(a.scenes) == 7
    assert a.scenes[0].t0 == 0.0 and a.scenes[-1].t1 == 40.12
    assert all(s.t1 == nxt.t0 for s, nxt in zip(a.scenes, a.scenes[1:]))
    assert len(a.tokens) == 98                                  # caption timings still come from Whisper


def test_low_match_ratio_falls_back(rolex):
    words = [dict(w, word=" lorem") for w in rolex["words"]]
    a = _align(rolex, words=words)
    assert a.fallback is True
    assert a.reason == "low_match_ratio"
    assert a.match_ratio < 0.70


def test_missing_scene_texts_split_evenly_into_requested_scene_count(rolex):
    a = align_words(rolex["words"], [], rolex["narration"], rolex["duration"], num_scenes=5)
    assert a.fallback is True and a.reason == "scene_texts_missing"
    assert len(a.scenes) == 5
    assert a.scenes[1].t0 == pytest.approx(40.12 / 5, abs=1e-3)


def test_autojunk_disabled_on_long_narrations():
    # 360 tokens; Whisper drops every "on". difflib's autojunk would ignore "the" (>1 % of 200+ items)
    # and lose matches; with autojunk=False every other token matches.
    script = []
    for i in range(60):
        script += ["the", f"cat{i}", "sat", "on", "the", "mat."]
    heard = [w for w in script if w != "on"]
    words = [{"word": " " + w, "start": i * 0.3, "end": i * 0.3 + 0.25} for i, w in enumerate(heard)]
    narration = " ".join(script)
    a = align_words(words, [narration], narration, 100.0)
    assert a.match_ratio == pytest.approx(300 / 360, abs=1e-9)


def test_empty_scene_text_never_produces_zero_length_scene(rolex):
    scene_texts = list(rolex["scene_texts"])
    scene_texts.insert(3, "")
    a = align_words(rolex["words"], scene_texts, rolex["narration"], rolex["duration"])
    assert len(a.scenes) == 8
    assert all(s.t1 - s.t0 >= MIN_SCENE - 1e-3 for s in a.scenes)
    assert all(s.t1 == nxt.t0 for s, nxt in zip(a.scenes, a.scenes[1:]))


def test_alignment_json_roundtrip(rolex):
    a = _align(rolex)
    d = json.loads(json.dumps(a.to_json()))
    assert Alignment.from_json(d).to_json() == d


def test_align_survives_whisper_failure(rolex):
    with patch("app.cin.align.transcribe_words", side_effect=RuntimeError("no model")):
        a, words = align("narration.mp3", rolex["scene_texts"], rolex["narration"], rolex["duration"])
    assert words == []
    assert a.fallback is True
    assert a.reason.startswith("transcription_failed")
    assert len(a.scenes) == 7
