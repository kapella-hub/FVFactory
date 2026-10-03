""""Your story" input (Generate page source "Your story", CLI --story-file): pure text rules.

verbatim mode: the narration is exactly the user's words (whitespace normalised). The story is split into
scenes HERE, deterministically and at sentence boundaries, so no LLM can change the narration; the one LLM
call (ScriptGenerator.write_story_script) only writes the visuals for these fixed scene texts.
adapt mode: the story is source material for the normal retention-script path (ScriptGenerator.write_script).

No LLM, no I/O.
"""
from __future__ import annotations

import math
import re
from typing import List, Optional, Tuple

from app.script_quality import WORDS_PER_SECOND, count_words, word_budget

MAX_STORY_CHARS = 4000            # counted on the whitespace-normalised text (what is spoken), as the UI shows
STORY_MODES = ("verbatim", "adapt")
DEFAULT_STORY_MODE = "verbatim"
SCENE_SECONDS = 5.0               # target spoken seconds per scene
MAX_SCENES = 20                   # ScriptOutput.image_prompts allows 5-20; longer stories get longer scenes
TITLE_WORDS = 8                   # default title = the story's first words

# A token ends a sentence when it ends in . ! ? (or their full-width forms) or an ellipsis, optionally followed by closing quotes/brackets.
_SENTENCE_END = re.compile(r"(?:[.!?。！？．]|…)+[\"'”’)\]]*$")
_ABBREVIATIONS = frozenset({"mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "vs.", "e.g.", "i.e.", "mt.",
                            "prof.", "no.", "approx."})
_SOFT_BREAK = re.compile(r"[,;:—–]$|^[—–-]+$")     # cut a too-long sentence after these
_TRAILING_PUNCT = ".,;:!?…\"'“”‘’()[]-—– "


class StoryError(ValueError):
    """A story the pipeline cannot use (empty, too long, unknown mode)."""


def normalize_story(text: Optional[str]) -> str:
    """Collapse every run of whitespace (newlines, tabs) to one space; strip the ends."""
    return " ".join(str(text or "").split())


def check_story(story: Optional[str], mode: Optional[str] = None) -> Tuple[str, str]:
    """(normalised story, mode). Raises StoryError for an empty or too-long story or an unknown mode.
    mode None/blank = DEFAULT_STORY_MODE."""
    text = normalize_story(story)
    if not text:
        raise StoryError("Story is empty: paste the narration you want spoken")
    if len(text) > MAX_STORY_CHARS:
        raise StoryError(f"Story is {len(text)} characters; the limit is {MAX_STORY_CHARS} "
                         f"(about {round(MAX_STORY_CHARS / 5.7 / WORDS_PER_SECOND / 60)} minutes spoken)")
    m = (mode or "").strip().lower() or DEFAULT_STORY_MODE
    if m not in STORY_MODES:
        raise StoryError(f"Unknown story_mode {mode!r}; choose one of {', '.join(STORY_MODES)}")
    return text, m


def default_title(story: Optional[str], words: int = TITLE_WORDS) -> str:
    """The first `words` words of the story, without trailing punctuation (job folder / metadata topic)."""
    return " ".join(normalize_story(story).split(" ")[:words]).strip(_TRAILING_PUNCT)


def split_sentences(story: Optional[str]) -> List[str]:
    """Sentences of the normalised story. " ".join(result) == normalize_story(story), always."""
    tokens = normalize_story(story).split(" ")
    if tokens == [""]:
        return []
    sentences, current = [], []
    for i, tok in enumerate(tokens):
        current.append(tok)
        last = i == len(tokens) - 1
        if last or (_SENTENCE_END.search(tok) and tok.lower() not in _ABBREVIATIONS):
            sentences.append(" ".join(current))
            current = []
    return sentences


def scene_count(words: int, preset: Optional[str]) -> int:
    """Scenes for a story of `words` words: ~SCENE_SECONDS of narration each. When the story fits the duration
    preset's word range the count is clamped to the preset's SCENE_RANGE; otherwise it is proportional to the
    story. Always 1..MAX_SCENES."""
    budget = word_budget(preset)
    n = max(1, round(words / WORDS_PER_SECOND / SCENE_SECONDS))
    if budget.contains(words):
        lo, hi = budget.scenes
        n = min(max(n, lo), hi)
    return min(n, MAX_SCENES)


def _chunk(sentence: str, k: int) -> List[str]:
    """Split one long sentence into k word-boundary pieces of about equal length, moving each cut to the
    nearest comma / semicolon / dash within half a piece when there is one."""
    tokens = sentence.split(" ")
    k = max(1, min(k, len(tokens)))
    size = len(tokens) / k
    cuts, prev = [], 0
    for j in range(1, k):
        ideal = round(j * size)
        window = max(1, int(size // 2))
        best = None
        for d in range(window + 1):                       # nearest soft break, earlier side first on ties
            for cut in (ideal - d, ideal + d):
                if prev < cut < len(tokens) - (k - j - 1) and _SOFT_BREAK.search(tokens[cut - 1]):
                    best = cut
                    break
            if best is not None:
                break
        if best is None:
            best = min(max(ideal, prev + 1), len(tokens) - (k - j))
        cuts.append(best)
        prev = best
    bounds = [0, *cuts, len(tokens)]
    return [" ".join(tokens[a:b]) for a, b in zip(bounds, bounds[1:])]


def _partition(weights: List[int], k: int) -> List[int]:
    """Cut indexes splitting `weights` into k contiguous non-empty groups with the least sum of squared
    deviations from the mean group weight. Deterministic (the earliest best cut wins ties)."""
    m = len(weights)
    target = sum(weights) / k
    prefix = [0]
    for w in weights:
        prefix.append(prefix[-1] + w)
    inf = float("inf")
    best = [[inf] * (m + 1) for _ in range(k + 1)]
    back = [[0] * (m + 1) for _ in range(k + 1)]
    best[0][0] = 0.0
    for g in range(1, k + 1):
        for end in range(g, m - (k - g) + 1):
            for start in range(g - 1, end):
                if best[g - 1][start] == inf:
                    continue
                cost = best[g - 1][start] + (prefix[end] - prefix[start] - target) ** 2
                if cost < best[g][end] - 1e-9:
                    best[g][end], back[g][end] = cost, start
    cuts, end = [], m
    for g in range(k, 0, -1):
        cuts.append(end)
        end = back[g][end]
    return sorted(cuts)


def split_scenes(story: Optional[str], n: int) -> List[str]:
    """Split the normalised story into at most n scene texts at sentence boundaries, balancing words.
    A sentence longer than two scenes' worth of words is first cut into scene-sized pieces (at commas when
    possible). Fewer than n scenes come back when there are fewer sentences (pieces) than n.
    " ".join(result) == normalize_story(story), always."""
    sentences = split_sentences(story)
    if not sentences:
        return []
    n = max(1, n)
    per_scene = sum(count_words(s) for s in sentences) / n
    units: List[str] = []
    for s in sentences:
        w = count_words(s)
        if n > 1 and per_scene > 0 and w > 2 * per_scene:
            units += _chunk(s, math.ceil(w / per_scene))
        else:
            units.append(s)
    k = min(n, len(units))
    bounds = [0, *_partition([count_words(u) for u in units], k)]
    return [" ".join(units[a:b]) for a, b in zip(bounds, bounds[1:])]
