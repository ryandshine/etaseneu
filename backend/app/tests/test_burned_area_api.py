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
    # polygon_ids terisi -> endpoint juga memanggil burned_area_unique_ha();
    # tanpa mock ini test diam-diam menyentuh PostgreSQL sungguhan.
    monkeypatch.setattr(PostgresStore, "burned_area_unique_ha", lambda self, polygon_ids: None)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/summary?polygon_ids=42854")

    assert response.status_code == 200
    assert captured["polygon_ids"] == [42854]


def test_burned_area_geometry_includes_is_estimated_flag(monkeypatch) -> None:
    """Titik centroid perkiraan (KPS kecil tanpa bentuk piksel yang bisa
    divektorisasi) harus bisa dibedakan frontend dari bentuk asli hasil
    reduceToVectors, supaya digambar beda (bukan disamakan begitu saja)."""
    from app.services.postgres_store import PostgresStore

    fake_rows = [
        {"polygon_metadata_id": 1, "year": 2026, "month": 3, "burned_area_ha": 50.0,
         "geometry_json": {"type": "Polygon", "coordinates": []}, "is_estimated": False},
        {"polygon_metadata_id": 2, "year": 2026, "month": 3, "burned_area_ha": 2.1,
         "geometry_json": {"type": "Point", "coordinates": [110.0, -1.0]}, "is_estimated": True},
    ]
    monkeypatch.setattr(PostgresStore, "read_burned_area_geometries", lambda self, ids, **kwargs: fake_rows)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/geometry?polygon_ids=1&polygon_ids=2")

    assert response.status_code == 200
    features = response.json()["features"]
    assert features[0]["properties"]["is_estimated"] is False
    assert features[1]["properties"]["is_estimated"] is True
    assert features[1]["geometry"]["type"] == "Point"


