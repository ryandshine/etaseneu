import json
import pytest
from app.main import create_app
from app.services.notification_service import NotificationService


class _DisabledStore:
    enabled = False


@pytest.mark.anyio
async def test_get_notifications_api(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.notification_service.PostgresStore",
        lambda *args, **kwargs: _DisabledStore(),
    )
    app = create_app()
    messages: list[dict] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/notifications",
        "raw_path": b"/api/notifications",
        "query_string": b"limit=10",
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

    start = next(m for m in messages if m["type"] == "http.response.start")
    body = next(m for m in messages if m["type"] == "http.response.body")
    payload = json.loads(body["body"].decode("utf-8"))

    assert start["status"] == 200
    assert "total" in payload
    assert "notifications" in payload
    assert isinstance(payload["notifications"], list)
    assert len(payload["notifications"]) > 0


@pytest.mark.anyio
async def test_notification_service_notify_new_hotspots(monkeypatch) -> None:
    store = _DisabledStore()
    service = NotificationService(store=store)

    sample_hotspots = [
        {
            "source": "VIIRS NOAA-20",
            "satellite": "NOAA-20",
            "latitude": 0.5,
            "longitude": 101.4,
            "confidence": "high",
            "frp": 35.0,
            "agencyName": "KTH Tella Serasan",
            "polygonMetadata": {"NAMA_PROV": "Riau", "LEMBAGA": "KTH Tella Serasan"},
        },
        {
            "source": "MODIS",
            "satellite": "Terra",
            "latitude": -2.3,
            "longitude": 104.2,
            "confidence": "nominal",
            "frp": 12.0,
            "agencyName": "Muara Medak",
            "polygonMetadata": {"NAMA_PROV": "Sumatera Selatan"},
        },
    ]

    notif = await service.notify_new_hotspots(sample_hotspots)
    assert notif["hotspot_count"] == 2
    assert notif["severity"] == "danger"  # karena FRP > 30 dan confidence high
    assert "Riau" in notif["metadata"]["provinces"]
    assert "Sumatera Selatan" in notif["metadata"]["provinces"]
    assert "KTH Tella Serasan" in notif["metadata"]["agencies"]

    listed = service.list_notifications(limit=5)
    assert any(n["id"] == notif["id"] for n in listed)
