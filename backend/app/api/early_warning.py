"""Router API untuk Analisis Peringatan Dini & Rekapitulasi Kebakaran KPS."""

from datetime import datetime
from fastapi import APIRouter, Query, Response

from app.services.early_warning_service import EarlyWarningService

router = APIRouter()


@router.get("/early-warning/summary")
async def get_early_warning_summary() -> dict:
    """Ambil ringkasan metrik statistik makro kebakaran KPS."""
    service = EarlyWarningService()
    return service.get_summary_metrics()


@router.get("/early-warning/list")
async def get_early_warning_list(
    category: str = Query(default="burned_active_today"),
    province: str | None = None,
    skema: str | None = None,
    search: str | None = None,
    limit: int = Query(default=1000, le=2000),
) -> dict:
    """Ambil daftar KPS berdasarkan kategori analisis."""
    service = EarlyWarningService()
    items = service.get_kps_analysis_list(
        category=category,
        province=province,
        skema=skema,
        search=search,
        limit=limit,
    )
    return {
        "category": category,
        "total_items": len(items),
        "items": items,
    }


@router.get("/early-warning/export.xlsx")
async def export_early_warning_excel(
    category: str = Query(default="all"),
) -> Response:
    """Ekspor data analisis KPS langsung ke file Excel."""
    service = EarlyWarningService()
    content = service.build_excel_export(category=category)
    filename = f"rekap-early-warning-{category}-{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
