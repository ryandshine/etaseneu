"""Service untuk kalkulasi angin global (U/V komponen) dan interpolasi Open-Meteo."""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from app.services.weather_service import (
    bilinear_interpolate,
    build_axis,
)

logger = logging.getLogger("wind.service")

# ---------------------------------------------------------------------------
# Grid definition covering the entire world
# ---------------------------------------------------------------------------
LAT_START = 85.0
LAT_END = -85.0
LON_START = -180.0
LON_END = 180.0
STEP = 5.0

_lats = build_axis(LAT_START, LAT_END, STEP, descending=True)
_lons = build_axis(LON_START, LON_END, STEP)

NX = len(_lons)
NY = len(_lats)

GRID_POINTS: list[tuple[float, float]] = [
    (lat, lon) for lat in _lats for lon in _lons
]

SAMPLE_LAT_POINTS = [80.0, 40.0, 0.0, -40.0, -80.0]
SAMPLE_LON_POINTS = [-180.0, -135.0, -90.0, -45.0, 0.0, 45.0, 90.0, 135.0, 180.0]
SAMPLE_POINTS: list[tuple[float, float]] = [
    (lat, lon) for lat in SAMPLE_LAT_POINTS for lon in SAMPLE_LON_POINTS
]

CACHE_TTL_SECONDS = 3600  # 1 hour
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


def wind_to_uv(speed: float, direction_deg: float) -> tuple[float, float]:
    """Convert wind speed (m/s) and meteorological direction (°) to U/V."""
    rad = math.radians(direction_deg)
    u = -speed * math.sin(rad)
    v = -speed * math.cos(rad)
    return u, v


def build_wind_header(parameter_number: int) -> dict[str, Any]:
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


def empty_wind_payload() -> list[dict[str, Any]]:
    zeros = [0.0] * len(GRID_POINTS)
    return [
        {"header": build_wind_header(2), "data": zeros},
        {"header": build_wind_header(3), "data": list(zeros)},
    ]


def interpolate_wind_grid(
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
        u_data.append(round(bilinear_interpolate(u_grid, lat, lon, sample_lats, sample_lons), 4))
        v_data.append(round(bilinear_interpolate(v_grid, lat, lon, sample_lats, sample_lons), 4))

    return [
        {"header": build_wind_header(2), "data": u_data},
        {"header": build_wind_header(3), "data": v_data},
    ]


async def fetch_wind_data(timeout_seconds: float = 30.0) -> list[dict[str, Any]]:
    """Fetch wind data from Open-Meteo using a sparse grid and interpolate locally."""
    sample_uv: dict[tuple[float, float], tuple[float, float]] = {}

    lat_param = ",".join(str(lat) for lat, _ in SAMPLE_POINTS)
    lon_param = ",".join(str(lon) for _, lon in SAMPLE_POINTS)

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
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
        response.raise_for_status()
        payload = response.json()
        items: list[dict[str, Any]] = payload if isinstance(payload, list) else [payload]
        if len(items) != len(SAMPLE_POINTS):
            raise ValueError("Unexpected wind data shape from Open-Meteo.")

        for index, item in enumerate(items):
            current = item.get("current", {})
            speed = float(current.get("wind_speed_10m", 0.0) or 0.0)
            direction = float(current.get("wind_direction_10m", 0.0) or 0.0)
            sample_uv[SAMPLE_POINTS[index]] = wind_to_uv(speed, direction)

    return interpolate_wind_grid(sample_uv)
