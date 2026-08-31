"""Tes endpoint tutupan lahan. Service & store di-fake — tidak ada GEE/DB
nyata (bahaya #1). conftest autouse sudah mematikan API_REQUIRE_AUTH."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.land_cover as lc_mod
from app.main import create_app

YEARS = (2020, 2021, 2022, 2023, 2024, 2025)


class _FakeService:
    enabled = True

    def __init__(self, *a, **k):
        pass

    def analyze_polygon(self, polygon_id):
        return {"polygon_id": polygon_id}


class _FakeStore:
    def __init__(self, status=None, result=None, overlay=None):
        self._status = status
        self._result = result
        self._overlay = overlay or []
        self.running_marked = False

    def read_land_cover_status(self, polygon_id):
        return self._status

    def read_land_cover_result(self, polygon_id):
        return self._result

    def read_land_cover_overlay(self, polygon_id, year):
        return self._overlay

    def mark_land_cover_running(self, polygon_id, layer_key):
        self.running_marked = True

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


def test_status_idle_when_no_row(client):
    r = client.get("/api/land-cover/status", params={"polygon_id": 1})
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


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
    assert body["table"]["2020"]["hutan"]["pct"] == 20.0
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
    r = client.get("/api/land-cover/overlay", params={"polygon_id": 1, "year": 2020})
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["properties"]["class_key"] == "hutan"
