"""Weather and Air Quality endpoints – serves spot forecasts and weather grids."""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Grid definition covering Indonesia
# ---------------------------------------------------------------------------
LAT_START = 8.0
LAT_END = -12.0
LON_START = 94.0
LON_END = 142.0
STEP = 2.0

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

# Dense output grid rendered in the client
GRID_POINTS: list[tuple[float, float]] = [
    (lat, lon) for lat in _lats for lon in _lons
]

# Sparse sample points for querying Open-Meteo
SAMPLE_LAT_POINTS = [8.0, 4.0, 0.0, -4.0, -8.0, -12.0]
SAMPLE_LON_POINTS = [94.0, 100.0, 106.0, 112.0, 118.0, 124.0, 130.0, 136.0, 142.0]
SAMPLE_POINTS: list[tuple[float, float]] = [
    (lat, lon) for lat in SAMPLE_LAT_POINTS for lon in SAMPLE_LON_POINTS
]

CACHE_TTL_SECONDS = 3600  # 1 hour
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_BASE = "https://air-quality-api.open-meteo.com/v1/air-quality"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cache_path(parameter: str) -> Path:
    return get_settings().resolved_cache_dir / f"weather_grid_{parameter}.json"


def _cache_is_valid(path: Path) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < CACHE_TTL_SECONDS


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _build_header(parameter_name: str) -> dict[str, Any]:
    # Mimic grib parameter info if needed, or customize
    return {
        "parameterName": parameter_name,
        "lo1": LON_START,
        "la1": LAT_START,
        "lo2": _lons[-1],
        "la2": _lats[-1],
        "dx": STEP,
        "dy": STEP,
        "nx": NX,
        "ny": NY,
    }


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


def calculate_cbi_val(temp_c: float, rh_pct: float) -> float:
    rh = max(0.0, min(100.0, rh_pct))
    cbi = ((110.0 - 1.37 * rh) - 9.01) * (10 ** (0.0444 * temp_c)) / 124.0
    return max(0.0, cbi)


def calculate_cbi(temp_c: float, rh_pct: float) -> dict[str, Any]:
    cbi = calculate_cbi_val(temp_c, rh_pct)
    if cbi < 50:
        level = "Rendah"
        color = "#22c55e"
    elif cbi < 75:
        level = "Sedang"
        color = "#eab308"
    elif cbi < 90:
        level = "Tinggi"
        color = "#f97316"
    elif cbi < 97.5:
        level = "Sangat Tinggi"
        color = "#ef4444"
    else:
        level = "Ekstrem"
        color = "#7f1d1d"

    return {
        "value": round(cbi, 2),
        "level": level,
        "color": color
    }


def _interpolate_grid(
    sample_values: dict[tuple[float, float], float],
    parameter_name: str,
) -> dict[str, Any]:
    sample_lats = sorted(set(lat for lat, _ in SAMPLE_POINTS))
    sample_lons = sorted(set(lon for _, lon in SAMPLE_POINTS))
    val_grid = [[0.0 for _ in sample_lons] for _ in sample_lats]

    for lat_index, lat in enumerate(sample_lats):
        for lon_index, lon in enumerate(sample_lons):
            val_grid[lat_index][lon_index] = sample_values.get((lat, lon), 0.0)

    data: list[float] = []
    for lat, lon in GRID_POINTS:
        data.append(round(_bilinear(val_grid, lat, lon, sample_lats, sample_lons), 2))

    return {
        "header": _build_header(parameter_name),
        "data": data,
    }


