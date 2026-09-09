"""Router API untuk Analisis Siaga Rambatan Api (Deteksi Ancaman Luar KPS)."""

from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Response

from app.services.fire_spread_service import FireSpreadService

router = APIRouter()


@router.get("/fire-spread/summary")
async def get_fire_spread_summary(
    time_window_hours: int = Query(default=48, ge=1, le=720),
    max_distance_km: float = Query(default=5.0, ge=0.5, le=20.0),
    province: str | None = None,
    regency: str | None = None,
    wilker: str | None = None,
) -> dict:
    """Ringkasan statistik jumlah KPS yang terancam api di perimeter luar."""
    service = FireSpreadService()
    return service.get_summary(
        time_window_hours=time_window_hours,
        max_distance_km=max_distance_km,
        province=province,
        regency=regency,
        wilker=wilker,
    )


@router.get("/fire-spread/threats")
async def get_fire_spread_threats(
    time_window_hours: int = Query(default=48, ge=1, le=720),
    max_distance_km: float = Query(default=5.0, ge=0.5, le=20.0),
    level: str | None = Query(default=None, pattern="^(bahaya|waspada|pantau)$"),
    province: str | None = None,
    regency: str | None = None,
    wilker: str | None = None,
    search: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Daftar KPS terancam api luar, diurutkan dari jarak terdekat ke batas poligon."""
    service = FireSpreadService()
    return service.get_threats(
        time_window_hours=time_window_hours,
        max_distance_km=max_distance_km,
        level=level,
        province=province,
        regency=regency,
        wilker=wilker,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.get("/fire-spread/detail")
async def get_fire_spread_detail(
    polygon_id: int = Query(..., ge=1),
    time_window_hours: int = Query(default=48, ge=1, le=720),
    max_distance_km: float = Query(default=5.0, ge=0.5, le=20.0),
) -> dict:
    """Detail satu KPS terancam, koordinat poligon, serta titik-titik hotspot di luar batas."""
    service = FireSpreadService()
    detail = service.get_threat_detail(
        polygon_id=polygon_id,
        time_window_hours=time_window_hours,
        max_distance_km=max_distance_km,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="KPS tidak ditemukan atau tidak aktif")
    return detail


@router.get("/fire-spread/export.xlsx")
async def export_fire_spread_excel(
    time_window_hours: int = Query(default=48, ge=1, le=720),
    max_distance_km: float = Query(default=5.0, ge=0.5, le=20.0),
    level: str | None = None,
    province: str | None = None,
    regency: str | None = None,
    wilker: str | None = None,
    search: str | None = None,
) -> Response:
    """Download laporan KPS terancam api luar dalam format Excel (.xlsx)."""
    service = FireSpreadService()
    content = service.export_threats_xlsx(
        time_window_hours=time_window_hours,
        max_distance_km=max_distance_km,
        level=level,
        province=province,
        regency=regency,
        wilker=wilker,
        search=search,
    )
    filename = f"Laporan_Siaga_Rambatan_Api_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
