import io
import json
import zipfile

import pytest

from app.services.point_upload_parser import PointParseError, parse_points


def test_reads_geojson_points_and_keeps_original_properties():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [110.26, -1.88]},
                "properties": {"kode": "A-1", "petugas": "Budi"},
            }
        ],
    }
    result = parse_points(json.dumps(payload).encode(), "titik.geojson")

    assert len(result.points) == 1
    point = result.points[0]
    assert point.latitude == pytest.approx(-1.88)
    assert point.longitude == pytest.approx(110.26)
    # Metadata bawaan pengguna harus utuh, bukan dibuang.
    assert point.properties == {"kode": "A-1", "petugas": "Budi"}


def test_counts_non_point_geometry_as_skipped_instead_of_failing():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [110.0, -1.0]},
                "properties": {},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[110, -1], [111, -1], [111, 0], [110, -1]]],
                },
                "properties": {},
            },
        ],
    }
    result = parse_points(json.dumps(payload).encode(), "campur.geojson")

    assert len(result.points) == 1
    assert result.skipped_features == 1


def test_falls_back_to_lat_lon_columns_when_geometry_missing():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": None,
                "properties": {"Latitude": "-1.88", "Longitude": "110.26", "id": 7},
            }
        ],
    }
    result = parse_points(json.dumps(payload).encode(), "tanpa-geometry.geojson")

    assert len(result.points) == 1
    assert result.points[0].latitude == pytest.approx(-1.88)
    assert result.points[0].longitude == pytest.approx(110.26)


def test_rejects_coordinates_outside_earth():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [999.0, 500.0]},
                "properties": {},
            }
        ],
    }
    with pytest.raises(PointParseError):
        parse_points(json.dumps(payload).encode(), "ngawur.geojson")


def test_reads_kml_placemarks_with_extended_data():
    kml = """<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark>
          <name>Titik Satu</name>
          <ExtendedData>
            <SchemaData>
              <SimpleData name="regu">Regu A</SimpleData>
            </SchemaData>
          </ExtendedData>
          <Point><coordinates>110.26,-1.88,0</coordinates></Point>
        </Placemark>
      </Document>
    </kml>"""
    result = parse_points(kml.encode(), "titik.kml")

    assert len(result.points) == 1
    point = result.points[0]
    assert point.latitude == pytest.approx(-1.88)
    assert point.longitude == pytest.approx(110.26)
    assert point.properties["name"] == "Titik Satu"
    assert point.properties["regu"] == "Regu A"


def test_kml_without_any_placemark_is_a_clear_error():
    kml = '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'
    with pytest.raises(PointParseError, match="Placemark"):
        parse_points(kml.encode(), "kosong.kml")


def _build_shapefile_zip(*, include_prj: bool, include_dbf: bool = True) -> bytes:
    shapefile = pytest.importorskip("shapefile")

    shp_buffer, shx_buffer, dbf_buffer = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp_buffer, shx=shx_buffer, dbf=dbf_buffer)
    writer.field("kode", "C", size=10)
    writer.point(110.26, -1.88)
    writer.record("A-1")
    writer.close()

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("data/titik.shp", shp_buffer.getvalue())
        archive.writestr("data/titik.shx", shx_buffer.getvalue())
        if include_dbf:
            archive.writestr("data/titik.dbf", dbf_buffer.getvalue())
        if include_prj:
            archive.writestr(
                "data/titik.prj",
                'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
                'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
                'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]',
            )
    return archive_buffer.getvalue()


def test_reads_shapefile_from_zip_with_attributes():
    result = parse_points(_build_shapefile_zip(include_prj=True), "titik.zip")

    assert len(result.points) == 1
    point = result.points[0]
    assert point.latitude == pytest.approx(-1.88)
    assert point.longitude == pytest.approx(110.26)
    assert point.properties["kode"] == "A-1"


def test_shapefile_without_prj_still_works_but_warns_loudly():
    """Diam-diam menganggap WGS84 itu berbahaya -- kalau aslinya UTM, hasil
    pencocokan KPS akan salah total tanpa pengguna sadar."""
    result = parse_points(_build_shapefile_zip(include_prj=False), "titik.zip")

    assert len(result.points) == 1
    assert any(".prj" in warning for warning in result.warnings)


def test_incomplete_shapefile_names_the_missing_part():
    with pytest.raises(PointParseError, match=r"\.dbf"):
        parse_points(_build_shapefile_zip(include_prj=True, include_dbf=False), "titik.zip")


def test_unsupported_extension_is_rejected():
    with pytest.raises(PointParseError, match="tidak didukung"):
        parse_points(b"apa saja", "data.csv")
