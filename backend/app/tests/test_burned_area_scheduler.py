from __future__ import annotations

from datetime import datetime, timezone

import pytest


def test_lookback_periods_returns_n_months_before_current_newest_first() -> None:
    from app.services.burned_area_scheduler import _lookback_periods

    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    assert _lookback_periods(now, 3) == [(2026, 7), (2026, 6), (2026, 5)]


def test_lookback_periods_rolls_over_year_boundary() -> None:
    from app.services.burned_area_scheduler import _lookback_periods

    now = datetime(2026, 2, 15, tzinfo=timezone.utc)
    assert _lookback_periods(now, 3) == [(2026, 1), (2025, 12), (2025, 11)]


def test_lookback_periods_zero_months_is_empty() -> None:
    from app.services.burned_area_scheduler import _lookback_periods

    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    assert _lookback_periods(now, 0) == []


class _FakePostgresStore:
    enabled = False

    def save_burned_area_scheduler_state(self, **kwargs):
        pass


class _FakeBurnedAreaService:
    def __init__(self, *, enabled: bool, outcomes: dict[tuple[int, int], object]) -> None:
        self.enabled = enabled
        self.postgres_store = _FakePostgresStore()
        self._outcomes = outcomes
        self.calls: list[tuple[int, int]] = []

    def refresh_burned_area(self, year: int, month: int, layer_keys=None):
        self.calls.append((year, month))
        outcome = self._outcomes[(year, month)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_run_burned_area_cycle_skips_when_gee_not_configured() -> None:
    import asyncio
    from app.services.burned_area_scheduler import run_burned_area_cycle

    service = _FakeBurnedAreaService(enabled=False, outcomes={})

    result = asyncio.run(run_burned_area_cycle(service, 3))

    assert result == {"success": False, "skipped": True, "reason": "gee_not_configured"}
    assert service.calls == []


def test_run_burned_area_cycle_calls_refresh_for_each_lookback_month() -> None:
    import asyncio
    from app.services.burned_area_scheduler import run_burned_area_cycle

    service = _FakeBurnedAreaService(
        enabled=True,
        outcomes={
            (2026, 7): {"year": 2026, "month": 7, "polygons_checked": 10, "computed": 10},
            (2026, 6): {"year": 2026, "month": 6, "polygons_checked": 10, "computed": 10},
            (2026, 5): {"year": 2026, "month": 5, "polygons_checked": 10, "computed": 10},
        },
    )

    result = asyncio.run(run_burned_area_cycle(service, 3))

    assert result["success"] is True
    assert len(result["months"]) == 3
    assert {(m["year"], m["month"]) for m in result["months"]} == {(2026, 7), (2026, 6), (2026, 5)}
    assert len(service.calls) == 3


def test_run_burned_area_cycle_continues_after_one_month_fails() -> None:
    """Satu bulan gagal (mis. error jaringan sesaat ke Earth Engine) tidak
    boleh menggagalkan bulan lain -- tiap bulan harus tetap dicoba."""
    import asyncio
    from app.services.burned_area_scheduler import run_burned_area_cycle

    service = _FakeBurnedAreaService(
        enabled=True,
        outcomes={
            (2026, 7): RuntimeError("EE timeout"),
            (2026, 6): {"year": 2026, "month": 6, "polygons_checked": 10, "computed": 10},
            (2026, 5): {"year": 2026, "month": 5, "polygons_checked": 10, "computed": 10},
        },
    )

    result = asyncio.run(run_burned_area_cycle(service, 3))

    assert result["success"] is False
    assert len(service.calls) == 3, "bulan lain harus tetap dicoba walau satu bulan gagal"
    failed = next(m for m in result["months"] if m["year"] == 2026 and m["month"] == 7)
    assert "EE timeout" in failed["error"]
    succeeded = [m for m in result["months"] if "error" not in m]
    assert len(succeeded) == 2


def test_record_run_result_resets_failures_on_success() -> None:
    from app.services import burned_area_scheduler as module

    module._consecutive_failures = 3
    service = _FakeBurnedAreaService(enabled=True, outcomes={})

    module._record_run_result({"success": True, "months": []}, service)

    assert module._consecutive_failures == 0
    assert module._last_successful_run_at is not None


def test_record_run_result_increments_failures_on_failure() -> None:
    from app.services import burned_area_scheduler as module

    module._consecutive_failures = 0
    service = _FakeBurnedAreaService(enabled=True, outcomes={})

    module._record_run_result({"success": False, "months": []}, service)

    assert module._consecutive_failures == 1


def test_record_run_result_skipped_does_not_count_as_failure() -> None:
    """Skip karena GEE belum dikonfigurasi bukan kegagalan operasional --
    jangan sampai menambah consecutive_failures dan memicu alert palsu."""
    from app.services import burned_area_scheduler as module

    module._consecutive_failures = 0
    service = _FakeBurnedAreaService(enabled=False, outcomes={})

    module._record_run_result({"success": False, "skipped": True, "reason": "gee_not_configured"}, service)

    assert module._consecutive_failures == 0


def test_burned_area_scheduler_status_endpoint(monkeypatch) -> None:
    import asyncio
    from app.api import scheduler as scheduler_api
    from app.services import burned_area_scheduler as module

    monkeypatch.setattr(module, "bootstrap_burned_area_scheduler_metrics", lambda *a, **k: None)
    module._last_run_result = {"success": True, "months": []}
    module._last_run_at = datetime(2026, 8, 18, tzinfo=timezone.utc)
    module._last_successful_run_at = module._last_run_at
    module._consecutive_failures = 0

    payload = asyncio.run(scheduler_api.burned_area_scheduler_status())

    assert payload["last_run_status"] == "success"
    assert payload["last_run_at"] == "2026-08-18T00:00:00+00:00"


def test_burned_area_scheduler_sync_requires_admin_key(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.main import create_app

    client = TestClient(create_app())
    response = client.post("/api/scheduler/burned-area/sync")
    assert response.status_code in (401, 503)


def test_burned_area_scheduler_sync_calls_run_cycle(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from app.core.auth import require_admin_key
    from app.main import create_app
    from app.services import burned_area_scheduler as module

    async def fake_run_cycle(service, lookback_months):
        return {"success": True, "months": [], "checked_at": "2026-08-18T00:00:00+00:00"}

    monkeypatch.setattr(module, "run_burned_area_cycle", fake_run_cycle)

    app = create_app()
    app.dependency_overrides[require_admin_key] = lambda: None
    client = TestClient(app)

    response = client.post("/api/scheduler/burned-area/sync")

    assert response.status_code == 200
    body = response.json()
    assert body["triggered"] is True
    assert body["success"] is True
