"""
Background scheduler untuk auto-fetch hotspot dari NASA FIRMS.

Berjalan sebagai asyncio task di dalam proses FastAPI.
Default schedule: tiap hari pada jam-jam tertentu (dapat dikonfigurasi via SCHEDULER_FIXED_HOURS di .env).
Selalu fetch 3 hari terakhir untuk menangkap data NRT yang terlambat masuk.
"""

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import get_settings
from app.models.query import HotspotQuery
from app.services.hotspot_service import HotspotService, SUPPORTED_SATELLITES

logger = logging.getLogger("hotspot.scheduler")

_last_sync_result: dict = {}
_last_sync_at: datetime | None = None
_last_successful_sync_at: datetime | None = None
_last_hotspot_fingerprints: set[str] | None = None
_last_new_hotspot_count: int = 0
_consecutive_failures: int = 0
_next_scheduled_sync_at: datetime | None = None


def _parse_fixed_hours(raw_hours: str) -> list[int]:
    hours: list[int] = []
    for chunk in raw_hours.split(","):
        value = chunk.strip()
        if not value:
            continue

        try:
            hour = int(value)
        except ValueError:
            logger.warning("SCHEDULER: Mengabaikan jam jadwal tidak valid: %s", value)
            continue

        if hour < 0 or hour > 23:
            logger.warning("SCHEDULER: Mengabaikan jam jadwal di luar rentang 0-23: %s", value)
            continue

        if hour not in hours:
            hours.append(hour)

    return sorted(hours)


def _resolve_schedule_timezone(raw_timezone: str) -> ZoneInfo | timezone:
    try:
        return ZoneInfo(raw_timezone)
    except ZoneInfoNotFoundError:
        logger.warning(
            "SCHEDULER: Timezone jadwal tidak valid (%s), fallback ke UTC.",
            raw_timezone,
        )
        return timezone.utc


def _schedule_timezone_label(schedule_timezone: ZoneInfo | timezone) -> str:
    if hasattr(schedule_timezone, "key"):
        return str(schedule_timezone.key)
    return "UTC"


def _describe_schedule_hours(hours: list[int], schedule_timezone: ZoneInfo | timezone) -> str:
    if not hours:
        return "fallback interval"
    tz_name = schedule_timezone.tzname(datetime.now(timezone.utc).astimezone(schedule_timezone))
    schedule_text = ", ".join(f"{hour:02d}:00" for hour in hours)
    return f"{schedule_text} {tz_name}" if tz_name else schedule_text


def _next_fixed_schedule_at(
    now: datetime,
    schedule_hours: list[int],
    schedule_timezone: ZoneInfo | timezone,
    fallback_interval_hours: float,
) -> datetime:
    if not schedule_hours:
        return now + timedelta(hours=fallback_interval_hours)

    local_now = now.astimezone(schedule_timezone)
    today = local_now.date()
    for hour in schedule_hours:
        candidate_local = datetime.combine(today, time(hour=hour), tzinfo=schedule_timezone)
        if candidate_local > local_now:
            return candidate_local.astimezone(timezone.utc)

    return datetime.combine(
        today + timedelta(days=1),
        time(hour=schedule_hours[0]),
        tzinfo=schedule_timezone,
    ).astimezone(timezone.utc)


_bootstrapped: bool = False


def bootstrap_scheduler_metrics(service: HotspotService) -> None:
    global _bootstrapped
    if _bootstrapped:
        return
    _bootstrapped = True
    if service.postgres_store.enabled:
        try:
            metrics = service.postgres_store.read_scheduler_metrics()
            if metrics:
                global _last_sync_result, _last_sync_at, _last_successful_sync_at
                global _last_hotspot_fingerprints, _last_new_hotspot_count, _consecutive_failures
                
                _last_sync_result = metrics.get("last_sync_result") or {}
                _last_sync_at = metrics.get("last_sync_at")
                _last_successful_sync_at = metrics.get("last_successful_sync_at")
                
                fingerprints = metrics.get("last_hotspot_fingerprints")
                if isinstance(fingerprints, list):
                    _last_hotspot_fingerprints = set(fingerprints)
                elif isinstance(fingerprints, set):
                    _last_hotspot_fingerprints = fingerprints
                else:
                    _last_hotspot_fingerprints = None
                    
                _last_new_hotspot_count = metrics.get("last_new_hotspot_count") or 0
                _consecutive_failures = metrics.get("consecutive_failures") or 0
                
                logger.info(
                    "SCHEDULER: Berhasil memuat state dari database. "
                    "Last successful sync: %s, consecutive failures: %d",
                    _last_successful_sync_at,
                    _consecutive_failures,
                )
        except Exception as e:
            logger.error("SCHEDULER: Gagal memuat state dari database — %s", e)


