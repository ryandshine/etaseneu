import logging
import math
import os
from datetime import datetime, timedelta, timezone
from io import BytesIO
from collections import Counter

import httpx
from PIL import Image as PILImage

from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas

# Graphics and drawing for the PDF
from reportlab.graphics.shapes import Drawing, Rect, Circle, Line, String as DString, Image as DImage

from app.models.query import HotspotQuery
from app.services.hotspot_categories import confidence_category as _get_conf_cat, frp_category as _get_frp_cat
from app.services.polygon_fields import sk_number
from app.services.skema_stats import (
    build_skema_provinsi_matrix,
    collapse_skema_columns,
    count_per_skema,
)

logger = logging.getLogger("hotspot.pdf_export")

# Colors matching the application's visual system
COLOR_PRIMARY = colors.HexColor("#1e3a8a")     # Deep blue
COLOR_SECONDARY = colors.HexColor("#0f766e")   # Teal
COLOR_ACCENT = colors.HexColor("#dc2626")      # Red / Alert
COLOR_NEUTRAL_DARK = colors.HexColor("#1f2937")# Charcoal text
COLOR_NEUTRAL_LIGHT = colors.HexColor("#f3f4f6")# Light grey
COLOR_BORDER = colors.HexColor("#e5e7eb")       # Border grey
COLOR_WHITE = colors.HexColor("#ffffff")

# Kolom Conf dilebarkan supaya muat "Sedang (28%)": kategori selalu tampil,
# nilai mentahnya tetap ikut kalau satelitnya memberi angka. Kolom No. SK juga
# ditambahkan. Total lebar dijaga tetap 769pt (lebar area cetak A4 lanskap),
# jadi penambahan diambil dari kolom lain yang masih longgar.
HOTSPOT_TABLE_COL_WIDTHS = [30, 136, 110, 68, 92, 56, 56, 62, 46, 46, 67]


def _get_wib_date_str(detected_at: str) -> str:
    if not detected_at:
        return ""
    try:
        from datetime import timezone, timedelta
        dt = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        return dt.astimezone(timezone(timedelta(hours=7))).strftime("%Y-%m-%d")
    except Exception:
        return str(detected_at)[:10]


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically calculate the total page count
    and draw a professional header and footer on every page.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        
        # Access metadata stored on the canvas instance
        period_str = getattr(self, "period_str", "N/A")
        download_date = getattr(self, "download_date", "N/A")

        # Top Header
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(COLOR_PRIMARY)
        self.drawString(36, 562, "ETAseneu — SISTEM PEMANTAUAN HOTSPOT PERHUTANAN SOSIAL")
        
        self.setFont("Helvetica", 8)
        self.setFillColor(COLOR_NEUTRAL_DARK)
        self.drawRightString(805, 562, f"Periode Laporan: {period_str}")
        
        # Header rule
        self.setStrokeColor(COLOR_BORDER)
        self.setLineWidth(0.75)
        self.line(36, 552, 805, 552)

        # Footer rule
        self.line(36, 40, 805, 40)

        # Bottom Footer
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(COLOR_NEUTRAL_DARK)
        self.drawString(36, 25, "DOKUMEN EKSEKUTIF")
        
        self.setFont("Helvetica", 8)
        self.drawCentredString(420, 25, f"Tanggal Unduh: {download_date}")
        self.drawRightString(805, 25, f"Halaman {self._pageNumber} dari {page_count}")
        
        self.restoreState()


def sec(x):
    return 1.0 / math.cos(x)


