"""Verifikasi Cloudflare Turnstile di POST /api/auth/login.

Tidak menyentuh Postgres produksi: get_store() di-override ke FakeUserStore
(lihat CLAUDE.md bahaya #1), dan verify_turnstile() di-monkeypatch supaya
tidak ada request keluar ke Cloudflare.
"""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.tests.test_admin_auth import FakeUserStore


@pytest.fixture
def turnstile_app(monkeypatch):
    from app.api.auth import get_store
    from app.main import create_app

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "context7")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "server-secret")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_store] = lambda: FakeUserStore()

    yield app, monkeypatch

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_login_blocked_when_token_missing(turnstile_app):
    app, _ = turnstile_app
    client = TestClient(app)

    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "context7"}
    )

    assert response.status_code == 400
    assert "captcha" in response.json()["detail"].lower()


def test_login_blocked_when_verification_fails(turnstile_app):
    app, monkeypatch = turnstile_app

    async def _reject(*_args, **_kwargs) -> bool:
        return False

    monkeypatch.setattr("app.api.auth.verify_turnstile", _reject)
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "context7", "turnstile_token": "tok"},
    )

    assert response.status_code == 400


def test_login_succeeds_when_verification_passes(turnstile_app):
    app, monkeypatch = turnstile_app
    seen: dict[str, object] = {}

    async def _accept(token: str, *, secret: str, remote_ip=None) -> bool:
        seen.update(token=token, secret=secret)
        return True

    monkeypatch.setattr("app.api.auth.verify_turnstile", _accept)
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "context7", "turnstile_token": "tok"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "admin" and body["token"]
    assert seen == {"token": "tok", "secret": "server-secret"}


def test_wrong_password_still_rejected_even_with_valid_captcha(turnstile_app):
    app, monkeypatch = turnstile_app

    async def _accept(*_args, **_kwargs) -> bool:
        return True

    monkeypatch.setattr("app.api.auth.verify_turnstile", _accept)
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "salah", "turnstile_token": "tok"},
    )

    assert response.status_code == 401


def test_login_ignores_captcha_when_secret_not_configured(monkeypatch):
    from app.api.auth import get_store
    from app.main import create_app

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "context7")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_store] = lambda: FakeUserStore()
    try:
        client = TestClient(app)
        response = client.post(
            "/api/auth/login", json={"username": "admin", "password": "context7"}
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_verify_turnstile_returns_false_on_network_error(monkeypatch):
    from app.services import turnstile_service

    class _BoomClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(turnstile_service.httpx, "AsyncClient", _BoomClient)

    result = asyncio.run(
        turnstile_service.verify_turnstile("tok", secret="s", remote_ip="1.2.3.4")
    )

    assert result is False
