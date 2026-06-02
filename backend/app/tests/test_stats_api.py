import asyncio
import json


async def _request_stats() -> tuple[int, dict]:
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
        "path": "/api/stats",
        "raw_path": b"/api/stats",
        "query_string": (
            b"start_date=2026-01-01&end_date=2026-05-26"
            b"&satellites=MODIS&active_layers=sample_area"
        ),
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


async def _request_stats_with_bad_date() -> tuple[int, dict]:
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
        "path": "/api/stats",
        "raw_path": b"/api/stats",
        "query_string": (
            b"start_date=bad-date&end_date=2026-05-26"
            b"&satellites=MODIS&active_layers=sample_area"
        ),
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


def test_stats_endpoint_returns_summary(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("NASA_FIRMS_API_KEY", "")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / ".cache"))
    monkeypatch.setenv("DATABASE_URL", "")

    try:
        status, body = asyncio.run(_request_stats())

        assert status == 200
        assert body["total"] == 0
        assert body["by_source"] == {}
        assert body["by_layer"] == {}
    finally:
        get_settings.cache_clear()


def test_stats_endpoint_returns_422_for_invalid_dates(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("NASA_FIRMS_API_KEY", "")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / ".cache"))

    try:
        status, body = asyncio.run(_request_stats_with_bad_date())

        assert status == 422
        assert body["detail"]
    finally:
        get_settings.cache_clear()
