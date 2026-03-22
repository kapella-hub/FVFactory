"""Trend Scout - Discovers trending topics from Google Trends and Reddit"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class TrendTopic:
    """A discovered trending topic."""
    title: str
    source: str  # "reddit" or "google_trends"
    score: int = 0
    url: str = ""


class TrendScout:
    """Discovers trending topics from multiple sources."""

    REDDIT_BASE = "https://www.reddit.com"
    USER_AGENT = "FVFactory/2.0"

    def discover_topics(self, niche: Optional[str] = None, count: int = 0) -> List[TrendTopic]:
        if count <= 0:
            count = settings.trend_count

        all_topics: List[TrendTopic] = []

        google_topics = self._fetch_google_trends()
        all_topics.extend(google_topics)
        logger.info(f"Google Trends: {len(google_topics)} topics")

        subreddits = settings.reddit_subreddits.split(",")
        reddit_topics = self._fetch_reddit_hot(subreddits)
        all_topics.extend(reddit_topics)
        logger.info(f"Reddit: {len(reddit_topics)} topics")

        all_topics.sort(key=lambda t: t.score, reverse=True)

        result = all_topics[:count]
        logger.info(f"Top {len(result)} trending topics discovered")
        return result

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
        """Fetch hot posts from Reddit. Filters NSFW."""
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
                    title = post.get("title", "").strip()
                    if not title:
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
