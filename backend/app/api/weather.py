"""Weather and Air Quality endpoints – serves spot forecasts and weather grids."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.services.weather_service import (
    AIR_QUALITY_BASE,
    CACHE_TTL_SECONDS,
    GRID_POINTS,
    LAT_END,
    LAT_START,
    LON_END,
    LON_START,
    NX,
    NY,
    OPEN_METEO_BASE,
    SAMPLE_LAT_POINTS,
    SAMPLE_LON_POINTS,
    SAMPLE_POINTS,
    STEP,
    bilinear_interpolate,
    build_axis,
    build_weather_header,
    calculate_cbi,
    calculate_cbi_val,
    check_rain_at_coordinates,
    fetch_grid_data,
    fetch_spot_weather,
    interpolate_weather_grid,
    is_cache_valid,
    read_json_cache,
    write_json_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Re-exports for backwards compatibility
_build_axis = build_axis
_build_header = build_weather_header
_bilinear = bilinear_interpolate
_interpolate_grid = interpolate_weather_grid
_fetch_grid_data = fetch_grid_data


def _cache_path(parameter: str) -> Path:
    return get_settings().resolved_cache_dir / f"weather_grid_{parameter}.json"


def _cache_is_valid(path: Path) -> bool:
    return is_cache_valid(path, CACHE_TTL_SECONDS)


def _read_cache(path: Path) -> dict[str, Any] | None:
    payload = read_json_cache(path)
    return payload if isinstance(payload, dict) else None


@router.get("/weather/spot")
async def get_spot_weather(
    lat: float = Query(..., description="Latitude coordinate"),
    lon: float = Query(..., description="Longitude coordinate"),
) -> dict[str, Any]:
    """Fetch spot weather forecast and air quality for a single coordinate."""
    settings = get_settings()
    try:
        return await fetch_spot_weather(lat, lon, timeout_seconds=settings.request_timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error fetching spot weather forecast: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to fetch spot weather forecast.") from exc


@router.get("/weather/grid")
async def get_weather_grid(
    parameter: str = Query(..., description="Parameter name: temperature, humidity, precipitation, soil_moisture, fwi"),
) -> dict[str, Any]:
    """Return weather parameter grid for map interpolation overlay."""
    if parameter not in ["temperature", "humidity", "precipitation", "soil_moisture", "fwi"]:
        raise HTTPException(status_code=400, detail="Invalid parameter name.")

    cache_file = _cache_path(parameter)
    cached_result = _read_cache(cache_file)

    # Serve from cache if still fresh
    if _cache_is_valid(cache_file) and cached_result is not None:
        return cached_result

    # Fetch fresh data
    settings = get_settings()
    try:
        result = await fetch_grid_data(parameter, timeout_seconds=settings.request_timeout_seconds)
    except HTTPException:
        if cached_result is not None:
            logger.warning("Weather grid '%s' upstream unavailable, serving stale cache.", parameter)
            return cached_result
        raise
    except Exception as exc:
        if cached_result is not None:
            logger.warning("Weather grid '%s' fetch failed, serving stale cache.", parameter, exc_info=True)
            return cached_result
        raise HTTPException(status_code=502, detail="Failed to fetch weather grid.") from exc

    # Persist to cache
    write_json_cache(cache_file, result)

    return result


@router.get("/weather/rain-check")
async def get_rain_check(
    coords: str = Query(..., description="Coordinates formatted as lat1,lon1;lat2,lon2;..."),
) -> list[dict[str, Any]]:
    """Check if it is raining at multiple coordinate points concurrently."""
    if not coords.strip():
        return []

    settings = get_settings()
    raw_parts = [p for p in coords.split(";") if p.strip()]
    max_points = 20
    if len(raw_parts) > max_points:
        raise HTTPException(
            status_code=400,
            detail=f"Terlalu banyak koordinat (maks {max_points}).",
        )

    points = []
    for p in raw_parts:
        try:
            lat_str, lon_str = p.split(",")
            points.append((float(lat_str), float(lon_str)))
        except ValueError:
            continue

    if not points:
        return []

    try:
        return await check_rain_at_coordinates(points, timeout_seconds=settings.request_timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch rain check: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to check rain from weather upstream.") from exc
