from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.models.query import HotspotQuery
from app.services.export_service import build_excel_file
from app.services.hotspot_service import HotspotService


router = APIRouter()


def _get_frp_category(hotspot: dict) -> str:
    frp = hotspot.get("frp")
    try:
        val = float(frp) if frp is not None else 0.0
    except ValueError:
        val = 0.0
        
    if val > 30:
        return "Tinggi"
    elif val >= 10:
        return "Sedang"
    else:
        return "Rendah"


@router.get("/export.xlsx")
async def export_hotspots(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
    province: str | None = None,
    wilker: str | None = None,
    confidence: str | None = None,
    agency: str | None = None,
) -> Response:
    service = HotspotService()
    result = await service.fetch_filtered_hotspots(
        HotspotQuery(
            start_at=_resolve_start_at(start_at, start_date),
            end_at=_resolve_end_at(end_at, end_date),
            satellites=satellites,
            active_layers=active_layers,
        )
    )
    hotspots = result["hotspots"]
    if province:
        hotspots = [h for h in hotspots if h.get("province_name") == province]
    if wilker:
        hotspots = [
            h for h in hotspots 
            if h.get("polygon_metadata", {}).get("WILKER_BPS") == wilker
        ]
    if confidence:
        hotspots = [h for h in hotspots if _get_frp_category(h) == confidence]
    if agency:
        hotspots = [h for h in hotspots if h.get("agency_name") == agency]

    return Response(
        content=build_excel_file(hotspots),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=eta-seuneu-hotspots.xlsx"},
    )


@router.get("/export.pdf")
async def export_hotspots_pdf(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
    province: str | None = None,
    wilker: str | None = None,
    confidence: str | None = None,
    agency: str | None = None,
) -> Response:
    service = HotspotService()
    query = HotspotQuery(
        start_at=_resolve_start_at(start_at, start_date),
        end_at=_resolve_end_at(end_at, end_date),
        satellites=satellites,
        active_layers=active_layers,
    )
    result = await service.fetch_filtered_hotspots(query)
    
    hotspots = result["hotspots"]
    if province:
        hotspots = [h for h in hotspots if h.get("province_name") == province]
    if wilker:
        hotspots = [
            h for h in hotspots 
            if h.get("polygon_metadata", {}).get("WILKER_BPS") == wilker
        ]
    if confidence:
        hotspots = [h for h in hotspots if _get_frp_category(h) == confidence]
    if agency:
        hotspots = [
            h for h in hotspots
            if (h.get("layer_name") or h.get("agency_name") or "") == agency
        ]

    layers_info = service.layer_service.spatial_layers_for_ids(active_layers)

    filename = (
        f"eta-seuneu-laporan-{agency.lower().replace(' ', '-')}.pdf"
        if agency
        else "eta-seuneu-hotspots-report.pdf"
    )

    if agency:
        from app.services.agency_pdf_service import build_agency_pdf_weasyprint
        pdf_content = build_agency_pdf_weasyprint(
            hotspots=hotspots,
            query=query,
            agency_name=agency,
        )
    else:
        from app.services.pdf_export_service import build_pdf_report
        pdf_content = build_pdf_report(
            hotspots=hotspots,
            query=query,
            layers_info=layers_info,
        )

    return Response(
        content=pdf_content,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


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
