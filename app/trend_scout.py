"""Trend Scout - Discovers trending topics from Google Trends, Reddit, and YouTube.

Uses GPT to curate and reframe topics for maximum video potential."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from app.config import settings
from app.llm import generate_json

logger = logging.getLogger(__name__)


@dataclass
class TrendTopic:
    """A discovered trending topic."""
    title: str
    source: str  # "reddit", "google_trends", or "youtube"
    score: int = 0
    url: str = ""
    # Added by GPT curation
    video_angle: str = ""  # Reframed title optimized for video
    viral_score: int = 0   # 1-10 GPT-assessed virality


class TrendScout:
    """Discovers trending topics from multiple sources and curates them with GPT."""

    REDDIT_BASE = "https://www.reddit.com"
    USER_AGENT = "FVFactory/2.0"

    # Niches that should generate their own topics rather than reframe trending ones
    DEDICATED_NICHES = {
        "stoicism", "philosophy", "self-improvement", "motivation",
        "mindset", "wisdom", "psychology",
    }

    def discover_topics(self, niche: Optional[str] = None, count: int = 0) -> List[TrendTopic]:
        """Discover, curate, and rank trending topics.

        For dedicated niches (stoicism, philosophy, etc.): GPT generates
        original niche-specific topics directly — no trending data needed.

        For general/trending: fetches from Google Trends, Reddit, YouTube,
        then GPT curates and picks the best video angles.
        """
        if count <= 0:
            count = settings.trend_count

        # For dedicated niches, generate topics directly with GPT
        niche_key = (niche or "").lower().strip()
        if niche_key in self.DEDICATED_NICHES:
            logger.info(f"Generating {count} topic(s) for dedicated niche: {niche_key}")
            niche_topics = self._generate_niche_topics(niche_key, count)
            if niche_topics:
                return niche_topics
            logger.warning(f"Niche topic generation failed for '{niche_key}', falling back to trending")

        # For general topics: fetch from all sources
        all_topics: List[TrendTopic] = []

        google_topics = self._fetch_google_trends()
        all_topics.extend(google_topics)
        logger.info(f"Google Trends: {len(google_topics)} topics")

        subreddits = settings.reddit_subreddits.split(",")
        reddit_topics = self._fetch_reddit_hot(subreddits)
        all_topics.extend(reddit_topics)
        logger.info(f"Reddit: {len(reddit_topics)} topics")

        youtube_topics = self._fetch_youtube_trending()
        all_topics.extend(youtube_topics)
        logger.info(f"YouTube: {len(youtube_topics)} topics")

        # Sort by raw score first
        all_topics.sort(key=lambda t: t.score, reverse=True)

        if not all_topics:
            logger.warning("No trending topics found from any source")
            return []

        # GPT curation: pick the best topics and reframe them
        curated = self._curate_with_gpt(all_topics[:30], niche=niche, count=count)

        if curated:
            logger.info(f"GPT curated {len(curated)} topics")
            return curated[:count]

        # Fallback: return raw topics if GPT fails
        logger.warning("GPT curation failed, returning raw topics")
        return all_topics[:count]

    def _fetch_google_trends(self) -> List[TrendTopic]:
        """Fetch trending searches from Google Trends. Never raises."""
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US")
            trending = pytrends.trending_searches(pn="united_states")

            topics = []
            for i, row in trending.iterrows():
                title = str(row[0]).strip()
                if title:
                    topics.append(TrendTopic(
                        title=title,
                        source="google_trends",
                        score=max(100 - i * 5, 10),
                    ))

            return topics[:20]

        except Exception as e:
            logger.warning(f"Google Trends fetch failed (non-fatal): {e}")
            return []

    def _fetch_reddit_hot(self, subreddits: List[str]) -> List[TrendTopic]:
        """Fetch hot posts from Reddit. Filters NSFW and low-quality posts."""
        topics: List[TrendTopic] = []

        for sub in subreddits:
            sub = sub.strip()
            if not sub:
                continue

            try:
                url = f"{self.REDDIT_BASE}/r/{sub}/hot.json?limit=10"
                response = requests.get(
                    url,
                    headers={"User-Agent": self.USER_AGENT},
                    timeout=10,
                )

                if response.status_code != 200:
                    logger.warning(f"Reddit r/{sub}: HTTP {response.status_code}")
                    continue

                data = response.json()
                children = data.get("data", {}).get("children", [])

                for child in children:
                    post = child.get("data", {})
                    if post.get("over_18", False):
                        continue
                    if post.get("stickied", False):
                        continue
                    title = post.get("title", "").strip()
                    if not title or len(title) < 15:
                        continue
                    # Skip meta/discussion posts
                    if any(skip in title.lower() for skip in [
                        "megathread", "weekly", "monthly", "daily thread",
                        "mod post", "rule", "[meta]",
                    ]):
                        continue
                    topics.append(TrendTopic(
                        title=title,
                        source="reddit",
                        score=post.get("score", 0),
                        url=f"{self.REDDIT_BASE}{post.get('permalink', '')}",
                    ))

            except Exception as e:
                logger.warning(f"Reddit r/{sub} fetch failed: {e}")
                continue

        return topics

    def _fetch_youtube_trending(self) -> List[TrendTopic]:
        """Fetch trending YouTube Shorts topics via the Data API or scraping.

        Uses YouTube Data API if YOUTUBE_API_KEY is set, otherwise falls back
        to Google Trends' YouTube trending.
        """
        api_key = settings.youtube_api_key
        if not api_key:
            return self._fetch_youtube_trending_fallback()

        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": "US",
                    "videoCategoryId": "27",  # Education
                    "maxResults": 15,
                    "key": api_key,
                },
                timeout=10,
            )

            if resp.status_code != 200:
                logger.warning(f"YouTube API error: {resp.status_code}")
                return self._fetch_youtube_trending_fallback()

            items = resp.json().get("items", [])
            topics = []
            for item in items:
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                title = snippet.get("title", "").strip()
                if not title:
                    continue

                view_count = int(stats.get("viewCount", 0))
                # Normalize score: views / 10000 capped at 500
                score = min(view_count // 10000, 500)

                topics.append(TrendTopic(
                    title=title,
                    source="youtube",
                    score=score,
                    url=f"https://youtube.com/watch?v={item.get('id', '')}",
                ))

            return topics

        except Exception as e:
            logger.warning(f"YouTube API fetch failed: {e}")
            return self._fetch_youtube_trending_fallback()

    def _generate_niche_topics(self, niche: str, count: int) -> List[TrendTopic]:
        """Generate original topics for a dedicated niche using LLM.

        Instead of trying to reframe trending news through a niche lens,
        this creates genuinely compelling niche-specific topics that
        are inherently interesting and shareable.
        """
        niche_examples = {
            "stoicism": [
                "The One Rule Billionaires Stole from Stoicism",
                "Why Seneca Wanted You to Practice Poverty",
                "Marcus Aurelius's Morning Routine Was Brutal",
                "This 2000-Year-Old Trick Kills Anxiety",
                "The Stoic Secret That Built Rome",
            ],
            "self-improvement": [
                "The 5-Second Rule That Changed Millions of Lives",
                "Why Your Brain Sabotages You at 3 AM",
                "The Japanese Method to Stop Procrastinating",
                "Navy SEALs Use This One Mental Trick Daily",
                "Why Successful People Wake Up Feeling Terrible",
            ],
            "philosophy": [
                "Nietzsche's Warning Nobody Listened To",
                "The Paradox That Broke Ancient Greece",
                "Why Socrates Chose Death Over Silence",
                "The Philosophy That Predicted Social Media",
                "Plato's Cave Is Happening Right Now",
            ],
            "motivation": [
                "The Speech That Created a Billionaire",
                "Why Motivation Is a Trap (Do This Instead)",
                "The 10-Minute Rule That Beats Laziness",
                "Kobe's Secret Nobody Talks About",
                "Why You're Not Lazy — You're Afraid",
            ],
            "psychology": [
                "Why Your Brain Lies to You Every Day",
                "The Dark Psychology of Supermarket Layouts",
                "Why We Remember Insults Longer Than Praise",
                "The Experiment That Proved Evil Is Normal",
                "Your Personality Changes Every 10 Years",
            ],
        }

        examples = niche_examples.get(niche, niche_examples.get("self-improvement"))
        examples_str = "\n".join(f'- "{e}"' for e in examples)

        prompt = f"""You are a viral short-form video strategist specializing in {niche} content.

