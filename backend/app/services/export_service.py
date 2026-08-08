from collections import Counter
from datetime import datetime, timedelta, timezone
from io import BytesIO

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.hotspot_categories import (
    CATEGORY_ORDER,
    confidence_category,
    frp_category,
)
from app.services.polygon_fields import polygon_field, sk_date, sk_number


WIB = timezone(timedelta(hours=7))

EXPORT_HEADERS = [
    "No",
    "Nama Wilayah",
    # Balai PS & Provinsi disisipkan setelah "Nama Wilayah" -- posisi kolom
    # sebelumnya (No, Nama Wilayah) sengaja dipertahankan supaya konsumen lama
    # yang membaca dua kolom pertama tidak ikut bergeser.
    "No. SK",
    "Tgl SK",
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

# ── Palet ──────────────────────────────────────────────────────────────────
_INK = "1B3A2B"
_ACCENT = "E0862A"
_HEADER_TEXT = "FFFFFF"
_BAND = "EEF3EF"
_MUTED = "6B726D"
_RULE = "D8DDD9"

_THIN_RULE = Side(style="thin", color=_RULE)
_CELL_BORDER = Border(left=_THIN_RULE, right=_THIN_RULE, top=_THIN_RULE, bottom=_THIN_RULE)


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


def _provinsi(hotspot: dict) -> str:
    direct = hotspot.get("province_name")
    if direct not in (None, ""):
        return str(direct)
    return polygon_field(hotspot, "NAMA_PROV", "NAMA_PROVINSI", "PROVINSI") or "Tanpa Provinsi"


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
                "Balai PS": _balai_ps(hotspot),
                "Provinsi": _provinsi(hotspot),
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
        "per_balai": Counter(row["Balai PS"] for row in rows).most_common(),
        "per_provinsi": Counter(row["Provinsi"] for row in rows).most_common(),
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

    widths = [5, 34, 40, 12, 22, 20, 18, 15, 20, 12, 12, 12, 12, 10, 12]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    # Baris header dibekukan supaya kolom Balai PS/Provinsi tetap terbaca saat
    # menggulir ribuan baris.
    sheet.freeze_panes = "A2"
    if rows:
        sheet.auto_filter.ref = f"A1:{get_column_letter(len(EXPORT_HEADERS))}{len(rows) + 1}"


def _title_block(sheet, summary: dict) -> int:
    sheet["A1"] = "DASHBOARD HOTSPOT KAWASAN PERHUTANAN SOSIAL"
    sheet["A1"].font = Font(bold=True, size=16, color=_INK)
    sheet["A2"] = (
        f"Periode {summary['periode_awal']} s.d. {summary['periode_akhir']}  •  "
        f"Sumber: ETA SENEU (hotspot beririsan dengan poligon KPS)"
    )
    sheet["A2"].font = Font(size=10, color=_MUTED, italic=True)

    cards = [
        ("Total Hotspot", summary["total"]),
        ("KPS Terdampak", summary["jumlah_kps"]),
        ("Balai PS", summary["jumlah_balai"]),
        ("Provinsi", summary["jumlah_provinsi"]),
    ]
    for offset, (label, value) in enumerate(cards):
        column = 1 + offset * 2
        label_cell = sheet.cell(row=4, column=column, value=label)
        label_cell.font = Font(bold=True, size=9, color=_MUTED)
        value_cell = sheet.cell(row=5, column=column, value=value)
        value_cell.font = Font(bold=True, size=20, color=_INK)
        sheet.cell(row=6, column=column).fill = PatternFill("solid", fgColor=_ACCENT)

    return 8


def _write_section(sheet, start_row: int, title: str, headers: tuple[str, str],
                   data: list[tuple[str, int]], total: int) -> int:
    """Tulis satu tabel ringkasan. Mengembalikan baris kosong setelah tabel."""
    title_cell = sheet.cell(row=start_row, column=1, value=title)
    title_cell.font = Font(bold=True, size=12, color=_INK)

    header_row = start_row + 1
    header_fill = PatternFill("solid", fgColor=_INK)
    for offset, header in enumerate((*headers, "%")):
        cell = sheet.cell(row=header_row, column=1 + offset, value=header)
        cell.fill = header_fill
        cell.font = Font(bold=True, color=_HEADER_TEXT, size=10)
        cell.border = _CELL_BORDER

    for index, (label, count) in enumerate(data):
        row_number = header_row + 1 + index
        share = (count / total * 100) if total else 0
        values = (label, count, round(share, 1) / 100)
        for offset, value in enumerate(values):
            cell = sheet.cell(row=row_number, column=1 + offset, value=value)
            cell.border = _CELL_BORDER
            if index % 2 == 0:
                cell.fill = PatternFill("solid", fgColor=_BAND)
        sheet.cell(row=row_number, column=3).number_format = "0.0%"

    return header_row + max(len(data), 1) + 2


def _attach_bar_chart(sheet, anchor: str, title: str, header_row: int, row_count: int) -> None:
    if row_count <= 0:
        return
    chart = BarChart()
    chart.type = "bar"
    chart.title = title
    chart.height = min(2 + row_count * 0.65, 11)
    chart.width = 16
    chart.legend = None
    chart.y_axis.majorGridlines = None
    data = Reference(sheet, min_col=2, min_row=header_row, max_row=header_row + row_count)
    categories = Reference(sheet, min_col=1, min_row=header_row + 1, max_row=header_row + row_count)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)
    sheet.add_chart(chart, anchor)


