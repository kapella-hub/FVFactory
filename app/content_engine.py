"""
Content Engine - Script and concept generation
Uses Claude CLI (via app.llm) with OpenAI API fallback.
"""

import json
import logging
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.llm import generate_json

logger = logging.getLogger(__name__)


class ScriptOutput(BaseModel):
    """Validated output model for generated scripts"""

    hook: str = Field(
        ...,
        description="First 3 seconds, very catchy opening line"
    )
    body: str = Field(
        ...,
        description="Main content, 25-85 seconds reading time depending on topic depth"
    )
    image_prompts: List[str] = Field(
        ...,
        min_length=5,
        max_length=20,
        description="5-14 distinct, highly visual descriptions for AI image generation"
    )
    keywords: List[str] = Field(
        ...,
        min_length=1,
        description="Keywords for metadata and discoverability"
    )

    # V2 fields (optional, backward compatible)
    hook_variants: List[str] = Field(default=[], description="3 alternative hook options")
    hook_viral_score: int = Field(default=0, description="1-10 scroll-stopping score for the hook")
    motion_prompts: List[str] = Field(default=[], description="Camera/motion descriptions, one per image_prompt")
    pacing_hints: List[str] = Field(default=[], description="Pacing values, one per image_prompt")
    scene_texts: List[str] = Field(default=[], description="Narration text segments, one per image_prompt")
    emoji_subtitles: List[str] = Field(default=[], description="Key phrases with contextual emojis for subtitles")

    @field_validator("image_prompts")
    @classmethod
    def validate_image_prompts_count(cls, v: List[str]) -> List[str]:
        if len(v) < 5 or len(v) > 20:
            raise ValueError("Between 5 and 20 image prompts are required")
        return v


GENERIC_MOTION_PROMPT = "slow cinematic push-in with subtle camera drift"


def _prompt_counts(script: "ScriptOutput") -> dict:
    return {"image_prompts": len(script.image_prompts), "motion_prompts": len(script.motion_prompts),
            "scene_texts": len(script.scene_texts), "pacing_hints": len(script.pacing_hints)}


def normalize_prompt_counts(script: "ScriptOutput") -> Tuple["ScriptOutput", Optional[dict]]:
    """Make image_prompts / motion_prompts / scene_texts / pacing_hints the same length (spec §10).

    Runs right after the LLM call, before any paid generation. The scene count is the number of
    image prompts, or fewer scene_texts if the LLM returned fewer. Extra scene_texts are merged into
    the last scene (not dropped) so the scenes still join back to the narration for alignment.
    Missing motion prompts get GENERIC_MOTION_PROMPT. model_copy(update=...) skips validation on
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
    new = script.model_copy(update={"image_prompts": list(script.image_prompts[:n]),
                                    "motion_prompts": motion, "scene_texts": scenes,
                                    "pacing_hints": hints})
    before, after = _prompt_counts(script), _prompt_counts(new)
    if before == after:
        return script, None
    logger.warning("Normalized prompt counts %s -> %s", before, after)
    return new, {"before": before, "after": after}


class ScriptGeneratorError(Exception):
    """Base exception for script generation errors"""
    pass


class ScriptGenerator:
    """Generates viral TikTok/Shorts scripts using OpenAI GPT-4o"""

    BASE_SYSTEM_PROMPT = """You are a viral TikTok content creator and scriptwriter.
Your scripts are engaging, punchy, and optimized for short-form video.

You MUST respond with a valid JSON object containing:
- "hook": A catchy opening line for the first 3 seconds that stops scrollers
- "body": The main content. Length should match the topic — say what needs to be said, then stop. Target 30-90 seconds of reading time (the full video including hook should be 30s minimum, 90s maximum). Short punchy topics can be 30-45s. Deep explanations can go up to 90s. Never pad with filler.
- "image_prompts": Visual scene descriptions for AI image generation. Use as many as the content needs — typically 5-14 scenes. Shorter videos need fewer scenes (5-7), longer ones need more (10-14). Each scene should last 3-8 seconds of narration.
- "keywords": Relevant keywords for metadata and discoverability

Make the content sound sophisticated and knowledgeable — like a well-read expert sharing insights.
Use clear, articulate language. Avoid slang or overly casual phrasing.
The tone should be authoritative yet accessible, like a documentary narrator or a TED talk.

CRITICAL IMAGE PROMPT RULES:
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

    V2_INSTRUCTION = """

ADDITIONAL REQUIRED FIELDS:
- "hook_variants": 3 alternative hook options (list of strings)
- "hook_viral_score": Rate the main hook 1-10 on scroll-stopping potential
- "motion_prompts": One camera/motion description per image prompt (same count as image_prompts).
  Each should describe how the camera moves or what animates in the scene.
  Examples: "slow zoom in on the subject, particles floating upward",
  "dramatic pan left revealing the landscape", "static shot with subtle parallax"
- "pacing_hints": One pacing value per scene (same count as image_prompts). Use: "fast" for exciting moments,
  "normal" for standard pacing, "slow" for emotional moments, "dramatic_pause" for reveals.
- "scene_texts": Split the full narration (hook + body) into segments, one per image prompt.
  Each segment is the EXACT text that should be spoken while that scene's image is shown.
  The segments must join together to form the complete narration (hook + body).
  This is CRITICAL for syncing visuals to narration. Example for 3 scenes:
  ["Did you know the ocean holds secrets?", "First, 80% is unexplored...", "Finally, the deepest point..."]
- "emoji_subtitles": 3-5 key phrases from the script with contextual emojis added.
  Example: "Bitcoin crashed 📉😱", "Scientists discovered 🔬🧬"
"""

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
        prompt = self.BASE_SYSTEM_PROMPT

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

        if settings.mascot_enabled and settings.mascot_prompt:
            mascot_section = self.MASCOT_INSTRUCTION.format(
                mascot_prompt=settings.mascot_prompt
            )
            prompt += mascot_section

        if enable_v2:
            prompt += self.V2_INSTRUCTION

        return prompt

    DURATION_GUIDE = {
        "short": "Keep the video SHORT: 30-45 seconds reading time, 5-7 scenes max. Be concise.",
        "medium": "Target MEDIUM length: 45-75 seconds reading time, 8-10 scenes.",
        "long": "This should be a LONG deep-dive: 75-90 seconds reading time, 11-14 scenes. Go in depth.",
    }

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

    def generate_script(self, topic: str, enable_v2: bool = False,
                        video_style: str = "", video_duration: str = "") -> ScriptOutput:
        """
        Generate a viral TikTok script for the given topic.

        Args:
            topic: The topic or theme for the video
            video_style: Image style — "photorealistic", "cartoon", or "illustration"
            video_duration: Video length — "short", "medium", or "long"

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
        style_hint = self.STYLE_GUIDE.get(style, self.STYLE_GUIDE["photorealistic"])

        user_prompt = (
            f"Create a viral TikTok script about: {topic}\n\n"
            f"DURATION: {duration_hint}\n\n"
            f"IMAGE STYLE: {style_hint}"
        )
        system_prompt = self._build_system_prompt(enable_v2=enable_v2, video_style=style)

        try:
            data = generate_json(user_prompt, system=system_prompt, temperature=0.8, max_tokens=3000)

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
