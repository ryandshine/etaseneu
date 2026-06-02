from fastapi import APIRouter, Query
from fastapi import HTTPException

from app.core.config import get_settings
from app.models.layers import LayerFeature
from app.services.layer_service import get_layer_service


router = APIRouter()


@router.get("/layers")
async def list_layers(view: str | None = Query(default=None)) -> dict[str, object]:
    settings = get_settings()
    service = get_layer_service(str(settings.resolved_shp_dir))
    layers = service.list_layers()
    if view == "preview":
        layers = [_to_preview_layer(layer) for layer in layers]
    return {"count": len(layers), "layers": [layer.model_dump() for layer in layers]}


@router.get("/layers/{layer_id}")
async def get_layer(layer_id: str, view: str | None = Query(default=None)) -> dict[str, object]:
    settings = get_settings()
    service = get_layer_service(str(settings.resolved_shp_dir))
    layer = service.get_layer(layer_id)
    if layer is None:
        raise HTTPException(status_code=404, detail="Layer not found")
    if view == "preview":
        layer = _to_preview_layer(layer)
    return layer.model_dump()


def _to_preview_layer(layer: LayerFeature) -> LayerFeature:
    bounds = layer.bounds
    preview_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [bounds.min_lon, bounds.min_lat],
                            [bounds.max_lon, bounds.min_lat],
                            [bounds.max_lon, bounds.max_lat],
                            [bounds.min_lon, bounds.max_lat],
                            [bounds.min_lon, bounds.min_lat],
                        ]
                    ],
                },
            }
        ],
    }
    return layer.model_copy(update={"geojson": preview_geojson, "geojson_mode": "preview"})
