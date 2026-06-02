from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.services import scheduler as scheduler_service


router = APIRouter()


def _format_labels(labels: dict[str, str] | None = None) -> str:
    if not labels:
        return ""

    rendered = []
    for key, value in labels.items():
        rendered.append(f'{key}="{value}"')
    return "{" + ",".join(rendered) + "}"


def _metric_line(name: str, value: object, labels: dict[str, str] | None = None) -> str:
    return f"{name}{_format_labels(labels)} {value}"


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    settings = get_settings()
    snapshot = scheduler_service.get_scheduler_metrics_snapshot()

    last_sync_at = scheduler_service._last_sync_at
    last_successful_sync_at = scheduler_service._last_successful_sync_at
    next_scheduled_sync_at = scheduler_service._next_scheduled_sync_at
    last_sync_success = 1 if snapshot["last_sync_status"] == "success" else 0

    lines = [
        _metric_line("etaseneu_scheduler_enabled", 1 if settings.scheduler_enabled else 0),
        _metric_line(
            "etaseneu_scheduler_schedule_info",
            1,
            labels={
                "hours": ",".join(f"{hour:02d}:00" for hour in snapshot["schedule_hours"]),
                "label": str(snapshot["schedule_label"]),
                "timezone": str(snapshot["schedule_timezone"]),
            },
        ),
        _metric_line(
            "etaseneu_scheduler_last_sync_timestamp_seconds",
            int(last_sync_at.timestamp()) if last_sync_at else 0,
        ),
        _metric_line(
            "etaseneu_scheduler_last_successful_sync_timestamp_seconds",
            int(last_successful_sync_at.timestamp()) if last_successful_sync_at else 0,
        ),
        _metric_line(
            "etaseneu_scheduler_seconds_since_last_successful_sync",
            snapshot["seconds_since_last_successful_sync"] or 0,
        ),
        _metric_line(
            "etaseneu_scheduler_last_hotspot_count",
            snapshot["last_sync_hotspot_count"],
        ),
        _metric_line(
            "etaseneu_scheduler_last_new_hotspot_count",
            snapshot["last_new_hotspot_count"],
        ),
        _metric_line(
            "etaseneu_scheduler_has_new_hotspot",
            1 if snapshot["has_new_hotspot"] else 0,
        ),
        _metric_line(
            "etaseneu_scheduler_new_hotspot_over_threshold",
            1 if snapshot["new_hotspot_over_threshold"] else 0,
        ),
        _metric_line(
            "etaseneu_scheduler_new_hotspot_alert_threshold",
            snapshot["new_hotspot_alert_threshold"],
        ),
        _metric_line(
            "etaseneu_scheduler_consecutive_failures",
            snapshot["consecutive_failures"],
        ),
        _metric_line("etaseneu_scheduler_last_sync_success", last_sync_success),
        _metric_line(
            "etaseneu_scheduler_next_scheduled_sync_timestamp_seconds",
            int(next_scheduled_sync_at.timestamp()) if next_scheduled_sync_at else 0,
        ),
    ]

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
