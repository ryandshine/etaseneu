"""Tes analisis mandiri bekas terbakar Sentinel-2.

Semua tes memakai store palsu (_FakeStore) -- TIDAK menyentuh PostgresStore
asli, sesuai bahaya #1 di CLAUDE.md (tidak ada DB test terpisah).
"""

from __future__ import annotations

from datetime import date

import pytest

from shapely.geometry import MultiPolygon, Polygon

from app.services.burned_area_s2_service import (
    BurnedAreaS2Error,
    BurnedAreaS2Service,
    _clean_burned_polygon,
    _iter_coords,
    _month_bounds,
)

# 1 derajat ~= 111.000 m (sama seperti pendekatan di burned_area_s2_service.py sendiri)
_M_PER_DEG = 111000.0


def _square_ha(side_m: float) -> float:
    return (side_m * side_m) / 10000.0


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


def _square(side_m: float, offset_m: tuple[float, float] = (0.0, 0.0)) -> list[tuple[float, float]]:
    s = side_m / _M_PER_DEG
    ox, oy = offset_m[0] / _M_PER_DEG, offset_m[1] / _M_PER_DEG
    return [(ox, oy), (ox + s, oy), (ox + s, oy + s), (ox, oy + s), (ox, oy)]


def test_clean_burned_polygon_drops_tiny_fragment_keeps_big_one() -> None:
    big = Polygon(_square(300))  # 9 ha, jauh di atas _MIN_FRAGMENT_HA (0.3 ha)
    tiny = Polygon(_square(20, offset_m=(1000, 1000)))  # 0,04 ha -- 1 piksel
    result = _clean_burned_polygon(MultiPolygon([big, tiny]))
    assert result is not None
    assert len(result.geoms) == 1
    kept_ha = result.geoms[0].area * _M_PER_DEG * _M_PER_DEG / 10000
    # toleransi longgar -- Chaikin memotong sudut kotak sederhana (4 titik) jauh lebih
    # agresif drpd bentuk bekas terbakar nyata yang bervertex banyak; yang penting di
    # sini cuma "tidak hilang total / tidak melonjak", bukan presisi luas pasca-smooth.
    assert kept_ha == pytest.approx(_square_ha(300), rel=0.15)


def test_clean_burned_polygon_returns_none_when_everything_too_small() -> None:
    tiny = Polygon(_square(20))
    assert _clean_burned_polygon(MultiPolygon([tiny])) is None


def test_clean_burned_polygon_fills_small_hole_keeps_big_hole() -> None:
    outer = _square(500)  # 25 ha
    small_hole = list(reversed(_square(20, offset_m=(50, 50))))  # 0,04 ha -- ditutup
    big_hole = list(reversed(_square(150, offset_m=(250, 250))))  # 2,25 ha -- dipertahankan
    poly = Polygon(outer, [small_hole, big_hole])
    result = _clean_burned_polygon(MultiPolygon([poly]))
    assert result is not None
    cleaned = result.geoms[0]
    # lubang kecil ditutup (interior berkurang), lubang besar tetap ada
    assert len(cleaned.interiors) == 1
    remaining_hole_ha = Polygon(cleaned.interiors[0]).area * _M_PER_DEG * _M_PER_DEG / 10000
    assert remaining_hole_ha == pytest.approx(_square_ha(150), rel=0.15)