def latlon_to_tile(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.log(math.tan(lat_rad) + sec(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def tile_to_latlon(xtile, ytile, zoom):
    n = 2.0 ** zoom
    lon_deg = xtile / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


def fetch_basemap_image(min_lon, min_lat, max_lon, max_lat, width=540, height=210) -> str | None:
    """
    Downloads static map tiles from CartoDB Positron and stitches them to fit the bounding box.
    Uses 2x resolution internally then downsamples for crisp output.
    """
    dlon = max(0.005, max_lon - min_lon)
    dlat = max(0.005, max_lat - min_lat)

    # Calculate appropriate zoom level
    zoom_lon = math.log2(360.0 * (width * 0.8) / (dlon * 256.0))
    zoom_lat = math.log2(180.0 * (height * 0.8) / (dlat * 256.0))
    zoom = int(min(zoom_lon, zoom_lat))
    zoom = max(0, min(zoom, 18))

    # Limit zoom to prevent downloading too many tiles
    x1, y1 = latlon_to_tile(max_lat, min_lon, zoom)
    x2, y2 = latlon_to_tile(min_lat, max_lon, zoom)

    x_min, x_max = min(x1, x2), max(x1, x2)
    y_min, y_max = min(y1, y2), max(y1, y2)

    while (x_max - x_min + 1) * (y_max - y_min + 1) > 16 and zoom > 0:
        zoom -= 1
        x1, y1 = latlon_to_tile(max_lat, min_lon, zoom)
        x2, y2 = latlon_to_tile(min_lat, max_lon, zoom)
        x_min, x_max = min(x1, x2), max(x1, x2)
        y_min, y_max = min(y1, y2), max(y1, y2)

    tile_width = 256
    grid_w = (x_max - x_min + 1) * tile_width
    grid_h = (y_max - y_min + 1) * tile_width

    stitched = PILImage.new("RGB", (grid_w, grid_h), color=(235, 238, 242))

    headers = {"User-Agent": "ETAseneu-PDF-Generator/1.0"}
    client = httpx.Client(timeout=8.0)

    success = False
    for x in range(x_min, x_max + 1):
        for y in range(y_min, y_max + 1):
            url = f"https://basemaps.cartocdn.com/light_all/{zoom}/{x}/{y}.png"
            try:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    tile_img = PILImage.open(BytesIO(resp.content)).convert("RGB")
                    px = (x - x_min) * tile_width
                    py = (y - y_min) * tile_width
                    stitched.paste(tile_img, (px, py))
                    success = True
            except Exception as e:
                logger.warning(f"Failed to fetch tile {zoom}/{x}/{y}: {e}")

    if not success:
        return None

    grid_lat_max, grid_lon_min = tile_to_latlon(x_min, y_min, zoom)
    grid_lat_min, grid_lon_max = tile_to_latlon(x_max + 1, y_max + 1, zoom)

    def lon_to_x(lon):
        return int((lon - grid_lon_min) / (grid_lon_max - grid_lon_min) * grid_w)

    def lat_to_y(lat):
        n = 2.0 ** zoom
        lat_rad = math.radians(lat)
        y = (1.0 - math.log(math.tan(lat_rad) + sec(lat_rad)) / math.pi) / 2.0 * n
        y_min_val = y_min
        y_max_val = y_max + 1
        return int((y - y_min_val) / (y_max_val - y_min_val) * grid_h)

    crop_x1 = max(0, lon_to_x(min_lon))
    crop_x2 = min(grid_w, lon_to_x(max_lon))
    crop_y1 = max(0, lat_to_y(max_lat))
    crop_y2 = min(grid_h, lat_to_y(min_lat))

    if crop_x2 - crop_x1 <= 0 or crop_y2 - crop_y1 <= 0:
        return None

    cropped = stitched.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    cropped = cropped.resize((width, height), PILImage.Resampling.LANCZOS)

    temp_path = f"/tmp/basemap_{min_lon:.4f}_{min_lat:.4f}_{width}x{height}.png"
    cropped.save(temp_path, "PNG")
    return temp_path


def create_map_with_hotspots_png(
    hotspots: list[dict],
    layers_info: list[dict],
    width: int = 1080,
    height: int = 420,
) -> str | None:
    """
    Render a high-quality raster map with hotspot markers and legend.
    Returns the path to a PNG file suitable for embedding in the PDF,
    or None if rendering failed entirely.
    """
    from PIL import ImageDraw, ImageFont

    # ---- coordinate bounds ----
    min_lon, min_lat, max_lon, max_lat = None, None, None, None
    for layer in layers_info:
        b = layer.get("bounds")
        if b:
            lnl = float(b.get("min_lon", 0))
            lsl = float(b.get("min_lat", 0))
            lnu = float(b.get("max_lon", 0))
            lsu = float(b.get("max_lat", 0))
            min_lon = lnl if min_lon is None else min(min_lon, lnl)
            min_lat = lsl if min_lat is None else min(min_lat, lsl)
            max_lon = lnu if max_lon is None else max(max_lon, lnu)
            max_lat = lsu if max_lat is None else max(max_lat, lsu)

    if min_lon is None or max_lon is None or min_lon == max_lon:
        min_lon, max_lon = 95.0, 141.0
    if min_lat is None or max_lat is None or min_lat == max_lat:
        min_lat, max_lat = -11.0, 6.0

    PAD = 4  # pixel padding inside the drawing area (in output coords)

    # ---- fetch basemap ----
    basemap_path = None
    try:
        basemap_path = fetch_basemap_image(min_lon, min_lat, max_lon, max_lat, width, height)
    except Exception as e:
        logger.error(f"create_map_with_hotspots_png: basemap error: {e}")

    if basemap_path and os.path.exists(basemap_path):
        canvas_img = PILImage.open(basemap_path).convert("RGBA")
        canvas_img = canvas_img.resize((width, height), PILImage.Resampling.LANCZOS)
    else:
        # fallback: plain background
        canvas_img = PILImage.new("RGBA", (width, height), (235, 238, 242, 255))

    draw = ImageDraw.Draw(canvas_img, "RGBA")

    # ---- helper: geo → pixel ----
    def geo_to_px(lon, lat):
        px = PAD + (lon - min_lon) / (max_lon - min_lon) * (width - 2 * PAD)
        py = PAD + (1.0 - (lat - min_lat) / (max_lat - min_lat)) * (height - 2 * PAD)
        return int(px), int(py)

    # ---- draw hotspots ----
    plotted = 0
    GLOW_R = 9
    DOT_R = 4
    for hs in hotspots:
        try:
            lon = float(hs.get("longitude", 0))
            lat = float(hs.get("latitude", 0))
        except (ValueError, TypeError):
            continue
        px, py = geo_to_px(lon, lat)
        if not (0 <= px < width and 0 <= py < height):
            continue
        # soft glow
        draw.ellipse(
            [px - GLOW_R, py - GLOW_R, px + GLOW_R, py + GLOW_R],
            fill=(220, 38, 38, 70),
        )
        # core dot
        draw.ellipse(
            [px - DOT_R, py - DOT_R, px + DOT_R, py + DOT_R],
            fill=(220, 38, 38, 230),
            outline=(127, 29, 29, 255),
            width=1,
        )
        plotted += 1

    # ---- legend panel (bottom-left) ----
    LEG_W, LEG_H = 210, 44
    LEG_X, LEG_Y = 8, height - LEG_H - 8
    draw.rounded_rectangle(
        [LEG_X, LEG_Y, LEG_X + LEG_W, LEG_Y + LEG_H],
        radius=6,
        fill=(255, 255, 255, 200),
        outline=(180, 190, 210, 255),
        width=1,
    )
    # legend title
    try:
        fnt_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        fnt_xs = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
    except Exception:
        fnt_sm = ImageFont.load_default()
        fnt_xs = fnt_sm

    draw.text((LEG_X + 8, LEG_Y + 5), "KETERANGAN", fill=(30, 58, 138, 255), font=fnt_sm)
    # hotspot symbol
    draw.ellipse([LEG_X + 8, LEG_Y + 22, LEG_X + 16, LEG_Y + 30], fill=(220, 38, 38, 220))
    draw.text((LEG_X + 20, LEG_Y + 21), f"Titik Panas (Hotspot) — {plotted} titik", fill=(31, 41, 55, 255), font=fnt_xs)

    # ---- coordinate label (bottom-right) ----
    coord_txt = f"{min_lon:.1f}°E – {max_lon:.1f}°E  /  {min_lat:.1f}°N – {max_lat:.1f}°N"
    bbox = draw.textbbox((0, 0), coord_txt, font=fnt_xs)
    txt_w = bbox[2] - bbox[0]
    draw.rectangle(
        [width - txt_w - 18, height - 20, width - 1, height - 1],
        fill=(255, 255, 255, 180),
    )
    draw.text((width - txt_w - 10, height - 17), coord_txt, fill=(75, 85, 99, 255), font=fnt_xs)

    # ---- thin border ----
    draw.rectangle([0, 0, width - 1, height - 1], outline=(180, 190, 210, 255), width=1)

    # ---- save ----
    out_path = f"/tmp/map_hotspots_{min_lon:.2f}_{min_lat:.2f}_{width}x{height}.png"
    canvas_img.convert("RGB").save(out_path, "PNG", optimize=False)
    return out_path


def create_spatial_map_drawing(hotspots: list[dict], layers_info: list[dict], width=420, height=210) -> Drawing:
    """
    Renders a spatial map with basemap image and hotspot overlay.
    Tries high-quality PIL-based rendering first; falls back to vector-only drawing.
    """

    d = Drawing(width, height)

    # Outer frame
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f8fafc"), strokeColor=COLOR_BORDER, strokeWidth=1, rx=4, ry=4))

    # Try to generate a full PIL-rendered map (basemap + hotspot markers)
    map_png = None
    try:
        map_png = create_map_with_hotspots_png(
            hotspots, layers_info,
            width=int((width - 20) * 2),   # 2× oversample for crispness
            height=int((height - 20) * 2),
        )
    except Exception as e:
        logger.error(f"create_spatial_map_drawing: PIL map error: {e}")

    if map_png and os.path.exists(map_png):
        # Embed the PNG inside the Drawing — DImage(x, y, w, h, path)
        d.add(DImage(10, 10, width - 20, height - 20, map_png))
        # Title overlay (on top of the image)
        d.add(DString(
            14, height - 14,
            "PETA SEBARAN SPASIAL HOTSPOT (VEKTOR)",
            fontName="Helvetica-Bold", fontSize=7,
            fillColor=colors.HexColor("#1e3a8a"),
        ))
        return d

    # ---- Fallback: pure-vector drawing (no basemap) ----
    # Determine bounds
    min_lon, min_lat, max_lon, max_lat = None, None, None, None
    for layer in layers_info:
        bounds = layer.get("bounds")
        if bounds:
            l_min_lon = float(bounds.get("min_lon", 0))
            l_min_lat = float(bounds.get("min_lat", 0))
            l_max_lon = float(bounds.get("max_lon", 0))
            l_max_lat = float(bounds.get("max_lat", 0))
            min_lon = l_min_lon if min_lon is None else min(min_lon, l_min_lon)
            min_lat = l_min_lat if min_lat is None else min(min_lat, l_min_lat)
            max_lon = l_max_lon if max_lon is None else max(max_lon, l_max_lon)
            max_lat = l_max_lat if max_lat is None else max(max_lat, l_max_lat)

    if min_lon is None or max_lon is None or min_lon == max_lon:
        min_lon, max_lon = 95.0, 141.0
    if min_lat is None or max_lat is None or min_lat == max_lat:
        min_lat, max_lat = -11.0, 6.0

    # Draw base map image inside the padded area
    temp_map_file = None
    try:
        temp_map_file = fetch_basemap_image(min_lon, min_lat, max_lon, max_lat, int(width - 40), int(height - 30))
    except Exception as e:
        logger.error(f"Failed to generate basemap image: {e}")

    if temp_map_file and os.path.exists(temp_map_file):
        d.add(DImage(20, 15, width - 40, height - 30, temp_map_file))

    # Draw grid lines
    grid_color = colors.HexColor("#cbd5e1")
    for i in range(1, 4):
        x = width * (i / 4.0)
        d.add(Line(x, 0, x, height, strokeColor=grid_color, strokeWidth=0.5, strokeDashArray=[2, 2]))
    for i in range(1, 3):
        y = height * (i / 3.0)
        d.add(Line(0, y, width, y, strokeColor=grid_color, strokeWidth=0.5, strokeDashArray=[2, 2]))

    # Draw spatial boundaries
    for layer in layers_info:
        bounds = layer.get("bounds")
        if not bounds:
            continue
        l_min_lon = float(bounds.get("min_lon", 0))
        l_min_lat = float(bounds.get("min_lat", 0))
        l_max_lon = float(bounds.get("max_lon", 0))
        l_max_lat = float(bounds.get("max_lat", 0))
        px_min = 20 + (l_min_lon - min_lon) / (max_lon - min_lon) * (width - 40)
        px_max = 20 + (l_max_lon - min_lon) / (max_lon - min_lon) * (width - 40)
        py_min = 15 + (l_min_lat - min_lat) / (max_lat - min_lat) * (height - 30)
        py_max = 15 + (l_max_lat - min_lat) / (max_lat - min_lat) * (height - 30)
        layer_color = colors.HexColor(layer.get("color", "#0f766e"))
        d.add(Rect(px_min, py_min, max(2, px_max - px_min), max(2, py_max - py_min),
                   fillColor=None, strokeColor=layer_color, strokeWidth=1, strokeDashArray=[4, 2]))

    # Plot hotspots
    plotted_count = 0
    for hotspot in hotspots:
        try:
            lon = float(hotspot.get("longitude", 0))
            lat = float(hotspot.get("latitude", 0))
        except (ValueError, TypeError):
            continue
        x = 20 + (lon - min_lon) / (max_lon - min_lon) * (width - 40)
        y = 15 + (lat - min_lat) / (max_lat - min_lat) * (height - 30)
        x = max(5, min(width - 5, x))
        y = max(5, min(height - 5, y))
        d.add(Circle(x, y, 3, fillColor=COLOR_ACCENT, strokeColor=colors.HexColor("#7f1d1d"), strokeWidth=0.5))
        plotted_count += 1

    d.add(DString(10, height - 15, "PETA SEBARAN SPASIAL HOTSPOT (VEKTOR)", fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_PRIMARY))
    d.add(DString(10, 10, f"Bounds: {min_lon:.2f}°E - {max_lon:.2f}°E / {min_lat:.2f}°N - {max_lat:.2f}°N", fontName="Helvetica", fontSize=7, fillColor=COLOR_NEUTRAL_DARK))
    d.add(DString(width - 120, 10, f"Hotspot Terpetakan: {plotted_count}", fontName="Helvetica", fontSize=7, fillColor=COLOR_NEUTRAL_DARK))

    return d


def _create_kpi_card(value: str, label: str, val_color) -> Table:
    p_val = Paragraph(value, ParagraphStyle("KpiVal", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=val_color, alignment=1))
    p_lbl = Paragraph(label, ParagraphStyle("KpiLbl", fontName="Helvetica-Bold", fontSize=7.5, leading=9, textColor=COLOR_NEUTRAL_DARK, alignment=1))
    t = Table([[p_val], [p_lbl]], colWidths=[175])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 1, COLOR_BORDER),
        ('PADDING', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    return t


def create_pie_chart(hotspots: list[dict], width=210, height=135) -> Drawing:
    """
    Renders a horizontal bar chart showing hotspot distribution by satellite source.
    """
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f8fafc"), strokeColor=COLOR_BORDER, strokeWidth=1, rx=4, ry=4))
    d.add(DString(10, height - 15, "PROPORSI PER SATELIT", fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_PRIMARY))

    counts = Counter(h.get("source", "UNKNOWN") for h in hotspots)
    if not counts:
        d.add(DString(width / 2, height / 2, "Tidak ada data", fontName="Helvetica", fontSize=9, textAnchor="middle", fillColor=COLOR_NEUTRAL_DARK))
        return d

    sorted_sources = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    total = sum(counts.values())
    max_val = max(counts.values())

    # Layout calculations
    left_margin = 12
    y_start = height - 32
    row_gap = (height - 45) / max(3, len(sorted_sources))
    bar_height = 8
    max_bar_width = width - left_margin - 55 # space for text at the end

    color_map = {
        "MODIS": colors.HexColor("#d97706"),
        "VIIRS S-NPP": colors.HexColor("#7c3aed"),
        "VIIRS NOAA-20": COLOR_PRIMARY,
        "VIIRS NOAA-21": COLOR_SECONDARY,
    }
    color_pool = [
        COLOR_PRIMARY, COLOR_SECONDARY, COLOR_ACCENT,
        colors.HexColor("#d97706"), colors.HexColor("#7c3aed")
    ]

    for idx, (source, val) in enumerate(sorted_sources):
        current_y = y_start - idx * row_gap
        
        # Draw label above the bar
        d.add(DString(left_margin, current_y + 10, source, fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_NEUTRAL_DARK))
        
        # Calculate bar width
        bar_w = max(4, int((val / max(max_val, 1)) * max_bar_width)) if val > 0 else 0
        color = color_map.get(source)
        if not color:
            color = color_pool[idx % len(color_pool)]
        
        if bar_w > 0:
            d.add(Rect(left_margin, current_y, bar_w, bar_height, fillColor=color, strokeColor=None, rx=1.5, ry=1.5))
        
        # Draw value
        pct = int(round((val / total) * 100)) if total else 0
        d.add(DString(left_margin + bar_w + 6, current_y + 1, f"{val} ({pct}%)", fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_NEUTRAL_DARK))

    return d


def get_ranked_wilkers(hotspots: list[dict]) -> list[tuple[str, int]]:
    """Peringkat per BALAI PS (wilayah kerja), sesuai field WILKER_BPS.

    Sebelumnya fungsi ini mendahulukan `layer_name` -- yaitu nama lembaga/KPS --
    sehingga tabel yang berjudul "Balai Pengelola" justru menampilkan ratusan
    lembaga, dan bertentangan dengan ringkasan spasial di halaman berikutnya
    yang menghitung jumlah balai dari WILKER_BPS.
    """
    counts = Counter()
    for hotspot in hotspots:
        wilker = hotspot.get("polygon_metadata", {}).get("WILKER_BPS") or "Belum Ditugaskan"
        counts[wilker] += 1
    return counts.most_common()


def get_ranked_lembaga(hotspots: list[dict]) -> list[tuple[str, int]]:
    """Peringkat per LEMBAGA/KPS (nama pemegang izin perhutanan sosial)."""
    counts = Counter()
    for hotspot in hotspots:
        lembaga = hotspot.get("layer_name") or hotspot.get("agency_name") or "Tidak Diketahui"
        counts[lembaga] += 1
    return counts.most_common()



def create_bar_chart_drawing(data_points: list[tuple[str, int, str]], title: str, width=370, height=150) -> Drawing:
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f8fafc"), strokeColor=COLOR_BORDER, strokeWidth=1, rx=4, ry=4))
    d.add(DString(10, height - 15, title, fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_PRIMARY))
    
    total = sum(v for _, v, _ in data_points)
    if total == 0:
        d.add(DString(width/2, height/2, "Tidak ada data", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=COLOR_NEUTRAL_DARK))
        return d

    max_val = max(v for _, v, _ in data_points)
    bar_max_width = width - 150
    available_height = height - 40
    row_height = available_height / 3
    bar_height = 12
    font_size = 8
    start_y = height - 40

    for idx, (label, val, col) in enumerate(data_points):
        current_y = start_y - (idx + 1) * row_height
        pct = int(round((val / total) * 100)) if total else 0
        d.add(DString(15, current_y + bar_height * 0.15, label, fontName="Helvetica-Bold", fontSize=font_size, fillColor=COLOR_NEUTRAL_DARK))
        
        bar_w = max(5, int((val / max(max_val, 1)) * bar_max_width)) if val > 0 else 0
        if bar_w > 0:
            d.add(Rect(60, current_y, bar_w, bar_height, fillColor=colors.HexColor(col), strokeColor=None, rx=2, ry=2))
        d.add(DString(60 + bar_w + 8, current_y + bar_height * 0.15, f"{val} ({pct}%)", fontName="Helvetica-Bold", fontSize=font_size, fillColor=COLOR_NEUTRAL_DARK))
        
    return d

def create_balai_ranking_table(
    hotspots: list[dict],
    tbl_header_style,
    body_style,
    bold_body_style,
    ranked: list[tuple[str, int]] | None = None,
    name_header: str = "Balai Pengelola",
) -> "Table":
    """
    Builds a full ReportLab Table of ALL affected rows sorted by hotspot count.
    Grows vertically to fit all rows — no limit.
    """
    if ranked is None:
        ranked = get_ranked_wilkers(hotspots)

    header = [
        Paragraph("#", tbl_header_style),
        Paragraph(name_header, tbl_header_style),
        Paragraph("Titik Panas", tbl_header_style),
        Paragraph("%", tbl_header_style),
    ]
    total = sum(c for _, c in ranked)
    rows = [header]
    for idx, (name, count) in enumerate(ranked, start=1):
        pct = f"{count / total * 100:.1f}%" if total else "0%"
        rows.append([
            Paragraph(str(idx), body_style),
            Paragraph(name, bold_body_style),
            Paragraph(str(count), body_style),
            Paragraph(pct, body_style),
        ])

    # repeatRows=1 supaya header kolom ikut tercetak di tiap halaman lanjutan --
    # daftar lembaga bisa memanjang belasan halaman dan tanpa ini pembaca
    # kehilangan konteks kolom setelah halaman pertama.
    tbl = Table(rows, colWidths=[30, None, 65, 45], repeatRows=1)
    row_bg = [colors.HexColor("#fff1f2"), COLOR_NEUTRAL_LIGHT]
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_SECONDARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_WHITE),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (3, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), row_bg),
        ('PADDING', (0, 0), (-1, -1), 4),
        # Highlight top-1
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor("#fef2f2")),
    ]))
    return tbl


