"""Layanan pembuatan dan pengiriman Laporan Harian Pemantauan Titik Panas (Hotspot) KPS (.pptx).

Menghasilkan paparan eksekutif 16:9 berstandar Kementerian Kehutanan & ETASENEU yang dilengkapi:
1. Grafik tren 7 hari & komparasi hari kemarin (H vs H-1) untuk membaca eskalasi risiko.
2. Grafik distribusi jam deteksi 24 jam (siklus diurnal WIB) untuk panduan waktu patroli.
3. Matriks keputusan manajemen & arahan ground check lapangan langsung.
4. Pengiriman otomatis via Telegram Bot API setiap pagi pukul 07:00 WIB.
"""

from __future__ import annotations

import asyncio
import html
import io
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from app.core.config import get_settings
from app.services.hotspot_categories import confidence_category
from app.services.postgres_store import PostgresStore

logger = logging.getLogger("hotspot.daily_report")

# ---------------------------------------------------------------- palet warna kedinasan
NAVY = RGBColor(15, 23, 42)          # #0F172A - Deep Navy Kemenhut
NAVY_LIGHT = RGBColor(30, 41, 59)    # #1E293B - Card Header
BG_CANVAS = RGBColor(248, 250, 252)  # #F8FAFC - Off-white canvas
CARD_BG = RGBColor(255, 255, 255)    # #FFFFFF - Card Background
CARD_BORDER = RGBColor(226, 232, 240)# #E2E8F0 - Subtle border
RED = RGBColor(220, 38, 38)          # #DC2626 - High confidence / Bahaya
AMBER = RGBColor(217, 119, 6)        # #D97706 - Medium confidence / Waspada
GREEN = RGBColor(22, 163, 74)        # #16A34A - Prioritas Rendah / Terkendali
BLUE = RGBColor(37, 99, 235)         # #2563EB - Accent blue
SKY = RGBColor(56, 189, 248)         # #38BDF8 - Sky blue highlight
PURPLE = RGBColor(124, 58, 237)      # #7C3AED - Night peat / smoldering
SLATE = RGBColor(100, 116, 139)      # #64748B - Text slate
MUTED = RGBColor(148, 163, 184)      # #94A3B8 - Header subdued text
WHITE = RGBColor(255, 255, 255)

FONT_FAMILY = "Calibri"

INDONESIAN_DAYS = {
    0: "Senin",
    1: "Selasa",
    2: "Rabu",
    3: "Kamis",
    4: "Jumat",
    5: "Sabtu",
    6: "Minggu",
}

INDONESIAN_MONTHS = {
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

# Pemetaan resmi Provinsi ke Wilayah Kerja Balai Perhutanan Sosial
PROVINCE_TO_BPS: dict[str, str] = {
    "Aceh": "Balai PS Medan",
    "Sumatera Utara": "Balai PS Medan",
    "Sumatera Barat": "Balai PS Medan",
    "Riau": "Balai PS Kampar",
    "Kepulauan Riau": "Balai PS Kampar",
    "Jambi": "Balai PS Kampar",
    "Kepulauan Bangka Belitung": "Balai PS Kampar",
    "Sumatera Selatan": "Balai PS Palembang",
    "Lampung": "Balai PS Palembang",
    "Bengkulu": "Balai PS Palembang",
    "Banten": "Balai PS Bogor",
    "Jawa Barat": "Balai PS Bogor",
    "DKI Jakarta": "Balai PS Bogor",
    "Jawa Tengah": "Balai PS Yogyakarta",
    "Daerah Istimewa Yogyakarta": "Balai PS Yogyakarta",
    "Di Yogyakarta": "Balai PS Yogyakarta",
    "Jawa Timur": "Balai PS Yogyakarta",
    "Kalimantan Barat": "Balai PS Banjarbaru",
    "Kalimantan Selatan": "Balai PS Banjarbaru",
    "Kalimantan Tengah": "Balai PS Banjarbaru",
    "Kalimantan Timur": "Balai PS Kutai Kertanegara",
    "Kalimantan Utara": "Balai PS Kutai Kertanegara",
    "Bali": "Balai PS Denpasar",
    "Nusa Tenggara Barat": "Balai PS Denpasar",
    "Nusa Tenggara Timur": "Balai PS Kupang",
    "Sulawesi Barat": "Balai PS Gowa",
    "Sulawesi Selatan": "Balai PS Gowa",
    "Sulawesi Tenggara": "Balai PS Gowa",
    "Sulawesi Tengah": "Balai PS Manado",
    "Sulawesi Utara": "Balai PS Manado",
    "Gorontalo": "Balai PS Manado",
    "Maluku": "Balai PS Ambon",
    "Maluku Utara": "Balai PS Ambon",
    "Papua Barat Daya": "Balai PS Ambon",
    "Papua": "Balai PS Manokwari",
    "Papua Barat": "Balai PS Manokwari",
    "Papua Pegunungan": "Balai PS Manokwari",
    "Papua Selatan": "Balai PS Manokwari",
    "Papua Tengah": "Balai PS Manokwari",
}


def _resolve_bps(raw_bps: str | None, prov: str | None) -> str:
    if raw_bps and raw_bps.strip() not in ("—", "-", "None", ""):
        clean = raw_bps.strip()
        if "Kurtanegara" in clean:
            clean = "Balai PS Kutai Kertanegara"
        return clean
    if prov and prov.strip() in PROVINCE_TO_BPS:
        return PROVINCE_TO_BPS[prov.strip()]
    return "Balai PS Terkait"


def _format_date_indonesian(d: date) -> str:
    day_name = INDONESIAN_DAYS.get(d.weekday(), "")
    month_name = INDONESIAN_MONTHS.get(d.month, "")
    return f"{day_name}, {d.day} {month_name} {d.year}"


def _add_rect(
    slide,
    x,
    y,
    w,
    h,
    fill_color: RGBColor | None = None,
    line_color: RGBColor | None = None,
    line_width=Pt(1),
    rounded: bool = False,
):
    shp_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shp_type, x, y, w, h)
    if rounded:
        try:
            shp.adjustments[0] = 0.04
        except Exception:
            pass
    shp.shadow.inherit = False
    if fill_color is not None:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill_color
    else:
        shp.fill.background()

    if line_color is not None:
        shp.line.color.rgb = line_color
        shp.line.width = line_width
    else:
        shp.line.fill.background()
    return shp


def _add_slide_header(
    slide,
    category: str,
    title: str,
    date_stamp: str | None = None,
):
    """Header bar kedinasan gelap di bagian atas slide."""
    _add_rect(slide, Inches(0), Inches(0), Inches(13.333), Inches(1.15), fill_color=NAVY)

    tb = slide.shapes.add_textbox(Inches(0.8), Inches(0.12), Inches(8.5), Inches(0.95))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

    p0 = tf.paragraphs[0]
    p0.space_after = Pt(2)
    r0 = p0.add_run()
    r0.text = category.upper()
    r0.font.name = FONT_FAMILY
    r0.font.size = Pt(9.5)
    r0.font.bold = True
    r0.font.color.rgb = SKY

    p1 = tf.add_paragraph()
    r1 = p1.add_run()
    r1.text = title
    r1.font.name = FONT_FAMILY
    r1.font.size = Pt(17)
    r1.font.bold = True
    r1.font.color.rgb = WHITE

    if date_stamp:
        tb_right = slide.shapes.add_textbox(Inches(6.8), Inches(0.2), Inches(5.7), Inches(0.75))
        tf_right = tb_right.text_frame
        tf_right.word_wrap = True
        tf_right.margin_left = tf_right.margin_top = tf_right.margin_right = tf_right.margin_bottom = 0
        p_right = tf_right.paragraphs[0]
        p_right.alignment = PP_ALIGN.RIGHT
        r_right = p_right.add_run()
        r_right.text = date_stamp
        r_right.font.name = FONT_FAMILY
        r_right.font.size = Pt(9.5)
        r_right.font.bold = True
        r_right.font.color.rgb = MUTED


def _add_slide_footer(slide):
    tb = slide.shapes.add_textbox(Inches(0.8), Inches(7.12), Inches(11.733), Inches(0.3))
    tf = tb.text_frame
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = (
        "Kementerian Kehutanan RI  ·  ETASENEU  ·  "
        "Khusus Titik Panas di Dalam Poligon KPS  ·  Akumulasi 24 Jam Kedinasan (Pukul 07:00 H-1 s.d. 07:00 H)"
    )
    r.font.name = FONT_FAMILY
    r.font.size = Pt(8)
    r.font.color.rgb = SLATE


