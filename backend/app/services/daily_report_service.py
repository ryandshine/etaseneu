"""Layanan pembuatan dan pengiriman Laporan Harian Pemantauan Titik Panas (Hotspot) KPS (.pptx).

Menghasilkan paparan resmi 16:9 berstandar Kementerian Kehutanan & ETASENEU,
dan mengirimkannya secara otomatis via Telegram Bot API setiap pagi pukul 07:00 WIB.
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

    # Label Kategori & Judul Utama
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

    # Tanggal dan Jam Stamp (Sisi Kanan)
    if date_stamp:
        tb_right = slide.shapes.add_textbox(Inches(9.2), Inches(0.3), Inches(3.3), Inches(0.55))
        tf_right = tb_right.text_frame
        tf_right.word_wrap = True
        tf_right.margin_left = tf_right.margin_top = tf_right.margin_right = tf_right.margin_bottom = 0
        p_right = tf_right.paragraphs[0]
        p_right.alignment = PP_ALIGN.RIGHT
        r_right = p_right.add_run()
        r_right.text = date_stamp
        r_right.font.name = FONT_FAMILY
        r_right.font.size = Pt(11)
        r_right.font.bold = True
        r_right.font.color.rgb = MUTED


def _add_slide_footer(slide):
    tb = slide.shapes.add_textbox(Inches(0.8), Inches(7.12), Inches(11.733), Inches(0.3))
    tf = tb.text_frame
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = (
        "Kementerian Kehutanan Republik Indonesia  ·  Sistem Informasi ETASENEU  ·  "
        "Laporan Harian Pemantauan Titik Panas (07:00 WIB)"
    )
    r.font.name = FONT_FAMILY
    r.font.size = Pt(8)
    r.font.color.rgb = SLATE


class DailyReportService:
    def __init__(self, store: PostgresStore | None = None) -> None:
        self.settings = get_settings()
        self.store = store or PostgresStore(self.settings.database_url)

    def collect_daily_hotspot_data(
        self,
        target_date: date | None = None,
        lookback_hours: int = 24,
    ) -> dict[str, Any]:
        """Kumpulkan data agregasi titik panas 24 jam terakhir dari database."""
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

        raw_rows: list[dict[str, Any]] = []
        if self.store.enabled:
            try:
                with self.store.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT 
                                h.id, h.latitude, h.longitude, h.detected_at, h.confidence,
                                h.satellite, h.source, h.agency_name,
                                (h.raw_payload->>'frp')::float as frp,
                                h.raw_payload->>'province_name' as prov,
                                h.raw_payload->'polygon_metadata' as poly_meta
                            FROM hotspot_observations h
                            WHERE h.detected_at >= %s AND h.detected_at <= %s
                            ORDER BY (h.raw_payload->>'frp')::float DESC NULLS LAST, h.detected_at DESC;
                            """,
                            (start_time, end_time),
                        )
                        raw_rows = [dict(r) for r in cur.fetchall()]
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

        for r in raw_rows:
            conf_cat = confidence_category(r)
            confidence_counts[conf_cat] = confidence_counts.get(conf_cat, 0) + 1

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
            else:
                agency = raw_agency

            # Lokasi teks
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

            # Update Balai PS stats
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

            # Update Agency stats
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

        # Olah daftar Balai PS dan skoring prioritas: (HIGH * 2) + (MED * 1)
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

        # Urutkan Balai PS berdasarkan skor prioritas tertinggi
        balai_list.sort(key=lambda x: (x["priority_score"], x["high_count"], x["max_frp"]), reverse=True)

        # Olah daftar Top KPS
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

        # Urutkan KPS berdasarkan prioritas tertinggi
        kps_list.sort(key=lambda x: (x["priority_score"], x["max_frp"]), reverse=True)

        max_frp = max(frp_values, default=0.0)
        avg_frp = (sum(frp_values) / len(frp_values)) if frp_values else 0.0

        high_and_med = confidence_counts["Tinggi"] + confidence_counts["Sedang"]
        if confidence_counts["Tinggi"] >= 5 or max_frp > 100 or high_and_med >= 50:
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
            "high_count": confidence_counts["Tinggi"],
            "medium_count": confidence_counts["Sedang"],
            "low_count": confidence_counts["Rendah"],
            "max_frp": round(max_frp, 1),
            "avg_frp": round(avg_frp, 1),
            "status_siaga": status_siaga,
            "siaga_color": siaga_color,
            "balai_list": balai_list,
            "kps_list": kps_list,
            "has_data": total_hotspots > 0,
        }

    def generate_daily_hotspot_pptx(self, data: dict[str, Any]) -> bytes:
        """Bangun presentasi PowerPoint 16:9 widescreen berisi 5 slide eksekutif."""
        prs = Presentation()
        prs.slide_width = Inches(13.333)
        prs.slide_height = Inches(7.5)

        blank_layout = prs.slide_layouts[6]

        # =====================================================================
        # SLIDE 1: COVER RESMI (SAMPUL)
        # =====================================================================
        s1 = prs.slides.add_slide(blank_layout)
        _add_rect(s1, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=NAVY)

        # Aksen Banner Garis Emas/Biru Atas
        _add_rect(s1, Inches(0), Inches(0), Inches(13.333), Inches(0.12), fill_color=SKY)

        # Kontainer Judul Utama
        tb_cov = s1.shapes.add_textbox(Inches(1.0), Inches(1.2), Inches(11.333), Inches(3.8))
        tf_cov = tb_cov.text_frame
        tf_cov.word_wrap = True
        tf_cov.margin_left = tf_cov.margin_top = tf_cov.margin_right = tf_cov.margin_bottom = 0

        p_kemenhut = tf_cov.paragraphs[0]
        p_kemenhut.space_after = Pt(12)
        r_kem = p_kemenhut.add_run()
        r_kem.text = "KEMENTERIAN KEHUTANAN REPUBLIK INDONESIA"
        r_kem.font.name = FONT_FAMILY
        r_kem.font.size = Pt(13)
        r_kem.font.bold = True
        r_kem.font.color.rgb = MUTED

        p_tit = tf_cov.add_paragraph()
        p_tit.space_after = Pt(8)
        r_tit = p_tit.add_run()
        r_tit.text = "LAPORAN HARIAN PEMANTAUAN TITIK PANAS (HOTSPOT)"
        r_tit.font.name = FONT_FAMILY
        r_tit.font.size = Pt(28)
        r_tit.font.bold = True
        r_tit.font.color.rgb = WHITE

        p_sub = tf_cov.add_paragraph()
        p_sub.space_after = Pt(18)
        r_sub = p_sub.add_run()
        r_sub.text = "Areal Persetujuan Perhutanan Sosial (KPS) dan Hutan Adat Seluruh Indonesia"
        r_sub.font.name = FONT_FAMILY
        r_sub.font.size = Pt(16)
        r_sub.font.color.rgb = SKY

        # Metadata Card Gelap di Cover
        _add_rect(s1, Inches(1.0), Inches(4.3), Inches(11.333), Inches(1.5), fill_color=NAVY_LIGHT, rounded=True)
        tb_meta = s1.shapes.add_textbox(Inches(1.3), Inches(4.45), Inches(10.7), Inches(1.2))
        tf_meta = tb_meta.text_frame
        tf_meta.word_wrap = True
        tf_meta.margin_left = tf_meta.margin_top = tf_meta.margin_right = tf_meta.margin_bottom = 0

        p_m1 = tf_meta.paragraphs[0]
        p_m1.space_after = Pt(4)
        r_m1 = p_m1.add_run()
        r_m1.text = f"📅 Periode Pemantauan: {data['time_window_str']}  |  Pukul 07:00 WIB"
        r_m1.font.name = FONT_FAMILY
        r_m1.font.size = Pt(12)
        r_m1.font.bold = True
        r_m1.font.color.rgb = WHITE

        p_m2 = tf_meta.add_paragraph()
        p_m2.space_after = Pt(4)
        r_m2 = p_m2.add_run()
        r_m2.text = (
            f"🛰️ Satelit Pengamat: NASA FIRMS (VIIRS NOAA-20, NOAA-21, S-NPP & MODIS Terra/Aqua)  ·  "
            f"Status: {data['status_siaga']}"
        )
        r_m2.font.name = FONT_FAMILY
        r_m2.font.size = Pt(11)
        r_m2.font.color.rgb = SKY

        p_m3 = tf_meta.add_paragraph()
        r_m3 = p_m3.add_run()
        r_m3.text = "📡 Disusun oleh: Sistem Informasi ETASENEU untuk Satgas Pengendalian Kebakaran Hutan (Dalkarhutla) & Balai PS"
        r_m3.font.name = FONT_FAMILY
        r_m3.font.size = Pt(10)
        r_m3.font.color.rgb = MUTED

        # Disclaimer Wajib Kedinasan
        tb_disc = s1.shapes.add_textbox(Inches(1.0), Inches(6.25), Inches(11.333), Inches(0.8))
        tf_disc = tb_disc.text_frame
        tf_disc.word_wrap = True
        tf_disc.margin_left = tf_disc.margin_top = tf_disc.margin_right = tf_disc.margin_bottom = 0
        p_disc = tf_disc.paragraphs[0]
        r_disc = p_disc.add_run()
        r_disc.text = (
            "CATATAN KEDINASAN: Indikasi hotspot merupakan anomali termal berbasis satelit penginderaan jauh "
            "dan BUKAN kejadian kebakaran yang telah terkonfirmasi fisik sebelum verifikasi lapangan (ground check) "
            "dan Berita Acara Pemeriksaan (BAP). Laporan ini berfungsi sebagai instrumen navigasi patroli & sistem peringatan dini."
        )
        r_disc.font.name = FONT_FAMILY
        r_disc.font.size = Pt(8.5)
        r_disc.font.italic = True
        r_disc.font.color.rgb = MUTED

        # =====================================================================
        # SLIDE 2: RINGKASAN EKSEKUTIF & INDIKATOR SIAGA 24 JAM
        # =====================================================================
        s2 = prs.slides.add_slide(blank_layout)
        _add_rect(s2, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s2,
            category="Ringkasan Eksekutif",
            title="Indikator Siaga dan Rekapitulasi Pantauan 24 Jam",
            date_stamp=f"{data['report_date_str']} • 07:00 WIB",
        )

        # 4 KPI Cards
        card_w = Inches(2.78)
        card_h = Inches(1.5)
        card_y = Inches(1.4)
        gap = Inches(0.2)
        start_x = Inches(0.8)

        kpis = [
            (
                "TOTAL TITIK PANAS (24 JAM)",
                f"{data['total_hotspots']:,}".replace(",", "."),
                f"High: {data['high_count']} | Med: {data['medium_count']}",
                NAVY,
            ),
            (
                "KEYAKINAN SEDANG & TINGGI",
                f"{data['high_count'] + data['medium_count']:,}".replace(",", "."),
                f"Fokus Utama Ground Check",
                RED if data['high_count'] > 0 else AMBER,
            ),
            (
                "FRP MAKSIMUM",
                f"{data['max_frp']} MW",
                f"Rata-rata: {data['avg_frp']} MW",
                RED if data['max_frp'] > 30 else AMBER,
            ),
            (
                "STATUS SIAGA HARIAN",
                data['status_siaga'],
                f"{len(data['balai_list'])} Balai PS Terindikasi",
                data.get('siaga_color') or GREEN,
            ),
        ]

        for i, (kpi_title, kpi_val, kpi_sub, kpi_color) in enumerate(kpis):
            cx = start_x + (i * (card_w + gap))
            _add_rect(s2, cx, card_y, card_w, card_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)
            _add_rect(s2, cx, card_y, card_w, Inches(0.08), fill_color=kpi_color, rounded=True)

            tb_k = s2.shapes.add_textbox(cx + Inches(0.15), card_y + Inches(0.16), card_w - Inches(0.3), card_h - Inches(0.25))
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
            p_kv.space_before = Pt(4)
            p_kv.space_after = Pt(2)
            r_kv = p_kv.add_run()
            r_kv.text = kpi_val
            r_kv.font.name = FONT_FAMILY
            r_kv.font.size = Pt(20)
            r_kv.font.bold = True
            r_kv.font.color.rgb = kpi_color

            p_ks = tf_k.add_paragraph()
            r_ks = p_ks.add_run()
            r_ks.text = kpi_sub
            r_ks.font.name = FONT_FAMILY
            r_ks.font.size = Pt(8.5)
            r_ks.font.color.rgb = SLATE

        # 2 Kartu Konten Bawah: Situasi Pantauan & Mandat Penapisan
        bottom_y = Inches(3.15)
        bottom_h = Inches(3.8)

        # Kartu Kiri: Analisis Pantauan
        left_w = Inches(6.8)
        _add_rect(s2, Inches(0.8), bottom_y, left_w, bottom_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)
        tb_left = s2.shapes.add_textbox(Inches(1.05), bottom_y + Inches(0.2), left_w - Inches(0.5), bottom_h - Inches(0.4))
        tf_left = tb_left.text_frame
        tf_left.word_wrap = True
        tf_left.margin_left = tf_left.margin_top = tf_left.margin_right = tf_left.margin_bottom = 0

        p_ltit = tf_left.paragraphs[0]
        p_ltit.space_after = Pt(8)
        r_ltit = p_ltit.add_run()
        r_ltit.text = "Analisis Spasial dan Situasi Pantauan Harian"
        r_ltit.font.name = FONT_FAMILY
        r_ltit.font.size = Pt(13)
        r_ltit.font.bold = True
        r_ltit.font.color.rgb = NAVY

        bullets_left = [
            f"Deteksi 24 Jam: Sebanyak {data['total_hotspots']:,} titik panas tertangkap di seluruh areal persetujuan KPS dan perimeter penyangga.".replace(",", "."),
            f"Klasifikasi Keyakinan: {data['high_count']} titik berkeyakinan Tinggi (High) dan {data['medium_count']} titik berkeyakinan Sedang (Nominal/Medium).",
            f"Titik Rendah (Low): Sebanyak {data['low_count']} titik disaring/dieksklusi dari prioritas verifikasi fisik demi efektivitas sumber daya patroli.",
            f"Intensitas Panas: Nilai Fire Radiative Power (FRP) tertinggi tercatat {data['max_frp']} MW dengan rerata {data['avg_frp']} MW.",
            f"Sebaran Terluas: Terdistribusi pada {len(data['balai_list'])} wilayah kerja Balai Perhutanan Sosial di seluruh Indonesia.",
        ]

        for b in bullets_left:
            p_b = tf_left.add_paragraph()
            p_b.space_after = Pt(6)
            r_bullet = p_b.add_run()
            r_bullet.text = f"•  {b}"
            r_bullet.font.name = FONT_FAMILY
            r_bullet.font.size = Pt(10)
            r_bullet.font.color.rgb = NAVY_LIGHT

        # Kartu Kanan: Formula Penapisan Prioritas & SOP
        right_x = Inches(7.85)
        right_w = Inches(4.68)
        _add_rect(s2, right_x, bottom_y, right_w, bottom_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)
        tb_right = s2.shapes.add_textbox(right_x + Inches(0.25), bottom_y + Inches(0.2), right_w - Inches(0.5), bottom_h - Inches(0.4))
        tf_right = tb_right.text_frame
        tf_right.word_wrap = True
        tf_right.margin_left = tf_right.margin_top = tf_right.margin_right = tf_right.margin_bottom = 0

        p_rtit = tf_right.paragraphs[0]
        p_rtit.space_after = Pt(8)
        r_rtit = p_rtit.add_run()
        r_rtit.text = "Indikator Prioritas Monitoring (Internal)"
        r_rtit.font.name = FONT_FAMILY
        r_rtit.font.size = Pt(13)
        r_rtit.font.bold = True
        r_rtit.font.color.rgb = NAVY

        bullets_right = [
            "Formula Skoring Kedinasan:\n   Skor = (Jumlah Hotspot HIGH × 2) + (Jumlah Hotspot MEDIUM × 1)",
            "🔴 Prioritas Tinggi (Skor ≥ 15 atau ≥ 2 HIGH):\n   Wajib verifikasi lapangan (ground check) dalam 1×24 jam oleh Satgas KPH & MPA.",
            "🟠 Prioritas Sedang (Skor 6 – 14):\n   Komunikasi intensif dengan pendamping KPS dan pemantauan satelit harian.",
            "🟢 Prioritas Rendah (Skor 1 – 5):\n   Monitoring berkala melalui sistem navigasi dan patroli reguler pencegahan.",
            "Alat Bantu Operasional: Skor ini adalah panduan internal penapisan lapangan, bukan vonis kebakaran mutlak.",
        ]

        for b in bullets_right:
            p_rb = tf_right.add_paragraph()
            p_rb.space_after = Pt(5)
            r_rb = p_rb.add_run()
            r_rb.text = f"•  {b}"
            r_rb.font.name = FONT_FAMILY
            r_rb.font.size = Pt(9.5)
            r_rb.font.color.rgb = NAVY_LIGHT

        _add_slide_footer(s2)

        # =====================================================================
        # SLIDE 3: REKAPITULASI SPASIAL PER BALAI PERHUTANAN SOSIAL (BPS)
        # =====================================================================
        s3 = prs.slides.add_slide(blank_layout)
        _add_rect(s3, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s3,
            category="Distribusi Spasial Wilayah Kerja",
            title="Rekapitulasi Deteksi Hotspot per Balai Perhutanan Sosial (BPS)",
            date_stamp=f"{data['report_date_str']} • 07:00 WIB",
        )

        table_y = Inches(1.4)
        table_w = Inches(11.733)
        table_h = Inches(5.4)

        balai_rows = data["balai_list"][:9]  # Tampilkan hingga 9 Balai PS teratas
        num_rows = max(len(balai_rows) + 1, 2)
        tbl_shape = s3.shapes.add_table(num_rows, 8, Inches(0.8), table_y, table_w, table_h)
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

        _add_slide_footer(s3)

        # =====================================================================
        # SLIDE 4: DAFTAR PRIORITAS UNIT PERHUTANAN SOSIAL (KPS) TERINDIKASI
        # =====================================================================
        s4 = prs.slides.add_slide(blank_layout)
        _add_rect(s4, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s4,
            category="Unit KPS Prioritas",
            title="Daftar Unit KPS Terindikasi Memerlukan Verifikasi Lapangan",
            date_stamp=f"{data['report_date_str']} • 07:00 WIB",
        )

        table_kps_rows = data["kps_list"][:9]
        num_kps_rows = max(len(table_kps_rows) + 1, 2)
        tbl_kps_shape = s4.shapes.add_table(num_kps_rows, 8, Inches(0.8), table_y, table_w, table_h)
        tbl_kps = tbl_kps_shape.table

        kps_col_widths = [
            Inches(0.5),   # No
            Inches(2.8),   # Nama Lembaga KPS
            Inches(1.8),   # Balai PS
            Inches(2.533), # Wilayah Administrasi
            Inches(0.9),   # High/Med
            Inches(1.0),   # FRP Maks
            Inches(1.1),   # Koordinat
            Inches(1.1),   # Peta / Link
        ]
        for idx, w in enumerate(kps_col_widths):
            tbl_kps.columns[idx].width = w

        kps_headers = [
            "NO",
            "NAMA LEMBAGA KPS",
            "BALAI PS",
            "LOKASI ADMINISTRATIF",
            "TITIK",
            "FRP MAKS",
            "KOORDINAT",
            "NAVIGASI",
        ]
        for col_idx, h_text in enumerate(kps_headers):
            cell = tbl_kps.cell(0, col_idx)
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

        if not table_kps_rows:
            cell = tbl_kps.cell(1, 1)
            p = cell.text_frame.paragraphs[0]
            r = p.add_run()
            r.text = "Tidak terdapat unit KPS dengan indikasi titik panas dalam 24 jam terakhir."
            r.font.name = FONT_FAMILY
            r.font.size = Pt(10)
            r.font.italic = True
        else:
            for row_idx, item in enumerate(table_kps_rows, 1):
                bg_c = CARD_BG if row_idx % 2 == 1 else RGBColor(241, 245, 249)
                coords_text = f"{item['latitude']:.4f}, {item['longitude']:.4f}"
                titik_text = f"{item['high_count']}H / {item['medium_count']}M"

                # Cells
                row_items = [
                    (str(row_idx), PP_ALIGN.CENTER, NAVY, False, None),
                    (item["name"], PP_ALIGN.LEFT, NAVY, True, None),
                    (item["bps"], PP_ALIGN.LEFT, SLATE, False, None),
                    (item["wilayah"], PP_ALIGN.LEFT, NAVY_LIGHT, False, None),
                    (titik_text, PP_ALIGN.CENTER, RED if item["high_count"] > 0 else AMBER, True, None),
                    (f"{item['max_frp']} MW", PP_ALIGN.CENTER, RED if item["max_frp"] > 30 else NAVY, True, None),
                    (coords_text, PP_ALIGN.CENTER, SLATE, False, None),
                    ("Buka Google Maps", PP_ALIGN.CENTER, BLUE, True, item["google_maps_url"]),
                ]

                for col_idx, (text_val, align, text_color, is_bold, link_url) in enumerate(row_items):
                    cell = tbl_kps.cell(row_idx, col_idx)
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

        _add_slide_footer(s4)

        # =====================================================================
        # SLIDE 5: PROTOKOL TINDAK LANJUT & ARAHAN GROUND CHECK SATGAS
        # =====================================================================
        s5 = prs.slides.add_slide(blank_layout)
        _add_rect(s5, Inches(0), Inches(0), Inches(13.333), Inches(7.5), fill_color=BG_CANVAS)
        _add_slide_header(
            s5,
            category="Standar Operasional Prosedur (SOP)",
            title="Protokol Penanganan Cepat & Arahan Ground Check Satgas Dalkarhutla",
            date_stamp=f"{data['report_date_str']} • 07:00 WIB",
        )

        step_w = Inches(2.78)
        step_h = Inches(5.2)
        step_y = Inches(1.5)

        steps = [
            (
                "01. PENAPISAN & DISPOSISI",
                "Satgas Balai PS & KPH",
                BLUE,
                [
                    "Identifikasi unit KPS kategori Prioritas Tinggi pada laporan ini.",
                    "Disposisikan data koordinat ke KPH dan Pendamping PS setempat.",
                    "Lakukan overlay batas perizinan persetujuan PS vs area buffer luar.",
                    "Siapkan peta kerja ground check berbasis Google Maps presisi.",
                ],
            ),
            (
                "02. PATROLI & GROUND CHECK",
                "Satgas Dalkarhutla & MPA",
                RED,
                [
                    "Pengerahan regu patroli terdekat dalam rentang waktu maksimal 1×24 jam.",
                    "Libatkan Masyarakat Peduli Api (MPA) dan pengurus kelompok KPS.",
                    "Gunakan tautan koordinat pada slide 4 untuk navigasi GPS lapangan.",
                    "Pastikan keselamatan personil dan ketersediaan peralatan pemadaman.",
                ],
            ),
            (
                "03. PEMBUKTIAN & BAP FISIK",
                "Tim Verifikasi Lapangan",
                AMBER,
                [
                    "Verifikasi tipe anomali: kebakaran aktif, bekas tebasan, atau panas industri.",
                    "Pengukuran luas indikasi terbakar menggunakan GPS tracking.",
                    "Pengambilan dokumentasi foto geotagged dari 4 penjuru mata angin.",
                    "Penyusunan Berita Acara Pemeriksaan (BAP) bermeterai resmi.",
                ],
            ),
            (
                "04. PELAPORAN BERJENJANG",
                "Direktorat & Ditjen Terkait",
                GREEN,
                [
                    "Input Berita Acara & foto lapangan ke platform ETASENEU.",
                    "Status hotspot dimutakhirkan dari indikasi menjadi terkonfirmasi/padam.",
                    "Laporan berkala disampaikan kepada Direktur PKTHA & Dirjen PSKL.",
                    "Evaluasi kepatuhan tata kelola pencegahan kebakaran kelompok KPS.",
                ],
            ),
        ]

        for idx, (s_title, s_sub, s_color, s_points) in enumerate(steps):
            sx = start_x + (idx * (step_w + gap))
            _add_rect(s5, sx, step_y, step_w, step_h, fill_color=CARD_BG, line_color=CARD_BORDER, rounded=True)
            _add_rect(s5, sx, step_y, step_w, Inches(0.1), fill_color=s_color, rounded=True)

            tb_s = s5.shapes.add_textbox(sx + Inches(0.18), step_y + Inches(0.2), step_w - Inches(0.36), step_h - Inches(0.35))
            tf_s = tb_s.text_frame
            tf_s.word_wrap = True
            tf_s.margin_left = tf_s.margin_top = tf_s.margin_right = tf_s.margin_bottom = 0

            p_h = tf_s.paragraphs[0]
            r_h = p_h.add_run()
            r_h.text = s_title
            r_h.font.name = FONT_FAMILY
            r_h.font.size = Pt(11)
            r_h.font.bold = True
            r_h.font.color.rgb = s_color

            p_sub = tf_s.add_paragraph()
            p_sub.space_before = Pt(2)
            p_sub.space_after = Pt(12)
            r_sub = p_sub.add_run()
            r_sub.text = s_sub
            r_sub.font.name = FONT_FAMILY
            r_sub.font.size = Pt(9)
            r_sub.font.bold = True
            r_sub.font.color.rgb = SLATE

            for pt in s_points:
                p_p = tf_s.add_paragraph()
                p_p.space_after = Pt(8)
                r_p = p_p.add_run()
                r_p.text = f"• {pt}"
                r_p.font.name = FONT_FAMILY
                r_p.font.size = Pt(9.5)
                r_p.font.color.rgb = NAVY_LIGHT

        _add_slide_footer(s5)

        # Simpan ke byte stream
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
        """Generate paparan .pptx dan kirimkan sebagai lampiran dokumen via Telegram Bot."""
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

        # Kumpulkan data pantauan
        data = self.collect_daily_hotspot_data(target_date=effective_date)
        pptx_bytes = self.generate_daily_hotspot_pptx(data)
        filename = f"Laporan_Harian_Hotspot_KPS_{date_iso}_0700WIB.pptx"

        # Susun caption Telegram ringkas (maks 1024 karakter sesuai limit Bot API)
        top_balai_str = ", ".join([b["name"] for b in data["balai_list"][:3]]) if data["balai_list"] else "Nihil"
        top_kps_lines = []
        for idx, kps in enumerate(data["kps_list"][:3], 1):
            short_name = kps["name"][:35]
            top_kps_lines.append(
                f"{idx}. <b>{html.escape(short_name)}</b>\n"
                f"   • {kps['high_count']}H/{kps['medium_count']}M | FRP: {kps['max_frp']} MW | <a href=\"{kps['google_maps_url']}\">Peta</a>"
            )

        top_kps_block = "\n".join(top_kps_lines) if top_kps_lines else "<i>Nihil indikasi titik panas.</i>"

        caption = (
            "📊 <b>LAPORAN HARIAN HOTSPOT KPS (07:00 WIB)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Tanggal</b>: {data['report_date_str']}\n"
            f"🚨 <b>Status</b>: <b>{data['status_siaga']}</b>\n"
            f"🔥 <b>Total Hotspot 24 Jam</b>: <b>{data['total_hotspots']:,}</b> titik\n"
            f"   • 🔴 High: <b>{data['high_count']}</b> | 🟠 Med: <b>{data['medium_count']}</b> | ⚪ Low: {data['low_count']}\n"
            f"⚡ <b>FRP Maks</b>: <b>{data['max_frp']} MW</b> (Rata-rata: {data['avg_frp']} MW)\n"
            f"🏢 <b>Balai Utama</b>: {top_balai_str}\n\n"
            "<b>Unit Prioritas Ground Check:</b>\n"
            f"{top_kps_block}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "📎 <i>Dokumen paparan resmi (.pptx) terlampir.</i>\n"
            f"🔗 <a href=\"{self.settings.frontend_origin}\">Buka Dashboard ETASENEU</a>"
        )

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

            # Cek apakah jam sudah mencapai atau melampaui target_hour (misal 07:00)
            if now_jkt.hour >= target_hour:
                service = DailyReportService()
                if not service.is_daily_report_already_sent(today_str):
                    logger.info(
                        "DAILY_REPORT: Menjalankan pengiriman laporan harian PPTX otomatis untuk tanggal %s...",
                        today_str,
                    )
                    await service.send_daily_telegram_report(force=False)

            # Hitung waktu tunggu hingga esok hari pada jam target_hour:00:05 WIB
            # (atau tunggu 60 detik jika belum jam 7 hari ini)
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
            # Batasi tidur maksimal 300 detik (5 menit) agar responsif terhadap perubahan jam atau reload
            sleep_duration = min(sleep_seconds, 300.0)
            await asyncio.sleep(sleep_duration)

        except asyncio.CancelledError:
            logger.info("DAILY_REPORT: Scheduler dihentikan.")
            break
        except Exception as err:
            logger.error("DAILY_REPORT: Kesalahan pada loop scheduler: %s", err, exc_info=True)
            await asyncio.sleep(60.0)
