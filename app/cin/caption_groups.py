"""Caption grouping and hook headline text (spec §7). Pure functions, no fonts, no I/O.

Groups hold 1-3 aligned script tokens. A group ends after punctuation (the token's sentence_end /
comma flag) and before a silence > GAP_BREAK. Numbers ("1 million", "40 percent") and capitalized
name runs ("Hans Wilsdorf", "ELON MUSK") are atomic units that never straddle two groups; a unit is
capped at MAX_WORDS tokens, so an all-caps sentence or a 4-word name degrades to 3-word groups
instead of one oversized group.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

MAX_WORDS = 3
GAP_BREAK = 0.25                 # spec §7: break at gaps > 0.25 s
HOOK_MAX_WORDS = 8               # spec §7: headline only if the hook's first sentence is <= 8 words
HOOK_SECONDS = 2.5               # spec §7: headline shown for [0, 2.5 s]
HEADLINE_MAX_WORDS = 6           # spec 2026-10-03 §8: the script's own hook_headline field
_EPS = 1e-6
NUMBER_WORDS = frozenset({
    "hundred", "thousand", "million", "billion", "trillion", "percent", "%",
    "dollars", "dollar", "euros", "pounds", "years", "kg", "km", "mph",
})
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_ABBREVIATIONS = frozenset({
    "mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "prof.", "vs.", "etc.", "u.s.", "u.k.", "no.", "inc.",
})
_SHORT_INITIAL = re.compile(r"^[A-Z][A-Za-z]{0,2}\.$")


def _first_sentence(text: str) -> str:
    """Text up to the first sentence break, skipping periods that follow an abbreviation or a lone
    short capitalized token ("Dr.", "A.")."""
    for m in _SENTENCE_SPLIT.finditer(text):
        left = text[:m.start()]
        last = left.split()[-1] if left.split() else ""
        if last.lower() in _ABBREVIATIONS:
            continue
        if _SHORT_INITIAL.match(left.strip()):
            continue
        return left
    return text


@dataclass
class CaptionWord:
    text: str
    t0: float
    t1: float


@dataclass
class CaptionGroup:
    t0: float
    t1: float
    words: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {"t0": round(self.t0, 3), "t1": round(self.t1, 3),
                "words": [{"text": w.text, "t0": round(w.t0, 3), "t1": round(w.t1, 3)} for w in self.words]}


def _is_number(text: str) -> bool:
    return any(c.isdigit() for c in text)


def _is_capitalized(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and letters[0].isupper()


def _joins(tokens: list, i: int, unit_len: int) -> bool:
    """True when token i continues the atomic unit that ends at token i-1."""
    prev, cur = tokens[i - 1], tokens[i]
    if unit_len >= MAX_WORDS or prev.sentence_end or prev.comma:
        return False
    if (_is_number(prev.text) or prev.text.lower() in NUMBER_WORDS) and cur.text.lower() in NUMBER_WORDS:
        return True
    return _is_capitalized(prev.text) and _is_capitalized(cur.text)


def _units(tokens: list) -> list:
    """Atomic [start, end) token ranges."""
    units, start = [], 0
    for i in range(1, len(tokens) + 1):
        if i == len(tokens) or not _joins(tokens, i, i - start):
            units.append((start, i))
            start = i
    return units


def group_captions(tokens: list) -> list:
    """Aligned tokens (anything with text, t0, t1, sentence_end, comma) -> [CaptionGroup]."""
    groups, current = [], []

    def flush():
        if current:
            groups.append(CaptionGroup(current[0].t0, current[-1].t1, list(current)))
            current.clear()

    for a, b in _units(tokens):
        if current:
            prev = tokens[a - 1]
            gap = tokens[a].t0 - prev.t1
            if len(current) + (b - a) > MAX_WORDS or gap > GAP_BREAK + _EPS:
                flush()
        current.extend(CaptionWord(t.text, t.t0, t.t1) for t in tokens[a:b])
        last = tokens[b - 1]
        if last.sentence_end or last.comma:
            flush()
    flush()
    return groups


def hook_headline_text(hook: Optional[str]) -> Optional[str]:
    """The hook's first sentence if it has <= HOOK_MAX_WORDS words, else None (spec §7).
    A trailing full stop is dropped; '?' and '!' are kept."""
    hook = (hook or "").strip()
    if not hook:
        return None
    first = _first_sentence(hook).strip()
    words = first.split()
    if not words or len(words) > HOOK_MAX_WORDS:
        return None
    return first.rstrip(".…").strip() or None


def script_headline_text(headline: Optional[str]) -> Optional[str]:
    """The script's hook_headline if it is 1..HEADLINE_MAX_WORDS words, else None.
    Same trailing-punctuation rule as hook_headline_text."""
    text = " ".join((headline or "").split()).rstrip(".…").strip()
    if not text or len(text.split()) > HEADLINE_MAX_WORDS:
        return None
    return text


def make_hook_headline(hook: Optional[str], duration: float, headline: Optional[str] = None) -> Optional[dict]:
    """shot_plan.json "hook_headline" value (spec §6.6): the script's headline field when usable,
    else the hook's first sentence (<= HOOK_MAX_WORDS words), else None."""
    text = script_headline_text(headline) or hook_headline_text(hook)
    if text is None:
        return None
    return {"text": text, "t0": 0.0, "t1": round(min(HOOK_SECONDS, duration), 3)}
