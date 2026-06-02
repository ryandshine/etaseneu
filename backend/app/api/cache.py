import asyncio
import os
import shutil
from fastapi import APIRouter, Query, UploadFile, File, HTTPException

from app.services.hotspot_service import HotspotService


router = APIRouter()


@router.post("/cache/refresh")
async def refresh_cache() -> dict[str, str]:
    return {"status": "queued"}


@router.get("/geojson/status")
async def geojson_status() -> dict[str, object]:
    service = HotspotService()
    return service.geojson_status()


@router.post("/geojson/refresh")
async def geojson_refresh() -> dict[str, object]:
    service = HotspotService()
    summary = service.refresh_geojson()
    service.layer_service.clear_caches()
    return summary


@router.post("/geojson/upload")
async def upload_geojson(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.filename.endswith(".geojson"):
        raise HTTPException(status_code=400, detail="Hanya file dengan ekstensi .geojson yang diperbolehkan.")

    service = HotspotService()
    shp_dir = service.layer_service.shp_dir

    # 1. Clean up old geojson files in shp_dir
    try:
        for old_file in shp_dir.glob("*.geojson"):
            file_name = old_file.name
            try:
                service.layer_service.geojson_sync_service.postgres_store.deactivate_geojson_file_registry(file_name)
            except Exception:
                pass
            os.remove(old_file)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membersihkan file geojson lama: {str(e)}")

    # 2. Write new file in chunks
    target_path = shp_dir / file.filename
    try:
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        if os.path.exists(target_path):
            os.remove(target_path)
        raise HTTPException(status_code=500, detail=f"Gagal menyimpan file geojson baru: {str(e)}")
    finally:
        file.file.close()

    # 3. Clear caches
    service.layer_service.clear_caches()

    # 4. Trigger sync
    try:
        summary = service.refresh_geojson()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal melakukan sinkronisasi geojson: {str(e)}")

    return {
        "status": "success",
        "file_name": file.filename,
        "summary": summary
    }


@router.post("/polygon-hotspot-summary/refresh")
async def polygon_hotspot_summary_refresh() -> dict[str, int]:
    service = HotspotService()
    return service.refresh_polygon_hotspot_summaries()


@router.get("/cache/history/status")
async def cache_history_status(
    year: int = Query(default=2026, ge=2000, le=2100),
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
) -> dict[str, object]:
    service = HotspotService()
    return service.history_status(
        year=year,
        satellites=satellites,
        layer_ids=active_layers,
    )


@router.post("/cache/history/prewarm")
async def cache_history_prewarm(
    year: int = Query(default=2026, ge=2000, le=2100),
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
) -> dict[str, object]:
    service = HotspotService()
    return await asyncio.shield(
        service.prewarm_year_history(
            year=year,
            satellites=satellites or None,
            layer_ids=active_layers or None,
        )
    )


@router.get("/storage/status")
async def storage_status() -> dict[str, object]:
    service = HotspotService()
    return service.storage_status()
