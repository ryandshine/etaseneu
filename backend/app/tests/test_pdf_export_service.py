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
