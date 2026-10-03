# Script Upgrades (Retention-Engineered Scripts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scripts follow a hook → open loop → body → re-hook → payoff → loop-ending structure in a conversational voice, hit a per-preset word budget before any paid generation, and hand the editor their beats (headline, scene roles) so transitions land on the beats.

**Architecture:** A new pure module `app/script_quality.py` holds the word budget and scene-role rules. `ScriptGenerator.write_script` (in `app/content_engine.py`) wraps the existing single LLM call with normalization, role checking and at most one length-revision call, returning the script plus report warnings. `main.run_pipeline` uses it, records narration timing, and passes roles and the headline into `build_shot_plan`, which saves roles on scenes and picks styled transitions from them; `rebuild_plan` reads them back so `--rerender` is stable. The image-style/mascot fix threads the run's `video_style` into `AssetManager`.

**Tech Stack:** Python 3.14 (venv `.venv/`), pydantic v2, pytest, Windows + Git Bash. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-03-script-upgrades-design.md`

## Global Constraints

- Word budget: `WORDS_PER_SECOND = 2.6`, tolerance ±15 %; short 30 s → 78 words (67–89), medium 45 s → 117 (100–134), long 60 s → 156 (133–179); scenes short 6–8, medium 9–11, long 11–14; unknown/empty preset → medium.
- At most **one** revision call per run; the gate and the revision never fail a run; only a failed first draft does.
- Scene roles: `hook | open_loop | body | rehook | payoff | loop`; first must be `hook`; invalid → derived (`hook`, `body`…, `loop`) with warning `scene_roles_derived`.
- `hook_headline`: 1–6 words after trimming, else fallback to the hook's first sentence (≤ 8 words) with warning `hook_headline_fallback`.
- Styled transitions: max 3, roles priority `rehook` > `payoff` > `loop`; no roles → longest-pause rule unchanged; roles present → no pause fallback.
- `shot_plan.json` scenes get an optional `role` key written only when set; legacy plans load with `role = None` and round-trip byte-identical.
- New warning codes: `script_length_off_target`, `scene_roles_derived`, `hook_headline_fallback` (added to `WARNING_CODES` and carried by `--rerender`).
- Mascot never applied to photorealistic runs; `mascot_enabled` default `False`; `image_style` default `""` (derive from the run's `video_style`); `.env` overrides keep working.
- Tests are offline: the LLM is a fake installed on `app.content_engine.generate_json`. An unpatched LLM call starts the `claude` CLI subprocess (`llm_provider` default `claude_cli`), which the `requests` patches do not catch — never leave one unpatched. No paid run.
- Never print `.env` values.
- Run commands from the repo root in Git Bash with `.venv/Scripts/python.exe`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Baseline (2026-10-03, `feat/script-upgrades` @ 1970d87): `.venv/Scripts/python.exe -m pytest tests/ -q --tb=no -rf -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py` → `12 failed, 527 passed` (4 `test_uploader`, 6 `test_trends`, 1 `test_trend_scout`, 1 `test_local_image_gen`). These 12 stay failing; nothing else may.

## Review Focus

1. **The LLM writes roles with casing or hyphens** (`"Re-hook"`, `"Open loop"`, `"PAYOFF"`) — a person expects them accepted as-is, not replaced by the heuristic with a warning. Pinned by `test_canonical_role` (Task 1) and `test_role_casing_variants_are_accepted_silently` (Task 3).
2. **The revision call times out or returns broken JSON** (claude CLI timeout, truncated output) — a person expects the run to continue on the draft with a `script_length_off_target` warning, not to fail after nothing was spent. Pinned by `test_failed_revision_call_keeps_the_draft_and_never_raises` and `test_invalid_revision_json_keeps_the_draft` (Task 3).
3. **`--rerender` of a job made before this change** (no `role` keys) and of a new job at a different pacing — a person expects the styled transitions to stay where they were. Pinned by `test_rebuild_legacy_plan_without_roles_keeps_pause_transitions` and `test_rebuild_plan_keeps_roles_and_beat_transitions` (Task 4).
4. **Paraphrased `scene_texts` force the word-count alignment fallback** — a person expects roles still to land on the right scenes and the loop scene still to get its transition. Pinned by `test_roles_survive_alignment_fallback` (Task 5).
5. **`.env` sets `MASCOT_ENABLED` (value not inspected); if it is true with the photorealistic style** — a person expects no robot in the system prompt or on mock images. Pinned by `test_mascot_never_added_to_photoreal_prompts` and `test_mock_image_never_mentions_the_mascot_for_photoreal` (Task 6).

---

## File map

| File | Responsibility | Tasks |
|---|---|---|
| `app/script_quality.py` (new) | Word budget, word count, role canonicalization/check/derivation. Pure. | 1 |
| `app/content_engine.py` | `ScriptOutput` fields, role normalization, prompt text, `write_script` + `revise_length`, mascot guard | 2, 3, 6 |
| `app/cin/shot_plan.py` | `Scene.role`, `build_shot_plan(roles=)`, beat transitions | 4 |
| `app/cin/caption_groups.py` | `script_headline_text`, `make_hook_headline(headline=)` | 4 |
| `app/cin/editor.py` | `rebuild_plan` reads roles; rerender carries script section/warnings | 4, 5 |
| `app/cin/report.py` | `RunReport.script`, new warning codes | 5 |
| `main.py` | `write_script`, narration timing, roles + headline into the plan, `AssetManager(video_style=)` | 5, 6 |
| `app/config.py`, `app/asset_manager.py`, `app/web/static/js/generate.js` | Style suffix, mascot default/guard, labels | 6 |

---

### Task 1: Word budget and scene-role rules

**Files:**
- Create: `app/script_quality.py`
- Test: `tests/test_script_quality.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 2, 3):
  - `WORDS_PER_SECOND: float`, `TOLERANCE: float`, `DEFAULT_DURATION: str`, `DURATION_SECONDS: dict[str, int]`, `SCENE_RANGE: dict[str, tuple[int, int]]`, `SCENE_ROLES: tuple[str, ...]`
  - `@dataclass(frozen=True) WordBudget(preset: str, seconds: int, target: int, lo: int, hi: int, scenes: tuple[int, int])` with `contains(words: int) -> bool`
  - `word_budget(duration: Optional[str]) -> WordBudget`
  - `count_words(text: Optional[str]) -> int`
  - `canonical_role(value) -> Optional[str]`
  - `derived_roles(n: int) -> list[str]`
  - `check_roles(roles: list, n: int) -> tuple[list[str], Optional[str]]` — `(canonical roles, None)` when valid, else `(derived_roles(n), reason)`

- [ ] **Step 1: Write the failing test**

Create `tests/test_script_quality.py`:

