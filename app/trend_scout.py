"""Trend Scout v2 — Multi-source trending topic discovery with cross-platform
signal boosting, topic deduplication, and sophisticated GPT curation.

Sources: Google Trends, Reddit (viral subs), YouTube (multiple categories),
HackerNews, and Exploding Topics proxy via Google Trends related queries.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import requests

from app.config import settings
from app.llm import generate_json

logger = logging.getLogger(__name__)


@dataclass
class TrendTopic:
    """A discovered trending topic."""
    title: str
    source: str  # "reddit", "google_trends", "youtube", "hackernews", "multi"
    score: int = 0
    url: str = ""
    subreddit: str = ""  # for reddit topics
    # Added by GPT curation
    video_angle: str = ""  # Reframed title optimized for video
    viral_score: int = 0   # 1-10 GPT-assessed virality
    reason: str = ""       # Why GPT picked this
    # Cross-platform signal
    source_count: int = 1  # How many platforms this topic appeared on


# Reddit subreddits organized by content type — viral/story-driven first
REDDIT_VIRAL_SUBS = [
    # High-viral storytelling
    "todayilearned", "Damnthatsinteresting", "interestingasfuck",
    "nextfuckinglevel", "BeAmazed", "ThatsInsane",
    # Science & nature (visual, shareable)
    "space", "NatureIsFuckingLit", "sciences",
    # Tech & future
    "Futurology", "technology", "artificial",
    # History & culture
    "HistoryPorn", "history", "ArtefactPorn",
    # Psychology & human behavior
    "psychology", "YouShouldKnow", "LifeProTips",
]

# YouTube categories worth scanning (not just Education)
YOUTUBE_CATEGORIES = {
    "28": "Science & Technology",
    "27": "Education",
    "25": "News & Politics",
    "24": "Entertainment",
}

# Niche-specific subreddit mapping
NICHE_SUBREDDITS = {
    "tech": ["technology", "artificial", "Futurology", "programming", "gadgets"],
    "science": ["sciences", "space", "physics", "biology", "chemistry"],
    "finance": ["finance", "economics", "CryptoCurrency", "stocks", "wallstreetbets"],
    "history": ["history", "HistoryPorn", "ArtefactPorn", "AskHistorians"],
    "gaming": ["gaming", "Games", "pcgaming", "PS5", "NintendoSwitch"],
    "health": ["health", "Fitness", "nutrition", "science"],
    "lifestyle": ["LifeProTips", "productivity", "minimalism", "getdisciplined"],
    "trending": REDDIT_VIRAL_SUBS[:10],
}


class TrendScout:
    """Discovers trending topics from multiple sources and curates them with GPT.

    v2 improvements:
    - Cross-platform signal boosting (topic on 2+ platforms scores higher)
    - Better Reddit coverage (viral/story subs, niche-specific subs)
    - YouTube multi-category scanning
    - HackerNews front page
    - Topic deduplication against past videos
    - Smarter GPT curation prompt (short-form video specific)
    """

    REDDIT_BASE = "https://www.reddit.com"
    USER_AGENT = "FVFactory/3.0"

    # Niches that should generate their own topics rather than reframe trending ones
    DEDICATED_NICHES = {
        "stoicism", "philosophy", "self-improvement", "motivation",
        "mindset", "wisdom", "psychology",
    }

    def discover_topics(self, niche: Optional[str] = None, count: int = 0) -> List[TrendTopic]:
        """Discover, curate, and rank trending topics.

        For dedicated niches: GPT generates original niche-specific topics.
        For general/trending: fetches from all sources, cross-references, GPT curates.
        """
        if count <= 0:
            count = settings.trend_count

        niche_key = (niche or "").lower().strip()

        # For dedicated niches, generate topics directly with GPT
        if niche_key in self.DEDICATED_NICHES:
            logger.info("Generating %d topic(s) for dedicated niche: %s", count, niche_key)
            niche_topics = self._generate_niche_topics(niche_key, count)
            if niche_topics:
                return niche_topics
            logger.warning("Niche topic generation failed for '%s', falling back to trending", niche_key)

        # Fetch from all sources in parallel-friendly fashion
        all_topics: List[TrendTopic] = []

        # 1. Google Trends
        google_topics = self._fetch_google_trends()
        all_topics.extend(google_topics)
        logger.info("Google Trends: %d topics", len(google_topics))

        # 2. Reddit — use niche-specific subs if applicable, else viral defaults
        subreddits = self._get_subreddits(niche_key)
        reddit_topics = self._fetch_reddit_hot(subreddits)
        all_topics.extend(reddit_topics)
        logger.info("Reddit: %d topics from %d subs", len(reddit_topics), len(subreddits))

        # 3. YouTube — scan multiple categories
        youtube_topics = self._fetch_youtube_trending()
        all_topics.extend(youtube_topics)
        logger.info("YouTube: %d topics", len(youtube_topics))

        # 4. HackerNews front page
        hn_topics = self._fetch_hackernews()
        all_topics.extend(hn_topics)
        logger.info("HackerNews: %d topics", len(hn_topics))

        if not all_topics:
            logger.warning("No trending topics found from any source")
            return []

        # Cross-platform signal boosting
        all_topics = self._boost_cross_platform(all_topics)

        # Sort by score
        all_topics.sort(key=lambda t: t.score, reverse=True)

        # Load past topics for dedup
        past_topics = self._load_past_topics()

        # GPT curation: pick the best topics and reframe them
        curated = self._curate_with_gpt(
            all_topics[:40], niche=niche, count=count,
            past_topics=past_topics,
        )

        if curated:
            logger.info("GPT curated %d topics (top viral_score: %d)",
                        len(curated), curated[0].viral_score if curated else 0)
            return curated[:count]

        # Fallback: return raw topics if GPT fails
        logger.warning("GPT curation failed, returning raw topics")
        return all_topics[:count]

    def _get_subreddits(self, niche: str) -> List[str]:
        """Get relevant subreddits for the niche."""
        if niche in NICHE_SUBREDDITS:
            # Niche-specific + a few viral subs for variety
            return NICHE_SUBREDDITS[niche] + REDDIT_VIRAL_SUBS[:3]
        # Default: viral subs + configured subs
        custom = [s.strip() for s in settings.reddit_subreddits.split(",") if s.strip()]
        combined = list(dict.fromkeys(REDDIT_VIRAL_SUBS + custom))  # dedup, preserve order
        return combined[:15]  # cap to avoid rate limiting

    def _fetch_google_trends(self) -> List[TrendTopic]:
        """Fetch trending searches from Google Trends."""
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
            logger.warning("Google Trends fetch failed (non-fatal): %s", e)
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
                    continue

                data = response.json()
                children = data.get("data", {}).get("children", [])

                for child in children:
                    post = child.get("data", {})
                    if post.get("over_18", False) or post.get("stickied", False):
                        continue
                    title = post.get("title", "").strip()
                    if not title or len(title) < 15:
                        continue
                    # Skip meta/discussion posts
                    title_lower = title.lower()
                    if any(skip in title_lower for skip in [
                        "megathread", "weekly", "monthly", "daily thread",
                        "mod post", "rule", "[meta]", "ama", "ask me anything",
                    ]):
                        continue

                    upvotes = post.get("score", 0)
                    # Normalize: posts with 1k+ upvotes are genuinely trending
                    norm_score = min(upvotes // 100, 200)

                    topics.append(TrendTopic(
                        title=title,
                        source="reddit",
                        score=norm_score,
                        url=f"{self.REDDIT_BASE}{post.get('permalink', '')}",
                        subreddit=sub,
                    ))

            except Exception as e:
                logger.warning("Reddit r/%s fetch failed: %s", sub, e)
                continue

        # Deduplicate similar titles within Reddit
        return self._deduplicate_topics(topics)

    def _fetch_youtube_trending(self) -> List[TrendTopic]:
        """Fetch trending YouTube videos across multiple categories."""
        api_key = settings.youtube_api_key
        if not api_key:
            return self._fetch_youtube_trending_fallback()

        all_topics = []
        for cat_id, cat_name in YOUTUBE_CATEGORIES.items():
            try:
                resp = requests.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={
                        "part": "snippet,statistics",
                        "chart": "mostPopular",
                        "regionCode": "US",
                        "videoCategoryId": cat_id,
                        "maxResults": 10,
                        "key": api_key,
                    },
                    timeout=10,
                )

                if resp.status_code != 200:
                    continue

                items = resp.json().get("items", [])
                for item in items:
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    title = snippet.get("title", "").strip()
                    if not title:
                        continue

                    view_count = int(stats.get("viewCount", 0))
                    score = min(view_count // 10000, 500)

                    all_topics.append(TrendTopic(
                        title=title,
                        source="youtube",
                        score=score,
                        url=f"https://youtube.com/watch?v={item.get('id', '')}",
                    ))

            except Exception as e:
                logger.warning("YouTube cat %s fetch failed: %s", cat_id, e)

        return all_topics

    def _fetch_hackernews(self) -> List[TrendTopic]:
        """Fetch top stories from HackerNews (strong signal for tech/science/interesting)."""
        try:
            # Get top 30 story IDs
            resp = requests.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json",
                timeout=10,
            )
            if resp.status_code != 200:
                return []

            story_ids = resp.json()[:30]
            topics = []

            for sid in story_ids[:20]:  # fetch details for top 20
                try:
                    item_resp = requests.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                        timeout=5,
                    )
                    if item_resp.status_code != 200:
                        continue
                    item = item_resp.json()
                    title = item.get("title", "").strip()
                    if not title or len(title) < 10:
                        continue

                    score = item.get("score", 0)
                    # HN scores: 100+ is solid, 500+ is very hot
                    norm_score = min(score // 5, 200)

                    topics.append(TrendTopic(
                        title=title,
                        source="hackernews",
                        score=norm_score,
                        url=item.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                    ))
                except Exception:
                    continue

            return topics

        except Exception as e:
            logger.warning("HackerNews fetch failed (non-fatal): %s", e)
            return []

    def _fetch_youtube_trending_fallback(self) -> List[TrendTopic]:
        """Fallback when no YouTube API key is set."""
        return []

    def _boost_cross_platform(self, topics: List[TrendTopic]) -> List[TrendTopic]:
        """Boost topics that appear on multiple platforms.

        If a topic about 'AI' appears on Reddit, HackerNews, AND Google Trends,
        it's genuinely trending — boost its score significantly.
        """
        # Build keyword index: extract key terms from each title
        from collections import defaultdict

        # Group topics by normalized key phrases
        keyword_groups: dict[str, list[TrendTopic]] = defaultdict(list)

        for topic in topics:
            # Extract meaningful words (3+ chars, lowercase)
            words = set(
                w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', topic.title)
                if w.lower() not in {
                    "the", "and", "for", "that", "this", "with", "from", "are",
                    "was", "has", "have", "had", "not", "but", "what", "who",
                    "how", "why", "when", "where", "can", "will", "just", "been",
                    "its", "all", "your", "you", "they", "their", "than", "more",
                    "about", "into", "over", "after", "also", "new", "first",
                }
            )
            # Create bigrams from significant words for better matching
            for word in words:
                keyword_groups[word].append(topic)

        # Find topics that share keywords across different sources
        boosted = set()
        for word, group in keyword_groups.items():
            sources = set(t.source for t in group)
            if len(sources) >= 2:
                # This keyword appears on 2+ platforms — boost all related topics
                for topic in group:
                    if id(topic) not in boosted:
                        topic.score = int(topic.score * 1.5)
                        topic.source_count = len(sources)
                        boosted.add(id(topic))

        return topics

    def _deduplicate_topics(self, topics: List[TrendTopic]) -> List[TrendTopic]:
        """Remove near-duplicate topics (same story from different subs)."""
        seen_keys = set()
        unique = []

        for topic in topics:
            # Create a rough dedup key from significant words
            words = sorted(set(
                w.lower() for w in re.findall(r'\b[a-zA-Z]{4,}\b', topic.title)
            ))
            key = " ".join(words[:5])  # first 5 significant words

            if key not in seen_keys:
                seen_keys.add(key)
                unique.append(topic)

        return unique

    def _load_past_topics(self) -> List[str]:
        """Load titles of previously generated videos to avoid repeats."""
        past = []
        metadata_dir = Path(settings.output_dir) / "metadata"
        if not metadata_dir.exists():
            return past

        try:
            for f in sorted(metadata_dir.glob("*.json"), reverse=True)[:50]:
                try:
                    data = json.loads(f.read_text())
                    # Try various title fields
                    title = (
                        data.get("title_tiktok", "") or
                        data.get("title_youtube", "") or
                        data.get("topic", "") or
                        ""
                    )
                    if title:
                        past.append(title)
                except Exception:
                    continue
        except Exception:
            pass

        return past

    def _generate_niche_topics(self, niche: str, count: int) -> List[TrendTopic]:
        """Generate original topics for a dedicated niche using LLM.

        Creates genuinely compelling niche-specific topics that
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

        # Load past topics to avoid repeats
        past_topics = self._load_past_topics()
        past_str = ""
        if past_topics:
            past_str = "\n\nDO NOT generate topics similar to these (already produced):\n" + \
                       "\n".join(f'- "{t}"' for t in past_topics[:20])

        examples = niche_examples.get(niche, niche_examples.get("self-improvement"))
        examples_str = "\n".join(f'- "{e}"' for e in examples)

        prompt = f"""You are a viral short-form video strategist specializing in {niche} content.

Generate {count} compelling video topic(s) for 60-second educational documentary-style videos in the "{niche}" niche.

REQUIREMENTS:
- Each topic MUST have a strong curiosity gap — a question, paradox, or surprising fact
- The title should be SHORT (under 60 characters), punchy, and scroll-stopping
- Think "things people don't know but would find fascinating"
- Topics should be specific, not generic. "Why Sleep Matters" is boring. "The Military Sleeps in 2 Minutes Using This" is specific.
- Vary the angles — mix historical, scientific, psychological, and practical
- Do NOT repeat or rephrase the examples below

EXAMPLES of good {niche} titles (for style reference only, do NOT reuse):
{examples_str}
{past_str}

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
                        reason=pick.get("reason", ""),
                    ))

            logger.info("Generated %d niche topics for '%s'", len(topics), niche)
            return topics[:count]

        except Exception as e:
            logger.warning("Niche topic generation failed: %s", e)
            return []

    def _curate_with_gpt(
        self,
        topics: List[TrendTopic],
        niche: Optional[str] = None,
        count: int = 5,
        past_topics: Optional[List[str]] = None,
    ) -> List[TrendTopic]:
        """Use GPT to curate, score, and reframe topics for short-form video.

        GPT evaluates with a short-form video lens:
        - Hook potential (can the first 3 seconds grab attention?)
        - Visual storytelling (can we create compelling AI-generated scenes?)
        - Curiosity gap (does the title make you NEED to watch?)
        - Shareability (would someone send this to a friend?)
        - Cross-platform signal (trending on multiple platforms = stronger)
        """
        # Build the topic list for GPT
        topic_lines = []
        for i, t in enumerate(topics):
            cross = f" [TRENDING ON {t.source_count} PLATFORMS]" if t.source_count > 1 else ""
            sub_info = f" (r/{t.subreddit})" if t.subreddit else ""
            topic_lines.append(
                f"{i+1}. [{t.source}{sub_info}] (score: {t.score}){cross} {t.title}"
            )

        topic_list = "\n".join(topic_lines)

        # Past topics for dedup
        past_str = ""
        if past_topics:
            past_str = "\n\nAVOID topics similar to these (already produced by this channel):\n" + \
                       "\n".join(f"- {t}" for t in past_topics[:15])

        niche_instruction = ""
        if niche:
            niche_instruction = f"""
