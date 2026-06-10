import logging
import math
import os
from datetime import datetime, timezone
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
from reportlab.graphics.shapes import Drawing, Rect, Circle, Line, String as DString, Group, Image as DImage
from reportlab.graphics.charts.piecharts import Pie

from app.models.query import HotspotQuery

logger = logging.getLogger("hotspot.pdf_export")

# Colors matching the application's visual system
COLOR_PRIMARY = colors.HexColor("#1e3a8a")     # Deep blue
COLOR_SECONDARY = colors.HexColor("#0f766e")   # Teal
COLOR_ACCENT = colors.HexColor("#dc2626")      # Red / Alert
COLOR_NEUTRAL_DARK = colors.HexColor("#1f2937")# Charcoal text
COLOR_NEUTRAL_LIGHT = colors.HexColor("#f3f4f6")# Light grey
COLOR_BORDER = colors.HexColor("#e5e7eb")       # Border grey
COLOR_WHITE = colors.HexColor("#ffffff")

HOTSPOT_TABLE_COL_WIDTHS = [30, 180, 80, 115, 65, 65, 40, 55, 55, 84]


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
    from reportlab.platypus import Image as RLImage

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
    counts = Counter()
    for hotspot in hotspots:
        wilker = hotspot.get("layer_name") or hotspot.get("polygon_metadata", {}).get("WILKER_BPS") or "Belum Ditugaskan"
        counts[wilker] += 1
    return counts.most_common()



def _get_conf_cat(hotspot: dict) -> str:
    conf = str(hotspot.get("confidence", "")).strip().lower()
    if conf in ["h", "high"]: return "Tinggi"
    if conf in ["n", "nominal", "medium"]: return "Sedang"
    if conf in ["l", "low"]: return "Rendah"
    try:
        val = int(conf)
        if val > 80: return "Tinggi"
        if val >= 30: return "Sedang"
        return "Rendah"
    except ValueError:
        return "Rendah"

