"""Tests for depth extraction module."""
import pytest
import numpy as np
from PIL import Image


def test_estimate_depth_returns_array(tmp_path):
    from app.cin.depth import estimate_depth
    img_path = str(tmp_path / "test.png")
    Image.fromarray(np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)).save(img_path)
    depth = estimate_depth(img_path)
    assert isinstance(depth, np.ndarray)
    assert depth.shape[:2] == (256, 256)


def test_split_into_layers():
    from app.cin.depth import split_into_layers
    img = np.random.randint(0, 255, (100, 100, 3), dtype=np.uint8)
    depth = np.random.rand(100, 100).astype(np.float32)
    layers = split_into_layers(img, depth, num_layers=3)
    assert len(layers) == 3
    for layer in layers:
        assert layer["rgba"].shape == (100, 100, 4)
        assert "depth_range" in layer
