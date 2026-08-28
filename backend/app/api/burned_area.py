from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import require_admin_key
from app.services.burned_area_klhk_service import BurnedAreaKlhkError, refresh_burned_area_from_klhk_file
from app.services.burned_area_service import BurnedAreaService, BurnedAreaServiceError
from app.services.postgres_store import PostgresStore
from app.core.config import get_settings


router = APIRouter()


@router.get("/burned-area/summary")
async def burned_area_summary(
    year: int | None = None,
    month: int | None = None,
    layer_ids: list[str] = Query(default=[]),
    # Halaman detail KPS cuma butuh satu polygon. Tanpa filter ini pemanggil
    # terpaksa mengunduh SELURUH tabel lalu menyaring di klien -- pada cakupan
    # penuh (7313 polygon x 12 bulan) itu ~16 MB per kali buka halaman.
    polygon_ids: list[int] = Query(default=[]),
) -> dict[str, object]:
    store = PostgresStore(get_settings().database_url)
    rows = store.read_burned_area_summary(
        polygon_ids=polygon_ids or None,
        layer_keys=layer_ids or None,
        year=year,
        month=month,
    )
    latest = store.latest_burned_area_period()
    # `total_ha` menjumlahkan angka bulanan, jadi lahan yang terbakar lebih
    # dari sekali ikut terhitung berulang. `unique_ha` menggabungkan jejaknya
    # (ST_Union) sehingga tumpang tindih dihitung sekali -- ini yang layak
    # disebut "luas lahan terbakar". Keduanya dikirim supaya pemakai bisa
    # membedakan akumulasi kejadian dari luas area sesungguhnya.
    unique_ha = store.burned_area_unique_ha(polygon_ids) if polygon_ids else None
    return {
        "rows": rows,
        "total_ha": sum(float(row["burned_area_ha"]) for row in rows),
        "unique_ha": unique_ha,
        "latest_period": (
            {"year": latest[0], "month": latest[1]} if latest else None
        ),
    }


@router.get("/burned-area/by-skema")
async def burned_area_by_skema(
    year: int | None = None,
    month: int | None = None,
    layer_ids: list[str] = Query(default=[]),
) -> dict[str, object]:
    """Rekap luas terbakar unik per skema perhutanan sosial (PPHD, PPHKm,
    dst) -- digabung per poligon (union geometry) dulu sebelum dijumlah per
    skema, supaya lahan yang terbakar berulang tidak dobel-hitung."""
    store = PostgresStore(get_settings().database_url)
    rows = store.burned_area_by_skema(year=year, month=month, layer_keys=layer_ids or None)
    return {
        "rows": rows,
        "total_ha": sum(row["total_ha"] for row in rows),
    }


@router.get("/burned-area/frequency")
async def burned_area_frequency() -> dict[str, object]:
    """Berapa periode (bulan) terpisah tiap KPS pernah tercatat terbakar
    resmi KLHK -- dipakai kolom "Frekuensi" di Buku Besar (Matriks Data).
    Tidak terikat filter waktu dashboard, dipanggil sekali saat halaman
    dibuka."""
    store = PostgresStore(get_settings().database_url)
    rows = store.burn_frequency_by_lembaga()
    return {"rows": rows}


@router.get("/burned-area/geometry")
async def burned_area_geometry(
    polygon_ids: list[int] = Query(default=[]),
    year: int | None = None,
    month: int | None = None,
) -> dict[str, object]:
    """Jejak area terbakar sebagai FeatureCollection, untuk lapisan peta."""
    if not polygon_ids:
        return {"type": "FeatureCollection", "features": []}

    store = PostgresStore(get_settings().database_url)
    rows = store.read_burned_area_geometries(polygon_ids, year=year, month=month)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": row["geometry_json"],
                "properties": {
                    "polygon_metadata_id": row["polygon_metadata_id"],
                    "year": row["year"],
                    "month": row["month"],
                    "burned_area_ha": row["burned_area_ha"],
                    "is_estimated": row["is_estimated"],
                },
            }
            for row in rows
        ],
    }


