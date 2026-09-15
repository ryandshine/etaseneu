"""Pembaca berkas titik yang diunggah pengguna (GeoJSON / KML / SHP-zip).

Keluarannya seragam apa pun format masukannya: daftar ParsedPoint berisi
koordinat WGS84 plus SELURUH atribut asli dari berkas. Atribut asli tidak
pernah dibuang -- itu yang nanti digabung dengan hasil pencocokan KPS.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

import pyproj
import shapely
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform

SUPPORTED_EXTENSIONS = (".geojson", ".json", ".kml", ".zip")

# Nama kolom yang lazim dipakai kalau titik disimpan sebagai atribut, bukan
# sebagai geometry (sering terjadi pada shapefile/CSV hasil ekspor GPS).
_LAT_KEYS = ("latitude", "lat", "y", "lintang", "garis_lintang")
_LON_KEYS = ("longitude", "lon", "lng", "long", "x", "bujur", "garis_bujur")


class PointParseError(ValueError):
    """Berkas tidak bisa dibaca -- pesannya ditujukan untuk pengguna akhir."""


@dataclass
class ParsedPoint:
    latitude: float
    longitude: float
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedPolygon:
    geometry: Any  # shapely Polygon or MultiPolygon
    geojson: dict[str, Any]  # GeoJSON geometry mapping
    area_ha: float
    bounds: tuple[float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    points: list[ParsedPoint] = field(default_factory=list)
    source_format: str = ""
    # Hal-hal yang perlu diketahui pengguna tapi tidak menggagalkan proses,
    # mis. asumsi CRS atau geometry non-titik yang dilewati. Ditampilkan di UI.
    warnings: list[str] = field(default_factory=list)
    skipped_features: int = 0
    kind: str = "points"  # "points" | "polygon"
    polygon: ParsedPolygon | None = None


def _calculate_polygon_area_ha(geom: Any) -> float:
    try:
        geod = pyproj.Geod(ellps="WGS84")
        area, _ = geod.geometry_area_perimeter(geom)
        return round(abs(area) / 10000.0, 2)
    except Exception:
        return 0.0


def _clean_geometry(geom: Any) -> Any:
    if not geom.is_valid:
        geom = shapely.make_valid(geom)
    if geom.has_z:
        geom = transform(lambda x, y, *_: (x, y), geom)
    return geom


def _is_valid_lat(value: float) -> bool:
    return -90.0 <= value <= 90.0


def _is_valid_lon(value: float) -> bool:
    return -180.0 <= value <= 180.0


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _point_from_properties(properties: dict[str, Any]) -> tuple[float, float] | None:
    """Ambil lat/lon dari atribut kalau geometry-nya tidak ada."""
    lowered = {str(key).strip().lower(): value for key, value in properties.items()}
    lat = next((_coerce_float(lowered[k]) for k in _LAT_KEYS if k in lowered), None)
    lon = next((_coerce_float(lowered[k]) for k in _LON_KEYS if k in lowered), None)
    if lat is None or lon is None:
        return None
    if not _is_valid_lat(lat) or not _is_valid_lon(lon):
        return None
    return lat, lon


# ---------------------------------------------------------------- GeoJSON


def _iter_geojson_features(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise PointParseError("Isi berkas GeoJSON tidak dikenali.")

    kind = payload.get("type")
    if kind == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list):
            raise PointParseError("FeatureCollection tidak punya daftar features.")
        return [f for f in features if isinstance(f, dict)]
    if kind == "Feature":
        return [payload]
    if kind in {"Point", "MultiPoint", "Polygon", "MultiPolygon"}:
        return [{"type": "Feature", "geometry": payload, "properties": {}}]
    if kind == "GeometryCollection":
        geometries = payload.get("geometries", [])
        return [{"type": "Feature", "geometry": g, "properties": {}} for g in geometries if isinstance(g, dict)]
    raise PointParseError(f"Tipe GeoJSON '{kind}' tidak didukung.")


def parse_geojson(raw: bytes) -> ParseResult:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointParseError("Berkas GeoJSON tidak bisa dibaca (format JSON rusak).") from exc

    features = _iter_geojson_features(payload)
    polygon_geoms: list[Any] = []
    polygon_properties: dict[str, Any] = {}
    points: list[ParsedPoint] = []
    skipped = 0

    for feature in features:
        properties = feature.get("properties")
        properties = dict(properties) if isinstance(properties, dict) else {}
        geometry = feature.get("geometry")

        if not isinstance(geometry, dict):
            fallback = _point_from_properties(properties)
            if fallback is None:
                skipped += 1
                continue
            points.append(ParsedPoint(fallback[0], fallback[1], properties))
            continue

        geom_type = geometry.get("type")
        coords = geometry.get("coordinates")

        if geom_type in ("Polygon", "MultiPolygon") and coords:
            try:
                g = _clean_geometry(shape(geometry))
                if not g.is_empty:
                    polygon_geoms.append(g)
                    if not polygon_properties:
                        polygon_properties = properties
            except Exception:
                skipped += 1
        elif geom_type == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            lon, lat = _coerce_float(coords[0]), _coerce_float(coords[1])
            if lat is None or lon is None or not _is_valid_lat(lat) or not _is_valid_lon(lon):
                skipped += 1
                continue
            points.append(ParsedPoint(lat, lon, properties))
        elif geom_type == "MultiPoint" and isinstance(coords, (list, tuple)):
            added = 0
            for pair in coords:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    lon, lat = _coerce_float(pair[0]), _coerce_float(pair[1])
                    if lat is not None and lon is not None and _is_valid_lat(lat) and _is_valid_lon(lon):
                        points.append(ParsedPoint(lat, lon, dict(properties)))
                        added += 1
            if added == 0:
                skipped += 1
        else:
            skipped += 1

    if polygon_geoms and not points:
        union_geom = shapely.unary_union(polygon_geoms) if len(polygon_geoms) > 1 else polygon_geoms[0]
        union_geom = _clean_geometry(union_geom)
        bounds = tuple(float(x) for x in union_geom.bounds)
        area_ha = _calculate_polygon_area_ha(union_geom)
        parsed_poly = ParsedPolygon(
            geometry=union_geom,
            geojson=mapping(union_geom),
            area_ha=area_ha,
            bounds=(bounds[0], bounds[1], bounds[2], bounds[3]),
            properties=polygon_properties,
        )
        return ParseResult(
            source_format="geojson",
            kind="polygon",
            polygon=parsed_poly,
            skipped_features=skipped,
        )

    return ParseResult(
        points=points,
        source_format="geojson",
        kind="points",
        skipped_features=skipped + len(polygon_geoms),
    )


# -------------------------------------------------------------------- KML


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _kml_extended_data(placemark: ElementTree.Element) -> dict[str, Any]:
    """Baca ExtendedData/SimpleData dan Data/value -- metadata bawaan KML."""
    properties: dict[str, Any] = {}
    for element in placemark.iter():
        tag = _strip_ns(element.tag)
        if tag == "SimpleData":
            name = element.get("name")
            if name:
                properties[name] = (element.text or "").strip()
        elif tag == "Data":
            name = element.get("name")
            if not name:
                continue
            value = ""
            for child in element:
                if _strip_ns(child.tag) == "value":
                    value = (child.text or "").strip()
            properties[name] = value
    return properties


def parse_kml(raw: bytes) -> ParseResult:
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise PointParseError("Berkas KML tidak bisa dibaca (format XML rusak).") from exc

    points: list[ParsedPoint] = []
    polygon_geoms: list[Any] = []
    polygon_properties: dict[str, Any] = {}
    skipped = 0

    placemarks = [el for el in root.iter() if _strip_ns(el.tag) == "Placemark"]
    if not placemarks:
        raise PointParseError("Tidak ada Placemark di dalam berkas KML.")

    for placemark in placemarks:
        properties = _kml_extended_data(placemark)
        for child in placemark:
            tag = _strip_ns(child.tag)
            if tag in {"name", "description"} and child.text:
                properties.setdefault(tag, child.text.strip())

        point_elements = [el for el in placemark.iter() if _strip_ns(el.tag) == "Point"]
        poly_elements = [el for el in placemark.iter() if _strip_ns(el.tag) == "Polygon"]

        for poly_el in poly_elements:
            outer_coords: list[tuple[float, float]] = []
            for child in poly_el.iter():
                if _strip_ns(child.tag) == "outerBoundaryIs":
                    for coord_el in child.iter():
                        if _strip_ns(coord_el.tag) == "coordinates" and coord_el.text:
                            for chunk in coord_el.text.strip().split():
                                parts = chunk.split(",")
                                if len(parts) >= 2:
                                    lon, lat = _coerce_float(parts[0]), _coerce_float(parts[1])
                                    if lon is not None and lat is not None and _is_valid_lon(lon) and _is_valid_lat(lat):
                                        outer_coords.append((lon, lat))
            inner_rings: list[list[tuple[float, float]]] = []
            for child in poly_el.iter():
                if _strip_ns(child.tag) == "innerBoundaryIs":
                    hole: list[tuple[float, float]] = []
                    for coord_el in child.iter():
                        if _strip_ns(coord_el.tag) == "coordinates" and coord_el.text:
                            for chunk in coord_el.text.strip().split():
                                parts = chunk.split(",")
                                if len(parts) >= 2:
                                    lon, lat = _coerce_float(parts[0]), _coerce_float(parts[1])
                                    if lon is not None and lat is not None and _is_valid_lon(lon) and _is_valid_lat(lat):
                                        hole.append((lon, lat))
                    if len(hole) >= 3:
                        inner_rings.append(hole)

            if len(outer_coords) >= 3:
                try:
                    p = Polygon(outer_coords, holes=inner_rings)
                    p = _clean_geometry(p)
                    if not p.is_empty:
                        polygon_geoms.append(p)
                        if not polygon_properties:
                            polygon_properties = dict(properties)
                except Exception:
                    skipped += 1

        for point_el in point_elements:
            coord_text = ""
            for el in point_el.iter():
                if _strip_ns(el.tag) == "coordinates" and el.text:
                    coord_text = el.text.strip()
            if not coord_text:
                continue
            for chunk in coord_text.split():
                parts = chunk.split(",")
                if len(parts) < 2:
                    continue
                lon, lat = _coerce_float(parts[0]), _coerce_float(parts[1])
                if lat is None or lon is None or not _is_valid_lat(lat) or not _is_valid_lon(lon):
                    continue
                points.append(ParsedPoint(lat, lon, dict(properties)))

        if not point_elements and not poly_elements:
            skipped += 1

    if polygon_geoms and not points:
        union_geom = shapely.unary_union(polygon_geoms) if len(polygon_geoms) > 1 else polygon_geoms[0]
        union_geom = _clean_geometry(union_geom)
        bounds = tuple(float(x) for x in union_geom.bounds)
        area_ha = _calculate_polygon_area_ha(union_geom)
        parsed_poly = ParsedPolygon(
            geometry=union_geom,
            geojson=mapping(union_geom),
            area_ha=area_ha,
            bounds=(bounds[0], bounds[1], bounds[2], bounds[3]),
            properties=polygon_properties,
        )
        return ParseResult(
            source_format="kml",
            kind="polygon",
            polygon=parsed_poly,
            skipped_features=skipped,
        )

    return ParseResult(
        points=points,
        source_format="kml",
        kind="points",
        skipped_features=skipped + len(polygon_geoms),
    )


# -------------------------------------------------------------- SHP (zip)


def _reproject_to_wgs84(
    coords: list[tuple[float, float]], prj_text: str
) -> tuple[list[tuple[float, float]], str | None]:
    """Kembalikan (koordinat_lon_lat, peringatan). Input dianggap (x, y)."""
    from pyproj import CRS, Transformer
    from pyproj.exceptions import CRSError

    try:
        crs = CRS.from_wkt(prj_text)
    except (CRSError, Exception):  # noqa: BLE001 - pyproj melempar beragam tipe
        return coords, (
            "Berkas .prj ada tapi sistem koordinatnya tidak dikenali; "
            "koordinat dianggap sudah WGS84 (lon/lat)."
        )

    if crs.to_epsg() == 4326:
        return coords, None

    transformer = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    converted: list[tuple[float, float]] = []
    for x, y in coords:
        lon, lat = transformer.transform(x, y)
        converted.append((lon, lat))
    name = crs.name or "tidak bernama"
    return converted, f"Koordinat diproyeksikan ulang dari {name} ke WGS84."


def parse_shapefile_zip(raw: bytes) -> ParseResult:
    import shapefile  # pyshp

    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise PointParseError("Berkas ZIP rusak atau bukan ZIP.") from exc

    names = archive.namelist()

    def _find(ext: str) -> str | None:
        matches = [n for n in names if n.lower().endswith(ext) and not n.startswith("__MACOSX")]
        return matches[0] if matches else None

    shp_name = _find(".shp")
    if shp_name is None:
        raise PointParseError("Tidak ada berkas .shp di dalam ZIP.")

    dbf_name = _find(".dbf")
    shx_name = _find(".shx")
    prj_name = _find(".prj")

    if dbf_name is None:
        raise PointParseError(
            "Shapefile tidak lengkap: berkas .dbf tidak ada. "
            "ZIP harus berisi .shp, .shx, dan .dbf sekaligus."
        )
    if shx_name is None:
        raise PointParseError(
            "Shapefile tidak lengkap: berkas .shx tidak ada. "
            "ZIP harus berisi .shp, .shx, dan .dbf sekaligus."
        )

    warnings: list[str] = []

    try:
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(shp_name)),
            shx=io.BytesIO(archive.read(shx_name)),
            dbf=io.BytesIO(archive.read(dbf_name)),
        )
    except Exception as exc:  # noqa: BLE001 - pyshp melempar beragam tipe
        raise PointParseError(f"Shapefile tidak bisa dibaca: {exc}") from exc

    field_names = [f[0] for f in reader.fields[1:]]  # lewati DeletionFlag

    raw_coords: list[tuple[float, float]] = []
    props_per_point: list[dict[str, Any]] = []
    polygon_geoms: list[Any] = []
    polygon_properties: dict[str, Any] = {}
    skipped = 0

    for record in reader.iterShapeRecords():
        shp_rec = record.shape
        properties = dict(zip(field_names, list(record.record)))
        for key, value in list(properties.items()):
            if not isinstance(value, (str, int, float, bool, type(None))):
                properties[key] = str(value)

        # Poligon (shapeType 5=POLYGON, 15=POLYGONZ, 25=POLYGONM)
        if shp_rec.shapeType in (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM):
            try:
                g = _clean_geometry(shape(shp_rec.__geo_interface__))
                if not g.is_empty:
                    polygon_geoms.append(g)
                    if not polygon_properties:
                        polygon_properties = dict(properties)
            except Exception:
                skipped += 1
            continue

        pts = list(getattr(shp_rec, "points", []) or [])
        if not pts:
            fallback = _point_from_properties(properties)
            if fallback is None:
                skipped += 1
                continue
            raw_coords.append((fallback[1], fallback[0]))
            props_per_point.append(properties)
            continue

        if shp_rec.shapeType in (1, 11, 21, 8, 18, 28):
            for x, y in pts:
                raw_coords.append((float(x), float(y)))
                props_per_point.append(dict(properties))
        else:
            skipped += 1

    transformer_to_wgs84 = None
    if prj_name:
        prj_text = archive.read(prj_name).decode("utf-8", errors="replace")
        try:
            from pyproj import CRS, Transformer
            crs = CRS.from_wkt(prj_text)
            if crs.to_epsg() != 4326:
                transformer_to_wgs84 = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
                name = crs.name or "tidak bernama"
                warnings.append(f"Koordinat diproyeksikan ulang dari {name} ke WGS84.")
        except Exception:
            warnings.append(
                "Berkas .prj ada tapi sistem koordinatnya tidak dikenali; "
                "koordinat dianggap sudah WGS84 (lon/lat)."
            )
    else:
        warnings.append(
            "Berkas .prj tidak ada di dalam ZIP, jadi koordinat dianggap sudah "
            "WGS84 (lon/lat). Kalau data aslinya memakai proyeksi lain (mis. UTM), "
            "hasil pencocokan akan salah."
        )

    if polygon_geoms and not raw_coords:
        if transformer_to_wgs84:
            polygon_geoms = [transform(transformer_to_wgs84.transform, g) for g in polygon_geoms]
        union_geom = shapely.unary_union(polygon_geoms) if len(polygon_geoms) > 1 else polygon_geoms[0]
        union_geom = _clean_geometry(union_geom)
        bounds = tuple(float(x) for x in union_geom.bounds)
        area_ha = _calculate_polygon_area_ha(union_geom)
        parsed_poly = ParsedPolygon(
            geometry=union_geom,
            geojson=mapping(union_geom),
            area_ha=area_ha,
            bounds=(bounds[0], bounds[1], bounds[2], bounds[3]),
            properties=polygon_properties,
        )
        return ParseResult(
            source_format="shapefile",
            kind="polygon",
            polygon=parsed_poly,
            warnings=warnings,
            skipped_features=skipped,
        )

    if transformer_to_wgs84 and raw_coords:
        converted: list[tuple[float, float]] = []
        for x, y in raw_coords:
            lon, lat = transformer_to_wgs84.transform(x, y)
            converted.append((lon, lat))
        raw_coords = converted

    points: list[ParsedPoint] = []
    for (lon, lat), properties in zip(raw_coords, props_per_point):
        if not _is_valid_lat(lat) or not _is_valid_lon(lon):
            skipped += 1
            continue
        points.append(ParsedPoint(lat, lon, properties))

    return ParseResult(
        points=points,
        source_format="shapefile",
        kind="points",
        warnings=warnings,
        skipped_features=skipped,
    )


# ------------------------------------------------------------- dispatcher


def parse_spatial_file(raw: bytes, filename: str) -> ParseResult:
    """Baca berkas spasial (titik atau poligon) berdasarkan ekstensinya."""
    lowered = (filename or "").lower()

    if lowered.endswith(".zip"):
        result = parse_shapefile_zip(raw)
    elif lowered.endswith(".kml"):
        result = parse_kml(raw)
    elif lowered.endswith((".geojson", ".json")):
        result = parse_geojson(raw)
    else:
        raise PointParseError(
            "Format berkas tidak didukung. Gunakan .geojson, .json, .kml, "
            "atau .zip berisi shapefile."
        )

    if result.kind == "points" and not result.points:
        raise PointParseError(
            "Tidak ada titik maupun poligon yang bisa dibaca dari berkas ini. "
            "Pastikan berkas berisi koordinat titik atau poligon batas areal."
        )
    if result.kind == "polygon" and not result.polygon:
        raise PointParseError(
            "Poligon tidak valid atau kosong di dalam berkas ini."
        )

    return result


def parse_points(raw: bytes, filename: str) -> ParseResult:
    """Kompatibilitas mundur: baca berkas spasial."""
    return parse_spatial_file(raw, filename)
