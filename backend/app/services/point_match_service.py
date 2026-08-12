"""Gabungkan berkas titik yang diunggah dengan polygon KPS.

Alurnya: berkas mentah -> parser -> spatial join PostGIS -> hasil + ringkasan.
Metadata asli pengguna dibawa utuh sampai ke laporan.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.services.point_upload_parser import ParseResult, parse_points

# Batas ini melindungi endpoint yang terbuka untuk umum. Angkanya jauh di atas
# skala pemakaian yang disebutkan (puluhan ribu titik), tapi tetap mencegah satu
# unggahan menghabiskan memori server.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_POINTS = 200_000


class PointMatchError(ValueError):
    """Pesan yang aman dan berguna untuk ditampilkan ke pengguna akhir."""


@dataclass
class MatchedPoint:
    latitude: float
    longitude: float
    properties: dict[str, Any]
    kps: dict[str, Any] | None

    @property
    def inside_kps(self) -> bool:
        return self.kps is not None


@dataclass
class MatchSummary:
    total_points: int
    inside_count: int
    outside_count: int
    distinct_kps: int
    by_kps: list[dict[str, Any]] = field(default_factory=list)
    by_wilker: list[dict[str, Any]] = field(default_factory=list)
    by_province: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class MatchOutcome:
    points: list[MatchedPoint]
    summary: MatchSummary
    source_format: str
    warnings: list[str]
    skipped_features: int
    property_columns: list[str]
    # Geometry polygon KPS yang kena, dipakai menggambar peta kecil di laporan.
    # Kosong kalau geometry gagal diambil -- laporan tetap terbit, hanya tanpa
    # petanya, karena angka dan tabelnya jauh lebih penting daripada gambar.
    polygon_geometries: dict[int, dict[str, Any]] = field(default_factory=dict)


def _rank(counter: Counter[str], limit: int | None = None) -> list[dict[str, Any]]:
    items = [
        {"label": label, "count": count}
        for label, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return items[:limit] if limit else items


def _build_summary(points: list[MatchedPoint]) -> MatchSummary:
    by_kps: Counter[str] = Counter()
    by_wilker: Counter[str] = Counter()
    by_province: Counter[str] = Counter()

    inside = 0
    for point in points:
        if not point.kps:
            continue
        inside += 1
        by_kps[str(point.kps.get("lembaga") or "(tanpa nama)")] += 1
        by_wilker[str(point.kps.get("wilker_bps") or "(tanpa wilker)")] += 1
        by_province[str(point.kps.get("nama_prov") or "(tanpa provinsi)")] += 1

    return MatchSummary(
        total_points=len(points),
        inside_count=inside,
        outside_count=len(points) - inside,
        distinct_kps=len(by_kps),
        by_kps=_rank(by_kps),
        by_wilker=_rank(by_wilker),
        by_province=_rank(by_province),
    )


def _collect_property_columns(points: list[MatchedPoint]) -> list[str]:
    """Kolom metadata asli, urut sesuai kemunculan pertama.

    Dipakai supaya laporan Excel/PDF punya kolom yang stabil walau tiap fitur
    membawa kunci yang berbeda-beda.
    """
    columns: list[str] = []
    seen: set[str] = set()
    for point in points:
        for key in point.properties:
            name = str(key)
            if name not in seen:
                seen.add(name)
                columns.append(name)
    return columns


def match_uploaded_points(raw: bytes, filename: str, store: Any) -> MatchOutcome:
    """Baca berkas lalu cocokkan tiap titik ke polygon KPS."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PointMatchError(
            f"Ukuran berkas melebihi batas {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    parsed: ParseResult = parse_points(raw, filename)

    if len(parsed.points) > MAX_POINTS:
        raise PointMatchError(
            f"Jumlah titik ({len(parsed.points):,}) melebihi batas {MAX_POINTS:,} titik."
        )

    if not getattr(store, "enabled", False):
        raise PointMatchError(
            "Database tidak tersedia, jadi titik tidak bisa dicocokkan ke KPS."
        )

    coordinates = [(point.latitude, point.longitude) for point in parsed.points]
    matches = store.match_points_to_polygons(coordinates)

    points = [
        MatchedPoint(
            latitude=parsed_point.latitude,
            longitude=parsed_point.longitude,
            properties=parsed_point.properties,
            kps=match,
        )
        for parsed_point, match in zip(parsed.points, matches)
    ]

    polygon_ids = {
        int(point.kps["polygon_metadata_id"])
        for point in points
        if point.kps and point.kps.get("polygon_metadata_id") is not None
    }
    polygon_geometries: dict[int, dict[str, Any]] = {}
    if polygon_ids and hasattr(store, "read_polygon_geometries"):
        try:
            polygon_geometries = store.read_polygon_geometries(sorted(polygon_ids))
        except Exception:
            # Peta hanyalah pelengkap; kegagalan mengambil geometry tidak boleh
            # menggagalkan seluruh analisis yang angkanya sudah benar.
            polygon_geometries = {}

    return MatchOutcome(
        points=points,
        summary=_build_summary(points),
        source_format=parsed.source_format,
        warnings=list(parsed.warnings),
        skipped_features=parsed.skipped_features,
        property_columns=_collect_property_columns(points),
        polygon_geometries=polygon_geometries,
    )
