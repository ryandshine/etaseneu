from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import weather_service


def test_calculate_cbi_levels():
    low = weather_service.calculate_cbi(temp_c=25.0, rh_pct=85.0, wind_speed_ms=1.0, rain_mm=5.0)
    assert low["level"] == "Rendah"
    assert low["color"] == "#22c55e"

    extreme = weather_service.calculate_cbi(temp_c=38.0, rh_pct=25.0, wind_speed_ms=8.0, rain_mm=0.0, soil_moisture=0.10)
    assert extreme["level"] in ["Sangat Tinggi", "Ekstrem"]


def test_build_axis_and_bilinear():
    axis = weather_service.build_axis(0.0, 10.0, 2.0)
    assert axis == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]

    grid = [[0.0, 10.0], [0.0, 10.0]]
    val = weather_service.bilinear_interpolate(grid, 5.0, 5.0, [0.0, 10.0], [0.0, 10.0])
    assert val == 5.0


def test_weather_rain_check_validation():
    app = create_app()
    client = TestClient(app)

    # Empty coords returns empty list
    resp = client.get("/api/weather/rain-check?coords=")
    assert resp.status_code == 200
    assert resp.json() == []

    # Too many coords (>20) rejected with 400
    many = ";".join(["-6.2,106.8"] * 25)
    resp = client.get(f"/api/weather/rain-check?coords={many}")
    assert resp.status_code == 400
    assert "Terlalu banyak" in resp.json()["detail"]


def test_weather_grid_invalid_parameter():
    app = create_app()
    client = TestClient(app)

    resp = client.get("/api/weather/grid?parameter=invalid_param")
    assert resp.status_code == 400


def test_fetch_grid_data_requests_wind_speed_in_meters_per_second(monkeypatch):
    """Regresi: calculate_cbi_val() mengasumsikan m/s. Tanpa wind_speed_unit=ms,
    Open-Meteo balas km/h dan CBI overlay peta jadi tidak sejalan dengan CBI di
    fetch_spot_weather() (kartu cuaca titik), yang sudah minta "ms"."""

    captured: dict = {}

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def get(self, url, params=None):
            captured["params"] = params
            item = {
                "current": {
                    "temperature_2m": 30.0,
                    "relative_humidity_2m": 40.0,
                    "wind_speed_10m": 5.0,
                    "precipitation": 0.0,
                    "soil_moisture_0_to_10cm": 0.2,
                }
            }
            return _FakeResponse([item] * len(weather_service.SAMPLE_POINTS))

    monkeypatch.setattr(weather_service.httpx, "AsyncClient", _FakeAsyncClient)

    asyncio.run(weather_service.fetch_grid_data("fwi"))

    assert captured["params"]["wind_speed_unit"] == "ms"
