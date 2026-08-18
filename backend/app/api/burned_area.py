from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import require_admin_key
from app.services.burned_area_service import BurnedAreaService, BurnedAreaServiceError
from app.services.postgres_store import PostgresStore
from app.core.config import get_settings


router = APIRouter()


@router.get("/burned-area/summary")
async def burned_area_summary(
    year: int | None = None,
    month: int | None = None,
    layer_ids: list[str] = Query(default=[]),
) -> dict[str, object]:
    store = PostgresStore(get_settings().database_url)
    rows = store.read_burned_area_summary(
        layer_keys=layer_ids or None, year=year, month=month
    )
    latest = store.latest_burned_area_period()
    return {
        "rows": rows,
        "total_ha": sum(float(row["burned_area_ha"]) for row in rows),
        "latest_period": (
            {"year": latest[0], "month": latest[1]} if latest else None
        ),
    }


@router.post("/burned-area/refresh")
async def burned_area_refresh(
    year: int | None = None,
    month: int | None = None,
    layer_ids: list[str] = Query(default=[]),
    _: None = Depends(require_admin_key),
) -> dict[str, object]:
    """Hitung ulang luas terbakar satu bulan. Default: bulan lalu (produk
    MCD64A1 hampir tidak pernah punya citra untuk bulan berjalan)."""
    if year is None or month is None:
        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month - 1
        if month == 0:
            year -= 1
            month = 12

    service = BurnedAreaService()
    try:
        return service.refresh_burned_area(year, month, layer_keys=layer_ids or None)
    except BurnedAreaServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
