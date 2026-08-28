"""Router API untuk Analisis Peringatan Dini & Rekapitulasi Kebakaran KPS."""

from datetime import datetime
from fastapi import APIRouter, Query, Response

from app.services.early_warning_service import EarlyWarningService

router = APIRouter()


@router.get("/early-warning/summary")
async def get_early_warning_summary(
    wilker_bps: str | None = Query(default=None),
) -> dict:
    """Ambil ringkasan metrik statistik makro kebakaran KPS."""
    service = EarlyWarningService()
    return service.get_summary_metrics(wilker_bps=wilker_bps)


@router.get("/early-warning/list")
async def get_early_warning_list(
    category: str = Query(default="burned_active_today"),
    province: str | None = None,
    skema: str | None = None,
    wilker_bps: str | None = None,
    search: str | None = None,
    limit: int = Query(default=1000, le=2000),
) -> dict:
    """Ambil daftar KPS berdasarkan kategori analisis."""
    service = EarlyWarningService()
    items = service.get_kps_analysis_list(
        category=category,
        province=province,
        skema=skema,
        wilker_bps=wilker_bps,
        search=search,
        limit=limit,
    )
    return {
        "category": category,
        "wilker_bps": wilker_bps,
        "total_items": len(items),
        "items": items,
    }


@router.get("/early-warning/export.xlsx")
async def export_early_warning_excel(
    category: str = Query(default="all"),
    wilker_bps: str | None = Query(default=None),
) -> Response:
    """Ekspor data analisis KPS langsung ke file Excel."""
    service = EarlyWarningService()
    content = service.build_excel_export(category=category, wilker_bps=wilker_bps)
    wilker_suffix = f"-{wilker_bps.replace(' ', '_')}" if wilker_bps else ""
    filename = f"rekap-early-warning-{category}{wilker_suffix}-{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
