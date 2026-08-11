import asyncio
import json
from urllib.parse import urlsplit


async def _request_layers(query: str = "", admin_key: str | None = None) -> tuple[int, dict]:
    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    headers = [(b"x-admin-key", admin_key.encode("utf-8"))] if admin_key else []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/layers",
        "raw_path": b"/api/layers",
        "query_string": query.encode("utf-8"),
        "headers": headers,
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


async def _request_layer_detail(path: str, admin_key: str | None = None) -> tuple[int, dict]:
    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    parsed = urlsplit(path)
    headers = [(b"x-admin-key", admin_key.encode("utf-8"))] if admin_key else []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("utf-8"),
        "query_string": parsed.query.encode("utf-8"),
        "headers": headers,
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


def test_layers_endpoint_returns_detected_layers(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("ADMIN_API_KEY", "kunci-rahasia")
    try:
        status, body = asyncio.run(_request_layers(admin_key="kunci-rahasia"))

        assert status == 200
        assert body["count"] == 1
        assert "layers" in body
        assert body["layers"][0]["id"] == "sample_area"
    finally:
        get_settings.cache_clear()


def test_layer_detail_endpoint_returns_preview_geometry(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("ADMIN_API_KEY", "kunci-rahasia")
    try:
        status, body = asyncio.run(
            _request_layer_detail("/api/layers/sample_area?view=preview", admin_key="kunci-rahasia")
        )

        assert status == 200
        assert body["id"] == "sample_area"
        assert body["geojson_mode"] == "preview"
        assert len(body["geojson"]["features"]) == 1
    finally:
        get_settings.cache_clear()


def test_layers_preview_stays_public_for_the_map(monkeypatch) -> None:
    """Peta publik memanggil ini saat halaman dibuka -- jangan sampai terkunci."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("ADMIN_API_KEY", "kunci-rahasia")
    try:
        status, body = asyncio.run(_request_layers(query="view=preview"))

        assert status == 200
        assert body["layers"][0]["geojson_mode"] == "preview"
    finally:
        get_settings.cache_clear()


def test_layers_full_mode_requires_admin_key(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("ADMIN_API_KEY", "kunci-rahasia")
    try:
        status, _ = asyncio.run(_request_layers())
        assert status == 401

        status, _ = asyncio.run(_request_layers(admin_key="tebakan-salah"))
        assert status == 401
    finally:
        get_settings.cache_clear()


def test_layer_detail_requires_admin_key_even_in_preview_mode(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("ADMIN_API_KEY", "kunci-rahasia")
    try:
        status, _ = asyncio.run(_request_layer_detail("/api/layers/sample_area?view=preview"))
        assert status == 401
    finally:
        get_settings.cache_clear()