def _generate_trend_chart_image(daily_trend: list[dict[str, Any]], delta_pct: float) -> bytes:
    """Bangun grafik batang tren 7 hari terakhir + komparasi H-1 vs H dalam resolusi tinggi."""
    fig, ax = plt.subplots(figsize=(6.2, 3.8), dpi=160)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    labels = [d["label"] for d in daily_trend]
    totals = [d["total"] for d in daily_trend]

    n = len(totals)
    colors = []
    for idx in range(n):
        if idx == n - 1:  # Hari ini (H)
            colors.append("#DC2626" if delta_pct >= 0 else "#16A34A")
        elif idx == n - 2:  # Kemarin (H-1)
            colors.append("#F59E0B")
        else:
            colors.append("#94A3B8")

    bars = ax.bar(labels, totals, color=colors, width=0.55, edgecolor="#CBD5E1", linewidth=0.5)

    max_val = max(totals, default=100)
    y_offset = max(max_val * 0.03, 10)
    for bar in bars:
        h = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            h + y_offset,
            f"{h:,}".replace(",", "."),
            ha="center",
            va="bottom",
            fontsize=7.5,
            fontweight="bold",
            color="#1E293B",
        )

    ax.set_ylim(0, max_val * 1.18)
    delta_str = f"+{delta_pct:.1f}% NAIK" if delta_pct >= 0 else f"{delta_pct:.1f}% TURUN"
    ax.set_title(
        f"Tren Harian 7 Hari & Komparasi H vs H-1 ({delta_str})",
        fontsize=9.5,
        fontweight="bold",
        pad=10,
        color="#0F172A",
    )
    ax.tick_params(labelsize=7.5, colors="#475569")
    ax.grid(axis="y", linestyle="--", alpha=0.5, color="#E2E8F0")

    # Garis batas visual H-1 dan H
    for spine in ax.spines.values():
        spine.set_color("#E2E8F0")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _generate_hourly_chart_image(hourly_data: list[dict[str, Any]], peak_day: int, peak_night: int) -> bytes:
    """Bangun grafik distribusi jam deteksi 24 jam (siklus diurnal) dengan highlight waktu rawan."""
    fig, ax = plt.subplots(figsize=(6.2, 4.6), dpi=160)
    fig.patch.set_facecolor("#FFFFFF")
    ax.set_facecolor("#FFFFFF")

    hours = [d["hour"] for d in hourly_data]
    counts = [d["count"] for d in hourly_data]

    colors = []
    for h in hours:
        if 11 <= h <= 14:
            colors.append("#DC2626")  # Puncak Siang (Flaming/Api Menyala)
        elif h >= 23 or h <= 2:
            colors.append("#7C3AED")  # Puncak Dini Hari (Bara Gambut/Smoldering)
        else:
            colors.append("#94A3B8")

    ax.bar(hours, counts, color=colors, width=0.68, edgecolor="#CBD5E1", linewidth=0.5)

    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)], fontsize=7.5)
    ax.set_title(
        "Distribusi Jam Deteksi 24 Jam (Siklus Harian WIB)",
        fontsize=9.5,
        fontweight="bold",
        pad=10,
        color="#0F172A",
    )
    ax.tick_params(labelsize=7.5, colors="#475569")
    ax.grid(axis="y", linestyle="--", alpha=0.5, color="#E2E8F0")

    for spine in ax.spines.values():
        spine.set_color("#E2E8F0")

    # Keterangan Legenda Visual
    ax.plot([], [], color="#DC2626", label="Puncak Siang: Api Aktif / Flaming (11:00–14:00)")
    ax.plot([], [], color="#7C3AED", label="Puncak Malam: Bara Gambut / Smoldering (23:00–02:00)")
    ax.legend(loc="upper right", fontsize=7.0, frameon=True, facecolor="#F8FAFC", edgecolor="#E2E8F0")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


