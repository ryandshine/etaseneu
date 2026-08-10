from fastapi import APIRouter, HTTPException

from app.services.polygon_service import get_polygon_service


router = APIRouter()


@router.get("/polygons/{polygon_metadata_id}")
async def get_polygon(polygon_metadata_id: int) -> dict[str, object]:
    service = get_polygon_service()
    detail = service.get_polygon_detail(polygon_metadata_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Polygon not found")
    return detail.model_dump()