```python
"""Word budget and scene roles (spec 2026-10-03 §5, §7)."""
import pytest

from app.script_quality import (
    SCENE_ROLES, canonical_role, check_roles, count_words, derived_roles, word_budget,
)


@pytest.mark.parametrize("preset, seconds, target, lo, hi, scenes", [
    ("short", 30, 78, 67, 89, (6, 8)),
    ("medium", 45, 117, 100, 134, (9, 11)),
    ("long", 60, 156, 133, 179, (11, 14)),
])
def test_word_budget_table(preset, seconds, target, lo, hi, scenes):
    b = word_budget(preset)
    assert (b.preset, b.seconds, b.target, b.lo, b.hi, b.scenes) == (preset, seconds, target, lo, hi, scenes)
    assert b.contains(lo) and b.contains(hi) and not b.contains(lo - 1) and not b.contains(hi + 1)


@pytest.mark.parametrize("value", ["", None, "epic", "MEDIUM"])
def test_unknown_or_empty_preset_uses_medium(value):
    assert word_budget(value).preset == "medium"


def test_count_words_ignores_punctuation_only_tokens():
    assert count_words("This watch costs more than a car — and nobody notices.") == 10
    assert count_words("It cost $1,000,000 in 1969.") == 5
    assert count_words("") == 0 and count_words(None) == 0


@pytest.mark.parametrize("raw, expected", [
    ("hook", "hook"), ("Re-hook", "rehook"), ("re hook", "rehook"), ("REHOOK", "rehook"),
    ("Open loop", "open_loop"), ("open-loop", "open_loop"), ("loop ending", "loop"),
    (" payoff ", "payoff"), ("climax", None), ("", None), (None, None), (3, None),
])
def test_canonical_role(raw, expected):
    assert canonical_role(raw) == expected


def test_derived_roles_shapes():
    assert derived_roles(0) == []
    assert derived_roles(1) == ["hook"]
    assert derived_roles(2) == ["hook", "loop"]
    assert derived_roles(5) == ["hook", "body", "body", "body", "loop"]


def test_valid_roles_are_canonicalized_without_a_reason():
    roles, reason = check_roles(["Hook", "open loop", "body", "Re-hook", "payoff", "loop"], 6)
    assert roles == ["hook", "open_loop", "body", "rehook", "payoff", "loop"]
    assert reason is None
    assert set(roles) <= set(SCENE_ROLES)


@pytest.mark.parametrize("roles, n, reason_part", [
    ([], 4, "missing"),
    (["body", "hook", "payoff", "loop"], 4, "not 'hook'"),
    (["hook", "climax", "payoff", "loop"], 4, "unknown roles"),
    (["hook", "payoff", "loop"], 4, "expected 4 roles"),
])
def test_invalid_roles_are_derived_with_a_reason(roles, n, reason_part):
    out, reason = check_roles(roles, n)
    assert out == derived_roles(n)
    assert reason_part in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_script_quality.py -q -p no:cacheprovider`
Expected: collection error `ModuleNotFoundError: No module named 'app.script_quality'`

- [ ] **Step 3: Write minimal implementation**

Create `app/script_quality.py`:

```python
"""Script retention rules (spec 2026-10-03): word budget per duration preset and scene roles.
Pure functions: no LLM, no I/O. The LLM revision call that uses the budget lives in
app/content_engine.py (ScriptGenerator.write_script)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional, Tuple

WORDS_PER_SECOND = 2.6            # ~156 wpm, ElevenLabs Multilingual v2 at default speed
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_script_quality.py -q -p no:cacheprovider`
Expected: `26 passed`

- [ ] **Step 5: Commit**

```bash
git add app/script_quality.py tests/test_script_quality.py
git commit -m "feat: word budget and scene-role rules for retention scripts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Script fields, role normalization and the retention prompt

**Files:**
- Modify: `app/content_engine.py:1-15` (imports), `:18-47` (`ScriptOutput`), `:60-93` (`_prompt_counts`, `normalize_prompt_counts`), `:96` (new `duration_guide` before `ScriptGeneratorError`), `:104-148` (`BASE_SYSTEM_PROMPT`, `V2_INSTRUCTION`), `:191-195` (`DURATION_GUIDE`)
- Test: `tests/test_content_engine.py:38-47` (flip one assertion) and new tests; `tests/test_prompt_normalization.py` (new tests)

**Interfaces:**
- Consumes (Task 1): `DURATION_SECONDS`, `WordBudget`, `word_budget`.
- Produces (used by Tasks 3–5):
  - `ScriptOutput.hook_headline: str = ""`, `ScriptOutput.scene_roles: List[str] = []`
  - `normalize_prompt_counts(script) -> (ScriptOutput, Optional[dict])` now also aligns `scene_roles` and reports `"scene_roles"` in `before`/`after`.
  - `duration_guide(budget: WordBudget) -> str`; `ScriptGenerator.DURATION_GUIDE: dict[str, str]` built from it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_content_engine.py`, replace

```python
    assert "hook_variants" in prompt
    assert "hook_viral_score" in prompt
```

with

```python
    assert "hook_variants" in prompt
    assert "hook_viral_score" not in prompt          # spec 2026-10-03 §4.6: no longer requested
```

and append:

```python


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
```

Append to `tests/test_prompt_normalization.py`:

```python


def test_scene_roles_padded_with_body_only_when_present():
    script = make().model_copy(update={"scene_roles": ["hook", "open_loop", "body", "rehook"]})
    out, change = normalize_prompt_counts(script)
    assert out.scene_roles == ["hook", "open_loop", "body", "rehook", "body", "body"]
    assert change["before"]["scene_roles"] == 4 and change["after"]["scene_roles"] == 6
    assert normalize_prompt_counts(make())[0].scene_roles == []


def test_extra_scene_roles_merge_like_scene_texts_and_keep_the_last_role():
    roles = ["hook", "open_loop", "body", "rehook", "body", "body", "payoff", "loop"]
    script = make(scenes=8).model_copy(update={"scene_roles": roles})
    out, _ = normalize_prompt_counts(script)
    assert out.scene_roles == ["hook", "open_loop", "body", "rehook", "body", "loop"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_content_engine.py tests/test_prompt_normalization.py -q -p no:cacheprovider --tb=line`
Expected: 6 failed — `assert 'hook_viral_score' not in ...`, `AttributeError: 'ScriptOutput' object has no attribute 'hook_headline'`, `AssertionError: "hook_headline"`, `assert ('78 words' in 'Keep the video SHORT: ...')`, and two `scene_roles` list mismatches. (`test_cartoon_style_still_replaces_the_photoreal_image_rules` passes already; it pins the two `.replace()` targets that the prompt rewrite must keep verbatim.)

- [ ] **Step 3: Implement**

In `app/content_engine.py`:

(a) Imports — after `from app.llm import generate_json` add:

```python
from app.script_quality import DURATION_SECONDS, WordBudget, word_budget
```

(b) `ScriptOutput` — change the `hook` description to `"First spoken sentence: <= 12 words, ~2 seconds"` and add after `emoji_subtitles`:

```python

    # Retention fields (spec 2026-10-03, optional, backward compatible)
    hook_headline: str = Field(default="", description="<= 6 punchy words for the top band; not the hook sentence")
    scene_roles: List[str] = Field(default=[], description="One per scene: hook|open_loop|body|rehook|payoff|loop")
```

(c) Replace `_prompt_counts` and the body of `normalize_prompt_counts` from `hints = list(...)` to the `model_copy` call:

```python
def _prompt_counts(script: "ScriptOutput") -> dict:
    return {"image_prompts": len(script.image_prompts), "motion_prompts": len(script.motion_prompts),
            "scene_texts": len(script.scene_texts), "pacing_hints": len(script.pacing_hints),
            "scene_roles": len(script.scene_roles)}
```

```python
    hints = list(script.pacing_hints)
    if hints:
        hints = hints[:n] + ["normal"] * max(0, n - len(hints))
    roles = list(script.scene_roles)
    if len(roles) > n:      # same merge rule as scene_texts: the merged last scene keeps the last role
        roles = roles[:max(n - 1, 0)] + roles[-1:] if n else []
    elif roles:
        roles += ["body"] * (n - len(roles))
    new = script.model_copy(update={"image_prompts": list(script.image_prompts[:n]),
                                    "motion_prompts": motion, "scene_texts": scenes,
                                    "pacing_hints": hints, "scene_roles": roles})
```

Update its docstring's first line to `Make image_prompts / motion_prompts / scene_texts / pacing_hints / scene_roles the same length (spec §10; scene_roles: spec 2026-10-03 §5.3).` and add the sentence `scene_roles, when present, are padded with "body" or merged like scene_texts (the merged last scene keeps the last role); validity is checked later by app.script_quality.check_roles.`