class DailyReportService:
    def __init__(self, store: PostgresStore | None = None) -> None:
        self.settings = get_settings()
        self.store = store or PostgresStore(self.settings.database_url)

    def collect_daily_hotspot_data(
        self,
        target_date: date | None = None,
        lookback_hours: int = 24,
    ) -> dict[str, Any]:
        """Kumpulkan data agregasi titik panas 24 jam terakhir, perbandingan H-1, tren 7 hari, dan jam deteksi."""
        jakarta_tz = ZoneInfo("Asia/Jakarta")
        now_jkt = datetime.now(jakarta_tz)

        if target_date is not None:
            end_time = datetime.combine(target_date, time(7, 0), tzinfo=jakarta_tz)
            start_time = end_time - timedelta(hours=lookback_hours)
            report_date = target_date
        else:
            report_date = now_jkt.date()
            end_time = now_jkt
            start_time = end_time - timedelta(hours=lookback_hours)

        report_date_str = _format_date_indonesian(report_date)
        time_window_str = f"{start_time.strftime('%d/%m/%Y %H:%M')} s.d. {end_time.strftime('%d/%m/%Y %H:%M')} WIB"

        # Rentang waktu H-1 (Kemarin)
        start_time_y = start_time - timedelta(hours=24)
        end_time_y = start_time
        seven_days_start = end_time - timedelta(days=7)

        raw_rows: list[dict[str, Any]] = []
        yesterday_total = 0
        yesterday_high = 0
        trend_rows_raw: list[dict[str, Any]] = []
        hourly_counts: dict[int, int] = defaultdict(int)

        if self.store.enabled:
            try:
                with self.store.connection() as conn:
                    with conn.cursor() as cur:
                        # 1. Hotspot 24 jam hari ini - KHUSUS DI DALAM POLIGON KPS
                        cur.execute(
                            """
                            SELECT 
                                h.id, h.latitude, h.longitude, h.detected_at, h.confidence,
                                h.satellite, h.source, h.agency_name,
                                (h.raw_payload->>'frp')::float as frp,
                                h.raw_payload->>'province_name' as prov,
                                h.raw_payload->'polygon_metadata' as poly_meta,
                                EXTRACT(HOUR FROM h.detected_at AT TIME ZONE 'Asia/Jakarta')::int as hr
                            FROM hotspot_observations h
                            WHERE h.detected_at >= %s AND h.detected_at < %s
                              AND (h.agency_name NOT LIKE 'Luar Kawasan%%' AND COALESCE((h.raw_payload->>'is_perimeter')::boolean, false) = false)
                            ORDER BY (h.raw_payload->>'frp')::float DESC NULLS LAST, h.detected_at DESC;
                            """,
                            (start_time, end_time),
                        )
                        raw_rows = [dict(r) for r in cur.fetchall()]

                        # 2. Statistik hari kemarin (H-1) - KHUSUS DI DALAM POLIGON KPS
                        cur.execute(
                            """
                            SELECT 
                                COUNT(*) as total,
                                COUNT(*) FILTER (WHERE confidence IN ('high', 'h') OR (confidence ~ '^[0-9]+$' AND confidence::int > 80)) as high_count
                            FROM hotspot_observations
                            WHERE detected_at >= %s AND detected_at < %s
                              AND (agency_name NOT LIKE 'Luar Kawasan%%' AND COALESCE((raw_payload->>'is_perimeter')::boolean, false) = false);
                            """,
                            (start_time_y, end_time_y),
                        )
                        y_row = cur.fetchone()
                        if y_row:
                            yesterday_total = int(y_row["total"] or 0)
                            yesterday_high = int(y_row["high_count"] or 0)

                        # 3. Tren 7 hari terakhir - KHUSUS DI DALAM POLIGON KPS
                        cur.execute(
                            """
                            SELECT 
                                (date_trunc('day', detected_at AT TIME ZONE 'Asia/Jakarta'))::date as day_date,
                                COUNT(*) as total
                            FROM hotspot_observations
                            WHERE detected_at >= %s AND detected_at < %s
                              AND (agency_name NOT LIKE 'Luar Kawasan%%' AND COALESCE((raw_payload->>'is_perimeter')::boolean, false) = false)
                            GROUP BY day_date
                            ORDER BY day_date;
                            """,
                            (seven_days_start, end_time),
                        )
                        trend_rows_raw = [dict(r) for r in cur.fetchall()]
            except Exception as e:
                logger.error("Gagal query hotspot harian dari database: %s", e)

        total_hotspots = len(raw_rows)
        confidence_counts = {"Tinggi": 0, "Sedang": 0, "Rendah": 0}
        bps_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"high": 0, "medium": 0, "low": 0, "max_frp": 0.0, "agencies": set()}
        )
        agency_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "high": 0,
                "medium": 0,
                "low": 0,
                "max_frp": 0.0,
                "sample_point": None,
                "bps": "Lainnya",
                "wilayah": "Indonesia",
            }
        )

        frp_values: list[float] = []

        inside_kps_count = 0
        buffer_kps_count = 0

        for r in raw_rows:
            conf_cat = confidence_category(r)
            confidence_counts[conf_cat] = confidence_counts.get(conf_cat, 0) + 1

            # Hitung distribusi jam
            hr = r.get("hr")
            if hr is not None:
                hourly_counts[int(hr)] += 1

            frp = float(r.get("frp") or 0.0)
            if frp > 0:
                frp_values.append(frp)

            poly_meta = r.get("poly_meta") or {}
            prov_name = (poly_meta.get("NAMA_PROV") or r.get("prov") or "").strip()
            raw_bps = poly_meta.get("WILKER_BPS") or poly_meta.get("wilker_bps")
            bps_name = _resolve_bps(raw_bps, prov_name)

            raw_agency = (r.get("agency_name") or poly_meta.get("LEMBAGA") or "Areal KPS").strip()
            if raw_agency.startswith("Luar Kawasan (") and raw_agency.endswith(")"):
                inner_agency = raw_agency[len("Luar Kawasan ("):-1].strip()
                agency = f"{inner_agency} (Buffer Keliling)"
                buffer_kps_count += 1
            else:
                agency = raw_agency
                inside_kps_count += 1

            loc_parts = []
            if poly_meta.get("NAMA_DESA"):
                loc_parts.append(f"Desa {poly_meta['NAMA_DESA']}")
            if poly_meta.get("NAMA_KEC"):
                loc_parts.append(f"Kec. {poly_meta['NAMA_KEC']}")
            if poly_meta.get("NAMA_KAB"):
                loc_parts.append(f"Kab. {poly_meta['NAMA_KAB']}")
            if prov_name:
                loc_parts.append(prov_name)
            wilayah_text = ", ".join(loc_parts) if loc_parts else (prov_name or "Indonesia")

            bps_item = bps_stats[bps_name]
            if conf_cat == "Tinggi":
                bps_item["high"] += 1
            elif conf_cat == "Sedang":
                bps_item["medium"] += 1
            else:
                bps_item["low"] += 1
            if frp > bps_item["max_frp"]:
                bps_item["max_frp"] = round(frp, 1)
            bps_item["agencies"].add(agency)

            ag_item = agency_stats[agency]
            if conf_cat == "Tinggi":
                ag_item["high"] += 1
            elif conf_cat == "Sedang":
                ag_item["medium"] += 1
            else:
                ag_item["low"] += 1
            if frp > ag_item["max_frp"]:
                ag_item["max_frp"] = round(frp, 1)
                ag_item["sample_point"] = (r["latitude"], r["longitude"])
            elif ag_item["sample_point"] is None:
                ag_item["sample_point"] = (r["latitude"], r["longitude"])
            ag_item["bps"] = bps_name
            ag_item["wilayah"] = wilayah_text

        # Komparasi Hari Kemarin (H vs H-1)
        delta_total = total_hotspots - yesterday_total
        delta_pct = (delta_total / yesterday_total * 100.0) if yesterday_total else 0.0
        delta_high = confidence_counts["Tinggi"] - yesterday_high
        delta_high_pct = (delta_high / yesterday_high * 100.0) if yesterday_high else 0.0

        if delta_pct > 5.0:
            trend_label = f"ESKALASI NAIK (+{delta_pct:.1f}%)"
            trend_color = RED
            trend_icon = "🔺"
        elif delta_pct < -5.0:
            trend_label = f"MELANDAI TURUN ({delta_pct:.1f}%)"
            trend_color = GREEN
            trend_icon = "🔻"
        else:
            trend_label = f"STABIL ({delta_pct:+.1f}%)"
            trend_color = AMBER
            trend_icon = "➡️"

        # Susun Tren 7 Hari
        daily_trend_list = []
        if trend_rows_raw:
            for idx, tr in enumerate(trend_rows_raw):
                d_date = tr["day_date"]
                d_str = d_date.strftime("%d %b")
                if idx == len(trend_rows_raw) - 1:
                    lbl = f"{d_str} (H)"
                elif idx == len(trend_rows_raw) - 2:
                    lbl = f"{d_str} (H-1)"
                else:
                    lbl = d_str
                daily_trend_list.append({"label": lbl, "total": int(tr["total"])})
        else:
            daily_trend_list = [
                {"label": "H-2", "total": yesterday_total},
                {"label": "H-1", "total": yesterday_total},
                {"label": "H (Hari Ini)", "total": total_hotspots},
            ]

        # Susun Distribusi Jam
        hourly_data_list = []
        peak_day_hour = 13
        peak_night_hour = 1
        max_day_val = -1
        max_night_val = -1
        for h in range(24):
            c = hourly_counts[h]
            hourly_data_list.append({"hour": h, "count": c})
            if 10 <= h <= 15 and c > max_day_val:
                max_day_val = c
                peak_day_hour = h
            if (h >= 22 or h <= 3) and c > max_night_val:
                max_night_val = c
                peak_night_hour = h

        # Balai PS list
        balai_list = []
        for bps_key, stats in bps_stats.items():
            h_count = stats["high"]
            m_count = stats["medium"]
            score = (h_count * 2) + (m_count * 1)
            total_priority = h_count + m_count

            if score >= 15 or h_count >= 2:
                priority_status = "Prioritas Tinggi"
            elif score >= 6:
                priority_status = "Prioritas Sedang"
            else:
                priority_status = "Prioritas Rendah"

            balai_list.append({
                "name": bps_key,
                "high_count": h_count,
                "medium_count": m_count,
                "low_count": stats["low"],
                "total_priority": total_priority,
                "priority_score": score,
                "priority_status": priority_status,
                "max_frp": stats["max_frp"],
                "agency_count": len(stats["agencies"]),
            })
        balai_list.sort(key=lambda x: (x["priority_score"], x["high_count"], x["max_frp"]), reverse=True)

        # KPS list
        kps_list = []
        for ag_name, stats in agency_stats.items():
            h_count = stats["high"]
            m_count = stats["medium"]
            score = (h_count * 2) + (m_count * 1)
            lat, lon = stats["sample_point"] or (0.0, 0.0)

            if score >= 15 or h_count >= 2:
                priority_status = "Prioritas Tinggi"
            elif score >= 6:
                priority_status = "Prioritas Sedang"
            else:
                priority_status = "Prioritas Rendah"

            gmaps_url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"

            kps_list.append({
                "name": ag_name,
                "bps": stats["bps"],
                "wilayah": stats["wilayah"],
                "high_count": h_count,
                "medium_count": m_count,
                "low_count": stats["low"],
                "total": h_count + m_count + stats["low"],
                "priority_score": score,
                "priority_status": priority_status,
                "max_frp": stats["max_frp"],
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "google_maps_url": gmaps_url,
            })
        kps_list.sort(key=lambda x: (x["priority_score"], x["max_frp"]), reverse=True)

        max_frp = max(frp_values, default=0.0)
        avg_frp = (sum(frp_values) / len(frp_values)) if frp_values else 0.0

        # Ambil data dari Menu Peringatan Dini (Early Warning Service & FTRI)
        early_warning_kps_list = []
        ew_summary_data = {
            "strict_reburn_kps": 0,
            "expanding_kps": 0,
            "ew_new_kps": 0,
            "total_burned_ha": 0.0,
        }
        try:
            from app.services.early_warning_service import EarlyWarningService

            ew_svc = EarlyWarningService(store=self.store)
            ew_summary = ew_svc.get_summary_metrics()
            b_stats = ew_summary.get("burned_area_stats", {})
            e_stats = ew_summary.get("early_warning_stats", {})

            ew_summary_data = {
                "strict_reburn_kps": int(b_stats.get("strict_reburn_kps_today", 0)),
                "expanding_kps": int(b_stats.get("active_today", 0)),
                "ew_new_kps": int(e_stats.get("active_today", 0)),
                "total_burned_ha": round(float(b_stats.get("total_burned_ha", 0.0)), 1),
            }

            # 1. KPS dari kategori Terbakar Kembali (Re-burn & Ekspansi) - AMBIL SEMUA
            burned_active_items = ew_svc.get_kps_analysis_list(category="burned_active_today", limit=500)
            burned_kps_list = []
            for it in burned_active_items:
                is_strict = it.get("hotspots_today_strict_reburn", 0) > 0
                cat_label = "Strict Re-burn" if is_strict else "Ekspansi Bara"
                it_copy = dict(it)
                it_copy["ew_category"] = cat_label
                burned_kps_list.append(it_copy)

            burned_kps_list.sort(
                key=lambda x: (
                    1 if x.get("hotspots_today_strict_reburn", 0) > 0 else 0,
                    x.get("hotspots_today") or 0,
                    x.get("ftri_score") or 0.0,
                ),
                reverse=True,
            )

            # 2. KPS dari kategori Peringatan Dini Baru (early_warning_today) - AMBIL SEMUA
            ew_active_items = ew_svc.get_kps_analysis_list(category="early_warning_today", limit=500)
            ew_new_list = []
            for it in ew_active_items:
                it_copy = dict(it)
                it_copy["ew_category"] = "Peringatan Dini Baru"
                ew_new_list.append(it_copy)

            ew_new_list.sort(
                key=lambda x: (
                    x.get("ftri_score") or 0.0,
                    x.get("hotspots_today") or 0,
                ),
                reverse=True,
            )

            early_warning_kps_list = burned_kps_list + ew_new_list

            # Query titik centroid poligon untuk Google Maps presisi
            poly_ids = [k["id"] for k in early_warning_kps_list if k.get("id")]
            if poly_ids and self.store.enabled:
                with self.store.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT id, ST_Y(ST_Centroid(geometry)) as lat, ST_X(ST_Centroid(geometry)) as lon
                            FROM polygon_metadata
                            WHERE id = ANY(%s);
                            """,
                            (poly_ids,),
                        )
                        coords_map = {r["id"]: (float(r["lat"]), float(r["lon"])) for r in cur.fetchall()}

                for k in early_warning_kps_list:
                    lat, lon = coords_map.get(k["id"], (0.0, 0.0))
                    k["latitude"] = round(lat, 6)
                    k["longitude"] = round(lon, 6)
                    k["google_maps_url"] = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
                    ftri = float(k.get("ftri_score") or 0.0)
                    k["ftri_label"] = "Ekstrem" if ftri >= 70 else ("Tinggi" if ftri >= 50 else ("Sedang" if ftri >= 30 else "Rendah"))

        except Exception as e:
            logger.error("Gagal mengambil daftar KPS menu peringatan dini: %s", e)
            burned_kps_list = []
            ew_new_list = []

        high_and_med = confidence_counts["Tinggi"] + confidence_counts["Sedang"]
        if confidence_counts["Tinggi"] >= 5 or max_frp > 100 or high_and_med >= 50 or delta_pct > 20:
            status_siaga = "SIAGA DARURAT"
            siaga_color = RED
        elif confidence_counts["Tinggi"] >= 1 or max_frp > 30 or high_and_med >= 10:
            status_siaga = "SIAGA / WASPADA"
            siaga_color = AMBER
        elif high_and_med > 0:
            status_siaga = "WASPADA TERKENDALI"
            siaga_color = GREEN
        else:
            status_siaga = "TERKENDALI / AMAN"
            siaga_color = GREEN

        return {
            "report_date": report_date.isoformat(),
            "report_date_str": report_date_str,
            "report_time_str": "07:00 WIB",
            "time_window_str": time_window_str,
            "total_hotspots": total_hotspots,
            "inside_kps_count": inside_kps_count,
            "buffer_kps_count": buffer_kps_count,
            "high_count": confidence_counts["Tinggi"],
            "medium_count": confidence_counts["Sedang"],
            "low_count": confidence_counts["Rendah"],
            "yesterday_total": yesterday_total,
            "yesterday_high": yesterday_high,
            "delta_total": delta_total,
            "delta_pct": round(delta_pct, 1),
            "delta_high": delta_high,
            "delta_high_pct": round(delta_high_pct, 1),
            "trend_label": trend_label,
            "trend_color": trend_color,
            "trend_icon": trend_icon,
            "daily_trend": daily_trend_list,
            "hourly_data": hourly_data_list,
            "peak_day_hour": peak_day_hour,
            "peak_night_hour": peak_night_hour,
            "max_frp": round(max_frp, 1),
            "avg_frp": round(avg_frp, 1),
            "status_siaga": status_siaga,
            "siaga_color": siaga_color,
            "balai_list": balai_list,
            "kps_list": kps_list,
            "burned_kps_list": burned_kps_list,
            "ew_new_list": ew_new_list,
            "early_warning_summary": ew_summary_data,
            "early_warning_kps_list": early_warning_kps_list,
            "total_ew_active_today": len(early_warning_kps_list),
            "has_data": total_hotspots > 0,
        }

    def generate_daily_hotspot_pptx(self, data: dict[str, Any]) -> bytes:
        """Bangun presentasi PowerPoint 16:9 widescreen berisi visual grafik komparasi & matriks keputusan."""
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        blank_layout = prs.slide_layouts[6]

        # Buat grafik gambar (in-memory)
        trend_img_bytes = _generate_trend_chart_image(data.get("daily_trend", []), data.get("delta_pct", 0.0))
        hourly_img_bytes = _generate_hourly_chart_image(
            data.get("hourly_data", []),
            data.get("peak_day_hour", 13),
            data.get("peak_night_hour", 1),
        )

        # =====================================================================
        # SLIDE 1: COVER RESMI & STATUS SIAGA UTAMA
        # =====================================================================
        s1 = prs.slides.add_slide(blank_layout)
        _add_rect(s1, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=NAVY)
        _add_rect(s1, Inches(0), Inches(0), Inches(13.333), Inches(0.12), fill_color=SKY)

        tb_cov = s1.shapes.add_textbox(Inches(1.0), Inches(1.1), Inches(11.333), Inches(3.2))
        tf_cov = tb_cov.text_frame
        tf_cov.word_wrap = True
        tf_cov.margin_left = tf_cov.margin_top = tf_cov.margin_right = tf_cov.margin_bottom = 0

        p_kem = tf_cov.paragraphs[0]
        p_kem.space_after = Pt(10)
        r_kem = p_kem.add_run()
        r_kem.text = "KEMENTERIAN KEHUTANAN REPUBLIK INDONESIA"
        r_kem.font.name = FONT_FAMILY
        r_kem.font.size = Pt(13)
        r_kem.font.bold = True
        r_kem.font.color.rgb = MUTED

        p_tit = tf_cov.add_paragraph()
        p_tit.space_after = Pt(8)
        r_tit = p_tit.add_run()
        r_tit.text = "LAPORAN HARIAN PEMANTAUAN TITIK PANAS (HOTSPOT) AREAL KPS"
        r_tit.font.name = FONT_FAMILY
        r_tit.font.size = Pt(28)
        r_tit.font.bold = True
        r_tit.font.color.rgb = WHITE

        p_sub = tf_cov.add_paragraph()
        p_sub.space_after = Pt(16)
        r_sub = p_sub.add_run()
        r_sub.text = "Khusus Titik Panas di Dalam Poligon Perizinan Perhutanan Sosial (KPS)"
        r_sub.font.name = FONT_FAMILY
        r_sub.font.size = Pt(16)
        r_sub.font.color.rgb = SKY

        # Card Status Siaga Utama & Sorotan Keputusan
        _add_rect(s1, Inches(1.0), Inches(4.1), Inches(11.333), Inches(2.05), fill_color=NAVY_LIGHT, rounded=True)
        tb_meta = s1.shapes.add_textbox(Inches(1.3), Inches(4.2), Inches(10.7), Inches(1.85))
        tf_meta = tb_meta.text_frame
        tf_meta.word_wrap = True
        tf_meta.margin_left = tf_meta.margin_top = tf_meta.margin_right = tf_meta.margin_bottom = 0

        p_s = tf_meta.paragraphs[0]
        p_s.space_after = Pt(3)
        r_s1 = p_s.add_run()
        r_s1.text = f"🚨 STATUS SIAGA NASIONAL: {data.get('status_siaga', 'WASPADA')}  |  "
        r_s1.font.name = FONT_FAMILY
        r_s1.font.size = Pt(13)
        r_s1.font.bold = True
        r_s1.font.color.rgb = data.get("siaga_color") or RED

        r_s2 = p_s.add_run()
        r_s2.text = f"Tren: {data.get('trend_icon', '➡️')} {data.get('trend_label', 'STABIL')}"
        r_s2.font.name = FONT_FAMILY
        r_s2.font.size = Pt(12)
        r_s2.font.bold = True
        r_s2.font.color.rgb = WHITE

        p_m1 = tf_meta.add_paragraph()
        p_m1.space_after = Pt(3)
        r_m1 = p_m1.add_run()
        r_m1.text = (
            f"⏱️ Jendela Waktu: {data.get('time_window_str', '')} (Akumulasi 24 Jam Kedinasan)  ·  "
            f"Total: {data.get('total_hotspots', 0):,} Titik di Dalam KPS (vs {data.get('yesterday_total', 0):,} H-1)".replace(",", ".")
        )
        r_m1.font.name = FONT_FAMILY
        r_m1.font.size = Pt(10.5)
        r_m1.font.bold = True
        r_m1.font.color.rgb = SKY

        p_m_lingkup = tf_meta.add_paragraph()
        p_m_lingkup.space_after = Pt(3)
        r_m_lingkup = p_m_lingkup.add_run()
        r_m_lingkup.text = "📍 Lingkup Spasial: Khusus titik panas yang berada tepat DI DALAM batas definitif poligon KPS (area luar/buffer keliling tidak dihitung)."
        r_m_lingkup.font.name = FONT_FAMILY
        r_m_lingkup.font.size = Pt(9.5)
        r_m_lingkup.font.color.rgb = WHITE

        p_m2 = tf_meta.add_paragraph()
        r_m2 = p_m2.add_run()
        top_3_balai = ", ".join([b["name"] for b in data.get("balai_list", [])[:3]]) if data.get("balai_list") else "Nihil"
        r_m2.text = f"🎯 Fokus Wilayah Intervensi Hari Ini: {top_3_balai} (Alokasi Patroli Prioritas)"
        r_m2.font.name = FONT_FAMILY
        r_m2.font.size = Pt(10)
        r_m2.font.bold = True
        r_m2.font.color.rgb = MUTED

        # Disclaimer
        tb_disc = s1.shapes.add_textbox(Inches(1.0), Inches(6.35), Inches(11.333), Inches(0.7))
        tf_disc = tb_disc.text_frame
        tf_disc.word_wrap = True
        tf_disc.margin_left = tf_disc.margin_top = tf_disc.margin_right = tf_disc.margin_bottom = 0
        p_disc = tf_disc.paragraphs[0]
        r_disc = p_disc.add_run()
        r_disc.text = (
            "CATATAN KEDINASAN: Data hotspot disaring khusus di dalam poligon izin Perhutanan Sosial (KPS) "
            "berdasarkan rekaman sensor satelit NASA FIRMS selama 24 jam buku harian kedinasan (pukul 07:00 WIB H-1 s.d. 07:00 WIB H). "
            "Titik panas merupakan anomali termal untuk verifikasi lapangan (ground check) dan dasar komando patroli Satgas."
        )
        r_disc.font.name = FONT_FAMILY
        r_disc.font.size = Pt(8.5)
        r_disc.font.italic = True
        r_disc.font.color.rgb = MUTED

        # =====================================================================
        # SLIDE 2: PERBANDINGAN HARI KEMARIN (H vs H-1) & TREN 7 HARI
        # =====================================================================
        s2 = prs.slides.add_slide(blank_layout)
        _add_rect(s2, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s2,
            category="Evaluasi Eskalasi Risiko",
            title="Analisis Tren Harian & Perbandingan Hari Kemarin (H vs H-1)",
            date_stamp=f"{data.get('report_date_str', '')} • 07:00 WIB",
        )

        # 4 KPI Cards dengan Delta H vs H-1
        card_w = Inches(2.78)
        card_h = Inches(1.4)
        card_y = Inches(1.35)
        gap = Inches(0.2)
        start_x = Inches(0.8)

        kpis = [
            (
                "HOTSPOT DALAM KPS (24 JAM)",
                f"{data.get('total_hotspots', 0):,}".replace(",", "."),
                f"Kemarin: {data.get('yesterday_total', 0):,} | {data.get('trend_icon', '➡️')} {data.get('delta_pct', 0.0):+.1f}%",
                NAVY,
            ),
            (
                "KEYAKINAN TINGGI (HIGH)",
                f"{data.get('high_count', 0):,}".replace(",", "."),
                f"Kemarin: {data.get('yesterday_high', 0):,} | Fokus Utama",
                RED if data.get("high_count", 0) > 0 else AMBER,
            ),
            (
                "FRP MAKSIMUM",
                f"{data.get('max_frp', 0.0)} MW",
                f"Rata-rata: {data.get('avg_frp', 0.0)} MW",
                RED if data.get("max_frp", 0.0) > 30 else AMBER,
            ),
            (
                "STATUS SIAGA HARIAN",
                data.get("status_siaga", "WASPADA"),
                f"{len(data.get('balai_list', []))} Balai PS Terindikasi",
                data.get("siaga_color") or GREEN,
            ),
        ]

        for i, (kpi_title, kpi_val, kpi_sub, kpi_color) in enumerate(kpis):
            cx = start_x + (i * (card_w + gap))
            _add_rect(s2, cx, card_y, card_w, card_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)
            _add_rect(s2, cx, card_y, card_w, Inches(0.08), fill_color=kpi_color, rounded=True)

            tb_k = s2.shapes.add_textbox(cx + Inches(0.14), card_y + Inches(0.14), card_w - Inches(0.28), card_h - Inches(0.22))
            tf_k = tb_k.text_frame
            tf_k.word_wrap = True
            tf_k.margin_left = tf_k.margin_top = tf_k.margin_right = tf_k.margin_bottom = 0

            p_kt = tf_k.paragraphs[0]
            r_kt = p_kt.add_run()
            r_kt.text = kpi_title
            r_kt.font.name = FONT_FAMILY
            r_kt.font.size = Pt(8.5)
            r_kt.font.bold = True
            r_kt.font.color.rgb = SLATE

            p_kv = tf_k.add_paragraph()
            p_kv.space_before = Pt(3)
            p_kv.space_after = Pt(2)
            r_kv = p_kv.add_run()
            r_kv.text = kpi_val
            r_kv.font.name = FONT_FAMILY
            r_kv.font.size = Pt(19)
            r_kv.font.bold = True
            r_kv.font.color.rgb = kpi_color

            p_ks = tf_k.add_paragraph()
            r_ks = p_ks.add_run()
            r_ks.text = kpi_sub
            r_ks.font.name = FONT_FAMILY
            r_ks.font.size = Pt(8.5)
            r_ks.font.color.rgb = SLATE

        # Baris Bawah: Grafik Matplotlib (Kiri) + Rekomendasi Keputusan (Kanan)
        plot_y = Inches(2.95)
        plot_w = Inches(6.0)
        plot_h = Inches(3.9)

        # Sisipkan Gambar Grafik Tren
        s2.shapes.add_picture(io.BytesIO(trend_img_bytes), Inches(0.8), plot_y, plot_w, plot_h)

        # Kartu Rekomendasi Keputusan Berdasarkan Tren (Kanan)
        right_x = Inches(7.05)
        right_w = Inches(5.48)
        _add_rect(s2, right_x, plot_y, right_w, plot_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)

        tb_dec = s2.shapes.add_textbox(right_x + Inches(0.25), plot_y + Inches(0.2), right_w - Inches(0.5), plot_h - Inches(0.4))
        tf_dec = tb_dec.text_frame
        tf_dec.word_wrap = True
        tf_dec.margin_left = tf_dec.margin_top = tf_dec.margin_right = tf_dec.margin_bottom = 0

        p_dtit = tf_dec.paragraphs[0]
        p_dtit.space_after = Pt(8)
        r_dtit = p_dtit.add_run()
        r_dtit.text = "Rekomendasi Keputusan Berdasarkan Tren"
        r_dtit.font.name = FONT_FAMILY
        r_dtit.font.size = Pt(13)
        r_dtit.font.bold = True
        r_dtit.font.color.rgb = NAVY

        trend_lbl = data.get("trend_label", "STABIL")
        delta_p = data.get("delta_pct", 0.0)
        delta_t = data.get("delta_total", 0)
        h_cnt = data.get("high_count", 0)
        delta_h = data.get("delta_high", 0)
        b_list = data.get("balai_list", [])
        top_b_name = b_list[0]["name"] if b_list else "Terkait"

        decisions_s2 = [
            f"Dinamika Risiko: Jumlah deteksi {trend_lbl} sebesar {delta_p:+.1f}% ({delta_t:+d} titik) dibanding hari kemarin.",
            f"Lonjakan Keyakinan Tinggi: Hotspot berkategori High tercatat {h_cnt} titik (delta: {delta_h:+d} titik). Ini mengindikasikan api berkobar aktif yang butuh intervensi segera.",
            f"Konsentrasi Wilayah: Wilayah kerja {top_b_name} menyumbang beban pantauan terbesar hari ini.",
            "Arah Tindakan Komando:\n   • Tingkatkan patroli siaga di KPS rawan eskalasi.\n   • Aktifkan koordinasi lintas sektor (KPH & BPBD/Satgas Karhutla Daops).",
        ]

        for d in decisions_s2:
            p_d = tf_dec.add_paragraph()
            p_d.space_after = Pt(6)
            r_d = p_d.add_run()
            r_d.text = f"•  {d}"
            r_d.font.name = FONT_FAMILY
            r_d.font.size = Pt(9.5)
            r_d.font.color.rgb = NAVY_LIGHT

        _add_slide_footer(s2)

        # =====================================================================
        # SLIDE 3: DISTRIBUSI JAM DETEKSI & JENDELA WAKTU KRITIS PATROLI
        # =====================================================================
        s3 = prs.slides.add_slide(blank_layout)
        _add_rect(s3, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s3,
            category="Siklus Harian & Jadwal Patroli",
            title="Distribusi Jam Deteksi 24 Jam & Jendela Waktu Kritis Patroli",
            date_stamp=f"{data['report_date_str']} • 07:00 WIB",
        )

        # Sisipkan Gambar Grafik Distribusi Jam (Kiri)
        s3_plot_y = Inches(1.4)
        s3_plot_w = Inches(6.0)
        s3_plot_h = Inches(5.4)
        s3.shapes.add_picture(io.BytesIO(hourly_img_bytes), Inches(0.8), s3_plot_y, s3_plot_w, s3_plot_h)

        # Panduan Taktis Jadwal Operasi Lapangan (Kanan)
        s3_right_x = Inches(7.05)
        s3_right_w = Inches(5.48)
        _add_rect(s3, s3_right_x, s3_plot_y, s3_right_w, s3_plot_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)

        tb_hr = s3.shapes.add_textbox(s3_right_x + Inches(0.25), s3_plot_y + Inches(0.22), s3_right_w - Inches(0.5), s3_plot_h - Inches(0.44))
        tf_hr = tb_hr.text_frame
        tf_hr.word_wrap = True
        tf_hr.margin_left = tf_hr.margin_top = tf_hr.margin_right = tf_hr.margin_bottom = 0

        p_htit = tf_hr.paragraphs[0]
        p_htit.space_after = Pt(8)
        r_htit = p_htit.add_run()
        r_htit.text = "Pedoman Jam Operasi Lapangan Satgas"
        r_htit.font.name = FONT_FAMILY
        r_htit.font.size = Pt(13)
        r_htit.font.bold = True
        r_htit.font.color.rgb = NAVY

        pk_day = data.get("peak_day_hour", 13)
        pk_night = data.get("peak_night_hour", 1)
        hour_guidance = [
            f"☀️ Puncak Siang (11:00 – 14:00 WIB) — Api Aktif / Flaming:\n   Puncak deteksi termal satelit terjadi pada pukul {pk_day:02d}:00 WIB. Suhu lingkungan mencapai titik tertinggi dan kelembapan rendah. Api sangat rentan menyebar cepat.",
            f"🌙 Puncak Dini Hari (23:00 – 02:00 WIB) — Bara Gambut / Smoldering:\n   Terdeteksi anomali persisten pada pukul {pk_night:02d}:00 WIB. Ini mencirikan api bawah tanah (gambut) yang membara tanpa nyala terbuka dan menghasilkan kabut asap pekat.",
            "⏰ Waktu Efektif Pengerahan Personel:\n   Regu patroli terpadu wajib diberangkatkan maksimal pukul 08:30 WIB agar tiba dan mendirikan pos sekat bakar sebelum jam penyalaan puncak tengah hari.",
            "🚁 Operasi Pemantauan Drone:\n   Jadwal terbaik penerbangan drone thermal: pukul 10:00 – 13:00 WIB untuk deteksi perimeter asap awal.",
        ]

        for g in hour_guidance:
            p_g = tf_hr.add_paragraph()
            p_g.space_after = Pt(7)
            r_g = p_g.add_run()
            r_g.text = f"•  {g}"
            r_g.font.name = FONT_FAMILY
            r_g.font.size = Pt(9.5)
            r_g.font.color.rgb = NAVY_LIGHT

        _add_slide_footer(s3)

        # =====================================================================
        # HELPER: RENDER TABEL KPS PERINGATAN DINI DI ATAS SLIDE
        # =====================================================================
        def _render_kps_table_on_slide(
            slide,
            items_chunk: list[dict[str, Any]],
            start_no: int,
            tbl_y: Any,
            tbl_h: Any,
            empty_msg: str = "Nihil unit KPS dalam status ancaman peringatan dini hari ini.",
        ):
            tbl_w = Inches(11.733)
            num_rows = max(len(items_chunk) + 1, 2)
            tbl_shape = slide.shapes.add_table(num_rows, 8, Inches(0.8), tbl_y, tbl_w, tbl_h)
            tbl = tbl_shape.table

            ew_col_widths = [
                Inches(0.5),   # No
                Inches(2.6),   # Nama Lembaga KPS & Skema
                Inches(1.8),   # Balai PS
                Inches(2.133), # Wilayah Administrasi
                Inches(1.4),   # Kategori Ancaman
                Inches(0.9),   # Hotspot Hari Ini
                Inches(1.1),   # Skor FTRI
                Inches(1.3),   # Navigasi
            ]
            for idx, w in enumerate(ew_col_widths):
                tbl.columns[idx].width = w

            ew_headers = [
                "NO",
                "NAMA LEMBAGA KPS",
                "BALAI PS",
                "WILAYAH",
                "KATEGORI ANCAMAN",
                "HARI INI",
                "SKOR FTRI",
                "NAVIGASI",
            ]
            for col_idx, h_text in enumerate(ew_headers):
                cell = tbl.cell(0, col_idx)
                cell.fill.solid()
                cell.fill.fore_color.rgb = NAVY
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                p = cell.text_frame.paragraphs[0]
                p.alignment = PP_ALIGN.CENTER if col_idx not in (1, 2, 3) else PP_ALIGN.LEFT
                r = p.add_run()
                r.text = h_text
                r.font.name = FONT_FAMILY
                r.font.size = Pt(9.5)
                r.font.bold = True
                r.font.color.rgb = WHITE

            if not items_chunk:
                cell = tbl.cell(1, 1)
                p = cell.text_frame.paragraphs[0]
                r = p.add_run()
                r.text = empty_msg
                r.font.name = FONT_FAMILY
                r.font.size = Pt(10)
                r.font.italic = True
            else:
                for idx_item, item in enumerate(items_chunk):
                    row_idx = idx_item + 1
                    no_val = str(start_no + idx_item)
                    bg_c = CARD_BG if row_idx % 2 == 1 else RGBColor(241, 245, 249)
                    wil_str = f"{item.get('nama_kab', '')}, {item.get('nama_prov', '')}".strip(", ") or "Indonesia"
                    h_today_val = str(item.get("hotspots_today") or item.get("h_today") or 0)
                    ftri_val = float(item.get("ftri_score") or 0.0)
                    ftri_str = f"{ftri_val:.1f} ({item.get('ftri_label', 'Sedang')})"
                    cat_str = item.get("ew_category", "Peringatan Dini")
                    gmaps = item.get("google_maps_url")

                    cat_color = RED if "Strict" in cat_str else (AMBER if "Ekspansi" in cat_str else BLUE)
                    ftri_color = RED if ftri_val >= 70 else (AMBER if ftri_val >= 50 else SLATE)

                    row_items = [
                        (no_val, PP_ALIGN.CENTER, NAVY, False, None),
                        (f"{item.get('lembaga', 'Areal KPS')} ({item.get('skema', 'PS')})", PP_ALIGN.LEFT, NAVY, True, None),
                        (item.get("wilker_bps", "Balai PS"), PP_ALIGN.LEFT, SLATE, False, None),
                        (wil_str, PP_ALIGN.LEFT, NAVY_LIGHT, False, None),
                        (cat_str, PP_ALIGN.CENTER, cat_color, True, None),
                        (f"{h_today_val} titik", PP_ALIGN.CENTER, RED if int(h_today_val) > 10 else NAVY, True, None),
                        (ftri_str, PP_ALIGN.CENTER, ftri_color, True, None),
                        ("Buka Google Maps", PP_ALIGN.CENTER, BLUE, True, gmaps),
                    ]

                    for col_idx, (text_val, align, text_color, is_bold, link_url) in enumerate(row_items):
                        cell = tbl.cell(row_idx, col_idx)
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = bg_c
                        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                        p = cell.text_frame.paragraphs[0]
                        p.alignment = align
                        r = p.add_run()
                        r.text = text_val
                        r.font.name = FONT_FAMILY
                        r.font.size = Pt(9)
                        r.font.bold = is_bold
                        r.font.color.rgb = text_color
                        if link_url:
                            r.hyperlink.address = link_url
                            r.font.underline = True

        # =====================================================================
        # SLIDE KPS TERBAKAR KEMBALI & EKSPANSI BARA (SELURUH KPS TANPA TERPOTONG)
        # =====================================================================
        ew_sum = data.get("early_warning_summary", {})
        mini_w = Inches(3.75)
        mini_h = Inches(0.85)
        mini_y = Inches(1.3)
        mini_gap = Inches(0.24)
        mini_start_x = Inches(0.8)

        mini_cards = [
            (
                "🚨 KPS TERBAKAR ULANG (RE-BURN)",
                f"{ew_sum.get('strict_reburn_kps', 0)} KPS",
                "Ancaman Kritis pada Bekas Bakaran",
                RED,
            ),
            (
                "🟠 KPS EKSPANSI PERAMBATAN",
                f"{ew_sum.get('expanding_kps', 0)} KPS",
                "Perambatan Api Baru ke Vegetasi",
                AMBER,
            ),
            (
                "🟡 KPS PERINGATAN DINI BARU",
                f"{ew_sum.get('ew_new_kps', 0)} KPS",
                "Terindikasi Hotspot Hari Ini",
                BLUE,
            ),
        ]

        burned_kps_list = data.get("burned_kps_list", [])
        burned_chunks = [burned_kps_list[i:i + 9] for i in range(0, len(burned_kps_list), 9)] if burned_kps_list else [[]]
        total_burned_pages = len(burned_chunks)

        for p_idx, b_chunk in enumerate(burned_chunks):
            s_burn = prs.slides.add_slide(blank_layout)
            _add_rect(s_burn, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)

            p_label = f" (Hal. {p_idx + 1}/{total_burned_pages})" if total_burned_pages > 1 else ""
            _add_slide_header(
                s_burn,
                category="Sistem Peringatan Dini • Areal Bekas Terbakar",
                title=f"Daftar KPS Terbakar Kembali & Ekspansi Bara{p_label}",
                date_stamp=f"{data.get('report_date_str', '')} • 07:00 WIB",
            )

            if p_idx == 0:
                for idx, (m_title, m_val, m_sub, m_col) in enumerate(mini_cards):
                    mx = mini_start_x + (idx * (mini_w + mini_gap))
                    _add_rect(s_burn, mx, mini_y, mini_w, mini_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)
                    _add_rect(s_burn, mx, mini_y, mini_w, Inches(0.06), fill_color=m_col, rounded=True)

                    tb_m = s_burn.shapes.add_textbox(mx + Inches(0.12), mini_y + Inches(0.08), mini_w - Inches(0.24), mini_h - Inches(0.12))
                    tf_m = tb_m.text_frame
                    tf_m.word_wrap = True
                    tf_m.margin_left = tf_m.margin_top = tf_m.margin_right = tf_m.margin_bottom = 0

                    p_mt = tf_m.paragraphs[0]
                    r_mt = p_mt.add_run()
                    r_mt.text = m_title
                    r_mt.font.name = FONT_FAMILY
                    r_mt.font.size = Pt(8.5)
                    r_mt.font.bold = True
                    r_mt.font.color.rgb = SLATE

                    p_mv = tf_m.add_paragraph()
                    r_mv = p_mv.add_run()
                    r_mv.text = f"{m_val}  ·  "
                    r_mv.font.name = FONT_FAMILY
                    r_mv.font.size = Pt(14)
                    r_mv.font.bold = True
                    r_mv.font.color.rgb = m_col

                    r_ms = p_mv.add_run()
                    r_ms.text = m_sub
                    r_ms.font.name = FONT_FAMILY
                    r_ms.font.size = Pt(8.5)
                    r_ms.font.color.rgb = SLATE

                _render_kps_table_on_slide(
                    slide=s_burn,
                    items_chunk=b_chunk,
                    start_no=1,
                    tbl_y=Inches(2.3),
                    tbl_h=Inches(4.7),
                    empty_msg="Nihil KPS terbakar ulang atau ekspansi bara hari ini.",
                )
            else:
                _render_kps_table_on_slide(
                    slide=s_burn,
                    items_chunk=b_chunk,
                    start_no=(p_idx * 9) + 1,
                    tbl_y=Inches(1.4),
                    tbl_h=Inches(5.4),
                    empty_msg="Nihil KPS terbakar ulang atau ekspansi bara hari ini.",
                )
            _add_slide_footer(s_burn)

        # =====================================================================
        # SLIDE KPS PERINGATAN DINI BARU — PRIORITAS FTRI EKSTREM & TINGGI
        # =====================================================================
        ew_new_list = data.get("ew_new_list", [])
        top_ew_items = ew_new_list[:18]  # Top 18 KPS ancaman FTRI tertinggi
        ew_chunks = [top_ew_items[i:i + 9] for i in range(0, len(top_ew_items), 9)] if top_ew_items else [[]]
        total_ew_pages = len(ew_chunks)

        for e_idx, e_chunk in enumerate(ew_chunks):
            s_ew = prs.slides.add_slide(blank_layout)
            _add_rect(s_ew, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)

            e_label = f" (Hal. {e_idx + 1}/{total_ew_pages})" if total_ew_pages > 1 else ""
            _add_slide_header(
                s_ew,
                category=f"Sistem Peringatan Dini • Potensi Kebakaran Baru (Total {len(ew_new_list)} KPS Aktif)",
                title=f"Daftar KPS Peringatan Dini Baru — Ancaman FTRI Ekstrem{e_label}",
                date_stamp=f"{data.get('report_date_str', '')} • 07:00 WIB",
            )

            _render_kps_table_on_slide(
                slide=s_ew,
                items_chunk=e_chunk,
                start_no=(e_idx * 9) + 1,
                tbl_y=Inches(1.4),
                tbl_h=Inches(5.4),
                empty_msg="Nihil KPS terindikasi titik panas baru hari ini.",
            )
            _add_slide_footer(s_ew)

        # =====================================================================
        # SLIDE: REKAPITULASI SPASIAL BALAI PERHUTANAN SOSIAL (BPS)
        # =====================================================================
        s5 = prs.slides.add_slide(blank_layout)
        _add_rect(s5, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s5,
            category="Pemetaan Wilayah Kerja",
            title="Rekapitulasi Spasial per Balai Perhutanan Sosial (BPS)",
            date_stamp=f"{data.get('report_date_str', '')} • 07:00 WIB",
        )

        table_y = Inches(1.4)
        table_w = Inches(11.733)
        table_h = Inches(5.4)

        balai_rows = data.get("balai_list", [])[:9]
        num_rows = max(len(balai_rows) + 1, 2)
        tbl_shape = s5.shapes.add_table(num_rows, 8, Inches(0.8), table_y, table_w, table_h)
        tbl = tbl_shape.table

        col_widths = [
            Inches(0.6),   # No
            Inches(3.333), # Balai PS
            Inches(1.1),   # High
            Inches(1.1),   # Medium
            Inches(1.3),   # Total Pantau
            Inches(1.3),   # Max FRP
            Inches(1.4),   # Skor Prioritas
            Inches(1.6),   # Status Prioritas
        ]
        for idx, w in enumerate(col_widths):
            tbl.columns[idx].width = w

        headers = [
            "NO",
            "WILAYAH KERJA BALAI PS",
            "HIGH",
            "MEDIUM",
            "TOTAL PANTAU",
            "FRP MAKS",
            "SKOR PRIORITAS",
            "STATUS PRIORITAS",
        ]
        for col_idx, h_text in enumerate(headers):
            cell = tbl.cell(0, col_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if col_idx not in (1,) else PP_ALIGN.LEFT
            r = p.add_run()
            r.text = h_text
            r.font.name = FONT_FAMILY
            r.font.size = Pt(9.5)
            r.font.bold = True
            r.font.color.rgb = WHITE

        if not balai_rows:
            cell = tbl.cell(1, 1)
            p = cell.text_frame.paragraphs[0]
            r = p.add_run()
            r.text = "Nihil deteksi titik panas di seluruh Balai PS dalam 24 jam terakhir."
            r.font.name = FONT_FAMILY
            r.font.size = Pt(10)
            r.font.italic = True
        else:
            for row_idx, item in enumerate(balai_rows, 1):
                bg_c = CARD_BG if row_idx % 2 == 1 else RGBColor(241, 245, 249)
                row_data = [
                    (str(row_idx), PP_ALIGN.CENTER, NAVY),
                    (item["name"], PP_ALIGN.LEFT, NAVY),
                    (str(item["high_count"]), PP_ALIGN.CENTER, RED if item["high_count"] > 0 else SLATE),
                    (str(item["medium_count"]), PP_ALIGN.CENTER, AMBER if item["medium_count"] > 0 else SLATE),
                    (str(item["total_priority"]), PP_ALIGN.CENTER, NAVY),
                    (f"{item['max_frp']} MW", PP_ALIGN.CENTER, RED if item["max_frp"] > 30 else NAVY),
                    (str(item["priority_score"]), PP_ALIGN.CENTER, NAVY),
                    (item["priority_status"], PP_ALIGN.CENTER, RED if item["priority_status"] == "Prioritas Tinggi" else (AMBER if item["priority_status"] == "Prioritas Sedang" else GREEN)),
                ]
                for col_idx, (val_text, align, text_color) in enumerate(row_data):
                    cell = tbl.cell(row_idx, col_idx)
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = bg_c
                    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                    p = cell.text_frame.paragraphs[0]
                    p.alignment = align
                    r = p.add_run()
                    r.text = val_text
                    r.font.name = FONT_FAMILY
                    r.font.size = Pt(9.5)
                    r.font.bold = (col_idx in (1, 6, 7))
                    r.font.color.rgb = text_color

        _add_slide_footer(s5)

        # =====================================================================
        # SLIDE 6: MATRIKS KEPUTUSAN & INSTRUKSI LAPANGAN SATGAS HARI INI
        # =====================================================================
        s6 = prs.slides.add_slide(blank_layout)
        _add_rect(s6, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s6,
            category="Instruksi Operasional",
            title="Matriks Keputusan & Instruksi Lapangan Satgas Hari Ini",
            date_stamp=f"{data.get('report_date_str', '')} • 07:00 WIB",
        )

        step_w = Inches(3.75)
        step_h = Inches(5.4)
        step_y = Inches(1.4)
        step_gap = Inches(0.24)
        step_start_x = Inches(0.8)

        # Prioritaskan KPS dari Menu Peringatan Dini sebagai target tugas utama
        top_targets = data.get("early_warning_kps_list", [])[:3] or data.get("kps_list", [])[:3]
        kps_decision_text = []
        for idx, kps in enumerate(top_targets, 1):
            k_name = kps.get("lembaga") or kps.get("name") or "Areal KPS"
            k_bps = kps.get("wilker_bps") or kps.get("bps") or "Balai PS"
            k_pts = kps.get("hotspots_today") or kps.get("total") or 0
            k_ftri = kps.get("ftri_score")
            ftri_note = f" | FTRI: {k_ftri:.1f}" if k_ftri else ""
            k_lat = kps.get("latitude", 0.0)
            k_lon = kps.get("longitude", 0.0)
            kps_decision_text.append(
                f"{idx}. {k_name} ({k_bps})\n"
                f"   • Titik: {k_pts} Titik{ftri_note} | Pin: {k_lat:.4f}, {k_lon:.4f}"
            )

        b_list_s6 = data.get("balai_list", [])
        b1_name = b_list_s6[0]["name"] if b_list_s6 else "Balai Terkait"
        b2_name = b_list_s6[1]["name"] if len(b_list_s6) > 1 else "Balai Kedua"
        hi_cnt = data.get("high_count", 0)

        instructions = [
            (
                "01. PENETAPAN STATUS KOMANDO",
                "Keputusan Manajemen & Pimpinan",
                RED if hi_cnt > 10 else AMBER,
                [
                    f"Tetapkan Status Siaga: {data.get('status_siaga', 'WASPADA')} untuk seluruh unit pelaksana teknis (UPT).",
                    f"Aktivasi Posko Darurat: Prioritas di {b1_name} dan {b2_name}.",
                    "Penyekatan Kanal: Instruksikan pengelola KPS lahan gambut membuka pintu pembasahan sekat kanal.",
                    "Logistik & Armada: Siagakan pompa jinjing dan tangki air di titik kumpul posko terdekat.",
                ],
            ),
            (
                "02. DISPOSISI GROUND CHECK MENU EW",
                "Perintah Tugas Lapangan Hari Ini",
                BLUE,
                [
                    "Terbitkan Surat Perintah Tugas (SPT) verifikasi darat untuk 3 KPS prioritas Peringatan Dini:",
                ] + (kps_decision_text if kps_decision_text else ["Nihil unit KPS kritis hari ini."]),
            ),
            (
                "03. PENYUSUNAN BAP & LEGALITAS",
                "Standar Penegakan Aturan Lapangan",
                GREEN,
                [
                    "Dokumentasi Wajib: Ambil foto geotagged 4 penjuru mata angin pada titik koordinat anomali.",
                    "Uji Fisik Lapangan: Pastikan apakah indikasi merupakan api berkobar, sisa abu, atau panas atap/industri.",
                    "Berita Acara (BAP): Susun BAP verifikasi lapangan bersama ketua kelompok KPS dan pendamping.",
                    "Input Sistem: Laporkan hasil BAP langsung ke aplikasi ETASENEU dalam kurun waktu 1×24 jam.",
                ],
            ),
        ]

        for idx, (ins_title, ins_sub, ins_color, ins_points) in enumerate(instructions):
            ix = step_start_x + (idx * (step_w + step_gap))
            _add_rect(s6, ix, step_y, step_w, step_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)
            _add_rect(s6, ix, step_y, step_w, Inches(0.1), fill_color=ins_color, rounded=True)

            tb_i = s6.shapes.add_textbox(ix + Inches(0.2), step_y + Inches(0.2), step_w - Inches(0.4), step_h - Inches(0.4))
            tf_i = tb_i.text_frame
            tf_i.word_wrap = True
            tf_i.margin_left = tf_i.margin_top = tf_i.margin_right = tf_i.margin_bottom = 0

            p_h = tf_i.paragraphs[0]
            r_h = p_h.add_run()
            r_h.text = ins_title
            r_h.font.name = FONT_FAMILY
            r_h.font.size = Pt(11)
            r_h.font.bold = True
            r_h.font.color.rgb = ins_color

            p_sub = tf_i.add_paragraph()
            p_sub.space_before = Pt(2)
            p_sub.space_after = Pt(10)
            r_sub = p_sub.add_run()
            r_sub.text = ins_sub
            r_sub.font.name = FONT_FAMILY
            r_sub.font.size = Pt(9)
            r_sub.font.bold = True
            r_sub.font.color.rgb = SLATE

            for pt in ins_points:
                p_p = tf_i.add_paragraph()
                p_p.space_after = Pt(7)
                r_p = p_p.add_run()
                r_p.text = f"• {pt}"
                r_p.font.name = FONT_FAMILY
                r_p.font.size = Pt(9)
                r_p.font.color.rgb = NAVY_LIGHT

        _add_slide_footer(s6)

        buf = io.BytesIO()
        prs.save(buf)
        buf.seek(0)
        return buf.getvalue()

    def record_daily_report_sent(self, report_date_str: str) -> None:
        """Catat tanggal laporan harian yang berhasil dikirim ke database untuk deduplikasi."""
        if not self.store.enabled:
            return
        try:
            with self.store.connection() as conn:
                self.store._ensure_hotspot_sync_state_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO hotspot_sync_state (sync_key, last_hotspot_sync_at, last_hotspot_sync_count)
                        VALUES (%s, NOW(), 1)
                        ON CONFLICT (sync_key)
                        DO UPDATE SET last_hotspot_sync_at = NOW(), last_hotspot_sync_count = hotspot_sync_state.last_hotspot_sync_count + 1;
                        """,
                        (f"daily_report_{report_date_str}",),
                    )
        except Exception as e:
            logger.error("Gagal mencatat status laporan harian di DB: %s", e)

    def is_daily_report_already_sent(self, report_date_str: str) -> bool:
        """Cek apakah laporan harian tanggal ini sudah pernah terkirim."""
        if not self.store.enabled:
            return False
        try:
            with self.store.connection() as conn:
                self.store._ensure_hotspot_sync_state_table(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT sync_key FROM hotspot_sync_state WHERE sync_key = %s;",
                        (f"daily_report_{report_date_str}",),
                    )
                    return cur.fetchone() is not None
        except Exception as e:
            logger.error("Gagal memeriksa status laporan harian: %s", e)
            return False

    async def send_daily_telegram_report(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        target_date: date | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Generate paparan .pptx dengan grafik visual dan kirimkan via Telegram Bot."""
        token = (self.settings.telegram_bot_token if bot_token is None else bot_token).strip()
        target_chat = (self.settings.telegram_chat_id if chat_id is None else chat_id).strip()

        if not token or not target_chat:
            return {
                "success": False,
                "error": "telegram_bot_token atau telegram_chat_id belum dikonfigurasi.",
            }

        jakarta_tz = ZoneInfo("Asia/Jakarta")
        effective_date = target_date or datetime.now(jakarta_tz).date()
        date_iso = effective_date.strftime("%Y%m%d")
        date_str_key = effective_date.strftime("%Y-%m-%d")

        if not force and self.is_daily_report_already_sent(date_str_key):
            logger.info("Laporan harian untuk %s sudah pernah terkirim sebelumnya.", date_str_key)
            return {
                "success": True,
                "skipped": True,
                "reason": "already_sent_today",
                "message": f"Laporan harian {date_str_key} sudah pernah terkirim hari ini.",
            }

        data = self.collect_daily_hotspot_data(target_date=effective_date)
        pptx_bytes = self.generate_daily_hotspot_pptx(data)
        filename = f"Laporan_Harian_Hotspot_KPS_{date_iso}_0700WIB.pptx"

        top_balai_str = ", ".join([b["name"].replace("Balai PS ", "") for b in data.get("balai_list", [])[:2]]) if data.get("balai_list") else "Nihil"
        ew_sum = data.get("early_warning_summary", {})

        # Rincian KPS Strict Re-burn (Terbakar Ulang) - maks 2 baris agar aman dalam 1024 char limit Telegram
        strict_kps = [k for k in data.get("burned_kps_list", []) if k.get("hotspots_today_strict_reburn", 0) > 0]

        strict_lines = []
        for idx, kps in enumerate(strict_kps[:2], 1):
            s_name = kps.get("lembaga", "Areal KPS")[:20]
            s_bps = kps.get("wilker_bps", "Balai PS").replace("Balai PS ", "")
            s_pts = kps.get("hotspots_today") or 0
            s_re = kps.get("hotspots_today_strict_reburn") or 0
            gmaps = kps.get("google_maps_url", "#")
            strict_lines.append(
                f"{idx}. 🚨 <b>{html.escape(s_name)}</b> ({s_bps})\n"
                f"   • {s_pts} Titik ({s_re} Re-burn) • <a href=\"{gmaps}\">Maps</a>"
            )
        more_strict = len(strict_kps) - 2
        if more_strict > 0:
            strict_lines.append(f"   <i>(+{more_strict} KPS terbakar ulang lainnya di slide .pptx)</i>")

        strict_block = "\n".join(strict_lines) if strict_lines else "<i>Nihil KPS terbakar ulang hari ini.</i>"

        tot_ew = data.get("total_ew_active_today", 0)
        str_kps_cnt = ew_sum.get("strict_reburn_kps", 0)
        exp_kps_cnt = ew_sum.get("expanding_kps", 0)
        new_kps_cnt = ew_sum.get("ew_new_kps", 0)

        caption = (
            "📊 <b>LAPORAN HARIAN HOTSPOT KPS (07:00 WIB)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Tanggal</b>: {data['report_date_str']}\n"
            f"🚨 <b>Status Siaga</b>: <b>{data['status_siaga']}</b>\n"
            f"📈 <b>Tren H vs H-1</b>: <b>{data['total_hotspots']:,} titik</b> ({data['trend_icon']} {data['delta_pct']:+.1f}% vs {data['yesterday_total']:,})\n"
            f"⚡ <b>FRP Maks</b>: <b>{data['max_frp']} MW</b> | Fokus: {top_balai_str}\n\n"
            "<b>🔥 REKAP PERINGATAN DINI:</b>\n"
            f"• 🚨 <b>{str_kps_cnt} KPS Terbakar Ulang</b> | 🟠 <b>{exp_kps_cnt} Ekspansi</b>\n"
            f"• 🟡 <b>{new_kps_cnt} KPS Baru</b> <i>(Total {tot_ew} KPS aktif)</i>\n\n"
            "<b>🚨 KPS TERBAKAR ULANG (PRIORITAS 1):</b>\n"
            f"{strict_block}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📎 <i>Semua 27 KPS Terbakar Ulang & Top FTRI termuat di .pptx.</i>\n"
            f"🔗 <a href=\"{self.settings.frontend_origin}\">Unduh Excel {tot_ew} KPS di ETASENEU</a>"
        )
        if len(caption) > 1020:
            caption = caption[:1015] + "..."

        url = f"https://api.telegram.org/bot{token}/sendDocument"
        payload_data = {
            "chat_id": target_chat,
            "caption": caption,
            "parse_mode": "HTML",
        }
        files = {
            "document": (
                filename,
                pptx_bytes,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(url, data=payload_data, files=files)
                if resp.status_code == 200:
                    resp_json = resp.json()
                    msg_id = (resp_json.get("result") or {}).get("message_id")
                    logger.info(
                        "Laporan harian PPTX berhasil dikirim ke Telegram chat %s (message_id=%s).",
                        target_chat,
                        msg_id,
                    )
                    self.record_daily_report_sent(date_str_key)
                    return {
                        "success": True,
                        "message_id": msg_id,
                        "filename": filename,
                        "file_size": len(pptx_bytes),
                        "total_hotspots": data["total_hotspots"],
                        "status_siaga": data["status_siaga"],
                    }

                logger.error("Gagal mengirim dokumen PPTX ke Telegram: HTTP %s %s", resp.status_code, resp.text)
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": resp.text,
                }
        except Exception as e:
            logger.error("Exception saat mengirim laporan harian PPTX ke Telegram: %s", e)
            return {"success": False, "error": str(e)}


async def daily_report_scheduler_loop() -> None:
    """Loop latar belakang scheduler untuk mengirimkan laporan harian PPTX setiap pukul 07:00 WIB."""
    settings = get_settings()
    jakarta_tz = ZoneInfo("Asia/Jakarta")
    target_hour = int(settings.daily_report_fixed_hour)

    logger.info("DAILY_REPORT: Scheduler aktif — disetel setiap hari pada pukul %02d:00 WIB.", target_hour)

    while True:
        try:
            now_jkt = datetime.now(jakarta_tz)
            today_str = now_jkt.strftime("%Y-%m-%d")

            if now_jkt.hour >= target_hour:
                service = DailyReportService()
                if not service.is_daily_report_already_sent(today_str):
                    logger.info(
                        "DAILY_REPORT: Menjalankan pengiriman laporan harian PPTX otomatis untuk tanggal %s...",
                        today_str,
                    )
                    await service.send_daily_telegram_report(force=False)

            now_jkt = datetime.now(jakarta_tz)
            if now_jkt.hour < target_hour:
                next_check = datetime.combine(now_jkt.date(), time(target_hour, 0, 5), tzinfo=jakarta_tz)
            else:
                next_check = datetime.combine(
                    now_jkt.date() + timedelta(days=1),
                    time(target_hour, 0, 5),
                    tzinfo=jakarta_tz,
                )

            sleep_seconds = max(10.0, (next_check - now_jkt).total_seconds())
            sleep_duration = min(sleep_seconds, 300.0)
            await asyncio.sleep(sleep_duration)

        except asyncio.CancelledError:
            logger.info("DAILY_REPORT: Scheduler dihentikan.")
            break
        except Exception as err:
            logger.error("DAILY_REPORT: Kesalahan pada loop scheduler: %s", err, exc_info=True)
            await asyncio.sleep(60.0)
