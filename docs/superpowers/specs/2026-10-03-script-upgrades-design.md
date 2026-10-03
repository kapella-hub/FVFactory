# Script Upgrades (Retention-Engineered Scripts) — Design Spec

**Date:** 2026-10-03
**Status:** Decisions made by the controller; the user asked us to proceed autonomously. Spec self-reviewed.
**Sub-project:** 2 of 3 in the "top-of-the-line short-form" effort
(1 = shot-based editor, finished on `main`; 3 = quality tiers + new models + cost cap)
**Branch:** `feat/script-upgrades`

## 1. Goal

Make every script hold a viewer to the last second and loop cleanly, and make the editor use the
script's beats instead of guessing. Success means a default run:

- Opens with a hook of 12 words or fewer, opens a loop by about 5 s, re-hooks at 40–60 %, pays the
  loop off, and ends on a line that flows back into the hook.
- Sounds conversational: second person where natural, short sentences, no documentary/TED voice.
- Hits its duration preset's word budget (±15 %) before any money is spent on TTS, images or clips.
- Shows a dedicated on-screen headline during the hook and puts styled transitions on the beats.
- Never mixes cartoon/robot text into photorealistic image prompts.
- Records every script-level fallback in `run_report.json`; none of them fails the run.

## 2. Background (verified in code, 2026-10-03, `feat/script-upgrades` @ 1970d87)

| Area | Today | File |
|---|---|---|
| Tone | "sophisticated and knowledgeable … like a documentary narrator or a TED talk" | `app/content_engine.py:113-115` |
| Structure | Only "a catchy opening line for the first 3 seconds"; no open loop, re-hook, payoff or loop ending | `app/content_engine.py:108` |
| Own example | V2 `scene_texts` example opens with "Did you know…" (a banned opener) | `app/content_engine.py:145` |
| Length | 30–90 s free choice; presets 30–45 / 45–75 / 75–90 s, 5–7 / 8–10 / 11–14 scenes; no check | `app/content_engine.py:109-110, 191-195` |
| Hook score | `hook_viral_score` requested every run; no consumer outside `content_engine` and its tests | `app/content_engine.py:43, 134` |
| Headline | First hook sentence if ≤ 8 words, else none | `app/cin/caption_groups.py:17, 115-133`, `main.py:264` |
| Transitions | Up to 3, at the longest preceding pauses | `app/cin/shot_plan.py:339-355` |
| Risers | One per styled transition, keyed on `shot.transition_in` | `app/cin/sfx_library.py:78-84` |
| Re-render | `rebuild_plan` re-runs `build_shot_plan`, so transitions are recomputed | `app/cin/editor.py:221-233` |
| Carried warnings | Re-render keeps only `prompt_count_normalized`, `clip_retry` | `app/cin/editor.py:198` |
| Image style | `image_style` default `"vector art style, vibrant colors, clean lines"` appended to photoreal prompts; reads the global `settings.video_style`, not the run's style | `app/config.py:44`, `app/asset_manager.py:56-68` |
| Mascot | `mascot_enabled=True`; a "cute … robot, vector art style" is required in **every** image prompt via the system prompt, regardless of style; mock images print it too | `app/config.py:38-42`, `app/content_engine.py:180-184`, `app/asset_manager.py:253-256` |
| `.env` | Sets `MASCOT_ENABLED` (value not inspected) — a new default alone will not reach this install | `.env` |
| LLM | `generate_json` → `claude_cli` subprocess by default (OpenAI fallback) | `app/llm.py:188-229`, `app/config.py:147` |
| UI labels | Medium "~60s, 8-10 scenes", Long "~90s, 11-14 scenes" | `app/web/static/js/generate.js:32-34` |

