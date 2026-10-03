"""FastAPI application server for FVFactory."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.web.cors import cors_origin_list
from app.web.ws import ws_manager

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
DATA_DIR = Path("data")

# The UI ships as plain files with no build hashes: make the browser revalidate them on every load
# (ETag / Last-Modified still give a cheap 304), so an updated UI is never hidden behind a cached old one.
NO_CACHE = {"Cache-Control": "no-cache"}


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(NO_CACHE)
        return response


def _index_response():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index, headers=NO_CACHE)
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(exist_ok=True)
    # Settings-page values survive a restart (before Phase D they were applied in-process only).
    from app.run_options import apply_saved_settings, load_config_file
    from app.web.routes.api_config import CONFIG_PATH
    applied = apply_saved_settings(settings, load_config_file(CONFIG_PATH))
    if applied:
        logger.info("Applied saved settings from %s: %s", CONFIG_PATH, ", ".join(sorted(applied)))
    logger.info("FVFactory server starting...")
    yield
    logger.info("FVFactory server shutting down...")


app = FastAPI(title="FVFactory", lifespan=lifespan)

# No CORS by default: the bundled UI is same-origin, and a wildcard would let any web page the user has
# open drive the API (settings, generation). CORS_ORIGINS in .env names any extra origins.
_cors_origins = cors_origin_list(settings.cors_origins)
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
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
    app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return _index_response() or {"status": "FVFactory API running", "docs": "/docs"}


# SPA catch-all: serve index.html for client-side routes
@app.get("/{path:path}")
async def spa_fallback(path: str):
    # Don't intercept API or static file requests
    if path.startswith("api/") or path.startswith("static/"):
        return {"error": "Not found"}
    return _index_response() or {"error": "Not found"}


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
