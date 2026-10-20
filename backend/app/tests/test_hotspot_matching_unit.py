"""Tes unit (tanpa database) untuk mesin pencocokan hotspot <-> poligon dan jalur ingest.

Perilaku spasial yang sebenarnya diuji terhadap PostGIS di ``test_hotspot_matching_integration.py``.
Di sini: bentuk SQL, pemecahan jendela waktu, urutan relasi->ringkasan, penanganan error, dan dua
bug produksi (``layer.name`` pada dict, status persistensi scheduler).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc


# ----------------------------------------------------------------------------- SQL bersama


def test_pairs_cte_uses_covers_on_valid_geometry_and_no_layer_equality() -> None:
    from app.services.postgres_store._hotspot_match import pairs_cte_sql

    sql = pairs_cte_sql()
    assert "ST_Covers(p.analysis_geometry, obs.geom)" in sql
    assert "obs.geom && p.geometry" in sql  # prefilter indeks GiST
    assert "ST_MakeValid" in sql and "ST_IsValid" in sql
    assert "AS MATERIALIZED" in sql  # validasi geometri sekali per poligon
    assert "p.is_active = TRUE" in sql
    # label layer observasi bukan syarat spasial
    assert "obs.layer_key" not in sql
    assert "p.layer_key = obs" not in sql


def test_summary_sql_groups_by_wib_year_and_counts_distinct_observations() -> None:
    from app.services.postgres_store import PostgresStore

    captured: list[str] = []

    class _Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, query, params=None):
            captured.append(query)

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _Cursor()

        def transaction(self):
            return self

    store = PostgresStore("postgresql://demo")
    store.connection = lambda: _Conn()  # type: ignore[method-assign]
    store.rebuild_polygon_hotspot_summary([7, 7, 9])

    joined = "\n".join(captured)
    assert "pg_advisory_xact_lock" in joined  # pembangunan ringkasan diserialkan
    assert "DELETE FROM polygon_hotspot_summary" in joined
    assert "AT TIME ZONE %(tz)s" in joined  # tahun menurut Asia/Jakarta, bukan zona sesi
    assert "COUNT(DISTINCT observation_id)" in joined
    assert "ST_Covers(p.analysis_geometry, obs.geom)" in joined
    assert "hotspot_polygon_relation" not in joined  # ringkasan tidak bergantung pada kelengkapan relasi


# ----------------------------------------------------------------------------- jendela waktu


def test_iter_windows_splits_ranges_without_gaps_or_overlap() -> None:
    from app.services.postgres_store._hotspot_match import _iter_windows

    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 4, 1, tzinfo=UTC)
    windows = list(_iter_windows(start, end, 31))
    assert windows[0][0] == start and windows[-1][1] == end
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:]))
    assert all(w[1] - w[0] <= timedelta(days=31) for w in windows)
    assert list(_iter_windows(end, start, 31)) == []


def test_detected_at_window_covers_all_points_in_utc_and_is_exclusive_at_end() -> None:
    from app.services.hotspot_service import _detected_at_window

    hotspots = [
        {"detected_at": "2026-10-10T06:00:00Z"},
        {"detected_at": datetime(2026, 10, 10, 13, 30, tzinfo=timezone(timedelta(hours=7)))},  # 06:30Z
        {"detected_at": "tanggal-rusak"},
        {"detected_at": None},
    ]
    start, end = _detected_at_window(hotspots)
    assert start == datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 10, 6, 30, 1, tzinfo=UTC)  # akhir + 1 detik (batas atas eksklusif)
    assert _detected_at_window([{"detected_at": None}]) is None


def test_naive_window_is_rejected_before_touching_database() -> None:
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://demo")
    with pytest.raises(ValueError):
        store.reconcile_hotspot_polygon_relations(start_at=datetime(2026, 1, 1), end_at=datetime(2026, 1, 2, tzinfo=UTC))


# ----------------------------------------------------------------------------- urutan relasi -> ringkasan


def test_summary_is_not_rebuilt_when_relation_reconcile_fails() -> None:
    from app.services.postgres_store._hotspot_match import HotspotRelationSyncError, _HotspotMatchMixin

    class _Store(_HotspotMatchMixin):
        rebuilt: list[list[int]] = []

        def reconcile_hotspot_polygon_relations(self, **_kwargs):
            raise HotspotRelationSyncError("gagal", {"chunks": 0})

        def rebuild_polygon_hotspot_summary(self, polygon_ids, **_kwargs):
            self.rebuilt.append(list(polygon_ids))
            return len(polygon_ids)

    store = _Store()
    with pytest.raises(HotspotRelationSyncError):
        store.sync_hotspot_relations_and_summaries(start_at=datetime(2026, 1, 1, tzinfo=UTC), end_at=datetime(2026, 1, 2, tzinfo=UTC))
    assert store.rebuilt == []


def test_summary_failure_after_relations_is_raised_not_swallowed() -> None:
    from app.services.postgres_store._hotspot_match import HotspotRelationSyncError, _HotspotMatchMixin

    class _Store(_HotspotMatchMixin):
        def reconcile_hotspot_polygon_relations(self, **_kwargs):
            return {"inserted": 3, "updated": 0, "spatial_pairs": 3, "polygon_ids": [1, 2]}

        def rebuild_polygon_hotspot_summary(self, polygon_ids, **_kwargs):
            raise RuntimeError("timeout")

    with pytest.raises(HotspotRelationSyncError) as excinfo:
        _Store().sync_hotspot_relations_and_summaries(
            start_at=datetime(2026, 1, 1, tzinfo=UTC), end_at=datetime(2026, 1, 2, tzinfo=UTC)
        )
    assert excinfo.value.progress["inserted"] == 3  # relasi yang sudah tersimpan tetap dilaporkan


# ----------------------------------------------------------------------------- jalur ingest


class _Store:
    enabled = True

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, object]] = []

    def upsert_hotspot_observations(self, hotspots) -> None:
        self.calls.append(("upsert", len(hotspots)))

    def sync_hotspot_relations_and_summaries(self, *, start_at, end_at):
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append(("sync", (start_at, end_at)))
        return {"inserted": 4, "updated": 1, "summary_rebuilt": 2}


def _service(store):
    from app.services.hotspot_service import HotspotService

    service = HotspotService.__new__(HotspotService)
    service.postgres_store = store
    return service


def test_persist_syncs_one_window_covering_all_hotspots_regardless_of_polygon_metadata() -> None:
    store = _Store()
    hotspots = [
        {"detected_at": "2026-10-10T06:00:00Z", "latitude": 1.0, "longitude": 100.0},
        {"detected_at": "2026-10-10T09:00:00Z", "latitude": 1.0, "longitude": 110.0, "layer_id": "perimeter_threat"},
    ]
    outcome = _service(store)._persist_observations_and_relations(hotspots)

    assert [name for name, _ in store.calls] == ["upsert", "sync"]  # observasi dulu, baru relasi
    window = store.calls[1][1]
    assert window == (datetime(2026, 10, 10, 6, 0, tzinfo=UTC), datetime(2026, 10, 10, 9, 0, 1, tzinfo=UTC))
    assert outcome == {"ok": True, "relations_inserted": 4, "relations_updated": 1, "summaries_rebuilt": 2}


def test_persist_failure_is_logged_with_traceback_and_reported(caplog) -> None:
    store = _Store(fail=True)
    with caplog.at_level("ERROR", logger="hotspot.service"):
        outcome = _service(store)._persist_observations_and_relations(
            [{"detected_at": "2026-10-10T06:00:00Z", "latitude": 1.0, "longitude": 100.0}]
        )
    assert outcome == {"ok": False}
    assert any("HOTSPOT PERSIST" in r.message and r.exc_info for r in caplog.records)


def test_persist_does_not_reconcile_when_observation_upsert_fails() -> None:
    store = _Store()

    def broken_upsert(_hotspots):
        raise RuntimeError("tabel terkunci")

    store.upsert_hotspot_observations = broken_upsert  # type: ignore[method-assign]
    outcome = _service(store)._persist_observations_and_relations(
        [{"detected_at": "2026-10-10T06:00:00Z", "latitude": 1.0, "longitude": 100.0}]
    )
    assert outcome == {"ok": False}
    assert store.calls == []  # tidak ada sync relasi atas observasi yang tidak tersimpan


def test_nasa_fetch_error_handler_does_not_crash_on_dict_layers() -> None:
    """Regresi produksi 19 Okt 2026: ``layer.name`` pada dict menggagalkan seluruh siklus sinkron."""
    from app.models.query import HotspotQuery

    class _Layers:
        def spatial_layers_for_ids(self, ids):
            return [{"id": "psagustus2026", "name": "PS", "geojson": {"features": []}}]

    class _Cache:
        def read(self, key):
            return None

        def write(self, key, value):
            pass

    class _Disabled:
        enabled = False

    service = _service(_Disabled())
    service.layer_service = _Layers()
    service.cache_service = _Cache()

    async def failing_archive(**_kwargs):
        raise RuntimeError("ReadError: koneksi FIRMS terputus")

    service._read_or_warm_layer_year_archive = failing_archive  # type: ignore[method-assign]
    query = HotspotQuery(
        start_at=datetime(2026, 10, 10, tzinfo=UTC),
        end_at=datetime(2026, 10, 11, tzinfo=UTC),
        satellites=["VIIRS_SNPP"],
        active_layers=["psagustus2026"],
    )
    result = asyncio.run(service.fetch_filtered_hotspots(query, bypass_cache=True))
    assert result["count"] == 0  # error FIRMS dicatat sebagai warning, bukan menjatuhkan siklus


# ----------------------------------------------------------------------------- scheduler


def test_scheduler_marks_cycle_failed_when_persistence_failed(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.services import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "get_settings", lambda: SimpleNamespace(nasa_firms_api_key="test-key"))

    class _Layer:
        id = "sample_area"

    class _LayerService:
        def list_layers(self):
            return [_Layer()]

    class _PgStore:
        enabled = False

    class _Service:
        layer_service = _LayerService()
        postgres_store = _PgStore()

        async def fetch_filtered_hotspots(self, query, bypass_cache: bool = False):
            return {"count": 12, "hotspots": [], "stats": {}, "persistence": {"ok": False}}

    scheduler_module._consecutive_failures = 0
    result = asyncio.run(scheduler_module._run_sync_cycle(_Service()))

    assert result["success"] is False and result["persistence_ok"] is False
    assert scheduler_module._consecutive_failures == 1  # terlihat di metrik Prometheus yang sudah ada


def test_scheduler_cycle_stays_successful_when_persistence_ok(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.services import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "get_settings", lambda: SimpleNamespace(nasa_firms_api_key="test-key"))

    class _Layer:
        id = "sample_area"

    class _LayerService:
        def list_layers(self):
            return [_Layer()]

    class _PgStore:
        enabled = False

    class _Service:
        layer_service = _LayerService()
        postgres_store = _PgStore()

        async def fetch_filtered_hotspots(self, query, bypass_cache: bool = False):
            return {"count": 3, "hotspots": [], "stats": {}, "persistence": {"ok": True}}

    scheduler_module._consecutive_failures = 5
    result = asyncio.run(scheduler_module._run_sync_cycle(_Service()))
    assert result["success"] is True and scheduler_module._consecutive_failures == 0
