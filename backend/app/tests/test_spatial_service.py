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


def test_filter_hotspots_by_layers_tiered_perimeter_buffer() -> None:
    from app.services.spatial_service import filter_hotspots_by_layers

    # Polygon boundary is [95.0, 4.0] to [95.2, 4.2]
    hotspots = [
        # Point 1: Inside polygon
        {"latitude": 4.1, "longitude": 95.1, "source": "MODIS", "id": "p1"},
        # Point 2: ~445m outside east border (95.2) -> Bahaya (< 1 km)
        {"latitude": 4.1, "longitude": 95.204, "source": "MODIS", "id": "p2"},
        # Point 3: ~2003m outside east border (95.2) -> Waspada (1–3 km)
        {"latitude": 4.1, "longitude": 95.218, "source": "MODIS", "id": "p3"},
        # Point 4: ~4007m outside east border (95.2) -> Pantau (3–5 km)
        {"latitude": 4.1, "longitude": 95.236, "source": "MODIS", "id": "p4"},
        # Point 5: ~11.1km outside border -> discarded (> 5 km)
        {"latitude": 4.1, "longitude": 95.30, "source": "MODIS", "id": "p5"},
    ]
    layers = [
        {
            "id": "kps_layer",
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
                            "LEMBAGA": "KPS Hutan Sejahtera",
                            "NAMA_PROV": "Aceh",
                        },
                    }
                ],
            },
        }
    ]

    filtered = filter_hotspots_by_layers(hotspots, layers, include_perimeter=True)

    # p5 should be discarded (>5km), leaving p1, p2, p3, p4
    assert len(filtered) == 4

    p1 = next(h for h in filtered if h["id"] == "p1")
    assert p1["is_perimeter"] is False
    assert p1["layer_id"] == "kps_layer"
    assert p1["agency_name"] == "KPS Hutan Sejahtera"

    p2 = next(h for h in filtered if h["id"] == "p2")
    assert p2["is_perimeter"] is True
    assert p2["layer_id"] == "perimeter_threat"
    assert p2["threat_tier"] == "bahaya"
    assert "Bahaya" in p2["threat_label"]
    assert p2["distance_to_kps_m"] < 1000.0
    assert p2["nearest_kps_name"] == "KPS Hutan Sejahtera"

    p3 = next(h for h in filtered if h["id"] == "p3")
    assert p3["is_perimeter"] is True
    assert p3["threat_tier"] == "waspada"
    assert 1000.0 <= p3["distance_to_kps_m"] < 3000.0

    p4 = next(h for h in filtered if h["id"] == "p4")
    assert p4["is_perimeter"] is True
    assert p4["threat_tier"] == "pantau"
    assert 3000.0 <= p4["distance_to_kps_m"] <= 5000.0


def test_filter_hotspots_by_layers_without_perimeter() -> None:
    from app.services.spatial_service import filter_hotspots_by_layers

    hotspots = [
        {"latitude": 4.1, "longitude": 95.1, "source": "MODIS", "id": "inside"},
        {"latitude": 4.1, "longitude": 95.204, "source": "MODIS", "id": "buffer"},
    ]
    layers = [
        {
            "id": "kps_layer",
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
                        "properties": {"LEMBAGA": "KPS Hutan Sejahtera"},
                    }
                ],
            },
        }
    ]

    filtered = filter_hotspots_by_layers(hotspots, layers, include_perimeter=False)
    assert len(filtered) == 1
    assert filtered[0]["id"] == "inside"

