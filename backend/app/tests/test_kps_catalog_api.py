"""Tes unit untuk endpoint katalog data KPS (/api/kps-catalog)."""

from __future__ import annotations

from typing import Any
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.kps_catalog import router
from app.services.kps_catalog_service import KpsCatalogService


class _FakeCatalogService:
    def get_catalog_meta(self, force_refresh: bool = False) -> dict[str, Any]:
        return {
            "summary": {
                "total_kps": 100,
                "total_luas_ha": 50000.0,
                "total_provinsi": 10,
                "total_balai": 5,
                "kps_hotspot_30d": 12,
                "kps_burned": 8,
            },
            "filters": {
                "skemas": ["PPHD", "PPHKm"],
                "wilkers": ["Balai PS Banjarbaru"],
                "provinces": ["Kalimantan Barat"],
            },
        }

    def get_kps_catalog(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "pagination": {
                "page": kwargs.get("page", 1),
                "page_size": kwargs.get("page_size", 25),
                "total_records": 1,
                "total_pages": 1,
            },
            "items": [
                {
                    "id": 1,
                    "lembaga": "LPHD TELUK MESJID",
                    "no_sk": "SK.123/2021",
                    "tgl_sk": "2021-05-10",
                    "skema": "PPHD",
                    "nama_prov": "Riau",
                    "nama_kab": "Pelalawan",
                    "nama_kec": "Kuala Kampar",
                    "nama_desa": "Teluk Mesjid",
                    "wilker_bps": "Balai PS Palembang",
                    "luas_final": 1250.5,
                    "luas_hl": 1000.0,
                    "luas_hp": 250.5,
                    "luas_hpt": 0.0,
                    "luas_hpk": 0.0,
                    "luas_hk": 0.0,
                    "jml_kk": 150,
                    "hotspot_count_30d": 3,
                    "last_hotspot_at": "2026-08-25T10:00:00Z",
                    "burned_area_ha": 5.2,
                }
            ],
        }

    def export_kps_catalog_csv(self, **kwargs: Any) -> str:
        return "ID,Nama Lembaga / KPS\n1,LPHD TELUK MESJID\n"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake_service = _FakeCatalogService()
    monkeypatch.setattr("app.api.kps_catalog.get_kps_catalog_service", lambda: fake_service)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_kps_catalog_list(client: TestClient) -> None:
    res = client.get("/kps-catalog?page=1&page_size=10&search=TELUK")
    assert res.status_code == 200
    data = res.json()
    assert "pagination" in data
    assert data["pagination"]["page"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["lembaga"] == "LPHD TELUK MESJID"


def test_get_kps_catalog_meta(client: TestClient) -> None:
    res = client.get("/kps-catalog/meta")
    assert res.status_code == 200
    data = res.json()
    assert data["summary"]["total_kps"] == 100
    assert "skemas" in data["filters"]


def test_export_kps_catalog(client: TestClient) -> None:
    res = client.get("/kps-catalog/export")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    assert "LPHD TELUK MESJID" in res.text
