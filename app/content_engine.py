"""
Content Engine - Script and concept generation
Uses Claude CLI (via app.llm) with OpenAI API fallback.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.llm import generate_json
from app.script_quality import (DURATION_SECONDS, WORDS_PER_SECOND, WordBudget, canonical_role, check_roles,
                                count_words, word_budget)
from app.story import DEFAULT_STORY_MODE, check_story, default_title, scene_count, split_scenes

logger = logging.getLogger(__name__)


class ScriptOutput(BaseModel):
    """Validated output model for generated scripts"""

    hook: str = Field(
        ...,
        description="First spoken sentence: <= 12 words, ~2 seconds"
    )
    body: str = Field(
        ...,
        description="Main content; length follows the duration word budget (app.script_quality.word_budget)"
    )
    image_prompts: List[str] = Field(
        ...,
        min_length=5,
        max_length=20,
        description="One distinct, highly visual description per scene (6-14 scenes depending on duration; see SCENE_RANGE)"
    )
    keywords: List[str] = Field(
        ...,
        min_length=1,
        description="Keywords for metadata and discoverability"
    )

    # V2 fields (optional, backward compatible)
    hook_variants: List[str] = Field(default=[], description="3 alternative hook options")
    hook_viral_score: int = Field(default=0, description="1-10 scroll-stopping score for the hook")
    motion_prompts: List[str] = Field(default=[], description="Subject-action motion descriptions (what moves and how), one per image_prompt")
    pacing_hints: List[str] = Field(default=[], description="Pacing values, one per image_prompt")
    scene_texts: List[str] = Field(default=[], description="Narration text segments, one per image_prompt")
    emoji_subtitles: List[str] = Field(default=[], description="Key phrases with contextual emojis for subtitles")

    # Retention fields (spec 2026-10-03, optional, backward compatible)
    hook_headline: str = Field(default="", description="<= 6 punchy words for the top band; not the hook sentence")
    scene_roles: List[str] = Field(default=[], description="One per scene: hook|open_loop|body|rehook|payoff|loop")

    @field_validator("scene_roles", "hook_variants", mode="before")
    @classmethod
    def _coerce_list_fields(cls, v):
        """LLMs return null or a bare string for optional lists; never fail the run for that (spec §4.2)."""
        if not isinstance(v, list):
            return []
        return [x if isinstance(x, str) else str(x) for x in v if x is not None]

    @field_validator("hook_headline", mode="before")
    @classmethod
    def _coerce_headline(cls, v):
        return v if isinstance(v, str) else ""

    @field_validator("image_prompts")
    @classmethod
    def validate_image_prompts_count(cls, v: List[str]) -> List[str]:
        if len(v) < 5 or len(v) > 20:
            raise ValueError("Between 5 and 20 image prompts are required")
        return v


GENERIC_MOTION_PROMPT = "the main subject moves with clear, natural motion while the camera pushes in"


def _prompt_counts(script: "ScriptOutput") -> dict:
    return {"image_prompts": len(script.image_prompts), "motion_prompts": len(script.motion_prompts),
            "scene_texts": len(script.scene_texts), "pacing_hints": len(script.pacing_hints),
            "scene_roles": len(script.scene_roles)}


def normalize_prompt_counts(script: "ScriptOutput") -> Tuple["ScriptOutput", Optional[dict]]:
    """Make image_prompts / motion_prompts / scene_texts / pacing_hints / scene_roles the same length (spec §10; scene_roles: spec 2026-10-03 §5.3).

    Runs right after the LLM call, before any paid generation. The scene count is the number of
    image prompts, or fewer scene_texts if the LLM returned fewer. Extra scene_texts are merged into
    the last scene (not dropped) so the scenes still join back to the narration for alignment.
    Missing motion prompts get GENERIC_MOTION_PROMPT. scene_roles, when present, are padded with "body" or
    merged like scene_texts (the merged last scene keeps the last role); validity is checked later by
    app.script_quality.check_roles. model_copy(update=...) skips validation on
    purpose: truncating to fewer than five scenes is allowed here.
    Returns (script, None) when nothing changed, else (new_script, {"before", "after"}).
    """
    n = len(script.image_prompts)
    if script.scene_texts:
        n = min(n, len(script.scene_texts))
    scenes = list(script.scene_texts)
    if len(scenes) > n:
        scenes = scenes[:n - 1] + [" ".join(scenes[n - 1:])]
    motion = list(script.motion_prompts[:n])
    motion += [GENERIC_MOTION_PROMPT] * (n - len(motion))
    hints = list(script.pacing_hints)
    if hints:
        hints = hints[:n] + ["normal"] * max(0, n - len(hints))
    roles = list(script.scene_roles)
    if len(roles) > n:      # same merge rule as scene_texts: the merged last scene keeps the last role
        roles = roles[:max(n - 1, 0)] + roles[-1:] if n else []
    elif roles:
        pad = ["body"] * (n - len(roles))
        if canonical_role(roles[-1]) == "loop":     # keep the loop scene last
            roles = roles[:-1] + pad + roles[-1:]
        else:
            roles += pad
    new = script.model_copy(update={"image_prompts": list(script.image_prompts[:n]),
                                    "motion_prompts": motion, "scene_texts": scenes,
                                    "pacing_hints": hints, "scene_roles": roles})
    before, after = _prompt_counts(script), _prompt_counts(new)
    if before == after:
        return script, None
    logger.warning("Normalized prompt counts %s -> %s", before, after)
    return new, {"before": before, "after": after}


def duration_guide(budget: WordBudget) -> str:
    """The DURATION line of the user prompt, generated from the word budget so the two never drift."""
    return (f"{budget.preset.upper()}: about {budget.seconds} seconds of narration. hook + body together must be "
            f"{budget.target} words (anything from {budget.lo} to {budget.hi} words is fine). "
            f"Use {budget.scenes[0]}-{budget.scenes[1]} scenes, one idea per scene.")


def _warning(code: str, message: str, detail: dict) -> dict:
    return {"code": code, "message": message, "detail": detail}


@dataclass
class ScriptResult:
    """write_script output: the script to use, run_report warnings, and run_report.json "script"."""
    script: "ScriptOutput"
    warnings: list
    length: dict


class ScriptGeneratorError(Exception):
    """Base exception for script generation errors"""
    pass


class ScriptGenerator:
    """Generates viral TikTok/Shorts scripts using OpenAI GPT-4o"""

    _SCRIPT_HEAD = """You write scripts for short vertical videos (TikTok, YouTube Shorts, Reels).
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

