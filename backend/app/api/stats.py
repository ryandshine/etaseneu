from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query

from app.models.query import HotspotQuery
from app.services.hotspot_service import HotspotService


router = APIRouter()


@router.get("/stats")
async def get_stats(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
) -> dict[str, object]:
    query = HotspotQuery(
        start_at=_resolve_start_at(start_at, start_date),
        end_at=_resolve_end_at(end_at, end_date),
        satellites=satellites,
        active_layers=active_layers,
    )
    service = HotspotService()
    result = await service.fetch_filtered_hotspots(query)
    return result["stats"]


def _resolve_start_at(start_at: datetime | None, start_date: date | None) -> datetime:
    if start_at is not None:
        return _normalize_datetime(start_at)
    if start_date is not None:
        return datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _resolve_end_at(end_at: datetime | None, end_date: date | None) -> datetime:
    if end_at is not None:
        return _normalize_datetime(end_at)
    if end_date is not None:
        return datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
