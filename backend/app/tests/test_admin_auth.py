import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import require_admin_key
from app.core.config import get_settings


@pytest.fixture
def protected_app(monkeypatch):
    """App kecil khusus untuk test dependency-nya sendiri, terlepas dari
    endpoint asli mana pun -- fokus hanya pada perilaku require_admin_key."""
    app = FastAPI()

    @app.post("/protected")
    async def protected_route(_: None = Depends(require_admin_key)) -> dict[str, bool]:
        return {"ok": True}

    def _client_with_key(key: str) -> None:
        monkeypatch.setenv("ADMIN_API_KEY", key)
        get_settings.cache_clear()

    yield app, _client_with_key
    get_settings.cache_clear()


def test_fails_closed_when_admin_key_not_configured(protected_app, monkeypatch):
    app, set_key = protected_app
    # Diset kosong, bukan delenv: menghapus env var saja tidak cukup karena
    # Pydantic masih membaca backend/.env milik developer (yang biasanya
    # berisi ADMIN_API_KEY). Env var kosong menang atas isi .env, jadi test
    # ini menguji kode -- bukan konfigurasi lokal siapa pun yang menjalankannya.
    monkeypatch.setenv("ADMIN_API_KEY", "")
    get_settings.cache_clear()

    client = TestClient(app)
    response = client.post("/protected")

    assert response.status_code == 503


def test_rejects_missing_header_when_configured(protected_app):
    app, set_key = protected_app
    set_key("s3cret")

    client = TestClient(app)
    response = client.post("/protected")

    assert response.status_code == 401


def test_rejects_wrong_key(protected_app):
    app, set_key = protected_app
    set_key("s3cret")

    client = TestClient(app)
    response = client.post("/protected", headers={"X-Admin-Key": "wrong"})

    assert response.status_code == 401


def test_accepts_correct_key(protected_app):
    app, set_key = protected_app
    set_key("s3cret")

    client = TestClient(app)
    response = client.post("/protected", headers={"X-Admin-Key": "s3cret"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_verify_endpoint_uses_same_dependency(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)

        assert client.post("/api/auth/verify").status_code == 401
        assert client.post("/api/auth/verify", headers={"X-Admin-Key": "wrong"}).status_code == 401
        ok = client.post("/api/auth/verify", headers={"X-Admin-Key": "s3cret"})
        assert ok.status_code == 200
        assert ok.json() == {"ok": True}
    finally:
        get_settings.cache_clear()


# --- /api/auth/login (gerbang login seluruh aplikasi, terpisah dari admin key) ---


def test_login_fails_closed_when_password_not_configured(monkeypatch):
    from app.main import create_app

    # Sama seperti test admin key: diset kosong (bukan delenv) supaya .env
    # developer lokal tidak ikut memengaruhi hasil test ini.
    monkeypatch.setenv("APP_LOGIN_PASSWORD", "")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": "admin", "password": "context7"})
        assert response.status_code == 503
    finally:
        get_settings.cache_clear()


def test_login_rejects_wrong_password(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "context7")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_login_rejects_wrong_username(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "context7")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": "someone-else", "password": "context7"})
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


def test_login_accepts_correct_credentials(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "context7")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": "admin", "password": "context7"})
        assert response.status_code == 200
        assert response.json() == {"ok": True}
    finally:
        get_settings.cache_clear()
