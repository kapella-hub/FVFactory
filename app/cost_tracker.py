"""Cost Tracker - Logs per-video API costs to output/cost_log.json"""

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from app.config import settings
from app.fsutil import atomic_write_text

logger = logging.getLogger(__name__)

# Serialises load-modify-save across tracker instances in this process (concurrent runs).
_LOCK = threading.Lock()


def unit_costs() -> dict:
    """USD per unit of every non-clip cost item, read from settings at call time."""
    return {
        "flux_image": settings.cost_flux_image,
        "elevenlabs_tts": settings.cost_elevenlabs_per_1k_chars,
        "openai_gpt4o": settings.cost_openai_gpt4o,
        "openai_tts": settings.cost_openai_tts_per_1k_chars,
        "whisper": 0.00,
        "local_image": settings.cost_local_image,       # $0.00
        "local_video": settings.cost_local_video,       # $0.00
        "claude_cli": settings.cost_claude_cli,         # $0.00
        "codex_cli": settings.cost_codex_cli,           # $0.00
    }


def unit_clip_cost(model: str, seconds: float, pricing: Optional[dict] = None) -> float:
    """USD for one clip of `seconds` from settings.clip_pricing (or `pricing`). Unknown model -> ValueError."""
    pricing = settings.clip_pricing if pricing is None else pricing
    price = pricing.get(model)
    if price is None:
        raise ValueError(f"No clip pricing for model {model!r}. Known: {sorted(pricing)}")
    if "per_second" in price:
        return round(float(price["per_second"]) * float(seconds), 4)
    return float(price.get("per_clip", 0.0))


class CostTracker:
    """Tracks API costs per video and persists to JSON."""

    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or settings.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.output_dir / "cost_log.json"
        self._dirty: set = set()
        self._costs = self._load()

    @property
    def unit_costs(self) -> dict:
        return unit_costs()

    @staticmethod
    def _empty() -> dict:
        return {"schema_version": 1, "videos": {}}

    def _read(self) -> Optional[dict]:
        """Read the log from disk (caller holds _LOCK). Returns None when the file exists but cannot be
        trusted or read (locked, or corrupt with no safe copy made) - callers must then not overwrite it."""
        text = None
        for attempt in range(5):
            try:
                text = self.log_path.read_text(encoding="utf-8")
                break
            except FileNotFoundError:
                return self._empty()
            except PermissionError as e:
                if attempt == 4:
                    logger.warning("Cost log %s is locked (%s); leaving it untouched", self.log_path, e)
                    return None
                time.sleep(0.1)
            except OSError as e:
                logger.warning("Cost log %s unreadable (%s); leaving it untouched", self.log_path, e)
                return None
            except ValueError:          # UnicodeDecodeError: bad bytes are corruption
                text = ""
                break
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("videos"), dict):
                return data
            reason = "unexpected structure"
        except ValueError as e:
            reason = str(e)
        try:
            shutil.copy2(self.log_path, self.log_path.with_name("cost_log.corrupt.json"))
        except OSError as e:
            logger.warning("Cost log %s is corrupt (%s) and could not be copied aside (%s); leaving it untouched",
                           self.log_path, reason, e)
            return None
        logger.warning("Cost log %s is corrupt (%s); copied to cost_log.corrupt.json, starting empty",
                       self.log_path, reason)
        return self._empty()

    def _load(self) -> dict:
        with _LOCK:
            return self._read() or self._empty()

    def log_cost(self, video_id: str, item: str, quantity: int = 1) -> None:
        if item not in self.unit_costs:
            raise ValueError(f"Unknown cost item: {item}. Valid: {list(self.unit_costs.keys())}")
        unit = self.unit_costs[item]
        self._append(video_id, {"item": item, "quantity": quantity, "unit_cost": unit,
                                "cost": round(unit * quantity, 4)})
        logger.debug(f"Cost: {item} x{quantity} = ${unit * quantity:.4f} (video: {video_id})")

    def clip_unit_cost(self, model: str, seconds: float) -> float:
        return unit_clip_cost(model, seconds)

    def log_clip(self, video_id: str, model: str, seconds: float, count: int = 1) -> float:
        unit = self.clip_unit_cost(model, seconds)
        cost = round(unit * count, 4)
        self._append(video_id, {"item": f"clip:{model}", "quantity": count, "seconds": seconds,
                                "unit_cost": unit, "cost": cost})
        return cost

    def get_video_items(self, video_id: str) -> list:
        return list(self._costs["videos"].get(video_id, {}).get("items", []))

    def _append(self, video_id: str, entry: dict) -> None:
        self._dirty.add(video_id)
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
        with _LOCK:
            disk = self._read()
            if disk is None:
                logger.warning("Cost log not saved (unreadable); %d video(s) kept in memory only", len(self._dirty))
                return
            for vid in self._dirty:
                disk["videos"][vid] = self._costs["videos"][vid]
            atomic_write_text(self.log_path, json.dumps(disk, indent=2))
            self._costs = disk
        logger.info(f"Cost log saved to {self.log_path}")
