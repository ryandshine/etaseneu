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
    from app.core.auth import require_admin_key
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
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


def test_geojson_upload_endpoint(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.services.hotspot_service import HotspotService

    # Mock refresh_geojson to prevent actual database sync during test
    monkeypatch.setattr(HotspotService, "refresh_geojson", lambda self: {"files_scanned": 1})

    app = create_app()
    from app.core.auth import require_admin_key
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    # Mock the HotspotService init to use the temporary path for shape files
    original_init = HotspotService.__init__
    def mock_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.layer_service.shp_dir = tmp_path
        self.layer_service.clear_caches = lambda: None
    
    monkeypatch.setattr(HotspotService, "__init__", mock_init)

    # 1. Invalid file extension test
    response = client.post(
        "/api/geojson/upload",
        files={"file": ("test.txt", b"invalid data", "text/plain")},
    )
    assert response.status_code == 400
    assert "Hanya file dengan ekstensi .geojson yang diperbolehkan" in response.json()["detail"]

    # 2. Valid file test
    old_file = tmp_path / "old.geojson"
    old_file.write_text("{}", encoding="utf-8")

    response = client.post(
        "/api/geojson/upload",
        files={"file": ("new.geojson", b'{"type": "FeatureCollection"}', "application/json")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["file_name"] == "new.geojson"
    
    # Verify old file was deleted and new file was written
    assert not old_file.exists()
    assert (tmp_path / "new.geojson").exists()


def _upload_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.services.hotspot_service import HotspotService
    from app.core.auth import require_admin_key

    monkeypatch.setattr(HotspotService, "refresh_geojson", lambda self: {"files_scanned": 1})

    original_init = HotspotService.__init__

    def mock_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.layer_service.shp_dir = tmp_path
        self.layer_service.clear_caches = lambda: None

    monkeypatch.setattr(HotspotService, "__init__", mock_init)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    return TestClient(app)


def test_upload_mode_add_keeps_other_layers(monkeypatch, tmp_path) -> None:
    """Sistem ini memuat lebih dari satu layer (mis. Perhutanan Sosial dan Hutan
    Adat). Menambah layer kedua tidak boleh menghapus yang pertama."""
    client = _upload_client(monkeypatch, tmp_path)

    existing = tmp_path / "PS_FEB_26.geojson"
    existing.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    response = client.post(
        "/api/geojson/upload",
        files={"file": ("HUTAN_ADAT.geojson", b'{"type": "FeatureCollection"}', "application/json")},
        data={"mode": "add"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "add"
    assert existing.exists(), "layer lama terhapus padahal mode 'add'"
    assert (tmp_path / "HUTAN_ADAT.geojson").exists()


def test_upload_mode_replace_is_still_the_default(monkeypatch, tmp_path) -> None:
    """Perilaku lama dipertahankan supaya pemanggil yang sudah ada tidak
    berubah artinya diam-diam."""
    client = _upload_client(monkeypatch, tmp_path)

    existing = tmp_path / "lama.geojson"
    existing.write_text("{}", encoding="utf-8")

    response = client.post(
        "/api/geojson/upload",
        files={"file": ("baru.geojson", b'{"type": "FeatureCollection"}', "application/json")},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "replace"
    assert not existing.exists()


def test_deactivate_geojson_removes_file_but_keeps_registry_row(monkeypatch, tmp_path) -> None:
    client = _upload_client(monkeypatch, tmp_path)

    from app.services.postgres_store import PostgresStore

    calls: list[str] = []

    def fake_deactivate(self, file_name: str) -> bool:
        calls.append(file_name)
        return True

    monkeypatch.setattr(PostgresStore, "deactivate_geojson_file_registry", fake_deactivate)
    monkeypatch.setattr(
        "app.services.hotspot_service.HotspotService.refresh_polygon_hotspot_summaries",
        lambda self: {"active_polygon_count": 1, "pruned": 1, "rebuilt": 0},
    )

    existing = tmp_path / "PS_FEB_26.geojson"
    existing.write_text("{}", encoding="utf-8")

    response = client.post("/api/geojson/PS_FEB_26.geojson/deactivate")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "deactivated"
    assert body["file_removed"] is True
    assert body["deactivated"] is True
    assert not existing.exists()
    assert calls == ["PS_FEB_26.geojson"]


def test_deactivate_geojson_404_when_unknown(monkeypatch, tmp_path) -> None:
    client = _upload_client(monkeypatch, tmp_path)

    from app.services.postgres_store import PostgresStore

    monkeypatch.setattr(PostgresStore, "deactivate_geojson_file_registry", lambda self, file_name: False)

    response = client.post("/api/geojson/tidak-ada.geojson/deactivate")

    assert response.status_code == 404


def test_delete_geojson_removes_file_and_deactivates_registry(monkeypatch, tmp_path) -> None:
    client = _upload_client(monkeypatch, tmp_path)

    from app.services.postgres_store import PostgresStore

    calls: list[str] = []

    def fake_remove(self, file_name: str) -> str | None:
        calls.append(file_name)
        return "PS_FEB_26"

    monkeypatch.setattr(PostgresStore, "remove_geojson_file_registry", fake_remove)
    monkeypatch.setattr(
        "app.services.hotspot_service.HotspotService.refresh_polygon_hotspot_summaries",
        lambda self: {"active_polygon_count": 1, "pruned": 0, "rebuilt": 1},
    )

    existing = tmp_path / "PS_FEB_26.geojson"
    existing.write_text("{}", encoding="utf-8")

    response = client.delete("/api/geojson/PS_FEB_26.geojson")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "deleted"
    assert body["file_name"] == "PS_FEB_26.geojson"
    assert body["file_removed"] is True
    assert body["layer_key"] == "PS_FEB_26"
    assert not existing.exists()
    assert calls == ["PS_FEB_26.geojson"]


def test_delete_geojson_404_when_unknown(monkeypatch, tmp_path) -> None:
    client = _upload_client(monkeypatch, tmp_path)

    from app.services.postgres_store import PostgresStore

    monkeypatch.setattr(PostgresStore, "remove_geojson_file_registry", lambda self, file_name: None)

    response = client.delete("/api/geojson/tidak-ada.geojson")

    assert response.status_code == 404


def test_delete_geojson_rejects_path_traversal(monkeypatch, tmp_path) -> None:
    client = _upload_client(monkeypatch, tmp_path)

    from app.services.postgres_store import PostgresStore

    calls: list[str] = []
    monkeypatch.setattr(
        PostgresStore,
        "remove_geojson_file_registry",
        lambda self, file_name: calls.append(file_name) or None,
    )

    response = client.delete("/api/geojson/..%2F..%2Fetc%2Fpasswd")

    # "{file_name}" adalah path segment tunggal -- routing FastAPI sendiri
    # sudah menolak "/" yang ter-decode dari "%2F" sebelum handler dipanggil,
    # jadi Path(...).name di dalam handler adalah lapisan pertahanan kedua,
    # bukan satu-satunya. calls tetap kosong karena handler tidak pernah jalan.
    assert response.status_code == 404
    assert calls == []


def test_upload_rejects_unknown_mode(monkeypatch, tmp_path) -> None:
    client = _upload_client(monkeypatch, tmp_path)
    existing = tmp_path / "lama.geojson"
    existing.write_text("{}", encoding="utf-8")

    response = client.post(
        "/api/geojson/upload",
        files={"file": ("baru.geojson", b"{}", "application/json")},
        data={"mode": "hapus-semua"},
    )

    assert response.status_code == 400
    # Mode yang salah tidak boleh sempat menghapus apa pun.
    assert existing.exists()
