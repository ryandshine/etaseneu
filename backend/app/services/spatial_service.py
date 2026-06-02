import hashlib
import json

from shapely.geometry import Point, shape


_spatial_tree_cache: dict[str, tuple[list[dict], object]] = {}


def filter_hotspots_by_layers(hotspots: list[dict], layers: list[dict]) -> list[dict]:
    if not layers:
        return []

    keys = []
    for layer in layers:
        features = layer.get("geojson", {}).get("features", [])
        sig = f"{len(features)}"
        if features:
            f = features[0]
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            sig += f"_{geom.get('type')}_{props.get('LEMBAGA') or props.get('lembaga') or ''}"
        keys.append(f"{layer['id']}:{sig}")
    cache_key = ",".join(sorted(keys))

    from shapely.strtree import STRtree

    if cache_key not in _spatial_tree_cache:
        prepared_layers = _prepare_layers(layers)
        if prepared_layers:
            geoms = [layer["geometry"] for layer in prepared_layers]
            tree = STRtree(geoms)
            _spatial_tree_cache[cache_key] = (prepared_layers, tree)
        else:
            _spatial_tree_cache[cache_key] = ([], None)

    prepared_layers, tree = _spatial_tree_cache[cache_key]
    if not prepared_layers or tree is None:
        return []

    filtered: list[dict] = []
    for hotspot in hotspots:
        point = Point(hotspot["longitude"], hotspot["latitude"])
        indices = tree.query(point)
        for idx in indices:
            layer = prepared_layers[idx]
            if layer["geometry"].covers(point):
                filtered.append(
                    {
                        **hotspot,
                        "layer_id": layer["id"],
                        "layer_name": layer["name"],
                        "agency_name": layer["name"],
                        "province_name": layer["province_name"],
                        "polygon_metadata": layer["metadata"],
                    }
                )
                break

    return filtered


def _prepare_layers(layers: list[dict]) -> list[dict]:
    prepared_layers: list[dict] = []

    for layer in layers:
        for feature_index, feature in enumerate(layer.get("geojson", {}).get("features", [])):
            geometry = feature.get("geometry")
            if geometry is None:
                continue

            properties = feature.get("properties") or {}
            label = (
                properties.get("LEMBAGA")
                or properties.get("lembaga")
                or properties.get("NAMA_KEC")
                or properties.get("NAMA_KAB")
                or layer["id"]
            )
            province_name = str(
                properties.get("NAMA_PROV")
                or properties.get("NAMA_PROVINSI")
                or properties.get("PROVINSI")
                or ""
            )
            metadata = _extract_polygon_metadata(properties)
            metadata["feature_key"] = _feature_key(str(layer["id"]), feature)
            metadata["layer_key"] = str(layer["id"])
            metadata["feature_index"] = feature_index

            prepared_layers.append(
                {
                    "id": layer["id"],
                    "name": str(label),
                    "geometry": shape(geometry),
                    "province_name": province_name,
                    "metadata": metadata,
                    "feature_index": feature_index,
                }
            )

    return prepared_layers


def _extract_polygon_metadata(properties: dict) -> dict[str, str]:
    selected_fields = [
        "OBJECTID_1",
        "KODE_PROV",
        "KODE_KAB",
        "PS_ID",
        "SKEMA",
        "LEMBAGA",
        "NAMA_PROV",
        "NAMA_KAB",
        "NAMA_KEC",
        "NAMA_DESA",
        "NO_SK",
        "TGL_SK",
        "Luas_HK",
        "LUAS_HL",
        "LUAS_HPT",
        "LUAS_HP",
        "LUAS_HPK",
        "Status",
        "WILKER_BPS",
        "LUAS_SK",
        "Luas_Poli",
        "KETERANGAN",
        "Keliling",
        "Shape_Leng",
        "Shape_Area",
        "LuasFinal",
        "Jml_KK",
    ]
    metadata: dict[str, str] = {}

    for field in selected_fields:
        value = properties.get(field)
        if value is None or value == "":
            continue
        metadata[field] = str(value)

    return metadata


def _feature_key(layer_key: str, feature: dict) -> str:
    canonical = json.dumps(
        {
            "layer_key": layer_key,
            "geometry": feature.get("geometry"),
            "properties": feature.get("properties") or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
