"""Wind data endpoint – serves U/V component grids in leaflet-velocity format."""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Grid definition covering the entire world
# ---------------------------------------------------------------------------
LAT_START = 85.0
LAT_END = -85.0
LON_START = -180.0
LON_END = 180.0
STEP = 5.0

def _build_axis(start: float, end: float, step: float, *, descending: bool = False) -> list[float]:
    values: list[float] = []
    current = start

    while (current >= end if descending else current <= end):
        values.append(round(current, 10))
        current = current - step if descending else current + step

    if not values or abs(values[-1] - end) > 1e-9:
        values.append(end)

    return values


_lats = _build_axis(LAT_START, LAT_END, STEP, descending=True)
_lons = _build_axis(LON_START, LON_END, STEP)

NX = len(_lons)
NY = len(_lats)

# Dense output grid rendered in the client.
GRID_POINTS: list[tuple[float, float]] = [
    (lat, lon) for lat in _lats for lon in _lons
]

# Sparse source grid used to query Open-Meteo once and interpolate locally.
SAMPLE_LAT_POINTS = [80.0, 40.0, 0.0, -40.0, -80.0]
SAMPLE_LON_POINTS = [-180.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 180.0]
SAMPLE_POINTS: list[tuple[float, float]] = [
    (lat, lon) for lat in SAMPLE_LAT_POINTS for lon in SAMPLE_LON_POINTS
]

CACHE_TTL_SECONDS = 3600  # 1 hour
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cache_path() -> Path:
    return get_settings().resolved_cache_dir / "wind_data.json"


def _cache_is_valid(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def _read_cache(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, list) else None


def _wind_to_uv(speed: float, direction_deg: float) -> tuple[float, float]:
    """Convert wind speed (m/s) and meteorological direction (°) to U/V."""
    rad = math.radians(direction_deg)
    u = -speed * math.sin(rad)
    v = -speed * math.cos(rad)
    return u, v


def _build_header(parameter_number: int) -> dict[str, Any]:
    return {
        "parameterCategory": 2,
        "parameterNumber": parameter_number,
        "lo1": LON_START,
        "la1": LAT_START,
        "lo2": _lons[-1],
        "la2": _lats[-1],
        "dx": STEP,
        "dy": STEP,
        "nx": NX,
        "ny": NY,
    }


def _empty_payload() -> list[dict[str, Any]]:
    zeros = [0.0] * len(GRID_POINTS)
    return [
        {"header": _build_header(2), "data": zeros},
        {"header": _build_header(3), "data": list(zeros)},
    ]


def _bilinear(value_grid: list[list[float]], lat: float, lon: float, lats: list[float], lons: list[float]) -> float:
    if not lats or not lons:
        return 0.0

    if len(lats) == 1 and len(lons) == 1:
        return value_grid[0][0]

    lat_low = max((value for value in lats if value <= lat), default=lats[0])
    lat_high = min((value for value in lats if value >= lat), default=lats[-1])
    lon_low = max((value for value in lons if value <= lon), default=lons[0])
    lon_high = min((value for value in lons if value >= lon), default=lons[-1])

    if lat_low == lat_high and lon_low == lon_high:
        return value_grid[lats.index(lat_low)][lons.index(lon_low)]

    if lat_low == lat_high:
        row = value_grid[lats.index(lat_low)]
        left = row[lons.index(lon_low)]
        right = row[lons.index(lon_high)]
        if lon_high == lon_low:
            return left
        ratio = (lon - lon_low) / (lon_high - lon_low)
        return left + (right - left) * ratio

    if lon_low == lon_high:
        bottom = value_grid[lats.index(lat_low)][lons.index(lon_low)]
        top = value_grid[lats.index(lat_high)][lons.index(lon_low)]
        if lat_high == lat_low:
            return bottom
        ratio = (lat - lat_low) / (lat_high - lat_low)
        return bottom + (top - bottom) * ratio

    q11 = value_grid[lats.index(lat_low)][lons.index(lon_low)]
    q12 = value_grid[lats.index(lat_low)][lons.index(lon_high)]
    q21 = value_grid[lats.index(lat_high)][lons.index(lon_low)]
    q22 = value_grid[lats.index(lat_high)][lons.index(lon_high)]

    lon_ratio = (lon - lon_low) / (lon_high - lon_low)
    lat_ratio = (lat - lat_low) / (lat_high - lat_low)

    return (
        q11 * (1 - lon_ratio) * (1 - lat_ratio)
        + q12 * lon_ratio * (1 - lat_ratio)
        + q21 * (1 - lon_ratio) * lat_ratio
        + q22 * lon_ratio * lat_ratio
    )


def _interpolate_grid(
    sample_uv: dict[tuple[float, float], tuple[float, float]],
) -> list[dict[str, Any]]:
    sample_lats = sorted(set(lat for lat, _ in SAMPLE_POINTS))
    sample_lons = sorted(set(lon for _, lon in SAMPLE_POINTS))
    u_grid = [[0.0 for _ in sample_lons] for _ in sample_lats]
    v_grid = [[0.0 for _ in sample_lons] for _ in sample_lats]

    for lat_index, lat in enumerate(sample_lats):
        for lon_index, lon in enumerate(sample_lons):
            u, v = sample_uv[(lat, lon)]
            u_grid[lat_index][lon_index] = u
            v_grid[lat_index][lon_index] = v

    u_data: list[float] = []
    v_data: list[float] = []
    for lat, lon in GRID_POINTS:
        u_data.append(round(_bilinear(u_grid, lat, lon, sample_lats, sample_lons), 4))
        v_data.append(round(_bilinear(v_grid, lat, lon, sample_lats, sample_lons), 4))

    return [
        {"header": _build_header(2), "data": u_data},
        {"header": _build_header(3), "data": v_data},
    ]


async def _fetch_wind_data() -> list[dict[str, Any]]:
    """Fetch wind data from Open-Meteo using a sparse grid and interpolate locally."""
    settings = get_settings()
    sample_uv: dict[tuple[float, float], tuple[float, float]] = {}

    lat_param = ",".join(str(lat) for lat, _ in SAMPLE_POINTS)
    lon_param = ",".join(str(lon) for _, lon in SAMPLE_POINTS)

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.get(
            OPEN_METEO_BASE,
            params={
                "latitude": lat_param,
                "longitude": lon_param,
                "current": "wind_speed_10m,wind_direction_10m",
                "timezone": "Asia/Jakarta",
                "wind_speed_unit": "ms",
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip() or "Open-Meteo request failed."
            raise HTTPException(status_code=502, detail=detail) from exc

        payload = response.json()
        items: list[dict[str, Any]] = payload if isinstance(payload, list) else [payload]
        if len(items) != len(SAMPLE_POINTS):
            raise HTTPException(status_code=502, detail="Unexpected wind data shape from Open-Meteo.")

        for index, item in enumerate(items):
            current = item.get("current", {})
            speed = float(current.get("wind_speed_10m", 0.0) or 0.0)
            direction = float(current.get("wind_direction_10m", 0.0) or 0.0)
            sample_uv[SAMPLE_POINTS[index]] = _wind_to_uv(speed, direction)

    return _interpolate_grid(sample_uv)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

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
    except Exception as exc:  # pragma: no cover - defensive fallback
        if cached_result is not None:
            logger.warning("Wind fetch failed, serving stale cache.", exc_info=True)
            return cached_result
        logger.warning("Wind fetch failed, serving calm fallback.", exc_info=True)
        return _empty_payload()

    # Persist to cache
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        logger.warning("Failed to write wind cache file.", exc_info=True)

    return result
