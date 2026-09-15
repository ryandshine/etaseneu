import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import point_result_store as store_module


@pytest.fixture(autouse=True)
def fresh_stores(monkeypatch):
    monkeypatch.setattr(store_module, "point_result_store", store_module.PointResultStore())
    monkeypatch.setattr(
        store_module, "upload_rate_limiter", store_module.RateLimiter(max_requests=10, window_seconds=600)
    )
    import app.api.point_match as api_module

    monkeypatch.setattr(api_module, "point_result_store", store_module.point_result_store)
    monkeypatch.setattr(api_module, "upload_rate_limiter", store_module.upload_rate_limiter)
    yield


class FakePolygonStore:
    enabled = True

    def check_polygon_kps_overlap(self, polygon_geojson: str, limit: int = 20):
        return [
            {
                "id": 101,
                "lembaga": "LPHD BUKIT HIJAU",
                "nama_prov": "Kalimantan Barat",
                "nama_kab": "Ketapang",
                "skema": "HD",
                "no_sk": "SK.123/2022",
            }
        ]

    def find_hotspots_in_polygon(self, polygon_geojson: str, start_date: str, end_date: str):
        return [
            {
                "id": 1,
                "source": "VIIRS NOAA-20",
                "satellite": "N20",
                "latitude": -1.05,
                "longitude": 110.05,
                "brightness": 345.5,
                "confidence": "h",
                "detected_at": datetime(2026, 8, 15, 13, 30, tzinfo=timezone.utc),
                "raw_payload": {"frp": 25.4, "brightness": 345.5},
            },
            {
                "id": 2,
                "source": "VIIRS NOAA-21",
                "satellite": "N21",
                "latitude": -1.08,
                "longitude": 110.08,
                "brightness": 320.0,
                "confidence": "n",
                "detected_at": datetime(2026, 8, 16, 14, 0, tzinfo=timezone.utc),
                "raw_payload": {"frp": 12.0, "brightness": 320.0},
            },
        ]


def _patch_store(monkeypatch, fake):
    import app.api.point_match as api_module
    monkeypatch.setattr(api_module, "PostgresStore", lambda _url: fake)


def _polygon_geojson_bytes():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Areal Konsesi PT ABC"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [110.0, -1.0],
                            [110.1, -1.0],
                            [110.1, -1.1],
                            [110.0, -1.1],
                            [110.0, -1.0],
                        ]
                    ],
                },
            }
        ],
    }
    return json.dumps(payload).encode()


def _polygon_kml_bytes():
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Batas Kawasan Hutan X</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              110.0,-1.0,0 110.1,-1.0,0 110.1,-1.1,0 110.0,-1.1,0 110.0,-1.0,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""


def test_analyze_polygon_geojson(monkeypatch):
    _patch_store(monkeypatch, FakePolygonStore())
    client = TestClient(create_app())

    response = client.post(
        "/api/point-match/analyze",
        files={"file": ("areal_konsesi.geojson", _polygon_geojson_bytes(), "application/geo+json")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "polygon"
    assert body["polygon_info"]["area_ha"] > 0
    assert body["polygon_info"]["overlaps_kps"] is True
    assert len(body["polygon_info"]["kps_matches"]) == 1
    assert body["summary"]["total_hotspots"] == 2
    assert body["summary"]["confidence_high"] == 1
    assert body["summary"]["confidence_medium"] == 1
    assert body["token"]
    assert len(body["preview_rows"]) == 2


def test_analyze_polygon_kml(monkeypatch):
    _patch_store(monkeypatch, FakePolygonStore())
    client = TestClient(create_app())

    response = client.post(
        "/api/point-match/analyze",
        files={"file": ("areal_kml.kml", _polygon_kml_bytes(), "application/vnd.google-earth.kml+xml")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "polygon"
    assert body["summary"]["total_hotspots"] == 2


def test_export_polygon_excel_and_pdf(monkeypatch):
    _patch_store(monkeypatch, FakePolygonStore())
    client = TestClient(create_app())

    response = client.post(
        "/api/point-match/analyze",
        files={"file": ("kawasan.geojson", _polygon_geojson_bytes(), "application/geo+json")},
    )
    token = response.json()["token"]

    excel_resp = client.get(f"/api/point-match/{token}/export.xlsx")
    assert excel_resp.status_code == 200
    assert "spreadsheetml" in excel_resp.headers["content-type"]
    assert len(excel_resp.content) > 1000

    pdf_resp = client.get(f"/api/point-match/{token}/export.pdf")
    assert pdf_resp.status_code == 200
    assert "pdf" in pdf_resp.headers["content-type"]
    assert len(pdf_resp.content) > 1000
