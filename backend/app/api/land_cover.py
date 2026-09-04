"""Menu Tutupan Lahan per KPS: analisis on-demand Sentinel-2 + Random Forest
(2021-2025), hasil di-cache permanen. Analisis butuh env GEE; membaca hasil
tidak.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query

from app.core.config import get_settings
from app.services.land_cover_service import (
    CLASS_KEYS,
    YEARS,
    LandCoverService,
    _build_summary_text,
    _net_change,
    land_cover_any_running,
    land_cover_run_state,
)
from app.services.postgres_store import PostgresStore

router = APIRouter()


def _store() -> PostgresStore:
    return PostgresStore(get_settings().database_url)


@router.post("/land-cover/analyze", status_code=202)
async def land_cover_analyze(
    background_tasks: BackgroundTasks,
    polygon_id: int = Body(..., embed=True),
    force: bool = Query(default=False),
) -> dict[str, object]:
    service = LandCoverService()
    if not service.enabled:
        raise HTTPException(status_code=503, detail="GEE belum dikonfigurasi di server")

    # Lock GLOBAL, TIDAK ikut ditimpa force -- force cuma untuk override state
    # basi poligon INI sendiri (lihat komentar di bawah), bukan buat motong
    # antrean saat poligon LAIN beneran sedang jalan (itu yang mau dicegah:
    # rebutan kuota GEE & CPU RF training kalau banyak user klik bersamaan).
    running_elsewhere = land_cover_any_running()
    if running_elsewhere and running_elsewhere["polygon_id"] != polygon_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ada analisis KPS/Hutan Adat lain sedang berjalan, coba lagi nanti",
                "busy_elsewhere": True,
            },
        )

    store = _store()
    status = store.read_land_cover_status(polygon_id)
    if status and status["status"] == "running" and not force:
        # force=true dipakai tombol "Analisis ulang" -- juga jadi jalan keluar
        # kalau ada baris 'running' basi (mis. container restart saat job jalan).
        raise HTTPException(status_code=409, detail="Analisis sedang berjalan")
    if status and status["status"] == "done" and not force:
        raise HTTPException(status_code=409, detail={"message": "sudah dianalisis", "done": True})

    target = store.read_land_cover_target_polygon(polygon_id)
    if not target:
        raise HTTPException(
            status_code=404,
            detail="Poligon tidak ditemukan / tidak aktif / bukan KPS maupun Hutan Adat",
        )
    store.mark_land_cover_running(polygon_id, target["layer_key"])
    background_tasks.add_task(LandCoverService().analyze_polygon, polygon_id)
    return {"started": True, "polygon_id": polygon_id}


@router.delete("/land-cover/result")
async def land_cover_delete(polygon_id: int) -> dict[str, object]:
    """Hapus hasil analisis supaya poligon kembali ke 'belum dianalisis'.
    Alur UI "hapus dulu, baru analisis lagi" (menggantikan tombol "Analisis
    ulang"/force dari state done). Ditolak kalau job poligon ini BENERAN
    sedang jalan di proses ini -- hasilnya toh akan ditulis ulang saat selesai."""
    if land_cover_run_state(polygon_id):
        raise HTTPException(status_code=409, detail="Analisis sedang berjalan, tunggu selesai dulu")
    deleted = _store().delete_land_cover_result(polygon_id)
    return {"deleted": bool(deleted), "polygon_id": polygon_id}


@router.get("/land-cover/polygons")
async def land_cover_polygons() -> list[dict[str, object]]:
    return _store().list_polygons_with_land_cover_status()


@router.get("/land-cover/status")
async def land_cover_status(polygon_id: int) -> dict[str, object]:
    row = _store().read_land_cover_status(polygon_id)
    live = land_cover_run_state(polygon_id)
    running_elsewhere = land_cover_any_running()
    return {
        "state": row["status"] if row else "idle",
        "step": live["step"] if live else None,
        "error": row["error_message"] if row else None,
        "computed_at": row["computed_at"] if row else None,
        # true kalau poligon LAIN (bukan ini) sedang dianalisis di proses ini
        # sekarang -- dipakai frontend buat nonaktifkan tombol "Jalankan
        # Analisis" sementara, biar tidak rebutan kuota GEE/CPU.
        "busy_elsewhere": bool(running_elsewhere and running_elsewhere["polygon_id"] != polygon_id),
    }


@router.get("/land-cover/result")
async def land_cover_result(polygon_id: int) -> dict[str, object]:
    res = _store().read_land_cover_result(polygon_id)
    if not res:
        raise HTTPException(status_code=404, detail="Belum ada hasil analisis")
    table: dict[int, dict[str, dict]] = {}
    for r in res["year_class"]:
        table.setdefault(r["year"], {})[r["class_key"]] = {
            "area_ha": r["area_ha"], "pct": r["pct"],
        }
    return {
        "meta": res["meta"],
        "years": list(YEARS),
        "classes": list(CLASS_KEYS),
        "table": {str(y): table.get(y, {}) for y in YEARS},
        "net_change": _net_change(table),
        "summary_text": _build_summary_text(table),
    }


@router.get("/land-cover/overlay")
async def land_cover_overlay(
    polygon_id: int,
    year: int = Query(...),
) -> dict[str, object]:
    if year not in YEARS:
        raise HTTPException(status_code=404, detail="Tahun di luar rentang 2021-2025")
    store = _store()
    status = store.read_land_cover_status(polygon_id)
    if not status or status["status"] != "done":
        raise HTTPException(status_code=404, detail="Belum ada hasil analisis")
    rows = store.read_land_cover_overlay(polygon_id, year)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": r["geometry_json"],
                "properties": {
                    "class_key": r["class_key"],
                    "area_ha": r["area_ha"],
                    "pct": r["pct"],
                },
            }
            for r in rows
            if r.get("geometry_json")
        ],
    }
