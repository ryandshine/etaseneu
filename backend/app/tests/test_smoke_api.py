"""Tes lapisan asap: proxy tile citra satelit NASA GIBS + grid prakiraan PM2.5.

TIDAK menyentuh Postgres maupun jaringan: semua panggilan upstream
(`smoke_service.fetch_imagery_tile` / `fetch_pm25_cube`) di-monkeypatch, dan
direktori cache diarahkan ke tmp_path. Tidak perlu store `_Disabled*` seperti
tes LayerService (lihat bahaya #1 di CLAUDE.md) karena endpoint ini tidak
memakai PostgresStore sama sekali.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import smoke as smoke_api
from app.core.config import get_settings
from app.main import create_app
from app.services import smoke_service

LAYER = "VIIRS_SNPP_CorrectedReflectance_TrueColor"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke_api, "_cache_dir", lambda: tmp_path)
    return TestClient(create_app())


# --------------------------------------------------------------------------
# Tile citra satelit (GIBS)
# --------------------------------------------------------------------------


def test_imagery_rejects_layer_outside_whitelist(client):
    # Whitelist mencegah endpoint dipakai sebagai proxy terbuka ke host lain.
    resp = client.get(f"/api/smoke/imagery/../../etc/{_today_utc()}/5/25/16")
    assert resp.status_code in (400, 404)
    resp = client.get(f"/api/smoke/imagery/NOT_A_LAYER/{_today_utc()}/5/25/16")
    assert resp.status_code == 400


@pytest.mark.parametrize("bad_date", ["2026-13-40", "hari-ini", "20260919", "2026-9-9"])
def test_imagery_rejects_malformed_date(client, bad_date):
    resp = client.get(f"/api/smoke/imagery/{LAYER}/{bad_date}/5/25/16")
    assert resp.status_code == 400


def test_imagery_rejects_date_too_old_or_future(client):
    assert client.get(f"/api/smoke/imagery/{LAYER}/{_days_ago(90)}/5/25/16").status_code == 400
    future = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%d")
    assert client.get(f"/api/smoke/imagery/{LAYER}/{future}/5/25/16").status_code == 400


@pytest.mark.parametrize("z,x,y", [(10, 0, 0), (-1, 0, 0), (5, 32, 0), (5, 0, 32), (5, -1, 0)])
def test_imagery_rejects_tile_coordinates_out_of_range(client, z, x, y):
    resp = client.get(f"/api/smoke/imagery/{LAYER}/{_today_utc()}/{z}/{x}/{y}")
    assert resp.status_code == 400


def test_imagery_miss_then_hit_serves_from_disk_cache(client, monkeypatch):
    calls = []

    async def fake_fetch(layer, date, z, x, y, timeout_seconds=15.0):
        calls.append((layer, date, z, x, y))
        return JPEG

    monkeypatch.setattr(smoke_service, "fetch_imagery_tile", fake_fetch)
    url = f"/api/smoke/imagery/{LAYER}/{_today_utc()}/5/25/16"

    first = client.get(url)
    assert first.status_code == 200
    assert first.content == JPEG
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["x-tile-cache"] == "miss"

    second = client.get(url)
    assert second.content == JPEG
    assert second.headers["x-tile-cache"] == "hit"
    assert len(calls) == 1, "ubin yang sama tidak boleh diambil ulang dari NASA selama TTL"


def test_imagery_upstream_failure_serves_stale_cache(client, monkeypatch, tmp_path):
    async def failing_fetch(*args, **kwargs):
        raise httpx.ConnectError("GIBS down")

    monkeypatch.setattr(smoke_service, "fetch_imagery_tile", failing_fetch)
    date = _today_utc()
    url = f"/api/smoke/imagery/{LAYER}/{date}/5/25/16"

    # Tanpa cache sama sekali -> 502 (bukan crash).
    assert client.get(url).status_code == 502

    # Dengan cache BASI -> tetap disajikan daripada ubin kosong.
    stale = tmp_path / smoke_api.tile_cache_filename(LAYER, date, 5, 25, 16)
    stale.write_bytes(JPEG)
    old = time.time() - 7 * 24 * 3600
    os.utime(stale, (old, old))
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.content == JPEG
    assert resp.headers["x-tile-cache"] == "stale"


def test_imagery_missing_upstream_tile_returns_transparent_png(client, monkeypatch):
    async def none_fetch(*args, **kwargs):
        return None  # GIBS 404: belum ada citra untuk tanggal/ubin ini

    monkeypatch.setattr(smoke_service, "fetch_imagery_tile", none_fetch)
    resp = client.get(f"/api/smoke/imagery/{LAYER}/{_today_utc()}/5/25/16")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")


def test_imagery_url_is_built_for_gibs_wmtscompatible_level9():
    url = smoke_service.build_gibs_tile_url(LAYER, "2026-09-19", 5, 25, 16)
    assert url == (
        "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
        f"{LAYER}/default/2026-09-19/GoogleMapsCompatible_Level9/5/16/25.jpg"
    )  # urutan GIBS: {z}/{row=y}/{col=x}


# --------------------------------------------------------------------------
# Grid PM2.5 (CAMS via Open-Meteo)
# --------------------------------------------------------------------------


def _fake_cube(hours: int = 72):
    start = datetime(2026, 9, 20, 0, 0)
    times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)]
    # nilai = jam ke-h di setiap sel, supaya mudah dicek slice-nya
    n = smoke_service.NX * smoke_service.NY
    return {"times": times, "hours": [[float(h)] * n for h in range(hours)]}


def test_pm25_grid_shape_matches_header():
    assert smoke_service.NX == 33 and smoke_service.NY == 14
    assert len(smoke_service.GRID_POINTS) == smoke_service.NX * smoke_service.NY == 462
    # baris-mayor, lintang menurun -- konvensi yang sama dengan lapisan cuaca/angin
    assert smoke_service.GRID_POINTS[0] == (7.5, 94.0)
    assert smoke_service.GRID_POINTS[-1] == (-12.0, 142.0)


def test_slice_pm25_picks_current_hour_plus_offset():
    cube = _fake_cube()
    now = datetime(2026, 9, 20, 11, 42)  # jam WIB 11 -> indeks 11
    now_slice = smoke_service.slice_pm25(cube, offset_hours=0, now=now)
    assert now_slice["data"][0] == 11.0
    assert now_slice["header"]["valid_time"] == "2026-09-20T11:00"

    later = smoke_service.slice_pm25(cube, offset_hours=24, now=now)
    assert later["data"][0] == 35.0
    assert later["header"]["valid_time"] == "2026-09-21T11:00"
    assert later["header"]["offset_hours"] == 24


def test_slice_pm25_clamps_to_last_available_hour():
    cube = _fake_cube(hours=30)
    out = smoke_service.slice_pm25(cube, offset_hours=48, now=datetime(2026, 9, 20, 11, 0))
    assert out["data"][0] == 29.0  # jam terakhir yang ada, bukan IndexError


def test_pm25_endpoint_rejects_offset_out_of_range(client):
    assert client.get("/api/smoke/pm25?offset_hours=-1").status_code == 400
    assert client.get("/api/smoke/pm25?offset_hours=73").status_code == 400


def test_pm25_endpoint_caches_cube_between_requests(client, monkeypatch):
    calls = []

    async def fake_cube(timeout_seconds=30.0):
        calls.append(1)
        return _fake_cube()

    monkeypatch.setattr(smoke_service, "fetch_pm25_cube", fake_cube)

    first = client.get("/api/smoke/pm25?offset_hours=0")
    assert first.status_code == 200
    body = first.json()
    assert body["header"]["nx"] == 33 and body["header"]["ny"] == 14
    assert len(body["data"]) == 462
    assert "CAMS" in body["header"]["source"]

    second = client.get("/api/smoke/pm25?offset_hours=12")
    assert second.status_code == 200
    assert second.json()["header"]["offset_hours"] == 12
    assert len(calls) == 1, "satu kubus cache melayani semua offset; jangan tembak Open-Meteo per permintaan"


def test_pm25_endpoint_serves_stale_cube_when_upstream_fails(client, monkeypatch, tmp_path):
    async def ok_cube(timeout_seconds=30.0):
        return _fake_cube()

    monkeypatch.setattr(smoke_service, "fetch_pm25_cube", ok_cube)
    assert client.get("/api/smoke/pm25").status_code == 200

    # Buat cache basi lalu matikan upstream.
    cache_file = tmp_path / smoke_api.PM25_CACHE_FILENAME
    old = time.time() - 24 * 3600
    os.utime(cache_file, (old, old))

    async def failing_cube(timeout_seconds=30.0):
        raise httpx.ConnectError("open-meteo down")

    monkeypatch.setattr(smoke_service, "fetch_pm25_cube", failing_cube)
    resp = client.get("/api/smoke/pm25")
    assert resp.status_code == 200, "cache basi lebih baik daripada error"


def test_pm25_endpoint_502_when_upstream_fails_without_cache(client, monkeypatch):
    async def failing_cube(timeout_seconds=30.0):
        raise httpx.ConnectError("open-meteo down")

    monkeypatch.setattr(smoke_service, "fetch_pm25_cube", failing_cube)
    assert client.get("/api/smoke/pm25").status_code == 502


# --------------------------------------------------------------------------
# Gerbang auth (API_REQUIRE_AUTH)
# --------------------------------------------------------------------------


def test_auth_gate_protects_pm25_but_not_imagery_tiles(tmp_path, monkeypatch):
    monkeypatch.setenv("API_REQUIRE_AUTH", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(smoke_api, "_cache_dir", lambda: tmp_path)

    async def fake_fetch(*args, **kwargs):
        return JPEG

    monkeypatch.setattr(smoke_service, "fetch_imagery_tile", fake_fetch)
    client = TestClient(create_app())

    assert client.get("/api/smoke/pm25").status_code == 401
    # Leaflet memuat ubin lewat <img src>, tak bisa membawa header Bearer --
    # sama seperti /api/kawasan-hutan/tile, sengaja tidak digerbang.
    assert client.get(f"/api/smoke/imagery/{LAYER}/{_today_utc()}/5/25/16").status_code == 200
