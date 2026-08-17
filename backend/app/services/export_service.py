from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.data_source import AxDataSource, StrRef
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.hotspot_categories import (
    CATEGORY_ORDER,
    confidence_category,
    frp_category,
)
from app.services.polygon_fields import (
    polygon_field,
    provinsi_name,
    sk_date,
    sk_number,
    skema_name,
)
from app.services.skema_stats import (
    SkemaProvinsiMatrix,
    build_skema_provinsi_matrix,
    count_per_skema,
)


WIB = timezone(timedelta(hours=7))

EXPORT_HEADERS = [
    "No",
    "Nama Wilayah",
    # Balai PS, Provinsi, & Skema disisipkan setelah "Nama Wilayah" -- posisi
    # kolom sebelumnya (No, Nama Wilayah) sengaja dipertahankan supaya konsumen
    # lama yang membaca dua kolom pertama tidak ikut bergeser.
    "No. SK",
    "Tgl SK",
    "Skema",
    "Balai PS",
    "Provinsi",
    "Kabupaten",
    "Satelit",
    "Tanggal Deteksi",
    "Latitude",
    "Longitude",
    "Confidence",
    "Kategori FRP",
    "FRP (MW)",
    "Brightness",
]

DATA_SHEET_TITLE = "Data Hotspot"
DASHBOARD_SHEET_TITLE = "Dashboard"
SKEMA_SHEET_TITLE = "Skema per Provinsi"

# ── Palet Warna Eksekutif Modern ─────────────────────────────────────────────
_INK = "1B3A2B"        # Deep Forest Green (Utama)
_EMERALD = "2D6A4F"    # Emerald Green (Sekunder)
_ACCENT = "E0862A"     # Warm Amber (Aksen Highlight)
_HEADER_TEXT = "FFFFFF"# Putih
_CARD_BG = "F4F8F5"    # Card background
_CARD_BORDER = "CFD8D2"# Card border
_BAND = "F8FAF9"       # Zebra striping lembut
_MUTED = "5A655F"      # Text muted
_RULE = "D8DDD9"       # Border tabel
_TOTAL_BG = "EBF2ED"   # Background baris total

_THIN_RULE = Side(style="thin", color=_RULE)
_DOUBLE_RULE = Side(style="double", color=_INK)
_CARD_SIDE = Side(style="thin", color=_CARD_BORDER)

_CELL_BORDER = Border(left=_THIN_RULE, right=_THIN_RULE, top=_THIN_RULE, bottom=_THIN_RULE)
_TOTAL_BORDER = Border(left=_THIN_RULE, right=_THIN_RULE, top=_THIN_RULE, bottom=_DOUBLE_RULE)
_CARD_BOX = Border(left=_CARD_SIDE, right=_CARD_SIDE, top=_CARD_SIDE, bottom=_CARD_SIDE)


