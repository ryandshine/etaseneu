import asyncio
import json


async def _request_cache_history_status() -> tuple[int, dict]:
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
        "path": "/api/cache/history/status",
        "raw_path": b"/api/cache/history/status",
        "query_string": b"year=2026&satellites=MODIS&active_layers=sample_area",
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


async def _request_cache_history_prewarm() -> tuple[int, dict]:
    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/cache/history/prewarm",
        "raw_path": b"/api/cache/history/prewarm",
        "query_string": b"year=2026&satellites=MODIS&active_layers=sample_area",
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


async def _request_storage_status() -> tuple[int, dict]:
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
        "path": "/api/storage/status",
        "raw_path": b"/api/storage/status",
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


async def _request_polygon_hotspot_summary_refresh() -> tuple[int, dict]:
    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/polygon-hotspot-summary/refresh",
        "raw_path": b"/api/polygon-hotspot-summary/refresh",
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


def test_cache_history_status_endpoint(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("NASA_FIRMS_API_KEY", "")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / ".cache"))
    monkeypatch.setenv("DATABASE_URL", "")

    try:
        status, body = asyncio.run(_request_cache_history_status())

        assert status == 200
        assert body["year"] == 2026
        assert body["cached"] is False
        assert body["layers"]
    finally:
        get_settings.cache_clear()


def test_cache_history_prewarm_endpoint(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings
    from app.services.hotspot_service import HotspotService

    async def fake_prewarm(self, year: int, satellites=None, layer_ids=None) -> dict[str, object]:
        return {
            "year": year,
            "cached": True,
            "layer_count": 1,
            "layers": ["sample_area"],
            "satellites": satellites or ["MODIS"],
        }

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("NASA_FIRMS_API_KEY", "")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / ".cache"))
    monkeypatch.setattr(HotspotService, "prewarm_year_history", fake_prewarm)

    try:
        status, body = asyncio.run(_request_cache_history_prewarm())

        assert status == 200
        assert body["cached"] is True
        assert body["layer_count"] == 1
    finally:
        get_settings.cache_clear()


def test_storage_status_endpoint(monkeypatch) -> None:
    from app.services.hotspot_service import HotspotService

    def fake_storage_status(self) -> dict[str, object]:
        return {
            "database_enabled": True,
            "database_url_present": True,
            "last_hotspot_sync_at": "2026-05-28T00:10:59+07:00",
            "last_hotspot_sync_count": 136,
            "tables": {
                "layers": 1,
                "geojson_file_registry": 1,
                "hotspot_history_archives": 2,
                "api_cache_entries": 3,
                "hotspot_observations": 4,
                "hotspot_sync_state": 1,
            },
        }

    monkeypatch.setattr(HotspotService, "storage_status", fake_storage_status)

    status, body = asyncio.run(_request_storage_status())

    assert status == 200
    assert body["database_enabled"] is True
    assert body["tables"]["layers"] == 1
    assert body["tables"]["geojson_file_registry"] == 1
    assert body["tables"]["hotspot_observations"] == 4
    assert body["last_hotspot_sync_at"] == "2026-05-28T00:10:59+07:00"


def test_polygon_hotspot_summary_refresh_endpoint(monkeypatch) -> None:
    from app.services.hotspot_service import HotspotService

    def fake_refresh(self) -> dict[str, int]:
        return {
            "active_polygon_count": 2,
            "pruned": 1,
            "rebuilt": 2,
        }

    monkeypatch.setattr(HotspotService, "refresh_polygon_hotspot_summaries", fake_refresh)

    status, body = asyncio.run(_request_polygon_hotspot_summary_refresh())

    assert status == 200
    assert body == {
        "active_polygon_count": 2,
        "pruned": 1,
        "rebuilt": 2,
    }
