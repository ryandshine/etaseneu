from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
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

# ── Palet ──────────────────────────────────────────────────────────────────
_INK = "1B3A2B"
_EMERALD = "2D6A4F"
_ACCENT = "E0862A"
_HEADER_TEXT = "FFFFFF"
_BAND = "F5F8F6"
_MUTED = "5A655F"
_RULE = "D8DDD9"
_CARD_BG = "F4F8F5"

_THIN_RULE = Side(style="thin", color=_RULE)
_DOUBLE_RULE = Side(style="double", color=_INK)
_CELL_BORDER = Border(left=_THIN_RULE, right=_THIN_RULE, top=_THIN_RULE, bottom=_THIN_RULE)
_TOTAL_BORDER = Border(left=_THIN_RULE, right=_THIN_RULE, top=_THIN_RULE, bottom=_DOUBLE_RULE)


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

    cards = [
        ("Total Hotspot", summary["total"]),
        ("KPS Terdampak", summary["jumlah_kps"]),
        ("Balai PS", summary["jumlah_balai"]),
        ("Provinsi", summary["jumlah_provinsi"]),
        ("Skema PS", summary["jumlah_skema"]),
    ]

    card_fill = PatternFill("solid", fgColor=_CARD_BG)
    card_border = Border(left=_THIN_RULE, right=_THIN_RULE, top=_THIN_RULE, bottom=_THIN_RULE)

    for offset, (label, value) in enumerate(cards):
        column = 1 + offset * 2
        label_cell = sheet.cell(row=4, column=column, value=label)
        label_cell.font = Font(name="Calibri", bold=True, size=8, color=_MUTED)
        label_cell.fill = card_fill
        label_cell.border = card_border
        label_cell.alignment = Alignment(horizontal="center", vertical="center")

        value_cell = sheet.cell(row=5, column=column, value=value)
        value_cell.font = Font(name="Calibri", bold=True, size=18, color=_INK)
        value_cell.fill = card_fill
        value_cell.border = card_border
        value_cell.number_format = "#,##0"
        value_cell.alignment = Alignment(horizontal="center", vertical="center")

        sheet.cell(row=6, column=column).fill = PatternFill("solid", fgColor=_ACCENT)

    sheet.row_dimensions[4].height = 16
    sheet.row_dimensions[5].height = 26
    sheet.row_dimensions[6].height = 4
    sheet.row_dimensions[7].height = 14

    return 8


def _write_section(sheet, start_row: int, title: str, headers: tuple[str, str],
                   data: list[tuple[str, int]], total: int) -> int:
    """Tulis satu tabel ringkasan dengan zebra-striping dan baris total."""
    title_cell = sheet.cell(row=start_row, column=1, value=title)
    title_cell.font = Font(name="Calibri", bold=True, size=11, color=_INK)
    sheet.row_dimensions[start_row].height = 22

    header_row = start_row + 1
    sheet.row_dimensions[header_row].height = 20
    header_fill = PatternFill("solid", fgColor=_INK)
    for offset, header in enumerate((*headers, "%")):
        cell = sheet.cell(row=header_row, column=1 + offset, value=header)
        cell.fill = header_fill
        cell.font = Font(name="Calibri", bold=True, color=_HEADER_TEXT, size=9)
        cell.border = _CELL_BORDER
        cell.alignment = Alignment(
            vertical="center",
            horizontal="left" if offset == 0 else "right"
        )

    sum_count = sum(count for _, count in data) if data else 0

    for index, (label, count) in enumerate(data):
        row_number = header_row + 1 + index
        sheet.row_dimensions[row_number].height = 18
        share = (count / total) if total else 0

        c_lbl = sheet.cell(row=row_number, column=1, value=label)
        c_lbl.border = _CELL_BORDER
        c_lbl.font = Font(name="Calibri", size=9)
        c_lbl.alignment = Alignment(vertical="center", horizontal="left")

        c_cnt = sheet.cell(row=row_number, column=2, value=count)
        c_cnt.border = _CELL_BORDER
        c_cnt.font = Font(name="Calibri", size=9)
        c_cnt.number_format = "#,##0"
        c_cnt.alignment = Alignment(vertical="center", horizontal="right")

        c_pct = sheet.cell(row=row_number, column=3, value=share)
        c_pct.border = _CELL_BORDER
        c_pct.font = Font(name="Calibri", size=9)
        c_pct.number_format = "0.0%"
        c_pct.alignment = Alignment(vertical="center", horizontal="right")

        if index % 2 == 1:
            c_lbl.fill = PatternFill("solid", fgColor=_BAND)
            c_cnt.fill = PatternFill("solid", fgColor=_BAND)
            c_pct.fill = PatternFill("solid", fgColor=_BAND)

    total_row = header_row + len(data) + 1
    sheet.row_dimensions[total_row].height = 20
    total_fill = PatternFill("solid", fgColor="EBF2ED")

    t_lbl = sheet.cell(row=total_row, column=1, value="Total")
    t_lbl.font = Font(name="Calibri", bold=True, size=9, color=_INK)
    t_lbl.fill = total_fill
    t_lbl.border = _TOTAL_BORDER
    t_lbl.alignment = Alignment(vertical="center", horizontal="left")

    t_cnt = sheet.cell(row=total_row, column=2, value=sum_count)
    t_cnt.font = Font(name="Calibri", bold=True, size=9, color=_INK)
    t_cnt.fill = total_fill
    t_cnt.border = _TOTAL_BORDER
    t_cnt.number_format = "#,##0"
    t_cnt.alignment = Alignment(vertical="center", horizontal="right")

    t_pct = sheet.cell(row=total_row, column=3, value=(sum_count / total) if total else 0)
    t_pct.font = Font(name="Calibri", bold=True, size=9, color=_INK)
    t_pct.fill = total_fill
    t_pct.border = _TOTAL_BORDER
    t_pct.number_format = "0.0%"
    t_pct.alignment = Alignment(vertical="center", horizontal="right")

    return total_row + 2


