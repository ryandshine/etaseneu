import asyncio
from fastapi import APIRouter, Query

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
    service.layer_service._layers_cache = None
    service.layer_service._spatial_layers_cache = None
    return summary


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