def create_daily_volume_trend_chart(hotspots: list[dict], width=370, height=100) -> Drawing:
    """
    Renders a vertical column/bar chart showing daily hotspot counts.
    """
    d = Drawing(width, height)
    
    # Outer frame
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f8fafc"), strokeColor=COLOR_BORDER, strokeWidth=1, rx=4, ry=4))
    
    # Header
    d.add(DString(10, height - 12, "VOLUME INSIDEN HARIAN (TITIK PANAS)", fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_PRIMARY))
    
    # Count per day (YYYY-MM-DD)
    daily_counts = Counter()
    for h in hotspots:
        date_str = _get_wib_date_str(str(h.get("detected_at", "")))
        if date_str:
            daily_counts[date_str] += 1
            
    if not daily_counts:
        d.add(DString(width/2, height/2, "Tidak ada data", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=COLOR_NEUTRAL_DARK))
        return d
        
    sorted_days = sorted(daily_counts.keys())
    counts_list = [daily_counts[day] for day in sorted_days]
    
    if len(sorted_days) < 5:
        max_val = max(counts_list) if counts_list else 1
        
        left_margin = 12
        y_start = height - 28
        row_gap = (height - 38) / max(1, len(sorted_days))
        bar_height = 8
        max_bar_width = width - left_margin - 85
        
        months_id = {
            "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "Mei", "06": "Jun",
            "07": "Jul", "08": "Ags", "09": "Sep", "10": "Okt", "11": "Nov", "12": "Des"
        }
        
        for idx, day in enumerate(sorted_days):
            val = daily_counts[day]
            current_y = y_start - idx * row_gap
            
            parts = day.split("-")
            date_label = f"{parts[2]} {months_id.get(parts[1], parts[1])}" if len(parts) == 3 else day
            
            d.add(DString(left_margin, current_y + 1, date_label, fontName="Helvetica-Bold", fontSize=7.5, fillColor=COLOR_NEUTRAL_DARK))
            
            bar_w = max(4, int((val / max_val) * max_bar_width)) if val > 0 else 0
            if bar_w > 0:
                d.add(Rect(60, current_y, bar_w, bar_height, fillColor=COLOR_PRIMARY, strokeColor=None, rx=1.5, ry=1.5))
                
            d.add(DString(60 + bar_w + 6, current_y + 1, f"{val} hotspot", fontName="Helvetica-Bold", fontSize=7.5, fillColor=COLOR_NEUTRAL_DARK))
            
        return d

    if len(sorted_days) > 15:
        sorted_days = sorted_days[-15:]
        counts_list = [daily_counts[day] for day in sorted_days]

    max_val = max(counts_list) if counts_list else 1
    
    # Dimensions for chart area
    chart_x = 35
    chart_y = 20
    chart_w = width - 50
    chart_h = height - 40
    
    # Y Axis Grid lines
    d.add(Line(chart_x, chart_y, chart_x + chart_w, chart_y, strokeColor=COLOR_BORDER, strokeWidth=0.5))
    d.add(Line(chart_x, chart_y + chart_h, chart_x + chart_w, chart_y + chart_h, strokeColor=COLOR_BORDER, strokeWidth=0.5))
    
    # Draw bars
    num_days = len(sorted_days)
    col_w = max(4, int(chart_w / (num_days or 1)) - 4)
    col_gap = int((chart_w - (num_days * (col_w + 2))) / 2) if num_days > 0 else 0
    
    for idx, day in enumerate(sorted_days):
        val = daily_counts[day]
        col_h = max(2, int((val / max_val) * chart_h))
        
        # Calculate coordinate
        col_x = chart_x + col_gap + idx * (col_w + 2)
        
        # Draw bar (primary blue color)
        d.add(Rect(col_x, chart_y, col_w, col_h, fillColor=COLOR_PRIMARY, strokeColor=None, rx=1, ry=1))
        
        # Draw small date label on the bottom
        if num_days <= 7 or idx == 0 or idx == num_days - 1 or idx % 3 == 0:
            short_date = day[5:]
            d.add(DString(col_x + col_w/2, chart_y - 10, short_date, fontName="Helvetica", fontSize=6, textAnchor="middle", fillColor=COLOR_NEUTRAL_DARK))
            
    # Y-axis labels
    d.add(DString(chart_x - 5, chart_y, "0", fontName="Helvetica", fontSize=6, textAnchor="end", fillColor=COLOR_NEUTRAL_DARK))
    d.add(DString(chart_x - 5, chart_y + chart_h - 4, f"{max_val}", fontName="Helvetica", fontSize=6, textAnchor="end", fillColor=COLOR_NEUTRAL_DARK))
    
    return d


