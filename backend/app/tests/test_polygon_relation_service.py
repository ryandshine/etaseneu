from __future__ import annotations

from datetime import datetime, timezone


class FakePostgresStore:
    """Store palsu: mencatat jendela waktu yang direkonsiliasi, tanpa menyentuh database."""

    def __init__(self) -> None:
        self.enabled = True
        self.synced: list[tuple[datetime, datetime]] = []

    def sync_hotspot_relations_and_summaries(self, *, start_at, end_at):
        self.synced.append((start_at, end_at))
        return {"inserted": 2, "updated": 0, "summary_rebuilt": 2}


def _hotspot(detected_at: str, lon: float) -> dict[str, object]:
    return {
        "source": "MODIS",
        "satellite": "Terra",
        "latitude": 4.1,
        "longitude": lon,
        "detected_at": detected_at,
        "layer_id": "sample_area",
    }


def test_persist_filtered_hotspots_syncs_relations_for_the_whole_batch_window() -> None:
    """Relasi dibentuk dari pencocokan spasial di database untuk SELURUH jendela waktu batch --
    bukan dari metadata poligon milik tiap dict hotspot (jalur lama hanya membentuk relasi untuk
    hotspot yang satu poligon dengan hotspot pertama di layernya)."""
    from app.services.hotspot_service import HotspotService

    service = HotspotService.__new__(HotspotService)
    service.postgres_store = FakePostgresStore()

    result = service._persist_filtered_hotspots(
        [_hotspot("2026-05-02T12:00:00Z", 95.1), _hotspot("2026-05-03T03:00:00Z", 120.7)]
    )

    assert service.postgres_store.synced == [
        (
            datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 3, 3, 0, 1, tzinfo=timezone.utc),
        )
    ]
    assert result["inserted"] == 2


def test_persist_filtered_hotspots_skips_when_database_disabled() -> None:
    from app.services.hotspot_service import HotspotService

    service = HotspotService.__new__(HotspotService)
    service.postgres_store = FakePostgresStore()
    service.postgres_store.enabled = False

    assert service._persist_filtered_hotspots([_hotspot("2026-05-02T12:00:00Z", 95.1)]) == {}
    assert service.postgres_store.synced == []
