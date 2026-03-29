"""Tests for enhanced local video generation."""
import pytest
from app.local_video_gen import LocalVideoGenerator


def test_init():
    gen = LocalVideoGenerator()
    assert gen.fps == 24


def test_generate_creates_video(tmp_path):
    from PIL import Image
    import numpy as np

    # Create test image
    img = Image.fromarray(np.random.randint(50, 200, (1920, 1080, 3), dtype=np.uint8))
    img_path = str(tmp_path / "test.png")
    img.save(img_path)

    gen = LocalVideoGenerator()
    output = str(tmp_path / "test.mp4")
    result = gen.generate(img_path, "zoom in", output, duration=1.0)
    assert result == output
    assert (tmp_path / "test.mp4").exists()
    assert (tmp_path / "test.mp4").stat().st_size > 0


def test_unload_is_noop():
    gen = LocalVideoGenerator()
    gen.unload()  # should not raise
