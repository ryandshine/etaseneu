import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.services import scheduler as scheduler_service
from app.services.scheduler import hotspot_scheduler_loop
from app.services.burned_area_scheduler import burned_area_scheduler_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hotspot.main")


def _defer_scheduler_start(
    *,
    schedule_hours: list[int],
    fallback_interval_hours: float,
) -> tuple[asyncio.Handle, dict[str, asyncio.Task | None]]:
    loop = asyncio.get_running_loop()
    holder: dict[str, asyncio.Task | None] = {"task": None}

    def _start_scheduler() -> None:
        holder["task"] = asyncio.create_task(
            hotspot_scheduler_loop(
                schedule_hours=schedule_hours,
                fallback_interval_hours=fallback_interval_hours,
            )
        )

    handle = loop.call_later(1.0, _start_scheduler)
    return handle, holder


def _defer_burned_area_scheduler_start(
    *,
    interval_hours: float,
    lookback_months: int,
) -> tuple[asyncio.Handle, dict[str, asyncio.Task | None]]:
    loop = asyncio.get_running_loop()
    holder: dict[str, asyncio.Task | None] = {"task": None}

    def _start_scheduler() -> None:
        holder["task"] = asyncio.create_task(
            burned_area_scheduler_loop(
                interval_hours=interval_hours,
                lookback_months=lookback_months,
            )
        )

    # Mulai 2 detik setelah startup, setelah scheduler hotspot (1 detik) --
    # supaya tidak berebut start-up cost di detik pertama yang sama.
    handle = loop.call_later(2.0, _start_scheduler)
    return handle, holder


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Job tutupan lahan berjalan di BackgroundTasks proses ini; baris
    # 'running' yang tertinggal dari proses sebelumnya tidak akan pernah
    # selesai -> tandai error supaya UI tidak terkunci. Dibungkus try:
    # kegagalan DB saat boot tidak boleh menjatuhkan seluruh API.
    try:
        from app.services.postgres_store import PostgresStore

        store = PostgresStore(settings.database_url)
        if store.enabled:
            n = store.reset_stale_land_cover_running()
            if n:
                logger.warning("LAND_COVER: %s analisis 'running' basi ditandai error saat startup", n)
    except Exception:  # noqa: BLE001
        logger.exception("LAND_COVER: gagal mereset status running basi saat startup")

    scheduler_task = None
    scheduler_start_handle = None
    scheduler_task_holder: dict[str, asyncio.Task | None] | None = None
    if settings.scheduler_enabled:
        scheduler_hours = scheduler_service._parse_fixed_hours(settings.scheduler_fixed_hours)
        scheduler_timezone = scheduler_service._resolve_schedule_timezone(settings.scheduler_timezone)
        logger.info(
            "AUTO-SYNC: Scheduler aktif — jadwal harian %s.",
            scheduler_service._describe_schedule_hours(scheduler_hours, scheduler_timezone)
            if scheduler_hours
            else f"fallback interval {settings.scheduler_interval_hours:.1f} jam",
        )
        scheduler_start_handle, scheduler_task_holder = _defer_scheduler_start(
            schedule_hours=scheduler_hours,
            fallback_interval_hours=settings.scheduler_interval_hours,
        )
    else:
        logger.info("AUTO-SYNC: Scheduler dinonaktifkan (SCHEDULER_ENABLED=false).")

    burned_area_task = None
    burned_area_start_handle = None
    burned_area_task_holder: dict[str, asyncio.Task | None] | None = None
    if settings.burned_area_scheduler_enabled:
        logger.info(
            "BURNED_AREA_SCHEDULER: Auto-refresh aktif — interval %.1f jam, lookback %d bulan "
            "(nonaktif otomatis kalau GEE belum dikonfigurasi).",
            settings.burned_area_scheduler_interval_hours,
            settings.burned_area_scheduler_lookback_months,
        )
        burned_area_start_handle, burned_area_task_holder = _defer_burned_area_scheduler_start(
            interval_hours=settings.burned_area_scheduler_interval_hours,
            lookback_months=settings.burned_area_scheduler_lookback_months,
        )
    else:
        logger.info(
            "BURNED_AREA_SCHEDULER: Dinonaktifkan (BURNED_AREA_SCHEDULER_ENABLED=false)."
        )

    yield  # aplikasi berjalan di sini

    if scheduler_start_handle is not None and scheduler_task_holder is not None:
        scheduler_task = scheduler_task_holder["task"]
        if scheduler_task is None:
            scheduler_start_handle.cancel()

    if scheduler_task is not None:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        logger.info("AUTO-SYNC: Scheduler dihentikan.")

    if burned_area_start_handle is not None and burned_area_task_holder is not None:
        burned_area_task = burned_area_task_holder["task"]
        if burned_area_task is None:
            burned_area_start_handle.cancel()

    if burned_area_task is not None:
        burned_area_task.cancel()
        try:
            await burned_area_task
        except asyncio.CancelledError:
            pass
        logger.info("BURNED_AREA_SCHEDULER: Dihentikan.")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "Accept"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)

    return app


app = create_app()