(d) Add before `class ScriptGeneratorError`:

```python
def duration_guide(budget: WordBudget) -> str:
    """The DURATION line of the user prompt, generated from the word budget so the two never drift."""
    return (f"{budget.preset.upper()}: about {budget.seconds} seconds of narration. hook + body together must be "
            f"{budget.target} words (anything from {budget.lo} to {budget.hi} words is fine). "
            f"Use {budget.scenes[0]}-{budget.scenes[1]} scenes, one idea per scene.")
```

(e) Replace everything in `BASE_SYSTEM_PROMPT` **before** the line `CRITICAL IMAGE PROMPT RULES:` (keep that line and the whole image-rules block byte-identical) with:

```python
    BASE_SYSTEM_PROMPT = """You write scripts for short vertical videos (TikTok, YouTube Shorts, Reels).
Your one job: keep a scrolling viewer watching to the last second, then make the replay feel seamless.

You MUST respond with a valid JSON object containing:
- "hook": The first spoken sentence. 12 words or fewer, about 2 seconds out loud.
- "body": Everything spoken after the hook. hook + body is the whole narration; the DURATION section says how many words it must be.
- "hook_headline": 2 to 6 punchy words shown on screen while the hook plays. Do NOT repeat the hook sentence; add the number or the stakes. Example: hook "This watch costs more than your house." -> hook_headline "$2M FOR A WATCH?"
- "image_prompts": One visual description per scene. The DURATION section says how many scenes.
- "scene_roles": One role per scene, same count as image_prompts, each one of "hook", "open_loop", "body", "rehook", "payoff", "loop". The first is always "hook"; the last is "loop".
- "keywords": Relevant keywords for metadata and discoverability

STRUCTURE (in this order):
1. HOOK (scene 1, role "hook"): stop the scroll in under 2 seconds with a contradiction, a specific number, or real stakes. Lead with the most surprising fact, never with a setup.
   Never open with "In this video", "Have you ever wondered", "Did you know", "Let's talk about", "Imagine", "Today we" or "Welcome".
2. OPEN LOOP (by about 5 seconds, role "open_loop"): promise a specific payoff and hold it back, e.g. "...and the reason it still works is the strangest part." The viewer must want that answer.
3. BODY (role "body"): concrete specifics - numbers, names of places and things, cause and effect. One idea per scene; each scene earns the next.
4. RE-HOOK (40-60% of the way in, role "rehook"): a pattern interrupt that resets attention, e.g. "But here's the part nobody mentions." Then raise the stakes.
5. PAYOFF (role "payoff"): close the open loop with the answer you promised. Make it specific.
6. LOOP ENDING (last scene, role "loop"): the last sentence leads straight back into the hook, so the replay sounds like one continuous thought. Either set the hook up ("...and that is why, fifty years later,") or end on a line the hook answers. No goodbye, no "follow for more", no summary.

VOICE:
- Talk to one person. Use "you" where it fits. Sound like a friend telling you something wild they just found out.
- Short sentences: 14 words or fewer on average. Plain words a 12-year-old knows.
- No documentary-narrator or TED-talk voice. No filler, no throat-clearing, no rhetorical windups.
- Never use these phrases: "in today's world", "let's dive in", "dive into", "buckle up", "game-changer", "mind-blowing", "you won't believe", "the answer may surprise you", "stay tuned", "without further ado", "at the end of the day", "fun fact", "it's important to note", "in conclusion".
- Every claim must be true and specific.

CRITICAL IMAGE PROMPT RULES:
```

(f) In `V2_INSTRUCTION`: replace the two lines

```text
- "hook_variants": 3 alternative hook options (list of strings)
- "hook_viral_score": Rate the main hook 1-10 on scroll-stopping potential
```

with

```text
- "hook_variants": 3 alternative hook options (list of strings), each following the HOOK rules
```

replace `  The segments must join together to form the complete narration (hook + body).` with
`  The segments must join together to form the complete narration (hook + body); the first segment starts with the hook.`
and replace the example line `  ["Did you know the ocean holds secrets?", "First, 80% is unexplored...", "Finally, the deepest point..."]` with
`  ["The ocean floor is darker than outer space.", "We have mapped less than a quarter of it...", "And the deepest point..."]`.

(g) Replace the `DURATION_GUIDE = {...}` dict (3 hard-coded strings) with:

```python
    DURATION_GUIDE = {preset: duration_guide(word_budget(preset)) for preset in DURATION_SECONDS}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_content_engine.py tests/test_prompt_normalization.py tests/test_script_quality.py -q -p no:cacheprovider`
Expected: `44 passed`

- [ ] **Step 5: Commit**

```bash
git add app/content_engine.py tests/test_content_engine.py tests/test_prompt_normalization.py
git commit -m "feat: retention-structured system prompt, hook_headline and scene_roles fields

Hook / open loop / re-hook / payoff / loop ending, conversational voice, banned openers and
phrases; DURATION lines generated from the word budget; hook_viral_score no longer requested.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Word-budget gate with one revision call

**Files:**
- Modify: `app/content_engine.py` (imports; new `_warning`, `ScriptResult` before `ScriptGeneratorError`; `generate_script` tail at `:281-295` becomes `_request`; new `REVISE_PROMPT`, `revise_length`, `_prepare`, `write_script`)
- Test: `tests/test_script_writer.py` (new)

**Interfaces:**
- Consumes: Task 1 `WordBudget`, `word_budget`, `count_words`, `check_roles`; Task 2 fields and `normalize_prompt_counts`.
- Produces (used by Task 5):
  - `@dataclass ScriptResult(script: ScriptOutput, warnings: list[dict], length: dict)` — warnings are `{"code", "message", "detail"}`; `length` keys: `preset, target_seconds, target_words, word_range, draft_words, words, revision`.
  - `ScriptGenerator.write_script(topic: str, enable_v2: bool = False, video_style: str = "", video_duration: str = "") -> ScriptResult`
  - `ScriptGenerator.revise_length(script, *, topic, words, budget, enable_v2=False, video_style="") -> ScriptOutput` (raises `ScriptGeneratorError`)
  - `generate_script(...)` keeps its signature and contract (one call, validated `ScriptOutput`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_script_writer.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_script_writer.py -q -p no:cacheprovider --tb=line`
Expected: `14 failed`, each `AttributeError: 'ScriptGenerator' object has no attribute 'write_script'`

- [ ] **Step 3: Implement**

In `app/content_engine.py`:

(a) Imports: add `from dataclasses import dataclass` after `import logging`, and change the Task 2 import to

```python
from app.script_quality import DURATION_SECONDS, WordBudget, check_roles, count_words, word_budget
```

(b) Add before `class ScriptGeneratorError` (after `duration_guide`):

```python
def _warning(code: str, message: str, detail: dict) -> dict:
    return {"code": code, "message": message, "detail": detail}


@dataclass
class ScriptResult:
    """write_script output: the script to use, run_report warnings, and run_report.json "script"."""
    script: "ScriptOutput"
    warnings: list
    length: dict
```

(c) In `generate_script`, replace everything from the `system_prompt = self._build_system_prompt(...)` line to the end of the method (the `try:` block with the `generate_json` call, validation and the two `except` clauses) with the block below — the same `system_prompt` line, a call to a new `_request`, and the new methods:

