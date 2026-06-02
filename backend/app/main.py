import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.services import scheduler as scheduler_service
from app.services.scheduler import hotspot_scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hotspot.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    scheduler_task = None
    if settings.scheduler_enabled:
        scheduler_hours = scheduler_service._parse_fixed_hours(settings.scheduler_fixed_hours)
        scheduler_timezone = scheduler_service._resolve_schedule_timezone(settings.scheduler_timezone)
        logger.info(
            "AUTO-SYNC: Scheduler aktif — jadwal harian %s.",
            scheduler_service._describe_schedule_hours(scheduler_hours, scheduler_timezone)
            if scheduler_hours
            else f"fallback interval {settings.scheduler_interval_hours:.1f} jam",
        )
        scheduler_task = asyncio.create_task(
            hotspot_scheduler_loop(
                schedule_hours=scheduler_hours,
                fallback_interval_hours=settings.scheduler_interval_hours,
            )
        )
    else:
        logger.info("AUTO-SYNC: Scheduler dinonaktifkan (SCHEDULER_ENABLED=false).")

    yield  # aplikasi berjalan di sini

    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        logger.info("AUTO-SYNC: Scheduler dihentikan.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    return app


app = create_app()