"""

    IMAGE_RULES = """CRITICAL IMAGE PROMPT RULES:
- Every image prompt MUST describe a photorealistic scene. NO cartoons, illustrations, vector art, or anime.
- All prompts must share the SAME visual style: cinematic, realistic, natural lighting, muted tones.
- Describe real-world scenes, objects, and environments. Think National Geographic or documentary footage.
- Include specific details: lighting direction, camera angle, environment, textures.
- NEVER use words like "cartoon", "illustration", "vector", "animated", "cute character", or "art style".
- NEVER reference specific named people, celebrities, actors, or public figures in image prompts. AI image generators CANNOT render recognizable people — the result will be random strangers and look wrong. Instead, describe the CONCEPT, SCENE, or OBJECT. Example: instead of "Tom Holland and Zendaya on a red carpet", write "a superhero in a red and blue suit swinging between skyscrapers at night". Instead of "Marcus Aurelius writing", write "an ancient Roman emperor in golden armor writing at a marble desk by candlelight".
- CRITICAL: First write "scene_texts" to split the narration into segments. Then write EACH image_prompt to directly visualize the EXACT content of its corresponding scene_text. If scene_text[2] says "the Mariana Trench is deeper than Mount Everest", image_prompt[2] MUST show the Mariana Trench — NOT a generic ocean scene.
- Think of each image as a frame from a documentary. A viewer watching the video on mute should be able to understand the topic from the visuals alone.
- Be extremely specific and literal. If the narration mentions "a blue whale", show a blue whale. If it mentions "coral reef", show a coral reef. Never use abstract or symbolic imagery.
- Focus on OBJECTS, PLACES, CONCEPTS, and ACTIONS — not people's faces. Wide shots, aerial views, close-ups of objects, environments, and symbolic imagery work best.
Each image prompt should be detailed enough for an AI to generate a compelling photorealistic visual."""

    BASE_SYSTEM_PROMPT = _SCRIPT_HEAD + IMAGE_RULES

    _V2_HEAD = """

