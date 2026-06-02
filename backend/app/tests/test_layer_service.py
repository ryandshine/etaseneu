import json
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "shp"


def test_layer_service_loads_geojson_layers() -> None:
    from app.services.layer_service import LayerService

    service = LayerService(FIXTURE_DIR)

    layers = service.list_layers()

    assert len(layers) == 1
    assert layers[0].id == "sample_area"
    assert layers[0].name == "sample_area"
    assert layers[0].label == "LPHD NYUAI PENINGUN"
    assert "LPHD NYUAI PENINGUN" in layers[0].agencies
    assert layers[0].feature_count == 1


def test_layer_service_transforms_projected_geojson_to_wgs84(tmp_path) -> None:
    from pyproj import Transformer

    from app.services.layer_service import LayerService

    transformer = Transformer.from_crs("EPSG:4326", "ESRI:54034", always_xy=True)
    ring = [
        (95.0, 4.0),
        (95.2, 4.0),
        (95.2, 4.2),
        (95.0, 4.2),
        (95.0, 4.0),
    ]
    projected_ring = [list(transformer.transform(lon, lat)) + [0.0] for lon, lat in ring]
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:ESRI::54034"}},
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [projected_ring],
                },
            }
        ],
    }
    (tmp_path / "projected.geojson").write_text(json.dumps(payload), encoding="utf-8")

    service = LayerService(tmp_path)
    layers = service.list_layers()

    assert len(layers) == 1
    assert layers[0].bounds.min_lon == pytest.approx(95.0, abs=1e-5)
    assert layers[0].bounds.min_lat == pytest.approx(4.0, abs=1e-5)
    assert layers[0].bounds.max_lon == pytest.approx(95.2, abs=1e-5)
    assert layers[0].bounds.max_lat == pytest.approx(4.2, abs=1e-5)
    assert "crs" not in layers[0].geojson


def test_display_simplification_tolerance_stays_close_to_spatial_boundary() -> None:
    from app.services.layer_service import _display_simplify_tolerance

    assert _display_simplify_tolerance(7000) <= 0.001


def test_layer_service_lists_preview_layers_without_building_full_display(monkeypatch) -> None:
    from app.services.layer_service import LayerService

    service = LayerService(FIXTURE_DIR)

    monkeypatch.setattr(
        "app.services.layer_service._build_display_payload",
        lambda payload: (_ for _ in ()).throw(AssertionError("full display payload should not be built")),
    )

    layers = service.list_preview_layers()

    assert len(layers) == 1
    assert layers[0].geojson_mode == "preview"
    assert len(layers[0].geojson["features"]) == 1


def test_layer_service_preview_layers_preserve_original_shape(tmp_path) -> None:
    from app.services.layer_service import LayerService

    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"LEMBAGA": "Sample Agency"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [100.0, -2.0],
                        [100.4, -1.8],
                        [100.9, -1.9],
                        [101.2, -1.3],
                        [101.0, -0.7],
                        [100.5, -0.5],
                        [100.1, -0.9],
                        [100.0, -2.0],
                    ]],
                },
            }
        ],
    }
    (tmp_path / "sample.geojson").write_text(json.dumps(payload), encoding="utf-8")

    service = LayerService(tmp_path)
    layers = service.list_preview_layers()

    preview_feature = layers[0].geojson["features"][0]
    preview_ring = preview_feature["geometry"]["coordinates"][0]

    assert layers[0].geojson_mode == "preview"
    assert preview_feature["properties"]["label"] == "Sample Agency"
    assert len(preview_ring) > 5
    assert preview_ring != [
        [100.0, -2.0],
        [101.2, -2.0],
        [101.2, -0.5],
        [100.0, -0.5],
        [100.0, -2.0],
    ]
