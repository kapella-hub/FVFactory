"""Tests for local FLUX image generation."""
import pytest
from unittest.mock import patch, MagicMock
from app.local_image_gen import LocalImageGenerator


@patch("app.local_image_gen.HAS_DIFFUSERS", True)
@patch("app.local_image_gen.FluxPipeline")
def test_generate_creates_image(mock_pipeline_cls, tmp_path):
    mock_pipe = MagicMock()
    mock_image = MagicMock()
    mock_pipe.return_value.images = [mock_image]
    mock_pipeline_cls.from_pretrained.return_value = mock_pipe

    gen = LocalImageGenerator.__new__(LocalImageGenerator)
    gen.pipe = mock_pipe
    gen.device = "cpu"

    output_path = str(tmp_path / "test.png")
    result = gen.generate("a sunset", 1080, 1920, output_path)
    assert result == output_path
    mock_image.save.assert_called_once_with(output_path)


@patch("app.local_image_gen.HAS_DIFFUSERS", True)
@patch("app.local_image_gen.FluxPipeline")
def test_generate_batch(mock_pipeline_cls, tmp_path):
    mock_pipe = MagicMock()
    mock_image = MagicMock()
    mock_pipe.return_value.images = [mock_image]
    mock_pipeline_cls.from_pretrained.return_value = mock_pipe

    gen = LocalImageGenerator.__new__(LocalImageGenerator)
    gen.pipe = mock_pipe
    gen.device = "cpu"

    results = gen.generate_batch(["cat", "dog"], 1080, 1920, str(tmp_path))
    assert len(results) == 2


def test_generate_without_diffusers():
    """Graceful error when diffusers not installed."""
    with patch("app.local_image_gen.HAS_DIFFUSERS", False):
        with pytest.raises(RuntimeError, match="diffusers"):
            LocalImageGenerator()