def _wib_datetime(detected_at: object) -> datetime | None:
    if not detected_at:
        return None
    try:
        parsed = datetime.fromisoformat(str(detected_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(WIB)


def _balai_ps(hotspot: dict) -> str:
    return polygon_field(hotspot, "WILKER_BPS") or "Tanpa Balai"


def build_export_rows(hotspots: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for index, hotspot in enumerate(hotspots, start=1):
        wib = _wib_datetime(hotspot.get("detected_at"))
        detected_at_wib = (
            wib.strftime("%d-%m-%Y %H:%M WIB") if wib else str(hotspot.get("detected_at", ""))
        )

        rows.append(
            {
                "No": index,
                "Nama Wilayah": hotspot.get("layer_name", ""),
                "No. SK": sk_number(hotspot),
                "Tgl SK": sk_date(hotspot),
                "Skema": skema_name(hotspot),
                "Balai PS": _balai_ps(hotspot),
                "Provinsi": provinsi_name(hotspot),
                "Kabupaten": polygon_field(hotspot, "NAMA_KAB"),
                "Satelit": hotspot.get("source", ""),
                "Tanggal Deteksi": detected_at_wib,
                "Latitude": hotspot.get("latitude", ""),
                "Longitude": hotspot.get("longitude", ""),
                "Confidence": confidence_category(hotspot),
                "Kategori FRP": frp_category(hotspot),
                "FRP (MW)": hotspot.get("frp", ""),
                "Brightness": hotspot.get("brightness", ""),
            }
        )
    return rows


# ── Agregasi dashboard ─────────────────────────────────────────────────────

def build_dashboard_summary(hotspots: list[dict]) -> dict:
    """Ringkasan yang dipakai sheet Dashboard.

    Dipisah dari penulisan Excel supaya angkanya bisa diuji tanpa harus
    membongkar file .xlsx.
    """
    rows = build_export_rows(hotspots)
    total = len(rows)

    moments = [m for m in (_wib_datetime(h.get("detected_at")) for h in hotspots) if m]

    per_bulan: Counter[str] = Counter()
    for moment in moments:
        per_bulan[moment.strftime("%Y-%m")] += 1

    return {
        "total": total,
        "periode_awal": min(moments).strftime("%d-%m-%Y") if moments else "-",
        "periode_akhir": max(moments).strftime("%d-%m-%Y") if moments else "-",
        "jumlah_kps": len({row["Nama Wilayah"] for row in rows if row["Nama Wilayah"]}),
        "jumlah_balai": len({row["Balai PS"] for row in rows if row["Balai PS"]}),
        "jumlah_provinsi": len({row["Provinsi"] for row in rows if row["Provinsi"]}),
        "jumlah_skema": len({row["Skema"] for row in rows if row["Skema"]}),
        "per_balai": Counter(row["Balai PS"] for row in rows).most_common(),
        "per_provinsi": Counter(row["Provinsi"] for row in rows).most_common(),
        "per_skema": count_per_skema(hotspots),
        "skema_per_provinsi": build_skema_provinsi_matrix(hotspots),
        "per_satelit": Counter(row["Satelit"] for row in rows).most_common(),
        "per_confidence": [
            (level, sum(1 for row in rows if row["Confidence"] == level))
            for level in CATEGORY_ORDER
        ],
        "per_frp": [
            (level, sum(1 for row in rows if row["Kategori FRP"] == level))
            for level in CATEGORY_ORDER
        ],
        "per_bulan": sorted(per_bulan.items()),
        "top_kps": Counter(
            row["Nama Wilayah"] for row in rows if row["Nama Wilayah"]
        ).most_common(10),
    }


# ── Penulisan sheet ────────────────────────────────────────────────────────

def _write_data_sheet(sheet, rows: list[dict]) -> None:
    sheet.append(EXPORT_HEADERS)
    for row in rows:
        sheet.append([row[header] for header in EXPORT_HEADERS])

    header_fill = PatternFill("solid", fgColor=_INK)
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(bold=True, color=_HEADER_TEXT, size=10)
        cell.alignment = Alignment(vertical="center", horizontal="left")
    sheet.row_dimensions[1].height = 22

    widths = [5, 34, 40, 12, 14, 22, 20, 18, 15, 20, 12, 12, 12, 12, 10, 12]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    # Baris header dibekukan supaya kolom Balai PS/Provinsi tetap terbaca saat
    # menggulir ribuan baris.
    sheet.freeze_panes = "A2"
    if rows:
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(EXPORT_HEADERS))}{len(rows) + 1}"


def _title_block(sheet, summary: dict) -> int:
    sheet["A1"] = "DASHBOARD HOTSPOT KAWASAN PERHUTANAN SOSIAL"
    sheet["A1"].font = Font(name="Calibri", bold=True, size=15, color=_INK)
    sheet["A2"] = (
        f"Periode {summary['periode_awal']} s.d. {summary['periode_akhir']}  •  "
        f"Sumber: ETA SENEU (hotspot beririsan dengan poligon KPS)"
    )
    sheet["A2"].font = Font(name="Calibri", size=9, color=_MUTED, italic=True)

    sheet.row_dimensions[1].height = 24
    sheet.row_dimensions[2].height = 18
    sheet.row_dimensions[3].height = 10

    # 5 Kartu Metrik Ringkasan (A, C, E, G, I) dengan merge 2 kolom per kartu
    cards = [
        ("Total Hotspot", summary["total"], 1, 2),
        ("KPS Terdampak", summary["jumlah_kps"], 3, 4),
        ("Balai PS", summary["jumlah_balai"], 5, 6),
        ("Provinsi", summary["jumlah_provinsi"], 7, 8),
        ("Skema PS", summary["jumlah_skema"], 9, 10),
    ]

    card_fill = PatternFill("solid", fgColor=_CARD_BG)
    accent_fill = PatternFill("solid", fgColor=_ACCENT)

    for label, value, col_start, col_end in cards:
        sheet.cell(row=4, column=col_start, value=label)
        sheet.cell(row=5, column=col_start, value=value)

        for r in range(4, 7):
            for c in range(col_start, col_end + 1):
                cell = sheet.cell(row=r, column=c)
                cell.fill = accent_fill if r == 6 else card_fill
                cell.border = _CARD_BOX

        lbl_cell = sheet.cell(row=4, column=col_start)
        lbl_cell.font = Font(name="Calibri", bold=True, size=8.5, color=_MUTED)
        lbl_cell.alignment = Alignment(horizontal="center", vertical="center")

        val_cell = sheet.cell(row=5, column=col_start)
        val_cell.font = Font(name="Calibri", bold=True, size=18, color=_INK)
        val_cell.number_format = "#,##0"
        val_cell.alignment = Alignment(horizontal="center", vertical="center")

        if col_end > col_start:
            sheet.merge_cells(start_row=4, start_column=col_start, end_row=4, end_column=col_end)
            sheet.merge_cells(start_row=5, start_column=col_start, end_row=5, end_column=col_end)
            sheet.merge_cells(start_row=6, start_column=col_start, end_row=6, end_column=col_end)

    sheet.row_dimensions[4].height = 16
    sheet.row_dimensions[5].height = 26
    sheet.row_dimensions[6].height = 4
    sheet.row_dimensions[7].height = 14

    return 8


def _attach_bar_chart(sheet, anchor: str, title: str, header_row: int, row_count: int,
                      chart_type: str = "bar", color: str = _INK, data_col: int = 1,
                      height: float = 8.5, width: float = 16.5) -> None:
    if row_count <= 0:
        return
    chart = BarChart()
    chart.type = chart_type
    chart.title = title
    chart.style = 10
    chart.legend = None
    chart.height = height
    chart.width = width

    if chart_type == "bar":
        # x_axis is Category Axis on the LEFT
        chart.x_axis.axPos = "l"
        chart.x_axis.tickLblPos = "nextTo"
        chart.x_axis.title = None

        # y_axis is Value Axis at the BOTTOM
        chart.y_axis.axPos = "b"
        chart.y_axis.tickLblPos = "nextTo"
        chart.y_axis.title = "Jumlah Titik Panas"
        chart.y_axis.majorGridlines = ChartLines()
    else:
        # x_axis is Category Axis at the BOTTOM
        chart.x_axis.axPos = "b"
        chart.x_axis.tickLblPos = "nextTo"
        chart.x_axis.title = None

        # y_axis is Value Axis on the LEFT
        chart.y_axis.axPos = "l"
        chart.y_axis.tickLblPos = "nextTo"
        chart.y_axis.title = "Jumlah Titik Panas"
        chart.y_axis.majorGridlines = ChartLines()

    # Data Labels: selalu tampilkan nilai angka pada setiap batang
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    chart.dataLabels.showCatName = False
    chart.dataLabels.showSerName = False
    chart.dataLabels.showPercent = False
    chart.dataLabels.showLegendKey = False

    value_col = data_col + 1
    data = Reference(sheet, min_col=value_col, min_row=header_row, max_row=header_row + row_count)
    categories = Reference(sheet, min_col=data_col, min_row=header_row + 1, max_row=header_row + row_count)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)

    cat_col_letter = get_column_letter(data_col)
    cat_range = f"'{sheet.title}'!${cat_col_letter}${header_row + 1}:${cat_col_letter}${header_row + row_count}"
    if chart.series:
        chart.series[0].cat = AxDataSource(strRef=StrRef(f=cat_range))
        chart.series[0].graphicalProperties.solidFill = color

    sheet.add_chart(chart, anchor)