def create_daily_frp_trend_chart(hotspots: list[dict], width=370, height=100) -> Drawing:
    """
    Renders a vertical column/bar chart showing daily FRP values.
    """
    d = Drawing(width, height)
    
    # Outer frame
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f8fafc"), strokeColor=COLOR_BORDER, strokeWidth=1, rx=4, ry=4))
    
    # Header
    d.add(DString(10, height - 12, "FIRE RADIATIVE POWER HARIAN (FRP - MW)", fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_PRIMARY))
    
    # Sum FRP per day (YYYY-MM-DD)
    daily_frp = Counter()
    for h in hotspots:
        date_str = _get_wib_date_str(str(h.get("detected_at", "")))
        if date_str:
            daily_frp[date_str] += float(h.get("frp") or 0.0)
            
    if not daily_frp:
        d.add(DString(width/2, height/2, "Tidak ada data", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=COLOR_NEUTRAL_DARK))
        return d
        
    sorted_days = sorted(daily_frp.keys())
    frp_list = [daily_frp[day] for day in sorted_days]
    
    if len(sorted_days) < 5:
        max_val = max(frp_list) if frp_list else 1.0
        
        left_margin = 12
        y_start = height - 28
        row_gap = (height - 38) / max(1, len(sorted_days))
        bar_height = 8
        max_bar_width = width - left_margin - 85
        
        months_id = {
            "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "Mei", "06": "Jun",
            "07": "Jul", "08": "Ags", "09": "Sep", "10": "Okt", "11": "Nov", "12": "Des"
        }
        
        for idx, day in enumerate(sorted_days):
            val = daily_frp[day]
            current_y = y_start - idx * row_gap
            
            parts = day.split("-")
            date_label = f"{parts[2]} {months_id.get(parts[1], parts[1])}" if len(parts) == 3 else day
            
            d.add(DString(left_margin, current_y + 1, date_label, fontName="Helvetica-Bold", fontSize=7.5, fillColor=COLOR_NEUTRAL_DARK))
            
            bar_w = max(4, int((val / max_val) * max_bar_width)) if val > 0 else 0
            if bar_w > 0:
                d.add(Rect(60, current_y, bar_w, bar_height, fillColor=colors.HexColor("#f59e0b"), strokeColor=None, rx=1.5, ry=1.5))
                
            d.add(DString(60 + bar_w + 6, current_y + 1, f"{val:.1f} MW", fontName="Helvetica-Bold", fontSize=7.5, fillColor=COLOR_NEUTRAL_DARK))
            
        return d

    if len(sorted_days) > 15:
        sorted_days = sorted_days[-15:]
        frp_list = [daily_frp[day] for day in sorted_days]

    max_val = max(frp_list) if frp_list else 1.0
    if max_val < 1.0:
        max_val = 1.0
        
    # Dimensions for chart area
    chart_x = 35
    chart_y = 20
    chart_w = width - 50
    chart_h = height - 40
    
    # Y Axis Grid lines
    d.add(Line(chart_x, chart_y, chart_x + chart_w, chart_y, strokeColor=COLOR_BORDER, strokeWidth=0.5))
    d.add(Line(chart_x, chart_y + chart_h, chart_x + chart_w, chart_y + chart_h, strokeColor=COLOR_BORDER, strokeWidth=0.5))
    
    # Draw bars/columns
    num_days = len(sorted_days)
    col_w = max(4, int(chart_w / (num_days or 1)) - 4)
    col_gap = int((chart_w - (num_days * (col_w + 2))) / 2) if num_days > 0 else 0
    
    for idx, day in enumerate(sorted_days):
        val = daily_frp[day]
        col_h = max(2, int((val / max_val) * chart_h))
        
        # Calculate coordinate
        col_x = chart_x + col_gap + idx * (col_w + 2)
        
        # Draw bar (orange/amber FRP color)
        d.add(Rect(col_x, chart_y, col_w, col_h, fillColor=colors.HexColor("#f59e0b"), strokeColor=None, rx=1, ry=1))
        
        # Draw small date label on the bottom
        if num_days <= 7 or idx == 0 or idx == num_days - 1 or idx % 3 == 0:
            short_date = day[5:]
            d.add(DString(col_x + col_w/2, chart_y - 10, short_date, fontName="Helvetica", fontSize=6, textAnchor="middle", fillColor=COLOR_NEUTRAL_DARK))
            
    # Y-axis labels
    d.add(DString(chart_x - 5, chart_y, "0", fontName="Helvetica", fontSize=6, textAnchor="end", fillColor=COLOR_NEUTRAL_DARK))
    d.add(DString(chart_x - 5, chart_y + chart_h - 4, f"{int(max_val)}", fontName="Helvetica", fontSize=6, textAnchor="end", fillColor=COLOR_NEUTRAL_DARK))
    
    return d


