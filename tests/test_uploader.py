"""Tests for YouTube Shorts uploader"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

from app.uploader import (
    YouTubeUploader,
    UploaderError,
    NICHE_CATEGORY_MAP,
    YOUTUBE_CATEGORY_EDUCATION,
    YOUTUBE_CATEGORY_ENTERTAINMENT,
    YOUTUBE_CATEGORY_SCIENCE,
)


class TestYouTubeUploader:
    """Tests for YouTubeUploader class."""

    def test_niche_category_mapping(self):
        """Verify niche-to-category mappings exist and are valid."""
        assert NICHE_CATEGORY_MAP["stoicism"] == YOUTUBE_CATEGORY_EDUCATION
        assert NICHE_CATEGORY_MAP["gaming"] == YOUTUBE_CATEGORY_ENTERTAINMENT
        assert NICHE_CATEGORY_MAP["science"] == YOUTUBE_CATEGORY_SCIENCE

    def test_load_metadata_returns_dict(self, tmp_path):
        """Test metadata loading from JSON file."""
        meta_dir = tmp_path / "metadata"
        meta_dir.mkdir()
        meta_file = meta_dir / "test_video.json"
        meta_file.write_text(json.dumps({
            "title_youtube": "Test Title",
            "description": "Test description",
            "hashtags": ["#test", "#video"],
        }))

        with patch("app.uploader.settings") as mock_settings:
            mock_settings.output_dir = str(tmp_path)
            mock_settings.youtube_client_secrets = "client_secrets.json"
            mock_settings.youtube_token_path = "youtube_token.json"
            uploader = YouTubeUploader()
            metadata = uploader._load_metadata("test_video")

        assert metadata["title_youtube"] == "Test Title"
        assert metadata["description"] == "Test description"
        assert len(metadata["hashtags"]) == 2

    def test_load_metadata_missing_file(self, tmp_path):
        """Test graceful handling of missing metadata."""
        with patch("app.uploader.settings") as mock_settings:
            mock_settings.output_dir = str(tmp_path)
            mock_settings.youtube_client_secrets = "client_secrets.json"
            mock_settings.youtube_token_path = "youtube_token.json"
            uploader = YouTubeUploader()
            metadata = uploader._load_metadata("nonexistent")

        assert metadata == {}

    def test_upload_missing_video_raises(self, tmp_path):
        """Test that uploading a nonexistent file raises UploaderError."""
        with patch("app.uploader.settings") as mock_settings:
            mock_settings.youtube_client_secrets = "client_secrets.json"
            mock_settings.youtube_token_path = str(tmp_path / "token.json")
            mock_settings.youtube_privacy = "private"
            mock_settings.output_dir = str(tmp_path)
            uploader = YouTubeUploader()

            with pytest.raises(UploaderError, match="Video file not found"):
                uploader.upload("/nonexistent/video.mp4", "test_id")

    def test_auth_missing_secrets_raises(self, tmp_path):
        """Test that auth without client_secrets.json raises UploaderError."""
        with patch("app.uploader.settings") as mock_settings:
            mock_settings.youtube_client_secrets = str(tmp_path / "missing.json")
            mock_settings.youtube_token_path = str(tmp_path / "token.json")
            uploader = YouTubeUploader()

            with pytest.raises(UploaderError, match="Client secrets file not found"):
                uploader.authenticate()

    def test_get_authenticated_service_no_token_raises(self, tmp_path):
        """Test that missing token file raises UploaderError."""
        with patch("app.uploader.settings") as mock_settings:
            mock_settings.youtube_client_secrets = "client_secrets.json"
            mock_settings.youtube_token_path = str(tmp_path / "no_token.json")
            uploader = YouTubeUploader()

            with pytest.raises(UploaderError, match="token not found"):
                uploader._get_authenticated_service()

    @patch("app.uploader.YouTubeUploader._get_authenticated_service")
    @patch("app.uploader.YouTubeUploader._upload_thumbnail")
    def test_upload_success(self, mock_thumb, mock_auth, tmp_path):
        """Test successful upload flow with mocked API."""
        # Create a fake video file
        video_file = tmp_path / "test_video.mp4"
        video_file.write_bytes(b"fake video content")

        # Create metadata
        meta_dir = tmp_path / "metadata"
        meta_dir.mkdir()
        (meta_dir / "test_video.json").write_text(json.dumps({
            "title_youtube": "My Test Video",
            "description": "Great video",
            "hashtags": ["#test"],
        }))

        # Mock YouTube API
        mock_youtube = MagicMock()
        mock_auth.return_value = mock_youtube

        mock_request = MagicMock()
        mock_request.next_chunk.return_value = (None, {"id": "abc123"})
        mock_youtube.videos.return_value.insert.return_value = mock_request

        with patch("app.uploader.settings") as mock_settings:
            mock_settings.youtube_client_secrets = "client_secrets.json"
            mock_settings.youtube_token_path = str(tmp_path / "token.json")
            mock_settings.youtube_privacy = "public"
            mock_settings.output_dir = str(tmp_path)

            uploader = YouTubeUploader()
            url = uploader.upload(str(video_file), "test_video", niche="stoicism")

        assert url == "https://youtube.com/shorts/abc123"
        mock_thumb.assert_called_once()