def test_burned_area_map_overlay_is_public_and_formats_period(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    fake_rows = [
        {"polygon_metadata_id": 49463, "lembaga": "KOPERASI X", "skema": "PPHKm",
         "nama_prov": "Riau", "wilker_bps": "BPSKL", "latest_period": 202604,
         "burned_months": 2, "burned_ha": 1786.3, "is_estimated": False,
         "geometry_json": {"type": "MultiPolygon", "coordinates": []}},
        {"polygon_metadata_id": 49735, "lembaga": "KT KECIL", "skema": "PPHKm",
         "nama_prov": "Lampung", "wilker_bps": "BPSKL", "latest_period": 202603,
         "burned_months": 1, "burned_ha": 2.1, "is_estimated": True,
         "geometry_json": {"type": "Point", "coordinates": [104.5, -5.0]}},
    ]
    monkeypatch.setattr(PostgresStore, "read_burned_area_map_overlay", lambda self, **kwargs: fake_rows)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/map-overlay?year=2026")

    assert response.status_code == 200
    body = response.json()
    assert body["kps_count"] == 2
    assert body["total_ha"] == pytest.approx(1788.4)
    # 202604 (integer, biar bisa di-MAX() di SQL) harus jadi label yang terbaca
    assert body["features"][0]["properties"]["latest_period"] == "2026-04"
    assert body["features"][0]["properties"]["lembaga"] == "KOPERASI X"
    assert body["features"][1]["properties"]["is_estimated"] is True


def test_burned_area_map_overlay_handles_missing_period(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    fake_rows = [
        {"polygon_metadata_id": 1, "lembaga": "X", "skema": "PPHD", "nama_prov": "Riau",
         "wilker_bps": None, "latest_period": None, "burned_months": 0,
         "burned_ha": 0.0, "is_estimated": True,
         "geometry_json": {"type": "Point", "coordinates": [0, 0]}},
    ]
    monkeypatch.setattr(PostgresStore, "read_burned_area_map_overlay", lambda self, **kwargs: fake_rows)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/map-overlay")

    assert response.status_code == 200
    assert response.json()["features"][0]["properties"]["latest_period"] is None


def test_burned_area_by_skema_is_public(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    fake_rows = [
        {"skema": "PPHKm", "kps_count": 10, "total_ha": 2413.9},
        {"skema": "PPHD", "kps_count": 10, "total_ha": 1866.5},
        {"skema": "PPHTR", "kps_count": 1, "total_ha": 24.8},
    ]
    monkeypatch.setattr(PostgresStore, "burned_area_by_skema", lambda self, **kwargs: fake_rows)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/by-skema?year=2026")

    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == fake_rows
    assert body["total_ha"] == pytest.approx(2413.9 + 1866.5 + 24.8)


def test_burned_area_frequency_is_public(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    fake_rows = [
        {"lembaga": "LD LINGAT", "periode_terbakar": 4, "pertama": "2026-04-01", "terakhir": "2026-07-01", "total_ha": 1027.4},
        {"lembaga": "LPHD AMBARAWA", "periode_terbakar": 1, "pertama": "2026-03-01", "terakhir": "2026-03-01", "total_ha": 12.0},
    ]
    monkeypatch.setattr(PostgresStore, "burn_frequency_by_lembaga", lambda self: fake_rows)

    client = _client(monkeypatch)
    response = client.get("/api/burned-area/frequency")

    assert response.status_code == 200
    assert response.json() == {"rows": fake_rows}


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


def test_burned_area_refresh_klhk_requires_admin_key(monkeypatch) -> None:
    client = _client(monkeypatch)
    response = client.post("/api/burned-area/refresh-klhk?file_name=burned.geojson")
    assert response.status_code == 401


def test_burned_area_refresh_klhk_calls_service(monkeypatch) -> None:
    from app.core.auth import require_admin_key
    from app.main import create_app
    from fastapi.testclient import TestClient
    import app.api.burned_area as burned_area_api

    calls = []

    def fake_refresh(file_path):
        calls.append(file_path)
        return {"file": "burned.geojson", "computed": 331}

    monkeypatch.setattr(burned_area_api, "refresh_burned_area_from_klhk_file", fake_refresh)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    response = client.post("/api/burned-area/refresh-klhk?file_name=burned.geojson")

    assert response.status_code == 200
    assert response.json() == {"file": "burned.geojson", "computed": 331}
    assert len(calls) == 1
    assert calls[0].endswith("burned.geojson")


def test_burned_area_refresh_klhk_sanitizes_path_traversal(monkeypatch) -> None:
    """file_name datang dari input admin lewat query string -- harus tidak
    bisa dipakai untuk keluar dari KLHK_BURNED_AREA_DIR (mis. ../../etc/passwd)."""
    from app.core.auth import require_admin_key
    from app.main import create_app
    from fastapi.testclient import TestClient
    from app.core.config import get_settings
    import app.api.burned_area as burned_area_api

    calls = []

    def fake_refresh(file_path):
        calls.append(file_path)
        return {"file": "passwd", "computed": 0}

    monkeypatch.setattr(burned_area_api, "refresh_burned_area_from_klhk_file", fake_refresh)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    client.post("/api/burned-area/refresh-klhk?file_name=../../../etc/passwd")

    resolved_dir = str(get_settings().resolved_klhk_burned_area_dir)
    assert calls[0].startswith(resolved_dir)
    assert calls[0] == str(get_settings().resolved_klhk_burned_area_dir / "passwd")


def test_burned_area_refresh_klhk_returns_404_when_file_missing(monkeypatch) -> None:
    from app.core.auth import require_admin_key
    from app.main import create_app
    from fastapi.testclient import TestClient
    from app.services.burned_area_klhk_service import BurnedAreaKlhkError
    import app.api.burned_area as burned_area_api

    def fake_refresh(file_path):
        raise BurnedAreaKlhkError(f"File tidak ditemukan: {file_path}")

    monkeypatch.setattr(burned_area_api, "refresh_burned_area_from_klhk_file", fake_refresh)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    response = client.post("/api/burned-area/refresh-klhk?file_name=tidak-ada.geojson")

    assert response.status_code == 404