def _attach_line_chart(sheet, anchor: str, title: str, header_row: int, row_count: int,
                       color: str = _INK, accent_color: str = _ACCENT, data_col: int = 1,
                       height: float = 8.5, width: float = 16.5) -> None:
    if row_count <= 0:
        return
    chart = LineChart()
    chart.title = title
    chart.style = 13
    chart.height = height
    chart.width = width
    chart.legend = None

    chart.x_axis.axPos = "b"
    chart.x_axis.tickLblPos = "nextTo"
    chart.x_axis.title = "Bulan"

    chart.y_axis.axPos = "l"
    chart.y_axis.tickLblPos = "nextTo"
    chart.y_axis.title = "Jumlah Titik Panas"
    chart.y_axis.majorGridlines = ChartLines()

    # Data Labels informatif pada setiap titik tren bulanan
    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    chart.dataLabels.showCatName = False
    chart.dataLabels.showSerName = False
    chart.dataLabels.showPercent = False
    chart.dataLabels.showLegendKey = False

    value_col = data_col + 1
    data = Reference(sheet, min_col=value_col, min_row=header_row, max_row=header_row + row_count)
    categories = Reference(sheet, min_col=data_col, min_row=header_row + 1, max_row=header_row + row_count)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)

    cat_col_letter = get_column_letter(data_col)
    cat_range = f"'{sheet.title}'!${cat_col_letter}${header_row + 1}:${cat_col_letter}${header_row + row_count}"
    if chart.series:
        chart.series[0].cat = AxDataSource(strRef=StrRef(f=cat_range))
        chart.series[0].graphicalProperties.line.solidFill = color
        chart.series[0].graphicalProperties.line.width = 25000
        chart.series[0].marker.symbol = "circle"
        chart.series[0].marker.size = 6
        chart.series[0].marker.graphicalProperties.solidFill = accent_color
        chart.series[0].marker.graphicalProperties.line.solidFill = accent_color

    sheet.add_chart(chart, anchor)


