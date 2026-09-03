import json

from fastapi import APIRouter, Depends, HTTPException
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
