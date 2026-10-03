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
        unit = self.unit_costs[item]
        self._append(video_id, {"item": item, "quantity": quantity, "unit_cost": unit,
                                "cost": round(unit * quantity, 4)})
        logger.debug(f"Cost: {item} x{quantity} = ${unit * quantity:.4f} (video: {video_id})")

    def clip_unit_cost(self, model: str, seconds: float) -> float:
        price = settings.clip_pricing.get(model)
        if price is None:
            raise ValueError(f"No clip pricing for model {model!r}. Known: {sorted(settings.clip_pricing)}")
        if "per_second" in price:
            return round(float(price["per_second"]) * float(seconds), 4)
        return float(price.get("per_clip", 0.0))

    def log_clip(self, video_id: str, model: str, seconds: float, count: int = 1) -> float:
        unit = self.clip_unit_cost(model, seconds)
        cost = round(unit * count, 4)
        self._append(video_id, {"item": f"clip:{model}", "quantity": count, "seconds": seconds,
                                "unit_cost": unit, "cost": cost})
        return cost

    def get_video_items(self, video_id: str) -> list:
        return list(self._costs["videos"].get(video_id, {}).get("items", []))

    def _append(self, video_id: str, entry: dict) -> None:
        video = self._costs["videos"].setdefault(video_id, {"items": [], "total": 0.0})
        video["items"].append(entry)
        video["total"] = round(video["total"] + entry["cost"], 4)

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
