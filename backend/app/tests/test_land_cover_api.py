"""Tes endpoint tutupan lahan. Service & store di-fake — tidak ada GEE/DB
nyata (bahaya #1). conftest autouse sudah mematikan API_REQUIRE_AUTH."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.land_cover as lc_mod
from app.main import create_app

YEARS = (2021, 2022, 2023, 2024, 2025)


class _FakeService:
    enabled = True

    def __init__(self, *a, **k):
        pass

    def analyze_polygon(self, polygon_id):
        return {"polygon_id": polygon_id}


class _FakeStore:
    def __init__(self, status=None, result=None, overlay=None, polygons=None):
        self._status = status
        self._result = result
        self._overlay = overlay or []
        self._polygons = polygons or []
        self.running_marked = False

    def list_polygons_with_land_cover_status(self):
        return self._polygons

    def read_land_cover_status(self, polygon_id):
        return self._status

    def read_land_cover_result(self, polygon_id):
        return self._result

    def read_land_cover_overlay(self, polygon_id, year):
        return self._overlay

    def mark_land_cover_running(self, polygon_id, layer_key):
        self.running_marked = True

    def delete_land_cover_result(self, polygon_id):
        self.deleted = polygon_id
        return self._status is not None

    def read_land_cover_target_polygon(self, polygon_id):
        return {"id": polygon_id, "layer_key": "psagustus2026",
                "lembaga": "X", "nama_prov": "Y", "geometry_json": {}}


@pytest.fixture
def client(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(lc_mod, "PostgresStore", lambda *_a, **_k: store)
    monkeypatch.setattr(lc_mod, "LandCoverService", _FakeService)
    c = TestClient(create_app())
    c._store = store  # akses di test
    return c


def test_analyze_503_when_gee_disabled(client, monkeypatch):
    class _Off(_FakeService):
        enabled = False

    monkeypatch.setattr(lc_mod, "LandCoverService", _Off)
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 503


def test_analyze_409_when_busy_elsewhere(client, monkeypatch):
    # Poligon LAIN (999) sedang jalan di memori proses -- lock global harus
    # menolak permintaan analisis poligon 1, terlepas dari status poligon 1
    # sendiri (idle di sini).
    monkeypatch.setattr(
        lc_mod, "land_cover_any_running", lambda: {"polygon_id": 999, "step": "2021 (1/5) — sampel"}
    )
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 409
    assert r.json()["detail"]["busy_elsewhere"] is True
    assert client._store.running_marked is False


def test_analyze_busy_lock_ignores_force(client, monkeypatch):
    # force=true cuma untuk override state basi poligon INI sendiri, BUKAN
    # buat motong antrean saat poligon lain beneran sedang jalan.
    monkeypatch.setattr(
        lc_mod, "land_cover_any_running", lambda: {"polygon_id": 999, "step": "x"}
    )
    r = client.post("/api/land-cover/analyze?force=true", json={"polygon_id": 1})
    assert r.status_code == 409
    assert r.json()["detail"]["busy_elsewhere"] is True


def test_analyze_allows_own_polygon_when_it_is_the_one_running(client, monkeypatch):
    # Kalau yang "sedang jalan" di memori itu poligon YANG SAMA (mis. restart
    # via tombol Mulai ulang), lock global tidak boleh ikut memblokir --
    # pemeriksaan status running/done per-poligon di bawah yang menentukan.
    monkeypatch.setattr(
        lc_mod, "land_cover_any_running", lambda: {"polygon_id": 1, "step": "x"}
    )
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 202


def test_analyze_409_when_running(client):
    client._store._status = {"status": "running", "error_message": None, "computed_at": None}
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 409


def test_analyze_force_overrides_stale_running(client):
    client._store._status = {"status": "running", "error_message": None, "computed_at": None}
    r = client.post("/api/land-cover/analyze?force=true", json={"polygon_id": 1})
    assert r.status_code == 202
    assert client._store.running_marked is True


def test_analyze_409_when_done_without_force(client):
    client._store._status = {"status": "done", "error_message": None, "computed_at": "2026-08-30T00:00:00"}
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 409
    assert r.json()["detail"].get("done") is True or r.json().get("done") is True


def test_analyze_202_starts_job(client):
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 42})
    assert r.status_code == 202
    assert r.json() == {"started": True, "polygon_id": 42}
    assert client._store.running_marked is True


def test_delete_result_removes_rows_and_reports(client):
    client._store._status = {"status": "done", "error_message": None, "computed_at": "x"}
    r = client.delete("/api/land-cover/result?polygon_id=7")
    assert r.status_code == 200
    assert r.json() == {"deleted": True, "polygon_id": 7}
    assert client._store.deleted == 7


def test_delete_result_409_while_polygon_actually_running(client, monkeypatch):
    monkeypatch.setattr(lc_mod, "land_cover_run_state", lambda pid: {"step": "x"})
    r = client.delete("/api/land-cover/result?polygon_id=7")
    assert r.status_code == 409
    assert not hasattr(client._store, "deleted")


def test_polygons_list_returns_store_rows(client):
    client._store._polygons = [
        {"polygon_metadata_id": 1, "layer_key": "psagustus2026", "lembaga": "A",
         "nama_prov": "Riau", "nama_kab": "Kampar", "nama_kec": None, "skema": "HD",
         "luas_final": 120.5, "land_cover_status": "done",
         "land_cover_computed_at": "2026-08-30T00:00:00"},
        {"polygon_metadata_id": 2, "layer_key": "HUTAN_ADAT_APR26", "lembaga": "B",
         "nama_prov": "Riau", "nama_kab": "Kampar", "nama_kec": None, "skema": None,
         "luas_final": 50.0, "land_cover_status": None, "land_cover_computed_at": None},
    ]
    r = client.get("/api/land-cover/polygons")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["land_cover_status"] == "done"
    assert body[1]["land_cover_status"] is None


def test_status_idle_when_no_row(client):
    r = client.get("/api/land-cover/status", params={"polygon_id": 1})
    assert r.status_code == 200
    assert r.json()["state"] == "idle"
    assert r.json()["busy_elsewhere"] is False


def test_status_busy_elsewhere_true_for_other_polygon(client, monkeypatch):
    monkeypatch.setattr(
        lc_mod, "land_cover_any_running", lambda: {"polygon_id": 999, "step": "x"}
    )
    r = client.get("/api/land-cover/status", params={"polygon_id": 1})
    assert r.json()["busy_elsewhere"] is True


def test_status_busy_elsewhere_false_for_the_running_polygon_itself(client, monkeypatch):
    monkeypatch.setattr(
        lc_mod, "land_cover_any_running", lambda: {"polygon_id": 1, "step": "x"}
    )
    r = client.get("/api/land-cover/status", params={"polygon_id": 1})
    assert r.json()["busy_elsewhere"] is False


def test_result_404_before_done(client):
    r = client.get("/api/land-cover/result", params={"polygon_id": 1})
    assert r.status_code == 404


def test_result_shape_when_done(client):
    client._store._result = {
        "meta": {"model_trees": 150, "n_training": 7200, "oob_accuracy": 0.81,
                 "duration_s": 130.0, "computed_at": "2026-08-30T00:00:00",
                 "source": "s", "label_source": "l"},
        "year_class": [
            {"year": y, "class_key": k, "area_ha": 100.0, "pct": 20.0}
            for y in YEARS for k in ("hutan", "semak", "pertanian", "terbuka", "air")
        ],
    }
    r = client.get("/api/land-cover/result", params={"polygon_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["years"] == list(YEARS)
    assert body["table"]["2021"]["hutan"]["pct"] == 20.0
    assert set(body["net_change"].keys()) == {"hutan", "semak", "pertanian", "terbuka", "air"}


def test_overlay_404_for_year_out_of_range(client):
    r = client.get("/api/land-cover/overlay", params={"polygon_id": 1, "year": 2019})
    assert r.status_code == 404


def test_overlay_featurecollection_when_done(client):
    client._store._status = {"status": "done", "error_message": None, "computed_at": "x"}
    client._store._overlay = [
        {"class_key": "hutan", "area_ha": 100.0, "pct": 50.0,
         "geometry_json": {"type": "MultiPolygon", "coordinates": []}},
    ]
    r = client.get("/api/land-cover/overlay", params={"polygon_id": 1, "year": 2021})
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["properties"]["class_key"] == "hutan"