def create_detailed_hotspot_rows(hotspots: list[dict]) -> list[list[str]]:
    headers = [
        "No",
        "Wilayah Lembaga",
        "No. SK",
        "Satelit / Sumber",
        "Tanggal Deteksi",
        "Lintang (Lat)",
        "Bujur (Lon)",
        "Confidence",
        "Bright (K)",
        "FRP (MW)",
        "Kategori FRP",
    ]

    rows: list[list[str]] = [headers]

    for idx, hs in enumerate(hotspots, start=1):
        detected_at = hs.get("detected_at", "")
        try:
            from datetime import timedelta
            dt = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
            date_display = dt.astimezone(timezone(timedelta(hours=7))).strftime("%d-%m-%Y %H:%M WIB")
        except Exception:
            date_display = str(detected_at)

        # Kategori selalu ditampilkan supaya satu kolom tidak campur dua format:
        # MODIS memberi confidence berupa persentase, VIIRS berupa kode huruf.
        # Sebelumnya baris MODIS tampil "28%" sementara baris VIIRS "Sedang".
        conf_cat = _get_conf_cat(hs)
        raw_conf = hs.get("confidence")
        try:
            conf_display = f"{conf_cat} ({int(str(raw_conf))}%)"
        except (ValueError, TypeError):
            conf_display = conf_cat

        frp_raw = hs.get("frp", "N/A")
        try:
            frp_display = f"{float(frp_raw):.2f}"
        except (ValueError, TypeError):
            frp_display = str(frp_raw)

        frp_cat = _get_frp_cat(hs)

        rows.append([
            str(idx),
            str(hs.get("layer_name", "Tidak Ada")),
            sk_number(hs) or "-",
            str(hs.get("source", "N/A")),
            date_display,
            f"{float(hs.get('latitude', 0)):.5f}",
            f"{float(hs.get('longitude', 0)):.5f}",
            conf_display,
            f"{hs.get('brightness', 'N/A')}",
            frp_display,
            frp_cat,
        ])

    if not hotspots:
        rows.append(["Tidak ada titik panas terdeteksi pada periode ini", *[""] * (len(headers) - 1)])

    return rows


def _build_report_styles() -> dict[str, ParagraphStyle]:
    """Bangun seluruh ParagraphStyle yang dipakai di setiap seksi laporan agregat."""
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "ReportBody",
        parent=base["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        textColor=COLOR_NEUTRAL_DARK,
        leading=14
    )
    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=COLOR_PRIMARY,
            spaceAfter=4
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=COLOR_SECONDARY,
            spaceAfter=15
        ),
        "section_heading": ParagraphStyle(
            "SectionHeading",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=COLOR_PRIMARY,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True
        ),
        "body": body,
        "bold_body": ParagraphStyle(
            "ReportBodyBold",
            parent=body,
            fontName="Helvetica-Bold"
        ),
        "summary_box": ParagraphStyle(
            "SummaryBox",
            parent=base["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=10,
            textColor=colors.HexColor("#0f766e"),
            leading=15
        ),
        "tbl_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=COLOR_WHITE
        ),
        "tbl_body": ParagraphStyle(
            "TableBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            textColor=COLOR_NEUTRAL_DARK
        ),
    }


def _format_report_period(query: HotspotQuery) -> str:
    """Format rentang tanggal laporan dalam WIB (Asia/Jakarta), mis. "1 - 7 Agustus 2026"."""
    wib_tz = timezone(timedelta(hours=7))
    start_wib = query.start_at.astimezone(wib_tz)
    end_wib = (query.end_at - timedelta(seconds=1)).astimezone(wib_tz)

    start_str = start_wib.strftime("%d %B %Y")
    end_str = end_wib.strftime("%d %B %Y")

    return start_str if start_str == end_str else f"{start_str} - {end_str}"


def _section_header_banner(hotspots: list[dict], period_str: str, styles: dict) -> list:
    """SECTION 1: judul laporan, subjudul, dan kotak ringkasan eksekutif."""
    exec_summary_text = (
        "<b>Ringkasan Eksekutif:</b> Pemantauan titik panas (hotspot) dilakukan untuk mendukung mitigasi kebakaran "
        f"hutan dan lahan pada periode <b>{period_str}</b>. Hasil analisis spasial mendeteksi sebanyak <b>{len(hotspots)} "
        f"titik panas</b> yang tersebar di wilayah Kelompok Perhutanan Sosial (KPS). Data dihimpun secara real-time dari "
        "NASA FIRMS dan disinkronkan secara otomatis untuk mendukung respon cepat di lapangan."
    )

    summary_table = Table(
        [[Paragraph(exec_summary_text, styles["summary_box"])]],
        colWidths=[769.89]
    )
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdfa")), # Teal very light
        ('BOX', (0,0), (-1,-1), 1, COLOR_SECONDARY),
        ('PADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    return [
        Paragraph("LAPORAN EKSEKUTIF PEMANTAUAN HOTSPOT KPS", styles["title"]),
        Paragraph("Sistem Deteksi Dini Kebakaran Hutan dan Lahan — KPS Hotspot Monitoring & Analysis", styles["subtitle"]),
        summary_table,
        Spacer(1, 12),
    ]


def _section_kpi_cards(hotspots: list[dict]) -> list:
    """SECTION 2: kartu KPI ringkas (total hotspot, wilayah, satelit, status sinkronisasi)."""
    active_satellites_count = len(set(h.get("source", "N/A") for h in hotspots)) if hotspots else 0
    # Unique wilayah lembaga from actual hotspot layer_name — no duplicate counting
    total_wilayah = len(set(h.get("layer_name", "") for h in hotspots if h.get("layer_name")))

    card1 = _create_kpi_card(str(len(hotspots)), "TITIK PANAS (HOTSPOT)", COLOR_ACCENT)
    card2 = _create_kpi_card(str(total_wilayah), "WILAYAH LEMBAGA", COLOR_SECONDARY)
    card3 = _create_kpi_card(str(active_satellites_count), "SATELIT DETEKTOR", COLOR_PRIMARY)
    card4 = _create_kpi_card("AKTIF / ONLINE", "STATUS SINKRONISASI", COLOR_SECONDARY)

    kpi_table = Table([[card1, card2, card3, card4]], colWidths=[192.4, 192.4, 192.4, 192.4])
    kpi_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 0),
    ]))
    return [kpi_table, Spacer(1, 12)]


def _section_balai_ranking(hotspots: list[dict], styles: dict) -> list:
    """SECTION 2B: rekap titik panas per Balai PS (wilayah kerja pembinaan).

    Dipecah jadi dua tabel: rekap per Balai PS (wilayah kerja, belasan baris)
    lalu rincian per lembaga/KPS (lihat _section_lembaga_ranking). Sebelumnya
    keduanya tercampur dalam satu tabel berjudul "Balai Pengelola" yang isinya
    justru ratusan lembaga.
    """
    story: list = [
        Paragraph("Sebaran Hotspot per Balai Pengelola (Wilayah Kerja)", styles["section_heading"]),
        Paragraph(
            "Rekapitulasi titik panas per Balai Perhutanan Sosial selaku wilayah kerja pembinaan, "
            "diurutkan berdasarkan jumlah titik panas terbanyak.",
            styles["body"]
        ),
        Spacer(1, 6),
    ]

    ranked_balai = get_ranked_wilkers(hotspots)
    if ranked_balai:
        story.append(create_balai_ranking_table(
            hotspots, styles["tbl_header"], styles["body"], styles["bold_body"],
            ranked=ranked_balai, name_header="Balai Pengelola (Wilker BPS)",
        ))
    else:
        story.append(Paragraph("Tidak ada data titik panas untuk periode ini.", styles["body"]))

    story.append(Spacer(1, 15))
    story.append(PageBreak())
    return story


def _section_lembaga_ranking(hotspots: list[dict], styles: dict) -> list:
    """SECTION 2C: seluruh lembaga (KPS) yang wilayahnya terdampak titik panas."""
    story: list = [
        Paragraph("Sebaran Hotspot per Lembaga (KPS)", styles["section_heading"]),
        Paragraph(
            "Seluruh lembaga pemegang izin perhutanan sosial yang wilayahnya terdampak titik panas "
            "pada periode ini, diurutkan berdasarkan jumlah titik panas terbanyak.",
            styles["body"]
        ),
        Spacer(1, 6),
    ]

    ranked_lembaga = get_ranked_lembaga(hotspots)
    if ranked_lembaga:
        story.append(create_balai_ranking_table(
            hotspots, styles["tbl_header"], styles["body"], styles["bold_body"],
            ranked=ranked_lembaga, name_header="Lembaga (KPS)",
        ))
    else:
        story.append(Paragraph("Tidak ada data titik panas untuk periode ini.", styles["body"]))

    story.append(Spacer(1, 15))
    story.append(PageBreak())
    return story


# Tabel silang skema x provinsi harus muat di lebar cetak A4 lanskap (769pt).
# Kalau sumber data suatu saat memuat lebih banyak skema, kolom sisanya
# digabung jadi "Lainnya" alih-alih membuat tabel melewati batas kertas.
SKEMA_TABLE_MAX_COLUMNS = 8

