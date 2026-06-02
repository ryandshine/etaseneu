def test_build_stats_returns_total_and_breakdown() -> None:
    from app.services.stats_service import build_stats

    stats = build_stats(
        [
            {"source": "MODIS", "layer_name": "sample_area"},
            {"source": "VIIRS S-NPP", "layer_name": "sample_area"},
            {"source": "MODIS", "layer_name": "sample_area"},
        ]
    )

    assert stats["total"] == 3
    assert stats["by_source"]["MODIS"] == 2
    assert stats["by_source"]["VIIRS S-NPP"] == 1
    assert stats["by_layer"]["sample_area"] == 3
