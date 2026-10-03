import json
import tempfile
from pathlib import Path

from app.cost_tracker import CostTracker


def test_log_single_cost():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        data = tracker.get_video_cost("video_001")
        assert data == 0.15  # 5 * 0.03


def test_log_multiple_items():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        tracker.log_cost("video_001", "openai_gpt4o", quantity=1)
        total = tracker.get_video_cost("video_001")
        assert abs(total - 0.155) < 0.001


def test_cost_log_persists_to_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        tracker.save()

        log_path = Path(tmpdir) / "cost_log.json"
        assert log_path.exists()

        with open(log_path) as f:
            data = json.load(f)
        assert "video_001" in data["videos"]


def test_get_total_costs():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        tracker.log_cost("video_001", "flux_image", quantity=5)
        tracker.log_cost("video_002", "flux_image", quantity=5)
        totals = tracker.get_total_costs()
        assert abs(totals["total"] - 0.30) < 0.001
        assert totals["video_count"] == 2


def test_unknown_cost_item_raises():
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = CostTracker(output_dir=tmpdir)
        try:
            tracker.log_cost("video_001", "nonexistent_service")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass


def test_local_provider_costs_are_zero():
    """Local providers should have $0.00 cost."""
    tracker = CostTracker()
    assert tracker.unit_costs["local_image"] == 0.0
    assert tracker.unit_costs["local_video"] == 0.0
    assert tracker.unit_costs["claude_cli"] == 0.0


import pytest


def test_hailuo_clip_priced_per_clip(tmp_path):
    tracker = CostTracker(output_dir=str(tmp_path))
    assert tracker.log_clip("v1", "hailuo", seconds=6.0, count=3) == 1.5
    assert tracker.get_video_cost("v1") == 1.5
    item = tracker.get_video_items("v1")[0]
    assert item["item"] == "clip:hailuo"
    assert item["quantity"] == 3
    assert item["unit_cost"] == 0.5


def test_kling_clip_priced_per_second(tmp_path):
    tracker = CostTracker(output_dir=str(tmp_path))
    assert tracker.log_clip("v1", "kling", seconds=10.0) == 0.45


def test_unknown_clip_model_raises(tmp_path):
    with pytest.raises(ValueError):
        CostTracker(output_dir=str(tmp_path)).log_clip("v1", "sora", 5.0)


def test_flat_minimax_item_removed(tmp_path):
    assert "minimax_video" not in CostTracker(output_dir=str(tmp_path)).unit_costs