```python
        system_prompt = self._build_system_prompt(enable_v2=enable_v2, video_style=style)
        return self._request(user_prompt, system_prompt, temperature=0.8)

    def _request(self, user_prompt: str, system_prompt: str, temperature: float) -> ScriptOutput:
        """One LLM call -> validated ScriptOutput; every failure becomes ScriptGeneratorError."""
        try:
            data = generate_json(user_prompt, system=system_prompt, temperature=temperature, max_tokens=3000)

            # Validate with Pydantic
            try:
                script = ScriptOutput(**data)
            except ValueError as e:
                raise ScriptGeneratorError(f"Response validation failed: {e}")

            return script

        except ValueError as e:
            raise ScriptGeneratorError(f"Invalid response: {e}")
        except Exception as e:
            raise ScriptGeneratorError(f"Script generation failed: {e}")

    REVISE_PROMPT = """Rewrite this short-form video script about: {topic}

LENGTH PROBLEM: the narration (hook + body) is {words} words. Rewrite it to {target} words (anything from {lo} to {hi} words is fine), about {seconds} seconds spoken. {direction}

Keep the same structure (hook, open loop, body, re-hook, payoff, loop ending) and the same voice rules. Return every JSON field again. image_prompts, scene_roles{v2_lists} must stay one entry per scene, {scene_lo}-{scene_hi} scenes.{v2_join}

IMAGE STYLE: {style_hint}

CURRENT SCRIPT (JSON):
{script_json}"""

    def revise_length(self, script: ScriptOutput, *, topic: str, words: int, budget: WordBudget,
                      enable_v2: bool = False, video_style: str = "") -> ScriptOutput:
        """One revision call with explicit length feedback (spec 2026-10-03 §7). Raises ScriptGeneratorError."""
        style = video_style or settings.video_style
        too_long = words > budget.hi
        user_prompt = self.REVISE_PROMPT.format(
            topic=topic, words=words, target=budget.target, lo=budget.lo, hi=budget.hi, seconds=budget.seconds,
            direction=("Cut filler and merge or drop the weakest scene; keep the specifics." if too_long else
                       "Add concrete specifics (numbers, names, cause and effect), not filler."),
            v2_lists=", motion_prompts, pacing_hints and scene_texts" if enable_v2 else "",
            v2_join=" scene_texts must still join to exactly hook + body." if enable_v2 else "",
            scene_lo=budget.scenes[0], scene_hi=budget.scenes[1],
            style_hint=self.STYLE_GUIDE.get(style, self.STYLE_GUIDE["photorealistic"]),
            script_json=json.dumps(script.model_dump(), ensure_ascii=False, indent=1),
        )
        system_prompt = self._build_system_prompt(enable_v2=enable_v2, video_style=style)
        return self._request(user_prompt, system_prompt, temperature=0.7)

    def _prepare(self, script: ScriptOutput) -> Tuple[ScriptOutput, list]:
        """Normalize prompt counts and scene roles. Returns (script, warnings); never raises."""
        warnings = []
        script, change = normalize_prompt_counts(script)
        if change:
            warnings.append(_warning("prompt_count_normalized",
                                     "LLM returned mismatched prompt counts; normalized before any paid generation",
                                     change))
        roles, reason = check_roles(script.scene_roles, len(script.image_prompts))
        if reason:
            warnings.append(_warning("scene_roles_derived", f"Scene roles replaced by a heuristic ({reason})",
                                     {"reason": reason, "llm_roles": list(script.scene_roles), "roles": roles}))
        if roles != script.scene_roles:
            script = script.model_copy(update={"scene_roles": roles})
        return script, warnings

    def write_script(self, topic: str, enable_v2: bool = False, video_style: str = "",
                     video_duration: str = "") -> "ScriptResult":
        """Draft -> normalize -> roles -> word-budget gate -> at most one revision (spec 2026-10-03 §7).
        Only the first draft can fail the run; the gate and the revision never do."""
        budget = word_budget(video_duration or settings.video_duration)
        script, warnings = self._prepare(self.generate_script(
            topic, enable_v2=enable_v2, video_style=video_style, video_duration=budget.preset))
        words = draft_words = count_words(f"{script.hook} {script.body}")
        revision = "not_needed"
        if not budget.contains(words):
            try:
                revised, revised_warnings = self._prepare(self.revise_length(
                    script, topic=topic, words=words, budget=budget, enable_v2=enable_v2, video_style=video_style))
            except ScriptGeneratorError as e:
                logger.warning("Script length revision failed, keeping the draft: %s", e)
                revision = "failed"
            else:
                revised_words = count_words(f"{revised.hook} {revised.body}")
                if abs(revised_words - budget.target) <= abs(words - budget.target):
                    script, warnings, words, revision = revised, revised_warnings, revised_words, "accepted"
                else:
                    revision = "kept_draft"
        if not budget.contains(words):
            warnings.append(_warning(
                "script_length_off_target",
                f"Narration is {words} words; target {budget.target} ({budget.lo}-{budget.hi}) for {budget.preset}",
                {"words": words, "target": budget.target, "range": [budget.lo, budget.hi], "revision": revision}))
        length = {"preset": budget.preset, "target_seconds": budget.seconds, "target_words": budget.target,
                  "word_range": [budget.lo, budget.hi], "draft_words": draft_words, "words": words,
                  "revision": revision}
        return ScriptResult(script, warnings, length)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_script_writer.py tests/test_content_engine.py tests/test_prompt_normalization.py -q -p no:cacheprovider`
Expected: `32 passed`

- [ ] **Step 5: Commit**

```bash
git add app/content_engine.py tests/test_script_writer.py
git commit -m "feat: word-budget gate with one length-revision call (ScriptGenerator.write_script)

Draft -> normalize -> scene-role check -> budget check -> at most one revision; the closer
script wins; failures of the revision keep the draft and only warn.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Beats in the shot plan — roles, beat transitions, script headline, re-render

**Files:**
- Modify: `app/cin/shot_plan.py:31-33` (constant), `:96-106` (`Scene`), `:171-175` (`from_json`), `:339-355` (`_pick_transitions`), `:358-385` (`build_shot_plan`)
- Modify: `app/cin/caption_groups.py:17-18` (constant), `:128-133` (`make_hook_headline` + new `script_headline_text`)
- Modify: `app/cin/editor.py:221-226` (`rebuild_plan`)
- Modify: `docs/superpowers/specs/2026-10-02-shot-based-editor-design.md` §6.5 and §7 (supersession notes)
- Test: `tests/test_cin_shot_plan.py`, `tests/test_rerender.py`, `tests/test_sfx_library.py`, `tests/test_cin_caption_groups.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks at runtime (roles are plain strings).
- Produces (used by Task 5):
  - `TRANSITION_ROLES = ("rehook", "payoff", "loop")`
  - `Scene.role: Optional[str] = None` (`to_json` writes `"role"` only when not `None`; `from_json` reads `s.get("role")`)
  - `build_shot_plan(alignment, pacing, clip_specs, *, fps=FPS, roles: Optional[list] = None) -> ShotPlan`
  - `HEADLINE_MAX_WORDS = 6`; `script_headline_text(headline: Optional[str]) -> Optional[str]`
  - `make_hook_headline(hook, duration, headline: Optional[str] = None) -> Optional[dict]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cin_shot_plan.py`:

