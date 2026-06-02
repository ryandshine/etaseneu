from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query

from app.models.query import HotspotQuery
from app.services.hotspot_service import HotspotService


router = APIRouter()


@router.get("/hotspots")
async def get_hotspots(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
    view: str | None = Query(default=None),
) -> dict[str, object]:
    query = HotspotQuery(
        start_at=_resolve_start_at(start_at, start_date),
        end_at=_resolve_end_at(end_at, end_date),
        satellites=satellites,
        active_layers=active_layers,
    )
    service = HotspotService()
    result = await service.fetch_filtered_hotspots(query)

    if view == "map":
        return {
            **result,
            "hotspots": [_to_map_hotspot(hotspot) for hotspot in result.get("hotspots", [])],
        }

    return result


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


def _to_map_hotspot(hotspot: dict[str, object]) -> dict[str, object]:
    return {
        "id": hotspot.get("id"),
        "source": hotspot.get("source"),
        "satellite": hotspot.get("satellite"),
        "latitude": hotspot.get("latitude"),
        "longitude": hotspot.get("longitude"),
        "brightness": hotspot.get("brightness"),
        "frp": hotspot.get("frp"),
        "detected_at": hotspot.get("detected_at"),
        "agency_name": hotspot.get("agency_name"),
        "province_name": hotspot.get("province_name"),
    }