ADDITIONAL REQUIRED FIELDS:
- "hook_variants": 3 alternative hook options (list of strings), each following the HOOK rules
"""

    MOTION_RULES = """- "motion_prompts": One motion description per image prompt (same count as image_prompts).
  Each MUST name the main subject's visible physical action: what moves and how it moves.
  You may add ONE camera move after the action. The clip must clearly move from start to finish.
  NEVER write a static shot, a camera move over a still subject, or "subtle", "slight" or parallax-only motion.
  Examples: "rust flakes crumble off the chain as it swings",
  "waves roll over the scattered coins, sand swirls", "molten gold pours into a mold and splashes, camera pushes in"
"""

    _V2_TAIL = """- "pacing_hints": One pacing value per scene (same count as image_prompts). Use: "fast" for exciting moments,
  "normal" for standard pacing, "slow" for emotional moments, "dramatic_pause" for reveals.
- "scene_texts": Split the full narration (hook + body) into segments, one per image prompt.
  Each segment is the EXACT text that should be spoken while that scene's image is shown.
  The segments must join together to form the complete narration (hook + body); the first segment starts with the hook.
  This is CRITICAL for syncing visuals to narration. Example for 3 scenes:
  ["The ocean floor is darker than outer space.", "We have mapped less than a quarter of it...", "And the deepest point..."]
- "emoji_subtitles": 3-5 key phrases from the script with contextual emojis added.
  Example: "Bitcoin crashed 📉😱", "Scientists discovered 🔬🧬"
"""

    V2_INSTRUCTION = _V2_HEAD + MOTION_RULES + _V2_TAIL

    MASCOT_INSTRUCTION = """

IMPORTANT - MASCOT CHARACTER REQUIREMENT:
Every image prompt MUST prominently feature the following character: {mascot_prompt}

The character should be:
- Performing an action directly related to the scene/topic
- Showing appropriate emotions (excited, surprised, thoughtful, etc.)
- The main focus of each image

Example: If discussing "Bitcoin crashed", the prompt should be:
"{mascot_prompt}, looking at a red stock chart crashing down with a panic expression"

