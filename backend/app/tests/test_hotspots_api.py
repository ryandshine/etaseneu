import asyncio
import json


async def _request_hotspots() -> tuple[int, dict]:
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
        "path": "/api/hotspots",
        "raw_path": b"/api/hotspots",
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


async def _request_hotspots_map_view() -> tuple[int, dict]:
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
        "path": "/api/hotspots",
        "raw_path": b"/api/hotspots",
        "query_string": (
            b"start_date=2026-01-01&end_date=2026-05-26"
            b"&satellites=MODIS&active_layers=sample_area&view=map"
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


async def _request_hotspots_with_bad_date() -> tuple[int, dict]:
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
        "path": "/api/hotspots",
        "raw_path": b"/api/hotspots",
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


def test_hotspots_endpoint_returns_collection(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("NASA_FIRMS_API_KEY", "")

    try:
        status, body = asyncio.run(_request_hotspots())

        assert status == 200
        assert "hotspots" in body
        assert "count" in body
    finally:
        get_settings.cache_clear()


def test_hotspots_endpoint_returns_map_view_payload(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services.hotspot_service import HotspotService

    async def fake_fetch_filtered_hotspots(self, query, bypass_cache: bool = False) -> dict:
        return {
            "count": 1,
            "hotspots": [
                {
                    "id": "hs-1",
                    "source": "MODIS",
                    "satellite": "MODIS",
                    "latitude": 1.23,
                    "longitude": 4.56,
                    "brightness": 320.0,
                    "frp": 12.5,
                    "detected_at": "2026-05-26T01:02:03Z",
                    "agency_name": "Agency",
                    "province_name": "Aceh",
                    "confidence": "high",
                    "daynight": "D",
                    "polygon_metadata": {"LEMBAGA": "Agency"},
                }
            ],
            "stats": {"total": 1, "by_source": {"MODIS": 1}, "by_layer": {"sample_area": 1}},
        }

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("NASA_FIRMS_API_KEY", "")
    monkeypatch.setattr(HotspotService, "fetch_filtered_hotspots", fake_fetch_filtered_hotspots)

    try:
        status, body = asyncio.run(_request_hotspots_map_view())

        assert status == 200
        assert body["count"] == 1
        assert body["hotspots"][0]["agency_name"] == "Agency"
        assert body["hotspots"][0]["province_name"] == "Aceh"
        assert "confidence" not in body["hotspots"][0]
        assert "daynight" not in body["hotspots"][0]
        assert "polygon_metadata" not in body["hotspots"][0]
    finally:
        get_settings.cache_clear()


def test_hotspots_endpoint_returns_422_for_invalid_dates(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("NASA_FIRMS_API_KEY", "")

    try:
        status, body = asyncio.run(_request_hotspots_with_bad_date())

        assert status == 422
        assert body["detail"]
    finally:
        get_settings.cache_clear()
