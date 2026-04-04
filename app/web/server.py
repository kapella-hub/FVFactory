"""FastAPI application server for FVFactory."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.web.ws import ws_manager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR = Path("data")


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(exist_ok=True)
    logger.info("FVFactory server starting...")
    yield
    logger.info("FVFactory server shutting down...")


app = FastAPI(title="FVFactory", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


from app.web.routes.api_config import router as config_router
from app.web.routes.api_library import router as library_router
from app.web.routes.api_generate import router as generate_router
from app.web.routes.api_scheduler import router as scheduler_router

app.include_router(config_router, prefix="/api")
app.include_router(library_router, prefix="/api")
app.include_router(generate_router, prefix="/api")
app.include_router(scheduler_router, prefix="/api")


# Serve static files only if directory exists
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"status": "FVFactory API running", "docs": "/docs"}


# SPA catch-all: serve index.html for client-side routes
@app.get("/{path:path}")
async def spa_fallback(path: str):
    # Don't intercept API or static file requests
    if path.startswith("api/") or path.startswith("static/"):
        return {"error": "Not found"}
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"error": "Not found"}


def start_server(host: str = "0.0.0.0", port: int = 8000):
    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass  # headless server, no browser
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_server()
