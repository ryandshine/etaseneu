import asyncio
import json


async def _request_geojson_status() -> tuple[int, dict]:
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
        "path": "/api/geojson/status",
        "raw_path": b"/api/geojson/status",
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


async def _request_geojson_refresh() -> tuple[int, dict]:
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
        "path": "/api/geojson/refresh",
        "raw_path": b"/api/geojson/refresh",
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


def test_geojson_status_endpoint(monkeypatch) -> None:
    from app.services.hotspot_service import HotspotService

    def fake_status(self) -> dict[str, object]:
        return {
            "database_enabled": True,
            "database_url_present": True,
            "count": 1,
            "active_count": 1,
            "inactive_count": 0,
            "files": [
                {
                    "file_name": "sample.geojson",
                    "layer_key": "sample",
                    "is_active": True,
                    "feature_count": 1,
                }
            ],
        }

    monkeypatch.setattr(HotspotService, "geojson_status", fake_status)

    status, body = asyncio.run(_request_geojson_status())

    assert status == 200
    assert body["database_enabled"] is True
    assert body["count"] == 1
    assert body["active_count"] == 1
    assert body["files"][0]["file_name"] == "sample.geojson"


def test_geojson_refresh_endpoint(monkeypatch) -> None:
    from app.services.hotspot_service import HotspotService

    def fake_refresh(self) -> dict[str, object]:
        return {
            "files_scanned": 1,
            "files_changed": 1,
            "files_unchanged": 0,
            "files_inactive": 0,
            "features_upserted": 1,
            "features_deactivated": 0,
            "files": [
                {
                    "file_name": "sample.geojson",
                    "layer_key": "sample",
                    "changed": True,
                    "feature_count": 1,
                }
            ],
        }

    monkeypatch.setattr(HotspotService, "refresh_geojson", fake_refresh)

    status, body = asyncio.run(_request_geojson_refresh())

    assert status == 200
    assert body["files_scanned"] == 1
    assert body["files_changed"] == 1
    assert body["files"][0]["file_name"] == "sample.geojson"