Generate {count} compelling video topic(s) for 60-second educational documentary-style videos in the "{niche}" niche.

REQUIREMENTS:
- Each topic should have a strong curiosity gap (a question or surprising fact)
- Topics should be timeless/evergreen, not tied to current events
- The title should be SHORT (under 60 characters), punchy, and scroll-stopping
- Think "things people don't know but would find fascinating"
- Vary the topics — don't repeat similar angles
- Do NOT repeat or rephrase the examples below — create something fresh

EXAMPLES of good {niche} titles (for style reference only, do NOT reuse):
{examples_str}

Respond with a JSON object:
{{
  "topics": [
    {{
      "title": "Short, catchy title under 60 chars",
      "viral_score": 8,
      "reason": "Why this will perform well"
    }}
  ]
}}"""

        try:
            data = generate_json(prompt, temperature=0.9, max_tokens=500)

            # Extract topics list
            picks = []
            if isinstance(data, dict):
                for key in ("topics", "results", "picks"):
                    if key in data and isinstance(data[key], list):
                        picks = data[key]
                        break
                if not picks:
                    for v in data.values():
                        if isinstance(v, list) and v:
                            picks = v
                            break

            topics = []
            for pick in picks:
                title = pick.get("title", "")
                if title:
                    topics.append(TrendTopic(
                        title=title,
                        source="llm_niche",
                        score=pick.get("viral_score", 7) * 100,
                        viral_score=pick.get("viral_score", 7),
                    ))

            logger.info(f"Generated {len(topics)} niche topics for '{niche}'")
            return topics[:count]

        except Exception as e:
            logger.warning(f"Niche topic generation failed: {e}")
            return []

    def _fetch_youtube_trending_fallback(self) -> List[TrendTopic]:
        """Fallback: fetch YouTube trending searches via Google Trends."""
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US")
            # Google Trends has YouTube-specific trending
            suggestions = pytrends.suggestions("trending")
            # This is limited, so just return empty and rely on other sources
            return []
        except Exception:
            return []

    def _curate_with_gpt(
        self,
        topics: List[TrendTopic],
        niche: Optional[str] = None,
        count: int = 5,
    ) -> List[TrendTopic]:
        """Use GPT to curate, score, and reframe topics for video potential.

        GPT evaluates each topic on:
        - Viral potential (would people click/share?)
        - Visual storytelling potential (can we make compelling scenes?)
        - Knowledge/insight value (does the viewer learn something?)

        If a niche is provided, GPT reframes topics through that lens.
        """
        if not settings.openai_api_key:
            return []

        # Build the topic list for GPT
        topic_lines = []
        for i, t in enumerate(topics):
            topic_lines.append(f"{i+1}. [{t.source}] (score: {t.score}) {t.title}")

        topic_list = "\n".join(topic_lines)

        niche_instruction = ""
        if niche:
            niche_instruction = f"""