# Dibatasi supaya tabel luas terbakar tetap muat rapi di laporan ringkas;
# kalau terpotong, pembaca diarahkan ke lampiran Excel yang memuat semuanya.
BURNED_AREA_TABLE_MAX_ROWS = 20
_SKEMA_TABLE_WIDTH = 769.0
_SKEMA_TABLE_PROVINSI_WIDTH = 150.0
_SKEMA_TABLE_TOTAL_WIDTH = 52.0


def _skema_col_widths(column_count: int) -> list[float]:
    available = _SKEMA_TABLE_WIDTH - _SKEMA_TABLE_PROVINSI_WIDTH - _SKEMA_TABLE_TOTAL_WIDTH
    per_column = min(110.0, available / max(column_count, 1))
    provinsi_width = _SKEMA_TABLE_WIDTH - _SKEMA_TABLE_TOTAL_WIDTH - per_column * column_count
    return [provinsi_width, *[per_column] * column_count, _SKEMA_TABLE_TOTAL_WIDTH]


def _skema_narrative(hotspots: list[dict]) -> str:
    per_skema = count_per_skema(hotspots)
    if not per_skema:
        return "Tidak ada titik panas terdeteksi pada periode ini."

    total = sum(count for _, count in per_skema)
    dominant, dominant_count = per_skema[0]
    share = int(round(dominant_count / total * 100)) if total else 0
    ringkasan = ", ".join(f"{label} ({count} titik)" for label, count in per_skema[:3])

    return (
        f"Titik panas periode ini tersebar pada <b>{len(per_skema)} skema</b> perhutanan sosial, "
        f"dengan konsentrasi terbesar pada skema <b>{dominant}</b> sebanyak {dominant_count} titik "
        f"({share}% dari total). Tiga skema teratas: {ringkasan}."
    )


def _section_skema_provinsi(hotspots: list[dict], styles: dict) -> list:
    """SECTION 2D: tabel silang jumlah titik panas per skema PS untuk tiap provinsi."""
    story: list = [
        Paragraph("Sebaran Hotspot per Skema Perhutanan Sosial per Provinsi", styles["section_heading"]),
        Paragraph(_skema_narrative(hotspots), styles["body"]),
        Spacer(1, 8),
    ]

    matrix = collapse_skema_columns(
        build_skema_provinsi_matrix(hotspots), SKEMA_TABLE_MAX_COLUMNS
    )
    if not matrix.skema:
        story.append(Paragraph("Tidak ada data titik panas untuk periode ini.", styles["body"]))
        story.append(Spacer(1, 15))
        story.append(PageBreak())
        return story

    header_style = styles["tbl_header"]
    bold_body_style = styles["bold_body"]
    # Angka dirata-tengah lewat ParagraphStyle: perintah ALIGN pada TableStyle
    # hanya mengatur posisi Paragraph-nya, bukan teks di dalamnya, sehingga
    # kolom angka tetap rata kiri kalau hanya mengandalkan TableStyle.
    number_style = ParagraphStyle("SkemaNumber", parent=styles["body"], alignment=1)
    number_bold_style = ParagraphStyle("SkemaNumberBold", parent=bold_body_style, alignment=1)
    header_center_style = ParagraphStyle("SkemaHeaderCenter", parent=header_style, alignment=1)

    table_rows = [
        [
            Paragraph("Provinsi", header_style),
            *[Paragraph(label, header_center_style) for label in matrix.skema],
            Paragraph("Total", header_center_style),
        ]
    ]
    for row in matrix.rows:
        table_rows.append([
            Paragraph(row.provinsi, bold_body_style),
            *[Paragraph(str(count) if count else "-", number_style) for count in row.counts],
            Paragraph(str(row.total), number_bold_style),
        ])
    table_rows.append([
        Paragraph("Total", bold_body_style),
        *[Paragraph(str(total), number_bold_style) for total in matrix.totals],
        Paragraph(str(matrix.grand_total), number_bold_style),
    ])

    table = Table(
        table_rows,
        colWidths=_skema_col_widths(len(matrix.skema)),
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_SECONDARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_WHITE),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [COLOR_WHITE, COLOR_NEUTRAL_LIGHT]),
        ('PADDING', (0, 0), (-1, -1), 4),
        # Baris total dibedakan supaya tidak terbaca sebagai provinsi terakhir.
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#e0f2fe")),
        ('LINEABOVE', (0, -1), (-1, -1), 1, COLOR_PRIMARY),
    ]))

    story.append(table)
    story.append(Spacer(1, 15))
    story.append(PageBreak())
    return story


_BURNED_AREA_SKEMA_COLORS = {
    "PPHD": "#dc2626",
    "PPHKm": "#f97316",
    "PPHTR": "#f59e0b",
    "PPHA": "#eab308",
    "PPKKPS": "#fb7185",
}
_BURNED_AREA_FALLBACK_COLOR = "#dc2626"


def create_burned_area_bar_chart(
    data_points: list[tuple[str, float]], title: str, width: int = 370, height: int = 150
) -> Drawing:
    """Chart batang luas terbakar per skema.

    Beda dari create_bar_chart_drawing() (dipakai untuk confidence/FRP): itu
    hardcode 3 baris karena dua-duanya SELALU tepat 3 kategori
    (Tinggi/Sedang/Rendah). Jumlah skema perhutanan sosial bervariasi
    (1 sampai 5+), jadi tinggi barisnya di sini dihitung dari jumlah data
    yang sebenarnya, bukan diasumsikan tetap.
    """
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=colors.HexColor("#f8fafc"), strokeColor=COLOR_BORDER, strokeWidth=1, rx=4, ry=4))
    d.add(DString(10, height - 15, title, fontName="Helvetica-Bold", fontSize=7, fillColor=COLOR_ACCENT))

    if not data_points:
        d.add(DString(width / 2, height / 2, "Tidak ada data", fontName="Helvetica", fontSize=8, textAnchor="middle", fillColor=COLOR_NEUTRAL_DARK))
        return d

    total = sum(v for _, v in data_points)
    max_val = max(v for _, v in data_points) or 1
    bar_max_width = width - 150
    available_height = height - 40
    row_count = len(data_points)
    row_height = available_height / row_count
    bar_height = min(14, row_height * 0.6)
    font_size = 8
    start_y = height - 40

    for idx, (label, val) in enumerate(data_points):
        current_y = start_y - (idx + 1) * row_height
        pct = int(round((val / total) * 100)) if total else 0
        color_hex = _BURNED_AREA_SKEMA_COLORS.get(label, _BURNED_AREA_FALLBACK_COLOR)
        d.add(DString(15, current_y + bar_height * 0.15, label, fontName="Helvetica-Bold", fontSize=font_size, fillColor=COLOR_NEUTRAL_DARK))

        bar_w = max(5, int((val / max_val) * bar_max_width)) if val > 0 else 0
        if bar_w > 0:
            d.add(Rect(60, current_y, bar_w, bar_height, fillColor=colors.HexColor(color_hex), strokeColor=None, rx=2, ry=2))
        d.add(DString(
            60 + bar_w + 8, current_y + bar_height * 0.15,
            f"{val:,.1f} Ha ({pct}%)", fontName="Helvetica-Bold", fontSize=font_size, fillColor=COLOR_NEUTRAL_DARK
        ))

    return d