def _attach_line_chart(sheet, anchor: str, title: str, header_row: int, row_count: int) -> None:
    if row_count <= 0:
        return
    chart = LineChart()
    chart.title = title
    chart.height = 8
    chart.width = 18
    chart.legend = None
    data = Reference(sheet, min_col=2, min_row=header_row, max_row=header_row + row_count)
    categories = Reference(sheet, min_col=1, min_row=header_row + 1, max_row=header_row + row_count)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)
    sheet.add_chart(chart, anchor)


def _write_dashboard_sheet(sheet, summary: dict) -> None:
    total = summary["total"]
    row = _title_block(sheet, summary)

    sections = [
        ("Hotspot per Balai PS", ("Balai PS", "Jumlah"), summary["per_balai"], "bar"),
        ("Hotspot per Provinsi", ("Provinsi", "Jumlah"), summary["per_provinsi"], "bar"),
        ("Tren Bulanan", ("Bulan", "Jumlah"), summary["per_bulan"], "line"),
        ("10 KPS dengan Hotspot Terbanyak", ("KPS", "Jumlah"), summary["top_kps"], "bar"),
        ("Distribusi Confidence", ("Kategori", "Jumlah"), summary["per_confidence"], "bar"),
        ("Distribusi Intensitas FRP", ("Kategori", "Jumlah"), summary["per_frp"], "bar"),
        ("Hotspot per Satelit", ("Satelit", "Jumlah"), summary["per_satelit"], "bar"),
    ]

    for title, headers, data, chart_kind in sections:
        header_row = row + 1
        next_row = _write_section(sheet, row, title, headers, data, total)
        anchor = f"E{row}"
        if chart_kind == "line":
            _attach_line_chart(sheet, anchor, title, header_row, len(data))
        else:
            _attach_bar_chart(sheet, anchor, title, header_row, len(data))
        # Chart menempel di kolom E dan butuh ruang vertikal sendiri; tabelnya
        # biasanya lebih pendek, jadi jarak antar seksi mengikuti yang lebih
        # tinggi supaya chart tidak saling tumpuk.
        row = max(next_row, header_row + len(data) + 2, row + 16)

    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["B"].width = 12
    sheet.column_dimensions["C"].width = 10
    sheet.column_dimensions["D"].width = 3


def build_excel_file(hotspots: list[dict]) -> bytes:
    workbook = Workbook()

    data_sheet = workbook.active
    data_sheet.title = DATA_SHEET_TITLE
    _write_data_sheet(data_sheet, build_export_rows(hotspots))

    dashboard_sheet = workbook.create_sheet(DASHBOARD_SHEET_TITLE)
    _write_dashboard_sheet(dashboard_sheet, build_dashboard_summary(hotspots))

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
