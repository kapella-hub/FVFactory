"""CORS origins for the web UI (pure: no FastAPI import, so it is unit-tested without the web extras)."""
from typing import Optional


def cors_origin_list(value: Optional[str]) -> list:
    """settings.cors_origins ("http://a,http://b") -> origins in order, trimmed, without a trailing "/"
    and duplicates. "" = [] = no CORS middleware (the bundled UI is same-origin)."""
    origins = []
    for origin in (value or "").split(","):
        origin = origin.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins
