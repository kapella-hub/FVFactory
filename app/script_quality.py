"""Script retention rules (spec 2026-10-03): word budget per duration preset and scene roles.
Pure functions: no LLM, no I/O. The LLM revision call that uses the budget lives in
app/content_engine.py (ScriptGenerator.write_script)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional, Tuple

WORDS_PER_SECOND = 2.2            # ~132 wpm. Measured 2026-10-03, ElevenLabs Multilingual v2 at default speed:
                                  # 2.15 and 2.28 words/s (119 words -> 55.4 s, 128 words -> 56.1 s); at the old
                                  # 2.6 a "medium" (45 s) video ran ~56 s
TOLERANCE = 0.15                  # accept +/- 15 % of the target word count
DEFAULT_DURATION = "medium"
DURATION_SECONDS = {"short": 30, "medium": 45, "long": 60}
SCENE_RANGE = {"short": (6, 8), "medium": (9, 11), "long": (11, 14)}

SCENE_ROLES = ("hook", "open_loop", "body", "rehook", "payoff", "loop")
_ROLE_ALIASES = {"re_hook": "rehook", "openloop": "open_loop", "loop_ending": "loop", "loopback": "loop"}
_WORD = re.compile(r"\w")


@dataclass(frozen=True)
class WordBudget:
    preset: str                   # short | medium | long
    seconds: int                  # target spoken seconds
    target: int                   # target word count
    lo: int                       # accepted range, inclusive
    hi: int
    scenes: Tuple[int, int]       # (min, max) scenes the prompt asks for

    def contains(self, words: int) -> bool:
        return self.lo <= words <= self.hi


def word_budget(duration: Optional[str]) -> WordBudget:
    """Budget for a duration preset; unknown or empty presets use DEFAULT_DURATION."""
    preset = duration if duration in DURATION_SECONDS else DEFAULT_DURATION
    seconds = DURATION_SECONDS[preset]
    target = round(seconds * WORDS_PER_SECOND)
    return WordBudget(preset, seconds, target,
                      math.ceil(target * (1 - TOLERANCE)), math.floor(target * (1 + TOLERANCE)),
                      SCENE_RANGE[preset])


def count_words(text: Optional[str]) -> int:
    """Whitespace tokens that contain at least one letter or digit ("—" and "-" do not count)."""
    return sum(1 for tok in (text or "").split() if _WORD.search(tok))


def canonical_role(value) -> Optional[str]:
    """'Re-hook' -> 'rehook', 'Open loop' -> 'open_loop'; None for anything that is not a role."""
    if not isinstance(value, str):
        return None
    key = re.sub(r"[\s\-]+", "_", value.strip().lower())
    key = _ROLE_ALIASES.get(key, key)
    return key if key in SCENE_ROLES else None


def derived_roles(n: int) -> list:
    """Heuristic roles when the LLM's are missing or invalid: first hook, last loop, body between."""
    if n <= 0:
        return []
    if n == 1:
        return ["hook"]
    return ["hook"] + ["body"] * (n - 2) + ["loop"]


def check_roles(roles: list, n: int) -> Tuple[list, Optional[str]]:
    """(roles, None) when the n roles are valid; else (derived_roles(n), reason).
    Valid: exactly n entries, every entry a known role (after canonical_role), first is 'hook'."""
    if not roles:
        return derived_roles(n), "missing"
    canon = [canonical_role(r) for r in roles]
    if len(canon) != n:
        return derived_roles(n), f"expected {n} roles, got {len(canon)}"
    bad = [r for r, c in zip(roles, canon) if c is None]
    if bad:
        return derived_roles(n), f"unknown roles {bad[:3]}"
    if canon[0] != "hook":
        return derived_roles(n), f"first role is {canon[0]!r}, not 'hook'"
    return canon, None
