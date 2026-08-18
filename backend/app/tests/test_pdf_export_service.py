from reportlab.graphics.shapes import Drawing, String

from app.services.pdf_export_service import (
    HOTSPOT_TABLE_COL_WIDTHS,
    create_detailed_hotspot_rows,
    create_pie_chart,
    get_ranked_wilkers,
)


def test_create_pie_chart_supports_multiple_sources() -> None:
    hotspots = [
        {"source": "VIIRS NOAA-20"},
        {"source": "VIIRS S-NPP"},
        {"source": "VIIRS NOAA-20"},
    ]

    drawing = create_pie_chart(hotspots, width=210, height=210)

    assert isinstance(drawing, Drawing)


def test_create_pie_chart_renders_satellite_legend_labels() -> None:
    hotspots = [
        {"source": "VIIRS NOAA-20"},
        {"source": "MODIS"},
        {"source": "VIIRS NOAA-20"},
    ]

    drawing = create_pie_chart(hotspots, width=210, height=210)
    labels = [
        item.text
        for item in drawing.contents
        if isinstance(item, String)
    ]

    assert "VIIRS NOAA-20" in labels
    assert "2 (67%)" in labels
    assert "MODIS" in labels
    assert "1 (33%)" in labels


def test_create_detailed_hotspot_rows_includes_all_filtered_hotspots() -> None:
    hotspots = [
        {
            "layer_name": f"Lembaga {idx}",
            "source": "VIIRS NOAA-20",
            "detected_at": "2026-05-29T05:44:00Z",
            "latitude": 1.23,
            "longitude": 4.56,
            "confidence": "n",
            "brightness": 320.1,
            "frp": 1.2,
        }
        for idx in range(51)
    ]

    rows = create_detailed_hotspot_rows(hotspots)

    assert len(rows) == 52


def test_get_ranked_wilkers_includes_all_wilkers() -> None:
    hotspots = [
        {"polygon_metadata": {"WILKER_BPS": f"Wilker {idx}"}}
        for idx in range(6)
    ]

    ranked = get_ranked_wilkers(hotspots)

    assert len(ranked) == 6


def test_hotspot_table_number_column_is_wide_enough_for_three_digits() -> None:
    assert HOTSPOT_TABLE_COL_WIDTHS[0] >= 30


def test_section_skema_provinsi_renders_crosstab_with_totals() -> None:
    from reportlab.platypus import Table

    from app.services.pdf_export_service import (
        _build_report_styles,
        _section_skema_provinsi,
    )

    hotspots = [
        {"province_name": "Riau", "polygon_metadata": {"SKEMA": "PPHD"}},
        {"province_name": "Riau", "polygon_metadata": {"SKEMA": "PKK"}},
        {"province_name": "Jambi", "polygon_metadata": {"SKEMA": "PPHD"}},
    ]

    story = _section_skema_provinsi(hotspots, _build_report_styles())
    table = next(item for item in story if isinstance(item, Table))
    text = [[cell.getPlainText() for cell in row] for row in table._cellvalues]

    assert text[0][0] == "Provinsi"
    assert text[0][-1] == "Total"
    assert {row[0] for row in text[1:]} == {"Riau", "Jambi", "Total"}
    # Baris terakhir = total keseluruhan, harus sama dengan jumlah hotspot.
    assert text[-1][-1] == "3"


def test_section_skema_provinsi_handles_empty_period() -> None:
    from reportlab.platypus import Table

    from app.services.pdf_export_service import (
        _build_report_styles,
        _section_skema_provinsi,
    )

    story = _section_skema_provinsi([], _build_report_styles())

    assert not any(isinstance(item, Table) for item in story)


def test_skema_table_fits_landscape_a4_print_width() -> None:
    from app.services.pdf_export_service import _skema_col_widths

    for column_count in range(1, 9):
        assert sum(_skema_col_widths(column_count)) == 769.0


_BURNED_REPORT = {
    "rows": [
        {"lembaga": "KOPERASI A", "skema": "PPHKm", "nama_prov": "Riau", "wilker_bps": "BPS Kampar",
         "burned_area_ha": 1786.3, "burned_months": 2, "latest_period": "2026-04", "is_estimated": False},
        {"lembaga": "KT C", "skema": "PPHKm", "nama_prov": "Lampung", "wilker_bps": "BPS Lampung",
         "burned_area_ha": 2.1, "burned_months": 1, "latest_period": "2026-03", "is_estimated": True},
    ],
    "by_skema": [{"skema": "PPHKm", "total_ha": 1788.4, "kps_count": 2}],
    "total_ha": 1788.4,
    "kps_count": 2,
}


