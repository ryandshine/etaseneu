from fastapi import APIRouter

from app.api.cache import router as cache_router
from app.api.export import router as export_router
from app.api.hotspots import router as hotspots_router
from app.api.layers import router as layers_router
from app.api.metrics import router as metrics_router
from app.api.scheduler import router as scheduler_router
from app.api.stats import router as stats_router
from app.api.wind import router as wind_router


router = APIRouter()
router.include_router(layers_router)
router.include_router(hotspots_router)
router.include_router(stats_router)
router.include_router(export_router)
router.include_router(cache_router)
router.include_router(scheduler_router)
router.include_router(metrics_router)
router.include_router(wind_router)
api_router = router


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
