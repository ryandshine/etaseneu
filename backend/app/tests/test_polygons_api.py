"""Tes gate role untuk /api/polygons.

Non-admin (role `user`/`bps`/anonim) hanya boleh menerima geometry poligon
KPS yang sudah dikasarkan; geometry mentah cuma keluar lewat endpoint ekspor
khusus admin. Semua akses store di-stub (bahaya #1: tidak ada DB test).
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.polygons import router
from app.core.auth import issue_token
from app.core.session_store import get_auth_store
from app.models.polygons import PolygonDetail


class _DummyAuthStore:
    enabled = False


class _FakePolygonService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, float | None]] = []

    def get_polygon_detail(self, polygon_metadata_id: int, *, tolerance: float | None = 0.0001):
        self.calls.append((polygon_metadata_id, tolerance))
        if polygon_metadata_id == 999:
            return None
        return PolygonDetail(
            id=polygon_metadata_id,
            layer_key="psagustus2026",
            feature_key="abc123",
            lembaga="LPHD CONTOH",
            nama_prov="LAMPUNG",
            no_sk="SK.123",
            geometry={
                "type": "Polygon",
                "coordinates": [[[105.0, -5.0], [105.1, -5.0], [105.1, -5.1], [105.0, -5.0]]],
            },
        )


@pytest.fixture
def client(monkeypatch) -> tuple[TestClient, _FakePolygonService]:
    fake = _FakePolygonService()
    monkeypatch.setattr("app.api.polygons.get_polygon_service", lambda: fake)

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_auth_store] = lambda: _DummyAuthStore()
    return TestClient(app), fake


def _token(role: str) -> str:
    return issue_token(user_id=1, username=f"{role}-user", role=role)


def _auth(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role)}"}


def test_get_polygon_anonymous_gets_coarse_tolerance(client) -> None:
    tc, fake = client
    resp = tc.get("/api/polygons/5")
    assert resp.status_code == 200
    assert fake.calls == [(5, 0.001)]


def test_get_polygon_non_admin_gets_coarse_tolerance(client) -> None:
    tc, fake = client
    for role in ("user", "bps"):
        fake.calls.clear()
        resp = tc.get("/api/polygons/5", headers=_auth(role))
        assert resp.status_code == 200
        assert fake.calls == [(5, 0.001)]


def test_get_polygon_admin_gets_fine_tolerance(client) -> None:
    tc, fake = client
    resp = tc.get("/api/polygons/5", headers=_auth("admin"))
    assert resp.status_code == 200
    assert fake.calls == [(5, 0.0001)]


def test_get_polygon_missing_returns_404(client) -> None:
    tc, _ = client
    assert tc.get("/api/polygons/999").status_code == 404


def test_export_geojson_rejects_anonymous(client) -> None:
    tc, _ = client
    assert tc.get("/api/polygons/5/export.geojson").status_code == 401


def test_export_geojson_rejects_non_admin(client) -> None:
    tc, _ = client
    for role in ("user", "bps"):
        resp = tc.get("/api/polygons/5/export.geojson", headers=_auth(role))
        assert resp.status_code == 403


def test_export_geojson_admin_downloads_raw_feature_collection(client) -> None:
    tc, fake = client
    resp = tc.get("/api/polygons/5/export.geojson", headers=_auth("admin"))

    assert resp.status_code == 200
    assert fake.calls == [(5, None)]
    assert resp.headers["content-type"].startswith("application/geo+json")
    assert 'attachment; filename="kps-5.geojson"' in resp.headers["content-disposition"]

    body = json.loads(resp.content)
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 1
    feature = body["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Polygon"
    assert feature["properties"]["lembaga"] == "LPHD CONTOH"
    assert "geometry" not in feature["properties"]


def test_export_geojson_admin_missing_returns_404(client) -> None:
    tc, _ = client
    assert tc.get("/api/polygons/999/export.geojson", headers=_auth("admin")).status_code == 404
