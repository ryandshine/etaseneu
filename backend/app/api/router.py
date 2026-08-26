from fastapi import APIRouter, Depends

from app.core.auth import require_session_if_enabled
from app.api.auth import router as auth_router
from app.api.burned_area import router as burned_area_router
from app.api.cache import router as cache_router
from app.api.export import router as export_router
from app.api.hotspot_clusters import router as hotspot_clusters_router
from app.api.hotspots import router as hotspots_router
from app.api.layers import router as layers_router
from app.api.metrics import router as metrics_router
from app.api.point_match import router as point_match_router
from app.api.polygons import router as polygons_router
from app.api.scheduler import router as scheduler_router
from app.api.stats import router as stats_router
from app.api.wind import router as wind_router
from app.api.weather import router as weather_router


# Gate baca opsional (flag API_REQUIRE_AUTH). Dipasang di router BACA saja.
# TIDAK dipasang di: auth (harus bisa pra-sesi), cache & scheduler (sudah
# require_admin_key -- menumpuk akan memutus automation X-Admin-Key-only),
# metrics (Prometheus scrape). scheduler punya GET baca yang dilindungi
# per-route di app/api/scheduler.py.
_read_gate = [Depends(require_session_if_enabled)]

router = APIRouter()
router.include_router(auth_router)
router.include_router(layers_router, dependencies=_read_gate)
router.include_router(polygons_router, dependencies=_read_gate)
router.include_router(point_match_router, dependencies=_read_gate)
router.include_router(hotspots_router, dependencies=_read_gate)
router.include_router(hotspot_clusters_router, dependencies=_read_gate)
router.include_router(stats_router, dependencies=_read_gate)
router.include_router(export_router, dependencies=_read_gate)
router.include_router(cache_router)
router.include_router(scheduler_router)
router.include_router(metrics_router)
router.include_router(wind_router, dependencies=_read_gate)
router.include_router(weather_router, dependencies=_read_gate)
router.include_router(burned_area_router, dependencies=_read_gate)
api_router = router


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