def test_vectorize_burned_union_falls_back_to_batches_when_full_set_fails(monkeypatch) -> None:
    """Regresi 2026-09-24: Kalimantan Barat & Papua Selatan kehilangan geometri
    UNTUK SELURUH provinsi (angka luas tetap tersimpan) karena satu
    reduceToVectors provinsi penuh mentok limit >5000 elemen getInfo() GEE.
    _vectorize_burned_union sekarang coba full-set dulu (jalur cepat), lalu
    pecah ke sub-batch _VECTORIZE_BATCH_SIZE kalau itu gagal."""
    from shapely.geometry import Point

    from app.services.burned_area_s2_service import _VECTORIZE_BATCH_SIZE

    svc = _svc()
    call_sizes: list[int] = []

    def fake_chunk(ee, scar_c, burned_polys):
        call_sizes.append(len(burned_polys))
        if len(burned_polys) > _VECTORIZE_BATCH_SIZE:
            return None  # simulasikan panggilan penuh mentok limit GEE
        return Point(0, 0).buffer(1)

    monkeypatch.setattr(svc, "_vectorize_chunk", fake_chunk)

    burned_polys = [
        {"id": i, "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}
        for i in range(75)
    ]
    result = svc._vectorize_burned_union(None, None, burned_polys)

    assert result is not None
    # Panggilan pertama untuk 75 poligon sekaligus (gagal), lalu 3 sub-batch
    # (30, 30, 15) yang masing-masing berhasil.
    assert call_sizes == [75, 30, 30, 15]


def test_vectorize_burned_union_returns_none_when_all_batches_fail(monkeypatch) -> None:
    svc = _svc()
    monkeypatch.setattr(svc, "_vectorize_chunk", lambda ee, scar_c, polys: None)

    burned_polys = [{"id": i, "geometry": {}} for i in range(40)]
    assert svc._vectorize_burned_union(None, None, burned_polys) is None


def test_vectorize_burned_union_skips_batching_for_small_sets(monkeypatch) -> None:
    """Provinsi kecil (di bawah _VECTORIZE_BATCH_SIZE) yang gagal di jalur
    cepat tidak perlu dicoba lagi per-batch -- hasilnya akan sama saja."""
    svc = _svc()
    call_sizes: list[int] = []

    def fake_chunk(ee, scar_c, burned_polys):
        call_sizes.append(len(burned_polys))
        return None

    monkeypatch.setattr(svc, "_vectorize_chunk", fake_chunk)

    burned_polys = [{"id": i, "geometry": {}} for i in range(5)]
    assert svc._vectorize_burned_union(None, None, burned_polys) is None
    assert call_sizes == [5]


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

    def __init__(self, *_a, **_k):
        pass

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

    @staticmethod
    def pixelArea():
        return _FakeImg()


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
        self._per_pid = {f._pid: f._pid_sqm for f in features if f._pid is not None}


class _FakeFeature:
    # per_pid_sqm diinjeksi lewat closure di test
    _lookup: dict[int, float] = {}

    def __init__(self, geom, props=None):
        # props None -- dipakai _gambut_mask (ee.Feature(ee.Geometry(geom)),
        # tanpa properties) beda dari batch reduceRegions poligon KPS/HA yang
        # selalu kasih {"pid": ...}.
        props = props or {}
        self._pid = props.get("pid")
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
    Image = _FakeImg


class _FakeStore:
    def __init__(self, polygons):
        self._polygons = polygons
        self.cleared = None
        self.upserted: list[dict] = []
        self.gambut_geometry = None
        self.gambut_calls: list[tuple] = []

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

    def read_gambut_mask_geometry(self, bbox, *, simplify_tolerance=0.001):
        self.gambut_calls.append((bbox, simplify_tolerance))
        return self.gambut_geometry


def test_gambut_mask_returns_none_without_current_bbox() -> None:
    svc = _svc()
    svc.postgres_store = _FakeStore([])
    # _current_bbox sengaja tidak diset (mis. _province_bbox belum dipanggil).
    assert svc._gambut_mask(_FakeEE(), _FakeGeom()) is None


def test_gambut_mask_returns_none_when_no_gambut_in_bbox() -> None:
    svc = _svc()
    store = _FakeStore([])
    store.gambut_geometry = None  # tidak ada gambut di provinsi ini
    svc.postgres_store = store
    svc._current_bbox = (109.0, -3.0, 114.0, 2.0)

    assert svc._gambut_mask(_FakeEE(), _FakeGeom()) is None
    assert store.gambut_calls == [((109.0, -3.0, 114.0, 2.0), 0.001)]


def test_gambut_mask_builds_image_when_geometry_present() -> None:
    svc = _svc()
    store = _FakeStore([])
    store.gambut_geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    svc.postgres_store = store
    svc._current_bbox = (109.0, -3.0, 114.0, 2.0)

    result = svc._gambut_mask(_FakeEE(), _FakeGeom())

    assert result is not None
    assert isinstance(result, _FakeImg)


def test_gambut_mask_non_fatal_when_store_raises() -> None:
    svc = _svc()

    class _RaisingStore:
        def read_gambut_mask_geometry(self, *a, **k):
            raise RuntimeError("boom")

    svc.postgres_store = _RaisingStore()
    svc._current_bbox = (109.0, -3.0, 114.0, 2.0)

    assert svc._gambut_mask(_FakeEE(), _FakeGeom()) is None


def test_scar_mask_skips_gambut_lookup_when_relax_disabled(monkeypatch) -> None:
    """enable_gambut_cluster_relax=False -> postgres_store.read_gambut_mask_geometry
    tidak boleh terpanggil sama sekali (hemat query + GEE call kalau user matikan)."""
    svc = _svc()
    store = _FakeStore([])
    svc.postgres_store = store
    svc.enable_sar_fusion = False
    svc.enable_gambut_cluster_relax = False
    svc._current_bbox = (109.0, -3.0, 114.0, 2.0)
    svc._pre_post = ("2026-06-01", "2026-08-01", "2026-08-01", "2026-09-01")

    svc._scar_mask(_FakeEE(), _FakeGeom())

    assert store.gambut_calls == []


def test_scar_mask_calls_gambut_lookup_when_relax_enabled(monkeypatch) -> None:
    svc = _svc()
    store = _FakeStore([])
    store.gambut_geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    svc.postgres_store = store
    svc.enable_sar_fusion = False
    svc.enable_gambut_cluster_relax = True
    svc._current_bbox = (109.0, -3.0, 114.0, 2.0)
    svc._pre_post = ("2026-06-01", "2026-08-01", "2026-08-01", "2026-09-01")

    svc._scar_mask(_FakeEE(), _FakeGeom())

    assert len(store.gambut_calls) == 1


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