The shot-based editor spec (2026-10-02) defers exactly this work: §3 (hook/open loop/re-hook/loop
ending, tone, WPM gate, dedicated `hook_headline`), §6.5 (longest-pause transitions "until
sub-project 2 replaces it with script beat markers") and §7 (headline "sub-project 2 adds a
dedicated field").

## 3. Scope

**In:** system prompt rewrite; `hook_headline` and `scene_roles` fields; word-budget gate with one
revision call; narration timing in the report; beats driving the headline, transitions (and so
risers) and saved in `shot_plan.json`; image-style/mascot fix; UI duration labels.

**Out:** tiers, new models, cost estimate/cap (sub-project 3); hook-variant selection; any paid run.

## 4. Decisions

Each was decided by the controller; rationale recorded here.

1. **Retention structure in the prompt.** HOOK (≤ 12 words, ≈ 2 s; contradiction, specific number
   or stakes; banned openers) → OPEN LOOP by ≈ 5 s → BODY of concrete specifics, one idea per scene →
   RE-HOOK at 40–60 % → PAYOFF closing the loop → LOOP ENDING flowing back into the hook. Tone is
   conversational, second person where natural, ≤ 14 words per sentence on average, plain words, no
   filler, short banned-phrase list. All existing image-prompt rules stay verbatim.
   *Why:* the first 2 s decide the swipe; an open loop and a mid-video re-hook are the cheapest
   retention levers; a loop ending turns completions into replays.
2. **New fields `hook_headline` and `scene_roles`.** Defaults `""` and `[]` (old scripts and fakes
   still validate). `normalize_prompt_counts` keeps `scene_roles` aligned. If roles are missing or
   invalid they are derived (first `hook`, last `loop`, `body` between) with a warning; never a failure.
   *Why:* the editor needs machine-readable beats; a headline that repeats the voice-over wastes the
   top band.
3. **Word-budget gate before TTS.** short 30 s, medium 45 s (new default sweet spot), long 60 s at
   2.6 words/s; accept ±15 %; one revision call with explicit feedback; if still outside, proceed
   with a `script_length_off_target` warning. After TTS, report actual narration seconds vs target
   (no gate). Scene counts: short 6–8, medium 9–11, long 11–14 (keeps average scene ≤ 5.5 s so one fixed 6 s Hailuo clip covers it).
   *Why:* TTS, images and clips are all paid per second or per scene; checking a word count is free.
4. **Beats used downstream.** (a) The script's `hook_headline` feeds `shot_plan.hook_headline`;
   `make_hook_headline`'s first-sentence heuristic is the fallback. (b) Up to 3 styled transitions go
   to scenes whose role is `rehook`, `payoff`, `loop`, in that priority; without roles, the
   longest-pause heuristic stays. Risers follow because they key on `transition_in`.
   (c) Roles are saved as an optional `role` key on `shot_plan.json` scenes and survive `--rerender`.
5. **Image-style conflict fixed.** The style suffix derives from the run's `video_style`
   (photorealistic → photographic keywords; other styles keep their own LLM-written keywords);
   `image_style` default becomes `""`; `mascot_enabled` default becomes `False`; the mascot is never
   added for photorealistic runs, whatever `.env` says. `.env` overrides keep working.
6. **Hook variants.** Keep `hook_variants` (still requested) and `hook_viral_score` (default 0) on
   `ScriptOutput`; stop requesting the score; no selection logic. Grep found no consumer outside
   `app/content_engine.py` and `tests/test_content_engine.py` (`src/` is untracked, stale code that
   imports symbols `app.config` does not define), so the fields stay only for backward compatibility.

## 5. Data model

### 5.1 `ScriptOutput` (`app/content_engine.py`)

```python
hook_headline: str = Field(default="", description="<= 6 punchy words for the top band; not the hook sentence")
scene_roles: List[str] = Field(default=[], description="One per scene: hook|open_loop|body|rehook|payoff|loop")
```

`hook` description changes to "First spoken sentence: <= 12 words, ~2 seconds". Nothing else changes.

### 5.2 Roles (`app/script_quality.py`, new, pure)

- `SCENE_ROLES = ("hook", "open_loop", "body", "rehook", "payoff", "loop")`.
- `canonical_role(value)`: lower-case, runs of spaces/hyphens → `_`, aliases
  `re_hook→rehook`, `openloop→open_loop`, `loop_ending→loop`, `loopback→loop`; anything else → `None`.
- `check_roles(roles, n) -> (roles, reason)`: valid iff exactly `n` entries, all canonical, first is
  `hook`. Valid → canonicalized roles, `reason=None` (casing variants are accepted silently).
  Invalid → `derived_roles(n)` and a reason string. `derived_roles(1) == ["hook"]`,
  `derived_roles(n) == ["hook"] + ["body"] * (n - 2) + ["loop"]`.
- `loop` last is requested by the prompt but not validated (decision 2 validates only the first role).

### 5.3 Prompt-count normalization

`normalize_prompt_counts` gains `scene_roles`, with the same rules as `pacing_hints` plus the
`scene_texts` merge rule: empty stays empty; shorter is padded with `"body"`; longer keeps the
first `n - 1` and the **last** role (the merged last scene keeps the loop). `_prompt_counts` reports
`scene_roles`, so a padded or merged list raises `prompt_count_normalized`.

### 5.4 `shot_plan.json` (contract of spec 2026-10-02 §6.6)

`scenes[i].role`: optional string. Written only when known, so plans made before this change
round-trip byte-identical; `ShotPlan.from_json` reads `s.get("role")` (legacy → `None`).
`version` stays 1.

### 5.5 `run_report.json`

New top-level `script` object (default `{}`; old reports load with `{}`):

```json
"script": {"preset": "medium", "target_seconds": 45, "target_words": 117, "word_range": [100, 134],
           "draft_words": 162, "words": 121, "revision": "accepted",
           "narration_seconds": 46.8, "seconds_vs_target": 1.8, "words_per_second": 2.59}
```

`revision` ∈ `not_needed` | `accepted` | `kept_draft` | `failed`. New warning codes (added to
`WARNING_CODES`): `script_length_off_target`, `scene_roles_derived`, `hook_headline_fallback`.

## 6. System prompt (full text)

`BASE_SYSTEM_PROMPT` becomes the text below. The "CRITICAL IMAGE PROMPT RULES" block is the current
text, unchanged; its first and fifth bullets must stay byte-identical because
`_build_system_prompt` `.replace()`s them for non-photoreal styles (`app/content_engine.py:172-178`).

```text
You write scripts for short vertical videos (TikTok, YouTube Shorts, Reels).
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
[current block, app/content_engine.py:117-128, unchanged]
```

`V2_INSTRUCTION` changes: the `hook_viral_score` line is removed; `hook_variants` reads "3
alternative hook options (list of strings), each following the HOOK rules"; `scene_texts` adds "the
first segment starts with the hook" and its example becomes `["The ocean floor is darker than outer
space.", "We have mapped less than a quarter of it...", "And the deepest point..."]`. Everything else
is unchanged. `hook_headline` and `scene_roles` live in the base prompt, so they are requested even
with `--no-motion` (which turns V2 off).

**Mascot:** `MASCOT_INSTRUCTION` is appended only when `settings.mascot_enabled and
settings.mascot_prompt and video_style != "photorealistic"`.

**DURATION line:** generated from the budget (§7) so prompt and gate cannot drift:
`"{PRESET}: about {seconds} seconds of narration. hook + body together must be {target} words
(anything from {lo} to {hi} words is fine). Use {a}-{b} scenes, one idea per scene."`

## 7. Word-budget gate

`app/script_quality.py`:

| Preset | Target s | Target words (`round(s × 2.6)`) | Accepted (`ceil(0.85 t)`–`floor(1.15 t)`) | Scenes |
|---|---|---|---|---|
| short | 30 | 78 | 67–89 | 6–8 |
| medium (default) | 45 | 117 | 100–134 | 9–11 |
| long | 60 | 156 | 133–179 | 11–14 |

Unknown or empty presets use medium. `count_words(text)` counts whitespace tokens containing at
least one letter or digit (a lone "—" is not a word; "$1,000,000" is one). The counted text is
`f"{hook} {body}"`, the exact string sent to TTS (`main.py:446`).

`ScriptGenerator.write_script(topic, enable_v2, video_style, video_duration) -> ScriptResult(script,
warnings, length)`:

1. `budget = word_budget(video_duration or settings.video_duration)`.
2. Draft = `generate_script(...)` (the existing single LLM call, unchanged contract; its failure
   still fails the run). Prepare it: `normalize_prompt_counts`, then `check_roles`; collect
   `prompt_count_normalized` / `scene_roles_derived` warnings.
3. `words = count_words(hook + " " + body)`. In range → done (`revision="not_needed"`).
4. Out of range → one `revise_length` call: same system prompt, user prompt `REVISE_PROMPT` with the
   topic, current count, target and range, seconds, a direction ("Cut filler and merge or drop the
   weakest scene; keep the specifics." when long, "Add concrete specifics (numbers, names, cause and
   effect), not filler." when short), the per-scene list rule and scene range, the style hint and the
   current script as JSON. Temperature 0.7.
5. Revision raises (`ScriptGeneratorError`, which wraps LLM errors and invalid JSON) → keep the
   draft, `revision="failed"`. Otherwise prepare it and keep whichever of draft/revision is closer to
   the target (tie → revision): `accepted` or `kept_draft`. Warnings are those of the script kept.
6. Still out of range → `script_length_off_target` warning
   (`detail: {words, target, range, revision}`).
7. `length` = the `script` report object minus the narration keys.

`main.run_pipeline` calls `write_script` inside the `script` stage (replacing `generate_script` +
`normalize_prompt_counts`), copies `length` into `report.script`, reports the warnings, and after
TTS adds `narration_seconds`, `seconds_vs_target` and `words_per_second`. There is never a second
revision and never a post-TTS gate.

## 8. Downstream wiring

- **Headline.** `make_hook_headline(hook, duration, headline=None)`: the script's headline if, after
  collapsing whitespace and stripping a trailing `.`/`…`, it has 1–6 words
  (`script_headline_text`, `HEADLINE_MAX_WORDS = 6`); else the existing first-sentence rule
  (≤ 8 words); else `None`. Window unchanged (`[0, min(2.5, duration)]`). When the script's headline
  is unusable, `_run_shot_editor` records `hook_headline_fallback` (detail: the raw field). Whether
  the headline copies the hook is a prompt rule only; it is not validated.
- **Transitions.** `build_shot_plan(alignment, pacing, clip_specs, *, fps=FPS, roles=None)`. Scene
  `i` gets `roles[i]` (missing entries → `None`). `_pick_transitions` keeps its eligibility rule
  (not scene 0; both shots at the boundary ≥ 0.3 s). With any role present, candidates are only
  scenes whose role is in `TRANSITION_ROLES = ("rehook", "payoff", "loop")`, ordered by that
  priority then scene index, top 3; **no** pause fallback fills unused slots. With no roles
  (`None` or `[]`), the longest-pause rule is unchanged. Transition names still cycle
  flash → zoom_through → whip_pan in time order. With derived roles only the loop boundary is
  styled; that degradation is visible through `scene_roles_derived`.
- **Risers.** No code change: `place_sfx` already puts one riser before every non-cut shot.
- **Re-render.** `rebuild_plan` passes `roles=[s.role for s in old.scenes]` when any is set, so
  `--rerender` keeps the same styled boundaries; legacy plans (all `None`) keep the pause rule.
  `rerender_job` copies `prev.script` and carries the three new warning codes (the script does not
  change on a re-render).
- **Classic editor** (`--classic`, personas): gets the gated script; ignores roles and headline.

## 9. Image style and mascot

- `app/config.py`: `mascot_enabled: bool = False`; `image_style: str = ""` ("" = derive);
  `video_duration` comment updated to the new presets.
- `app/asset_manager.py`: `STYLE_SUFFIX = {"photorealistic": "photorealistic photograph, natural
  light, realistic textures, sharp focus"}`. `AssetManager(video_style=None)` stores
  `self.video_style = video_style or settings.video_style`. `_enhance_prompt_with_style` appends
  `settings.image_style or STYLE_SUFFIX.get(self.video_style, "")` when non-empty and not already in
  the prompt. Mock images print the mascot line only when enabled **and** not photorealistic.
- `main.run_pipeline`: `AssetManager(video_style=options.video_style)`. The style is threaded
  through the constructor, not a `generate_images` keyword, because `tests/test_pipeline.py:123`
  patches `generate_images` with a fixed signature.
- `app/web/static/js/generate.js`: Medium "~45s, 9-11 scenes", Long "~60s, 11-14 scenes".
- Effect for this install: `.env` sets `MASCOT_ENABLED`, so the style guard in
  `_build_system_prompt` and the mock-image check carry the fix, not the new default.

## 10. Failure semantics

| Condition | Behaviour | Report |
|---|---|---|
| First draft LLM call fails / invalid JSON | Run fails (unchanged) | `status: failed` |
| Draft off budget, revision fails or is invalid | Draft kept, run continues | `script_length_off_target` (`revision: failed`) |
| Revision further from target than the draft | Draft kept | `script_length_off_target` (`kept_draft`) if still off |
| Still off budget after revision | Proceed | `script_length_off_target` |
| Roles missing / wrong count / unknown / first ≠ hook | Derived roles | `scene_roles_derived` |
| Roles list longer/shorter than scenes | Merged/padded | `prompt_count_normalized` |
| `hook_headline` empty or > 6 words | First-sentence fallback or none | `hook_headline_fallback` |
| Narration far from target after TTS | Proceed | numbers in `script` only |
| Legacy `shot_plan.json` without roles | Pause heuristic | — |

## 11. Testing (all offline; the LLM is a fake)

- `tests/test_script_quality.py`: budget table, unknown preset, word counting, role canonicalization,
  derivation, each invalid-role reason.
- `tests/test_script_writer.py`: a `FakeLLM` replacing `app.content_engine.generate_json` returns
  queued responses and records prompts: on-target draft (1 call); too long → revised (2 calls,
  feedback text asserted); too short direction; still off → warning; revision further → draft kept;
  revision raises / invalid JSON → draft kept, no exception; first draft failure raises; short
  preset; unknown preset; bad, missing and mixed-case roles; warnings belong to the kept script.
- Prompt tests: new fields and structure present, old tone gone, cartoon replacement still fires,
  DURATION lines match the budget, no `hook_viral_score`, no mascot for photoreal.
- Shot plan: role transitions and priority, roles without beats → none, no roles → pause rule,
  partial roles, role round-trip and legacy load; `rebuild_plan` keeps roles and transitions;
  legacy plan rerender keeps pause transitions; riser lands on the beat transition.
- Pipeline (`tests/test_pipeline.py`): the `offline` fixture also replaces
  `app.content_engine.generate_json` with a raiser (an unpatched revision would start the
  `claude` CLI subprocess, which the `requests` patch does not catch); exact warning list updated;
  `script` report section; roles and headline reach `shot_plan.json`; run style reaches image prompts.
- Report/rerender: `script` round-trip and legacy load; new codes registered; rerender carries
  `script` and the script warnings.
- No paid end-to-end run in this sub-project.

## 12. Risks

- **Clip count with Hailuo.** Medium 45 s over 9–11 scenes averages 5.0–6.4 s per scene. Hailuo
  clips are fixed at 6 s (`app/motion_gen.py:28`) and a segment needs scene + 0.5 s
  (`app/cin/shot_plan.py:27`), so scenes over 5.5 s become two chained clips (≈ $0.50 each). Long
  (60 s / 11–14 scenes, 5.0–6.7 s) has the same issue. Kling (5/10 s) does not. The run report's clip
  count shows the effect; sub-project 3's variable-length models remove it. Raising scene counts
  (e.g. medium 8–10) is the lever if the first runs show many chained clips.
- **2.6 words/s is an estimate** for ElevenLabs Multilingual v2. `words_per_second` in the report is
  the calibration data; change `WORDS_PER_SECOND` after a few real runs.
- **Prompt compliance.** The LLM may ignore the loop-ending or headline rules; only the hook role,
  word count and headline length are machine-checked.

## 13. Amendments to the shot-based editor spec

§6.5 ("Boundaries are chosen by the longest preceding pause") and §7 ("Hook headline … sub-project 2
adds a dedicated field") are superseded by §8 of this spec when the script supplies roles/headline.
