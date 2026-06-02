from datetime import datetime, timezone


async def _request_scheduler_metrics() -> tuple[int, dict]:
    import json

    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/scheduler/metrics",
        "raw_path": b"/api/scheduler/metrics",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)

    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")
    payload = json.loads(body["body"].decode("utf-8"))
    return start["status"], payload


async def _request_prometheus_metrics() -> tuple[int, str, list[tuple[bytes, bytes]]]:
    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/metrics",
        "raw_path": b"/api/metrics",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)

    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")
    return start["status"], body["body"].decode("utf-8"), start["headers"]


def test_run_sync_cycle_updates_shared_scheduler_status(monkeypatch) -> None:
    import asyncio

    from app.services import scheduler as scheduler_module

    class DummyLayer:
        id = "sample_area"

    class DummyLayerService:
        def list_layers(self) -> list[DummyLayer]:
            return [DummyLayer()]

    class DummyPostgresStore:
        enabled = False

    class DummyHotspotService:
        def __init__(self) -> None:
            self.layer_service = DummyLayerService()
            self.postgres_store = DummyPostgresStore()

        async def fetch_filtered_hotspots(self, query, bypass_cache: bool = False):
            return {"count": 7, "hotspots": [], "stats": {}}

    scheduler_module._last_sync_at = None
    scheduler_module._last_sync_result = {}

    async def _run() -> dict:
        service = DummyHotspotService()
        return await scheduler_module._run_sync_cycle(service)

    result = asyncio.run(_run())

    assert result["success"] is True
    assert scheduler_module._last_sync_result["hotspot_count"] == 7
    assert scheduler_module._last_sync_at is not None
    assert scheduler_module._last_sync_at.tzinfo == timezone.utc


def test_scheduler_status_reads_shared_scheduler_state(monkeypatch) -> None:
    import asyncio

    from app.api import scheduler as scheduler_api
    from app.services import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "bootstrap_scheduler_metrics", lambda *args, **kwargs: None)

    now = datetime(2026, 5, 28, 8, 30, tzinfo=timezone.utc)
    scheduler_module._last_sync_at = now
    scheduler_module._last_sync_result = {"success": True, "hotspot_count": 3}

    payload = asyncio.run(scheduler_api.scheduler_status())

    assert payload["last_sync_at"] == now.isoformat()
    assert payload["last_sync_result"] == {"success": True, "hotspot_count": 3}


def test_scheduler_metrics_endpoint_returns_operational_snapshot(monkeypatch) -> None:
    import asyncio

    from app.core.config import get_settings
    from app.services import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "bootstrap_scheduler_metrics", lambda *args, **kwargs: None)

    get_settings.cache_clear()
    now = datetime(2026, 5, 28, 8, 30, tzinfo=timezone.utc)
    scheduler_module._last_sync_at = now
    scheduler_module._last_successful_sync_at = now
    scheduler_module._last_sync_result = {"success": True, "hotspot_count": 3}
    scheduler_module._last_new_hotspot_count = 1
    scheduler_module._consecutive_failures = 0
    scheduler_module._next_scheduled_sync_at = datetime(2026, 5, 28, 11, 30, tzinfo=timezone.utc)

    status, payload = asyncio.run(_request_scheduler_metrics())

    assert status == 200
    assert payload["last_sync_status"] == "success"
    assert payload["last_sync_hotspot_count"] == 3
    assert payload["last_new_hotspot_count"] == 1
    assert payload["has_new_hotspot"] is True
    assert payload["new_hotspot_over_threshold"] is True
    assert payload["new_hotspot_alert_threshold"] == 1
    assert payload["schedule_hours"] == [0, 3, 6, 9, 12, 15, 18, 21]
    assert payload["schedule_label"] == "00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 WIB"
    assert payload["schedule_timezone"] == "Asia/Jakarta"
    assert payload["consecutive_failures"] == 0
    assert payload["next_scheduled_sync_at"] == "2026-05-28T11:30:00+00:00"


