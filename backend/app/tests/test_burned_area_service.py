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


def test_refresh_burned_area_upserts_computed_rows(monkeypatch) -> None:
    from app.services.burned_area_service import BurnedAreaService

    service = BurnedAreaService.__new__(BurnedAreaService)
    monkeypatch.setattr(service, "_ensure_ee", lambda: _FakeEE())

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

    result = service.refresh_burned_area(2026, 4)

    assert result["computed"] == 2
    assert result["polygons_checked"] == 2
    by_pid = {row["polygon_metadata_id"]: row["burned_area_ha"] for row in upserted_rows}
    assert by_pid[1] == pytest.approx(5.0)
    assert by_pid[2] == pytest.approx(0.0)
    assert all(row["layer_key"] == "PS_FEB_26" for row in upserted_rows)
    assert all(row["year"] == 2026 and row["month"] == 4 for row in upserted_rows)
