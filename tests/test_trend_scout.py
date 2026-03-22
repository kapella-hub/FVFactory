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


def test_fetch_reddit_hot_returns_topics():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Scientists discover new species",
                        "score": 5000,
                        "permalink": "/r/science/comments/abc/test",
                        "over_18": False,
                    }
                },
                {
                    "data": {
                        "title": "NSFW post",
                        "score": 3000,
                        "permalink": "/r/science/comments/def/nsfw",
                        "over_18": True,
                    }
                },
            ]
        }
    }

    with patch("app.trend_scout.requests.get", return_value=mock_response):
        scout = TrendScout()
        topics = scout._fetch_reddit_hot(["science"])
        assert len(topics) == 1
        assert topics[0].title == "Scientists discover new species"
        assert topics[0].source == "reddit"


def test_fetch_google_trends_graceful_failure():
    with patch("pytrends.request.TrendReq") as mock_tr:
        mock_tr.side_effect = Exception("pytrends broke")
        scout = TrendScout()
        topics = scout._fetch_google_trends()
        assert topics == []


def test_discover_topics_combines_sources():
    scout = TrendScout()
    reddit_topics = [
        TrendTopic(title="Topic A", source="reddit", score=100),
        TrendTopic(title="Topic B", source="reddit", score=50),
    ]
    google_topics = [
        TrendTopic(title="Topic C", source="google_trends", score=80),
    ]

    with patch.object(scout, "_fetch_reddit_hot", return_value=reddit_topics):
        with patch.object(scout, "_fetch_google_trends", return_value=google_topics):
            topics = scout.discover_topics(count=3)
            assert len(topics) == 3
            assert topics[0].title == "Topic A"
            assert topics[1].title == "Topic C"
            assert topics[2].title == "Topic B"
