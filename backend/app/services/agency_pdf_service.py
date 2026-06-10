"""
Agency PDF report generator using WeasyPrint + Jinja2 HTML templates.
Produces a modern, CSS-styled portrait A4 PDF.
"""
import base64
import logging
import math
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models.query import HotspotQuery

logger = logging.getLogger("hotspot.agency_pdf")

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


# ── helpers ──────────────────────────────────────────────────────────────────

def _conf_cat(h: dict) -> str:
    conf = str(h.get("confidence", "")).strip().lower()
    if conf in ("h", "high"):        return "Tinggi"
    if conf in ("n", "nominal", "medium"): return "Sedang"
    if conf in ("l", "low"):         return "Rendah"
    try:
        v = int(conf)
        return "Tinggi" if v > 80 else "Sedang" if v >= 30 else "Rendah"
    except ValueError:
        return "Rendah"


def _frp_cat(h: dict) -> str:
    try:
        v = float(h.get("frp") or 0)
        return "Tinggi" if v > 30 else "Sedang" if v >= 10 else "Rendah"
    except (ValueError, TypeError):
        return "Rendah"


def _conf_display(h: dict) -> str:
    raw = h.get("confidence")
    try:
        return f"{int(str(raw))}%"
    except (ValueError, TypeError):
        return _conf_cat(h)


