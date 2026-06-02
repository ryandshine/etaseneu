import json
from pathlib import Path


class FakePostgresStore:
    def __init__(self) -> None:
        self.enabled = True
        self.registry: dict[str, dict[str, object]] = {}
        self.polygons: dict[tuple[str, str], dict[str, object]] = {}

    def read_geojson_file_registry(self, file_name: str) -> dict[str, object] | None:
        return self.registry.get(file_name)

    def read_geojson_file_registry_all(self) -> list[dict[str, object]]:
        return [dict(row, file_name=file_name) for file_name, row in self.registry.items()]

    def upsert_geojson_file_registry(
        self,
        *,
        file_name: str,
        file_path: str,
        layer_key: str,
        checksum: str,
        mtime,
        feature_count: int,
        last_sync_status: str,
        last_sync_message: str = "",
        is_active: bool = True,
        last_synced_at=None,
    ) -> None:
        self.registry[file_name] = {
            "file_name": file_name,
            "file_path": file_path,
            "layer_key": layer_key,
            "checksum": checksum,
            "mtime": mtime,
            "feature_count": feature_count,
            "last_sync_status": last_sync_status,
            "last_sync_message": last_sync_message,
            "is_active": is_active,
            "last_synced_at": last_synced_at,
        }

    def deactivate_geojson_file_registry(self, file_name: str, *, message: str = "") -> bool:
        row = self.registry.get(file_name)
        if row is None:
            return False
        row["is_active"] = False
        row["last_sync_status"] = "removed"
        row["last_sync_message"] = message
        return True

    def upsert_polygon_metadata(self, records: list[dict[str, object]]) -> int:
        for record in records:
            key = (str(record["layer_key"]), str(record["feature_key"]))
            existing = self.polygons.get(key, {})
            self.polygons[key] = {**existing, **record, "is_active": True}
        return len(records)

    def deactivate_missing_polygons(self, layer_key: str, active_feature_keys) -> int:
        active_keys = {str(feature_key) for feature_key in active_feature_keys}
        updated = 0
        for (current_layer_key, feature_key), record in self.polygons.items():
            if current_layer_key != layer_key or not record.get("is_active", True):
                continue
            if feature_key in active_keys:
                continue
            record["is_active"] = False
            updated += 1
        return updated


def _write_geojson(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _feature(properties: dict[str, object], coordinates: list[list[list[float]]]) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": "Polygon",
            "coordinates": coordinates,
        },
    }


def test_geojson_sync_service_upserts_polygons_and_registry(tmp_path: Path) -> None:
    from app.services.geojson_sync_service import GeoJsonSyncService

    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()

    _write_geojson(
        shp_dir / "sample.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    {
                        "LEMBAGA": "Demo",
                        "NAMA_PROV": "Jawa Tengah",
                        "PS_ID": 123,
                        "LuasFinal": 42.5,
                    },
                    [[[110.0, -7.0], [110.1, -7.0], [110.1, -7.1], [110.0, -7.1], [110.0, -7.0]]],
                )
            ],
        },
    )

    store = FakePostgresStore()
    service = GeoJsonSyncService(shp_dir=shp_dir, database_url="postgresql://demo", postgres_store=store)

    first = service.sync_all()
    second = service.sync_all()

    assert first["files_scanned"] == 1
    assert first["files_changed"] == 1
    assert first["files_unchanged"] == 0
    assert first["features_upserted"] == 1
    assert first["features_deactivated"] == 0
    assert second["files_scanned"] == 1
    assert second["files_changed"] == 0
    assert second["files_unchanged"] == 1
    assert second["features_upserted"] == 0
    assert second["features_deactivated"] == 0

    registry = store.registry["sample.geojson"]
    assert registry["layer_key"] == "sample"
    assert registry["feature_count"] == 1
    assert registry["is_active"] is True

    assert len(store.polygons) == 1
    row = next(iter(store.polygons.values()))
    assert row["layer_key"] == "sample"
    assert row["is_active"] is True
    assert row["properties_raw"]["LEMBAGA"] == "Demo"
    assert row["properties_raw"]["PS_ID"] == 123
    assert row["properties_raw"]["LuasFinal"] == 42.5
    assert len(str(row["feature_key"])) == 64


def test_geojson_sync_service_marks_missing_features_and_removed_files_inactive(tmp_path: Path) -> None:
    from app.services.geojson_sync_service import GeoJsonSyncService

    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()

    sample_path = shp_dir / "sample.geojson"
    other_path = shp_dir / "other.geojson"

    _write_geojson(
        sample_path,
        {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    {"name": "Keep", "LEMBAGA": "Demo"},
                    [[[110.0, -7.0], [110.2, -7.0], [110.2, -7.2], [110.0, -7.2], [110.0, -7.0]]],
                ),
                _feature(
                    {"name": "Remove", "LEMBAGA": "Demo"},
                    [[[111.0, -7.0], [111.2, -7.0], [111.2, -7.2], [111.0, -7.2], [111.0, -7.0]]],
                ),
            ],
        },
    )
    _write_geojson(
        other_path,
        {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    {"name": "Other", "LEMBAGA": "Alt"},
                    [[[112.0, -7.0], [112.2, -7.0], [112.2, -7.2], [112.0, -7.2], [112.0, -7.0]]],
                )
            ],
        },
    )

    store = FakePostgresStore()
    service = GeoJsonSyncService(shp_dir=shp_dir, database_url="postgresql://demo", postgres_store=store)

    initial = service.sync_all()
    assert initial["files_scanned"] == 2
    assert initial["files_changed"] == 2
    assert initial["features_upserted"] == 3

    _write_geojson(
        sample_path,
        {
            "type": "FeatureCollection",
            "features": [
                _feature(
                    {"name": "Keep", "LEMBAGA": "Demo"},
                    [[[110.0, -7.0], [110.2, -7.0], [110.2, -7.2], [110.0, -7.2], [110.0, -7.0]]],
                )
            ],
        },
    )
    other_path.unlink()

    second = service.sync_all()

    assert second["files_scanned"] == 1
    assert second["files_changed"] == 1
    assert second["files_inactive"] == 1
    assert second["features_deactivated"] == 1

    assert store.registry["sample.geojson"]["is_active"] is True
    assert store.registry["other.geojson"]["is_active"] is False
    assert store.registry["other.geojson"]["last_sync_status"] == "removed"

    sample_rows = [row for row in store.polygons.values() if row["layer_key"] == "sample"]
    assert len(sample_rows) == 2
    assert sum(1 for row in sample_rows if row["is_active"]) == 1
    assert sum(1 for row in sample_rows if not row["is_active"]) == 1
    assert any(row["properties_raw"]["name"] == "Remove" and not row["is_active"] for row in sample_rows)
