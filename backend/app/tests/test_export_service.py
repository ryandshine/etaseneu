def test_build_export_rows_maps_hotspot_fields() -> None:
    from app.services.export_service import build_export_rows

    rows = build_export_rows(
        [
            {
                "layer_name": "sample_area",
                "source": "MODIS",
                "detected_at": "2026-05-24T06:12:00",
                "latitude": 4.1,
                "longitude": 95.1,
                "confidence": "Rendah",
                "brightness": 330.4,
            }
        ]
    )

    assert rows[0]["Nama Wilayah"] == "sample_area"
    assert rows[0]["Satelit"] == "MODIS"


def test_build_excel_file_writes_headers_and_row_values() -> None:
    from io import BytesIO

    from openpyxl import load_workbook

    from app.services.export_service import build_excel_file

    content = build_excel_file(
        [
            {
                "layer_name": "sample_area",
                "source": "MODIS",
                "detected_at": "2026-05-24T06:12:00",
                "latitude": 4.1,
                "longitude": 95.1,
                "confidence": "Rendah",
                "brightness": 330.4,
            }
        ]
    )

    workbook = load_workbook(BytesIO(content))
    sheet = workbook.active

    assert [cell.value for cell in sheet[1]] == [
        "No",
        "Nama Wilayah",
        "Satelit",
        "Tanggal Deteksi",
        "Latitude",
        "Longitude",
        "Kategori FRP",
        "Brightness",
    ]
    assert [cell.value for cell in sheet[2]] == [
        1,
        "sample_area",
        "MODIS",
        "24-05-2026 06:12 WIB",
        4.1,
        95.1,
        "Rendah",
        330.4,
    ]
