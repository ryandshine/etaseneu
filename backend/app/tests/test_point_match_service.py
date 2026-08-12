import json

import pytest

from app.services.point_match_service import (
    MAX_POINTS,
    PointMatchError,
    match_uploaded_points,
)


class FakeStore:
    """Store palsu supaya test ini tidak menyentuh database sungguhan."""

    def __init__(self, matches):
        self.enabled = True
        self._matches = matches
        self.received_coordinates = None

    def match_points_to_polygons(self, coordinates):
        self.received_coordinates = list(coordinates)
        return self._matches


def _geojson(features):
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def _point_feature(lon, lat, properties=None):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties or {},
    }


def test_merges_kps_match_with_original_metadata():
    raw = _geojson([_point_feature(110.26, -1.88, {"kode": "A-1"})])
    store = FakeStore([{"lembaga": "LPHD DEMO", "wilker_bps": "Balai PS X", "nama_prov": "Kalbar"}])

    outcome = match_uploaded_points(raw, "titik.geojson", store)

    assert len(outcome.points) == 1
    point = outcome.points[0]
    assert point.inside_kps is True
    assert point.kps["lembaga"] == "LPHD DEMO"
    # Metadata asli tidak boleh tergeser oleh hasil pencocokan.
    assert point.properties == {"kode": "A-1"}
    assert outcome.property_columns == ["kode"]


def test_points_outside_any_kps_are_reported_not_dropped():
    raw = _geojson(
        [
            _point_feature(110.26, -1.88, {"kode": "A"}),
            _point_feature(90.0, 0.0, {"kode": "B"}),
        ]
    )
    store = FakeStore([{"lembaga": "LPHD DEMO"}, None])

    outcome = match_uploaded_points(raw, "titik.geojson", store)

    assert outcome.summary.total_points == 2
    assert outcome.summary.inside_count == 1
    assert outcome.summary.outside_count == 1
    # Titik di luar kawasan tetap ada barisnya, hanya kps-nya None.
    assert outcome.points[1].inside_kps is False
    assert outcome.points[1].properties == {"kode": "B"}


def test_coordinates_are_passed_as_lat_lon_pairs_in_order():
    raw = _geojson([_point_feature(110.0, -1.0), _point_feature(111.0, -2.0)])
    store = FakeStore([None, None])

    match_uploaded_points(raw, "titik.geojson", store)

    assert store.received_coordinates == [(-1.0, 110.0), (-2.0, 111.0)]


def test_summary_ranks_kps_wilker_and_province_by_count():
    raw = _geojson([_point_feature(110.0, -1.0) for _ in range(3)])
    store = FakeStore(
        [
            {"lembaga": "A", "wilker_bps": "W1", "nama_prov": "P1"},
            {"lembaga": "B", "wilker_bps": "W1", "nama_prov": "P1"},
            {"lembaga": "B", "wilker_bps": "W2", "nama_prov": "P2"},
        ]
    )

    outcome = match_uploaded_points(raw, "titik.geojson", store)

    assert outcome.summary.distinct_kps == 2
    assert outcome.summary.by_kps[0] == {"label": "B", "count": 2}
    assert outcome.summary.by_wilker[0] == {"label": "W1", "count": 2}
    assert outcome.summary.by_province[0] == {"label": "P1", "count": 2}


def test_property_columns_keep_first_seen_order_across_mixed_features():
    raw = _geojson(
        [
            _point_feature(110.0, -1.0, {"kode": "A", "regu": "R1"}),
            _point_feature(111.0, -2.0, {"petugas": "Budi", "kode": "B"}),
        ]
    )
    store = FakeStore([None, None])

    outcome = match_uploaded_points(raw, "titik.geojson", store)

    assert outcome.property_columns == ["kode", "regu", "petugas"]


def test_rejects_upload_larger_than_limit():
    with pytest.raises(PointMatchError, match="melebihi batas"):
        match_uploaded_points(b"x" * (51 * 1024 * 1024), "besar.geojson", FakeStore([]))


def test_rejects_more_points_than_limit():
    features = [_point_feature(110.0, -1.0) for _ in range(3)]
    raw = _geojson(features)
    store = FakeStore([None, None, None])

    import app.services.point_match_service as module

    original = module.MAX_POINTS
    module.MAX_POINTS = 2
    try:
        with pytest.raises(PointMatchError, match="melebihi batas"):
            match_uploaded_points(raw, "titik.geojson", store)
    finally:
        module.MAX_POINTS = original


def test_reports_clearly_when_database_is_unavailable():
    class DisabledStore:
        enabled = False

    raw = _geojson([_point_feature(110.0, -1.0)])
    with pytest.raises(PointMatchError, match="Database tidak tersedia"):
        match_uploaded_points(raw, "titik.geojson", DisabledStore())


def test_parser_warnings_reach_the_caller():
    """Peringatan CRS dari parser tidak boleh hilang di tengah jalan --
    pengguna perlu tahu kalau proyeksi diasumsikan."""
    import io
    import zipfile

    shapefile = pytest.importorskip("shapefile")

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf)
    writer.field("kode", "C", size=10)
    writer.point(110.26, -1.88)
    writer.record("A-1")
    writer.close()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("t.shp", shp.getvalue())
        archive.writestr("t.shx", shx.getvalue())
        archive.writestr("t.dbf", dbf.getvalue())
        # sengaja tanpa .prj

    outcome = match_uploaded_points(buffer.getvalue(), "titik.zip", FakeStore([None]))

    assert any(".prj" in warning for warning in outcome.warnings)
