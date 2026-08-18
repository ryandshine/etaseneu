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
    # Kolom terakhir = geometry (NULL kalau baris tidak membawa geometry_geojson).
    assert params[0] == (1, "PS_FEB_26", 2026, 4, 12.5, "MODIS/061/MCD64A1", None)


def test_upsert_burned_area_summary_serializes_geometry(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch)

    geom = {"type": "MultiPolygon", "coordinates": [[[[109.0, 0.4], [109.1, 0.4], [109.1, 0.5], [109.0, 0.4]]]]}
    store.upsert_burned_area_summary(
        [
            {
                "polygon_metadata_id": 43617,
                "layer_key": "PS_FEB_26",
                "year": 2026,
                "month": 1,
                "burned_area_ha": 149.0,
                "geometry_geojson": geom,
            }
        ]
    )

    _query, params = cursor.executemany_calls[0]
    import json as _json

    assert _json.loads(params[0][6]) == geom


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


def test_burned_area_unique_ha_uses_st_union(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"ha": 124.1})

    result = store.burned_area_unique_ha([43617], year=2026)

    assert result == 124.1
    query, params = cursor.executed[0]
    assert "ST_Union(geometry)" in query
    assert params == [[43617], 2026]


def test_burned_area_unique_ha_query_combines_geometry_and_fallback(monkeypatch) -> None:
    """Regresi: versi awal cuma ST_Union tanpa GROUP BY per-poligon, jadi
    poligon dengan campuran bulan-ada-geometry dan bulan-tanpa-geometry
    diam-diam kehilangan kontribusi bulan yang tanpa geometry (bukan dobel
    hitung, tapi kurang hitung). Query sekarang harus menggabungkan
    keduanya per poligon (FILTER WHERE geometry IS NOT NULL / IS NULL)
    sebelum dijumlah lintas poligon."""
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"ha": 149.44})

    store.burned_area_unique_ha([49634])

    query, _params = cursor.executed[0]
    assert "GROUP BY polygon_metadata_id" in query
    assert "FILTER (WHERE geometry IS NOT NULL)" in query
    assert "FILTER (WHERE geometry IS NULL)" in query


def test_burned_area_by_skema_groups_and_filters(monkeypatch) -> None:
    fake_rows = [
        {"skema": "PPHKm", "kps_count": 10, "total_ha": 2413.9},
        {"skema": "PPHD", "kps_count": 10, "total_ha": 1866.5},
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.burned_area_by_skema(year=2026, layer_keys=["PS_FEB_26"])

    assert result == [
        {"skema": "PPHKm", "kps_count": 10, "total_ha": 2413.9},
        {"skema": "PPHD", "kps_count": 10, "total_ha": 1866.5},
    ]
    query, params = cursor.executed[0]
    assert "GROUP BY b.polygon_metadata_id, p.skema" in query
    assert "GROUP BY skema" in query
    assert params == [2026, ["PS_FEB_26"]]


def test_burned_area_unique_ha_returns_none_without_geometry(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"ha": None})
    assert store.burned_area_unique_ha([43617]) is None


def test_burned_area_unique_ha_empty_polygon_list(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    assert store.burned_area_unique_ha([]) is None


def test_latest_burned_area_period_returns_none_when_empty(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result=None)
    assert store.latest_burned_area_period() is None


def test_latest_burned_area_period_returns_tuple(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"year": 2026, "month": 4})
    assert store.latest_burned_area_period() == (2026, 4)


def test_save_burned_area_scheduler_state_upserts_single_row(monkeypatch) -> None:
    from datetime import datetime, timezone

    store, cursor = _store_with_fake_cursor(monkeypatch)

    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    store.save_burned_area_scheduler_state(
        last_run_at=now,
        last_successful_run_at=now,
        last_run_result={"success": True, "months": []},
        consecutive_failures=0,
    )

    query, params = cursor.executed[-1]
    assert "INSERT INTO burned_area_scheduler_state" in query
    assert "ON CONFLICT (id) DO UPDATE" in query
    assert params[0] == now
    assert params[1] == now
    assert params[3] == 0


def test_read_burned_area_scheduler_state_returns_none_when_no_row(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result=None)
    assert store.read_burned_area_scheduler_state() is None


def test_read_burned_area_scheduler_state_parses_row(monkeypatch) -> None:
    import json as _json

    store, _cursor = _store_with_fake_cursor(
        monkeypatch,
        fetchone_result={
            "last_run_at": "2026-08-18T00:00:00+00:00",
            "last_successful_run_at": "2026-08-18T00:00:00+00:00",
            "last_run_result": _json.dumps({"success": True}),
            "consecutive_failures": 0,
        },
    )

    result = store.read_burned_area_scheduler_state()

    assert result["last_run_result"] == {"success": True}
    assert result["consecutive_failures"] == 0
