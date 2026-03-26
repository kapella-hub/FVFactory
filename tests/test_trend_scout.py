"""Tests for TrendScout - trend discovery and GPT curation."""

import json
from unittest.mock import patch, MagicMock

from app.trend_scout import TrendScout, TrendTopic


def test_trend_topic_model():
    topic = TrendTopic(
        title="Bitcoin hits new high",
        source="reddit",
        score=100,
        url="https://reddit.com/r/technology/123",
    )
    assert topic.title == "Bitcoin hits new high"
    assert topic.source == "reddit"
    assert topic.score == 100
    assert topic.video_angle == ""
    assert topic.viral_score == 0


def test_fetch_reddit_hot_returns_topics():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Scientists discover new species in the deep ocean",
                        "score": 5000,
                        "permalink": "/r/science/comments/abc/test",
                        "over_18": False,
                        "stickied": False,
                    }
                },
                {
                    "data": {
                        "title": "NSFW post",
                        "score": 3000,
                        "permalink": "/r/science/comments/def/nsfw",
                        "over_18": True,
                        "stickied": False,
                    }
                },
            ]
        }
    }

    with patch("app.trend_scout.requests.get", return_value=mock_response):
        scout = TrendScout()
        topics = scout._fetch_reddit_hot(["science"])
        assert len(topics) == 1
        assert topics[0].title == "Scientists discover new species in the deep ocean"
        assert topics[0].source == "reddit"


def test_reddit_filters_stickied_and_short_titles():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Weekly Discussion Megathread",
                        "score": 100,
                        "permalink": "/r/test/1",
                        "over_18": False,
                        "stickied": True,
                    }
                },
                {
                    "data": {
                        "title": "Short",
                        "score": 200,
                        "permalink": "/r/test/2",
                        "over_18": False,
                        "stickied": False,
                    }
                },
                {
                    "data": {
                        "title": "Monthly mod post about rules",
                        "score": 50,
                        "permalink": "/r/test/3",
                        "over_18": False,
                        "stickied": False,
                    }
                },
                {
                    "data": {
                        "title": "A fascinating new discovery about the human brain that changes everything",
                        "score": 8000,
                        "permalink": "/r/test/4",
                        "over_18": False,
                        "stickied": False,
                    }
                },
            ]
        }
    }

    with patch("app.trend_scout.requests.get", return_value=mock_response):
        scout = TrendScout()
        topics = scout._fetch_reddit_hot(["test"])
        # Stickied, short title, and "monthly...mod post" should be filtered
        assert len(topics) == 1
        assert "brain" in topics[0].title


def test_fetch_google_trends_graceful_failure():
    with patch("pytrends.request.TrendReq") as mock_tr:
        mock_tr.side_effect = Exception("pytrends broke")
        scout = TrendScout()
        topics = scout._fetch_google_trends()
        assert topics == []


def test_fetch_youtube_trending_with_api_key():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "items": [
            {
                "id": "abc123",
                "snippet": {"title": "How Black Holes Actually Work"},
                "statistics": {"viewCount": "2500000"},
            },
            {
                "id": "def456",
                "snippet": {"title": "Why Nobody Talks About This Ocean Mystery"},
                "statistics": {"viewCount": "800000"},
            },
        ]
    }

    with patch("app.trend_scout.requests.get", return_value=mock_response), \
         patch("app.trend_scout.settings") as mock_settings:
        mock_settings.youtube_api_key = "test_key"
        scout = TrendScout()
        topics = scout._fetch_youtube_trending()

        assert len(topics) == 2
        assert topics[0].source == "youtube"
        assert topics[0].score == 250  # 2500000 / 10000
        assert "Black Holes" in topics[0].title


def test_fetch_youtube_trending_no_api_key():
    with patch("app.trend_scout.settings") as mock_settings:
        mock_settings.youtube_api_key = ""
        scout = TrendScout()
        topics = scout._fetch_youtube_trending()
        assert topics == []


def test_discover_topics_combines_sources():
    scout = TrendScout()
    reddit_topics = [
        TrendTopic(title="Topic A from Reddit", source="reddit", score=100),
        TrendTopic(title="Topic B from Reddit", source="reddit", score=50),
    ]
    google_topics = [
        TrendTopic(title="Topic C from Google", source="google_trends", score=80),
    ]
    youtube_topics = [
        TrendTopic(title="Topic D from YouTube", source="youtube", score=200),
    ]

    with patch.object(scout, "_fetch_reddit_hot", return_value=reddit_topics), \
         patch.object(scout, "_fetch_google_trends", return_value=google_topics), \
         patch.object(scout, "_fetch_youtube_trending", return_value=youtube_topics), \
         patch.object(scout, "_curate_with_gpt", return_value=[]):
        # GPT returns empty, so falls back to raw sort
        topics = scout.discover_topics(count=4)
        assert len(topics) == 4
        assert topics[0].title == "Topic D from YouTube"  # highest score
        assert topics[0].source == "youtube"


def test_curate_with_gpt_reframes_topics():
    scout = TrendScout()
    topics = [
        TrendTopic(title="AI is changing everything", source="reddit", score=5000),
        TrendTopic(title="New species found in ocean", source="google_trends", score=80),
        TrendTopic(title="How memory works in the brain", source="youtube", score=300),
    ]

    mock_data = {
        "topics": [
            {
                "original_index": 1,
                "video_angle": "Why AI Will Make 40% of Jobs Obsolete by 2030",
                "viral_score": 9,
                "reason": "Fear + specific stat = high curiosity gap",
            },
            {
                "original_index": 3,
                "video_angle": "Your Brain Deletes Memories While You Sleep",
                "viral_score": 8,
                "reason": "Surprising personal fact everyone relates to",
            },
        ]
    }

    with patch("app.trend_scout.generate_json", return_value=mock_data):
        curated = scout._curate_with_gpt(topics, niche=None, count=2)

        assert len(curated) == 2
        assert curated[0].viral_score == 9
        assert "AI" in curated[0].title
        assert curated[1].viral_score == 8
        assert "Brain" in curated[1].title


def test_curate_with_gpt_niche_reframing():
    scout = TrendScout()
    topics = [
        TrendTopic(title="AI replacing jobs", source="reddit", score=5000),
    ]

    mock_data = {
        "topics": [
            {
                "original_index": 1,
                "video_angle": "What Marcus Aurelius Would Say About AI Taking Your Job",
                "viral_score": 9,
                "reason": "Stoic lens on modern anxiety",
            },
        ]
    }

    with patch("app.trend_scout.generate_json", return_value=mock_data):
        curated = scout._curate_with_gpt(topics, niche="stoicism", count=1)

        assert len(curated) == 1
        assert "Marcus Aurelius" in curated[0].title


def test_curate_with_gpt_failure_returns_empty():
    scout = TrendScout()
    topics = [TrendTopic(title="Test", source="reddit", score=100)]

    with patch("app.trend_scout.generate_json", side_effect=Exception("API down")):
        result = scout._curate_with_gpt(topics, count=1)
        assert result == []