def test_prometheus_metrics_endpoint_exposes_scheduler_metrics(monkeypatch) -> None:
    import asyncio

    from app.core.config import get_settings
    from app.services import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "bootstrap_scheduler_metrics", lambda *args, **kwargs: None)

    get_settings.cache_clear()
    now = datetime(2026, 5, 28, 8, 30, tzinfo=timezone.utc)
    scheduler_module._last_sync_at = now
    scheduler_module._last_successful_sync_at = now
    scheduler_module._last_sync_result = {"success": False, "error": "boom"}
    scheduler_module._last_new_hotspot_count = 4
    scheduler_module._consecutive_failures = 2
    scheduler_module._next_scheduled_sync_at = datetime(2026, 5, 28, 11, 30, tzinfo=timezone.utc)

    status, body, headers = asyncio.run(_request_prometheus_metrics())

    assert status == 200
    assert any(header == (b"content-type", b"text/plain; version=0.0.4; charset=utf-8") for header in headers)
    assert "etaseneu_scheduler_last_sync_success 0" in body
    assert "etaseneu_scheduler_last_new_hotspot_count 4" in body
    assert "etaseneu_scheduler_has_new_hotspot 1" in body
    assert "etaseneu_scheduler_new_hotspot_over_threshold 1" in body
    assert "etaseneu_scheduler_consecutive_failures 2" in body
    assert "etaseneu_scheduler_next_scheduled_sync_timestamp_seconds" in body


def test_successful_sync_resets_consecutive_failures() -> None:
    from app.services import scheduler as scheduler_module

    scheduler_module._consecutive_failures = 2

    scheduler_module._record_sync_result({"success": True, "hotspot_count": 5})

    assert scheduler_module._consecutive_failures == 0
    assert scheduler_module._last_successful_sync_at is not None


def test_run_sync_cycle_uses_first_success_as_baseline_for_new_hotspots() -> None:
    import asyncio

    from app.services import scheduler as scheduler_module

    class DummyLayer:
        id = "sample_area"

    class DummyLayerService:
        def list_layers(self) -> list[DummyLayer]:
            return [DummyLayer()]

    class DummyPostgresStore:
        enabled = False

    class DummyHotspotService:
        def __init__(self, payloads: list[dict]) -> None:
            self.layer_service = DummyLayerService()
            self.postgres_store = DummyPostgresStore()
            self._payloads = payloads

        async def fetch_filtered_hotspots(self, query, bypass_cache: bool = False):
            return self._payloads.pop(0)

    scheduler_module._last_hotspot_fingerprints = None
    scheduler_module._last_new_hotspot_count = 0

    first_service = DummyHotspotService(
        [
            {
                "count": 2,
                "hotspots": [
                    {"source": "MODIS", "latitude": 4.1, "longitude": 95.1, "detected_at": "2026-05-28T08:00:00Z"},
                    {"source": "MODIS", "latitude": 4.2, "longitude": 95.2, "detected_at": "2026-05-28T08:10:00Z"},
                ],
                "stats": {},
            }
        ]
    )
    second_service = DummyHotspotService(
        [
            {
                "count": 3,
                "hotspots": [
                    {"source": "MODIS", "latitude": 4.1, "longitude": 95.1, "detected_at": "2026-05-28T08:00:00Z"},
                    {"source": "MODIS", "latitude": 4.2, "longitude": 95.2, "detected_at": "2026-05-28T08:10:00Z"},
                    {"source": "VIIRS", "latitude": 4.3, "longitude": 95.3, "detected_at": "2026-05-28T08:20:00Z"},
                ],
                "stats": {},
            }
        ]
    )

    first_result = asyncio.run(scheduler_module._run_sync_cycle(first_service))
    second_result = asyncio.run(scheduler_module._run_sync_cycle(second_service))

    assert first_result["new_hotspot_count"] == 0
    assert second_result["new_hotspot_count"] == 1
    assert scheduler_module._last_new_hotspot_count == 1


def test_next_fixed_schedule_aligns_to_configured_hours() -> None:
    from app.services import scheduler as scheduler_module

    now = datetime(2026, 5, 28, 16, 42, tzinfo=timezone.utc)
    schedule_hours = [0, 3, 6, 9, 12, 15, 18, 21]
    schedule_timezone = scheduler_module._resolve_schedule_timezone("Asia/Jakarta")

    next_run = scheduler_module._next_fixed_schedule_at(now, schedule_hours, schedule_timezone, 3.0)

    assert next_run == datetime(2026, 5, 28, 17, 0, tzinfo=timezone.utc)


def test_next_fixed_schedule_rolls_over_to_next_day_after_last_slot() -> None:
    from app.services import scheduler as scheduler_module

    now = datetime(2026, 5, 28, 22, 10, tzinfo=timezone.utc)
    schedule_hours = [0, 3, 6, 9, 12, 15, 18, 21]
    schedule_timezone = scheduler_module._resolve_schedule_timezone("Asia/Jakarta")

    next_run = scheduler_module._next_fixed_schedule_at(now, schedule_hours, schedule_timezone, 3.0)

    assert next_run == datetime(2026, 5, 28, 23, 0, tzinfo=timezone.utc)
