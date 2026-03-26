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