```python


# ------------------------------------------------------------------ script beats (spec 2026-10-03 §8)

def styled(plan):
    return [(s.scene, s.transition_in) for s in plan.shots if s.transition_in != "cut"]


def test_transitions_follow_beat_roles_not_pauses():
    a = _synthetic([0.9, 0.2, 0.6, 0.4])       # pauses alone would pick scenes 1, 3, 4
    roles = ["hook", "open_loop", "rehook", "payoff", "loop"]
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)), roles=roles)
    assert styled(plan) == [(2, "flash"), (3, "zoom_through"), (4, "whip_pan")]
    assert [s.role for s in plan.scenes] == roles


def test_beat_priority_is_rehook_then_payoff_then_loop():
    a = _synthetic([0.3, 0.3, 0.3, 0.3, 0.3])
    roles = ["hook", "rehook", "loop", "rehook", "payoff", "loop"]
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)), roles=roles)
    assert [sc for sc, _ in styled(plan)] == [1, 3, 4]       # both rehooks, then payoff; loops lose


def test_roles_without_beat_scenes_give_no_styled_transitions():
    a = _synthetic([0.9, 0.2, 0.6, 0.4])
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)), roles=["hook"] + ["body"] * 4)
    assert styled(plan) == []                   # roles present: no fallback to pauses


def test_no_roles_keeps_the_pause_heuristic():
    a = _synthetic([0.9, 0.2, 0.6, 0.4])
    for roles in (None, []):
        plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)), roles=roles)
        assert styled(plan) == [(1, "flash"), (3, "zoom_through"), (4, "whip_pan")]
        assert all(s.role is None for s in plan.scenes)


def test_fewer_roles_than_scenes_leave_the_rest_unset():
    a = _synthetic([0.5, 0.5, 0.5, 0.5])
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)), roles=["hook", "rehook"])
    assert [s.role for s in plan.scenes] == ["hook", "rehook", None, None, None]
    assert styled(plan) == [(1, "flash")]


def test_roles_round_trip_and_legacy_plans_load_with_role_none(tmp_path):
    a = _synthetic([0.5, 0.5])
    plan = build_shot_plan(a, "standard", specs_for(plan_segments(a, None)), roles=["hook", "rehook", "loop"])
    plan.save(tmp_path / "shot_plan.json")
    loaded = ShotPlan.load(tmp_path / "shot_plan.json")
    assert [s.role for s in loaded.scenes] == ["hook", "rehook", "loop"]
    legacy = build_shot_plan(a, "standard", specs_for(plan_segments(a, None))).to_json()
    assert all("role" not in s for s in legacy["scenes"])            # old schema, byte-identical
    assert [s.role for s in ShotPlan.from_json(legacy).scenes] == [None, None, None]
```

Append to `tests/test_rerender.py`:

```python


def test_rebuild_plan_keeps_roles_and_beat_transitions(tmp_path):
    job, alignment, specs = build_gold_job(tmp_path)
    plan = build_shot_plan(alignment, "standard", specs, roles=["hook", "loop"])
    plan.save(job.shot_plan)
    new = rebuild_plan(job, "fast")
    assert [s.role for s in new.scenes] == ["hook", "loop"]
    assert [(s.scene, s.transition_in) for s in new.shots if s.transition_in != "cut"] == \
        [(s.scene, s.transition_in) for s in plan.shots if s.transition_in != "cut"]


def test_rebuild_legacy_plan_without_roles_keeps_pause_transitions(tmp_path):
    job, old = saved_job(tmp_path)                       # saved before roles existed: no "role" keys
    assert all("role" not in s for s in json.loads(job.shot_plan.read_text(encoding="utf-8"))["scenes"])
    new = rebuild_plan(job, "standard")
    assert all(s.role is None for s in new.scenes)
    assert [s.transition_in for s in new.shots] == [s.transition_in for s in old.shots]
```

Append to `tests/test_sfx_library.py`:

```python


def test_risers_follow_beat_transitions():
    alignment = fixture_alignment("words_rolex_40s.json")
    specs = [ClipSpec(s.scene, s.index, s.t0, s.t1, s.requested_len, f"sources/images/scene{s.scene:02d}.png")
             for s in plan_segments(alignment, None)]
    roles = ["hook"] + ["body"] * (len(alignment.scenes) - 2) + ["loop"]
    plan = build_shot_plan(alignment, "standard", specs, roles=roles)
    [loop_shot] = [s for s in plan.shots if s.transition_in != "cut"]
    assert loop_shot.scene == len(alignment.scenes) - 1
    risers = [e for e in place_sfx(plan, POOL) if e["kind"] == "riser"]
    assert len(risers) == 1 and abs(risers[0]["t"] + 2.5 - loop_shot.t0) < 0.01   # ends at the transition
```

Append to `tests/test_cin_caption_groups.py`:

```python


def test_script_headline_field_wins_over_the_hook_sentence():
    hook = "This watch costs more than your house."
    assert make_hook_headline(hook, 40.0, headline="$2M FOR A WATCH?") == \
        {"text": "$2M FOR A WATCH?", "t0": 0.0, "t1": 2.5}
    assert make_hook_headline(hook, 40.0, headline="  Worth   more  than a house. ")["text"] == \
        "Worth more than a house"


def test_unusable_script_headline_falls_back_to_the_hook():
    hook = "Gold is heavy."
    assert make_hook_headline(hook, 40.0, headline="")["text"] == "Gold is heavy"
    assert make_hook_headline(hook, 40.0, headline=None)["text"] == "Gold is heavy"
    assert make_hook_headline(hook, 40.0, headline="one two three four five six seven")["text"] == "Gold is heavy"
    assert make_hook_headline("a b c d e f g h i", 40.0, headline="...") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_shot_plan.py tests/test_rerender.py tests/test_sfx_library.py tests/test_cin_caption_groups.py -q -p no:cacheprovider -m "not render" --tb=line`
Expected: 11 failed — `TypeError: build_shot_plan() got an unexpected keyword argument 'roles'` (8), `AttributeError: 'Scene' object has no attribute 'role'` (1), `TypeError: make_hook_headline() got an unexpected keyword argument 'headline'` (2).

- [ ] **Step 3: Implement**

`app/cin/shot_plan.py` — after `TRANSITION_CYCLE = (...)` add:

```python
TRANSITION_ROLES = ("rehook", "payoff", "loop")   # spec 2026-10-03 §8: beat scenes, in priority order
```

Replace the `Scene` dataclass:

```python
@dataclass
class Scene:
    index: int
    t0: float
    t1: float
    text: str
    segments: list = field(default_factory=list)
    role: Optional[str] = None        # script beat (spec 2026-10-03 §8); None in plans made before it

    def to_json(self) -> dict:
        d = {"index": self.index, "t0": round(self.t0, 3), "t1": round(self.t1, 3),
             "text": self.text, "segments": [s.to_json() for s in self.segments]}
        if self.role is not None:     # omitted when unknown, so legacy plans round-trip byte-identical
            d["role"] = self.role
        return d
```

In `ShotPlan.from_json`, replace the `scenes = [...]` expression with:

```python
        scenes = [Scene(s["index"], s["t0"], s["t1"], s["text"],
                        [Segment(g["t0"], g["t1"], g["clip"], g["requested_len"], g["start_image"])
                         for g in s["segments"]], s.get("role")) for s in d["scenes"]]
```

Replace `_pick_transitions`:

```python
def _pick_transitions(alignment: Alignment, shots: list, roles: Optional[dict] = None) -> None:
    """Up to MAX_TRANSITIONS styled scene boundaries. With roles ({scene index: role}), only scenes whose
    role is in TRANSITION_ROLES qualify, in that priority order (spec 2026-10-03 §8); without roles, the
    longest preceding pauses win (spec §6.5). Both need a boundary whose two shots are >= TRANSITION_LEN."""
    toks = alignment.tokens
    first_shot = {}
    for i, s in enumerate(shots):
        first_shot.setdefault(s.scene, i)
    candidates = []
    for sc in alignment.scenes[1:]:
        i = first_shot.get(sc.index)
        if i is None or i == 0 or not (0 < sc.first_token < len(toks)):
            continue
        pause = toks[sc.first_token].t0 - toks[sc.first_token - 1].t1
        a, b = shots[i - 1], shots[i]
        if a.t1 - a.t0 < TRANSITION_LEN or b.t1 - b.t0 < TRANSITION_LEN:
            continue
        if roles:
            role = roles.get(sc.index)
            if role in TRANSITION_ROLES:
                candidates.append((-TRANSITION_ROLES.index(role), -sc.index, i))
        elif pause > 0:
            candidates.append((pause, -sc.index, i))
    chosen = sorted(i for _, _, i in sorted(candidates, reverse=True)[:MAX_TRANSITIONS])
    for n, i in enumerate(chosen):
        shots[i].transition_in = TRANSITION_CYCLE[n % len(TRANSITION_CYCLE)]
```

