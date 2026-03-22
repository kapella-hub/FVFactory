import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.metadata_gen import MetadataGenerator


def test_generate_metadata_returns_dict():
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps({
        "title_tiktok": "You Won't Believe This!",
        "title_youtube": "The Shocking Truth About Bitcoin",
        "description": "In this video we explore...",
        "hashtags": ["#bitcoin", "#crypto", "#finance"],
        "best_posting_time": "Tuesday 6-8 PM EST",
    })

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response

    gen = MetadataGenerator()
    gen.client = mock_client

    result = gen.generate_metadata(
        topic="Bitcoin price history",
        hook="Did you know Bitcoin was once worth $0?",
        keywords=["bitcoin", "crypto"],
    )

    assert "title_tiktok" in result
    assert "hashtags" in result
    assert isinstance(result["hashtags"], list)


def test_save_metadata_creates_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MetadataGenerator(output_dir=tmpdir)
        metadata = {
            "title_tiktok": "Test Title",
            "hashtags": ["#test"],
        }
        gen.save_metadata("test_video_001", metadata)

        path = Path(tmpdir) / "metadata" / "test_video_001.json"
        assert path.exists()

        with open(path) as f:
            saved = json.load(f)
        assert saved["title_tiktok"] == "Test Title"


def test_fallback_metadata_when_no_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        gen = MetadataGenerator(output_dir=tmpdir)
        gen.client = None

        result = gen.generate_metadata(
            topic="Test Topic",
            hook="Test Hook",
            keywords=["keyword1", "keyword2"],
        )

        assert result["title_tiktok"] == "Test Topic"
        assert "#keyword1" in result["hashtags"]
