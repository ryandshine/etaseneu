"""API endpoints untuk katalog direktori data KPS nasional."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, Query, Response

from app.core.auth import TokenClaims, get_current_user_claims
from app.services.kps_catalog_service import get_kps_catalog_service

router = APIRouter(prefix="/kps-catalog", tags=["KPS Catalog"])


@router.get("")
async def get_kps_catalog_list(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=5, le=100),
    search: str | None = Query(default=None),
    wilker: str | None = Query(default=None),
    province: str | None = Query(default=None),
    regency: str | None = Query(default=None),
    skema: str | None = Query(default=None),
    has_hotspot_30d: bool | None = Query(default=None),
    has_burned_area: bool | None = Query(default=None),
    sort_by: str = Query(default="lembaga"),
    sort_dir: str = Query(default="asc"),
    _claims: TokenClaims | None = Depends(get_current_user_claims),
) -> dict[str, Any]:
    """Mengambil data katalog KPS dengan filter, pencarian, dan pagination."""
    service = get_kps_catalog_service()
    return service.get_kps_catalog(
        page=page,
        page_size=page_size,
        search=search,
        wilker=wilker,
        province=province,
        regency=regency,
        skema=skema,
        has_hotspot_30d=has_hotspot_30d,
        has_burned_area=has_burned_area,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )


@router.get("/meta")
async def get_kps_catalog_meta(
    refresh: bool = Query(default=False),
    _claims: TokenClaims | None = Depends(get_current_user_claims),
) -> dict[str, Any]:
    """Mengambil KPI ringkasan nasional dan opsi filter berjenjang (dicache)."""
    service = get_kps_catalog_service()
    return service.get_catalog_meta(force_refresh=refresh)


@router.get("/export")
async def export_kps_catalog(
    search: str | None = Query(default=None),
    wilker: str | None = Query(default=None),
    province: str | None = Query(default=None),
    regency: str | None = Query(default=None),
    skema: str | None = Query(default=None),
    has_hotspot_30d: bool | None = Query(default=None),
    has_burned_area: bool | None = Query(default=None),
    _claims: TokenClaims | None = Depends(get_current_user_claims),
) -> Response:
    """Unduh data katalog KPS terfilter ke berkas CSV."""
    service = get_kps_catalog_service()
    csv_content = service.export_kps_catalog_csv(
        search=search,
        wilker=wilker,
        province=province,
        regency=regency,
        skema=skema,
        has_hotspot_30d=has_hotspot_30d,
        has_burned_area=has_burned_area,
    )
    filename = "data_kps_nasional.csv"
    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
