from __future__ import annotations

import pytest


def test_month_range_handles_december_rollover() -> None:
    from app.services.burned_area_service import _month_range

    assert _month_range(2026, 4) == ("2026-04-01", "2026-05-01")
    assert _month_range(2026, 12) == ("2026-12-01", "2027-01-01")


def test_enabled_is_false_when_credentials_missing(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services.burned_area_service import BurnedAreaService

    get_settings.cache_clear()
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_EMAIL", "")
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_KEY_PATH", "")
    monkeypatch.setenv("GEE_PROJECT_ID", "")
    try:
        service = BurnedAreaService.__new__(BurnedAreaService)
        service.settings = get_settings()
        assert service.enabled is False
    finally:
        get_settings.cache_clear()


def test_refresh_burned_area_raises_when_not_configured(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.services.burned_area_service import BurnedAreaService, BurnedAreaServiceError

    get_settings.cache_clear()
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_EMAIL", "")
    monkeypatch.setenv("GEE_SERVICE_ACCOUNT_KEY_PATH", "")
    monkeypatch.setenv("GEE_PROJECT_ID", "")
    try:
        service = BurnedAreaService.__new__(BurnedAreaService)
        service.settings = get_settings()
        service._ee_initialized = False
        with pytest.raises(BurnedAreaServiceError):
            service.refresh_burned_area(2026, 4)
    finally:
        get_settings.cache_clear()


class _FakeReducer:
    @staticmethod
    def sum():
        return "sum-reducer"


class _FakeGeometry:
    def __init__(self, geojson):
        self.geojson = geojson


class _FakeFeature:
    def __init__(self, geometry, props):
        self.geometry = geometry
        self.props = props


class _FakeFeatureCollection:
    def __init__(self, features):
        self.features = features


class _FakeReducedResult:
    def __init__(self, features_out):
        self._features_out = features_out

    def getInfo(self):
        return {"features": self._features_out}


class _FakeAreaImage:
    def __init__(self, per_pid_sqm):
        self._per_pid_sqm = per_pid_sqm

    def reduceRegions(self, collection, reducer, scale):
        features_out = [
            {"properties": {"pid": feature.props["pid"], "sum": self._per_pid_sqm.get(feature.props["pid"], 0)}}
            for feature in collection.features
        ]
        return _FakeReducedResult(features_out)


class _FakeMosaicImage:
    def gt(self, _threshold):
        return self

    def multiply(self, _pixel_area):
        return _FakeAreaImage(per_pid_sqm={1: 50_000.0, 2: 0.0})  # 5 ha, 0 ha


class _FakeImageCollection:
    def __init__(self, _collection_id):
        self._size = 1

    def filterDate(self, _start, _end):
        return self

    def select(self, _band):
        return self

    def size(self):
        class _Size:
            def __init__(self, n):
                self._n = n

            def getInfo(self_inner):
                return self_inner._n

        return _Size(self._size)

    def mosaic(self):
        return _FakeMosaicImage()


class _FakeImage:
    @staticmethod
    def pixelArea():
        return "pixel-area"


class _FakeEE:
    ImageCollection = _FakeImageCollection
    Image = _FakeImage
    Geometry = _FakeGeometry
    Feature = _FakeFeature
    FeatureCollection = _FakeFeatureCollection
    Reducer = _FakeReducer


def test_vectorize_burned_area_clips_pixels_to_kps_boundary() -> None:
    """Regresi: ditemukan lewat sanity check nyata -- satu KPS 20,7 ha
    menyimpan geometry seluas 49,7 ha (2,4x lipat), karena reduceToVectors()
    mengembalikan SELURUH piksel MODIS 500m (25 ha) yang tersentuh geometri
    KPS, tanpa memotongnya ke batas kawasan sesungguhnya. Piksel yang cuma
    menyerempet tepi ikut utuh, meluber jauh keluar. Hasil vektorisasi wajib
    di-clip ke polygon_geojson sebelum disimpan."""
    from shapely.geometry import box, mapping, shape

    from app.services.burned_area_service import BurnedAreaService

    service = BurnedAreaService.__new__(BurnedAreaService)
    kps = mapping(box(0.0, 0.0, 0.009, 0.009))
    # Piksel MODIS yang jauh lebih besar dari KPS-nya, meluber ke segala arah --
    # mensimulasikan kasus nyata yang ditemukan.
    oversized_pixel = mapping(box(-0.005, -0.005, 0.02, 0.02))

    class _FakeReduced:
        def getInfo(self):
            return {"features": [{"geometry": oversized_pixel}]}

    class _FakeBurnedMask:
        def selfMask(self):
            return self

        def reduceToVectors(self, **kwargs):
            return _FakeReduced()

    class _FakeEE:
        @staticmethod
        def Geometry(geojson):
            return geojson

    result = service._vectorize_burned_area(_FakeEE(), _FakeBurnedMask(), kps)

    assert result is not None
    result_area = shape(result).area
    kps_area = shape(kps).area
    assert result_area <= kps_area + 1e-12, (
        "geometry yang tersimpan tidak boleh lebih luas dari KPS-nya sendiri"
    )
    # Piksel di kasus ini menutupi seluruh KPS, jadi setelah clip hasilnya
    # sama persis dengan batas KPS.
    assert result_area == pytest.approx(kps_area)


def test_vectorize_burned_area_returns_none_when_intersection_is_empty() -> None:
    from shapely.geometry import box, mapping

    from app.services.burned_area_service import BurnedAreaService

    service = BurnedAreaService.__new__(BurnedAreaService)
    kps = mapping(box(0.0, 0.0, 0.009, 0.009))
    far_away_pixel = mapping(box(10.0, 10.0, 10.005, 10.005))

    class _FakeReduced:
        def getInfo(self):
            return {"features": [{"geometry": far_away_pixel}]}

    class _FakeBurnedMask:
        def selfMask(self):
            return self

        def reduceToVectors(self, **kwargs):
            return _FakeReduced()

    class _FakeEE:
        @staticmethod
        def Geometry(geojson):
            return geojson

    result = service._vectorize_burned_area(_FakeEE(), _FakeBurnedMask(), kps)
    assert result is None


def test_refresh_burned_area_upserts_computed_rows(monkeypatch) -> None:
    from app.services.burned_area_service import MCD64A1_COLLECTION, BurnedAreaService

    service = BurnedAreaService.__new__(BurnedAreaService)
    monkeypatch.setattr(service, "_ensure_ee", lambda: _FakeEE())

    upserted_rows = []
    tolerances_used = []

    class _FakeStore:
        def read_active_layer_keys(self):
            return ["PS_FEB_26"]

        def read_active_polygon_metadata_ids(self, layer_keys=None):
            return [1, 2]

        def read_polygon_geometries(self, ids, tolerance=0.001):
            tolerances_used.append(tolerance)
            return {pid: {"type": "Polygon", "coordinates": []} for pid in ids}

        def upsert_burned_area_summary(self, rows):
            upserted_rows.extend(rows)
            return len(rows)

    service.postgres_store = _FakeStore()

    result = service.refresh_burned_area(2026, 4)

    assert result["computed"] == 2
    assert result["polygons_checked"] == 2
    # Regresi: tolerance 0.001 (~110m, default fungsi -- dipakai tempat lain
    # untuk peta kecil di PDF) menggembungkan KPS mungil sampai +21% luas,
    # yang lantas jadi batas clip untuk burned_area_ha DAN geometry-nya.
    # Perhitungan luas terbakar butuh presisi jauh lebih ketat dari itu.
    assert tolerances_used and all(t == 0.0001 for t in tolerances_used)
    by_pid = {row["polygon_metadata_id"]: row["burned_area_ha"] for row in upserted_rows}
    assert by_pid[1] == pytest.approx(5.0)
    assert by_pid[2] == pytest.approx(0.0)
    assert all(row["layer_key"] == "PS_FEB_26" for row in upserted_rows)
    assert all(row["year"] == 2026 and row["month"] == 4 for row in upserted_rows)
    # MODIS "tersedia" di fake ini (size=1), jadi tidak boleh fallback ke VIIRS.
    assert all(row["source"] == MCD64A1_COLLECTION for row in upserted_rows)


class _FakeSize:
    def __init__(self, n: int) -> None:
        self._n = n

    def getInfo(self):
        return self._n


def test_resolve_monthly_source_falls_back_to_viirs_when_modis_unavailable() -> None:
    """MCD64A1 punya lag rilis lebih panjang dari VNP64A1 (Terra/Aqua yang
    makin uzur vs Suomi-NPP/NOAA-20 yang lebih baru) -- kalau bulan berjalan
    belum ada citra MODIS tapi VIIRS sudah, sistem harus tetap bisa
    menghitung pakai VIIRS, bukan langsung menyerah."""
    from app.services.burned_area_service import (
        MCD64A1_COLLECTION,
        VNP64A1_COLLECTION,
        BurnedAreaService,
    )

    class _FallbackImageCollection:
        def __init__(self, collection_id):
            self._collection_id = collection_id

        def filterDate(self, _start, _end):
            return self

        def select(self, _band):
            return self

        def size(self):
            return _FakeSize(0 if self._collection_id == MCD64A1_COLLECTION else 1)

        def mosaic(self):
            return _FakeMosaicImage()

    class _FallbackEE(_FakeEE):
        ImageCollection = _FallbackImageCollection

    service = BurnedAreaService.__new__(BurnedAreaService)
    source_id, burned_mask = service._resolve_monthly_source(_FallbackEE(), "2026-06-01", "2026-07-01")

    assert source_id == VNP64A1_COLLECTION
    assert burned_mask is not None


def test_resolve_monthly_source_returns_none_when_both_unavailable() -> None:
    from app.services.burned_area_service import BurnedAreaService

    class _EmptyImageCollection:
        def __init__(self, _collection_id):
            pass

        def filterDate(self, _start, _end):
            return self

        def select(self, _band):
            return self

        def size(self):
            return _FakeSize(0)

    class _EmptyEE(_FakeEE):
        ImageCollection = _EmptyImageCollection

    service = BurnedAreaService.__new__(BurnedAreaService)
    source_id, burned_mask = service._resolve_monthly_source(_EmptyEE(), "2026-08-01", "2026-09-01")

    assert source_id is None
    assert burned_mask is None


def test_refresh_burned_area_returns_note_when_neither_source_available(monkeypatch) -> None:
    from app.services.burned_area_service import BurnedAreaService

    class _EmptyImageCollection:
        def __init__(self, _collection_id):
            pass

        def filterDate(self, _start, _end):
            return self

        def select(self, _band):
            return self

        def size(self):
            return _FakeSize(0)

    class _EmptyEE(_FakeEE):
        ImageCollection = _EmptyImageCollection

    service = BurnedAreaService.__new__(BurnedAreaService)
    monkeypatch.setattr(service, "_ensure_ee", lambda: _EmptyEE())

    class _FakeStore:
        def read_active_layer_keys(self):
            return ["PS_FEB_26"]

    service.postgres_store = _FakeStore()

    result = service.refresh_burned_area(2026, 8)

    assert result["computed"] == 0
    assert "note" in result
    assert "VNP64A1" in result["note"]


def test_refresh_burned_area_records_viirs_as_source_when_used(monkeypatch) -> None:
    from app.services.burned_area_service import MCD64A1_COLLECTION, VNP64A1_COLLECTION, BurnedAreaService

    class _FallbackImageCollection:
        def __init__(self, collection_id):
            self._collection_id = collection_id

        def filterDate(self, _start, _end):
            return self

        def select(self, _band):
            return self

        def size(self):
            return _FakeSize(0 if self._collection_id == MCD64A1_COLLECTION else 1)

        def mosaic(self):
            return _FakeMosaicImage()

    class _FallbackEE(_FakeEE):
        ImageCollection = _FallbackImageCollection

    service = BurnedAreaService.__new__(BurnedAreaService)
    monkeypatch.setattr(service, "_ensure_ee", lambda: _FallbackEE())

    upserted_rows = []

    class _FakeStore:
        def read_active_layer_keys(self):
            return ["PS_FEB_26"]

        def read_active_polygon_metadata_ids(self, layer_keys=None):
            return [1, 2]

        def read_polygon_geometries(self, ids, tolerance=0.001):
            return {pid: {"type": "Polygon", "coordinates": []} for pid in ids}

        def upsert_burned_area_summary(self, rows):
            upserted_rows.extend(rows)
            return len(rows)

    service.postgres_store = _FakeStore()

    result = service.refresh_burned_area(2026, 6)

    assert result["computed"] == 2
    assert upserted_rows and all(row["source"] == VNP64A1_COLLECTION for row in upserted_rows)
