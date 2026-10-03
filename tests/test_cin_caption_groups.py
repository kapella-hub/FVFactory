"""Caption grouping + hook headline text (spec §7). Pure: aligned tokens in, groups out."""
from app.cin.align import AlignedToken
from app.cin.caption_groups import (GAP_BREAK, group_captions, hook_headline_text, make_hook_headline)
from tests.conftest import fixture_alignment


def toks(spec: str, step: float = 0.3, gap: float = 0.02):
    """'Hans Wilsdorf founded, a' -> AlignedTokens 0.3 s long with 0.02 s gaps; a trailing
    '.'/'!'/'?' sets sentence_end, ','/';' sets comma. '|' inserts a 0.5 s pause."""
    out, t = [], 0.0
    for raw in spec.split():
        if raw == "|":
            t += 0.5
            continue
        text = raw.rstrip(".,!?;")
        out.append(AlignedToken(text, round(t, 3), round(t + step, 3), True,
                                raw.endswith((".", "!", "?")), raw.endswith((",", ";"))))
        t += step + gap
    return out


def texts(groups):
    return [" ".join(w.text for w in g.words) for g in groups]


def test_groups_hold_one_to_three_words_and_keep_timing():
    groups = group_captions(toks("one two three four five six seven"))
    assert texts(groups) == ["one two three", "four five six", "seven"]
    assert groups[0].t0 == 0.0 and groups[0].t1 == groups[0].words[-1].t1
    assert all(w.t0 < w.t1 for g in groups for w in g.words)       # real per-word timing, not an even split


def test_break_after_sentence_end_and_comma():
    assert texts(group_captions(toks("It sank. Then, it rose again"))) == ["It sank", "Then", "it rose again"]


def test_break_at_gap_longer_than_quarter_second():
    assert texts(group_captions(toks("wait for | it now"))) == ["wait for", "it now"]
    tight = toks("a b c")
    tight[1].t0 = tight[0].t1 + GAP_BREAK          # exactly 0.25 s is not a break
    tight[1].t1 = tight[1].t0 + 0.3
    tight[2].t0, tight[2].t1 = tight[1].t1 + 0.02, tight[1].t1 + 0.3
    assert texts(group_captions(tight)) == ["a b c"]


def test_name_runs_never_split():
    assert texts(group_captions(toks("a German orphan named Hans Wilsdorf founded it"))) == \
        ["a German orphan", "named Hans Wilsdorf", "founded it"]


def test_all_caps_name_stays_together():
    assert texts(group_captions(toks("then ELON MUSK said no"))) == ["then ELON MUSK", "said no"]


def test_number_runs_never_split():
    assert texts(group_captions(toks("Rolex makes about 1 million watches"))) == \
        ["Rolex makes about", "1 million watches"]
    assert texts(group_captions(toks("sell for 40 percent above retail"))) == \
        ["sell for", "40 percent above", "retail"]


def test_money_token_is_one_word():
    assert texts(group_captions(toks("it sold for $1,000,000 in 1999."))) == ["it sold for", "$1,000,000 in 1999"]


def test_long_units_are_capped_at_three_words():
    """A 4-word name or an all-caps sentence must not become one oversized group."""
    assert texts(group_captions(toks("Martin Luther King Jr spoke"))) == ["Martin Luther King", "Jr spoke"]
    shouting = group_captions(toks("THIS IS THE BIGGEST SECRET IN HISTORY"))
    assert all(1 <= len(g.words) <= 3 for g in shouting)
    assert sum(len(g.words) for g in shouting) == 7


def test_empty_token_list_gives_no_groups():
    assert group_captions([]) == []


def test_rolex_fixture_groups():
    a = fixture_alignment("words_rolex_40s.json")
    groups = group_captions(a.tokens)
    flat = [w.text for g in groups for w in g.words]
    assert flat == [t.text for t in a.tokens]                       # nothing dropped or reordered
    assert all(1 <= len(g.words) <= 3 for g in groups)
    joined = texts(groups)
    assert "named Hans Wilsdorf" in joined
    assert any(j.startswith("1 million") for j in joined)
    assert any("40 percent" in j for j in joined)
    assert any(j.endswith("English Channel") for j in joined)
    i = 0
    for g in groups:                                                # punctuation only ever ends a group
        inner = a.tokens[i:i + len(g.words) - 1]
        assert not any(t.sentence_end or t.comma for t in inner), texts([g])
        i += len(g.words)


def test_gold_fixture_groups():
    a = fixture_alignment("words_gold_8s.json")
    assert texts(group_captions(a.tokens)) == [
        "Gold is heavier", "than you think", "A single cube", "this size weighs", "as much as",
        "a small car", "and it fits", "in your hand"]


def test_hook_headline_text_rules():
    assert hook_headline_text("This watch costs more than a car. And nobody knows why.") == \
        "This watch costs more than a car"
    assert hook_headline_text("Why is gold so heavy? Here is the answer.") == "Why is gold so heavy?"
    assert hook_headline_text("one two three four five six seven eight.") == "one two three four five six seven eight"
    assert hook_headline_text("one two three four five six seven eight nine.") is None
    assert hook_headline_text("") is None and hook_headline_text(None) is None and hook_headline_text("   ") is None
    assert hook_headline_text("No punctuation at all here") == "No punctuation at all here"


def test_make_hook_headline_window():
    assert make_hook_headline("Gold is heavy.", 40.0) == {"text": "Gold is heavy", "t0": 0.0, "t1": 2.5}
    assert make_hook_headline("Gold is heavy.", 1.8) == {"text": "Gold is heavy", "t0": 0.0, "t1": 1.8}
    assert make_hook_headline("a b c d e f g h i", 40.0) is None


def test_headline_does_not_split_after_abbreviations():
    assert hook_headline_text("Dr. Smith built a watch that sank.") == "Dr. Smith built a watch that sank"
    assert hook_headline_text("Mr. Rolex made time. Then it grew.") == "Mr. Rolex made time"
    assert hook_headline_text("Born in the U.S. he moved. Later he left.") == "Born in the U.S. he moved"
    assert hook_headline_text("A. Lange built it. Then more.") == "A. Lange built it"
    assert hook_headline_text("Rolex was founded. It grew.") == "Rolex was founded"
