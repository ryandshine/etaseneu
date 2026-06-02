import json
from functools import lru_cache
from pathlib import Path

from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform

from app.core.config import get_settings
from app.models.layers import LayerBounds, LayerFeature
from app.services.geojson_sync_service import GeoJsonSyncService
from app.services.postgres_store import PostgresStore


LAYER_COLORS = ["#1d4ed8", "#059669", "#dc2626", "#d97706", "#7c3aed"]


def _friendly_layer_name(layer_id: str) -> str:
    if layer_id == "PS_FEB_26":
        return "Perhutanan Sosial"
    return layer_id


def _friendly_layer_label(layer_id: str, agencies: list[str]) -> str:
    if layer_id == "PS_FEB_26":
        return "Perhutanan Sosial"
    return agencies[0] if agencies else layer_id


class LayerService:
    def __init__(self, shp_dir: Path) -> None:
        self.shp_dir = shp_dir
        self._layers_cache: list[LayerFeature] | None = None
        self._preview_layers_cache: list[LayerFeature] | None = None
        self._spatial_layers_cache: list[dict] | None = None
        self.postgres_store = PostgresStore(get_settings().database_url)
        self.geojson_sync_service = GeoJsonSyncService(self.shp_dir, get_settings().database_url)

    def list_layers(self) -> list[LayerFeature]:
        if self._layers_cache is not None:
            return self._layers_cache

        layers: list[LayerFeature] = []

        for index, path in enumerate(sorted(self.shp_dir.glob("*.geojson"))):
            payload = json.loads(path.read_text(encoding="utf-8"))
            source_crs = _extract_crs_name(payload)
            source_bounds = _build_source_bounds(payload)
            bounds = _transform_bounds(source_bounds, source_crs)
            normalized = self._normalize_payload(payload)
            layer_id = path.stem
            color = LAYER_COLORS[index % len(LAYER_COLORS)]
            agencies = _extract_agencies(payload)

            friendly_name = _friendly_layer_name(layer_id)
            friendly_label = _friendly_layer_label(layer_id, agencies)

            layers.append(
                LayerFeature(
                    id=layer_id,
                    name=friendly_name,
                    label=friendly_label,
                    color=color,
                    active=True,
                    feature_count=len(payload.get("features", [])),
                    bounds=bounds,
                    geojson=_build_display_payload(normalized),
                    geojson_mode="full",
                    agencies=agencies,
                )
            )
            self._sync_layer_to_database(
                layer_key=layer_id,
                layer_name=friendly_name,
                layer_label=friendly_label,
                feature_count=len(payload.get("features", [])),
                bounds=bounds.model_dump(),
                agencies=agencies,
                display_geojson=_build_display_payload(normalized),
                spatial_geojson=normalized,
            )

        try:
            self.geojson_sync_service.sync_all()
        except Exception:
            pass
        self._layers_cache = layers
        return layers

    def list_preview_layers(self) -> list[LayerFeature]:
        if self._preview_layers_cache is not None:
            return self._preview_layers_cache

        layers: list[LayerFeature] = []

        for index, path in enumerate(sorted(self.shp_dir.glob("*.geojson"))):
            payload = json.loads(path.read_text(encoding="utf-8"))
            source_crs = _extract_crs_name(payload)
            source_bounds = _build_source_bounds(payload)
            bounds = _transform_bounds(source_bounds, source_crs)
            layer_id = path.stem
            color = LAYER_COLORS[index % len(LAYER_COLORS)]
            agencies = _extract_agencies(payload)

            friendly_name = _friendly_layer_name(layer_id)
            friendly_label = _friendly_layer_label(layer_id, agencies)

            layers.append(
                LayerFeature(
                    id=layer_id,
                    name=friendly_name,
                    label=friendly_label,
                    color=color,
                    active=True,
                    feature_count=len(payload.get("features", [])),
                    bounds=bounds,
                    geojson=_build_preview_payload(bounds),
                    geojson_mode="preview",
                    agencies=agencies,
                )
            )

        self._preview_layers_cache = layers
        return layers

    def get_layer(self, layer_id: str) -> LayerFeature | None:
        for layer in self.list_layers():
            if layer.id == layer_id:
                return layer
        return None

    def bounds_for_layer_ids(self, layer_ids: list[str]) -> LayerBounds | None:
        selected = [layer.bounds for layer in self.list_layers() if layer.id in layer_ids]
        if not selected:
            return None

        return LayerBounds(
            min_lat=min(layer.min_lat for layer in selected),
            min_lon=min(layer.min_lon for layer in selected),
            max_lat=max(layer.max_lat for layer in selected),
            max_lon=max(layer.max_lon for layer in selected),
        )

    def spatial_layers_for_ids(self, layer_ids: list[str]) -> list[dict]:
        if self._spatial_layers_cache is None:
            self._spatial_layers_cache = self._load_spatial_layers()

        if self._spatial_layers_cache is None:
            return []

        return [layer for layer in self._spatial_layers_cache if layer["id"] in layer_ids]

    def _load_spatial_layers(self) -> list[dict]:
        spatial_layers: list[dict] = []

        for index, path in enumerate(sorted(self.shp_dir.glob("*.geojson"))):
            payload = json.loads(path.read_text(encoding="utf-8"))
            normalized = self._normalize_payload(payload)
            bounds = self._build_bounds(normalized)
            layer_id = path.stem
            color = LAYER_COLORS[index % len(LAYER_COLORS)]
            agencies = _extract_agencies(payload)

            friendly_name = _friendly_layer_name(layer_id)
            friendly_label = _friendly_layer_label(layer_id, agencies)

            spatial_layers.append(
                {
                    "id": layer_id,
                    "name": friendly_name,
                    "label": friendly_label,
                    "color": color,
                    "active": True,
                    "feature_count": len(normalized.get("features", [])),
                    "bounds": bounds.model_dump(),
                    "geojson": normalized,
                    "agencies": agencies,
                }
            )

        return spatial_layers

    def _sync_layer_to_database(
        self,
        *,
        layer_key: str,
        layer_name: str,
        layer_label: str,
        feature_count: int,
        bounds: dict,
        agencies: list[str],
        display_geojson: dict,
        spatial_geojson: dict,
    ) -> None:
        if not self.postgres_store.enabled:
            return

        try:
            state = self.postgres_store.layer_sync_state(layer_key)
            if state is not None:
                current_feature_count = int(state.get("feature_count", -1))
                current_label = str(state.get("layer_label", ""))
                if current_feature_count == feature_count and current_label == layer_label:
                    return
            self.postgres_store.upsert_layer(
                layer_key=layer_key,
                layer_name=layer_name,
                layer_label=layer_label,
                feature_count=feature_count,
                bounds=bounds,
                agencies=agencies,
                display_geojson=display_geojson,
                spatial_geojson=spatial_geojson,
            )
        except Exception:
            pass

    def _normalize_payload(self, payload: dict) -> dict:
        source_crs = _extract_crs_name(payload)
        if _is_wgs84(source_crs):
            return payload

        normalized = {**payload}
        normalized.pop("crs", None)
        normalized["features"] = [
            {
                **feature,
                "geometry": _transform_geometry(feature.get("geometry"), source_crs),
            }
            for feature in payload.get("features", [])
        ]
        return normalized

    def _build_bounds(self, payload: dict) -> LayerBounds:
        geometries = [
            feature["geometry"]
            for feature in payload.get("features", [])
            if feature.get("geometry") is not None
        ]

        if not geometries:
            return LayerBounds(min_lat=0.0, min_lon=0.0, max_lat=0.0, max_lon=0.0)

        min_lon: float | None = None
        min_lat: float | None = None
        max_lon: float | None = None
        max_lat: float | None = None

        for geometry in geometries:
            geom_min_lon, geom_min_lat, geom_max_lon, geom_max_lat = shape(geometry).bounds
            min_lon = geom_min_lon if min_lon is None else min(min_lon, geom_min_lon)
            min_lat = geom_min_lat if min_lat is None else min(min_lat, geom_min_lat)
            max_lon = geom_max_lon if max_lon is None else max(max_lon, geom_max_lon)
            max_lat = geom_max_lat if max_lat is None else max(max_lat, geom_max_lat)

        return LayerBounds(
            min_lat=min_lat or 0.0,
            min_lon=min_lon or 0.0,
            max_lat=max_lat or 0.0,
            max_lon=max_lon or 0.0,
        )


