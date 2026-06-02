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
