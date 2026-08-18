from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.models.query import HotspotQuery
from app.services.burned_area_report import load_burned_area_report
from app.services.export_service import build_excel_file
from app.services.hotspot_categories import frp_category as _get_frp_category
from app.services.hotspot_service import HotspotService
from app.services.polygon_fields import skema_name


router = APIRouter()


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
    skema: str | None = None,
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
    if skema:
        hotspots = [h for h in hotspots if skema_name(h) == skema]
    if agency:
        hotspots = [h for h in hotspots if h.get("agency_name") == agency]

    # Lampiran luas terbakar mengikuti filter wilayah/skema yang sama dengan
    # laporan hotspot-nya. Filter waktu sengaja TIDAK diteruskan: burned area
    # terbit bulanan dengan jeda 1-3 bulan, jadi menyamakannya dengan rentang
    # beberapa hari terakhir akan membuat lampiran ini hampir selalu kosong.
    burned_area_report = load_burned_area_report(
        province=province, skema=skema, agency=agency
    )

    return Response(
        content=build_excel_file(hotspots, burned_area_report=burned_area_report),
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
    skema: str | None = None,
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
    if skema:
        hotspots = [h for h in hotspots if skema_name(h) == skema]
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
        from app.services.polygon_service import get_polygon_service

        # Fetch full year-to-date hotspots for Section 05 chronology.
        # Tahun diambil dari waktu berjalan -- sebelumnya 2026 ditulis tetap,
        # sehingga tahun berikutnya laporan tetap mulai dari 1 Januari 2026.
        ytd_end   = datetime.now(timezone.utc)
        ytd_start = datetime(ytd_end.year, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ytd_query = HotspotQuery(
            start_at=ytd_start,
            end_at=ytd_end,
            satellites=satellites,
            active_layers=active_layers,
        )
        ytd_result = await service.fetch_filtered_hotspots(ytd_query)
        hotspots_ytd = [
            h for h in ytd_result["hotspots"]
            if (h.get("layer_name") or h.get("agency_name") or "") == agency
        ]

        # Cari ID polygon dari hotspot MANAPUN yang sudah ke-link -- bukan
        # cuma yang pertama, supaya satu-dua titik yang belum sempat
        # ke-spatial-join tidak bikin peta kawasan hilang (pola yang sama
        # dengan KpsDetailView.tsx di frontend).
        polygon_geometry = None
        for hotspot in hotspots:
            raw_id = hotspot.get("polygon_metadata", {}).get("polygon_metadata_id")
            polygon_metadata_id = int(raw_id) if raw_id is not None else None
            if polygon_metadata_id is None:
                continue
            detail = get_polygon_service().get_polygon_detail(polygon_metadata_id)
            if detail is not None:
                polygon_geometry = detail.geometry
                break

        pdf_content = build_agency_pdf_weasyprint(
            hotspots=hotspots,
            query=query,
            agency_name=agency,
            hotspots_ytd=hotspots_ytd,
            polygon_geometry=polygon_geometry,
        )
    else:
        from app.services.pdf_export_service import build_pdf_report
        pdf_content = build_pdf_report(
            hotspots=hotspots,
            query=query,
            layers_info=layers_info,
            # Sama seperti lampiran Excel: ikut filter wilayah/skema, tapi
            # tidak ikut filter waktu (lihat komentar di export_hotspots).
            burned_area_report=load_burned_area_report(
                province=province, skema=skema, agency=agency
            ),
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