NICHE REFRAMING: The channel's niche is "{niche}".
For EACH topic, reframe it through the lens of {niche}.
Example: If the niche is "stoicism" and the topic is "AI replacing jobs",
the video_angle should be something like "What Marcus Aurelius Would Say About AI Taking Your Job"
or "The Stoic Response to the AI Revolution".
The angle should feel natural, not forced. If a topic truly cannot connect to {niche}, skip it."""

        prompt = f"""You are a viral short-form video strategist. Below are today's trending topics from Google Trends, Reddit, and YouTube.

Pick the top {count} topics that would make the BEST 60-second educational/documentary-style videos.

SCORING CRITERIA (1-10):
- Curiosity gap: Would someone stop scrolling to watch this?
- Visual potential: Can we create compelling photorealistic scenes?
- Knowledge value: Does the viewer learn something surprising?
- Shareability: Would someone send this to a friend?
- Evergreen potential: Will this still be interesting in a week?

AVOID:
- Celebrity gossip, sports scores, politics, breaking news that will be stale
- Topics that need live footage (we generate AI images)
- Anything controversial or divisive
{niche_instruction}

TRENDING TOPICS:
{topic_list}

Respond with a JSON array of exactly {count} objects:
[
  {{
    "original_index": 1,
    "video_angle": "The reframed title optimized for a viral video",
    "viral_score": 8,
    "reason": "One sentence on why this will perform well"
  }}
]

Pick diverse topics. The video_angle should be a compelling, specific title — not generic.
Respond ONLY with the JSON array, no other text."""

        try:
            data = generate_json(prompt, temperature=0.7, max_tokens=800)

            # Handle various response shapes from GPT
            picks = []
            if isinstance(data, list):
                picks = data
            elif isinstance(data, dict):
                # Try common key names
                for key in ("topics", "results", "picks", "selected", "curated"):
                    if key in data and isinstance(data[key], list):
                        picks = data[key]
                        break
                if not picks:
                    # Try any list value
                    for v in data.values():
                        if isinstance(v, list) and v:
                            picks = v
                            break

            curated = []
            for pick in picks:
                idx = pick.get("original_index", 1) - 1
                if 0 <= idx < len(topics):
                    topic = topics[idx]
                    topic.video_angle = pick.get("video_angle", topic.title)
                    topic.viral_score = pick.get("viral_score", 5)
                    # Use the reframed angle as the title
                    topic.title = topic.video_angle
                    curated.append(topic)

            # Sort by viral score
            curated.sort(key=lambda t: t.viral_score, reverse=True)
            return curated

        except Exception as e:
            logger.warning(f"GPT curation failed: {e}")
            return []