async def _fetch_grid_data(parameter: str) -> dict[str, Any]:
    settings = get_settings()
    sample_values: dict[tuple[float, float], float] = {}

    lat_param = ",".join(str(lat) for lat, _ in SAMPLE_POINTS)
    lon_param = ",".join(str(lon) for _, lon in SAMPLE_POINTS)

    # Map our UI parameter names to Open-Meteo variables
    om_vars = "temperature_2m,relative_humidity_2m"
    if parameter == "soil_moisture":
        om_vars += ",soil_moisture_0_to_10cm"
    elif parameter == "precipitation":
        om_vars += ",precipitation"

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.get(
            OPEN_METEO_BASE,
            params={
                "latitude": lat_param,
                "longitude": lon_param,
                "current": om_vars,
                "timezone": "Asia/Jakarta",
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
            raise HTTPException(status_code=502, detail="Unexpected weather data shape from Open-Meteo.")

        for index, item in enumerate(items):
            current = item.get("current", {})
            pt = SAMPLE_POINTS[index]

            if parameter == "temperature":
                sample_values[pt] = float(current.get("temperature_2m", 0.0) or 0.0)
            elif parameter == "humidity":
                sample_values[pt] = float(current.get("relative_humidity_2m", 0.0) or 0.0)
            elif parameter == "precipitation":
                sample_values[pt] = float(current.get("precipitation", 0.0) or 0.0)
            elif parameter == "soil_moisture":
                sample_values[pt] = float(current.get("soil_moisture_0_to_10cm", 0.0) or 0.0)
            elif parameter == "fwi":
                t = float(current.get("temperature_2m", 0.0) or 0.0)
                rh = float(current.get("relative_humidity_2m", 0.0) or 0.0)
                sample_values[pt] = calculate_cbi_val(t, rh)
            else:
                sample_values[pt] = 0.0

    return _interpolate_grid(sample_values, parameter)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/weather/spot")
async def get_spot_weather(
    lat: float = Query(..., description="Latitude coordinate"),
    lon: float = Query(..., description="Longitude coordinate"),
) -> dict[str, Any]:
    """Fetch spot weather forecast and air quality for a single coordinate."""
    settings = get_settings()

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        # Fetch weather forecast
        try:
            weather_resp = await client.get(
                OPEN_METEO_BASE,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,soil_moisture_0_to_10cm,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
                    "timezone": "Asia/Jakarta",
                    "wind_speed_unit": "ms",
                }
            )
            weather_resp.raise_for_status()
            weather_data = weather_resp.json()
        except Exception as e:
            logger.error(f"Error fetching spot weather forecast: {e}")
            raise HTTPException(status_code=502, detail="Failed to fetch spot weather forecast.")

        # Fetch air quality
        air_quality_data = {}
        try:
            aq_resp = await client.get(
                AIR_QUALITY_BASE,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "pm2_5,pm10,carbon_monoxide,us_aqi",
                    "timezone": "Asia/Jakarta",
                }
            )
            if aq_resp.status_code == 200:
                air_quality_data = aq_resp.json()
        except Exception as e:
            logger.warning(f"Error fetching air quality: {e}")
            # Non-blocking, return empty if failed

    current_weather = weather_data.get("current", {})
    daily_weather = weather_data.get("daily", {})
    current_aq = air_quality_data.get("current", {})

    temp = float(current_weather.get("temperature_2m", 0.0) or 0.0)
    rh = float(current_weather.get("relative_humidity_2m", 0.0) or 0.0)
    cbi = calculate_cbi(temp, rh)

    # Soil moisture status
    sm = float(current_weather.get("soil_moisture_0_to_10cm", 0.0) or 0.0)
    if sm < 0.15:
        sm_status = "Kering (Ekstrem)"
        sm_color = "#ef4444"
    elif sm < 0.25:
        sm_status = "Sedang"
        sm_color = "#eab308"
    else:
        sm_status = "Basah (Aman)"
        sm_color = "#22c55e"

    return {
        "latitude": lat,
        "longitude": lon,
        "current": {
            "temperature": temp,
            "humidity": rh,
            "precipitation": float(current_weather.get("precipitation", 0.0) or 0.0),
            "wind_speed": float(current_weather.get("wind_speed_10m", 0.0) or 0.0),
            "wind_direction": float(current_weather.get("wind_direction_10m", 0.0) or 0.0),
            "wind_gusts": float(current_weather.get("wind_gusts_10m", 0.0) or 0.0),
            "soil_moisture": sm,
            "soil_moisture_status": sm_status,
            "soil_moisture_color": sm_color,
            "weather_code": int(current_weather.get("weather_code", 0) or 0),
            "fire_danger": cbi,
        },
        "daily": {
            "time": daily_weather.get("time", []),
            "temp_max": daily_weather.get("temperature_2m_max", []),
            "temp_min": daily_weather.get("temperature_2m_min", []),
            "precipitation_sum": daily_weather.get("precipitation_sum", []),
            "wind_speed_max": daily_weather.get("wind_speed_10m_max", []),
        },
        "air_quality": {
            "pm2_5": float(current_aq.get("pm2_5", 0.0) or 0.0),
            "pm10": float(current_aq.get("pm10", 0.0) or 0.0),
            "carbon_monoxide": float(current_aq.get("carbon_monoxide", 0.0) or 0.0),
            "aqi": int(current_aq.get("us_aqi", 0) or 0),
        }
    }


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
    try:
        result = await _fetch_grid_data(parameter)
    except HTTPException:
        if cached_result is not None:
            logger.warning(f"Weather grid '{parameter}' upstream unavailable, serving stale cache.")
            return cached_result
        raise
    except Exception as exc:
        if cached_result is not None:
            logger.warning(f"Weather grid '{parameter}' fetch failed, serving stale cache.", exc_info=True)
            return cached_result
        raise HTTPException(status_code=502, detail="Failed to fetch weather grid.")

    # Persist to cache
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        logger.warning(f"Failed to write weather grid cache '{parameter}'.", exc_info=True)

    return result