DO NOT just mention the character - describe what they are DOING in each scene."""

    def _build_system_prompt(self, enable_v2: bool = False, video_style: str = "photorealistic") -> str:
        """Build the system prompt, optionally including mascot instructions."""
        prompt = self._styled(self.BASE_SYSTEM_PROMPT, video_style)
        if enable_v2:
            prompt += self.V2_INSTRUCTION
        return prompt

    def _styled(self, prompt: str, video_style: str) -> str:
        """Apply the video style to the image rules inside `prompt`, and append the mascot section."""
        # Override the photorealistic-only rule for non-photorealistic styles
        if video_style != "photorealistic" and video_style in self.STYLE_GUIDE:
            style_label = video_style.replace("_", " ").upper()
            prompt = prompt.replace(
                "Every image prompt MUST describe a photorealistic scene. NO cartoons, illustrations, vector art, or anime.",
                f"Every image prompt MUST describe a {style_label} style scene."
            ).replace(
                'NEVER use words like "cartoon", "illustration", "vector", "animated", "cute character", or "art style".',
                f"ALWAYS use style-specific keywords for {style_label} in every image prompt."
            )

        if settings.mascot_enabled and settings.mascot_prompt and video_style != "photorealistic":
            mascot_section = self.MASCOT_INSTRUCTION.format(
                mascot_prompt=settings.mascot_prompt
            )
            prompt += mascot_section

        return prompt

    DURATION_GUIDE = {preset: duration_guide(word_budget(preset)) for preset in DURATION_SECONDS}

    STYLE_GUIDE = {
        "photorealistic": (
            "Every image prompt MUST describe a photorealistic scene. NO cartoons, illustrations, or anime. "
            "Cinematic, realistic, natural lighting, muted tones. Think National Geographic or documentary."
        ),
        "cartoon": (
            "Every image prompt MUST describe a colorful CARTOON scene. Use bold outlines, bright saturated colors, "
            "exaggerated proportions, playful composition. Think Pixar or modern animated explainer videos. "
            "Include words like 'cartoon style', '3D animated', 'vibrant colors', 'fun exaggerated' in every prompt."
        ),
        "anime": (
            "Every image prompt MUST describe an ANIME style scene. Use Japanese animation aesthetics — "
            "large expressive eyes, dynamic action lines, dramatic lighting, cel-shaded colors, detailed backgrounds. "
            "Think Studio Ghibli or Makoto Shinkai. Include 'anime style', 'cel-shaded', 'Japanese animation' in every prompt."
        ),
        "stop_motion": (
            "Every image prompt MUST describe a STOP-MOTION ANIMATION style scene. Miniature handcrafted look — "
            "clay figures, felt textures, wooden props, visible fingerprints on clay, tiny detailed sets. "
            "Think Aardman (Wallace & Gromit) or Laika studios. Include 'stop motion', 'claymation', 'miniature set' in every prompt."
        ),
        "pixel_art": (
            "Every image prompt MUST describe a PIXEL ART style scene. Retro 16-bit or 32-bit aesthetic — "
            "chunky pixels, limited color palette, dithering effects, nostalgic video game look. "
            "Include 'pixel art', 'retro 16-bit', '8-bit style', 'video game aesthetic' in every prompt."
        ),
        "comic_book": (
            "Every image prompt MUST describe a COMIC BOOK style scene. Bold ink outlines, halftone dots, "
            "dramatic shadows, speech-bubble-ready compositions, dynamic panel-like framing. "
            "Think Marvel/DC comics or graphic novels. Include 'comic book style', 'ink outlines', 'halftone dots' in every prompt."
        ),
        "watercolor": (
            "Every image prompt MUST describe a WATERCOLOR PAINTING style scene. Soft translucent washes, "
            "bleeding edges, visible paper texture, delicate brushwork, pastel and muted tones. "
            "Include 'watercolor painting', 'soft washes', 'paper texture', 'delicate brushwork' in every prompt."
        ),
        "3d_render": (
            "Every image prompt MUST describe a 3D RENDERED scene. Clean CGI look — smooth surfaces, "
            "volumetric lighting, subsurface scattering, global illumination, Blender/Unreal Engine quality. "
            "Include '3D render', 'CGI', 'volumetric lighting', 'octane render' in every prompt."
        ),
        "noir": (
            "Every image prompt MUST describe a FILM NOIR style scene. High contrast black and white, "
            "dramatic shadows, venetian blind lighting, rain-slicked streets, moody atmosphere. "
            "Include 'film noir', 'black and white', 'dramatic shadows', 'high contrast' in every prompt."
        ),
        "oil_painting": (
            "Every image prompt MUST describe an OIL PAINTING style scene. Rich impasto texture, "
            "visible brushstrokes, Renaissance or Impressionist influence, deep saturated colors, classical composition. "
            "Include 'oil painting', 'thick brushstrokes', 'impasto texture', 'classical art' in every prompt."
        ),
    }

    STORY_SOURCE = """

