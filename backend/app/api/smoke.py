"""Lapisan asap: proxy+cache ubin citra satelit NASA GIBS dan grid PM2.5 CAMS.

Dua router terpisah karena beda gerbang auth (lihat `app/api/router.py`):

* `tile_router` -- ubin citra (`/smoke/imagery/...`). TIDAK digerbang: Leaflet
  memuatnya lewat `<img src>` yang tidak bisa membawa header Authorization
  (alasan sama dengan `/api/kawasan-hutan/tile`). Aman: sumbernya data publik
  NASA, tidak ada data ETASENEU yang lewat sini.
* `router` -- grid PM2.5 (`/smoke/pm25`). Dimuat lewat `authFetch`, jadi
  mengikuti gerbang baca `API_REQUIRE_AUTH` seperti router cuaca/angin.

Pola cache file-based sama seperti `app/api/kawasan_hutan.py` & `weather.py`
(BUKAN Postgres: blob biner per-ubin hanya membengkakkan DB produksi bersama,
lihat bahaya #1 di CLAUDE.md). Kalau NASA/Open-Meteo lambat atau down, cache
basi disajikan daripada gagal total.
"""

from __future__ import annotations

import base64
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

from app.core.config import get_settings
from app.services import smoke_service
from app.services.weather_service import is_cache_valid, read_json_cache, write_json_cache

logger = logging.getLogger(__name__)

router = APIRouter()
tile_router = APIRouter()

PM25_CACHE_FILENAME = "smoke_pm25_cube.json"
PM25_CACHE_TTL_SECONDS = 3 * 3600  # CAMS diperbarui ~2x/hari; 3 jam cukup segar
MAX_OFFSET_HOURS = 48

TILE_TTL_TODAY_SECONDS = 3600  # citra hari ini masih bertambah seiring lintasan satelit
TILE_TTL_PAST_SECONDS = 24 * 3600
TILE_PRUNE_AFTER_DAYS = 3
_PRUNE_INTERVAL_SECONDS = 3600
_last_prune = 0.0

# PNG 1x1 transparan: dikembalikan untuk ubin yang belum ada di GIBS (404),
# supaya peta tidak menampilkan ikon gambar rusak.
TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _cache_dir() -> Path:
    d = get_settings().resolved_cache_dir / "smoke"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tile_cache_filename(layer: str, date: str, z: int, x: int, y: int) -> str:
    return f"{layer}_{date}_{z}_{x}_{y}.tile"


def _utc_today() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _validate_tile_request(layer: str, date: str, z: int, x: int, y: int) -> datetime:
    """Validasi ketat -- semua nilai ini masuk ke URL upstream & nama file cache."""
    if layer not in smoke_service.IMAGERY_LAYERS:
        raise HTTPException(status_code=400, detail="Layer citra tidak dikenal.")
    if not smoke_service.DATE_PATTERN.match(date):
        raise HTTPException(status_code=400, detail="Format tanggal harus YYYY-MM-DD.")
    try:
        day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Tanggal tidak valid.") from exc
    today = _utc_today()
    if day > today + timedelta(days=1) or day < today - timedelta(days=smoke_service.MAX_IMAGERY_AGE_DAYS):
        raise HTTPException(status_code=400, detail="Tanggal di luar rentang yang didukung.")
    if not 0 <= z <= smoke_service.MAX_TILE_ZOOM:
        raise HTTPException(status_code=400, detail="Zoom di luar rentang.")
    limit = 2**z
    if not (0 <= x < limit and 0 <= y < limit):
        raise HTTPException(status_code=400, detail="Koordinat ubin di luar rentang.")
    return day


def _media_type(content: bytes) -> str:
    # Ubin tersimpan bisa JPEG (utuh) atau PNG (piksel kosong dibuat transparan).
    return "image/png" if content.startswith(b"\x89PNG") else "image/jpeg"


def _tile_ttl(day: datetime) -> int:
    return TILE_TTL_TODAY_SECONDS if day >= _utc_today() else TILE_TTL_PAST_SECONDS


