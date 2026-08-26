"""Regresi konfigurasi CORS: daftar method/header eksplisit tidak boleh
memutus preflight untuk header yang benar-benar dipakai frontend
(`Authorization`, `Content-Type`, `X-Admin-Key`)."""

from fastapi.testclient import TestClient

from app.core.config import get_settings


def _preflight(client: TestClient, request_headers: str):
    return client.options(
        "/api/hotspots",
        headers={
            "Origin": "https://etaseneu.ditpps.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": request_headers,
        },
    )


def test_cors_preflight_allows_authorization_header(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("FRONTEND_ORIGIN", "https://etaseneu.ditpps.com")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = _preflight(client, "authorization, content-type")

        assert resp.status_code == 200
        allow = resp.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allow
        assert "content-type" in allow
        assert (
            resp.headers.get("access-control-allow-origin")
            == "https://etaseneu.ditpps.com"
        )
    finally:
        get_settings.cache_clear()


def test_cors_preflight_allows_x_admin_key_header(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("FRONTEND_ORIGIN", "https://etaseneu.ditpps.com")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = _preflight(client, "x-admin-key")

        assert resp.status_code == 200
        assert "x-admin-key" in resp.headers.get("access-control-allow-headers", "").lower()
    finally:
        get_settings.cache_clear()
