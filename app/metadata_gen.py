"""Metadata Generator - Generates titles, descriptions, hashtags, and thumbnails"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

logger = logging.getLogger(__name__)


class MetadataGenerator:
    """Generates platform-optimized metadata for videos."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or settings.output_dir)
        self.metadata_dir = self.output_dir / "metadata"
        self.thumbnail_dir = self.output_dir / "thumbnails"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

        self.client = None
        if settings.openai_api_key:
            self.client = OpenAI(api_key=settings.openai_api_key)

    def generate_metadata(
        self,
        topic: str,
        hook: str,
        keywords: List[str],
        niche: str = "",
    ) -> Dict:
        """Generate platform-optimized metadata using GPT."""
        if not self.client:
            return self._fallback_metadata(topic, hook, keywords)

        prompt = f"""Generate social media metadata for a short-form video.
Topic: {topic}
Hook: {hook}
Keywords: {', '.join(keywords)}
Niche: {niche or 'general'}

Return JSON with:
- "title_tiktok": Short, catchy title for TikTok (max 50 chars)
- "title_youtube": SEO-optimized title for YouTube Shorts (max 70 chars)
- "description": 2-3 sentence description with keywords
- "hashtags": List of 5-10 relevant hashtags (include # prefix)
- "best_posting_time": Recommended posting time"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=500,
            )
            content = response.choices[0].message.content
            return json.loads(content)

        except Exception as e:
            logger.warning(f"Metadata generation failed, using fallback: {e}")
            return self._fallback_metadata(topic, hook, keywords)

    def _fallback_metadata(self, topic: str, hook: str, keywords: List[str]) -> Dict:
        """Generate basic metadata without GPT."""
        return {
            "title_tiktok": topic[:50],
            "title_youtube": topic[:70],
            "description": hook,
            "hashtags": [f"#{kw.replace(' ', '')}" for kw in keywords[:10]],
            "best_posting_time": "Tuesday-Thursday 6-8 PM EST",
        }

    def save_metadata(self, video_id: str, metadata: Dict) -> str:
        """Save metadata to JSON file."""
        path = self.metadata_dir / f"{video_id}.json"
        with open(path, "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info(f"Metadata saved: {path}")
        return str(path)

    def generate_thumbnail(
        self,
        video_path: str,
        video_id: str,
        title: str,
    ) -> Optional[str]:
        """Extract a frame from the video and add title text for thumbnail."""
        try:
            from moviepy import VideoFileClip

            clip = VideoFileClip(video_path)
            frame_time = clip.duration * 0.25
            frame = clip.get_frame(frame_time)
            clip.close()

            img = Image.fromarray(frame)

            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.truetype("Arial-Bold", 80)
            except OSError:
                font = ImageFont.load_default()

            text = title[:40].upper()
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            x = (img.width - text_w) // 2
            y = img.height // 3

            for dx in range(-3, 4):
                for dy in range(-3, 4):
                    draw.text((x + dx, y + dy), text, font=font, fill="black")
            draw.text((x, y), text, font=font, fill="white")

            thumb_path = self.thumbnail_dir / f"{video_id}.png"
            img.save(str(thumb_path))
            logger.info(f"Thumbnail saved: {thumb_path}")
            return str(thumb_path)

        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            return None