def _section_burned_area(burned_area_report: dict | None, styles: dict) -> list:
    """SECTION 2E: rekap luas bekas terbakar (citra MODIS/VIIRS bulanan).

    Ditempatkan setelah rekap hotspot dan diberi peringatan eksplisit karena
    satuannya beda (hektar vs jumlah titik) dan kesegarannya beda jauh
    (bulanan dengan jeda rilis 1-3 bulan vs sinkron tiap 3 jam) -- tanpa itu
    pembaca mudah menjumlahkan dua angka yang tidak sebanding.

    Kalau tidak ada data (fitur belum dikonfigurasi, atau tidak ada kawasan
    terbakar pada filter laporan), seksi ini dilewati sama sekali supaya
    laporan tidak berisi halaman kosong.
    """
    if not burned_area_report or not burned_area_report.get("rows"):
        return []

    rows = burned_area_report["rows"]
    total_ha = float(burned_area_report.get("total_ha") or 0)
    kps_count = int(burned_area_report.get("kps_count") or 0)
    by_skema = burned_area_report.get("by_skema") or []

    skema_phrase = ", ".join(
        f"{item['skema']} {item['total_ha']:,.1f} Ha ({item['kps_count']} KPS)" for item in by_skema
    )
    narrative = (
        f"Analisis citra satelit mendeteksi <b>{total_ha:,.1f} hektar</b> area bekas terbakar "
        f"pada <b>{kps_count} kawasan perhutanan sosial</b>. Rincian per skema: {skema_phrase}. "
        "Angka ini berasal dari produk burned area MODIS MCD64A1 / VIIRS VNP64A1 (resolusi 500 m, "
        "terbit bulanan dengan jeda rilis 1-3 bulan) dan dihitung sekali per kawasan meskipun "
        "terbakar berulang, sehingga <b>tidak dapat dijumlahkan langsung dengan jumlah titik "
        "panas</b> pada bagian sebelumnya."
    )

    story: list = [
        Paragraph("Luas Bekas Terbakar pada Kawasan Perhutanan Sosial", styles["section_heading"]),
        Paragraph(narrative, styles["body"]),
        Spacer(1, 8),
    ]

    if by_skema:
        chart_points = [(item["skema"], float(item["total_ha"])) for item in by_skema]
        story.append(create_burned_area_bar_chart(
            chart_points, "LUAS TERBAKAR PER SKEMA (HA)", width=370, height=110
        ))
        story.append(Spacer(1, 10))

    header_style = styles["tbl_header"]
    bold_body_style = styles["bold_body"]
    number_style = ParagraphStyle("BurnNumber", parent=styles["body"], alignment=1)
    number_bold_style = ParagraphStyle("BurnNumberBold", parent=bold_body_style, alignment=1)
    header_center_style = ParagraphStyle("BurnHeaderCenter", parent=header_style, alignment=1)

    table_rows = [[
        Paragraph("No", header_center_style),
        Paragraph("Nama Kawasan / KPS", header_style),
        Paragraph("Skema", header_center_style),
        Paragraph("Provinsi", header_style),
        Paragraph("Luas Terbakar (Ha)", header_center_style),
        Paragraph("Bulan", header_center_style),
        Paragraph("Periode Terakhir", header_center_style),
        Paragraph("Keterangan", header_center_style),
    ]]

    ranked = sorted(rows, key=lambda item: item["burned_area_ha"], reverse=True)
    for index, item in enumerate(ranked[:BURNED_AREA_TABLE_MAX_ROWS], start=1):
        table_rows.append([
            Paragraph(str(index), number_style),
            Paragraph(str(item["lembaga"]), bold_body_style),
            Paragraph(str(item["skema"]), number_style),
            Paragraph(str(item["nama_prov"]), styles["body"]),
            Paragraph(f"{item['burned_area_ha']:,.1f}", number_bold_style),
            Paragraph(str(item["burned_months"]), number_style),
            Paragraph(str(item["latest_period"]), number_style),
            Paragraph(
                "Perkiraan lokasi" if item["is_estimated"] else "Terpetakan",
                number_style,
            ),
        ])

    table_rows.append([
        Paragraph("", number_style),
        Paragraph("TOTAL", bold_body_style),
        Paragraph("", number_style),
        Paragraph("", number_style),
        Paragraph(f"{total_ha:,.1f}", number_bold_style),
        Paragraph("", number_style),
        Paragraph("", number_style),
        Paragraph("", number_style),
    ])

    table = Table(
        table_rows,
        colWidths=[28, 205, 55, 105, 80, 42, 78, 82],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        # Merah, bukan teal seperti tabel hotspot -- penanda visual bahwa ini
        # metrik yang berbeda, sejalan dengan warna lapisan peta dan Excel.
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_ACCENT),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_WHITE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [COLOR_WHITE, COLOR_NEUTRAL_LIGHT]),
        ('PADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#fee2e2")),
        ('LINEABOVE', (0, -1), (-1, -1), 1, COLOR_ACCENT),
    ]))
    story.append(table)

    if len(ranked) > BURNED_AREA_TABLE_MAX_ROWS:
        story.append(Spacer(1, 5))
        story.append(Paragraph(
            f"Menampilkan {BURNED_AREA_TABLE_MAX_ROWS} kawasan dengan luas terbakar terbesar "
            f"dari total {len(ranked)} kawasan terdampak. Rincian lengkap tersedia pada "
            "lampiran Excel (sheet \"Luas Terbakar\").",
            styles["body"],
        ))

    story.append(Spacer(1, 15))
    story.append(PageBreak())
    return story


def _section_visualization(hotspots: list[dict], layers_info: list[dict], styles: dict) -> list:
    """SECTION 3: peta sebaran spasial, pie chart satelit, dan kotak ringkasan spasial."""
    provinces = set()
    balais = set()
    wilker_counts = Counter()
    for h in hotspots:
        prov = h.get("province_name") or h.get("nama_prov") or h.get("polygon_metadata", {}).get("NAMA_PROV")
        if prov:
            provinces.add(prov)

        balai = h.get("polygon_metadata", {}).get("WILKER_BPS")
        if balai:
            balais.add(balai)

        wilker = h.get("layer_name") or h.get("polygon_metadata", {}).get("LEMBAGA")
        if wilker:
            wilker_counts[wilker] += 1

    count_prov = len(provinces)
    count_balai = len(balais)

    if wilker_counts:
        top_wilker, top_count = wilker_counts.most_common(1)[0]
        if len(top_wilker) > 28:
            top_wilker_display = top_wilker[:25] + "..."
        else:
            top_wilker_display = top_wilker
        top_wilker_str = f"{top_wilker_display} ({top_count})"
    else:
        top_wilker_str = "-"

    body_style = styles["body"]
    summary_data = [
        [Paragraph("<b>RINGKASAN SPASIAL</b>", ParagraphStyle("SpHeader", parent=body_style, fontName="Helvetica-Bold", fontSize=8, textColor=COLOR_PRIMARY, spaceAfter=4))],
        [Paragraph(f"Provinsi Terdampak: <b>{count_prov}</b>", body_style)],
        [Paragraph(f"Balai Terdampak: <b>{count_balai}</b>", body_style)],
        [Paragraph(f"Lembaga Terbanyak:<br/><b>{top_wilker_str}</b>", body_style)]
    ]
    summary_box = Table(summary_data, colWidths=[210])
    summary_box.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f8fafc")),
        ('BOX', (0,0), (-1,-1), 1, COLOR_BORDER),
        ('PADDING', (0,0), (-1,-1), 8),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    map_drawing = create_spatial_map_drawing(hotspots, layers_info, width=540, height=275)
    pie_drawing = create_pie_chart(hotspots, width=224, height=135)

    right_col_table = Table([[pie_drawing], [Spacer(1, 10)], [summary_box]], colWidths=[224])
    right_col_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 0),
    ]))

    vis_table = Table([[map_drawing, right_col_table]], colWidths=[540, 230])
    vis_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('PADDING', (0,0), (-1,-1), 0),
    ]))

    return [
        Paragraph("Sebaran Spasial & Proporsi Satelit Detektor", styles["section_heading"]),
        Paragraph("Peta sebaran spasial titik panas berdasarkan batas wilayah lembaga pengelola kawasan hutan dan proporsi deteksi masing-masing satelit.", body_style),
        Spacer(1, 10),
        vis_table,
        PageBreak(),
    ]


def _section_trend(hotspots: list[dict], styles: dict) -> list:
    """SECTION 3B: grafik tren harian volume kejadian dan FRP."""
    volume_chart = create_daily_volume_trend_chart(hotspots, width=769, height=110)
    frp_chart = create_daily_frp_trend_chart(hotspots, width=769, height=110)
    return [
        Paragraph("Analisis Tren Harian Titik Panas", styles["section_heading"]),
        Paragraph(
            "Visualisasi tren harian volume kejadian dan Fire Radiative Power (FRP) dalam periode yang dipilih.",
            styles["body"]
        ),
        Spacer(1, 10),
        volume_chart,
        Spacer(1, 10),
        frp_chart,
        PageBreak(),
    ]