SOURCE STORY (the user's own material): build the script from this story. Follow it faithfully: keep its facts, names, numbers and the order of events. Do not invent facts, people or events it does not contain. You may shorten, reword and restructure it for short-form retention.
<<<STORY
{story}
STORY>>>"""

    STORY_NO_INVENT = ("Expand only by elaborating details already in the story; add no new facts, names, "
                       "numbers or events.")

    def _story_block(self, story: str) -> str:
        return self.STORY_SOURCE.format(story=story) if story else ""

    def generate_script(self, topic: str, enable_v2: bool = False,
                        video_style: str = "", video_duration: str = "", story: str = "") -> ScriptOutput:
        """
        Generate a viral TikTok script for the given topic.

        Args:
            topic: The topic or theme for the video
            video_style: Image style — "photorealistic", "cartoon", or "illustration"
            video_duration: Video length — "short", "medium", or "long"
            story: optional user story ("Your story", adapt mode) the script must follow faithfully

        Returns:
            ScriptOutput: Validated script with hook, body, image_prompts, and keywords

        Raises:
            ScriptGeneratorError: If API call fails or response is invalid
        """
        if not topic or not topic.strip():
            raise ScriptGeneratorError("Topic cannot be empty")

        style = video_style or settings.video_style
        duration = video_duration or settings.video_duration

        duration_hint = self.DURATION_GUIDE.get(duration, self.DURATION_GUIDE["medium"])
        if story:
            duration_hint += " " + self.STORY_NO_INVENT
        style_hint = self.STYLE_GUIDE.get(style, self.STYLE_GUIDE["photorealistic"])

        user_prompt = (
            f"Create a viral TikTok script about: {topic}{self._story_block(story)}\n\n"
            f"DURATION: {duration_hint}\n\n"
            f"IMAGE STYLE: {style_hint}"
        )
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

    REVISE_PROMPT = """Rewrite this short-form video script about: {topic}{source}

LENGTH PROBLEM: the narration (hook + body) is {words} words. Rewrite it to {target} words (anything from {lo} to {hi} words is fine), about {seconds} seconds spoken. {direction}

Keep the same structure (hook, open loop, body, re-hook, payoff, loop ending) and the same voice rules. Return every JSON field again. image_prompts, scene_roles{v2_lists} must stay one entry per scene, {scene_lo}-{scene_hi} scenes.{v2_join}

IMAGE STYLE: {style_hint}

CURRENT SCRIPT (JSON):
{script_json}"""

    def revise_length(self, script: ScriptOutput, *, topic: str, words: int, budget: WordBudget,
                      enable_v2: bool = False, video_style: str = "", story: str = "") -> ScriptOutput:
        """One revision call with explicit length feedback (spec 2026-10-03 §7). Raises ScriptGeneratorError.
        story (adapt mode) stays in the prompt so the revision cannot drift from the source."""
        style = video_style or settings.video_style
        too_long = words > budget.hi
        user_prompt = self.REVISE_PROMPT.format(
            topic=topic, source=self._story_block(story), words=words, target=budget.target, lo=budget.lo, hi=budget.hi, seconds=budget.seconds,
            direction=("Cut filler and merge or drop the weakest scene; keep the specifics." if too_long else
                       (self.STORY_NO_INVENT if story else
                        "Add concrete specifics (numbers, names, cause and effect), not filler.")),
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
                     video_duration: str = "", story: str = "") -> "ScriptResult":
        """Draft -> normalize -> roles -> word-budget gate -> at most one revision (spec 2026-10-03 §7).
        Only the first draft can fail the run; the gate and the revision never do.
        story = "Your story" in adapt mode: source material both calls must follow faithfully."""
        budget = word_budget(video_duration or settings.video_duration)
        extra = {"story": story} if story else {}
        script, warnings = self._prepare(self.generate_script(
            topic, enable_v2=enable_v2, video_style=video_style, video_duration=budget.preset, **extra))
        words = draft_words = count_words(f"{script.hook} {script.body}")
        revision = "not_needed"
        if not budget.contains(words):
            try:
                revised, revised_warnings = self._prepare(self.revise_length(
                    script, topic=topic, words=words, budget=budget, enable_v2=enable_v2, video_style=video_style,
                    **extra))
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

    # ------------------------------------------------------------------ "Your story" (app.story)

    STORY_HEAD = """You plan the visuals for a short vertical video (TikTok, YouTube Shorts, Reels) whose narration is already written.
The narration is FIXED. It is split into numbered scenes; you must not change, add, remove or reorder any of its words. You only decide what is shown on screen while each scene is spoken.

You MUST respond with a valid JSON object containing:
- "title": a short title for the video, 8 words or fewer.
- "hook_headline": 2 to 6 punchy words shown on screen while scene 1 plays. Do NOT repeat scene 1; add the number or the stakes.
- "image_prompts": exactly one visual description per scene, in scene order.
- "motion_prompts": exactly one motion description per scene, in scene order (rules below).
- "scene_roles": one role per scene, each one of "hook", "open_loop", "body", "rehook", "payoff", "loop". The first is always "hook"; pick the others from what each scene does in the story.
- "keywords": relevant keywords for metadata and discoverability.

"""

    STORY_PROMPT = """The narration of this video is the user's own story. It is FIXED: do not rewrite it.
It is split into exactly {n} scenes. Return exactly {n} image_prompts, {n} motion_prompts and {n} scene_roles, one per scene, in order.
Each image_prompt must show what its scene says, literally and specifically.

SCENES (JSON list, scene 1 first):
{scenes_json}

IMAGE STYLE: {style_hint}"""

    def _story_system_prompt(self, video_style: str) -> str:
        image_rules = self.IMAGE_RULES.replace(
            'First write "scene_texts" to split the narration into segments. Then write EACH image_prompt',
            "Write EACH image_prompt")
        prompt = self.STORY_HEAD + image_rules + "\n\nMOTION PROMPT RULES:\n" + self.MOTION_RULES
        return self._styled(prompt, video_style)

    def write_story_script(self, story: str, *, mode: str = DEFAULT_STORY_MODE, enable_v2: bool = True,
                           video_style: str = "", video_duration: str = "", title: str = "") -> "ScriptResult":
        """The script of a "Your story" run (app.story).

        adapt: write_script with the story as source material (draft + word-budget gate + revision).
        verbatim: the narration is exactly the story (whitespace normalised). It is split into scenes locally
        (app.story.split_scenes); ONE LLM call returns image/motion prompts, roles, hook_headline, keywords and a
        title for those fixed scene texts; anything else it returns is ignored. Counts are reconciled with
        normalize_prompt_counts (a short list merges trailing scenes, never drops words). The length gate does
        not apply: a story outside the duration preset only gets a story_length warning.
        Raises ScriptGeneratorError when the call fails or returns no image prompts; ValueError for a bad story."""
        story, mode = check_story(story, mode)
        if mode == "adapt":
            result = self.write_script(title or default_title(story), enable_v2=enable_v2, video_style=video_style,
                                       video_duration=video_duration, story=story)
            result.length["story_mode"] = "adapt"
            return result

        budget = word_budget(video_duration or settings.video_duration)
        words = count_words(story)
        scenes = split_scenes(story, scene_count(words, budget.preset))
        style = video_style or settings.video_style
        user_prompt = self.STORY_PROMPT.format(
            n=len(scenes), scenes_json=json.dumps(scenes, ensure_ascii=False, indent=1),
            style_hint=self.STYLE_GUIDE.get(style, self.STYLE_GUIDE["photorealistic"]))
        try:
            data = generate_json(user_prompt, system=self._story_system_prompt(style), temperature=0.7,
                                 max_tokens=min(1200 + 250 * len(scenes), 8000))
        except Exception as e:
            raise ScriptGeneratorError(f"Story visuals generation failed: {e}")
        if not isinstance(data, dict):
            raise ScriptGeneratorError("Story visuals generation failed: the response is not a JSON object")

        images = _text_list(data.get("image_prompts"))
        if not images:
            raise ScriptGeneratorError("Story visuals generation failed: the response has no image prompts")
        llm_title = data.get("title").strip() if isinstance(data.get("title"), str) else ""
        keywords = _text_list(data.get("keywords")) or (title or default_title(story)).split()[:5] or ["story"]
        script = ScriptOutput.model_construct(
            hook=scenes[0], body=" ".join(scenes[1:]), image_prompts=images, keywords=keywords,
            hook_variants=[], hook_viral_score=0, motion_prompts=_text_list(data.get("motion_prompts")),
            pacing_hints=[], scene_texts=list(scenes), emoji_subtitles=[],
            hook_headline=data.get("hook_headline") if isinstance(data.get("hook_headline"), str) else "",
            scene_roles=_text_list(data.get("scene_roles")))
        script, warnings = self._prepare(script)
        scenes = list(script.scene_texts)                 # normalize_prompt_counts may have merged the tail
        script = script.model_copy(update={"hook": scenes[0], "body": " ".join(scenes[1:])})
        if " ".join(scenes) != story:                     # the guarantee of verbatim mode; never expected
            raise ScriptGeneratorError("Story scenes no longer join to the story text")

        seconds = round(words / WORDS_PER_SECOND, 1)
        if not budget.contains(words):
            warnings.append(_warning(
                "story_length",
                f"Your story is {words} words (about {seconds:g} s spoken); the {budget.preset} preset is "
                f"{budget.lo}-{budget.hi} words. The video follows your story.",
                {"words": words, "seconds": seconds, "preset": budget.preset, "range": [budget.lo, budget.hi]}))
        length = {"preset": budget.preset, "target_seconds": seconds, "target_words": words,
                  "word_range": [budget.lo, budget.hi], "draft_words": words, "words": words,
                  "revision": "not_applicable", "story_mode": "verbatim", "scenes": len(scenes),
                  "title": llm_title}
        return ScriptResult(script, warnings, length)


def _text_list(value) -> list:
    """An LLM list field as clean strings: non-lists become [], blanks and non-strings are dropped."""
    if not isinstance(value, list):
        return []
    return [x.strip() for x in value if isinstance(x, str) and x.strip()]