NICHE REFRAMING: The channel's niche is "{niche}".
For EACH topic, reframe it through the lens of {niche}.
Example: If the niche is "stoicism" and the topic is "AI replacing jobs",
the video_angle should be something like "What Marcus Aurelius Would Say About AI Taking Your Job".
The angle should feel natural, not forced. If a topic truly cannot connect to {niche}, skip it."""

        prompt = f"""You are a viral short-form video strategist who has produced hundreds of videos with 1M+ views.

Below are today's trending topics from Google Trends, Reddit, YouTube, and HackerNews.
Topics marked [TRENDING ON N PLATFORMS] are appearing on multiple sources — these are stronger signals.

Pick the top {count} topics that would make the BEST 60-second documentary-style short-form videos.

WHAT MAKES A GREAT SHORT-FORM VIDEO TOPIC:
1. HOOK POWER: Can you write a first sentence that makes someone stop scrolling? "Did you know..." is weak. "A man faked his own murder using AI — and almost got away with it" is strong.
2. VISUAL POTENTIAL: We generate scenes with AI image generation. Topics about physical things (nature, space, objects, places, experiments) work better than abstract concepts.
3. STORY ARC: The best videos have a beginning (surprising hook), middle (explanation/story), and end (twist/payoff). Look for topics with a natural narrative.
4. CURIOSITY GAP: The title should make it IMPOSSIBLE not to watch. Use specific numbers, surprising contradictions, or "hidden truth" angles.
5. SHAREABILITY: Would someone send this to a friend saying "you HAVE to see this"?

