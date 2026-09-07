from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.polygons import router
from app.services.polygon_service import PolygonService


class _DisabledStore:
    enabled = False


class _MockSurroundingStore:
    enabled = True

    def read_polygon_surrounding_hotspots(
        self,
        *,
        polygon_id: int,
        buffer_km: float,
        start_at: datetime,
        end_at: datetime,
        sources: list[str] | None = None,
    ):
        return [
            {
                "id": 101,
                "source": "VIIRS_NOAA20_NRT",
                "satellite": "NOAA-20",
                "latitude": -2.5,
                "longitude": 113.8,
                "brightness": 345.2,
                "confidence": "nominal",
                "frp": 14.5,
                "detected_at": "2026-09-06T14:30:00+07:00",
                "layer_key": "psagustus2026",
                "agency_name": "Lembaga KPS Mandiri",
                "raw_payload": {"frp": 14.5},
                "is_inside": True,
                "distance_m": 0,
                "bearing_deg": None,
            },
            {
                "id": 102,
                "source": "VIIRS_NOAA20_NRT",
                "satellite": "NOAA-20",
                "latitude": -2.48,
                "longitude": 113.85,
                "brightness": 330.1,
                "confidence": "high",
                "frp": 25.0,
                "detected_at": "2026-09-06T18:00:00+07:00",
                "layer_key": "perimeter_threat",
                "agency_name": None,
                "raw_payload": {"frp": 25.0},
                "is_inside": False,
                "distance_m": 1850,
                "bearing_deg": 45.0,
            },
        ]


def _build_client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_polygon_surrounding_hotspots_disabled_store():
    service = PolygonService("postgresql://test:test@localhost:5432/test")
    service.postgres_store = _DisabledStore()

    result = service.get_surrounding_hotspots(
        polygon_id=999,
        buffer_km=5.0,
        start_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )

    assert result["polygon_id"] == 999
    assert result["buffer_km"] == 5.0
    assert result["total_inside"] == 0
    assert result["total_outside"] == 0
    assert result["total_hotspots"] == 0
    assert result["hotspots"] == []


def test_polygon_surrounding_hotspots_formatting():
    service = PolygonService("postgresql://test:test@localhost:5432/test")
    service.postgres_store = _MockSurroundingStore()

    result = service.get_surrounding_hotspots(
        polygon_id=123,
        buffer_km=5.0,
        start_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
    )

    assert result["polygon_id"] == 123
    assert result["total_inside"] == 1
    assert result["total_outside"] == 1
    assert result["total_hotspots"] == 2

    inside_hs = result["hotspots"][0]
    assert inside_hs["id"] == "101"
    assert inside_hs["is_inside"] is True
    assert inside_hs["distance_m"] == 0
    assert inside_hs["bearing_compass"] == "Dalam Kawasan"
    assert inside_hs["threat_origin"] == "internal"

    outside_hs = result["hotspots"][1]
    assert outside_hs["id"] == "102"
    assert outside_hs["is_inside"] is False
    assert outside_hs["distance_m"] == 1850
    assert outside_hs["distance_km"] == 1.85
    assert outside_hs["bearing_compass"] == "Timur Laut (NE)"
    assert outside_hs["threat_origin"] == "non_kps"
    assert outside_hs["threat_origin_label"] == "Luar Kawasan (Bukan KPS)"


def test_polygon_surrounding_hotspots_api_endpoint(monkeypatch):
    client = _build_client()
    mock_service = PolygonService("postgresql://test:test@localhost:5432/test")
    mock_service.postgres_store = _MockSurroundingStore()

    monkeypatch.setattr("app.api.polygons.get_polygon_service", lambda: mock_service)

    resp = client.get(
        "/api/polygons/123/surrounding-hotspots?buffer_km=5&start_date=2026-09-01&end_date=2026-09-07"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["polygon_id"] == 123
    assert data["total_hotspots"] == 2
    assert data["total_inside"] == 1
    assert data["total_outside"] == 1
    assert len(data["hotspots"]) == 2
