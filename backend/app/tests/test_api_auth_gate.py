"""Gate baca opsional `API_REQUIRE_AUTH` (core/auth.require_session_if_enabled).

Tidak menyentuh Postgres produksi: hanya hit `/api/scheduler/status`
(murni settings + metrik in-memory), `/api/health`, `/api/metrics`. Properti
"router admin tidak ketumpuk gate baca" diuji secara struktural lewat
`app.routes` -- tanpa mengeksekusi endpoint admin yang berefek samping.
"""

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.core.auth import issue_token, require_session_if_enabled
from app.core.config import get_settings


@pytest.fixture
def make_app(monkeypatch):
    from app.main import create_app

    def _make(flag: str):
        monkeypatch.setenv("API_REQUIRE_AUTH", flag)
        monkeypatch.setenv("AUTH_JWT_SECRET", "gate-test-secret-min-32-bytes-long!!")
        get_settings.cache_clear()
        return create_app()

    yield _make
    get_settings.cache_clear()


def test_read_endpoint_public_when_flag_off(make_app):
    client = TestClient(make_app("false"))
    assert client.get("/api/scheduler/status").status_code == 200


def test_read_endpoint_401_when_flag_on_and_no_token(make_app):
    client = TestClient(make_app("true"))
    assert client.get("/api/scheduler/status").status_code == 401


def test_read_endpoint_200_when_flag_on_with_valid_token(make_app):
    client = TestClient(make_app("true"))
    token = issue_token(user_id=1, username="admin", role="admin")
    resp = client.get(
        "/api/scheduler/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


def test_health_always_public_even_when_flag_on(make_app):
    client = TestClient(make_app("true"))
    assert client.get("/api/health").status_code == 200


def test_metrics_always_public_even_when_flag_on(make_app):
    client = TestClient(make_app("true"))
    assert client.get("/api/metrics").status_code == 200


def _route_calls(app, method: str, path: str) -> set:
    """Kumpulkan semua callable dependency (rekursif) pada satu route."""
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path and method in route.methods:
            seen = set()
            stack = list(route.dependant.dependencies)
            while stack:
                dep = stack.pop()
                if dep.call is not None:
                    seen.add(dep.call)
                stack.extend(dep.dependencies)
            return seen
    raise AssertionError(f"route {method} {path} tidak ditemukan")


def test_read_route_has_gate_but_admin_route_does_not(make_app):
    app = make_app("true")

    hotspots_calls = _route_calls(app, "GET", "/api/hotspots")
    assert require_session_if_enabled in hotspots_calls

    sync_calls = _route_calls(app, "POST", "/api/scheduler/sync")
    assert require_session_if_enabled not in sync_calls
