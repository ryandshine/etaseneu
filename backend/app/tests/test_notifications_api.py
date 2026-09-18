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
    assert len(notif["metadata"]["hotspots"]) == 2
    assert notif["metadata"]["hotspots"][0]["frp"] == 35.0
    assert "google.com/maps?q=0.50000,101.40000" in notif["metadata"]["hotspots"][0]["google_maps_url"]

    listed = service.list_notifications(limit=5)
    assert any(n["id"] == notif["id"] for n in listed)


@pytest.mark.anyio
async def test_notification_filters_low_confidence_and_includes_gmaps_frp(monkeypatch) -> None:
    store = _DisabledStore()
    service = NotificationService(store=store)

    mixed_hotspots = [
        {
            "source": "VIIRS NOAA-20",
            "satellite": "NOAA-20",
            "latitude": -1.234,
            "longitude": 103.567,
            "confidence": "high",
            "frp": 42.5,
            "agencyName": "KPH Muara Jambi",
            "polygonMetadata": {"NAMA_PROV": "Jambi", "LEMBAGA": "KPH Muara Jambi"},
        },
        {
            "source": "VIIRS S-NPP",
            "satellite": "S-NPP",
            "latitude": -0.891,
            "longitude": 102.123,
            "confidence": "nominal",
            "frp": 14.2,
            "agencyName": "KPS Bukit Betabuh",
            "polygonMetadata": {"NAMA_PROV": "Riau", "LEMBAGA": "KPS Bukit Betabuh"},
        },
        {
            "source": "MODIS",
            "satellite": "Terra",
            "latitude": -6.789,
            "longitude": 106.123,
            "confidence": "low",  # Harus disaring / diabaikan
            "frp": 4.1,
            "agencyName": "KPS Rendah",
            "polygonMetadata": {"NAMA_PROV": "Jawa Barat"},
        },
        {
            "source": "MODIS",
            "satellite": "Aqua",
            "latitude": -7.123,
            "longitude": 108.456,
            "confidence": "20",  # 20% < 30% -> Rendah, harus disaring
            "frp": 2.5,
            "agencyName": "KPS Sangat Rendah",
        },
    ]

    notif = await service.notify_new_hotspots(mixed_hotspots)
    # Dari 4 titik panas, hanya 2 yang lolos (high & nominal/medium)
    assert notif["hotspot_count"] == 2
    hotspots = notif["metadata"]["hotspots"]
    assert len(hotspots) == 2
    assert all(h["confidence"] in ("Tinggi", "Sedang") for h in hotspots)
    assert hotspots[0]["frp"] == 42.5
    assert "https://www.google.com/maps?q=-1.23400,103.56700" in hotspots[0]["google_maps_url"]
    assert hotspots[1]["frp"] == 14.2
    assert "https://www.google.com/maps?q=-0.89100,102.12300" in hotspots[1]["google_maps_url"]

    # Jika semua hotspot berkeyakinan rendah, notifikasi harus kosong / tidak dipicu
    low_only = [
        {"latitude": -1.0, "longitude": 100.0, "confidence": "l", "frp": 3.0},
        {"latitude": -2.0, "longitude": 101.0, "confidence": "low", "frp": 2.0},
    ]
    empty_notif = await service.notify_new_hotspots(low_only)
    assert empty_notif == {}