In `build_shot_plan`, change the signature and first lines to:

```python
def build_shot_plan(alignment: Alignment, pacing: str, clip_specs: list, *, fps: int = FPS,
                    roles: Optional[list] = None) -> ShotPlan:
    """roles: one script beat per scene (ScriptOutput.scene_roles), or None for plans without beats.
    Missing entries (fewer roles than scenes) are None; roles only steer transitions and are saved."""
    if pacing not in PACING:
        raise ValueError(f"Unknown pacing {pacing!r}; choose one of {sorted(PACING)}")
    role_of = {i: r for i, r in enumerate(roles or []) if r}
```

pass the role into each scene:

```python
        scenes.append(Scene(sc.index, sc.t0, sc.t1, sc.text,
                            [Segment(s.t0, s.t1, s.path, s.requested_len, s.start_image) for s in specs],
                            role_of.get(sc.index)))
```

and change `_pick_transitions(alignment, shots)` to `_pick_transitions(alignment, shots, role_of)`.

`app/cin/caption_groups.py` — after `HOOK_SECONDS = 2.5 ...` add:

```python
HEADLINE_MAX_WORDS = 6           # spec 2026-10-03 §8: the script's own hook_headline field
```

and replace `make_hook_headline` with:

```python
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
```

`app/cin/editor.py` `rebuild_plan` — replace

```python
    plan = build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion))
    plan.hook_headline = old.hook_headline        # set from script.hook at generation; not in alignment.json
```

with

```python
    roles = [s.role for s in old.scenes]           # script beats; all None for plans made before them
    plan = build_shot_plan(alignment, pacing, clip_specs_from_plan(old, job, enable_motion),
                           roles=roles if any(roles) else None)
    plan.hook_headline = old.hook_headline        # set from the script at generation; not in alignment.json
```

`docs/superpowers/specs/2026-10-02-shot-based-editor-design.md` — append to §6.5 after "Sub-project 2 will replace this heuristic with script beat markers.":
`*(Amended 2026-10-03: when the script supplies scene_roles, rehook/payoff/loop scenes get the transitions instead; see 2026-10-03-script-upgrades-design.md §8.)*`
and append to the §7 "Hook headline" bullet:
`*(Amended 2026-10-03: the script's hook_headline field (≤ 6 words) is used first; see 2026-10-03-script-upgrades-design.md §8.)*`

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cin_shot_plan.py tests/test_rerender.py tests/test_sfx_library.py tests/test_cin_caption_groups.py tests/test_cin_segments.py -q -p no:cacheprovider -m "not render"`
Expected: all pass, 0 failed (render-marked tests deselected).

- [ ] **Step 5: Commit**

```bash
git add app/cin/shot_plan.py app/cin/caption_groups.py app/cin/editor.py tests/test_cin_shot_plan.py tests/test_rerender.py tests/test_sfx_library.py tests/test_cin_caption_groups.py docs/superpowers/specs/2026-10-02-shot-based-editor-design.md
git commit -m "feat: scene roles in shot_plan.json drive styled transitions; script headline field

rehook > payoff > loop get the (max 3) styled transitions when roles exist; plans without
roles keep the longest-pause rule; --rerender reads roles back from the saved plan.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pipeline and report wiring

**Files:**
- Modify: `app/cin/report.py:18-23` (`WARNING_CODES`), `:26-38` (`RunReport.script`)
- Modify: `app/cin/editor.py:198` (`_CARRIED_WARNINGS`), `:256-259` (`rerender_job` copies `script`)
- Modify: `main.py:16, 30` (imports), new `_record_narration` before `_run_shot_editor` (`:230`), `:263-264` (roles + headline), `:432-448` (script stage, narration timing)
- Test: `tests/test_pipeline.py:44-55` (fixture), `:87` (exact warning list), new tests; `tests/test_rerender.py`, `tests/test_cin_report.py` (append)

**Interfaces:**
- Consumes: Task 3 `ScriptGenerator.write_script -> ScriptResult`; Task 4 `build_shot_plan(..., roles=)`, `make_hook_headline(..., headline=)`, `script_headline_text`.
- Produces: `RunReport.script: dict` (run_report.json `"script"`); `main._record_narration(report: RunReport, seconds: float) -> None`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline.py`, in the `offline` fixture, change the `fake_script` return to also pass roles/headline from `state`:

```python
    def fake_script(self, topic, **kwargs):
        return ScriptOutput(hook=gold["scene_texts"][0], body=gold["scene_texts"][1],
                            image_prompts=["gold bar", "gold cube", "vault", "scale", "hand"],
                            keywords=["gold"], motion_prompts=["slow push", "orbit"],
                            scene_texts=state["scene_texts"], scene_roles=state.get("scene_roles", []),
                            hook_headline=state.get("hook_headline", ""))
```

and replace `monkeypatch.setattr(main.ScriptGenerator, "generate_script", fake_script)` with:

```python
    def no_llm(*args, **kwargs):
        raise AssertionError("LLM call attempted")

    monkeypatch.setattr(main.ScriptGenerator, "generate_script", fake_script)
    monkeypatch.setattr("app.content_engine.generate_json", no_llm)   # the length revision fails -> draft kept
```

In `test_job_folder_and_sources_written`, replace

```python
    assert [w["code"] for w in report["warnings"]] == ["prompt_count_normalized"]   # 5 prompts, 2 scenes
```

with

```python
    assert [w["code"] for w in report["warnings"]] == [
        "prompt_count_normalized",      # 5 prompts, 2 scenes
        "scene_roles_derived",          # the fake script has no scene_roles
        "script_length_off_target",     # 24 words; the revision call fails (no LLM) and the draft is kept
        "hook_headline_fallback",       # the fake script has no hook_headline
    ]
```

Append to `tests/test_pipeline.py`:

```python


def test_report_records_word_budget_and_narration_timing(offline, monkeypatch):
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True, video_duration="short")
    script = report_of(only_job(offline.out))["script"]
    assert script == {"preset": "short", "target_seconds": 30, "target_words": 78, "word_range": [67, 89],
                      "draft_words": 24, "words": 24, "revision": "failed",
                      "narration_seconds": 8.0, "seconds_vs_target": -22.0, "words_per_second": 3.0}


def test_script_roles_and_headline_reach_the_shot_plan(offline, monkeypatch):
    offline.state["scene_roles"] = ["hook", "loop"]
    offline.state["hook_headline"] = "HEAVIER THAN A CAR"
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert [s["role"] for s in plan["scenes"]] == ["hook", "loop"]
    assert plan["hook_headline"]["text"] == "HEAVIER THAN A CAR"
    styled = [s["scene"] for s in plan["shots"] if s["transition_in"] != "cut"]
    assert styled == [1]                                   # the loop scene
    codes = [w["code"] for w in report_of(job)["warnings"]]
    assert "scene_roles_derived" not in codes and "hook_headline_fallback" not in codes


