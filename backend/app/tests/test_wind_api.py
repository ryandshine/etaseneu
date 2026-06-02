from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest
from fastapi import HTTPException


def test_wind_grid_stays_within_open_meteo_limits() -> None:
    from app.api import wind

    assert len(wind.SAMPLE_POINTS) <= 100
    assert len(wind.GRID_POINTS) > len(wind.SAMPLE_POINTS)
    assert wind.LAT_START == 85.0
    assert wind.LAT_END == -85.0
    assert wind.LON_START == -180.0
    assert wind.LON_END == 180.0


def test_wind_endpoint_writes_fresh_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import wind

    cache_file = tmp_path / "wind_data.json"
    sample = [
        {"header": {"parameterNumber": 2}, "data": [1.0, 2.0]},
        {"header": {"parameterNumber": 3}, "data": [3.0, 4.0]},
    ]

    monkeypatch.setattr(wind, "_cache_path", lambda: cache_file)

    async def fake_fetch() -> list[dict]:
        return sample

    monkeypatch.setattr(wind, "_fetch_wind_data", fake_fetch)

    result = asyncio.run(wind.get_wind())

    assert result == sample
    assert json.loads(cache_file.read_text(encoding="utf-8")) == sample


def test_wind_endpoint_falls_back_to_stale_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import wind

    cache_file = tmp_path / "wind_data.json"
    cached = [
        {"header": {"parameterNumber": 2}, "data": [0.1, 0.2]},
        {"header": {"parameterNumber": 3}, "data": [0.3, 0.4]},
    ]
    cache_file.write_text(json.dumps(cached), encoding="utf-8")
    stale_at = time.time() - (wind.CACHE_TTL_SECONDS + 60)
    os.utime(cache_file, (stale_at, stale_at))

    monkeypatch.setattr(wind, "_cache_path", lambda: cache_file)

    async def boom() -> list[dict]:
        raise HTTPException(status_code=502, detail="Minutely API request limit exceeded.")

    monkeypatch.setattr(wind, "_fetch_wind_data", boom)

    result = asyncio.run(wind.get_wind())

    assert result == cached


def test_wind_endpoint_returns_calm_fallback_when_upstream_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import wind

    cache_file = tmp_path / "wind_data.json"
    monkeypatch.setattr(wind, "_cache_path", lambda: cache_file)

    async def boom() -> list[dict]:
        raise HTTPException(status_code=502, detail="Hourly API request limit exceeded.")

    monkeypatch.setattr(wind, "_fetch_wind_data", boom)

    result = asyncio.run(wind.get_wind())

    assert len(result) == 2
    assert all(entry["data"] for entry in result)
    assert set(result[0]["data"]) == {0.0}
    assert set(result[1]["data"]) == {0.0}


def test_wind_header_covers_worldwide_bounds() -> None:
    from app.api import wind

    header = wind._build_header(2)

    assert header["lo1"] == -180.0
    assert header["la1"] == 85.0
    assert header["lo2"] == 180.0
    assert header["la2"] == -85.0
