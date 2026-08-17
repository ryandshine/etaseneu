from app.services.skema_stats import (
    build_skema_provinsi_matrix,
    collapse_skema_columns,
    count_per_skema,
)


def _hotspot(provinsi: str, skema: str | None) -> dict:
    metadata: dict = {"NAMA_PROV": provinsi}
    if skema is not None:
        metadata["SKEMA"] = skema
    return {"polygon_metadata": metadata}


def test_count_per_skema_orders_by_count_descending() -> None:
    hotspots = [
        _hotspot("Riau", "PPHD"),
        _hotspot("Riau", "PPHKm"),
        _hotspot("Jambi", "PPHKm"),
    ]

    assert count_per_skema(hotspots) == [("PPHKm", 2), ("PPHD", 1)]


def test_matrix_counts_each_province_scheme_pair() -> None:
    hotspots = [
        _hotspot("Riau", "PPHD"),
        _hotspot("Riau", "PPHD"),
        _hotspot("Riau", "PPHD"),
        _hotspot("Riau", "PKK"),
        _hotspot("Jambi", "PKK"),
    ]

    matrix = build_skema_provinsi_matrix(hotspots)

    # Kolom & baris diurutkan dari jumlah terbanyak.
    assert matrix.skema == ("PPHD", "PKK")
    assert matrix.rows[0].provinsi == "Riau"
    assert matrix.rows[0].counts == (3, 1)
    assert matrix.rows[0].total == 4
    assert matrix.rows[1].provinsi == "Jambi"
    assert matrix.rows[1].counts == (0, 1)
    assert matrix.totals == (3, 2)
    assert matrix.grand_total == 5


def test_matrix_keeps_points_whose_polygon_has_no_skema() -> None:
    matrix = build_skema_provinsi_matrix([_hotspot("Riau", None), _hotspot("Riau", "PPHD")])

    assert "Tanpa Skema" in matrix.skema
    assert matrix.grand_total == 2


def test_matrix_uses_spatial_join_province_before_shapefile_property() -> None:
    hotspot = {"province_name": "Kalimantan Barat", "polygon_metadata": {"NAMA_PROV": "Riau"}}

    matrix = build_skema_provinsi_matrix([hotspot])

    assert matrix.rows[0].provinsi == "Kalimantan Barat"


def test_collapse_skema_columns_merges_the_tail_without_losing_totals() -> None:
    hotspots = [_hotspot("Riau", f"SKEMA-{index}") for index in range(5)]

    collapsed = collapse_skema_columns(build_skema_provinsi_matrix(hotspots), 3)

    assert len(collapsed.skema) == 3
    assert collapsed.skema[-1] == "Lainnya"
    assert collapsed.rows[0].counts == (1, 1, 3)
    assert collapsed.rows[0].total == 5
    assert collapsed.grand_total == 5


def test_collapse_skema_columns_is_a_noop_when_columns_fit() -> None:
    matrix = build_skema_provinsi_matrix([_hotspot("Riau", "PPHD")])

    assert collapse_skema_columns(matrix, 8) == matrix
