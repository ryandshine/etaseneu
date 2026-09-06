import hashlib
import json

from shapely.geometry import Point, shape

from app.services.geojson_sync_service import _field_value


_spatial_tree_cache: dict[str, tuple[list[dict], object]] = {}


def distance_to_perimeter_tier(dist_m: float) -> tuple[str, str]:
    """Mengembalikan (threat_tier, threat_label) berdasarkan jarak buffer dari batas KPS.
    - Ring 1 (< 1 km): Bahaya Kritis (Red)
    - Ring 2 (1–3 km): Waspada (Orange)
    - Ring 3 (3–5 km): Pantau (Yellow)
    """
    if dist_m < 1000.0:
        return "bahaya", "Bahaya Kritis (< 1 km)"
    if dist_m < 3000.0:
        return "waspada", "Waspada (1–3 km)"
    return "pantau", "Pantau (3–5 km)"


def filter_hotspots_by_layers(
    hotspots: list[dict],
    layers: list[dict],
    include_perimeter: bool = True,
    max_perimeter_m: float = 5000.0,
) -> list[dict]:
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

    # 1 derajat ~ 111.320 meter
    max_deg = max_perimeter_m / 111320.0
    filtered: list[dict] = []
    for hotspot in hotspots:
        point = Point(hotspot["longitude"], hotspot["latitude"])
        indices = tree.query(point)
        inside_layer = None
        for idx in indices:
            cand = prepared_layers[idx]
            if cand["geometry"].covers(point):
                inside_layer = cand
                break

        if inside_layer is not None:
            filtered.append(
                {
                    **hotspot,
                    "layer_id": inside_layer["id"],
                    "layer_name": inside_layer["name"],
                    "agency_name": inside_layer["name"],
                    "province_name": inside_layer["province_name"],
                    "polygon_metadata": inside_layer["metadata"],
                    "is_perimeter": False,
                }
            )
            continue

        if include_perimeter:
            perimeter_candidates = tree.query(point.buffer(max_deg))
            if len(perimeter_candidates) > 0:
                min_dist_deg = float("inf")
                nearest_layer = None
                for idx in perimeter_candidates:
                    cand = prepared_layers[idx]
                    d_deg = cand["geometry"].distance(point)
                    if d_deg < min_dist_deg:
                        min_dist_deg = d_deg
                        nearest_layer = cand

                if nearest_layer is not None and min_dist_deg <= max_deg:
                    dist_m = min_dist_deg * 111320.0
                    tier_key, tier_label = distance_to_perimeter_tier(dist_m)
                    filtered.append(
                        {
                            **hotspot,
                            "layer_id": "perimeter_threat",
                            "layer_name": f"Ancaman Buffer {nearest_layer['name']}",
                            "agency_name": f"Luar Kawasan ({nearest_layer['name']})",
                            "province_name": nearest_layer["province_name"],
                            "polygon_metadata": {},
                            "is_perimeter": True,
                            "distance_to_kps_m": round(dist_m, 1),
                            "threat_tier": tier_key,
                            "threat_level": tier_key,
                            "threat_label": tier_label,
                            "nearest_kps_id": nearest_layer["id"],
                            "nearest_kps_name": nearest_layer["name"],
                        }
                    )

    return filtered


def _prepare_layers(layers: list[dict]) -> list[dict]:
    prepared_layers: list[dict] = []

    for layer in layers:
        for feature_index, feature in enumerate(layer.get("geojson", {}).get("features", [])):
            geometry = feature.get("geometry")
            if geometry is None:
                continue

            properties = feature.get("properties") or {}
            # NAMA_MHA/NAMOBJ dipakai dataset Hutan Adat (kolom LEMBAGA-nya
            # tidak ada sama sekali) -- tanpa alias ini, seluruh hotspot yang
            # jatuh di kawasan Hutan Adat jatuh ke fallback layer["id"] (mis.
            # "HUTAN_ADAT_APR26" tampil sebagai nama lembaga di laporan),
            # padahal datanya sendiri lengkap. Sama pola dengan _field_value
            # yang sudah dipakai geojson_sync_service.py untuk sinkronisasi
            # KPS -- di sini dipakai lagi untuk pencocokan hotspot langsung.
            label = _field_value(
                properties, "LEMBAGA", "lembaga", "NAMA_MHA", "NAMOBJ", "NAMA_KEC", "NAMA_KAB"
            ) or layer["id"]
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
