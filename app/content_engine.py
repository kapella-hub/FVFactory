"""
Content Engine - Script and concept generation using OpenAI
"""

import json
from typing import List

from openai import OpenAI, APIError, APIConnectionError, RateLimitError
from pydantic import BaseModel, Field, field_validator

from app.config import settings


class ScriptOutput(BaseModel):
    """Validated output model for generated scripts"""

    hook: str = Field(
        ...,
        description="First 3 seconds, very catchy opening line"
    )
    body: str = Field(
        ...,
        description="Main content, approximately 30-40 seconds reading time"
    )
    image_prompts: List[str] = Field(
        ...,
        min_length=5,
        max_length=5,
        description="Exactly 5 distinct, highly visual descriptions for AI image generation"
    )
    keywords: List[str] = Field(
        ...,
        min_length=1,
        description="Keywords for metadata and discoverability"
    )

    # V2 fields (optional, backward compatible)
    hook_variants: List[str] = Field(default=[], description="3 alternative hook options")
    hook_viral_score: int = Field(default=0, description="1-10 scroll-stopping score for the hook")
    motion_prompts: List[str] = Field(default=[], description="5 camera/motion descriptions for image-to-video")
    pacing_hints: List[str] = Field(default=[], description="5 pacing values: fast, normal, slow, dramatic_pause")
    emoji_subtitles: List[str] = Field(default=[], description="Key phrases with contextual emojis for subtitles")

    @field_validator("image_prompts")
    @classmethod
    def validate_image_prompts_count(cls, v: List[str]) -> List[str]:
        if len(v) != 5:
            raise ValueError("Exactly 5 image prompts are required")
        return v


class ScriptGeneratorError(Exception):
    """Base exception for script generation errors"""
    pass


class ScriptGenerator:
    """Generates viral TikTok/Shorts scripts using OpenAI GPT-4o"""

    BASE_SYSTEM_PROMPT = """You are a viral TikTok content creator and scriptwriter.
Your scripts are engaging, punchy, and optimized for short-form video.

You MUST respond with a valid JSON object containing:
- "hook": A catchy opening line for the first 3 seconds that stops scrollers
- "body": The main content (30-40 seconds reading time), conversational and engaging
- "image_prompts": Exactly 5 distinct, highly visual scene descriptions for AI image generation that match the script flow
- "keywords": Relevant keywords for metadata and discoverability

Make the content informative yet entertaining. Use simple language.
Each image prompt should be detailed enough for an AI to generate a compelling visual."""

    V2_INSTRUCTION = """

ADDITIONAL REQUIRED FIELDS:
- "hook_variants": 3 alternative hook options (list of strings)
- "hook_viral_score": Rate the main hook 1-10 on scroll-stopping potential
- "motion_prompts": Exactly 5 camera/motion descriptions for image-to-video generation.
  Each should describe how the camera moves or what animates in the scene.
  Examples: "slow zoom in on the subject, particles floating upward",
  "dramatic pan left revealing the landscape", "static shot with subtle parallax"
- "pacing_hints": Exactly 5 pacing values, one per scene. Use: "fast" for exciting moments,
  "normal" for standard pacing, "slow" for emotional moments, "dramatic_pause" for reveals.
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

    def __init__(self):
        if not settings.openai_api_key:
            raise ScriptGeneratorError("OPENAI_API_KEY is not configured")

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = "gpt-4o"

    def _build_system_prompt(self, enable_v2: bool = False) -> str:
        """Build the system prompt, optionally including mascot instructions."""
        prompt = self.BASE_SYSTEM_PROMPT

        if settings.mascot_enabled and settings.mascot_prompt:
            mascot_section = self.MASCOT_INSTRUCTION.format(
                mascot_prompt=settings.mascot_prompt
            )
            prompt += mascot_section

        if enable_v2:
            prompt += self.V2_INSTRUCTION

        return prompt

    def generate_script(self, topic: str, enable_v2: bool = False) -> ScriptOutput:
        """
        Generate a viral TikTok script for the given topic.

        Args:
            topic: The topic or theme for the video

        Returns:
            ScriptOutput: Validated script with hook, body, image_prompts, and keywords

        Raises:
            ScriptGeneratorError: If API call fails or response is invalid
        """
        if not topic or not topic.strip():
            raise ScriptGeneratorError("Topic cannot be empty")

        user_prompt = f"Create a viral TikTok script about: {topic}"
        system_prompt = self._build_system_prompt(enable_v2=enable_v2)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.8,
                max_tokens=1500
            )

            content = response.choices[0].message.content

            if not content:
                raise ScriptGeneratorError("Empty response from OpenAI")

            # Parse JSON response
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                raise ScriptGeneratorError(f"Invalid JSON response: {e}")

            # Validate with Pydantic
            try:
                script = ScriptOutput(**data)
            except ValueError as e:
                raise ScriptGeneratorError(f"Response validation failed: {e}")

            return script

        except APIConnectionError as e:
            raise ScriptGeneratorError(f"Failed to connect to OpenAI: {e}")
        except RateLimitError as e:
            raise ScriptGeneratorError(f"OpenAI rate limit exceeded: {e}")
        except APIError as e:
            raise ScriptGeneratorError(f"OpenAI API error: {e}")