def _record_sync_result(result: dict, service: HotspotService | None = None) -> None:
    global _last_sync_result, _last_sync_at, _last_successful_sync_at, _consecutive_failures
    _last_sync_result = result
    _last_sync_at = datetime.now(timezone.utc)
    if result.get("success") is True:
        _last_successful_sync_at = _last_sync_at
        _consecutive_failures = 0
    elif result.get("success") is False:
        _consecutive_failures += 1

    if service is None:
        try:
            service = HotspotService()
        except Exception:
            return

    if service.postgres_store.enabled:
        try:
            fingerprints_list = list(_last_hotspot_fingerprints) if _last_hotspot_fingerprints is not None else None
            service.postgres_store.save_scheduler_metrics(
                last_sync_result=_last_sync_result,
                last_sync_at=_last_sync_at,
                last_successful_sync_at=_last_successful_sync_at,
                consecutive_failures=_consecutive_failures,
                last_new_hotspot_count=_last_new_hotspot_count,
                last_hotspot_fingerprints=fingerprints_list,
            )
        except Exception as e:
            logger.error("SCHEDULER: Gagal menyimpan status sync ke DB — %s", e)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _hotspot_fingerprint(hotspot: dict) -> str:
    return "|".join(
        [
            str(hotspot.get("source", "")),
            str(hotspot.get("latitude", "")),
            str(hotspot.get("longitude", "")),
            str(hotspot.get("detected_at", "")),
        ]
    )


def _count_new_hotspots(hotspots: list[dict]) -> int:
    global _last_hotspot_fingerprints, _last_new_hotspot_count

    fingerprints = {_hotspot_fingerprint(hotspot) for hotspot in hotspots}
    if _last_hotspot_fingerprints is None:
        _last_hotspot_fingerprints = fingerprints
        _last_new_hotspot_count = 0
        return 0

    new_count = len(fingerprints - _last_hotspot_fingerprints)
    _last_hotspot_fingerprints = fingerprints
    _last_new_hotspot_count = new_count
    return new_count


def get_scheduler_metrics_snapshot() -> dict[str, object]:
    settings = get_settings()
    try:
        bootstrap_scheduler_metrics(HotspotService())
    except Exception:
        pass
    now = datetime.now(timezone.utc)
    schedule_hours = _parse_fixed_hours(settings.scheduler_fixed_hours)
    schedule_timezone = _resolve_schedule_timezone(settings.scheduler_timezone)
    last_sync_status = "never"
    if _last_sync_result.get("success") is True:
        last_sync_status = "success"
    elif _last_sync_result.get("success") is False:
        last_sync_status = "failure"
    elif _last_sync_result.get("skipped") is True:
        last_sync_status = "skipped"

    threshold = max(1, int(settings.scheduler_new_hotspot_alert_threshold))
    has_new_hotspot = _last_new_hotspot_count > 0
    new_hotspot_over_threshold = _last_new_hotspot_count >= threshold

    return {
        "current_time_utc": now.isoformat(),
        "last_sync_at": _isoformat(_last_sync_at),
        "last_successful_sync_at": _isoformat(_last_successful_sync_at),
        "last_sync_status": last_sync_status,
        "last_sync_hotspot_count": int(_last_sync_result.get("hotspot_count", 0) or 0),
        "last_new_hotspot_count": _last_new_hotspot_count,
        "has_new_hotspot": has_new_hotspot,
        "new_hotspot_over_threshold": new_hotspot_over_threshold,
        "new_hotspot_alert_threshold": threshold,
        "schedule_hours": schedule_hours,
        "schedule_label": _describe_schedule_hours(schedule_hours, schedule_timezone),
        "schedule_timezone": _schedule_timezone_label(schedule_timezone),
        "seconds_since_last_sync": (
            max(0.0, (now - _last_sync_at).total_seconds()) if _last_sync_at else None
        ),
        "seconds_since_last_successful_sync": (
            max(0.0, (now - _last_successful_sync_at).total_seconds())
            if _last_successful_sync_at
            else None
        ),
        "consecutive_failures": _consecutive_failures,
        "last_error": _last_sync_result.get("error"),
        "next_scheduled_sync_at": _isoformat(_next_scheduled_sync_at),
    }


