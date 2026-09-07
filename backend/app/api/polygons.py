import json
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.core.auth import TokenClaims, get_current_user_claims, require_admin_role
from app.services.polygon_service import get_polygon_service


router = APIRouter()

# Toleransi ST_SimplifyPreserveTopology (derajat) untuk geometry detail KPS.
# Admin dapat versi ~11m (perilaku lama); non-admin dapat versi ~110m -- cukup
# untuk menggambar outline di peta, tapi terlalu kasar untuk dipanen jadi
# batas cadastral. Ekspor mentah cuma lewat endpoint /export.geojson (admin).
_ADMIN_DETAIL_TOLERANCE = 0.0001
_PUBLIC_DETAIL_TOLERANCE = 0.001


def _is_admin(claims: TokenClaims | None) -> bool:
    return claims is not None and claims.role == "admin"


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


@router.get("/polygons/{polygon_metadata_id}/export.geojson")
async def export_polygon_geojson(
    polygon_metadata_id: int,
    _claims: TokenClaims = Depends(require_admin_role),
) -> Response:
    """Unduh satu polygon KPS/Hutan Adat sebagai berkas GeoJSON presisi penuh.
    Khusus admin -- inilah satu-satunya jalur yang mengeluarkan geometry mentah.
    """
    service = get_polygon_service()
    detail = service.get_polygon_detail(polygon_metadata_id, tolerance=None)
    if detail is None:
        raise HTTPException(status_code=404, detail="Polygon not found")

    data = detail.model_dump()
    geometry = data.pop("geometry")
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": data, "geometry": geometry}
        ],
    }
    filename = f"kps-{polygon_metadata_id}.geojson"
    return Response(
        content=json.dumps(feature_collection, ensure_ascii=False),
        media_type="application/geo+json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/polygons/by-agency")
async def get_polygon_by_agency(
    agency: str,
    claims: TokenClaims | None = Depends(get_current_user_claims),
) -> dict[str, object]:
    """Cari satu polygon KPS/Hutan Adat berdasarkan nama LEMBAGA/agency.
    Dipakai Detail KPS saat KPS terpilih tidak memiliki hotspot pada rentang waktu
    aktif sehingga ID-nya tidak bisa disimpulkan dari titik hotspot."""
    tolerance = (
        _ADMIN_DETAIL_TOLERANCE if _is_admin(claims) else _PUBLIC_DETAIL_TOLERANCE
    )
    service = get_polygon_service()
    detail = service.get_polygon_detail_by_agency(agency, tolerance=tolerance)
    if detail is None:
        raise HTTPException(status_code=404, detail="Polygon not found for this agency")
    return detail.model_dump()


@router.get("/polygons/{polygon_metadata_id}")
async def get_polygon(
    polygon_metadata_id: int,
    claims: TokenClaims | None = Depends(get_current_user_claims),
) -> dict[str, object]:
    tolerance = (
        _ADMIN_DETAIL_TOLERANCE if _is_admin(claims) else _PUBLIC_DETAIL_TOLERANCE
    )
    service = get_polygon_service()
    detail = service.get_polygon_detail(polygon_metadata_id, tolerance=tolerance)
    if detail is None:
        raise HTTPException(status_code=404, detail="Polygon not found")
    return detail.model_dump()


@router.get("/polygons/{polygon_metadata_id}/surrounding-hotspots")
async def get_polygon_surrounding_hotspots(
    polygon_metadata_id: int,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    buffer_km: float = Query(default=5.0, ge=0.5, le=25.0),
    satellites: list[str] = Query(default=[]),
    _claims: TokenClaims | None = Depends(get_current_user_claims),
) -> dict[str, object]:
    """Ambil sebaran hotspot di dalam dan di zona penyangga luar (buffer) poligon KPS.
    Dipakai oleh Detail KPS dan animasi timeline agar pergerakan api dari luar terpantau utuh.
    """
    resolved_start = _resolve_start_at(start_at, start_date)
    resolved_end = _resolve_end_at(end_at, end_date)
    service = get_polygon_service()
    return service.get_surrounding_hotspots(
        polygon_id=polygon_metadata_id,
        buffer_km=buffer_km,
        start_at=resolved_start,
        end_at=resolved_end,
        satellites=satellites or None,
    )

