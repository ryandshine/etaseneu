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
class ParseResult:
    points: list[ParsedPoint]
    source_format: str
    # Hal-hal yang perlu diketahui pengguna tapi tidak menggagalkan proses,
    # mis. asumsi CRS atau geometry non-titik yang dilewati. Ditampilkan di UI.
    warnings: list[str] = field(default_factory=list)
    skipped_features: int = 0


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
    if kind in {"Point", "MultiPoint"}:
        return [{"type": "Feature", "geometry": payload, "properties": {}}]
    raise PointParseError(f"Tipe GeoJSON '{kind}' tidak didukung; harus berisi titik.")


def parse_geojson(raw: bytes) -> ParseResult:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PointParseError("Berkas GeoJSON tidak bisa dibaca (format JSON rusak).") from exc

    points: list[ParsedPoint] = []
    skipped = 0

    for feature in _iter_geojson_features(payload):
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

        if geom_type == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
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
            # Poligon/garis sengaja dilewati, bukan error: fitur ini memang
            # untuk titik. Jumlahnya dilaporkan supaya pengguna sadar.
            skipped += 1

    return ParseResult(points=points, source_format="geojson", skipped_features=skipped)


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
        if not point_elements:
            skipped += 1
            continue

        added = 0
        for point_el in point_elements:
            coord_text = ""
            for el in point_el.iter():
                if _strip_ns(el.tag) == "coordinates" and el.text:
                    coord_text = el.text.strip()
            if not coord_text:
                continue
            # KML: "lon,lat[,alt]" dan boleh banyak pasangan dipisah spasi
            for chunk in coord_text.split():
                parts = chunk.split(",")
                if len(parts) < 2:
                    continue
                lon, lat = _coerce_float(parts[0]), _coerce_float(parts[1])
                if lat is None or lon is None or not _is_valid_lat(lat) or not _is_valid_lon(lon):
                    continue
                points.append(ParsedPoint(lat, lon, dict(properties)))
                added += 1
        if added == 0:
            skipped += 1

    return ParseResult(points=points, source_format="kml", skipped_features=skipped)


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
    skipped = 0

    for record in reader.iterShapeRecords():
        shape = record.shape
        properties = dict(zip(field_names, list(record.record)))
        # Normalisasi tipe yang tidak bisa di-JSON (date, bytes, dst)
        for key, value in list(properties.items()):
            if not isinstance(value, (str, int, float, bool, type(None))):
                properties[key] = str(value)

        pts = list(getattr(shape, "points", []) or [])
        if not pts:
            fallback = _point_from_properties(properties)
            if fallback is None:
                skipped += 1
                continue
            raw_coords.append((fallback[1], fallback[0]))
            props_per_point.append(properties)
            continue

        # shapeType 1/11/21 = Point, 8/18/28 = MultiPoint
        if shape.shapeType in (1, 11, 21, 8, 18, 28):
            for x, y in pts:
                raw_coords.append((float(x), float(y)))
                props_per_point.append(dict(properties))
        else:
            skipped += 1

    if prj_name:
        prj_text = archive.read(prj_name).decode("utf-8", errors="replace")
        raw_coords, warning = _reproject_to_wgs84(raw_coords, prj_text)
        if warning:
            warnings.append(warning)
    else:
        warnings.append(
            "Berkas .prj tidak ada di dalam ZIP, jadi koordinat dianggap sudah "
            "WGS84 (lon/lat). Kalau data aslinya memakai proyeksi lain (mis. UTM), "
            "hasil pencocokan KPS akan salah."
        )

    points: list[ParsedPoint] = []
    for (lon, lat), properties in zip(raw_coords, props_per_point):
        if not _is_valid_lat(lat) or not _is_valid_lon(lon):
            skipped += 1
            continue
        points.append(ParsedPoint(lat, lon, properties))

    return ParseResult(
        points=points,
        source_format="shapefile",
        warnings=warnings,
        skipped_features=skipped,
    )


# ------------------------------------------------------------- dispatcher


def parse_points(raw: bytes, filename: str) -> ParseResult:
    """Baca berkas titik berdasarkan ekstensinya."""
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

    if not result.points:
        raise PointParseError(
            "Tidak ada titik yang bisa dibaca dari berkas ini. "
            "Pastikan isinya berupa titik (Point), bukan hanya poligon atau garis."
        )

    return result
