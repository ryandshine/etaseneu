def test_filter_hotspots_by_layers_keeps_points_inside_polygon_and_tags_layer() -> None:
    from app.services.spatial_service import filter_hotspots_by_layers

    hotspots = [
        {"latitude": 4.1, "longitude": 95.1, "source": "MODIS"},
        {"latitude": 6.0, "longitude": 97.0, "source": "MODIS"},
    ]
    layers = [
        {
            "id": "sample_area",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [95.0, 4.0],
                                    [95.2, 4.0],
                                    [95.2, 4.2],
                                    [95.0, 4.2],
                                    [95.0, 4.0],
                                ]
                            ],
                        },
                        "properties": {
                            "LEMBAGA": "LPHD NYUAI PENINGUN",
                        },
                    }
                ],
            },
        }
    ]

    filtered = filter_hotspots_by_layers(hotspots, layers)

    assert len(filtered) == 1
    assert filtered[0]["latitude"] == 4.1
    assert filtered[0]["layer_id"] == "sample_area"
    assert filtered[0]["layer_name"] == "LPHD NYUAI PENINGUN"
    assert filtered[0]["agency_name"] == "LPHD NYUAI PENINGUN"
    assert filtered[0]["polygon_metadata"]["LEMBAGA"] == "LPHD NYUAI PENINGUN"


def test_filter_hotspots_by_layers_uses_nama_mha_for_hutan_adat_dataset() -> None:
    """Dataset Hutan Adat tidak punya kolom LEMBAGA sama sekali (pakai
    NAMA_MHA/NAMOBJ) -- sebelum alias ini ditambahkan, SELURUH hotspot yang
    jatuh di kawasan Hutan Adat jatuh ke fallback layer["id"] (nama layer
    mentah, mis. "HUTAN_ADAT_APR26" tampil sebagai nama lembaga di laporan),
    padahal datanya sendiri lengkap."""
    from app.services.spatial_service import filter_hotspots_by_layers

    hotspots = [{"latitude": 4.1, "longitude": 95.1, "source": "VIIRS_NOAA21"}]
    layers = [
        {
            "id": "HUTAN_ADAT_APR26",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[95.0, 4.0], [95.2, 4.0], [95.2, 4.2], [95.0, 4.2], [95.0, 4.0]]
                            ],
                        },
                        "properties": {
                            "NAMA_MHA": "MHA Mukim Kunyet",
                            "NAMOBJ": "Mukim Kunyet",
                        },
                    }
                ],
            },
        }
    ]

    filtered = filter_hotspots_by_layers(hotspots, layers)

    assert len(filtered) == 1
    assert filtered[0]["layer_name"] == "MHA Mukim Kunyet"
    assert filtered[0]["agency_name"] == "MHA Mukim Kunyet"
