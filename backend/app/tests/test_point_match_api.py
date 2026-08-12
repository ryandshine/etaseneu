import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import point_result_store as store_module


@pytest.fixture(autouse=True)
def fresh_stores(monkeypatch):
    """Setiap test dapat penyimpanan & pembatas laju sendiri supaya tidak
    saling mempengaruhi lewat state global."""
    monkeypatch.setattr(store_module, "point_result_store", store_module.PointResultStore())
    monkeypatch.setattr(
        store_module, "upload_rate_limiter", store_module.RateLimiter(max_requests=10, window_seconds=600)
    )
    import app.api.point_match as api_module

    monkeypatch.setattr(api_module, "point_result_store", store_module.point_result_store)
    monkeypatch.setattr(api_module, "upload_rate_limiter", store_module.upload_rate_limiter)
    yield


class FakeStore:
    enabled = True

    def __init__(self, matches=None):
        self._matches = matches

    def match_points_to_polygons(self, coordinates):
        if self._matches is not None:
            return self._matches
        return [
            {
                "lembaga": "LPHD DEMO",
                "wilker_bps": "Balai PS X",
                "nama_prov": "Kalbar",
                "nama_kab": "Ketapang",
                "nama_kec": None,
                "nama_desa": None,
                "skema": "HD",
                "no_sk": "SK.1",
                "tgl_sk": "2020-01-01",
            }
            for _ in coordinates
        ]


def _patch_store(monkeypatch, fake):
    import app.api.point_match as api_module

    monkeypatch.setattr(api_module, "PostgresStore", lambda _url: fake)


def _geojson_bytes(count=2):
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [110.0 + i * 0.01, -1.0]},
            "properties": {"kode": f"A-{i}"},
        }
        for i in range(count)
    ]
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def _upload(client, content=None, filename="titik.geojson"):
    # Sengaja membedakan None (pakai default) dari b"" (memang mau uji berkas
    # kosong) -- `content or default` akan menelan b"" karena falsy.
    payload = _geojson_bytes() if content is None else content
    return client.post(
        "/api/point-match/analyze",
        files={"file": (filename, payload, "application/geo+json")},
    )


def test_analyze_returns_summary_and_preview(monkeypatch):
    _patch_store(monkeypatch, FakeStore())
    client = TestClient(create_app())

    response = _upload(client)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_points"] == 2
    assert body["summary"]["inside_count"] == 2
    assert body["property_columns"] == ["kode"]
    assert len(body["preview_rows"]) == 2
    assert body["token"]


def test_analyze_reports_points_outside_kps(monkeypatch):
    _patch_store(monkeypatch, FakeStore(matches=[None, None]))
    client = TestClient(create_app())

    body = _upload(client).json()

    assert body["summary"]["inside_count"] == 0
    assert body["summary"]["outside_count"] == 2


def test_rejects_unsupported_extension(monkeypatch):
    _patch_store(monkeypatch, FakeStore())
    client = TestClient(create_app())

    response = _upload(client, content=b"a,b\n1,2", filename="data.csv")

    assert response.status_code == 400
    assert "tidak didukung" in response.json()["detail"]


def test_rejects_empty_file(monkeypatch):
    _patch_store(monkeypatch, FakeStore())
    client = TestClient(create_app())

    response = _upload(client, content=b"")

    assert response.status_code == 400


def test_parse_failure_returns_readable_message(monkeypatch):
    _patch_store(monkeypatch, FakeStore())
    client = TestClient(create_app())

    response = _upload(client, content=b"{ini bukan json}")

    assert response.status_code == 400
    assert "GeoJSON" in response.json()["detail"]


def test_excel_and_pdf_download_use_the_token(monkeypatch):
    _patch_store(monkeypatch, FakeStore())
    client = TestClient(create_app())
    token = _upload(client).json()["token"]

    excel = client.get(f"/api/point-match/{token}/export.xlsx")
    assert excel.status_code == 200
    assert excel.content[:2] == b"PK"  # xlsx = arsip zip
    assert "attachment" in excel.headers["content-disposition"]

    pytest.importorskip("weasyprint")
    pdf = client.get(f"/api/point-match/{token}/export.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_unknown_token_tells_user_to_upload_again(monkeypatch):
    _patch_store(monkeypatch, FakeStore())
    client = TestClient(create_app())

    response = client.get("/api/point-match/token-yang-tidak-ada/export.xlsx")

    assert response.status_code == 404
    assert "unggah ulang" in response.json()["detail"].lower()


def test_rate_limit_blocks_flood_of_uploads(monkeypatch):
    """Endpoint ini terbuka untuk umum, jadi pembatas laju bukan hiasan."""
    _patch_store(monkeypatch, FakeStore())
    import app.api.point_match as api_module

    limiter = store_module.RateLimiter(max_requests=2, window_seconds=600)
    monkeypatch.setattr(api_module, "upload_rate_limiter", limiter)
    client = TestClient(create_app())

    assert _upload(client).status_code == 200
    assert _upload(client).status_code == 200
    blocked = _upload(client)

    assert blocked.status_code == 429
    assert blocked.headers.get("retry-after")


def test_limits_endpoint_exposes_caps_for_the_ui():
    client = TestClient(create_app())

    body = client.get("/api/point-match/limits").json()

    assert body["max_points"] > 0
    assert ".kml" in body["supported_extensions"]