def test_roles_survive_alignment_fallback(offline, monkeypatch):
    offline.state["scene_texts"] = ["Gold is heavy.", "A small cube weighs as much as a car."]   # paraphrased
    offline.state["scene_roles"] = ["hook", "loop"]
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True)
    job = only_job(offline.out)
    assert "alignment_fallback" in [w["code"] for w in report_of(job)["warnings"]]
    plan = json.loads((job / "sources/shot_plan.json").read_text(encoding="utf-8"))
    assert [s["role"] for s in plan["scenes"]] == ["hook", "loop"]
    assert [s["scene"] for s in plan["shots"] if s["transition_in"] != "cut"] == [1]
```

Append to `tests/test_rerender.py`:

```python


def test_rerender_carries_script_section_and_script_warnings(tmp_path, monkeypatch):
    job, _ = saved_job(tmp_path)
    prev = RunReport.load(job.report)
    prev.script = {"preset": "medium", "words": 150, "narration_seconds": 58.1}
    for code in ("script_length_off_target", "scene_roles_derived", "hook_headline_fallback"):
        prev.warn(code, code)
    prev.save(job.report)
    monkeypatch.setattr("app.cin.editor.render_job", lambda *a, **k: job.final)
    rerender_job(job.root, pacing="fast")
    rep = RunReport.load(job.report)
    assert rep.script == {"preset": "medium", "words": 150, "narration_seconds": 58.1}
    assert [w["code"] for w in rep.warnings] == ["script_length_off_target", "scene_roles_derived",
                                                 "hook_headline_fallback"]
```

Append to `tests/test_cin_report.py`:

```python


def test_script_section_round_trips_and_old_reports_load_empty(tmp_path):
    report = RunReport(job="j")
    report.script = {"preset": "medium", "words": 118, "narration_seconds": 46.2}
    path = tmp_path / "run_report.json"
    report.save(path)
    assert RunReport.load(path).script == {"preset": "medium", "words": 118, "narration_seconds": 46.2}
    path.write_text(json.dumps({"job": "old", "status": "ok"}), encoding="utf-8")
    assert RunReport.load(path).script == {}


def test_script_warning_codes_registered():
    from app.cin.report import WARNING_CODES
    assert {"script_length_off_target", "scene_roles_derived", "hook_headline_fallback"} <= set(WARNING_CODES)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_rerender.py tests/test_cin_report.py -q -p no:cacheprovider -m "not render" --tb=line`
Expected: 7 failed — `assert ['prompt_count_normalized'] == [...]`, `KeyError: 'script'`, `KeyError: 'role'` (2), `AttributeError: 'RunReport' object has no attribute 'script'` (2), `WARNING_CODES` subset assertion. No test may hang: if one runs for minutes, an LLM call is unpatched — stop and fix the fixture.

- [ ] **Step 3: Implement**

`app/cin/report.py` — extend `WARNING_CODES` with `"script_length_off_target", "scene_roles_derived", "hook_headline_fallback"` (after `"plan_save_failed"`), and add the field after `clips`:

```python
    script: dict = field(default_factory=dict)  # word budget + narration timing (spec 2026-10-03 §7)
```

`app/cin/editor.py`:

```python
_CARRIED_WARNINGS = ("prompt_count_normalized", "clip_retry",
                     # script-level facts: a rerender reuses the same script (spec 2026-10-03 §8)
                     "script_length_off_target", "scene_roles_derived", "hook_headline_fallback")
```

and in `rerender_job`, after `report.clips = prev.clips` add `report.script = prev.script`.

`main.py`:
- `from app.content_engine import ScriptGenerator` (drop `normalize_prompt_counts`).
- `from app.cin.caption_groups import make_hook_headline, script_headline_text`.
- Add before `_run_shot_editor`:

```python
def _record_narration(report: RunReport, seconds: float) -> None:
    """Actual narration length vs the word budget's target (spec 2026-10-03 §7). Report only, no gate."""
    s = report.script
    s["narration_seconds"] = round(seconds, 2)
    if s.get("target_seconds"):
        s["seconds_vs_target"] = round(seconds - s["target_seconds"], 2)
    if s.get("words") and seconds > 0:
        s["words_per_second"] = round(s["words"] / seconds, 2)
```

- In `_run_shot_editor`, replace the two lines `plan = build_shot_plan(...)` / `plan.hook_headline = make_hook_headline(...)` with:

```python
    plan = build_shot_plan(alignment, options.pacing, specs, roles=script.scene_roles or None)
    plan.hook_headline = make_hook_headline(script.hook, plan.duration, headline=script.hook_headline)
    if script_headline_text(script.hook_headline) is None:
        report.warn("hook_headline_fallback",
                    "Script hook_headline missing or longer than 6 words; "
                    + ("using the hook's first sentence" if plan.hook_headline else "no headline shown"),
                    {"hook_headline": script.hook_headline})
```

- In `run_pipeline`, replace the `script` stage and the `normalize_prompt_counts` block with:

```python
        with report.stage("script"):
            result = ScriptGenerator().write_script(
                topic, enable_v2=enable_motion, video_style=video_style, video_duration=video_duration)
        script = result.script
        report.script = dict(result.length)
        for w in result.warnings:
            report.warn(w["code"], w["message"], w["detail"])
```

  and after `logger.info(f"Audio generated: {audio_result.duration:.1f} seconds")` add `_record_narration(report, audio_result.duration)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_pipeline.py tests/test_rerender.py tests/test_cin_report.py tests/test_cin_editor.py -q -p no:cacheprovider -m "not render"`
Expected: all pass, 0 failed, finishing in well under a minute.

- [ ] **Step 5: Commit**

```bash
git add main.py app/cin/report.py app/cin/editor.py tests/test_pipeline.py tests/test_rerender.py tests/test_cin_report.py
git commit -m "feat: pipeline uses write_script; run_report.json script section; beats reach the plan

Word budget, revision outcome and actual narration seconds are reported; scene roles and the
script headline feed the shot plan; --rerender carries the script section and script warnings.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Image style and mascot fix, duration labels, full-suite check

**Files:**
- Modify: `app/config.py:37-44` (mascot/image_style defaults), `:163` (comment)
- Modify: `app/asset_manager.py:35-55` (`STYLE_SUFFIX`, `__init__`), `:56-68` (`_enhance_prompt_with_style`), `:253-256` (mock mascot text)
- Modify: `app/content_engine.py:180` (mascot guard in `_build_system_prompt`)
- Modify: `main.py` (`AssetManager(video_style=options.video_style)` in `run_pipeline`)
- Modify: `app/web/static/js/generate.js:32-34`
- Test: `tests/test_config.py:62`, `tests/test_asset_manager.py`, `tests/test_content_engine.py`, `tests/test_pipeline.py` (append)