def _extract_crs_name(payload: dict) -> str:
    crs = payload.get("crs") or {}
    properties = crs.get("properties") or {}
    return str(properties.get("name", "EPSG:4326"))


def _is_wgs84(crs_name: str) -> bool:
    normalized = crs_name.upper()
    return normalized in {"EPSG:4326", "CRS84", "URN:OGC:DEF:CRS:OGC:1.3:CRS84"}


def _transform_geometry(geometry: dict | None, source_crs: str) -> dict | None:
    if geometry is None:
        return None

    transformer = _build_transformer(source_crs)
    transformed = transform(transformer.transform, shape(geometry))
    return mapping(transformed)


@lru_cache(maxsize=16)
def _build_transformer(source_crs: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(source_crs), CRS.from_epsg(4326), always_xy=True)


def _build_display_payload(payload: dict) -> dict:
    features = payload.get("features", [])
    tolerance = _display_simplify_tolerance(len(features))
    display_features: list[dict] = []

    for feature in features:
        geometry = feature.get("geometry")
        if geometry is None:
            continue

        properties = feature.get("properties") or {}
        label = (
            properties.get("LEMBAGA")
            or properties.get("lembaga")
            or properties.get("NAMA_KEC")
            or properties.get("NAMA_KAB")
            or properties.get("name")
            or ""
        )
        display_features.append(
            {
                "type": "Feature",
                "properties": {"label": str(label)},
                "geometry": _simplify_geometry(geometry, tolerance),
            }
        )

    return {
        "type": "FeatureCollection",
        "features": display_features,
    }


