"""Proxy + cache ubin (tile) overlay Fungsi Kawasan Hutan (KWSHUTAN_AR_250K)
dari layanan ArcGIS resmi Ditjen Planologi Kehutanan.

Kenapa ini ada: sebelumnya browser TIAP PENGGUNA menembak endpoint `export`
ArcGIS itu LANGSUNG (lihat frontend/src/components/KawasanHutanLayer.tsx) --
beban ke server pemerintah itu naik linear dengan jumlah pengguna ETASENEU,
TANPA saling berbagi cache sama sekali, padahal batas fungsi kawasan hutan
(1:250.000, dari SK penunjukan) jarang berubah dalam hitungan hari/minggu.

Proxy ini menyimpan hasil `export` per kombinasi parameter query (yang buat
satu ubin z/x/y tertentu selalu identik) ke disk selama TILE_CACHE_TTL_HOURS
-- jadi SEMUA pengguna yang melihat ubin yang sama berbagi satu hasil cache,
mengubah beban ke server pemerintah dari "per-pengguna" jadi
"per-ubin-unik-per-TTL". Efek samping: peta kita juga jadi lebih cepat untuk
pengguna karena tidak lagi tergantung kecepatan server ArcGIS pemerintah
tiap saat.

Sengaja file-based (pola sama seperti cache grid cuaca di app/api/weather.py
`_cache_path`/`_cache_is_valid`), BUKAN tabel `api_cache_entries` generik --
itu untuk payload JSON kecil, sedangkan ini blob PNG biner per-ubin yang bisa
ribuan file; menaruhnya di Postgres cuma akan membengkakkan DB produksi tanpa
manfaat (lihat bahaya #1 soal DB produksi bersama di CLAUDE.md).
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, Response

from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

ARCGIS_EXPORT_URL = (
    "https://geoportal.planologi.kehutanan.go.id/server/rest/services/"
    "Peta_Interaktif_2026/KWSHUTAN_AR_250K/MapServer/export"
)

# Batas fungsi kawasan hutan berubah jarang -- TTL panjang aman dan yang
# paling menekan beban ke server pemerintah. Kalau ada revisi SK penunjukan
# yang perlu tampil lebih cepat, hapus manual isi direktori cache-nya.
TILE_CACHE_TTL_HOURS = 24 * 7  # 7 hari


def _cache_dir() -> Path:
    d = get_settings().resolved_cache_dir / "kawasan_hutan_tiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(params: dict[str, str]) -> str:
    canonical = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_fresh(path: Path) -> bool:
    return (time.time() - path.stat().st_mtime) < TILE_CACHE_TTL_HOURS * 3600


@router.get("/kawasan-hutan/tile")
async def get_kawasan_hutan_tile(
    bbox: str = Query(...),
    bboxSR: str = Query("3857"),
    imageSR: str = Query("3857"),
    size: str = Query("256,256"),
    dpi: str = Query("96"),
    format: str = Query("png32"),
    transparent: str = Query("true"),
    f: str = Query("image"),
) -> Response:
    params = {
        "bbox": bbox,
        "bboxSR": bboxSR,
        "imageSR": imageSR,
        "size": size,
        "dpi": dpi,
        "format": format,
        "transparent": transparent,
        "f": f,
    }
    cache_path = _cache_dir() / f"{_cache_key(params)}.png"
    max_age = TILE_CACHE_TTL_HOURS * 3600

    if cache_path.exists() and _is_fresh(cache_path):
        return Response(
            content=cache_path.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": f"public, max-age={max_age}", "X-Tile-Cache": "hit"},
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(ARCGIS_EXPORT_URL, params=params)
            resp.raise_for_status()
        content = resp.content
    except httpx.HTTPError as exc:
        # Layanan pemerintah bisa lambat/down -- kalau ada cache BASI, itu
        # jauh lebih baik ditampilkan ke user daripada ubin kosong/error.
        logger.warning("Gagal ambil ubin kawasan hutan dari ArcGIS: %s", exc)
        if cache_path.exists():
            return Response(
                content=cache_path.read_bytes(),
                media_type="image/png",
                headers={"Cache-Control": "no-cache", "X-Tile-Cache": "stale"},
            )
        raise HTTPException(status_code=502, detail="Gagal mengambil ubin fungsi kawasan hutan") from exc

    try:
        cache_path.write_bytes(content)
    except OSError:
        logger.warning("Gagal menulis cache ubin kawasan hutan ke disk (jalan tanpa cache)")

    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": f"public, max-age={max_age}", "X-Tile-Cache": "miss"},
    )
