"""Cost Tracker - Logs per-video API costs to output/cost_log.json"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class CostTracker:
    """Tracks API costs per video and persists to JSON."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.output_dir / "cost_log.json"
        self._costs = self._load()

    @property
    def unit_costs(self) -> dict:
        return {
            "flux_image": settings.cost_flux_image,
            "minimax_video": settings.cost_minimax_video,
            "elevenlabs_tts": settings.cost_elevenlabs_per_1k_chars,
            "openai_gpt4o": settings.cost_openai_gpt4o,
            "openai_tts": settings.cost_openai_tts_per_1k_chars,
            "whisper": 0.00,
            "local_image": settings.cost_local_image,       # $0.00
            "local_video": settings.cost_local_video,       # $0.00
            "claude_cli": settings.cost_claude_cli,         # $0.00
        }

    def _load(self) -> dict:
        if self.log_path.exists():
            with open(self.log_path) as f:
                return json.load(f)
        return {"schema_version": 1, "videos": {}}

    def log_cost(self, video_id: str, item: str, quantity: int = 1) -> None:
        if item not in self.unit_costs:
            raise ValueError(f"Unknown cost item: {item}. Valid: {list(self.unit_costs.keys())}")

        cost = self.unit_costs[item] * quantity

        if video_id not in self._costs["videos"]:
            self._costs["videos"][video_id] = {"items": [], "total": 0.0}

        self._costs["videos"][video_id]["items"].append({
            "item": item,
            "quantity": quantity,
            "unit_cost": self.unit_costs[item],
            "cost": round(cost, 4),
        })
        self._costs["videos"][video_id]["total"] = round(
            self._costs["videos"][video_id]["total"] + cost, 4
        )

        logger.debug(f"Cost: {item} x{quantity} = ${cost:.4f} (video: {video_id})")

    def get_video_cost(self, video_id: str) -> float:
        if video_id not in self._costs["videos"]:
            return 0.0
        return self._costs["videos"][video_id]["total"]

    def get_total_costs(self) -> dict:
        total = sum(v["total"] for v in self._costs["videos"].values())
        return {
            "total": round(total, 4),
            "video_count": len(self._costs["videos"]),
            "videos": {vid: v["total"] for vid, v in self._costs["videos"].items()},
        }

    def save(self) -> None:
        with open(self.log_path, "w") as f:
            json.dump(self._costs, f, indent=2)
        logger.info(f"Cost log saved to {self.log_path}")