def _display_simplify_tolerance(feature_count: int) -> float:
    if feature_count >= 7000:
        return 0.001
    if feature_count >= 3000:
        return 0.001
    if feature_count >= 1000:
        return 0.001
    return 0.0003


def _simplify_geometry(geometry: dict, tolerance: float) -> dict:
    simplified = shape(geometry).simplify(tolerance=tolerance, preserve_topology=True)
    return mapping(simplified)


def _build_preview_payload(bounds: LayerBounds) -> dict:
    return {
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


def _extract_agencies(payload: dict) -> list[str]:
    agencies: list[str] = []
    seen: set[str] = set()

    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        agency = (
            properties.get("LEMBAGA")
            or properties.get("lembaga")
            or properties.get("NAMA_KEC")
            or properties.get("NAMA_KAB")
        )
        if not agency:
            continue
        agency_name = str(agency).strip()
        if not agency_name or agency_name in seen:
            continue
        seen.add(agency_name)
        agencies.append(agency_name)

    return agencies


def _build_source_bounds(payload: dict) -> LayerBounds:
    geometries = [
        feature["geometry"]
        for feature in payload.get("features", [])
        if feature.get("geometry") is not None
    ]

    if not geometries:
        return LayerBounds(min_lat=0.0, min_lon=0.0, max_lat=0.0, max_lon=0.0)

    min_lon: float | None = None
    min_lat: float | None = None
    max_lon: float | None = None
    max_lat: float | None = None

    for geometry in geometries:
        geom_min_lon, geom_min_lat, geom_max_lon, geom_max_lat = shape(geometry).bounds
        min_lon = geom_min_lon if min_lon is None else min(min_lon, geom_min_lon)
        min_lat = geom_min_lat if min_lat is None else min(min_lat, geom_min_lat)
        max_lon = geom_max_lon if max_lon is None else max(max_lon, geom_max_lon)
        max_lat = geom_max_lat if max_lat is None else max(max_lat, geom_max_lat)

    return LayerBounds(
        min_lat=min_lat or 0.0,
        min_lon=min_lon or 0.0,
        max_lat=max_lat or 0.0,
        max_lon=max_lon or 0.0,
    )


def _transform_bounds(bounds: LayerBounds, source_crs: str) -> LayerBounds:
    if _is_wgs84(source_crs):
        return bounds

    transformer = _build_transformer(source_crs)
    min_lon, min_lat = transformer.transform(bounds.min_lon, bounds.min_lat)
    max_lon, max_lat = transformer.transform(bounds.max_lon, bounds.max_lat)
    return LayerBounds(
        min_lat=min(min_lat, max_lat),
        min_lon=min(min_lon, max_lon),
        max_lat=max(min_lat, max_lat),
        max_lon=max(min_lon, max_lon),
    )


@lru_cache(maxsize=8)
def get_layer_service(shp_dir: str) -> LayerService:
    return LayerService(Path(shp_dir))