def _attach_bar_chart(sheet, anchor: str, title: str, header_row: int, row_count: int,
                      chart_type: str = "bar", color: str = _INK) -> None:
    if row_count <= 0:
        return
    chart = BarChart()
    chart.type = chart_type
    chart.title = title
    chart.style = 10

    if chart_type == "bar":
        chart.height = min(max(3.5 + row_count * 0.45, 5.5), 12.0)
        chart.width = 17.0
    else:
        chart.height = 7.5
        chart.width = 16.0

    chart.legend = None
    chart.y_axis.majorGridlines = None
    chart.x_axis.majorGridlines = None

    # Hanya tampilkan dataLabels jika item <= 14 untuk menghindari text overlap
    if row_count <= 14:
        chart.dataLabels = DataLabelList()
        chart.dataLabels.showVal = True
        chart.dataLabels.showCatName = False
        chart.dataLabels.showSerName = False
        chart.dataLabels.showPercent = False
        chart.dataLabels.showLegendKey = False

    data = Reference(sheet, min_col=2, min_row=header_row, max_row=header_row + row_count)
    categories = Reference(sheet, min_col=1, min_row=header_row + 1, max_row=header_row + row_count)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)

    if chart.series:
        chart.series[0].graphicalProperties.solidFill = color

    sheet.add_chart(chart, anchor)


def _attach_line_chart(sheet, anchor: str, title: str, header_row: int, row_count: int,
                       color: str = _INK, accent_color: str = _ACCENT) -> None:
    if row_count <= 0:
        return
    chart = LineChart()
    chart.title = title
    chart.style = 13
    chart.height = 7.5
    chart.width = 16.0
    chart.legend = None

    chart.dataLabels = DataLabelList()
    chart.dataLabels.showVal = True
    chart.dataLabels.showCatName = False
    chart.dataLabels.showSerName = False
    chart.dataLabels.showPercent = False
    chart.dataLabels.showLegendKey = False

    data = Reference(sheet, min_col=2, min_row=header_row, max_row=header_row + row_count)
    categories = Reference(sheet, min_col=1, min_row=header_row + 1, max_row=header_row + row_count)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)

    if chart.series:
        chart.series[0].graphicalProperties.line.solidFill = color
        chart.series[0].graphicalProperties.line.width = 25000
        chart.series[0].marker.symbol = "circle"
        chart.series[0].marker.size = 5
        chart.series[0].marker.graphicalProperties.solidFill = accent_color
        chart.series[0].marker.graphicalProperties.line.solidFill = accent_color

    sheet.add_chart(chart, anchor)


def _write_dashboard_sheet(sheet, summary: dict) -> None:
    total = summary["total"]
    row = _title_block(sheet, summary)

    sections = [
        ("Hotspot per Balai PS", ("Balai PS", "Jumlah"), summary["per_balai"], "bar", _INK),
        ("Hotspot per Skema Perhutanan Sosial", ("Skema", "Jumlah"), summary["per_skema"], "col", _EMERALD),
        ("Tren Bulanan", ("Bulan", "Jumlah"), summary["per_bulan"], "line", _INK),
        ("10 KPS dengan Hotspot Terbanyak", ("KPS", "Jumlah"), summary["top_kps"], "bar", _ACCENT),
        ("Hotspot per Provinsi", ("Provinsi", "Jumlah"), summary["per_provinsi"], "bar", _INK),
        ("Distribusi Confidence", ("Kategori", "Jumlah"), summary["per_confidence"], "col", _INK),
        ("Distribusi Intensitas FRP", ("Kategori", "Jumlah"), summary["per_frp"], "col", _EMERALD),
        ("Hotspot per Satelit", ("Satelit", "Jumlah"), summary["per_satelit"], "col", _ACCENT),
    ]

    for title, headers, data, chart_kind, color in sections:
        header_row = row + 1
        next_row = _write_section(sheet, row, title, headers, data, total)
        anchor = f"E{row}"
        if chart_kind == "line":
            _attach_line_chart(sheet, anchor, title, header_row, len(data), color)
        elif chart_kind == "col":
            _attach_bar_chart(sheet, anchor, title, header_row, len(data), chart_type="col", color=color)
        else:
            _attach_bar_chart(sheet, anchor, title, header_row, len(data), chart_type="bar", color=color)

        table_rows = len(data) + 4
        chart_rows = int(min(max(3.5 + len(data) * 0.45, 5.5), 12.0) * 1.8) if chart_kind == "bar" else 15
        row = row + max(table_rows, chart_rows) + 2

    sheet.column_dimensions["A"].width = 32
    sheet.column_dimensions["B"].width = 12
    sheet.column_dimensions["C"].width = 10
    sheet.column_dimensions["D"].width = 3
    sheet.column_dimensions["E"].width = 14
    sheet.column_dimensions["F"].width = 14
    sheet.column_dimensions["G"].width = 14
    sheet.column_dimensions["H"].width = 14
    sheet.column_dimensions["I"].width = 14
    sheet.column_dimensions["J"].width = 14
    sheet.column_dimensions["K"].width = 14

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
