from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform

from app.services.postgres_store import PostgresStore


def _extract_crs_name(payload: dict) -> str:
    crs = payload.get("crs") or {}
    properties = crs.get("properties") or {}
    return str(properties.get("name", "EPSG:4326"))


def _is_wgs84(crs_name: str) -> bool:
    normalized = crs_name.upper()
    return normalized in {"EPSG:4326", "CRS84", "URN:OGC:DEF:CRS:OGC:1.3:CRS84"}


@lru_cache(maxsize=16)
def _build_transformer(source_crs: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(source_crs), CRS.from_epsg(4326), always_xy=True)


def _transform_geometry(geometry: dict | None, source_crs: str) -> dict | None:
    if geometry is None:
        return None

    transformer = _build_transformer(source_crs)
    transformed = transform(transformer.transform, shape(geometry))
    return mapping(transformed)



class GeoJsonSyncService:
    def __init__(
        self,
        shp_dir: Path,
        database_url: str,
        postgres_store: PostgresStore | None = None,
    ) -> None:
        self.shp_dir = Path(shp_dir)
        self.database_url = database_url.strip()
        self.postgres_store = postgres_store or PostgresStore(self.database_url)

    @property
    def enabled(self) -> bool:
        return self.postgres_store.enabled

    def status(self) -> dict[str, object]:
        if not self.enabled:
            return {
                "database_enabled": False,
                "database_url_present": False,
                "count": 0,
                "active_count": 0,
                "inactive_count": 0,
                "files": [],
            }

        registry = self.postgres_store.geojson_registry_status()
        return {
            "database_enabled": True,
            "database_url_present": True,
            **registry,
        }

    def sync_all(self) -> dict[str, object]:
        summary = {
            "files_scanned": 0,
            "files_changed": 0,
            "files_unchanged": 0,
            "files_inactive": 0,
            "features_upserted": 0,
            "features_deactivated": 0,
            "files": [],
        }

        if not self.enabled:
            return summary

        seen_file_names: set[str] = set()
        existing_registry = {
            row["file_name"]: row for row in self.postgres_store.read_geojson_file_registry_all()
        }

        for path in sorted(self.shp_dir.glob("*.geojson")):
            result = self.sync_file(path)
            seen_file_names.add(path.name)
            summary["files_scanned"] += 1
            summary["files_changed"] += int(bool(result["changed"]))
            summary["files_unchanged"] += int(not result["changed"])
            summary["features_upserted"] += int(result["features_upserted"])
            summary["features_deactivated"] += int(result["features_deactivated"])
            summary["files"].append(result)

        for file_name, row in existing_registry.items():
            if file_name in seen_file_names or row.get("is_active", True) is False:
                continue
            if self.postgres_store.deactivate_geojson_file_registry(file_name):
                summary["files_inactive"] += 1

        return summary

    def sync_file(self, path: Path) -> dict[str, object]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        checksum = _sha256(path.read_bytes())
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        file_name = path.name
        layer_key = path.stem

        existing = self.postgres_store.read_geojson_file_registry(file_name)
        changed = self._registry_changed(existing, checksum, mtime)

        features = list(payload.get("features", []))
        source_crs = _extract_crs_name(payload)
        is_wgs = _is_wgs84(source_crs)
        active_feature_keys: list[str] = []
        records: list[dict[str, Any]] = []

        if changed:
            for feature_index, feature in enumerate(features):
                geometry = feature.get("geometry")
                if geometry is None:
                    continue

                if not is_wgs:
                    geometry = _transform_geometry(geometry, source_crs)

                properties = feature.get("properties") or {}
                feature_key = _feature_key(layer_key, feature)
                active_feature_keys.append(feature_key)
                records.append(
                    {
                        "layer_key": layer_key,
                        "feature_key": feature_key,
                        "feature_index": feature_index,
                        "lembaga": _field_value(properties, "LEMBAGA", "lembaga"),
                        "nama_prov": _field_value(properties, "NAMA_PROV", "NAMA_PROVINSI", "PROVINSI"),
                        "nama_kab": _field_value(properties, "NAMA_KAB", "KABUPATEN"),
                        "nama_kec": _field_value(properties, "NAMA_KEC", "KECAMATAN"),
                        "nama_desa": _field_value(properties, "NAMA_DESA", "DESA"),
                        "skema": _field_value(properties, "SKEMA"),
                        "no_sk": _field_value(properties, "NO_SK"),
                        "tgl_sk": _field_value(properties, "TGL_SK"),
                        "status": _field_value(properties, "Status", "STATUS"),
                        "wilker_bps": _field_value(properties, "WILKER_BPS"),
                        "ps_id": _field_value(properties, "PS_ID", "ps_id"),
                        "kode_prov": _field_value(properties, "KODE_PROV"),
                        "kode_kab": _field_value(properties, "KODE_KAB"),
                        "luas_hk": _field_value(properties, "Luas_HK", "LUAS_HK"),
                        "luas_hl": _field_value(properties, "LUAS_HL"),
                        "luas_hpt": _field_value(properties, "LUAS_HPT"),
                        "luas_hp": _field_value(properties, "LUAS_HP"),
                        "luas_hpk": _field_value(properties, "LUAS_HPK"),
                        "luas_sk": _field_value(properties, "LUAS_SK"),
                        "luas_poli": _field_value(properties, "Luas_Poli", "LUAS_POLI"),
                        "luas_final": _field_value(properties, "LuasFinal", "LUASFINAL", "LUAS_FINAL"),
                        "jml_kk": _field_value(properties, "Jml_KK", "JML_KK"),
                        "shape_leng": _field_value(properties, "Shape_Leng", "SHAPE_LENG"),
                        "shape_area": _field_value(properties, "Shape_Area", "SHAPE_AREA"),
                        "geometry": _normalize_geometry(geometry),
                        "properties_raw": properties,
                        "source_file": str(path),
                        "file_checksum": checksum,
                        "is_active": True,
                    }
                )

            features_upserted = self.postgres_store.upsert_polygon_metadata(records)
            features_deactivated = self.postgres_store.deactivate_missing_polygons(layer_key, active_feature_keys)
        else:
            features_upserted = 0
            features_deactivated = 0
            for feature_index, feature in enumerate(features):
                geometry = feature.get("geometry")
                if geometry is None:
                    continue
                feature_key = _feature_key(layer_key, feature)
                active_feature_keys.append(feature_key)

        self.postgres_store.upsert_geojson_file_registry(
            file_name=file_name,
            file_path=str(path),
            layer_key=layer_key,
            checksum=checksum,
            mtime=mtime,
            feature_count=len(active_feature_keys),
            last_sync_status="synced" if changed else "unchanged",
            last_sync_message="",
            is_active=True,
        )

        return {
            "file_name": file_name,
            "layer_key": layer_key,
            "checksum": checksum,
            "mtime": mtime.isoformat(),
            "changed": changed,
            "feature_count": len(active_feature_keys),
            "features_upserted": features_upserted,
            "features_deactivated": features_deactivated,
        }

    def _registry_changed(
        self,
        existing: dict[str, object] | None,
        checksum: str,
        mtime: datetime,
    ) -> bool:
        if existing is None:
            return True

        if not existing.get("is_active", True):
            return True

        existing_checksum = str(existing.get("checksum", ""))
        if existing_checksum != checksum:
            return True

        existing_mtime = existing.get("mtime")
        if isinstance(existing_mtime, datetime):
            if existing_mtime.tzinfo is None:
                existing_mtime = existing_mtime.replace(tzinfo=timezone.utc)
            return existing_mtime != mtime

        if isinstance(existing_mtime, str):
            try:
                parsed = datetime.fromisoformat(existing_mtime.replace("Z", "+00:00"))
            except ValueError:
                return True
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed != mtime

        return True


def _feature_key(layer_key: str, feature: dict[str, Any]) -> str:
    properties = feature.get("properties") or {}
    canonical = json.dumps(
        {
            "layer_key": layer_key,
            "geometry": feature.get("geometry"),
            "properties": properties,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _field_value(properties: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = properties.get(key)
        if value is None or value == "":
            continue
        return str(value)
    return None


def _normalize_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    geom = shape(geometry)
    geom = transform(lambda x, y, z=None: (x, y), geom)
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    elif geom.geom_type != "MultiPolygon":
        raise ValueError(f"Unsupported geometry type: {geom.geom_type}")
    return mapping(geom)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
