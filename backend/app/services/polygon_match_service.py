"""Pencocokan poligon yang diunggah pengguna dengan titik panas NASA FIRMS sepanjang tahun berjalan.

Alurnya:
1. Polygon (GeoJSON / KML / Shapefile) diparsing dan divalidasi geometrinya.
2. Dihitung luas areal (Hektare) dan batas koordinat (Bounding Box).
3. Dicek apakah poligon beririsan dengan kawasan Perhutanan Sosial (KPS).
4. Jika poligon berada di luar KPS dan kunci NASA FIRMS tersedia, sistem dapat
   mengambil data langsung dari NASA FIRMS untuk bounding box tersebut.
5. Dicari seluruh titik panas di dalam poligon dari tabel hotspot_observations
   sepanjang tahun berjalan (2026).
6. Hasil diagregasi (total, tingkat keyakinan, satelit, bulanan) dan disiapkan
   untuk antarmuka serta ekspor Excel/PDF.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.hotspot_categories import confidence_category, frp_category
from app.services.hotspot_normalizer import normalize_hotspots
from app.services.nasa_client import NasaFirmsClient
from app.services.point_upload_parser import ParsedPolygon

logger = logging.getLogger("polygon_match")
WIB = ZoneInfo("Asia/Jakarta")
PREVIEW_LIMIT = 500


class PolygonMatchError(ValueError):
    """Pesan yang aman dan berguna untuk ditampilkan ke pengguna akhir."""


@dataclass
class PolygonSummary:
    total_hotspots: int = 0
    confidence_high: int = 0
    confidence_medium: int = 0
    confidence_low: int = 0
    density_per_1000ha: float = 0.0
    by_month: list[dict[str, Any]] = field(default_factory=list)
    by_satellite: list[dict[str, Any]] = field(default_factory=list)
    by_confidence: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PolygonMatchOutcome:
    kind: str = "polygon"
    source_name: str = ""
    source_format: str = ""
    area_ha: float = 0.0
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    overlaps_kps: bool = False
    kps_matches: list[dict[str, Any]] = field(default_factory=list)
    summary: PolygonSummary = field(default_factory=PolygonSummary)
    hotspots: list[dict[str, Any]] = field(default_factory=list)
    polygon_geojson: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    skipped_features: int = 0
    preview_rows: list[list[Any]] = field(default_factory=list)
    preview_truncated: bool = False


def _format_wib(dt: datetime | str | None) -> str:
    if not dt:
        return "-"
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return dt
    else:
        parsed = dt
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_dt = parsed.astimezone(WIB)
    return local_dt.strftime("%d %b %Y %H:%M WIB")


def _rank(counter: Counter[str], limit: int | None = None) -> list[dict[str, Any]]:
    items = [
        {"label": label, "count": count}
        for label, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return items[:limit] if limit else items


async def _sync_firms_for_bbox(
    bounds: tuple[float, float, float, float],
    start_date: date,
    end_date: date,
    store: Any,
    nasa_client: NasaFirmsClient | None,
    api_key: str | None,
) -> int:
    """Tarik data NASA FIRMS untuk bounding box poligon jika di luar KPS."""
    if not nasa_client or not api_key:
        return 0

    min_lon, min_lat, max_lon, max_lat = bounds
    # Lindungi agar tidak fetch area raksasa (misal se-Indonesia) yang bisa timeout
    if (max_lon - min_lon) > 3.0 or (max_lat - min_lat) > 3.0:
        logger.info("Bounding box poligon terlalu besar (%s, %s), lewati on-demand fetch NASA", max_lon - min_lon, max_lat - min_lat)
        return 0

    coords_str = f"{min_lon:.5f},{min_lat:.5f},{max_lon:.5f},{max_lat:.5f}"
    today = datetime.now(timezone.utc).date()

    tasks = []
    # Jalankan query per interval 5 hari (batas maksimal NASA FIRMS area API)
    # Gunakan VIIRS NOAA-20 (SP untuk arsip historis > 7 hari, NRT untuk hari terkini)
    cur = start_date
    while cur <= end_date:
        chunk_days = min(5, (end_date - cur).days + 1)
        if chunk_days <= 0:
            break
        is_sp = cur < (today - timedelta(days=7))
        ds_n20 = "VIIRS_NOAA20_SP" if is_sp else "VIIRS_NOAA20_NRT"
        tasks.append((ds_n20, "VIIRS NOAA-20", coords_str, chunk_days, cur.isoformat()))
        cur += timedelta(days=chunk_days)

    if not tasks:
        return 0

    async def _fetch_one(ds: str, source: str, c_str: str, days: int, dt_str: str):
        path = f"{api_key}/{ds}/{c_str}/{days}/{dt_str}"
        try:
            rows = await nasa_client.fetch_rows(path)
            return normalize_hotspots(list(rows), source=source)
        except Exception as e:
            logger.debug("Fetch NASA chunk %s gagal: %s", path, e)
            return []

    results = await asyncio.gather(*[_fetch_one(*t) for t in tasks], return_exceptions=True)
    all_hotspots = []
    for r in results:
        if isinstance(r, list) and r:
            all_hotspots.extend(r)

    if all_hotspots and getattr(store, "enabled", False):
        try:
            store.upsert_hotspot_observations(all_hotspots)
            logger.info("Berhasil sinkronisasi %d hotspot baru dari NASA FIRMS untuk poligon", len(all_hotspots))
        except Exception as e:
            logger.warning("Gagal menyimpan hotspot NASA ke database: %s", e)

    return len(all_hotspots)


async def match_uploaded_polygon(
    polygon: ParsedPolygon,
    source_name: str,
    source_format: str,
    store: Any,
    warnings: list[str] | None = None,
    skipped_features: int = 0,
    nasa_client: NasaFirmsClient | None = None,
) -> PolygonMatchOutcome:
    """Cocokkan poligon yang diunggah ke titik panas NASA FIRMS sepanjang tahun berjalan."""
    if not getattr(store, "enabled", False):
        raise PolygonMatchError("Database tidak tersedia, analisis spasial tidak dapat dilanjutkan.")

    polygon_geojson_str = json.dumps(polygon.geojson)
    settings = get_settings()

    # 1. Cek irisan dengan Perhutanan Sosial (KPS)
    kps_matches = []
    try:
        kps_matches = store.check_polygon_kps_overlap(polygon_geojson_str, limit=20)
    except Exception as e:
        logger.warning("Gagal mengecek irisan KPS: %s", e)

    overlaps_kps = len(kps_matches) > 0

    # 2. Tentukan rentang waktu: 1 Januari tahun berjalan s/d sekarang
    now_utc = datetime.now(timezone.utc)
    start_of_year = date(now_utc.year, 1, 1)
    end_date = now_utc.date()

    start_date_iso = f"{start_of_year.isoformat()}T00:00:00Z"
    end_date_iso = now_utc.isoformat()

    # 3. Jika di luar KPS (atau ingin fresh data), lakukan on-demand sync NASA FIRMS
    if not overlaps_kps and settings.nasa_firms_api_key and nasa_client:
        try:
            await _sync_firms_for_bbox(
                bounds=polygon.bounds,
                start_date=start_of_year,
                end_date=end_date,
                store=store,
                nasa_client=nasa_client,
                api_key=settings.nasa_firms_api_key,
            )
        except Exception as exc:
            logger.warning("On-demand NASA sync error: %s", exc)

    # 4. Cari titik panas di dalam poligon
    raw_hotspots = store.find_hotspots_in_polygon(
        polygon_geojson=polygon_geojson_str,
        start_date=start_date_iso,
        end_date=end_date_iso,
    )

    # 5. Olah dan rangkum setiap titik panas
    by_month_counter: Counter[str] = Counter()
    by_sat_counter: Counter[str] = Counter()
    by_conf_counter: Counter[str] = Counter()

    processed_hotspots: list[dict[str, Any]] = []
    preview_rows: list[list[Any]] = []

    month_names = {
        1: "Januari",
        2: "Februari",
        3: "Maret",
        4: "April",
        5: "Mei",
        6: "Juni",
        7: "Juli",
        8: "Agustus",
        9: "September",
        10: "Oktober",
        11: "November",
        12: "Desember",
    }

    high_count = 0
    med_count = 0
    low_count = 0

    for idx, h in enumerate(raw_hotspots, start=1):
        raw_payload = h.get("raw_payload") if isinstance(h.get("raw_payload"), dict) else {}
        conf_level = confidence_category(h)
        if conf_level == "Tinggi":
            high_count += 1
        elif conf_level == "Sedang":
            med_count += 1
        else:
            low_count += 1

        by_conf_counter[conf_level] += 1

        sat = str(h.get("source") or h.get("satellite") or "VIIRS")
        by_sat_counter[sat] += 1

        detected_at = h.get("detected_at")
        wib_str = _format_wib(detected_at)

        # Hitung sebaran bulanan
        if isinstance(detected_at, datetime):
            m_label = month_names.get(detected_at.month, f"Bulan {detected_at.month}")
            by_month_counter[m_label] += 1
        elif isinstance(detected_at, str) and len(detected_at) >= 7:
            try:
                m_num = int(detected_at[5:7])
                by_month_counter[month_names.get(m_num, f"Bulan {m_num}")] += 1
            except Exception:
                by_month_counter["Lainnya"] += 1

        frp_val = raw_payload.get("frp") or h.get("brightness") or 0.0
        brightness_val = h.get("brightness") or raw_payload.get("brightness") or "-"

        item = {
            "id": h.get("id"),
            "latitude": float(h["latitude"]),
            "longitude": float(h["longitude"]),
            "detected_at": str(detected_at),
            "detected_at_wib": wib_str,
            "satellite": sat,
            "confidence": str(h.get("confidence") or ""),
            "confidence_level": conf_level,
            "brightness": brightness_val,
            "frp": frp_val,
        }
        processed_hotspots.append(item)

        preview_rows.append([
            idx,
            wib_str,
            f"{float(h['latitude']):.5f}",
            f"{float(h['longitude']):.5f}",
            sat,
            conf_level,
            str(brightness_val),
            f"{float(frp_val):.1f}" if isinstance(frp_val, (int, float)) else "-",
        ])

    total_hs = len(processed_hotspots)
    density = round((total_hs / (polygon.area_ha / 1000.0)), 2) if polygon.area_ha > 0 else 0.0

    # Pastikan urutan bulan logis
    ordered_months = [
        {"label": name, "count": by_month_counter[name]}
        for m_num, name in sorted(month_names.items())
        if m_num <= now_utc.month and by_month_counter[name] > 0
    ]

    summary = PolygonSummary(
        total_hotspots=total_hs,
        confidence_high=high_count,
        confidence_medium=med_count,
        confidence_low=low_count,
        density_per_1000ha=density,
        by_month=ordered_months if ordered_months else _rank(by_month_counter),
        by_satellite=_rank(by_sat_counter),
        by_confidence=[
            {"label": "Tinggi", "count": high_count},
            {"label": "Sedang", "count": med_count},
            {"label": "Rendah", "count": low_count},
        ],
    )

    return PolygonMatchOutcome(
        kind="polygon",
        source_name=source_name,
        source_format=source_format,
        area_ha=polygon.area_ha,
        bounds=polygon.bounds,
        overlaps_kps=overlaps_kps,
        kps_matches=kps_matches,
        summary=summary,
        hotspots=processed_hotspots,
        polygon_geojson=polygon.geojson,
        warnings=list(warnings or []),
        skipped_features=skipped_features,
        preview_rows=preview_rows[:PREVIEW_LIMIT],
        preview_truncated=len(preview_rows) > PREVIEW_LIMIT,
    )
