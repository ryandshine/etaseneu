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


def test_hotspot_table_col_widths_fit_a4_landscape_and_match_headers() -> None:
    header_row = create_detailed_hotspot_rows([])[0]
    assert len(HOTSPOT_TABLE_COL_WIDTHS) == len(header_row)
    assert sum(HOTSPOT_TABLE_COL_WIDTHS) == 769


def test_create_detailed_hotspot_rows_includes_fungsi_kawasan_column() -> None:
    rows = create_detailed_hotspot_rows(
        [
            {
                "layer_name": "LPHD X",
                "source": "MODIS",
                "detected_at": "2026-05-29T05:44:00Z",
                "latitude": 1.0,
                "longitude": 2.0,
                "kawasan_hutan": {"fungsi": "Hutan Produksi Tetap", "kelompok": "Produksi"},
            },
            {
                "layer_name": "LPHD Y",
                "source": "MODIS",
                "detected_at": "2026-05-29T05:44:00Z",
                "latitude": 1.0,
                "longitude": 2.0,
            },
        ]
    )

    assert rows[0][-1] == "Fungsi Kawasan"
    assert rows[1][-1] == "Hutan Produksi Tetap"
    assert rows[2][-1] == "-"


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
    """Hektar (rekap resmi KLHK, tanpa jadwal tetap) dan jumlah titik panas
    (sinkron tiap 3 jam) bukan besaran sebanding -- laporan harus menyatakan
    itu, bukan menaruh dua angka berdampingan tanpa penjelasan."""
    text = _burned_section_text(_BURNED_REPORT)

    assert "tidak dapat dijumlahkan langsung" in text
    assert "KLHK" in text


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


def test_create_burned_area_bar_chart_scales_row_count_dynamically() -> None:
    """Beda dari create_bar_chart_drawing() yang hardcode 3 baris (Confidence/
    FRP selalu 3 kategori) -- jumlah skema perhutanan sosial bervariasi, jadi
    chart ini harus tetap membuat satu batang per data point, bukan diam-diam
    memotong atau menumpuk kalau jumlahnya bukan 3."""
    from app.services.pdf_export_service import create_burned_area_bar_chart

    two_bars = create_burned_area_bar_chart([("PPHKm", 2227.4), ("PPHD", 1771.9)], "Judul")
    five_bars = create_burned_area_bar_chart(
        [("PPHD", 100.0), ("PPHKm", 80.0), ("PPHTR", 40.0), ("PPHA", 20.0), ("PPKKPS", 10.0)],
        "Judul",
    )

    def _rect_count(drawing):
        from reportlab.graphics.shapes import Rect

        return sum(1 for item in drawing.contents if isinstance(item, Rect))

    # 1 rect latar + N rect batang (batang bernilai 0 tidak digambar, tapi di
    # sini semua nilai > 0)
    assert _rect_count(two_bars) == 1 + 2
    assert _rect_count(five_bars) == 1 + 5


def test_create_burned_area_bar_chart_handles_empty_data() -> None:
    from app.services.pdf_export_service import create_burned_area_bar_chart

    drawing = create_burned_area_bar_chart([], "Judul")
    assert drawing is not None


def test_section_burned_area_includes_chart_before_table() -> None:
    from reportlab.graphics.shapes import Drawing
    from reportlab.platypus import Table

    from app.services.pdf_export_service import _build_report_styles, _section_burned_area

    story = _section_burned_area(_BURNED_REPORT, _build_report_styles())

    drawing_index = next(i for i, item in enumerate(story) if isinstance(item, Drawing))
    table_index = next(i for i, item in enumerate(story) if isinstance(item, Table))
    assert drawing_index < table_index


def _make_hotspot(frp: float, idx: int) -> dict:
    return {
        "layer_name": f"KPS {idx}",
        "source": "MODIS",
        "detected_at": "2026-05-29T05:44:00Z",
        "latitude": 1.0 + idx * 0.001,
        "longitude": 100.0 + idx * 0.001,
        "confidence": "n",
        "brightness": 320.1,
        "frp": frp,
    }


def test_section_detailed_table_caps_rows_for_large_datasets() -> None:
    """reportlab Table dengan puluhan ribu baris butuh lebih dari 2 menit
    untuk di-layout (ditemukan: 16.872 baris = ~148 detik, cukup untuk bikin
    seluruh permintaan PDF timeout di reverse proxy manapun). Harus dibatasi
    HOTSPOT_DETAIL_TABLE_MAX_ROWS, bukan menyertakan semuanya."""
    from app.services.pdf_export_service import (
        HOTSPOT_DETAIL_TABLE_MAX_ROWS,
        _build_report_styles,
        _section_detailed_table,
    )
    from reportlab.platypus import Table

    hotspots = [_make_hotspot(frp=float(i), idx=i) for i in range(HOTSPOT_DETAIL_TABLE_MAX_ROWS + 50)]

    story = _section_detailed_table(hotspots, _build_report_styles())
    table = next(item for item in story if isinstance(item, Table))

    # -1 baris header
    assert len(table._cellvalues) - 1 == HOTSPOT_DETAIL_TABLE_MAX_ROWS


def test_section_detailed_table_sorts_by_frp_descending_when_truncated() -> None:
    from app.services.pdf_export_service import (
        HOTSPOT_DETAIL_TABLE_MAX_ROWS,
        _build_report_styles,
        _section_detailed_table,
    )
    from reportlab.platypus import Table

    hotspots = [_make_hotspot(frp=float(i), idx=i) for i in range(HOTSPOT_DETAIL_TABLE_MAX_ROWS + 50)]

    story = _section_detailed_table(hotspots, _build_report_styles())
    table = next(item for item in story if isinstance(item, Table))

    first_data_row = table._cellvalues[1]
    frp_cell = first_data_row[9]
    # kolom FRP -- yang tertinggi (idx terbesar) harus muncul duluan
    assert frp_cell.getPlainText() == f"{float(HOTSPOT_DETAIL_TABLE_MAX_ROWS + 49):.2f}"


def test_section_detailed_table_shows_truncation_note_when_over_limit() -> None:
    from app.services.pdf_export_service import (
        HOTSPOT_DETAIL_TABLE_MAX_ROWS,
        _build_report_styles,
        _section_detailed_table,
    )

    hotspots = [_make_hotspot(frp=float(i), idx=i) for i in range(HOTSPOT_DETAIL_TABLE_MAX_ROWS + 50)]

    story = _section_detailed_table(hotspots, _build_report_styles())
    texts = [getattr(item, "text", "") for item in story]

    assert any("Menampilkan" in text and "Excel" in text for text in texts)
    assert any(f"{HOTSPOT_DETAIL_TABLE_MAX_ROWS:,}" in text for text in texts)


def test_section_detailed_table_no_truncation_note_when_under_limit() -> None:
    from app.services.pdf_export_service import _build_report_styles, _section_detailed_table
    from reportlab.platypus import Table

    hotspots = [_make_hotspot(frp=float(i), idx=i) for i in range(10)]

    story = _section_detailed_table(hotspots, _build_report_styles())
    texts = [getattr(item, "text", "") for item in story]
    table = next(item for item in story if isinstance(item, Table))

    assert not any("Menampilkan" in text for text in texts)
    assert len(table._cellvalues) - 1 == 10
