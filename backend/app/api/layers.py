from fastapi import APIRouter, Header, Query
from fastapi import HTTPException

from app.core.auth import verify_admin_key
from app.core.config import get_settings
from app.models.layers import LayerFeature
from app.services.layer_service import get_layer_service


router = APIRouter()


@router.get("/layers")
async def list_layers(
    view: str | None = Query(default=None),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, object]:
    settings = get_settings()

    # Mode preview (geometry disederhanakan) memang dipakai peta publik saat
    # halaman dibuka, jadi harus tetap terbuka. Mode penuh tidak dipakai
    # frontend sama sekali, mengirim geometry presisi asli, dan list_layers()
    # ikut menulis ke database + memicu sync -- bukan sesuatu yang boleh
    # dipicu pengunjung anonim.
    if view != "preview":
        verify_admin_key(x_admin_key)

    service = get_layer_service(str(settings.resolved_shp_dir))
    layers = service.list_preview_layers() if view == "preview" else service.list_layers()
    return {"count": len(layers), "layers": [layer.model_dump() for layer in layers]}


@router.get("/layers/{layer_id}")
async def get_layer(
    layer_id: str,
    view: str | None = Query(default=None),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, object]:
    # Endpoint ini tidak dipakai frontend; apa pun mode-nya ia memanggil
    # list_layers() di baliknya (geometry penuh + tulis database).
    verify_admin_key(x_admin_key)

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