def _get_frp_cat(hotspot: dict) -> str:
    try:
        val = float(hotspot.get("frp") or 0)
        if val > 30: return "Tinggi"
        if val >= 10: return "Sedang"
        return "Rendah"
    except ValueError:
        return "Rendah"

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
) -> "Table":
    """
    Builds a full ReportLab Table of ALL affected balai sorted by hotspot count.
    Grows vertically to fit all rows — no limit.
    """
    ranked = get_ranked_wilkers(hotspots)

    header = [
        Paragraph("#", tbl_header_style),
        Paragraph("Balai Pengelola", tbl_header_style),
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

    tbl = Table(rows, colWidths=[30, None, 65, 45])
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
        "Satelit / Sumber",
        "Tanggal Deteksi",
        "Lintang (Lat)",
        "Bujur (Lon)",
        "Conf",
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

        conf_cat = _get_conf_cat(hs)
        raw_conf = hs.get("confidence")
        try:
            val = int(str(raw_conf))
            conf_display = f"{val}%"
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
        rows.append(["Tidak ada titik panas terdeteksi pada periode ini", "", "", "", "", "", "", "", "", ""])

    return rows


def build_pdf_report(hotspots: list[dict], query: HotspotQuery, layers_info: list[dict], agency_name: str | None = None) -> bytes:
    """
    Generates a beautifully designed landscape A4 PDF report.
    """
    if agency_name:
        return build_agency_pdf_report(hotspots, query, layers_info, agency_name)

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

    # Styles
    styles = getSampleStyleSheet()
    
    # Custom styles to fit the design system
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=COLOR_PRIMARY,
        spaceAfter=4
    )
    
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=13,
        textColor=COLOR_SECONDARY,
        spaceAfter=15
    )

    section_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=COLOR_PRIMARY,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        textColor=COLOR_NEUTRAL_DARK,
        leading=14
    )

    bold_body_style = ParagraphStyle(
        "ReportBodyBold",
        parent=body_style,
        fontName="Helvetica-Bold"
    )

    summary_box_style = ParagraphStyle(
        "SummaryBox",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=10,
        textColor=colors.HexColor("#0f766e"),
        leading=15
    )

    kpi_num_style = ParagraphStyle(
        "KpiNumber",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=20,
        textColor=COLOR_ACCENT,
        alignment=1 # Centered
    )

    kpi_label_style = ParagraphStyle(
        "KpiLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=COLOR_NEUTRAL_DARK,
        alignment=1 # Centered
    )

    tbl_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=COLOR_WHITE
    )

    tbl_body_style = ParagraphStyle(
        "TableBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        textColor=COLOR_NEUTRAL_DARK
    )

    story = []

    # Format period in WIB (Asia/Jakarta) timezone
    from datetime import timezone, timedelta
    wib_tz = timezone(timedelta(hours=7))
    start_wib = query.start_at.astimezone(wib_tz)
    end_wib = (query.end_at - timedelta(seconds=1)).astimezone(wib_tz)
    
    start_str = start_wib.strftime("%d %B %Y")
    end_str = end_wib.strftime("%d %B %Y")
    
    if start_str == end_str:
        period_str = start_str
    else:
        period_str = f"{start_str} - {end_str}"
    
    # ------------------ SECTION 1: HEADER BANNER & INFO ------------------
    story.append(Paragraph("LAPORAN EKSEKUTIF PEMANTAUAN HOTSPOT KPS", title_style))
    story.append(Paragraph("Sistem Deteksi Dini Kebakaran Hutan dan Lahan — KPS Hotspot Monitoring & Analysis", subtitle_style))
    
    # Executive Summary Paragraph
    exec_summary_text = (
        "<b>Ringkasan Eksekutif:</b> Pemantauan titik panas (hotspot) dilakukan untuk mendukung mitigasi kebakaran "
        f"hutan dan lahan pada periode <b>{period_str}</b>. Hasil analisis spasial mendeteksi sebanyak <b>{len(hotspots)} "
        f"titik panas</b> yang tersebar di wilayah konsesi Perhutanan Sosial. Data dihimpun secara real-time dari "
        "NASA FIRMS dan disinkronkan secara otomatis untuk mendukung respon cepat di lapangan."
    )
    
    # Styling Executive Summary as a callout box
    summary_table = Table(
        [[Paragraph(exec_summary_text, summary_box_style)]],
        colWidths=[769.89]
    )
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdfa")), # Teal very light
        ('BOX', (0,0), (-1,-1), 1, COLOR_SECONDARY),
        ('PADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 12))


    # ------------------ SECTION 2: KPI CARDS ------------------
    # Generate statistics
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
    story.append(kpi_table)
    story.append(Spacer(1, 12))

    # ------------------ SECTION 2B: SELURUH LEMBAGA TERDAMPAK ------------------
    story.append(Paragraph("Sebaran Hotspot per Balai Pengelola", section_heading))
    story.append(Paragraph(
        "Seluruh balai pengelola kawasan yang terdampak titik panas dalam periode ini, "
        "diurutkan berdasarkan jumlah titik panas terbanyak.",
        body_style
    ))
    story.append(Spacer(1, 6))

    all_ranked = get_ranked_wilkers(hotspots)
    if all_ranked:
        balai_tbl = create_balai_ranking_table(hotspots, tbl_header_style, body_style, bold_body_style)
        story.append(balai_tbl)
    else:
        story.append(Paragraph("Tidak ada data titik panas untuk periode ini.", body_style))
        
    story.append(Spacer(1, 15))
    story.append(PageBreak())

    # ------------------ SECTION 3: VISUALIZATION (MAP & PIE CHART) ------------------
    story.append(Paragraph("Sebaran Spasial & Proporsi Satelit Detektor", section_heading))
    story.append(Paragraph("Peta sebaran spasial titik panas berdasarkan batas wilayah lembaga pengelola kawasan hutan dan proporsi deteksi masing-masing satelit.", body_style))
    story.append(Spacer(1, 10))

    # Generate spatial summary counts
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

    summary_data = [
        [Paragraph("<b>RINGKASAN SPASIAL</b>", ParagraphStyle("SpHeader", parent=body_style, fontName="Helvetica-Bold", fontSize=8, textColor=COLOR_PRIMARY, spaceAfter=4))],
        [Paragraph(f"Provinsi Terdampak: <b>{count_prov}</b>", body_style)],
        [Paragraph(f"Balai Terdampak: <b>{count_balai}</b>", body_style)],
        [Paragraph(f"Hotspot Terbanyak:<br/><b>{top_wilker_str}</b>", body_style)]
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
    story.append(vis_table)
    story.append(PageBreak())

    # ------------------ SECTION 3B: TREND ANALYSIS ------------------
    story.append(Paragraph("Analisis Tren Harian Titik Panas", section_heading))
    story.append(Paragraph(
        "Visualisasi tren harian volume kejadian dan Fire Radiative Power (FRP) dalam periode yang dipilih.",
        body_style
    ))
    story.append(Spacer(1, 10))

    volume_chart = create_daily_volume_trend_chart(hotspots, width=769, height=110)
    frp_chart    = create_daily_frp_trend_chart(hotspots,    width=769, height=110)
    story.append(volume_chart)
    story.append(Spacer(1, 10))
    story.append(frp_chart)
    
    story.append(PageBreak())

    
    # ------------------ SECTION 4: CONFIDENCE & FRP ------------------
    story.append(Paragraph("ANALISIS HOTSPOT BERDASARKAN CONFIDENCE DAN FRP", section_heading))
    
    conf_counts = {"Tinggi": 0, "Sedang": 0, "Rendah": 0}
    frp_counts = {"Tinggi": 0, "Sedang": 0, "Rendah": 0}
    
    for h in hotspots:
        conf_counts[_get_conf_cat(h)] += 1
        frp_counts[_get_frp_cat(h)] += 1
        
    total_hs = len(hotspots)
    
    # Narratives
    dom_conf = max(conf_counts.items(), key=lambda x: x[1]) if total_hs else ("Rendah", 0)
    dom_frp = max(frp_counts.items(), key=lambda x: x[1]) if total_hs else ("Rendah", 0)
    
    pct_conf = int(round((dom_conf[1] / total_hs) * 100)) if total_hs else 0
    pct_frp = int(round((dom_frp[1] / total_hs) * 100)) if total_hs else 0
    
    narrative_text = f"Berdasarkan distribusi confidence, mayoritas hotspot berada pada kategori {dom_conf[0]} sebanyak {dom_conf[1]} titik ({pct_conf}%). "
    narrative_text += f"Berdasarkan distribusi FRP, mayoritas hotspot berada pada kategori {dom_frp[0]} sebanyak {dom_frp[1]} titik ({pct_frp}%), menunjukkan bahwa sebagian besar hotspot memiliki tingkat intensitas panas "
    narrative_text += "tinggi." if dom_frp[0] == "Tinggi" else "menengah." if dom_frp[0] == "Sedang" else "rendah."
    
    story.append(Paragraph(narrative_text, body_style))
    story.append(Spacer(1, 15))
    


    
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
    
    story.append(Table([[conf_chart, conf_table]], colWidths=[385, 384]))
    story.append(Spacer(1, 15))
    
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
    
    story.append(Table([[frp_chart, frp_table]], colWidths=[385, 384]))
    story.append(PageBreak())

# ------------------ SECTION 5: DETAILED HOTSPOT OBSERVATIONS ------------------
    story.append(Paragraph("Daftar Detail Observasi Titik Panas (Hotspot)", section_heading))
    
    detailed_rows = create_detailed_hotspot_rows(hotspots)
    hotspot_rows = [
        [Paragraph(cell, tbl_header_style) for cell in detailed_rows[0]]
    ]
    hotspot_rows.extend(
        [
            Paragraph(cell, tbl_body_style) for cell in row
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
    story.append(hotspots_table)

    story.append(Spacer(1, 10))

    # ------------------ SIGN-OFF ------------------
    sig_data = [
        [Paragraph("Disiapkan Oleh:", bold_body_style), Paragraph("Disetujui Oleh:", bold_body_style)],
        [Spacer(1, 20), Spacer(1, 20)],
        [Paragraph("_____________________________", body_style),
         Paragraph("_____________________________", body_style)]
    ]
    sig_table = Table(sig_data, colWidths=[385, 384])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('PADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(KeepTogether([Spacer(1, 10), sig_table]))

    # Build the document
    # Inject metadata to canvas
    class ConfiguredNumberedCanvas(NumberedCanvas):
        pass

    ConfiguredNumberedCanvas.period_str = period_str
    from datetime import timedelta
    ConfiguredNumberedCanvas.download_date = datetime.now(timezone(timedelta(hours=7))).strftime("%d-%m-%Y %H:%M:%S")

    doc.build(story, canvasmaker=ConfiguredNumberedCanvas)
    
    return buffer.getvalue()


def build_agency_pdf_report(hotspots: list[dict], query: HotspotQuery, layers_info: list[dict], agency_name: str) -> bytes:
    """
    Generates a beautifully designed portrait A4 PDF report specifically customized for a single Agency/Lembaga.
    """
    buffer = BytesIO()
    
    # Portrait A4 document: margins 36pt (0.5 inch) left/right, 48pt top/bottom
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=48,
        bottomMargin=48
    )

    styles = getSampleStyleSheet()
    
    # Colors matching the application's visual system
    c_primary = colors.HexColor("#0f766e")    # Teal for Agency
    c_secondary = colors.HexColor("#0284c7")  # Sky Blue
    c_accent = colors.HexColor("#ea580c")     # Orange
    c_dark = colors.HexColor("#0f172a")       # Dark Slate
    c_light = colors.HexColor("#f8fafc")      # Soft Gray
    c_border = colors.HexColor("#e2e8f0")
    c_white = colors.HexColor("#ffffff")

    title_style = ParagraphStyle(
        "AgencyReportTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=c_primary,
        spaceAfter=2
    )
    
    subtitle_style = ParagraphStyle(
        "AgencyReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=c_accent,
        spaceAfter=12
    )

    section_heading = ParagraphStyle(
        "AgencySectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=c_primary,
        spaceBefore=12,
        spaceAfter=6,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        "AgencyReportBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=c_dark,
        leading=13
    )

    bold_body_style = ParagraphStyle(
        "AgencyReportBodyBold",
        parent=body_style,
        fontName="Helvetica-Bold"
    )

    story = []

    # WIB Period
    from datetime import timezone, timedelta
    wib_tz = timezone(timedelta(hours=7))
    start_wib = query.start_at.astimezone(wib_tz)
    end_wib = (query.end_at - timedelta(seconds=1)).astimezone(wib_tz)
    start_str = start_wib.strftime("%d %B %Y")
    end_str = end_wib.strftime("%d %B %Y")
    period_str = start_str if start_str == end_str else f"{start_str} - {end_str}"

    # Header
    story.append(Paragraph("LAPORAN DETEKSI HOTSPOT SPESIFIK LEMBAGA", title_style))
    story.append(Paragraph(f"Kawasan: {agency_name.upper()}", subtitle_style))

    # Executive Summary for Agency
    exec_summary_text = (
        f"Laporan khusus pemantauan titik panas (hotspot) disusun secara terperinci untuk wilayah kerja lembaga "
        f"<b>{agency_name}</b> periode <b>{period_str}</b>. Hasil analisis spasial real-time mendeteksi sebanyak "
        f"<b>{len(hotspots)} titik panas aktif</b>. Data cuaca setempat dan bahaya kebakaran dianalisis secara presisi "
        f"untuk mendukung antisipasi dini dan pencegahan kebakaran hutan dan lahan."
    )
    
    summary_table = Table(
        [[Paragraph(exec_summary_text, body_style)]],
        colWidths=[523.27]
    )
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#f0fdfa")),
        ('BOX', (0,0), (-1,-1), 1.5, c_primary),
        ('PADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    # Calculate coordinate centroid for weather
    lats = [h.get("latitude") for h in hotspots if h.get("latitude") is not None]
    lons = [h.get("longitude") for h in hotspots if h.get("longitude") is not None]
    avg_lat = sum(lats) / len(lats) if lats else -2.5
    avg_lon = sum(lons) / len(lons) if lons else 118.0

    # Fetch Weather synchronously
    weather_info = None
    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": avg_lat,
                    "longitude": avg_lon,
                    "current": "temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,soil_moisture_0_to_10cm,weather_code",
                    "timezone": "Asia/Jakarta",
                    "wind_speed_unit": "ms"
                }
            )
            if resp.status_code == 200:
                weather_data = resp.json().get("current", {})
                
                # Fetch Air Quality
                aq_resp = client.get(
                    "https://air-quality-api.open-meteo.com/v1/air-quality",
                    params={
                        "latitude": avg_lat,
                        "longitude": avg_lon,
                        "current": "pm2_5,us_aqi",
                        "timezone": "Asia/Jakarta"
                    }
                )
                aq_data = aq_resp.json().get("current", {}) if aq_resp.status_code == 200 else {}
                
                # CBI
                t = float(weather_data.get("temperature_2m", 0.0) or 0.0)
                rh = float(weather_data.get("relative_humidity_2m", 0.0) or 0.0)
                rh_clamp = max(0.0, min(100.0, rh))
                cbi = ((110.0 - 1.37 * rh_clamp) - 9.01) * (10 ** (0.0444 * t)) / 124.0
                cbi = max(0.0, cbi)
                
                if cbi < 50:
                    cbi_level = "Rendah"
                    cbi_color = "#22c55e"
                elif cbi < 75:
                    cbi_level = "Sedang"
                    cbi_color = "#eab308"
                elif cbi < 90:
                    cbi_level = "Tinggi"
                    cbi_color = "#f97316"
                elif cbi < 97.5:
                    cbi_level = "Sangat Tinggi"
                    cbi_color = "#ef4444"
                else:
                    cbi_level = "Ekstrem"
                    cbi_color = "#7f1d1d"

                sm = float(weather_data.get("soil_moisture_0_to_10cm", 0.0) or 0.0)
                if sm < 0.15:
                    sm_status = "Kering (Ekstrem)"
                    sm_color = "#ef4444"
                elif sm < 0.25:
                    sm_status = "Sedang"
                    sm_color = "#eab308"
                else:
                    sm_status = "Basah (Aman)"
                    sm_color = "#22c55e"
                
                weather_info = {
                    "temperature": t,
                    "humidity": rh,
                    "precipitation": float(weather_data.get("precipitation", 0.0) or 0.0),
                    "wind_speed": float(weather_data.get("wind_speed_10m", 0.0) or 0.0),
                    "wind_gusts": float(weather_data.get("wind_gusts_10m", 0.0) or 0.0),
                    "soil_moisture": sm,
                    "soil_moisture_status": sm_status,
                    "soil_moisture_color": sm_color,
                    "cbi_value": round(cbi, 2),
                    "cbi_level": cbi_level,
                    "cbi_color": cbi_color,
                    "aqi": int(aq_data.get("us_aqi", 0) or 0),
                    "pm2_5": float(aq_data.get("pm2_5", 0.0) or 0.0)
                }
    except Exception as e:
        logger.warning(f"Failed to fetch weather for PDF: {e}")

    # Section 1: Profil Lembaga / Wilayah Kerja
    story.append(Paragraph("Profil Lembaga & Wilayah Administrasi", section_heading))
    
    # Extract Metadata from first hotspot if available
    first_h = hotspots[0] if hotspots else {}
    meta = first_h.get("polygon_metadata", {})
    
    prov_name = first_h.get("province_name") or meta.get("NAMA_PROV") or "N/A"
    bps_name = meta.get("WILKER_BPS") or "N/A"
    kab_name = meta.get("NAMA_KAB") or "N/A"
    fungsi_kws = meta.get("FUNGSI_KWS") or "N/A"
    
    profile_data = [
        [Paragraph("<b>Nama Lembaga:</b>", body_style), Paragraph(agency_name, bold_body_style)],
        [Paragraph("<b>Balai Pengelola (BPS):</b>", body_style), Paragraph(bps_name, body_style)],
        [Paragraph("<b>Kabupaten / Provinsi:</b>", body_style), Paragraph(f"{kab_name} / {prov_name}", body_style)],
        [Paragraph("<b>Fungsi Kawasan Hutan:</b>", body_style), Paragraph(fungsi_kws, body_style)],
        [Paragraph("<b>Koordinat Centroid:</b>", body_style), Paragraph(f"{avg_lat:.5f}, {avg_lon:.5f}", body_style)],
    ]
    
    profile_table = Table(profile_data, colWidths=[150, 373.27])
    profile_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), c_light),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    story.append(profile_table)
    story.append(Spacer(1, 8))

    # Section 2: Meteo & Early Warning Info (Open-Meteo)
    if weather_info:
        story.append(Paragraph("Kondisi Cuaca & Peringatan Dini Kebakaran", section_heading))
        weather_table_data = [
            [
                Paragraph("Suhu Udara: <b>{:.1f} °C</b>".format(weather_info["temperature"]), body_style),
                Paragraph("Kelembapan: <b>{:.0f}% RH</b>".format(weather_info["humidity"]), body_style),
            ],
            [
                Paragraph("Curah Hujan: <b>{:.1f} mm/jam</b>".format(weather_info["precipitation"]), body_style),
                Paragraph("Kecepatan Angin: <b>{:.1f} m/s</b>".format(weather_info["wind_speed"]), body_style),
            ],
            [
                Paragraph("Hembusan Maks: <b>{:.1f} m/s</b>".format(weather_info["wind_gusts"]), body_style),
                Paragraph("Gambut (Soil Moisture): <b style='color: {}'>{} ({:.1f}%)</b>".format(
                    weather_info["soil_moisture_color"],
                    weather_info["soil_moisture_status"],
                    weather_info["soil_moisture"] * 100
                ), body_style),
            ],
            [
                Paragraph("Polusi PM2.5: <b>{:.1f} µg/m³</b>".format(weather_info["pm2_5"]), body_style),
                Paragraph("Kualitas Udara: <b>{} AQI</b>".format(weather_info["aqi"]), body_style),
            ],
            [
                Paragraph("<b>Indeks Bahaya Api (CBI):</b>", bold_body_style),
                Paragraph("<b style='color: {}'>{} ({:.2f})</b>".format(
                    weather_info["cbi_color"],
                    weather_info["cbi_level"],
                    weather_info["cbi_value"]
                ), bold_body_style),
            ]
        ]
        weather_table = Table(weather_table_data, colWidths=[261.6, 261.6])
        weather_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#fffbfa")),
            ('BOX', (0,0), (-1,-1), 1.5, colors.HexColor("#ea580c")),
            ('GRID', (0,0), (-1,-1), 0.5, c_border),
            ('PADDING', (0,0), (-1,-1), 6),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        story.append(weather_table)
        story.append(Spacer(1, 8))

    # Section 3: Detailed Hotspot Table
    story.append(Paragraph(f"Daftar Deteksi Titik Panas Aktif ({len(hotspots)} Titik)", section_heading))
    
    # Columns: No, Tanggal, Satelit, Kepercayaan, Kecerahan, FRP, Lat/Lon
    h_headers = ["No", "Tanggal (WIB)", "Satelit", "Kategori", "Bright (K)", "FRP (MW)", "Koordinat"]
    h_rows = [[Paragraph(f"<b>{x}</b>", ParagraphStyle("Hdr", parent=bold_body_style, textColor=c_white)) for x in h_headers]]
    
    for idx, h in enumerate(hotspots):
        formatted_time = _get_wib_date_str(h.get("detected_at", ""))
        frp_val = float(h.get("frp", 0) or 0)
        frp_cat = "Tinggi" if frp_val > 30 else ("Sedang" if frp_val >= 10 else "Rendah")
        
        row = [
            Paragraph(str(idx + 1), body_style),
            Paragraph(formatted_time, body_style),
            Paragraph(h.get("source", "N/A"), body_style),
            Paragraph(frp_cat, bold_body_style),
            Paragraph(str(h.get("brightness", "-")), body_style),
            Paragraph(str(h.get("frp", "-")), body_style),
            Paragraph(f"{h.get('latitude', 0.0):.4f}, {h.get('longitude', 0.0):.4f}", body_style)
        ]
        h_rows.append(row)
        
    t_style = [
        ('BACKGROUND', (0,0), (-1,0), c_primary),
        ('GRID', (0,0), (-1,-1), 0.5, c_border),
        ('PADDING', (0,0), (-1,-1), 4),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]
    
    # Alternating row colors for premium readability
    for i in range(1, len(h_rows)):
        t_style.append(('BACKGROUND', (0, i), (-1, i), c_white if i % 2 == 1 else c_light))
        
    h_table = Table(h_rows, colWidths=[20, 105, 55, 60, 58, 55, 170.27], repeatRows=1)
    h_table.setStyle(TableStyle(t_style))
    story.append(h_table)
    story.append(Spacer(1, 15))

    # Signatures
    sig_data = [
        [Paragraph("Disiapkan Oleh:", bold_body_style), Paragraph("Disetujui Oleh Pengelola Kawasan:", bold_body_style)],
        [Spacer(1, 25), Spacer(1, 25)],
        [Paragraph("_____________________________", body_style), Paragraph("_____________________________", body_style)]
    ]
    sig_table = Table(sig_data, colWidths=[261, 262])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
        ('PADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(KeepTogether([Spacer(1, 5), sig_table]))

    # Canvas decorations
    class PortraitNumberedCanvas(canvas.Canvas):
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
            
            # Header
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(c_primary)
            self.drawString(36, 805, f"LAPORAN DETEKSI KHUSUS LEMBAGA — {agency_name.upper()}")
            
            self.setFont("Helvetica", 8)
            self.setFillColor(c_dark)
            self.drawRightString(559, 805, f"Periode: {period_str}")
            
            self.setStrokeColor(c_border)
            self.setLineWidth(0.75)
            self.line(36, 795, 559, 795)

            # Footer
            self.line(36, 40, 559, 40)
            self.setFont("Helvetica-Bold", 8)
            self.setFillColor(c_dark)
            self.drawString(36, 25, "ETA SEUNEU - MONITORING PERHUTANAN SOSIAL")
            
            self.setFont("Helvetica", 8)
            self.drawRightString(559, 25, f"Halaman {self._pageNumber} dari {page_count}")
            self.restoreState()

    doc.build(story, canvasmaker=PortraitNumberedCanvas)
    return buffer.getvalue()
