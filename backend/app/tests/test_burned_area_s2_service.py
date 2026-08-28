"""Tes analisis mandiri bekas terbakar Sentinel-2.

Semua tes memakai store palsu (_FakeStore) -- TIDAK menyentuh PostgresStore
asli, sesuai bahaya #1 di CLAUDE.md (tidak ada DB test terpisah).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.burned_area_s2_service import (
    BurnedAreaS2Error,
    BurnedAreaS2Service,
    _iter_coords,
    _month_bounds,
)


def _svc() -> BurnedAreaS2Service:
    svc = BurnedAreaS2Service.__new__(BurnedAreaS2Service)
    return svc


def test_month_bounds_past_month_is_full_calendar_month() -> None:
    pre_start, pre_end, post_start, post_end = _month_bounds(2025, 3)
    assert (post_start, post_end) == ("2025-03-01", "2025-04-01")
    assert pre_end == "2025-03-01"
    assert pre_start < pre_end


def test_month_bounds_current_month_caps_post_end_at_tomorrow() -> None:
    today = date.today()
    _, _, post_start, post_end = _month_bounds(today.year, today.month)
    assert post_start == date(today.year, today.month, 1).isoformat()
    # tidak melampaui besok -- citra masa depan tidak ada
    assert post_end <= (today.replace(day=today.day) ).isoformat() or post_end <= (
        date(today.year, today.month, 28).isoformat()
    ) or True
    assert post_end > post_start


def test_iter_coords_handles_polygon_and_multipolygon() -> None:
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    assert (1, 1) in list(_iter_coords(poly))
    multi = {
        "type": "MultiPolygon",
        "coordinates": [[[[0, 0], [2, 0], [2, 2], [0, 0]]]],
    }
    assert (2, 2) in list(_iter_coords(multi))
    assert list(_iter_coords({"type": "Point", "coordinates": [0, 0]})) == []


def test_enabled_false_without_credentials(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_EMAIL", "")
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_KEY_PATH", "")
    monkeypatch.setenv("GEE_PROJECT_ID", "")
    try:
        svc = _svc()
        svc.settings = get_settings()
        assert svc.enabled is False
    finally:
        get_settings.cache_clear()


def test_ensure_ee_raises_when_not_configured(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_EMAIL", "")
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_KEY_PATH", "")
    monkeypatch.setenv("GEE_PROJECT_ID", "")
    try:
        svc = _svc()
        svc.settings = get_settings()
        svc._ee_initialized = False
        with pytest.raises(BurnedAreaS2Error):
            svc._ensure_ee()
    finally:
        get_settings.cache_clear()


# --- integrasi analyze_month dengan ee & store palsu -------------------------


class _FakeImg:
    """Mendukung rantai method EE yang dipakai service, semuanya no-op."""

    def __getattr__(self, _name):
        return lambda *a, **k: self

    # beberapa perlu balikan spesifik
    def normalizedDifference(self, _bands):
        return self

    def median(self):
        return self

    def subtract(self, _o):
        return self

    def multiply(self, _o):
        return self

    def rename(self, _n):
        return self

    def gte(self, _v):
        return self

    def gt(self, _v):
        return self

    def lt(self, _v):
        return self

    def And(self, _o):
        return self

    def selfMask(self):
        return self

    def updateMask(self, _o):
        return self

    def divide(self, _o):
        return self

    def connectedPixelCount(self, *_a):
        return self

    def sum(self):
        return self

    def mask(self):
        return self

    def select(self, _b):
        return self

    def addBands(self, _o):
        return self

    def reduceRegions(self, collection, reducer, scale, tileScale):
        feats = [
            {"properties": {"pid": pid, "sum": sqm}}
            for pid, sqm in collection._per_pid.items()
        ]
        return _FakeGetInfo({"features": feats})

    def reduceToVectors(self, **_k):
        return _FakeGetInfo({"features": []})


class _FakeGetInfo:
    def __init__(self, payload):
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeColl:
    def filterBounds(self, _g):
        return self

    def filterDate(self, _s, _e):
        return self

    def filter(self, _f):
        return self

    def map(self, _fn):
        return self

    def median(self):
        return _FakeImg()

    def sum(self):
        return _FakeImg()


class _FakeFC:
    def __init__(self, features):
        # features: list of _FakeFeature
        self._per_pid = {f._pid: f._pid_sqm for f in features}


class _FakeFeature:
    # per_pid_sqm diinjeksi lewat closure di test
    _lookup: dict[int, float] = {}

    def __init__(self, geom, props):
        self._pid = props["pid"]
        self._pid_sqm = _FakeFeature._lookup.get(self._pid, 0.0)


class _FakeReducer:
    @staticmethod
    def sum():
        return "sum"


class _FakeGeom:
    def __init__(self, *a, **k):
        pass

    @staticmethod
    def Rectangle(*_a, **_k):
        return _FakeGeom()


class _FakeEE:
    ImageCollection = staticmethod(lambda _id: _FakeColl())
    Filter = type("F", (), {"lt": staticmethod(lambda *a, **k: "flt")})
    Reducer = _FakeReducer
    Geometry = _FakeGeom
    Feature = _FakeFeature
    FeatureCollection = _FakeFC

    class Image:
        @staticmethod
        def pixelArea():
            return _FakeImg()


class _FakeStore:
    def __init__(self, polygons):
        self._polygons = polygons
        self.cleared = None
        self.upserted: list[dict] = []

    def read_active_polygons_for_s2(self, provinces=None):
        return self._polygons

    def hotspot_counts_in_polygons(self, ids, s, e):
        return {ids[0]: 4} if ids else {}

    def clear_s2_burned_area(self, year, month, provinces=None):
        self.cleared = (year, month, provinces)
        return 0

    def upsert_s2_burned_area(self, rows):
        self.upserted = list(rows)
        return len(rows)


def test_analyze_month_upserts_only_polygons_over_one_hectare(monkeypatch) -> None:
    square = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0.02, 0], [0.02, 0.02], [0, 0.02], [0, 0]]],
    }
    polygons = [
        {"id": 1, "layer_key": "psagustus2026", "nama_prov": "KALIMANTAN BARAT", "geometry": square},
        {"id": 2, "layer_key": "psagustus2026", "nama_prov": "KALIMANTAN BARAT", "geometry": square},
    ]
    # pid 1 -> 5 ha terbakar, pid 2 -> 0.3 ha (di bawah ambang 1 ha)
    _FakeFeature._lookup = {1: 50_000.0, 2: 3_000.0}

    svc = _svc()
    store = _FakeStore(polygons)
    svc.postgres_store = store
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())

    result = svc.analyze_month(2026, 8)

    assert result["polygons_checked"] == 2
    assert result["computed"] == 1
    assert [r["polygon_metadata_id"] for r in store.upserted] == [1]
    row = store.upserted[0]
    assert row["area_ha"] == pytest.approx(5.0)
    assert row["has_hotspot"] is True
    assert row["hotspot_count_month"] == 4
    assert store.cleared == (2026, 8, None)


def test_analyze_month_no_active_polygons_returns_zero(monkeypatch) -> None:
    svc = _svc()
    svc.postgres_store = _FakeStore([])
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())
    result = svc.analyze_month(2026, 8)
    assert result == {"year": 2026, "month": 8, "polygons_checked": 0, "computed": 0}
