import asyncio
import json
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]


async def _request_health() -> tuple[int, dict]:
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
        "path": "/api/health",
        "raw_path": b"/api/health",
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


def test_config_uses_absolute_backend_env_path() -> None:
    from app.core import config

    assert config.ENV_FILE == BACKEND_DIR / ".env"
    assert config.ENV_FILE.is_absolute()


def test_create_app_uses_lazy_cached_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    monkeypatch.setenv("APP_NAME", "Task 1 Test App")
    try:
        app = create_app()
        settings = get_settings()

        assert app.title == "Task 1 Test App"
        assert settings.app_name == "Task 1 Test App"
        assert get_settings() is settings
    finally:
        get_settings.cache_clear()


def test_health_returns_ok() -> None:
    status, payload = asyncio.run(_request_health())

    assert status == 200
    assert payload == {"status": "ok"}


def test_app_imports_without_optional_psycopg_dependency() -> None:
    from app.main import create_app

    app = create_app()

    assert app.title


def test_scheduler_start_is_deferred_until_after_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main as main_module

    created_tasks = []

    class DummyHandle:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

    class DummyLoop:
        def __init__(self) -> None:
            self.callback = None
            self.delay = None

        def call_later(self, delay, callback):
            self.delay = delay
            self.callback = callback
            return DummyHandle()

    dummy_loop = DummyLoop()

    monkeypatch.setattr(main_module.asyncio, "get_running_loop", lambda: dummy_loop)
    monkeypatch.setattr(
        main_module.asyncio,
        "create_task",
        lambda coro: created_tasks.append(coro) or "scheduler-task",
    )

    handle, holder = main_module._defer_scheduler_start(
        schedule_hours=[0, 3, 6],
        fallback_interval_hours=3.0,
    )

    assert handle is not None
    assert holder["task"] is None
    assert dummy_loop.delay == 1.0
    assert dummy_loop.callback is not None

    dummy_loop.callback()

    assert holder["task"] == "scheduler-task"
    assert len(created_tasks) == 1
    created_tasks[0].close()
