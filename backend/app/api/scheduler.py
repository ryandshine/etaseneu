"""
Endpoint untuk monitoring dan kontrol scheduler auto-sync hotspot.

GET  /api/scheduler/status  — status scheduler & konfigurasi
POST /api/scheduler/sync    — trigger manual sync sekarang
"""

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends

from app.core.auth import require_admin_key, require_session_if_enabled
from app.core.config import get_settings
from app.services import scheduler as scheduler_service
from app.services import burned_area_scheduler as burned_area_scheduler_service
from app.services.burned_area_service import BurnedAreaService
from app.services.hotspot_service import HotspotService

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status(_: object = Depends(require_session_if_enabled)) -> dict:
    """Status scheduler dan hasil sync terakhir."""
    settings = get_settings()
    metrics = scheduler_service.get_scheduler_metrics_snapshot()
    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "interval_hours": settings.scheduler_interval_hours,
        "schedule_hours": metrics["schedule_hours"],
        "schedule_label": metrics["schedule_label"],
        "schedule_timezone": metrics["schedule_timezone"],
        "nasa_api_configured": bool(settings.nasa_firms_api_key),
        "last_sync_at": metrics["last_sync_at"],
        "last_sync_result": scheduler_service._last_sync_result,
        "current_time_utc": metrics["current_time_utc"],
    }


@router.get("/metrics")
async def scheduler_metrics(_: object = Depends(require_session_if_enabled)) -> dict[str, object]:
    settings = get_settings()
    metrics = scheduler_service.get_scheduler_metrics_snapshot()
    return {
        "scheduler_enabled": settings.scheduler_enabled,
        "interval_hours": settings.scheduler_interval_hours,
        "schedule_hours": metrics["schedule_hours"],
        "schedule_label": metrics["schedule_label"],
        "schedule_timezone": metrics["schedule_timezone"],
        "nasa_api_configured": bool(settings.nasa_firms_api_key),
        **metrics,
    }


@router.post("/sync")
async def trigger_manual_sync(_: None = Depends(require_admin_key)) -> dict:
    """Trigger sync manual sekarang secara sinkron."""
    settings = get_settings()

    if not settings.nasa_firms_api_key:
        return {
            "triggered": False,
            "success": False,
            "reason": "NASA FIRMS API key belum dikonfigurasi di .env",
        }

    service = HotspotService()
    result = await scheduler_service._run_sync_cycle(service)

    # Recalculate next scheduled run time
    now = datetime.now(timezone.utc)
    schedule_hours = scheduler_service._parse_fixed_hours(settings.scheduler_fixed_hours)
    schedule_timezone = scheduler_service._resolve_schedule_timezone(settings.scheduler_timezone)
    next_run = scheduler_service._next_fixed_schedule_at(
        now,
        schedule_hours,
        schedule_timezone,
        settings.scheduler_interval_hours,
    )
    scheduler_service._next_scheduled_sync_at = next_run

    return {
        "triggered": True,
        "success": result.get("success", False),
        "hotspot_count": result.get("hotspot_count", 0),
        "new_hotspot_count": result.get("new_hotspot_count", 0),
        "message": "Sync hotspot selesai secara manual.",
    }


@router.get("/burned-area/status")
async def burned_area_scheduler_status(
    _: object = Depends(require_session_if_enabled),
) -> dict:
    """Status auto-refresh burned area (MCD64A1 + fallback VNP64A1)."""
    settings = get_settings()
    metrics = burned_area_scheduler_service.get_burned_area_scheduler_metrics_snapshot()
    return {
        "scheduler_enabled": settings.burned_area_scheduler_enabled,
        "gee_configured": BurnedAreaService().enabled,
        **metrics,
    }


@router.post("/burned-area/sync")
async def trigger_burned_area_sync(_: None = Depends(require_admin_key)) -> dict:
    """Trigger manual siklus auto-refresh burned area (lookback N bulan) sekarang."""
    settings = get_settings()
    service = BurnedAreaService()
    result = await burned_area_scheduler_service.run_burned_area_cycle(
        service, settings.burned_area_scheduler_lookback_months
    )
    return {"triggered": True, **result}
