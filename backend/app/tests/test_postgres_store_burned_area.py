from __future__ import annotations

import contextlib


class FakeCursor:
    def __init__(self, fetchall_result=None, fetchone_result=None) -> None:
        self._fetchall_result = fetchall_result or []
        self._fetchone_result = fetchone_result
        self.executed: list[tuple[str, object]] = []
        self.executemany_calls: list[tuple[str, list]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params=()) -> None:
        self.executed.append((query, params))

    def executemany(self, query: str, params_list) -> None:
        self.executemany_calls.append((query, list(params_list)))

    def fetchall(self):
        return self._fetchall_result

    def fetchone(self):
        return self._fetchone_result


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


def _store_with_fake_cursor(monkeypatch, **cursor_kwargs):
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    cursor = FakeCursor(**cursor_kwargs)

    @contextlib.contextmanager
    def fake_connection():
        yield FakeConnection(cursor)

    monkeypatch.setattr(store, "connection", fake_connection)
    return store, cursor


def test_upsert_burned_area_summary_writes_rows(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch)

    rows = [
        {"polygon_metadata_id": 1, "layer_key": "PS_FEB_26", "year": 2026, "month": 4, "burned_area_ha": 12.5},
        {"polygon_metadata_id": 2, "layer_key": "PS_FEB_26", "year": 2026, "month": 4, "burned_area_ha": 0.0},
    ]

    count = store.upsert_burned_area_summary(rows)

    assert count == 2
    assert len(cursor.executemany_calls) == 1
    query, params = cursor.executemany_calls[0]
    assert "INSERT INTO burned_area_summary" in query
    assert "ON CONFLICT (polygon_metadata_id, year, month)" in query
    assert params[0] == (1, "PS_FEB_26", 2026, 4, 12.5, "MODIS/061/MCD64A1")


def test_upsert_burned_area_summary_empty_is_noop(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    assert store.upsert_burned_area_summary([]) == 0


def test_read_burned_area_summary_filters_by_year_and_month(monkeypatch) -> None:
    fake_rows = [
        {"polygon_metadata_id": 1, "layer_key": "PS_FEB_26", "year": 2026, "month": 4, "burned_area_ha": 5.0}
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.read_burned_area_summary(year=2026, month=4)

    assert result == fake_rows
    query, params = cursor.executed[0]
    assert "year = %s" in query
    assert "month = %s" in query
    assert params == [2026, 4]


def test_latest_burned_area_period_returns_none_when_empty(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result=None)
    assert store.latest_burned_area_period() is None


def test_latest_burned_area_period_returns_tuple(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"year": 2026, "month": 4})
    assert store.latest_burned_area_period() == (2026, 4)
