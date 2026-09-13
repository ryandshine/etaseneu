"""Wind data endpoint – serves U/V component grids in leaflet-velocity format."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.services.weather_service import is_cache_valid, read_json_cache, write_json_cache
from app.services.wind_service import (
    CACHE_TTL_SECONDS,
    GRID_POINTS,
    LAT_END,
    LAT_START,
    LON_END,
    LON_START,
    SAMPLE_POINTS,
    build_wind_header,
    empty_wind_payload,
    fetch_wind_data,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Re-exports for test compatibility
_build_header = build_wind_header

__all__ = [
    "CACHE_TTL_SECONDS",
    "GRID_POINTS",
    "LAT_END",
    "LAT_START",
    "LON_END",
    "LON_START",
    "SAMPLE_POINTS",
    "_build_header",
    "_cache_is_valid",
    "_cache_path",
    "_empty_payload",
    "_fetch_wind_data",
    "_read_cache",
    "get_wind",
    "router",
]


def _cache_path() -> Path:
    return get_settings().resolved_cache_dir / "wind_data.json"


def _cache_is_valid(path: Path) -> bool:
    return is_cache_valid(path, CACHE_TTL_SECONDS)


def _read_cache(path: Path) -> list[dict[str, Any]] | None:
    payload = read_json_cache(path)
    return payload if isinstance(payload, list) else None


def _empty_payload() -> list[dict[str, Any]]:
    return empty_wind_payload()


async def _fetch_wind_data() -> list[dict[str, Any]]:
    settings = get_settings()
    try:
        return await fetch_wind_data(timeout_seconds=settings.request_timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Open-Meteo wind request failed.") from exc


@router.get("/wind")
async def get_wind() -> list[dict[str, Any]]:
    """Return wind U/V component grid in leaflet-velocity format."""
    cache_file = _cache_path()
    cached_result = _read_cache(cache_file)

    # Serve from cache if still fresh
    if _cache_is_valid(cache_file) and cached_result is not None:
        return cached_result

    # Fetch fresh data
    try:
        result = await _fetch_wind_data()
    except HTTPException:
        if cached_result is not None:
            logger.warning("Wind upstream unavailable, serving stale cache.")
            return cached_result
        logger.warning("Wind upstream unavailable, serving calm fallback.")
        return _empty_payload()
    except Exception:  # pragma: no cover - defensive fallback
        if cached_result is not None:
            logger.warning("Wind fetch failed, serving stale cache.", exc_info=True)
            return cached_result
        logger.warning("Wind fetch failed, serving calm fallback.", exc_info=True)
        return _empty_payload()

    # Persist to cache
    write_json_cache(cache_file, result)

    return result