def _burned_section_text(report):
    from app.services.pdf_export_service import _build_report_styles, _section_burned_area

    story = _section_burned_area(report, _build_report_styles())
    texts = []
    for item in story:
        text = getattr(item, "text", None)
        if text:
            texts.append(str(text))
        for row in getattr(item, "_cellvalues", []) or []:
            for cell in row:
                cell_text = getattr(cell, "text", None)
                if cell_text:
                    texts.append(str(cell_text))
    return " ".join(texts)


def test_section_burned_area_is_skipped_when_no_data() -> None:
    """Laporan tidak boleh berisi halaman kosong hanya karena fitur luas
    terbakar belum dikonfigurasi atau tidak ada kawasan terbakar."""
    from app.services.pdf_export_service import _build_report_styles, _section_burned_area

    styles = _build_report_styles()

    assert _section_burned_area(None, styles) == []
    assert _section_burned_area({"rows": [], "total_ha": 0, "kps_count": 0}, styles) == []


def test_section_burned_area_lists_kps_and_totals() -> None:
    text = _burned_section_text(_BURNED_REPORT)

    assert "KOPERASI A" in text
    assert "KT C" in text
    # luas per KPS dan baris TOTAL keduanya muncul, dengan pemisah ribuan
    assert "1,786.3" in text
    assert "1,788.4" in text
    # narasi menyebut cakupannya, bukan cuma menempelkan tabel tanpa konteks
    assert "2 kawasan perhutanan sosial" in text


def test_section_burned_area_warns_units_are_not_additive_with_hotspot_counts() -> None:
    """Hektar (citra bulanan, jeda rilis 1-3 bulan) dan jumlah titik panas
    (sinkron tiap 3 jam) bukan besaran sebanding -- laporan harus menyatakan
    itu, bukan menaruh dua angka berdampingan tanpa penjelasan."""
    text = _burned_section_text(_BURNED_REPORT)

    assert "tidak dapat dijumlahkan langsung" in text
    assert "MCD64A1" in text


def test_section_burned_area_marks_estimated_rows() -> None:
    text = _burned_section_text(_BURNED_REPORT)

    assert "Perkiraan lokasi" in text
    assert "Terpetakan" in text


def test_section_burned_area_caps_rows_and_points_to_excel() -> None:
    from app.services.pdf_export_service import BURNED_AREA_TABLE_MAX_ROWS

    many = {
        "rows": [
            {"lembaga": f"KPS {i}", "skema": "PPHD", "nama_prov": "Riau", "wilker_bps": "BPS",
             "burned_area_ha": float(100 - i), "burned_months": 1,
             "latest_period": "2026-04", "is_estimated": False}
            for i in range(BURNED_AREA_TABLE_MAX_ROWS + 5)
        ],
        "by_skema": [{"skema": "PPHD", "total_ha": 1000.0, "kps_count": BURNED_AREA_TABLE_MAX_ROWS + 5}],
        "total_ha": 1000.0,
        "kps_count": BURNED_AREA_TABLE_MAX_ROWS + 5,
    }
    text = _burned_section_text(many)

    # KPS terluas ikut, yang paling kecil terpotong
    assert "KPS 0" in text
    assert f"KPS {BURNED_AREA_TABLE_MAX_ROWS + 4}" not in text
    assert "Luas Terbakar" in text


def test_build_pdf_report_accepts_burned_area_report() -> None:
    from datetime import datetime, timezone

    from app.models.query import HotspotQuery
    from app.services.pdf_export_service import build_pdf_report

    query = HotspotQuery(
        start_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 8, 18, tzinfo=timezone.utc),
        satellites=[],
        active_layers=[],
    )

    with_burned = build_pdf_report(
        hotspots=[], query=query, layers_info=[], burned_area_report=_BURNED_REPORT
    )
    without_burned = build_pdf_report(hotspots=[], query=query, layers_info=[])

    assert with_burned.startswith(b"%PDF")
    assert len(with_burned) > len(without_burned)
