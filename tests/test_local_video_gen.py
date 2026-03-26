"""Tests for local Wan2.1 video generation."""
import pytest
from unittest.mock import patch, MagicMock


def test_generate_without_diffusers():
    """Graceful error when diffusers not installed."""
    with patch("app.local_video_gen.HAS_DIFFUSERS", False):
        from app.local_video_gen import LocalVideoGenerator
        with pytest.raises(RuntimeError, match="diffusers"):
            LocalVideoGenerator()


def test_invalid_model_size():
    """Error on invalid model size."""
    with patch("app.local_video_gen.HAS_DIFFUSERS", True):
        from app.local_video_gen import LocalVideoGenerator
        with pytest.raises(ValueError, match="Unknown Wan model size"):
            LocalVideoGenerator(model_size="999b")


@patch("app.local_video_gen.HAS_DIFFUSERS", True)
@patch("app.local_video_gen.export_to_video")
@patch("app.local_video_gen.load_image")
def test_generate_creates_video(mock_load, mock_export, tmp_path):
    from app.local_video_gen import LocalVideoGenerator
    import numpy as np

    gen = LocalVideoGenerator.__new__(LocalVideoGenerator)
    gen.pipe = MagicMock()
    gen.device = "cpu"
    gen.model_size = "1.3b"
    gen.model_id = "test"

    mock_image = MagicMock()
    mock_load.return_value = mock_image
    mock_frames = [np.zeros((480, 720, 3), dtype=np.uint8)] * 16
    gen.pipe.return_value.frames = [mock_frames]

    output_path = str(tmp_path / "test.mp4")
    result = gen.generate("/tmp/img.png", "zoom in slowly", output_path)
    assert result == output_path
    mock_export.assert_called_once()