def _wib_dt(detected_at: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        return dt.astimezone(timezone(timedelta(hours=7)))
    except Exception:
        return None


# ── basemap (reuse logic from pdf_export_service) ─────────────────────────────

def _sec(x: float) -> float:
    return 1.0 / math.cos(x)


def _latlon_to_tile(lat: float, lon: float, zoom: int):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + _sec(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def _tile_to_latlon(xtile: int, ytile: int, zoom: int):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    return math.degrees(lat_rad), lon_deg


def _fetch_map_b64(hotspots: list[dict], width: int = 520, height: int = 260,
                   force_bounds: tuple | None = None, force_zoom: int | None = None) -> str | None:
    """Download a CartoDB basemap + plot hotspot dots, return base64 PNG string.
    force_bounds=(min_lat, max_lat, min_lon, max_lon) pins the viewport."""
    try:
        from PIL import Image as PILImage, ImageDraw
    except ImportError:
        return None

    lons = [float(h["longitude"]) for h in hotspots if h.get("longitude") is not None]
    lats = [float(h["latitude"])  for h in hotspots if h.get("latitude")  is not None]

    if force_bounds:
        min_lat, max_lat, min_lon, max_lon = force_bounds
    else:
        if not lons:
            return None
        min_lon = min(lons); max_lon = max(lons)
        min_lat = min(lats); max_lat = max(lats)
        pad = 0.05
        min_lon -= pad; max_lon += pad
        min_lat -= pad; max_lat += pad
        if max_lon - min_lon < 0.01: min_lon -= 0.05; max_lon += 0.05
        if max_lat - min_lat < 0.01: min_lat -= 0.05; max_lat += 0.05

    if force_zoom is not None:
        zoom = force_zoom
    else:
        dlon = max_lon - min_lon
        dlat = max_lat - min_lat
        zoom_lon = math.log2(360.0 * width  / (dlon * 256.0 * 1.2))
        zoom_lat = math.log2(180.0 * height / (dlat * 256.0 * 1.2))
        zoom = max(0, min(int(min(zoom_lon, zoom_lat)), 14))

    x1, y1 = _latlon_to_tile(max_lat, min_lon, zoom)
    x2, y2 = _latlon_to_tile(min_lat, max_lon, zoom)
    x_min, x_max = min(x1, x2), max(x1, x2)
    y_min, y_max = min(y1, y2), max(y1, y2)

    while (x_max - x_min + 1) * (y_max - y_min + 1) > 16 and zoom > 0:
        zoom -= 1
        x1, y1 = _latlon_to_tile(max_lat, min_lon, zoom)
        x2, y2 = _latlon_to_tile(min_lat, max_lon, zoom)
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)

    tile_w = 256
    grid_w = (x_max - x_min + 1) * tile_w
    grid_h = (y_max - y_min + 1) * tile_w
    stitched = PILImage.new("RGB", (grid_w, grid_h), (235, 238, 242))

    try:
        client = httpx.Client(timeout=8.0, headers={"User-Agent": "ETAseneu/2.0"})
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                url = f"https://basemaps.cartocdn.com/light_all/{zoom}/{x}/{y}.png"
                try:
                    r = client.get(url)
                    if r.status_code == 200:
                        tile = PILImage.open(BytesIO(r.content)).convert("RGB")
                        stitched.paste(tile, ((x - x_min) * tile_w, (y - y_min) * tile_w))
                except Exception:
                    pass
        client.close()
    except Exception as e:
        logger.warning(f"Map tile fetch error: {e}")

    gll_max, gll_min_lon = _tile_to_latlon(x_min, y_min, zoom)
    gll_min, gll_max_lon = _tile_to_latlon(x_max + 1, y_max + 1, zoom)

    def lon2x(lon: float) -> int:
        return int((lon - gll_min_lon) / (gll_max_lon - gll_min_lon) * grid_w)

    def lat2y(lat: float) -> int:
        n = 2.0 ** zoom
        lr = math.radians(lat)
        yf = (1.0 - math.log(math.tan(lr) + _sec(lr)) / math.pi) / 2.0 * n
        return int((yf - y_min) / (y_max + 1 - y_min) * grid_h)

    cx1 = max(0, lon2x(min_lon)); cx2 = min(grid_w, lon2x(max_lon))
    cy1 = max(0, lat2y(max_lat)); cy2 = min(grid_h, lat2y(min_lat))
    if cx2 - cx1 <= 0 or cy2 - cy1 <= 0:
        return None

    cropped = stitched.crop((cx1, cy1, cx2, cy2)).resize((width, height), PILImage.Resampling.LANCZOS)
    canvas = cropped.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")

    for h in hotspots:
        try:
            lon = float(h["longitude"]); lat = float(h["latitude"])
        except (KeyError, TypeError, ValueError):
            continue
        px = int((lon - min_lon) / (max_lon - min_lon) * width)
        py = int((1 - (lat - min_lat) / (max_lat - min_lat)) * height)
        if not (0 <= px < width and 0 <= py < height):
            continue
        draw.ellipse([px - 8, py - 8, px + 8, py + 8], fill=(220, 38, 38, 55))
        draw.ellipse([px - 4, py - 4, px + 4, py + 4], fill=(220, 38, 38, 220),
                     outline=(127, 29, 29, 255), width=1)

    buf = BytesIO()
    canvas.convert("RGB").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ── SVG trend chart helpers ───────────────────────────────────────────────────

def _build_trend_svg(days: list[str], values: list[float], color: str,
                     w: int = 540, h: int = 80) -> str:
    """Returns SVG content (without outer <svg> tags) for a column trend chart."""
    if not days:
        return f'<text x="{w//2}" y="{h//2}" text-anchor="middle" font-size="10" fill="#94a3b8">Tidak ada data</text>'

    max_v = max(values) if values else 1.0
    if max_v == 0:
        max_v = 1.0

    pad_l, pad_r, pad_t, pad_b = 30, 8, 8, 20
    chart_w = w - pad_l - pad_r
    chart_h = h - pad_t - pad_b
    n = len(days)
    col_w = max(3, chart_w // n - 2)

    parts = []

    # Y-axis lines
    for level in [0.25, 0.5, 0.75, 1.0]:
        y = pad_t + chart_h - int(level * chart_h)
        parts.append(f'<line x1="{pad_l}" y1="{y}" x2="{w - pad_r}" y2="{y}" stroke="#e2e8f0" stroke-width="0.5"/>')
        lv = max_v * level
        label = f"{lv:.0f}" if lv >= 1 else f"{lv:.1f}"
        parts.append(f'<text x="{pad_l - 3}" y="{y + 3}" text-anchor="end" font-size="6" fill="#94a3b8">{label}</text>')

    # Bars
    gap = (chart_w - n * col_w) / (n + 1)
    for i, (day, val) in enumerate(zip(days, values)):
        col_h = max(2, int((val / max_v) * chart_h))
        x = pad_l + int(gap + i * (col_w + gap))
        y = pad_t + chart_h - col_h
        parts.append(f'<rect x="{x}" y="{y}" width="{col_w}" height="{col_h}" fill="{color}" rx="1"/>')

        # x-label (show every nth to avoid overlap)
        if n <= 7 or i % max(1, n // 7) == 0:
            label = day[5:] if len(day) >= 7 else day
            parts.append(f'<text x="{x + col_w//2}" y="{h - 4}" text-anchor="middle" font-size="5.5" fill="#94a3b8">{label}</text>')

    # Bottom axis
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + chart_h}" x2="{w - pad_r}" y2="{pad_t + chart_h}" stroke="#cbd5e1" stroke-width="0.75"/>')

    return "\n".join(parts)


# ── weather fetch ─────────────────────────────────────────────────────────────

def _fetch_weather(lat: float, lon: float) -> dict | None:
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": (
                        "temperature_2m,relative_humidity_2m,precipitation,"
                        "wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
                        "soil_moisture_0_to_10cm,weather_code"
                    ),
                    "timezone": "Asia/Jakarta",
                    "wind_speed_unit": "ms",
                },
            )
            if resp.status_code != 200:
                return None
            wd = resp.json().get("current", {})

            aq_resp = client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality",
                params={"latitude": lat, "longitude": lon, "current": "pm2_5,us_aqi", "timezone": "Asia/Jakarta"},
            )
            aq = aq_resp.json().get("current", {}) if aq_resp.status_code == 200 else {}

            t  = float(wd.get("temperature_2m", 0) or 0)
            rh = float(wd.get("relative_humidity_2m", 0) or 0)
            rh_c = max(0.0, min(100.0, rh))
            cbi = max(0.0, ((110.0 - 1.37 * rh_c) - 9.01) * (10 ** (0.0444 * t)) / 124.0)

            if cbi < 50:    cbi_level = "Rendah"
            elif cbi < 75:  cbi_level = "Sedang"
            elif cbi < 90:  cbi_level = "Tinggi"
            elif cbi < 97.5:cbi_level = "Sangat Tinggi"
            else:           cbi_level = "Ekstrem"

            sm = float(wd.get("soil_moisture_0_to_10cm", 0) or 0)
            sm_status = ("Kering (Ekstrem)" if sm < 0.15 else "Sedang" if sm < 0.25 else "Basah (Aman)")
            sm_color  = ("#ef4444" if sm < 0.15 else "#eab308" if sm < 0.25 else "#22c55e")

            return {
                "temperature": t,
                "humidity": rh,
                "precipitation": float(wd.get("precipitation", 0) or 0),
                "wind_speed": float(wd.get("wind_speed_10m", 0) or 0),
                "wind_dir": float(wd.get("wind_direction_10m", 0) or 0),
                "wind_gusts": float(wd.get("wind_gusts_10m", 0) or 0),
                "soil_moisture": sm,
                "soil_moisture_status": sm_status,
                "soil_moisture_color": sm_color,
                "cbi_value": round(cbi, 2),
                "cbi_level": cbi_level,
                "pm2_5": float(aq.get("pm2_5", 0) or 0),
                "aqi": int(aq.get("us_aqi", 0) or 0),
            }
    except Exception as e:
        logger.warning(f"Weather fetch error: {e}")
        return None


