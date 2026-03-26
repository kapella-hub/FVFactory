"""Tests for video performance tracker."""

import json
from unittest.mock import patch, MagicMock

import pytest

from app.tracker import (
    _extract_youtube_id,
    get_video_tracking,
    save_link,
    save_manual_stats,
    fetch_youtube_stats,
    get_performance_summary,
    _load_tracking,
    _save_tracking,
    TRACKING_FILE,
)


class TestYouTubeIdExtraction:
    def test_shorts_url(self):
        assert _extract_youtube_id("https://youtube.com/shorts/abc12345678") == "abc12345678"

    def test_watch_url(self):
        assert _extract_youtube_id("https://www.youtube.com/watch?v=abc12345678") == "abc12345678"

    def test_short_url(self):
        assert _extract_youtube_id("https://youtu.be/abc12345678") == "abc12345678"

    def test_invalid_url(self):
        assert _extract_youtube_id("https://tiktok.com/@user/video/123") is None

    def test_empty_string(self):
        assert _extract_youtube_id("") is None


class TestTrackerStorage:
    def test_save_and_load_link(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            save_link("test_video_1", "youtube", "https://youtube.com/shorts/abc12345678")

            tracking = get_video_tracking("test_video_1")
            assert tracking["links"]["youtube"] == "https://youtube.com/shorts/abc12345678"

    def test_save_multiple_platforms(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            save_link("vid1", "youtube", "https://youtube.com/shorts/abc")
            save_link("vid1", "tiktok", "https://tiktok.com/@user/video/123")
            save_link("vid1", "instagram", "https://instagram.com/reel/xyz")

            tracking = get_video_tracking("vid1")
            assert len(tracking["links"]) == 3

    def test_save_manual_stats(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            save_manual_stats("vid1", "tiktok", views=1500, likes=200, comments=30)

            tracking = get_video_tracking("vid1")
            assert tracking["latest_stats"]["tiktok"]["views"] == 1500
            assert len(tracking["stats_history"]) == 1

    def test_multiple_stat_snapshots(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            save_manual_stats("vid1", "tiktok", views=100)
            save_manual_stats("vid1", "tiktok", views=500)
            save_manual_stats("vid1", "tiktok", views=1200)

            tracking = get_video_tracking("vid1")
            assert len(tracking["stats_history"]) == 3
            assert tracking["latest_stats"]["tiktok"]["views"] == 1200

    def test_get_nonexistent_video(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            tracking = get_video_tracking("nonexistent")
            assert tracking["links"] == {}
            assert tracking["stats_history"] == []


class TestYouTubeFetch:
    def test_fetch_no_link(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            result = fetch_youtube_stats("no_link_video")
            assert result is None

    def test_fetch_no_api_key(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file), \
             patch("app.tracker.settings") as mock_settings:
            mock_settings.youtube_api_key = ""
            mock_settings.output_dir = str(tmp_path)

            # Save a link first
            _save_tracking({"videos": {"vid1": {
                "links": {"youtube": "https://youtube.com/shorts/abc12345678"},
                "stats_history": [],
                "latest_stats": {},
            }}})

            result = fetch_youtube_stats("vid1")
            assert result is None

    @patch("app.tracker.requests")
    def test_fetch_success(self, mock_requests, tmp_path):
        tracking_file = tmp_path / "tracking.json"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "items": [{
                "statistics": {
                    "viewCount": "12500",
                    "likeCount": "890",
                    "commentCount": "45",
                }
            }]
        }
        mock_requests.get.return_value = mock_resp

        with patch("app.tracker.TRACKING_FILE", tracking_file), \
             patch("app.tracker.settings") as mock_settings:
            mock_settings.youtube_api_key = "test_api_key"
            mock_settings.output_dir = str(tmp_path)

            _save_tracking({"videos": {"vid1": {
                "links": {"youtube": "https://youtube.com/shorts/abc12345678"},
                "stats_history": [],
                "latest_stats": {},
            }}})

            result = fetch_youtube_stats("vid1")

            assert result is not None
            assert result["views"] == 12500
            assert result["likes"] == 890
            assert result["comments"] == 45


class TestPerformanceSummary:
    def test_empty_summary(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            summary = get_performance_summary()
            assert summary["total_views"] == 0
            assert summary["tracked_count"] == 0

    def test_summary_with_data(self, tmp_path):
        tracking_file = tmp_path / "tracking.json"
        with patch("app.tracker.TRACKING_FILE", tracking_file):
            _save_tracking({"videos": {
                "vid1": {
                    "links": {"youtube": "https://youtube.com/shorts/abc"},
                    "stats_history": [],
                    "latest_stats": {
                        "youtube": {"views": 5000, "likes": 300, "comments": 20, "shares": 0},
                    },
                },
                "vid2": {
                    "links": {"tiktok": "https://tiktok.com/v/123"},
                    "stats_history": [],
                    "latest_stats": {
                        "tiktok": {"views": 15000, "likes": 1200, "comments": 80, "shares": 50},
                    },
                },
            }})

            summary = get_performance_summary()
            assert summary["total_views"] == 20000
            assert summary["total_likes"] == 1500
            assert summary["tracked_count"] == 2
            assert summary["top_video"] == "vid2"
            assert summary["top_views"] == 15000