RED FLAGS — SKIP THESE:
- Celebrity gossip, sports scores, political drama, breaking news (will be stale)
- Topics needing live footage or real faces (we use AI-generated images)
- Anything controversial, divisive, or requiring taking sides
- Generic "did you know" topics with no story arc
- Topics that are just "X is cool" without depth
{niche_instruction}
{past_str}

TRENDING TOPICS:
{topic_list}

For each pick, craft a video_angle title that:
- Uses specific details (numbers, names of things, places)
- Creates a curiosity gap or tension
- Is under 60 characters
- Would work as a TikTok/YouTube Shorts title

Respond with a JSON array of exactly {count} objects:
[
  {{
    "original_index": 1,
    "video_angle": "The reframed title optimized for a viral video",
    "viral_score": 8,
    "reason": "One sentence explaining the hook, story arc, and visual potential"
  }}
]

Pick diverse topics. Respond ONLY with the JSON array."""

        try:
            data = generate_json(prompt, temperature=0.7, max_tokens=1000)

            picks = []
            if isinstance(data, list):
                picks = data
            elif isinstance(data, dict):
                for key in ("topics", "results", "picks", "selected", "curated"):
                    if key in data and isinstance(data[key], list):
                        picks = data[key]
                        break
                if not picks:
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
                    topic.reason = pick.get("reason", "")
                    topic.title = topic.video_angle
                    curated.append(topic)

            curated.sort(key=lambda t: t.viral_score, reverse=True)
            return curated

        except Exception as e:
            logger.warning("GPT curation failed: %s", e)
            return []
