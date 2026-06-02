from __future__ import annotations


class FakePostgresStore:
    def __init__(self) -> None:
        self.enabled = True
        self.observation_rows = [
            {
                "id": 17,
                "source": "MODIS",
                "satellite": "Terra",
                "latitude": 4.1,
                "longitude": 95.1,
                "detected_at": "2026-05-02T12:00:00Z",
                "layer_key": "sample_area",
            }
        ]
        self.polygon_lookup = {"feature-1": 99}
        self.relations: list[dict[str, object]] = []
        self.rebuilt: list[int] = []

    def read_hotspot_observation_records(self, hotspots):
        return list(self.observation_rows)

    def read_polygon_metadata_ids(self, *, layer_key: str, feature_keys: list[str]):
        return {feature_key: self.polygon_lookup[feature_key] for feature_key in feature_keys if feature_key in self.polygon_lookup}

    def upsert_hotspot_polygon_relation(self, relations):
        self.relations.extend(relations)
        return len(relations)

    def rebuild_polygon_hotspot_summary(self, polygon_metadata_ids):
        self.rebuilt.extend(int(item) for item in polygon_metadata_ids)
        return len(polygon_metadata_ids)


def test_persist_filtered_hotspots_builds_relation_and_summary() -> None:
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    service.postgres_store = FakePostgresStore()

    service._persist_filtered_hotspots(
        [
            {
                "id": "hotspot-1",
                "source": "MODIS",
                "satellite": "Terra",
                "latitude": 4.1,
                "longitude": 95.1,
                "detected_at": "2026-05-02T12:00:00Z",
                "layer_id": "sample_area",
                "polygon_metadata": {
                    "feature_key": "feature-1",
                    "layer_key": "sample_area",
                },
            }
        ]
    )

    assert service.postgres_store.relations == [
        {
            "hotspot_observation_id": 17,
            "polygon_metadata_id": 99,
            "layer_key": "sample_area",
            "match_method": "contains",
        }
    ]
    assert service.postgres_store.rebuilt == [99]