def _section_confidence_frp(hotspots: list[dict], styles: dict) -> list:
    """SECTION 4: distribusi confidence & FRP -- narasi, grafik batang, dan tabel per kategori."""
    body_style = styles["body"]
    bold_body_style = styles["bold_body"]

    conf_counts = {"Tinggi": 0, "Sedang": 0, "Rendah": 0}
    frp_counts = {"Tinggi": 0, "Sedang": 0, "Rendah": 0}

    for h in hotspots:
        conf_counts[_get_conf_cat(h)] += 1
        frp_counts[_get_frp_cat(h)] += 1

    total_hs = len(hotspots)

    dom_conf = max(conf_counts.items(), key=lambda x: x[1]) if total_hs else ("Rendah", 0)
    dom_frp = max(frp_counts.items(), key=lambda x: x[1]) if total_hs else ("Rendah", 0)

    pct_conf = int(round((dom_conf[1] / total_hs) * 100)) if total_hs else 0
    pct_frp = int(round((dom_frp[1] / total_hs) * 100)) if total_hs else 0

    narrative_text = f"Berdasarkan distribusi confidence, mayoritas hotspot berada pada kategori {dom_conf[0]} sebanyak {dom_conf[1]} titik ({pct_conf}%). "
    narrative_text += f"Berdasarkan distribusi FRP, mayoritas hotspot berada pada kategori {dom_frp[0]} sebanyak {dom_frp[1]} titik ({pct_frp}%), menunjukkan bahwa sebagian besar hotspot memiliki tingkat intensitas panas "
    narrative_text += "tinggi." if dom_frp[0] == "Tinggi" else "menengah." if dom_frp[0] == "Sedang" else "rendah."

    # Confidence Chart & Table
    conf_data = [
        ("Tinggi", conf_counts["Tinggi"], "#ef4444"),
        ("Sedang", conf_counts["Sedang"], "#f59e0b"),
        ("Rendah", conf_counts["Rendah"], "#3b82f6")
    ]
    conf_chart = create_bar_chart_drawing(conf_data, "DISTRIBUSI CONFIDENCE", width=370, height=130)

    conf_table_data = [
        [Paragraph("Confidence", bold_body_style), Paragraph("Jumlah", bold_body_style), Paragraph("Persentase", bold_body_style)],
        [Paragraph("Tinggi", body_style), Paragraph(str(conf_counts["Tinggi"]), body_style), Paragraph(f"{int(round((conf_counts['Tinggi']/total_hs)*100))}%" if total_hs else "0%", body_style)],
        [Paragraph("Sedang", body_style), Paragraph(str(conf_counts["Sedang"]), body_style), Paragraph(f"{int(round((conf_counts['Sedang']/total_hs)*100))}%" if total_hs else "0%", body_style)],
        [Paragraph("Rendah", body_style), Paragraph(str(conf_counts["Rendah"]), body_style), Paragraph(f"{int(round((conf_counts['Rendah']/total_hs)*100))}%" if total_hs else "0%", body_style)],
        [Paragraph("Total", bold_body_style), Paragraph(str(total_hs), bold_body_style), Paragraph("100%", bold_body_style)]
    ]
    conf_table = Table(conf_table_data, colWidths=[120, 100, 100])
    conf_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), COLOR_NEUTRAL_LIGHT),
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6)
    ]))

    # FRP Chart & Table
    frp_data = [
        ("Tinggi", frp_counts["Tinggi"], "#ef4444"),
        ("Sedang", frp_counts["Sedang"], "#f97316"),
        ("Rendah", frp_counts["Rendah"], "#22c55e")
    ]
    frp_chart = create_bar_chart_drawing(frp_data, "DISTRIBUSI INTENSITAS FRP", width=370, height=130)

    frp_table_data = [
        [Paragraph("Kategori FRP", bold_body_style), Paragraph("Jumlah", bold_body_style), Paragraph("Persentase", bold_body_style)],
        [Paragraph("Tinggi", body_style), Paragraph(str(frp_counts["Tinggi"]), body_style), Paragraph(f"{int(round((frp_counts['Tinggi']/total_hs)*100))}%" if total_hs else "0%", body_style)],
        [Paragraph("Sedang", body_style), Paragraph(str(frp_counts["Sedang"]), body_style), Paragraph(f"{int(round((frp_counts['Sedang']/total_hs)*100))}%" if total_hs else "0%", body_style)],
        [Paragraph("Rendah", body_style), Paragraph(str(frp_counts["Rendah"]), body_style), Paragraph(f"{int(round((frp_counts['Rendah']/total_hs)*100))}%" if total_hs else "0%", body_style)],
        [Paragraph("Total", bold_body_style), Paragraph(str(total_hs), bold_body_style), Paragraph("100%", bold_body_style)]
    ]
    frp_table = Table(frp_table_data, colWidths=[120, 100, 100])
    frp_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), COLOR_NEUTRAL_LIGHT),
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 6)
    ]))

    return [
        Paragraph("ANALISIS HOTSPOT BERDASARKAN CONFIDENCE DAN FRP", styles["section_heading"]),
        Paragraph(narrative_text, body_style),
        Spacer(1, 15),
        Table([[conf_chart, conf_table]], colWidths=[385, 384]),
        Spacer(1, 15),
        Table([[frp_chart, frp_table]], colWidths=[385, 384]),
        PageBreak(),
    ]


def _section_detailed_table(hotspots: list[dict], styles: dict) -> list:
    """SECTION 5: tabel rinci seluruh observasi hotspot, baris diwarnai per kategori FRP."""
    detailed_rows = create_detailed_hotspot_rows(hotspots)
    hotspot_rows = [
        [Paragraph(cell, styles["tbl_header"]) for cell in detailed_rows[0]]
    ]
    hotspot_rows.extend(
        [
            Paragraph(cell, styles["tbl_body"]) for cell in row
        ]
        for row in detailed_rows[1:]
    )

    table_styles = [
        ('BACKGROUND', (0,0), (-1,0), COLOR_SECONDARY),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ('PADDING', (0,0), (-1,-1), 4),
    ]
    for i, h in enumerate(hotspots):
        row_idx = i + 1
        cat = _get_frp_cat(h)
        if cat == "Tinggi":
            bg_color = colors.HexColor("#fef2f2")
        elif cat == "Sedang":
            bg_color = colors.HexColor("#fff7ed")
        else:
            bg_color = colors.HexColor("#f0fdf4")
        table_styles.append(('BACKGROUND', (0, row_idx), (-1, row_idx), bg_color))

    hotspots_table = Table(hotspot_rows, colWidths=HOTSPOT_TABLE_COL_WIDTHS, repeatRows=1)
    hotspots_table.setStyle(TableStyle(table_styles))

    return [
        Paragraph("Daftar Detail Observasi Titik Panas (Hotspot)", styles["section_heading"]),
        hotspots_table,
        Spacer(1, 10),
    ]


def _section_signoff(styles: dict) -> list:
    """Blok tanda tangan penyiap/penyetuju di penutup laporan."""
    body_style = styles["body"]
    bold_body_style = styles["bold_body"]
    sig_data = [
        [Paragraph("Disiapkan Oleh:", bold_body_style), Paragraph("Disetujui Oleh:", bold_body_style)],
        [Spacer(1, 20), Spacer(1, 20)],
        [Paragraph("_____________________________", body_style),
         Paragraph("_____________________________", body_style)],
        # Baris nama/NIP: sebelumnya hanya ada garis kosong tanpa penanda,
        # sehingga tidak jelas apa yang harus diisi saat dokumen dicetak.
        [Paragraph("Nama &amp; NIP", body_style), Paragraph("Nama &amp; NIP", body_style)],
    ]
    sig_table = Table(sig_data, colWidths=[385, 384])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('PADDING', (0,0), (-1,-1), 0),
    ]))
    return [KeepTogether([Spacer(1, 10), sig_table])]


def build_pdf_report(
    hotspots: list[dict],
    query: HotspotQuery,
    layers_info: list[dict],
    burned_area_report: dict | None = None,
) -> bytes:
    """
    Generates a beautifully designed landscape A4 PDF report.

    Laporan per-lembaga memakai jalur terpisah (lihat
    agency_pdf_service.build_agency_pdf_weasyprint) -- fungsi ini hanya
    untuk laporan agregat semua lembaga. Tiap seksi laporan (lihat komentar
    "SECTION N" yang sudah ada sejak awal di kode ini) dibangun oleh fungsi
    _section_* terpisah supaya masing-masing bisa dibaca dan diuji sendiri,
    alih-alih satu fungsi ~450 baris.
    """
    buffer = BytesIO()

    # margins 36pt (0.5 inch) left/right, 54pt top/bottom
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=36,
        rightMargin=36,
        topMargin=54,
        bottomMargin=54
    )

    styles = _build_report_styles()
    period_str = _format_report_period(query)

    story: list = []
    story.extend(_section_header_banner(hotspots, period_str, styles))
    story.extend(_section_kpi_cards(hotspots))
    story.extend(_section_balai_ranking(hotspots, styles))
    story.extend(_section_lembaga_ranking(hotspots, styles))
    story.extend(_section_skema_provinsi(hotspots, styles))
    story.extend(_section_burned_area(burned_area_report, styles))
    story.extend(_section_visualization(hotspots, layers_info, styles))
    story.extend(_section_trend(hotspots, styles))
    story.extend(_section_confidence_frp(hotspots, styles))
    story.extend(_section_detailed_table(hotspots, styles))
    story.extend(_section_signoff(styles))

    # Build the document
    # Inject metadata to canvas
    class ConfiguredNumberedCanvas(NumberedCanvas):
        pass

    ConfiguredNumberedCanvas.period_str = period_str
    ConfiguredNumberedCanvas.download_date = datetime.now(timezone(timedelta(hours=7))).strftime("%d-%m-%Y %H:%M:%S")

    doc.build(story, canvasmaker=ConfiguredNumberedCanvas)

    return buffer.getvalue()