@router.get("/burned-area/map-overlay")
async def burned_area_map_overlay(
    year: int | None = None,
    layer_ids: list[str] = Query(default=[]),
) -> dict[str, object]:
    """Lapisan "kawasan terdampak kebakaran" untuk peta utama.

    Satu fitur per KPS (geometry bulanan sudah digabung di server) supaya
    peta menjawab "KPS mana yang terdampak" tanpa menumpuk bentuk yang sama
    berkali-kali untuk kawasan yang terbakar berulang.
    """
    store = PostgresStore(get_settings().database_url)
    rows = store.read_burned_area_map_overlay(year=year, layer_keys=layer_ids or None)

    def _period_label(raw: object) -> str | None:
        if not raw:
            return None
        value = int(raw)
        return f"{value // 100:04d}-{value % 100:02d}"

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": row["geometry_json"],
                "properties": {
                    "polygon_metadata_id": row["polygon_metadata_id"],
                    "lembaga": row["lembaga"],
                    "skema": row["skema"],
                    "nama_prov": row["nama_prov"],
                    "wilker_bps": row["wilker_bps"],
                    "burned_area_ha": float(row["burned_ha"] or 0),
                    "burned_months": int(row["burned_months"] or 0),
                    "latest_period": _period_label(row["latest_period"]),
                    "is_estimated": row["is_estimated"],
                },
            }
            for row in rows
        ],
        "total_ha": sum(float(row["burned_ha"] or 0) for row in rows),
        "kps_count": len(rows),
    }


@router.post("/burned-area/refresh")
async def burned_area_refresh(
    year: int | None = None,
    month: int | None = None,
    layer_ids: list[str] = Query(default=[]),
    _: None = Depends(require_admin_key),
) -> dict[str, object]:
    """Hitung ulang luas terbakar satu bulan. Default: bulan lalu (produk
    MCD64A1 hampir tidak pernah punya citra untuk bulan berjalan)."""
    if year is None or month is None:
        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month - 1
        if month == 0:
            year -= 1
            month = 12

    service = BurnedAreaService()
    try:
        return service.refresh_burned_area(year, month, layer_keys=layer_ids or None)
    except BurnedAreaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/burned-area/s2-overlay")
async def burned_area_s2_overlay(
    year: int | None = None,
    month: int | None = None,
) -> dict[str, object]:
    """Estimasi bekas terbakar Sentinel-2 (analisis mandiri sistem) sebagai
    FeatureCollection untuk lapisan peta. Default: bulan berjalan."""
    if year is None or month is None:
        now = datetime.now(timezone.utc)
        year, month = now.year, now.month
    store = PostgresStore(get_settings().database_url)
    return store.read_s2_burned_area_overlay(year, month)


# Catatan: analisis Sentinel-2 dijalankan manual dari skrip
# (`app.services.burned_area_s2_service.BurnedAreaS2Service.analyze_month`),
# bukan lewat endpoint admin -- hasilnya di-upsert ke `s2_burned_area` dan
# ditampilkan lewat `/burned-area/s2-overlay` di atas. Tidak ada tombol UI
# maupun scheduler; frekuensinya mengikuti terbitnya rekap KLHK.


@router.post("/burned-area/refresh-klhk")
async def burned_area_refresh_klhk(
    file_name: str,
    _: None = Depends(require_admin_key),
) -> dict[str, object]:
    """Proses file resmi KLHK "Areal Kebakaran Hutan dan Lahan" (AKURASI H/M)
    yang sudah ditaruh admin di KLHK_BURNED_AREA_DIR (lewat SFTP, bukan
    upload HTTP -- filenya bisa ratusan MB), overlay ke KPS aktif, simpan
    ke burned_area_summary. Ini jalur utama pengganti GEE.
    """
    settings = get_settings()
    # Path(file_name).name membuang komponen direktori apa pun -- sama pola
    # dengan sanitasi nama file di /api/geojson/upload -- supaya file_name
    # tidak bisa dipakai untuk keluar dari KLHK_BURNED_AREA_DIR.
    safe_path = settings.resolved_klhk_burned_area_dir / Path(file_name).name

    try:
        return refresh_burned_area_from_klhk_file(str(safe_path))
    except BurnedAreaKlhkError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
