from io import BytesIO

from openpyxl import Workbook


EXPORT_HEADERS = [
    "No",
    "Nama Wilayah",
    "Satelit",
    "Tanggal Deteksi",
    "Latitude",
    "Longitude",
    "Kategori FRP",
    "Brightness",
]


from datetime import datetime, timezone, timedelta

def build_export_rows(hotspots: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for index, hotspot in enumerate(hotspots, start=1):
        detected_at = hotspot.get("detected_at", "")
        if detected_at:
            try:
                dt = datetime.fromisoformat(str(detected_at).replace("Z", "+00:00"))
                detected_at_wib = dt.astimezone(timezone(timedelta(hours=7))).strftime("%d-%m-%Y %H:%M WIB")
            except Exception:
                detected_at_wib = str(detected_at)
        else:
            detected_at_wib = ""

        rows.append(
            {
                "No": index,
                "Nama Wilayah": hotspot.get("layer_name", ""),
                "Satelit": hotspot.get("source", ""),
                "Tanggal Deteksi": detected_at_wib,
                "Latitude": hotspot.get("latitude", ""),
                "Longitude": hotspot.get("longitude", ""),
                "Kategori FRP": "Tinggi" if float(hotspot.get("frp") or 0) > 30 else ("Sedang" if float(hotspot.get("frp") or 0) >= 10 else "Rendah"),
                "Brightness": hotspot.get("brightness", ""),
            }
        )
    return rows


def build_excel_file(hotspots: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    rows = build_export_rows(hotspots)

    sheet.append(EXPORT_HEADERS)
    for row in rows:
        sheet.append([row[header] for header in EXPORT_HEADERS])

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
