"""
Video Performance Tracker - Monitor video stats across platforms.

Stores platform links and fetches/records performance metrics over time.
YouTube stats are fetched automatically via Data API v3 (API key only).
TikTok/Instagram stats are stored manually.

Data stored in: output/tracking.json
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from app.config import settings

logger = logging.getLogger(__name__)

TRACKING_FILE = Path(settings.output_dir) / "tracking.json"


def _load_tracking() -> dict:
    """Load tracking data from disk."""
    if TRACKING_FILE.exists():
        try:
            return json.loads(TRACKING_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"videos": {}}


def _save_tracking(data: dict):
    """Save tracking data to disk."""
    TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKING_FILE.write_text(json.dumps(data, indent=2, default=str))


def _extract_youtube_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})",
        r"youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


# =============================================================================
# PUBLIC API
# =============================================================================


def get_video_tracking(video_id: str) -> dict:
    """Get tracking data for a specific video."""
    data = _load_tracking()
    return data["videos"].get(video_id, {
        "links": {},
        "stats_history": [],
        "latest_stats": {},
    })


def get_all_tracking() -> dict:
    """Get tracking data for all videos."""
    return _load_tracking()


def save_link(video_id: str, platform: str, url: str):
    """Save a platform link for a video.

    Args:
        video_id: FVFactory video identifier
        platform: One of 'youtube', 'tiktok', 'instagram'
        url: The platform URL
    """
    data = _load_tracking()
    if video_id not in data["videos"]:
        data["videos"][video_id] = {
            "links": {},
            "stats_history": [],
            "latest_stats": {},
        }

    data["videos"][video_id]["links"][platform] = url
    _save_tracking(data)
    logger.info(f"Saved {platform} link for {video_id}: {url}")


def save_manual_stats(video_id: str, platform: str, views: int = 0,
                      likes: int = 0, comments: int = 0, shares: int = 0):
    """Manually save stats for TikTok or Instagram.

    Args:
        video_id: FVFactory video identifier
        platform: 'tiktok' or 'instagram'
        views, likes, comments, shares: Stat values
    """
    data = _load_tracking()
    if video_id not in data["videos"]:
        data["videos"][video_id] = {
            "links": {},
            "stats_history": [],
            "latest_stats": {},
        }

    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "platform": platform,
        "timestamp": now,
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
    }

    data["videos"][video_id]["stats_history"].append(snapshot)
    data["videos"][video_id]["latest_stats"][platform] = snapshot
    _save_tracking(data)
    logger.info(f"Saved manual {platform} stats for {video_id}: {views} views")


def fetch_youtube_stats(video_id: str) -> Optional[dict]:
    """Fetch YouTube stats for a video using the Data API v3.

    Requires YOUTUBE_API_KEY in config (not OAuth — just a simple API key).

    Returns:
        dict with views, likes, comments, or None on failure.
    """
    tracking = get_video_tracking(video_id)
    yt_url = tracking.get("links", {}).get("youtube")
    if not yt_url:
        logger.debug(f"No YouTube link for {video_id}")
        return None

    yt_video_id = _extract_youtube_id(yt_url)
    if not yt_video_id:
        logger.warning(f"Could not extract YouTube ID from: {yt_url}")
        return None

    api_key = settings.youtube_api_key
    if not api_key:
        logger.warning("YOUTUBE_API_KEY not set — cannot fetch stats")
        return None

    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "statistics",
                "id": yt_video_id,
                "key": api_key,
            },
            timeout=10,
        )

        if resp.status_code != 200:
            logger.warning(f"YouTube API error {resp.status_code}: {resp.text[:200]}")
            return None

        items = resp.json().get("items", [])
        if not items:
            logger.warning(f"No YouTube video found for ID: {yt_video_id}")
            return None

        stats = items[0].get("statistics", {})
        result = {
            "platform": "youtube",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "views": int(stats.get("viewCount", 0)),
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "shares": 0,  # Not available via API
        }

        # Store the snapshot
        data = _load_tracking()
        if video_id not in data["videos"]:
            data["videos"][video_id] = {
                "links": {},
                "stats_history": [],
                "latest_stats": {},
            }

        data["videos"][video_id]["stats_history"].append(result)
        data["videos"][video_id]["latest_stats"]["youtube"] = result
        _save_tracking(data)

        logger.info(f"YouTube stats for {video_id}: {result['views']} views, {result['likes']} likes")
        return result

    except Exception as e:
        logger.warning(f"Failed to fetch YouTube stats: {e}")
        return None


def fetch_all_youtube_stats() -> int:
    """Fetch YouTube stats for all tracked videos. Returns count of successful fetches."""
    data = _load_tracking()
    fetched = 0
    for video_id, info in data["videos"].items():
        if info.get("links", {}).get("youtube"):
            result = fetch_youtube_stats(video_id)
            if result:
                fetched += 1
    return fetched


def get_performance_summary() -> dict:
    """Get aggregate performance stats across all tracked videos."""
    data = _load_tracking()

    total_views = 0
    total_likes = 0
    total_comments = 0
    tracked_count = 0
    platform_counts = {"youtube": 0, "tiktok": 0, "instagram": 0}
    top_video = None
    top_views = 0

    for video_id, info in data["videos"].items():
        links = info.get("links", {})
        for platform in platform_counts:
            if platform in links:
                platform_counts[platform] += 1

        latest = info.get("latest_stats", {})
        if latest:
            tracked_count += 1
            for platform, stats in latest.items():
                views = stats.get("views", 0)
                total_views += views
                total_likes += stats.get("likes", 0)
                total_comments += stats.get("comments", 0)

                if views > top_views:
                    top_views = views
                    top_video = video_id

    return {
        "total_views": total_views,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "tracked_count": tracked_count,
        "platform_counts": platform_counts,
        "top_video": top_video,
        "top_views": top_views,
    }