def _write_chart_data(sheet, row: int, col: int, headers: tuple[str, str],
                      data: list[tuple[str, int]]) -> int:
    """Tulis label+jumlah polos (tanpa styling tabel) sebagai sumber data chart.

    Dashboard sekarang murni visual (KPI + chart grid), jadi angka mentahnya
    tidak perlu tampil sebagai tabel di layar -- cukup jadi sumber Reference
    untuk chart. Baris ini sengaja diletakkan di bawah print_area supaya tidak
    ikut tercetak/terekspor PDF.
    """
    header_row = row
    sheet.cell(row=header_row, column=col, value=headers[0])
    sheet.cell(row=header_row, column=col + 1, value=headers[1])
    for index, (label, count) in enumerate(data, start=1):
        sheet.cell(row=header_row + index, column=col, value=label)
        sheet.cell(row=header_row + index, column=col + 1, value=count)
    return header_row


# Grid ringkasan eksekutif: 2 kolom x 2 baris -- empat pertanyaan inti saja
# (di mana, skema apa, kapan, provinsi mana), bukan delapan tabel+chart yang
# ditumpuk memanjang seperti desain sebelumnya. Dibatasi 4 (bukan 6) supaya
# muat satu halaman cetak yang sungguhan tanpa berharap pada auto-scale
# "fit to page" -- terbukti tidak konsisten hasilnya antar aplikasi (Excel vs
# LibreOffice). Distribusi Confidence/FRP tetap dihitung di
# `build_dashboard_summary` untuk laporan PDF, hanya tidak ditampilkan di
# sini supaya ringkasannya benar-benar ringkas.
_GRID_COL_LEFT = 1   # A
_GRID_COL_RIGHT = 9  # I
_GRID_ROW_STEP = 16  # chart tinggi 7cm + jarak antar baris
_CHART_HEIGHT_CM = 7.0
_CHART_WIDTH_CM = 16.0


