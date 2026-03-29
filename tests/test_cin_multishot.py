"""Tests for multi-shot editor."""
import pytest
import numpy as np
from PIL import Image


def test_extract_shots():
    from app.cin.multishot import extract_shots
    img = np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8)
    shots = extract_shots(img)
    assert len(shots) >= 3
    for shot in shots:
        assert "crop" in shot
        assert "type" in shot
        assert shot["crop"].shape[0] > 0 and shot["crop"].shape[1] > 0


def test_plan_cuts():
    from app.cin.multishot import plan_cuts
    # Long scene with spread-out emphasis — should get at least 1 cut
    emphasis = [2.0, 6.0, 9.0]
    scene_duration = 12.0
    cuts = plan_cuts(scene_duration, emphasis_points=emphasis)
    assert len(cuts) >= 1
    assert cuts[0]["shot_type"] == "wide"  # always starts wide
    for cut in cuts:
        assert "time" in cut
        assert "shot_type" in cut