async def _run_sync_cycle(service: HotspotService) -> dict:
    """
    Satu siklus sync: fetch 3 hari terakhir untuk semua layer & satelit.
    Mengembalikan ringkasan hasil.
    """
    settings = get_settings()

    if not settings.nasa_firms_api_key:
        logger.warning("SCHEDULER: nasa_firms_api_key belum dikonfigurasi, sync dilewati.")
        result = {"skipped": True, "reason": "no_api_key"}
        _record_sync_result(result, service=service)
        return result

    now = datetime.now(timezone.utc)
    start_at = (now - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
    end_at = now

    all_layers = service.layer_service.list_layers()
    layer_ids = [str(layer.id) for layer in all_layers]

    if not layer_ids:
        logger.warning("SCHEDULER: Tidak ada layer aktif ditemukan, sync dilewati.")
        result = {"skipped": True, "reason": "no_layers"}
        _record_sync_result(result, service=service)
        return result

    logger.info(
        "SCHEDULER: Mulai sync hotspot | range: %s → %s | layers: %d | satellites: %s",
        start_at.strftime("%Y-%m-%d"),
        end_at.strftime("%Y-%m-%d %H:%M"),
        len(layer_ids),
        SUPPORTED_SATELLITES,
    )

    query = HotspotQuery(
        start_at=start_at,
        end_at=end_at,
        satellites=list(SUPPORTED_SATELLITES),
        active_layers=layer_ids,
    )

    try:
        result = await service.fetch_filtered_hotspots(query, bypass_cache=True)
        count = result.get("count", 0)
        new_hotspot_count = _count_new_hotspots(list(result.get("hotspots", [])))
        logger.info("SCHEDULER: Sync selesai — %d titik hotspot ditemukan/diperbarui.", count)
        
        if service.postgres_store.enabled:
            try:
                service.postgres_store.record_hotspot_sync(hotspot_count=count, synced_at=now)
            except Exception as e:
                logger.error("SCHEDULER: Gagal merekam status sync ke DB — %s", e)

        summary = {
            "success": True,
            "hotspot_count": count,
            "new_hotspot_count": new_hotspot_count,
            "synced_at": now.isoformat(),
            "range_start": start_at.isoformat(),
            "range_end": end_at.isoformat(),
        }
        _record_sync_result(summary, service=service)
        return summary
    except Exception as exc:
        logger.error("SCHEDULER: Sync gagal — %s", exc, exc_info=True)
        result = {"success": False, "error": str(exc)}
        _record_sync_result(result, service=service)
        return result


async def hotspot_scheduler_loop(
    schedule_hours: list[int] | None = None,
    fallback_interval_hours: float = 3.0,
) -> None:
    """
    Loop scheduler yang berjalan selamanya di background.
    Jalankan sync pertama segera, lalu ulangi sesuai jam jadwal harian.
    """
    settings = get_settings()
    service = HotspotService()
    try:
        bootstrap_scheduler_metrics(service)
    except Exception:
        pass
    effective_schedule_hours = schedule_hours if schedule_hours is not None else _parse_fixed_hours(settings.scheduler_fixed_hours)
    schedule_timezone = _resolve_schedule_timezone(settings.scheduler_timezone)

    logger.info(
        "SCHEDULER: Dimulai — jadwal harian pada %s.",
        _describe_schedule_hours(effective_schedule_hours, schedule_timezone),
    )

    global _next_scheduled_sync_at

    # Check if we can skip immediate sync on startup because of a recent success
    now = datetime.now(timezone.utc)
    next_run = _next_fixed_schedule_at(
        now,
        effective_schedule_hours,
        schedule_timezone,
        fallback_interval_hours,
    )
    _next_scheduled_sync_at = next_run

    skip_immediate = False
    if _last_successful_sync_at is not None:
        elapsed_seconds = (now - _last_successful_sync_at).total_seconds()
        # threshold is 80% of fallback interval, capped at a maximum of 2 hours (7200 seconds)
        threshold_seconds = min(7200.0, fallback_interval_hours * 3600.0 * 0.8)
        if elapsed_seconds < threshold_seconds:
            skip_immediate = True
            logger.info(
                "SCHEDULER: Melewati sync langsung pada startup karena sync terakhir sukses baru dilakukan %d detik yang lalu (threshold: %d detik).",
                int(elapsed_seconds),
                int(threshold_seconds),
            )

    first_iteration = True
    while True:
        if first_iteration and skip_immediate:
            first_iteration = False
            now = datetime.now(timezone.utc)
            sleep_seconds = max(1.0, (next_run - now).total_seconds())
            logger.info(
                "SCHEDULER: Menunggu %d detik sampai jadwal berikutnya pada %s.",
                int(sleep_seconds),
                next_run.strftime("%Y-%m-%d %H:%M UTC"),
            )
            await asyncio.sleep(sleep_seconds)
            continue

        first_iteration = False
        result = await _run_sync_cycle(service)

        now = datetime.now(timezone.utc)
        next_run = _next_fixed_schedule_at(
            now,
            effective_schedule_hours,
            schedule_timezone,
            fallback_interval_hours,
        )
        _next_scheduled_sync_at = next_run
        logger.info(
            "SCHEDULER: Sync berikutnya pada %s | hasil: %s",
            next_run.strftime("%Y-%m-%d %H:%M UTC"),
            result,
        )

        sleep_seconds = max(1.0, (next_run - now).total_seconds())
        await asyncio.sleep(sleep_seconds)