**Interfaces:**
- Consumes: Task 5's `main.run_pipeline` shape.
- Produces: `STYLE_SUFFIX: dict[str, str]`; `AssetManager(video_style: Optional[str] = None)` with attribute `video_style: str`. `generate_images` keeps its signature (tests patch it with a fixed-signature lambda at `tests/test_pipeline.py:123`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_config.py`, replace `    assert s.mascot_enabled is True` with:

```python
    assert s.mascot_enabled is False         # spec 2026-10-03 §9
    assert s.image_style == ""                # "" = derive from video_style
```

Append to `tests/test_asset_manager.py`:

```python


# ------------------------------------------------------------------ style suffix (spec 2026-10-03 §9)

def test_photoreal_prompts_get_photographic_keywords_not_vector_art(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "image_style", "")
    out = AssetManager(video_style="photorealistic")._enhance_prompt_with_style("a gold bar on a scale")
    assert out.startswith("a gold bar on a scale, ") and "photorealistic photograph" in out
    for word in ("vector", "cartoon", "clean lines", "robot"):
        assert word not in out


def test_non_photoreal_prompts_keep_their_own_style(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "image_style", "")
    prompt = "a gold bar on a scale, cartoon style, vibrant colors"
    assert AssetManager(video_style="cartoon")._enhance_prompt_with_style(prompt) == prompt


def test_explicit_image_style_setting_still_overrides(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "image_style", "35mm film grain")
    out = AssetManager(video_style="photorealistic")._enhance_prompt_with_style("a vault door")
    assert out == "a vault door, 35mm film grain"


def test_run_style_defaults_to_the_setting(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "video_style", "anime")
    assert AssetManager().video_style == "anime"
    assert AssetManager(video_style="noir").video_style == "noir"


def test_mock_image_never_mentions_the_mascot_for_photoreal(monkeypatch, tmp_path):
    from PIL import ImageDraw
    from app.config import settings
    monkeypatch.setattr(settings, "mascot_enabled", True)
    drawn = []
    original = ImageDraw.ImageDraw.text
    monkeypatch.setattr(ImageDraw.ImageDraw, "text",
                        lambda self, xy, text, *a, **k: drawn.append(text) or original(self, xy, text, *a, **k))
    AssetManager(video_style="photorealistic").generate_images(["p"], use_mock=True, output_dir=tmp_path / "a")
    assert drawn and not any("MASCOT" in t for t in drawn)
    drawn.clear()
    AssetManager(video_style="cartoon").generate_images(["p"], use_mock=True, output_dir=tmp_path / "b")
    assert any("MASCOT" in t for t in drawn)
```

Append to `tests/test_content_engine.py`:

```python


def test_mascot_never_added_to_photoreal_prompts(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "mascot_enabled", True)
    monkeypatch.setattr(settings, "mascot_prompt", "A cute robot, vector art style")
    gen = ScriptGenerator()
    assert "MASCOT" not in gen._build_system_prompt(video_style="photorealistic")
    assert "A cute robot" in gen._build_system_prompt(video_style="cartoon")
```

Append to `tests/test_pipeline.py`:

```python


def test_run_video_style_reaches_the_image_prompts(offline, monkeypatch):
    seen = []
    original = AssetManager._enhance_prompt_with_style
    monkeypatch.setattr(AssetManager, "_enhance_prompt_with_style",
                        lambda self, prompt: seen.append(self.video_style) or original(self, prompt))
    monkeypatch.setattr(main, "render_job", fake_render)
    main.run_pipeline("Gold facts", use_mock_images=True, video_style="cartoon")
    assert seen and set(seen) == {"cartoon"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_asset_manager.py tests/test_content_engine.py tests/test_pipeline.py -q -p no:cacheprovider -m "not render" --tb=line`
Expected: 8 failed — `assert True is False` (config), `TypeError: AssetManager.__init__() got an unexpected keyword argument 'video_style'` (4), `AttributeError: 'AssetManager' object has no attribute 'video_style'` (2, incl. the pipeline test), `assert 'MASCOT' not in 'You write s...'`.

- [ ] **Step 3: Implement**

`app/config.py` — replace the mascot/image_style block:

```python
    # Mascot settings for visual branding consistency. Never applied to photorealistic runs
    # (spec 2026-10-03 §9): a cartoon robot cannot appear in a photographic scene.
    mascot_enabled: bool = False
    mascot_prompt: str = (
        "A cute, futuristic robot with glowing blue eyes and a cracked screen, "
        "vector art style"
    )
    # Extra style keywords appended to every image prompt. "" = derive from the run's video_style
    # (photorealistic -> photographic keywords; other styles rely on the LLM's style keywords).
    image_style: str = ""
```

and change the `video_duration` comment to `# "short" (~30s, 6-8 scenes) | "medium" (~45s, 9-11) | "long" (~60s, 11-14)`.

`app/asset_manager.py` — before `class AssetManager` add:

```python
# Style keywords appended to image prompts when settings.image_style is "" (spec 2026-10-03 §9).
# Styles not listed get nothing: their keywords come from the script's image prompts.
STYLE_SUFFIX = {
    "photorealistic": "photorealistic photograph, natural light, realistic textures, sharp focus",
}
```

change `__init__` to:

```python
    def __init__(self, video_style: Optional[str] = None):
        self.video_style = video_style or settings.video_style   # the run's style, not just the global default
        self.openai_client = None
```

(rest of `__init__` unchanged), replace `_enhance_prompt_with_style` with:

```python
    def _enhance_prompt_with_style(self, prompt: str) -> str:
        """
        Append consistent style keywords to an image prompt (prevents style drift between scenes).
        settings.image_style wins when set (.env override); otherwise STYLE_SUFFIX[self.video_style].
        """
        style = settings.image_style or STYLE_SUFFIX.get(self.video_style, "")
        if style and style.lower() not in prompt.lower():
            return f"{prompt}, {style}"
        return prompt
```

and in `_generate_mock_image` change `if settings.mascot_enabled:` to
`if settings.mascot_enabled and self.video_style != "photorealistic":`.

`app/content_engine.py` `_build_system_prompt` — change
`if settings.mascot_enabled and settings.mascot_prompt:` to
`if settings.mascot_enabled and settings.mascot_prompt and video_style != "photorealistic":`.

`main.py` `run_pipeline` — `asset_manager = AssetManager()` becomes `asset_manager = AssetManager(video_style=options.video_style)`.

`app/web/static/js/generate.js` — the `DURATIONS` entries become:

```javascript
    { id: 'short',  label: 'Short',  desc: '~30s, 6-8 scenes' },
    { id: 'medium', label: 'Medium', desc: '~45s, 9-11 scenes' },
    { id: 'long',   label: 'Long',   desc: '~60s, 11-14 scenes' },
```

- [ ] **Step 4: Run the touched tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py tests/test_asset_manager.py tests/test_content_engine.py tests/test_pipeline.py -q -p no:cacheprovider -m "not render"`
Expected: all pass, 0 failed.

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --tb=no -rf -p no:cacheprovider --ignore=tests/test_scheduler.py --ignore=tests/test_web_api.py`
Expected: `12 failed, 597 passed` (derived: 539 baseline tests + 70 new; the scratch prototype lacked the untracked `tests/test_trends.py`, so this exact total was not measured) — exactly the baseline failures (4 `test_uploader`, 6 `test_trends`, 1 `test_trend_scout`, 1 `test_local_image_gen`); 70 new tests across Tasks 1–6. Any other failure blocks the commit.

- [ ] **Step 5: Commit**

```bash
git add app/config.py app/asset_manager.py app/content_engine.py main.py app/web/static/js/generate.js tests/test_config.py tests/test_asset_manager.py tests/test_content_engine.py tests/test_pipeline.py
git commit -m "fix: no vector-art suffix or mascot on photorealistic runs; style follows the run

image_style defaults to '' (derived from video_style), mascot_enabled to False, and the mascot
is never added to photorealistic prompts even when .env enables it. Duration labels updated.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (done while writing)

- **Spec coverage:** §4.1 prompt → Task 2; §4.2 fields/roles → Tasks 1–3; §4.3 gate/report → Tasks 1, 3, 5; §4.4 headline/transitions/risers/rerender → Tasks 4–5; §4.5 style/mascot → Task 6; §4.6 hook score → Task 2; UI labels/config comment → Task 6; spec amendments → Task 4.
- **Placeholders:** none; every code step carries its code.
- **Type consistency:** `write_script → ScriptResult(script, warnings, length)` (Task 3) is what `run_pipeline` reads (Task 5); `build_shot_plan(..., roles=)`, `make_hook_headline(..., headline=)`, `script_headline_text` (Task 4) match their Task 5 callers; `AssetManager(video_style=)` (Task 6) matches `main.py`.
- **Prototype:** every code block above was applied to a scratch copy of 1970d87 and run; the scratch full suite showed only the baseline failures that exist in tracked files (the 6 `test_trends` failures live in an untracked file and were absent there).
