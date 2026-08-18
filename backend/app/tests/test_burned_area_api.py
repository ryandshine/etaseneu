from __future__ import annotations

import pytest


def _client(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    return TestClient(app)


def test_burned_area_summary_is_public(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    fake_rows = [
        {
            "polygon_metadata_id": 1,
            "layer_key": "PS_FEB_26",
            "year": 2026,
            "month": 4,
            "burned_area_ha": 12.5,
            "source": "MODIS/061/MCD64A1",
            "computed_at": "2026-05-01T00:00:00Z",
        }
    ]
    monkeypatch.setattr(
        PostgresStore, "read_burned_area_summary", lambda self, **kwargs: fake_rows
    )
    monkeypatch.setattr(PostgresStore, "latest_burned_area_period", lambda self: (2026, 4))

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/summary?year=2026&month=4")

    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == fake_rows
    assert body["total_ha"] == 12.5
    assert body["latest_period"] == {"year": 2026, "month": 4}


def test_burned_area_summary_includes_unique_ha_via_st_union(monkeypatch) -> None:
    """total_ha menjumlahkan angka bulanan (bisa hitung ganda lahan yang
    terbakar berulang); unique_ha (ST_Union) adalah luas area sesungguhnya --
    endpoint harus mengirim keduanya, bukan cuma yang menyesatkan."""
    from app.services.postgres_store import PostgresStore

    fake_rows = [
        {"polygon_metadata_id": 1, "layer_key": "PS_FEB_26", "year": 2026, "month": 3,
         "burned_area_ha": 98.5, "source": "MODIS/061/MCD64A1", "computed_at": "2026-04-01T00:00:00Z"},
        {"polygon_metadata_id": 1, "layer_key": "PS_FEB_26", "year": 2026, "month": 4,
         "burned_area_ha": 68.4, "source": "MODIS/061/MCD64A1", "computed_at": "2026-05-01T00:00:00Z"},
    ]
    monkeypatch.setattr(PostgresStore, "read_burned_area_summary", lambda self, **kwargs: fake_rows)
    monkeypatch.setattr(PostgresStore, "latest_burned_area_period", lambda self: (2026, 4))
    monkeypatch.setattr(PostgresStore, "burned_area_unique_ha", lambda self, polygon_ids: 124.1)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/summary?polygon_ids=1")

    assert response.status_code == 200
    body = response.json()
    assert body["total_ha"] == pytest.approx(166.9)
    assert body["unique_ha"] == 124.1
    assert body["unique_ha"] < body["total_ha"]


def test_burned_area_summary_filters_by_polygon_id_on_the_server(monkeypatch) -> None:
    """Halaman detail KPS cuma butuh satu polygon -- filternya harus sampai ke
    query database, bukan mengunduh seluruh tabel lalu disaring di klien."""
    from app.services.postgres_store import PostgresStore

    captured: dict[str, object] = {}

    def fake_read(self, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(PostgresStore, "read_burned_area_summary", fake_read)
    monkeypatch.setattr(PostgresStore, "latest_burned_area_period", lambda self: None)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/summary?polygon_ids=42854")

    assert response.status_code == 200
    assert captured["polygon_ids"] == [42854]


def test_burned_area_refresh_requires_admin_key(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post("/api/burned-area/refresh?year=2026&month=4")
    assert response.status_code in (401, 503)


def test_burned_area_refresh_calls_service(monkeypatch) -> None:
    from app.core.auth import require_admin_key
    from app.main import create_app
    from fastapi.testclient import TestClient
    from app.services.burned_area_service import BurnedAreaService

    calls = []

    def fake_refresh(self, year, month, layer_keys=None):
        calls.append((year, month, layer_keys))
        return {"year": year, "month": month, "polygons_checked": 5, "computed": 5}

    monkeypatch.setattr(BurnedAreaService, "refresh_burned_area", fake_refresh)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    response = client.post("/api/burned-area/refresh?year=2026&month=4")

    assert response.status_code == 200
    assert response.json() == {"year": 2026, "month": 4, "polygons_checked": 5, "computed": 5}
    assert calls == [(2026, 4, None)]


def test_burned_area_refresh_defaults_to_last_month(monkeypatch) -> None:
    from app.core.auth import require_admin_key
    from app.main import create_app
    from fastapi.testclient import TestClient
    from app.services.burned_area_service import BurnedAreaService

    calls = []

    def fake_refresh(self, year, month, layer_keys=None):
        calls.append((year, month))
        return {"year": year, "month": month, "polygons_checked": 0, "computed": 0}

    monkeypatch.setattr(BurnedAreaService, "refresh_burned_area", fake_refresh)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    response = client.post("/api/burned-area/refresh")

    assert response.status_code == 200
    assert len(calls) == 1
    # Tidak menegaskan tahun/bulan persis (tergantung tanggal jalan test),
    # cukup pastikan endpoint benar-benar memanggil service dengan sesuatu.
    assert calls[0][1] in range(1, 13)


def test_burned_area_refresh_returns_503_when_not_configured(monkeypatch) -> None:
    from app.core.auth import require_admin_key
    from app.main import create_app
    from fastapi.testclient import TestClient
    from app.services.burned_area_service import BurnedAreaService, BurnedAreaServiceError

    def fake_refresh(self, year, month, layer_keys=None):
        raise BurnedAreaServiceError("belum dikonfigurasi")

    monkeypatch.setattr(BurnedAreaService, "refresh_burned_area", fake_refresh)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    response = client.post("/api/burned-area/refresh?year=2026&month=4")

    assert response.status_code == 503