# ── main builder ──────────────────────────────────────────────────────────────

def build_agency_pdf_weasyprint(
    hotspots: list[dict],
    query: HotspotQuery,
    agency_name: str,
    hotspots_ytd: list[dict] | None = None,
) -> bytes:
    """
    Generate a modern WeasyPrint+Jinja2 agency PDF report.
    Returns raw PDF bytes.
    """
    from weasyprint import HTML as WPhtml

    wib_tz = timezone(timedelta(hours=7))
    start_wib = query.start_at.astimezone(wib_tz)
    end_wib   = (query.end_at - timedelta(seconds=1)).astimezone(wib_tz)
    start_str = start_wib.strftime("%d %B %Y")
    end_str   = end_wib.strftime("%d %B %Y")
    period_str   = start_str if start_str == end_str else f"{start_str} – {end_str}"
    download_date = datetime.now(wib_tz).strftime("%d-%m-%Y %H:%M WIB")

    # ── stats ──
    total_hs = len(hotspots)
    conf_counts = {"Tinggi": 0, "Sedang": 0, "Rendah": 0}
    frp_counts  = {"Tinggi": 0, "Sedang": 0, "Rendah": 0}
    for h in hotspots:
        conf_counts[_conf_cat(h)] += 1
        frp_counts[_frp_cat(h)]   += 1

    dom_conf = max(conf_counts, key=lambda k: conf_counts[k]) if total_hs else "N/A"
    dom_frp  = max(frp_counts,  key=lambda k: frp_counts[k])  if total_hs else "N/A"
    frp_vals = [float(h.get("frp") or 0) for h in hotspots]
    avg_frp  = f"{sum(frp_vals)/len(frp_vals):.1f}" if frp_vals else "0.0"

    sat_counts = Counter(h.get("source", "UNKNOWN") for h in hotspots)
    sat_count  = len(sat_counts)

    # ── metadata (full SHP fields) ──
    first_h = hotspots[0] if hotspots else {}
    meta = first_h.get("polygon_metadata", {}) or {}

    def _m(key: str, fallback: str = "N/A") -> str:
        v = meta.get(key)
        return str(v).strip() if v not in (None, "", "null") else fallback

    def _m_area(key: str) -> str:
        v = meta.get(key)
        try:
            val = float(v)
            return f"{val:,.2f} ha" if val > 0 else "—"
        except (TypeError, ValueError):
            return "—"

    lembaga_val = _m("LEMBAGA", agency_name)
    prov_name   = first_h.get("province_name") or _m("NAMA_PROV")
    bps_name    = _m("WILKER_BPS")
    kab_name    = _m("NAMA_KAB")
    kec_name    = _m("NAMA_KEC")
    desa_name   = _m("NAMA_DESA")
    skema       = _m("SKEMA")
    no_sk       = _m("NO_SK")
    tgl_sk      = _m("TGL_SK")
    status_ps   = _m("Status")
    jml_kk      = _m("Jml_KK")
    keterangan  = _m("KETERANGAN")
    luas_final  = _m_area("LuasFinal")
    luas_sk     = _m_area("LUAS_SK")
    luas_hl     = _m_area("LUAS_HL")
    luas_hpt    = _m_area("LUAS_HPT")
    luas_hp     = _m_area("LUAS_HP")
    luas_hpk    = _m_area("LUAS_HPK")
    luas_hk     = _m_area("Luas_HK")
    keliling    = _m("Keliling")
    if keliling != "N/A":
        try:
            keliling = f"{float(keliling):,.2f} km"
        except ValueError:
            keliling = "N/A"

    lats = [float(h["latitude"])  for h in hotspots if h.get("latitude")  is not None]
    lons = [float(h["longitude"]) for h in hotspots if h.get("longitude") is not None]
    avg_lat = f"{sum(lats)/len(lats):.5f}" if lats else "-2.50000"
    avg_lon = f"{sum(lons)/len(lons):.5f}" if lons else "118.00000"

    # ── map — Indonesia full extent ──
    map_b64 = None
    try:
        # Show all of Indonesia (approx bounds), hotspot dots pinned on top
        map_b64 = _fetch_map_b64(
            hotspots, width=520, height=200,
            force_bounds=(-11.0, 6.0, 94.5, 141.5),
            force_zoom=4,
        )
    except Exception as e:
        logger.warning(f"Map generation error: {e}")

    # ── weather ──
    weather = _fetch_weather(float(avg_lat), float(avg_lon))

    cbi_color_map = {
        "Rendah": "#22c55e", "Sedang": "#eab308",
        "Tinggi": "#f97316", "Sangat Tinggi": "#ef4444", "Ekstrem": "#7f1d1d",
    }
    cbi_bg_map = {
        "Rendah": "#f0fdf4", "Sedang": "#fefce8",
        "Tinggi": "#fff7ed", "Sangat Tinggi": "#fff1f2", "Ekstrem": "#fdf2f8",
    }
    cbi_desc_map = {
        "Rendah": "Kondisi tidak mendukung penyebaran api secara aktif.",
        "Sedang": "Potensi kebakaran mulai meningkat, pantau kondisi lapangan.",
        "Tinggi": "Risiko kebakaran tinggi — persiapkan tim respons lapangan.",
        "Sangat Tinggi": "WASPADA — kondisi sangat mendukung penyebaran api cepat.",
        "Ekstrem": "BAHAYA EKSTREM — kebakaran besar sangat mungkin terjadi.",
    }
    cbi_level = weather["cbi_level"] if weather else "N/A"

    # ── chart data ──
    max_conf = max(conf_counts.values()) or 1
    max_frp  = max(frp_counts.values())  or 1
    conf_rows = [
        {"label": "Tinggi", "count": conf_counts["Tinggi"],
         "pct": round(conf_counts["Tinggi"]/total_hs*100) if total_hs else 0,
         "pct_bar": round(conf_counts["Tinggi"]/max_conf*100),
         "color": "#ef4444"},
        {"label": "Sedang", "count": conf_counts["Sedang"],
         "pct": round(conf_counts["Sedang"]/total_hs*100) if total_hs else 0,
         "pct_bar": round(conf_counts["Sedang"]/max_conf*100),
         "color": "#f59e0b"},
        {"label": "Rendah", "count": conf_counts["Rendah"],
         "pct": round(conf_counts["Rendah"]/total_hs*100) if total_hs else 0,
         "pct_bar": round(conf_counts["Rendah"]/max_conf*100),
         "color": "#3b82f6"},
    ]
    frp_rows = [
        {"label": "Tinggi", "count": frp_counts["Tinggi"],
         "pct": round(frp_counts["Tinggi"]/total_hs*100) if total_hs else 0,
         "pct_bar": round(frp_counts["Tinggi"]/max_frp*100),
         "color": "#ef4444"},
        {"label": "Sedang", "count": frp_counts["Sedang"],
         "pct": round(frp_counts["Sedang"]/total_hs*100) if total_hs else 0,
         "pct_bar": round(frp_counts["Sedang"]/max_frp*100),
         "color": "#f97316"},
        {"label": "Rendah", "count": frp_counts["Rendah"],
         "pct": round(frp_counts["Rendah"]/total_hs*100) if total_hs else 0,
         "pct_bar": round(frp_counts["Rendah"]/max_frp*100),
         "color": "#22c55e"},
    ]

    sat_total = sum(sat_counts.values()) or 1
    sat_color_map = {
        "MODIS": "#d97706", "VIIRS S-NPP": "#7c3aed",
        "VIIRS NOAA-20": "#0f766e", "VIIRS NOAA-21": "#0284c7",
    }
    color_pool = ["#0f766e", "#0284c7", "#dc2626", "#d97706", "#7c3aed"]
    max_sat = max(sat_counts.values()) if sat_counts else 1
    sat_rows = [
        {
            "label": src,
            "count": cnt,
            "pct": round(cnt / sat_total * 100),
            "color": sat_color_map.get(src, color_pool[i % len(color_pool)]),
        }
        for i, (src, cnt) in enumerate(sorted(sat_counts.items(), key=lambda x: -x[1]))
    ]

    # ── daily stats for Section 05 (full YTD if available, else fall back to current filter) ──
    _ytd_source = hotspots_ytd if hotspots_ytd is not None else hotspots
    daily_vol: Counter = Counter()
    daily_frp_sum: dict[str, float] = {}
    daily_max_frp: dict[str, float] = {}
    for h in _ytd_source:
        dt = _wib_dt(str(h.get("detected_at", "")))
        if dt:
            day = dt.strftime("%Y-%m-%d")
            daily_vol[day] += 1
            frp_v = float(h.get("frp") or 0)
            daily_frp_sum[day] = daily_frp_sum.get(day, 0.0) + frp_v
            daily_max_frp[day] = max(daily_max_frp.get(day, 0.0), frp_v)

    sorted_days = sorted(set(list(daily_vol.keys()) + list(daily_frp_sum.keys())))

    max_day_count = max(daily_vol.values()) if daily_vol else 1
    total_frp_all = round(sum(daily_frp_sum.values()), 1)
    active_days   = len(sorted_days)
    peak_day_count = max(daily_vol.values()) if daily_vol else 0
    peak_day_date  = max(daily_vol, key=daily_vol.get) if daily_vol else "—"  # type: ignore[arg-type]
    try:
        peak_day_display = datetime.strptime(peak_day_date, "%Y-%m-%d").strftime("%d %b %Y") if peak_day_date != "—" else "—"
    except ValueError:
        peak_day_display = peak_day_date
    avg_daily = f"{total_hs / active_days:.1f}" if active_days else "0"

    def _day_color(count: int, max_c: int) -> tuple[str, str]:
        ratio = count / max_c if max_c else 0
        if ratio >= 0.75: return "#dc2626", "badge-red"
        if ratio >= 0.40: return "#f97316", "badge-amber"
        return "#16a34a", "badge-green"

    daily_stats = []
    for day in sorted_days:
        cnt = daily_vol.get(day, 0)
        frp_t = round(daily_frp_sum.get(day, 0.0), 1)
        bar_pct = round(cnt / max_day_count * 100) if max_day_count else 0
        bar_color, status_badge = _day_color(cnt, max_day_count)
        status_lbl = "Tinggi" if status_badge == "badge-red" else "Sedang" if status_badge == "badge-amber" else "Rendah"
        try:
            date_disp = datetime.strptime(day, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            date_disp = day
        daily_stats.append({
            "date_display": date_disp,
            "count": cnt,
            "frp_total": frp_t,
            "bar_pct": bar_pct,
            "bar_color": bar_color,
            "status": status_lbl,
            "status_badge": status_badge,
        })

    # kept for template compat (unused but harmless)
    trend_svg_w = 540
    trend_svg_h = 80

    # ── hotspot rows ──
    hotspot_rows = []
    for idx, h in enumerate(hotspots):
        dt = _wib_dt(str(h.get("detected_at", "")))
        date_str = dt.strftime("%d-%m-%Y %H:%M") if dt else str(h.get("detected_at", ""))[:16]
        fc = _frp_cat(h)
        cc = _conf_cat(h)
        row_class = (
            "frp-high" if fc == "Tinggi"
            else "frp-med" if fc == "Sedang"
            else ("frp-low-odd" if idx % 2 == 0 else "frp-low-even")
        )
        frp_raw = h.get("frp", "-")
        try:
            frp_display = f"{float(frp_raw):.2f}"
        except (ValueError, TypeError):
            frp_display = str(frp_raw)

        daynight = str(h.get("daynight") or h.get("day_night") or "").strip().upper() or "-"

        hotspot_rows.append({
            "no": idx + 1,
            "date": date_str,
            "source": h.get("source", "N/A"),
            "daynight": daynight,
            "confidence": _conf_display(h),
            "conf_cat": cc,
            "brightness": h.get("brightness", "-"),
            "frp": frp_display,
            "frp_cat": fc,
            "lat": f"{float(h.get('latitude', 0)):.4f}",
            "lon": f"{float(h.get('longitude', 0)):.4f}",
            "row_class": row_class,
        })

    # ── render template ──
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    tmpl = env.get_template("agency_report.html")

    html_str = tmpl.render(
        agency_name=agency_name,
        period_str=period_str,
        download_date=download_date,
        total_hs=total_hs,
        sat_count=sat_count,
        dom_conf=dom_conf,
        dom_frp=dom_frp,
        avg_frp=avg_frp,
        avg_lat=avg_lat,
        avg_lon=avg_lon,
        # profile metadata
        lembaga_val=lembaga_val,
        skema=skema,
        no_sk=no_sk,
        tgl_sk=tgl_sk,
        status_ps=status_ps,
        bps_name=bps_name,
        prov_name=prov_name,
        kab_name=kab_name,
        kec_name=kec_name,
        desa_name=desa_name,
        jml_kk=jml_kk,
        keterangan=keterangan,
        luas_final=luas_final,
        luas_sk=luas_sk,
        luas_hl=luas_hl,
        luas_hpt=luas_hpt,
        luas_hp=luas_hp,
        luas_hpk=luas_hpk,
        luas_hk=luas_hk,
        keliling=keliling,
        map_image_b64=map_b64,
        weather=weather,
        cbi_color=cbi_color_map.get(cbi_level, "#64748b"),
        cbi_bg=cbi_bg_map.get(cbi_level, "#f8fafc"),
        cbi_desc=cbi_desc_map.get(cbi_level, ""),
        conf_rows=conf_rows,
        frp_rows=frp_rows,
        sat_rows=sat_rows,
        # section 05 - daily ops
        daily_stats=daily_stats,
        peak_day_display=peak_day_display,
        peak_day_count=peak_day_count,
        total_frp_all=total_frp_all,
        active_days=active_days,
        avg_daily=avg_daily,
        trend_svg_w=trend_svg_w,
        trend_svg_h=trend_svg_h,
        hotspot_rows=hotspot_rows,
    )

    pdf_bytes = WPhtml(string=html_str, base_url=str(TEMPLATE_DIR)).write_pdf()
    return pdf_bytes
