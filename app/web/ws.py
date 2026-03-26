"""WebSocket manager for real-time progress broadcasting."""

import json
import logging
from datetime import datetime, timezone
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """Manages WebSocket connections and broadcasts messages."""

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self.connections))

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)
        logger.info("WebSocket client disconnected (%d total)", len(self.connections))

    async def broadcast(self, message: dict):
        message["timestamp"] = datetime.now(timezone.utc).isoformat()
        data = json.dumps(message)
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)

    async def send_progress(self, job_id: str, stage: str, progress: float, message: str):
        await self.broadcast({
            "type": "progress", "job_id": job_id,
            "stage": stage, "progress": progress, "message": message,
        })

    async def send_complete(self, job_id: str, result: dict | None = None):
        await self.broadcast({"type": "complete", "job_id": job_id, "result": result})

    async def send_error(self, job_id: str, error: str):
        await self.broadcast({"type": "error", "job_id": job_id, "error": error})


ws_manager = WSManager()