def _prune_old_tiles(directory: Path) -> None:
    """Buang ubin lama supaya cache tidak tumbuh tanpa batas (maks 1x/jam)."""
    global _last_prune
    now = time.time()
    if now - _last_prune < _PRUNE_INTERVAL_SECONDS:
        return
    _last_prune = now
    cutoff = now - TILE_PRUNE_AFTER_DAYS * 24 * 3600
    # "*.jpg" = cache versi lama (sebelum ubin diproses); "*.tile" = sekarang.
    for path in [*directory.glob("*.tile"), *directory.glob("*.jpg")]:
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


@tile_router.get("/smoke/imagery/{layer}/{date}/{z}/{x}/{y}")
async def get_smoke_imagery_tile(layer: str, date: str, z: int, x: int, y: int) -> Response:
    day = _validate_tile_request(layer, date, z, x, y)
    ttl = _tile_ttl(day)
    cache_path = _cache_dir() / tile_cache_filename(layer, date, z, x, y)

    if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < ttl:
        cached_tile = cache_path.read_bytes()
        return Response(
            content=cached_tile,
            media_type=_media_type(cached_tile),
            headers={"Cache-Control": f"public, max-age={min(ttl, 900)}", "X-Tile-Cache": "hit"},
        )

    try:
        content = await smoke_service.fetch_imagery_tile(layer, date, z, x, y, timeout_seconds=15.0)
    except httpx.HTTPError as exc:
        logger.warning("Gagal ambil ubin citra asap dari GIBS: %s", exc)
        if cache_path.exists():
            stale_tile = cache_path.read_bytes()
            return Response(
                content=stale_tile,
                media_type=_media_type(stale_tile),
                headers={"Cache-Control": "no-cache", "X-Tile-Cache": "stale"},
            )
        raise HTTPException(status_code=502, detail="Gagal mengambil citra satelit asap.") from exc

    if content is None:
        return Response(
            content=TRANSPARENT_PNG,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=600", "X-Tile-Cache": "empty"},
        )

    content = smoke_service.make_nodata_transparent(content)

    try:
        cache_path.write_bytes(content)
        _prune_old_tiles(cache_path.parent)
    except OSError:
        logger.warning("Gagal menulis cache ubin citra asap (jalan tanpa cache)")

    return Response(
        content=content,
        media_type=_media_type(content),
        headers={"Cache-Control": f"public, max-age={min(ttl, 900)}", "X-Tile-Cache": "miss"},
    )


@router.get("/smoke/pm25")
async def get_smoke_pm25(
    offset_hours: int = Query(0, description="Geser jam dari sekarang (0 s.d. 48)."),
) -> dict[str, Any]:
    """Grid PM2.5 prakiraan (CAMS) untuk satu jam: sekarang + `offset_hours`."""
    if not 0 <= offset_hours <= MAX_OFFSET_HOURS:
        raise HTTPException(status_code=400, detail=f"offset_hours harus 0 s.d. {MAX_OFFSET_HOURS}.")

    cache_file = _cache_dir() / PM25_CACHE_FILENAME
    cached = read_json_cache(cache_file)
    cached = cached if isinstance(cached, dict) and "times" in cached and "hours" in cached else None

    if cached is not None and is_cache_valid(cache_file, PM25_CACHE_TTL_SECONDS):
        cube = cached
    else:
        try:
            cube = await smoke_service.fetch_pm25_cube(timeout_seconds=get_settings().request_timeout_seconds)
        except Exception as exc:  # noqa: BLE001 -- upstream apa pun: pilih cache basi bila ada
            if cached is None:
                logger.error("Gagal ambil grid PM2.5 dan tidak ada cache: %s", exc)
                raise HTTPException(status_code=502, detail="Gagal mengambil prakiraan PM2.5.") from exc
            logger.warning("Grid PM2.5 upstream gagal, menyajikan cache basi: %s", exc)
            cube = cached
        else:
            write_json_cache(cache_file, cube)

    return smoke_service.slice_pm25(cube, offset_hours=offset_hours)
