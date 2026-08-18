"""Background scheduler untuk auto-refresh luas kebakaran (burned area).

Beda dari scheduler hotspot (`scheduler.py`, tiap beberapa jam): produk
MODIS/VIIRS burned area terbit BULANAN dengan lag rilis 1-3 bulan, jadi
mengecek tiap hari sia-sia. Job ini jalan mingguan (default, lihat
`burned_area_scheduler_interval_hours`) dan tiap kali mencoba ulang N bulan
terakhir (`burned_area_scheduler_lookback_months`, default 3) supaya begitu
NASA merilis citra baru, sistem otomatis menangkapnya tanpa perlu tahu
persis tanggal rilisnya. `refresh_burned_area()` di baliknya idempotent
(upsert per polygon/tahun/bulan) sehingga mengulang bulan yang sudah
terhitung aman, cuma menimpa dengan angka yang sama.

`BurnedAreaService.refresh_burned_area()` sendiri sinkron dan bisa makan
waktu lama (network round-trip ke Earth Engine, ratusan detik untuk cakupan
nasional) -- dijalankan lewat `asyncio.to_thread` supaya tidak membekukan
seluruh API selama itu.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.services.burned_area_service import BurnedAreaService

logger = logging.getLogger("burned_area.scheduler")

_last_run_result: dict = {}
_last_run_at: datetime | None = None
_last_successful_run_at: datetime | None = None
_consecutive_failures: int = 0
_next_scheduled_run_at: datetime | None = None
_bootstrapped: bool = False


def _lookback_periods(now: datetime, months: int) -> list[tuple[int, int]]:
    """N bulan sebelum bulan berjalan, dari yang paling baru ke paling lama."""
    periods: list[tuple[int, int]] = []
    year, month = now.year, now.month
    for _ in range(max(0, months)):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        periods.append((year, month))
    return periods


def bootstrap_burned_area_scheduler_metrics(service: BurnedAreaService) -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    if not service.postgres_store.enabled:
        return
    try:
        state = service.postgres_store.read_burned_area_scheduler_state()
        if state:
            global _last_run_result, _last_run_at, _last_successful_run_at, _consecutive_failures
            _last_run_result = state.get("last_run_result") or {}
            _last_run_at = state.get("last_run_at")
            _last_successful_run_at = state.get("last_successful_run_at")
            _consecutive_failures = state.get("consecutive_failures") or 0
            logger.info(
                "BURNED_AREA_SCHEDULER: Berhasil memuat state dari database. "
                "Run sukses terakhir: %s, gagal berturut-turut: %d",
                _last_successful_run_at,
                _consecutive_failures,
            )
    except Exception as exc:
        logger.error("BURNED_AREA_SCHEDULER: Gagal memuat state dari database — %s", exc)


def _record_run_result(result: dict, service: BurnedAreaService) -> None:
    global _last_run_result, _last_run_at, _last_successful_run_at, _consecutive_failures
    _last_run_result = result
    _last_run_at = datetime.now(timezone.utc)
    if result.get("success"):
        _last_successful_run_at = _last_run_at
        _consecutive_failures = 0
    elif not result.get("skipped"):
        _consecutive_failures += 1

    if not service.postgres_store.enabled:
        return
    try:
        service.postgres_store.save_burned_area_scheduler_state(
            last_run_at=_last_run_at,
            last_successful_run_at=_last_successful_run_at,
            last_run_result=_last_run_result,
            consecutive_failures=_consecutive_failures,
        )
    except Exception as exc:
        logger.error("BURNED_AREA_SCHEDULER: Gagal menyimpan status ke DB — %s", exc)


async def run_burned_area_cycle(service: BurnedAreaService, lookback_months: int) -> dict[str, object]:
    """Satu siklus: coba refresh N bulan terakhir.

    Gagal di satu bulan (mis. error jaringan sesaat ke Earth Engine) tidak
    menggagalkan bulan lain -- tiap bulan independen, supaya satu kegagalan
    transient tidak menunda bulan lain yang mungkin sebenarnya berhasil.
    """
    if not service.enabled:
        result: dict[str, object] = {"success": False, "skipped": True, "reason": "gee_not_configured"}
        _record_run_result(result, service)
        return result

    now = datetime.now(timezone.utc)
    per_month: list[dict[str, object]] = []
    for year, month in _lookback_periods(now, lookback_months):
        try:
            outcome = await asyncio.to_thread(service.refresh_burned_area, year, month)
            per_month.append({"year": year, "month": month, **outcome})
            logger.info("BURNED_AREA_SCHEDULER: %04d-%02d — %s", year, month, outcome)
        except Exception as exc:
            per_month.append({"year": year, "month": month, "computed": 0, "error": str(exc)})
            logger.error("BURNED_AREA_SCHEDULER: %04d-%02d gagal — %s", year, month, exc, exc_info=True)

    success = all("error" not in entry for entry in per_month)
    result = {"success": success, "months": per_month, "checked_at": now.isoformat()}
    _record_run_result(result, service)
    return result


def get_burned_area_scheduler_metrics_snapshot() -> dict[str, object]:
    settings = get_settings()
    try:
        bootstrap_burned_area_scheduler_metrics(BurnedAreaService())
    except Exception:
        pass

    now = datetime.now(timezone.utc)
    status = "never"
    if _last_run_result.get("skipped"):
        status = "skipped"
    elif _last_run_result.get("success") is True:
        status = "success"
    elif _last_run_result.get("success") is False:
        status = "failure"

    return {
        "current_time_utc": now.isoformat(),
        "last_run_at": _last_run_at.isoformat() if _last_run_at else None,
        "last_successful_run_at": _last_successful_run_at.isoformat() if _last_successful_run_at else None,
        "last_run_status": status,
        "last_run_result": _last_run_result,
        "consecutive_failures": _consecutive_failures,
        "next_scheduled_run_at": _next_scheduled_run_at.isoformat() if _next_scheduled_run_at else None,
        "interval_hours": settings.burned_area_scheduler_interval_hours,
        "lookback_months": settings.burned_area_scheduler_lookback_months,
    }


async def burned_area_scheduler_loop(interval_hours: float, lookback_months: int) -> None:
    """Loop scheduler yang berjalan selamanya di background."""
    service = BurnedAreaService()
    try:
        bootstrap_burned_area_scheduler_metrics(service)
    except Exception:
        pass

    if not service.enabled:
        logger.info(
            "BURNED_AREA_SCHEDULER: GEE belum dikonfigurasi, scheduler burned-area tidak dijalankan."
        )
        return

    logger.info(
        "BURNED_AREA_SCHEDULER: Dimulai — interval %.1f jam, lookback %d bulan.",
        interval_hours,
        lookback_months,
    )

    global _next_scheduled_run_at
    interval = timedelta(hours=interval_hours)

    if _last_successful_run_at is not None:
        elapsed = datetime.now(timezone.utc) - _last_successful_run_at
        if elapsed < interval * 0.8:
            wait_for = interval - elapsed
            _next_scheduled_run_at = datetime.now(timezone.utc) + wait_for
            logger.info(
                "BURNED_AREA_SCHEDULER: Melewati run langsung, run terakhir sukses %s lalu. "
                "Run berikutnya pada %s.",
                elapsed,
                _next_scheduled_run_at.strftime("%Y-%m-%d %H:%M UTC"),
            )
            await asyncio.sleep(wait_for.total_seconds())

    while True:
        result = await run_burned_area_cycle(service, lookback_months)
        _next_scheduled_run_at = datetime.now(timezone.utc) + interval
        logger.info(
            "BURNED_AREA_SCHEDULER: Siklus selesai (%s) — run berikutnya pada %s.",
            "sukses" if result.get("success") else "gagal",
            _next_scheduled_run_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        await asyncio.sleep(interval.total_seconds())