def _write_dashboard_sheet(sheet, summary: dict) -> None:
    grid_start = _title_block(sheet, summary) + 1

    charts = [
        ("Hotspot per Balai PS", ("Balai PS", "Jumlah"), summary["per_balai"], "bar", _INK),
        ("Hotspot per Skema Perhutanan Sosial", ("Skema", "Jumlah"), summary["per_skema"], "col", _EMERALD),
        ("Tren Bulanan", ("Bulan", "Jumlah"), summary["per_bulan"], "line", _INK),
        ("10 Provinsi Teratas", ("Provinsi", "Jumlah"), summary["per_provinsi"][:10], "bar", _ACCENT),
    ]
    grid_rows = 2

    # Sumber data tiap chart ditulis polos (tanpa styling tabel) berurutan di
    # bawah grid, di luar print_area -- dashboard yang tercetak/PDF cuma
    # berisi KPI + grid chart, tapi angka mentahnya tetap ada di sheet ini
    # (bukan dihapus) kalau suatu saat perlu ditelusuri manual.
    staging_row = grid_start + grid_rows * _GRID_ROW_STEP + 3
    sheet.cell(row=staging_row - 2, column=1, value="Data pendukung chart di atas (tidak ikut tercetak)")
    sheet.cell(row=staging_row - 2, column=1).font = Font(name="Calibri", italic=True, size=8, color=_MUTED)

    for index, (title, headers, data, chart_kind, color) in enumerate(charts):
        header_row = _write_chart_data(sheet, staging_row, 1, headers, data)
        staging_row = header_row + len(data) + 3

        grid_col = _GRID_COL_LEFT if index % 2 == 0 else _GRID_COL_RIGHT
        grid_row = grid_start + (index // 2) * _GRID_ROW_STEP
        anchor = f"{get_column_letter(grid_col)}{grid_row}"

        if chart_kind == "line":
            _attach_line_chart(sheet, anchor, title, header_row, len(data), color,
                               height=_CHART_HEIGHT_CM, width=_CHART_WIDTH_CM)
        elif chart_kind == "col":
            _attach_bar_chart(sheet, anchor, title, header_row, len(data), chart_type="col", color=color,
                              height=_CHART_HEIGHT_CM, width=_CHART_WIDTH_CM)
        else:
            _attach_bar_chart(sheet, anchor, title, header_row, len(data), chart_type="bar", color=color,
                              height=_CHART_HEIGHT_CM, width=_CHART_WIDTH_CM)

    last_grid_row = grid_start + grid_rows * _GRID_ROW_STEP

    # Kolom Grid: A s.d. O seragam lebar 11 (7 kolom per chart + 1 gutter)
    for col_idx in range(1, 16):
        sheet.column_dimensions[get_column_letter(col_idx)].width = 11

    # Landscape print & fit setup. print_area dibatasi tepat sampai bawah
    # grid chart supaya data pendukung yang polos di bawahnya tidak ikut
    # tercetak/terekspor PDF -- tanpa ini, area cetak default hanya
    # mengikuti sel yang ada isinya dan chart yang melayang di luar itu bisa
    # terpotong (persis bug yang bikin dashboard versi sebelumnya kacau).
    sheet.print_area = f"A1:O{last_grid_row}"
    sheet.page_setup.orientation = sheet.ORIENTATION_LANDSCAPE
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    # fitToHeight=1 (bukan 0) supaya ringkasan eksekutif ini benar-benar muat
    # satu halaman cetak/PDF. Margin dipersempit karena auto-scale
    # "fit to page" terbukti tidak konsisten hasilnya antar aplikasi (Excel vs
    # LibreOffice) -- dengan grid 4 chart yang sudah dikompakkan, layout ini
    # muat 1 halaman A4 landscape bahkan di skala 100%, jadi tidak
    # menggantungkan diri sepenuhnya pada auto-scale itu.
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 1
    sheet.page_margins.left = 0.4
    sheet.page_margins.right = 0.4
    sheet.page_margins.top = 0.5
    sheet.page_margins.bottom = 0.4
    sheet.page_margins.header = 0.2
    sheet.page_margins.footer = 0.2

    sheet.views.sheetView[0].showGridLines = True


def _write_skema_provinsi_sheet(sheet, matrix: SkemaProvinsiMatrix) -> None:
    """Tabel silang provinsi (baris) x skema (kolom) beserta baris/kolom total."""
    sheet["A1"] = "REKAP HOTSPOT PER SKEMA PERHUTANAN SOSIAL PER PROVINSI"
    sheet["A1"].font = Font(bold=True, size=14, color=_INK)
    sheet["A2"] = (
        "Jumlah titik panas pada setiap kombinasi provinsi dan skema izin perhutanan sosial. "
        "Kolom diurutkan dari skema dengan titik panas terbanyak."
    )
    sheet["A2"].font = Font(size=10, color=_MUTED, italic=True)

    header_row = 4
    headers = ("Provinsi", *matrix.skema, "Total")
    header_fill = PatternFill("solid", fgColor=_INK)
    for offset, header in enumerate(headers):
        cell = sheet.cell(row=header_row, column=1 + offset, value=header)
        cell.fill = header_fill
        cell.font = Font(bold=True, color=_HEADER_TEXT, size=10)
        cell.border = _CELL_BORDER
        cell.alignment = Alignment(
            vertical="center", horizontal="left" if offset == 0 else "center", wrap_text=True
        )
    sheet.row_dimensions[header_row].height = 28

    for index, row in enumerate(matrix.rows):
        row_number = header_row + 1 + index
        values = (row.provinsi, *row.counts, row.total)
        for offset, value in enumerate(values):
            cell = sheet.cell(row=row_number, column=1 + offset, value=value)
            cell.border = _CELL_BORDER
            if offset:
                cell.alignment = Alignment(horizontal="center")
            if index % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=_BAND)
        sheet.cell(row=row_number, column=len(headers)).font = Font(bold=True, color=_INK)

    total_row = header_row + len(matrix.rows) + 1
    for offset, value in enumerate(("Total", *matrix.totals, matrix.grand_total)):
        cell = sheet.cell(row=total_row, column=1 + offset, value=value)
        cell.font = Font(bold=True, color=_HEADER_TEXT, size=10)
        cell.fill = PatternFill("solid", fgColor=_ACCENT)
        cell.border = _CELL_BORDER
        if offset:
            cell.alignment = Alignment(horizontal="center")

    sheet.column_dimensions["A"].width = 30
    for offset in range(1, len(headers)):
        sheet.column_dimensions[get_column_letter(1 + offset)].width = 16
    # Kolom provinsi & baris header dibekukan supaya tetap terbaca saat tabel
    # digulir ke kanan (skema bisa sampai delapan kolom).
    sheet.freeze_panes = f"B{header_row + 1}"


def build_excel_file(hotspots: list[dict]) -> bytes:
    workbook = Workbook()

    data_sheet = workbook.active
    data_sheet.title = DATA_SHEET_TITLE
    _write_data_sheet(data_sheet, build_export_rows(hotspots))

    summary = build_dashboard_summary(hotspots)

    dashboard_sheet = workbook.create_sheet(DASHBOARD_SHEET_TITLE)
    _write_dashboard_sheet(dashboard_sheet, summary)

    skema_sheet = workbook.create_sheet(SKEMA_SHEET_TITLE)
    _write_skema_provinsi_sheet(skema_sheet, summary["skema_per_provinsi"])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
