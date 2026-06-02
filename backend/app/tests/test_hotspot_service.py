from datetime import date, datetime, timezone


class DummyHistoryStore:
    def __init__(self, reads: dict[str, dict[str, object] | None] | None = None) -> None:
        self.reads = reads or {}
        self.written: dict[str, dict[str, object]] = {}

    def read(self, key: str) -> dict[str, object] | None:
        return self.reads.get(key)

    def write(self, key: str, value: dict[str, object]) -> None:
        self.written[key] = value


class DummyCacheService:
    def __init__(self, reads: dict[str, list[dict]] | None = None) -> None:
        self.reads = reads or {}
        self.written: dict[str, list[dict]] = {}
        self.cleared = 0

    def read(self, key: str) -> list[dict] | None:
        return self.reads.get(key)

    def write(self, key: str, value: list[dict]) -> None:
        self.written[key] = value

    def clear_query_cache(self) -> int:
        self.cleared += 1
        return 3


class DummyPostgresStore:
    def __init__(self, observations: list[dict] | None = None) -> None:
        self.enabled = True
        self.observations = observations or []
        self.saved: list[dict] = []
        self.summary_refreshes = 0

    def read_hotspot_observations(
        self,
        *,
        start_date: str,
        end_date: str,
        sources: list[str],
        layer_ids: list[str],
    ) -> list[dict]:
        return list(self.observations)

    def upsert_hotspot_observations(self, hotspots: list[dict]) -> None:
        self.saved.extend(hotspots)

    def refresh_polygon_hotspot_summaries(self, layer_ids: list[str] | None = None) -> dict[str, int]:
        self.summary_refreshes += 1
        return {"active_polygon_count": 1, "pruned": 0, "rebuilt": 1}


class DummyNasaClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    async def fetch_rows(self, path: str) -> list[dict[str, str]]:
        self.paths.append(path)
        acq_date = path.rsplit("/", 1)[-1]
        return [
            {
                "latitude": "4.1",
                "longitude": "95.1",
                "brightness": "330.1",
                "confidence": "80",
                "acq_date": acq_date,
                "acq_time": "1200" if acq_date.endswith("01") else "1215",
                "satellite": "Terra",
            }
        ]


def test_fetch_filtered_hotspots_warms_layer_year_archive(monkeypatch) -> None:
    import asyncio

    from app.models.layers import LayerBounds, LayerFeature
    from app.models.query import HotspotQuery
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    service.postgres_store = DummyPostgresStore()
    service.history_store = DummyHistoryStore()
    service.cache_service = DummyCacheService()
    service.nasa_client = DummyNasaClient()
    service.settings.nasa_firms_api_key = "demo-key"

    layer = LayerFeature(
        id="sample_area",
        name="sample_area",
        color="#1d4ed8",
        active=True,
        feature_count=1,
        bounds=LayerBounds(min_lat=4.0, min_lon=95.0, max_lat=4.2, max_lon=95.2),
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [95.0, 4.0],
                                [95.2, 4.0],
                                [95.2, 4.2],
                                [95.0, 4.2],
                                [95.0, 4.0],
                            ]
                        ],
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(service.layer_service, "list_layers", lambda: [layer])
    monkeypatch.setattr(
        service.layer_service,
        "spatial_layers_for_ids",
        lambda layer_ids: [
            {
                "id": layer.id,
                "name": layer.name,
                "bounds": {
                    "min_lat": layer.bounds.min_lat,
                    "min_lon": layer.bounds.min_lon,
                    "max_lat": layer.bounds.max_lat,
                    "max_lon": layer.bounds.max_lon,
                },
                "geojson": layer.geojson,
            }
        ],
    )

    query = HotspotQuery(
        start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 5, 7, 23, 59, 59, tzinfo=timezone.utc),
        satellites=["MODIS"],
        active_layers=["sample_area"],
    )

    payload = asyncio.run(service.fetch_filtered_hotspots(query))

    assert payload["count"] == 2
    assert len(payload["hotspots"]) == 2
    assert payload["stats"]["total"] == 2
    assert service.nasa_client.paths == [
        "demo-key/MODIS_NRT/95,4,95.2,4.2/5/2026-05-01",
        "demo-key/MODIS_NRT/95,4,95.2,4.2/2/2026-05-06",
    ]
    assert "history/2026/sample_area" in service.history_store.written
    assert service.history_store.written["history/2026/sample_area"]["coverage_start"] == "2026-05-01"
    assert service.history_store.written["history/2026/sample_area"]["coverage_end"] == "2026-05-07"
    assert service.history_store.written["history/2026/sample_area"]["satellites"] == ["MODIS"]


def test_fetch_filtered_hotspots_reads_year_archive_without_hitting_nasa() -> None:
    import asyncio

    from app.models.layers import LayerBounds, LayerFeature
    from app.models.query import HotspotQuery
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    service.postgres_store = DummyPostgresStore()
    service.history_store = DummyHistoryStore(
        reads={
            "history/2026/sample_area": {
                "coverage_start": "2026-05-01",
                "coverage_end": "2026-05-31",
                "satellites": ["MODIS"],
                "hotspots": [
                    {
                        "id": "first",
                        "source": "MODIS",
                        "latitude": 4.1,
                        "longitude": 95.1,
                        "layer_name": "sample_area",
                        "detected_at": "2026-05-02T12:00:00Z",
                    },
                    {
                        "id": "second",
                        "source": "MODIS",
                        "latitude": 4.15,
                        "longitude": 95.15,
                        "layer_name": "sample_area",
                        "detected_at": "2026-05-03T12:00:00Z",
                    },
                ],
            }
        }
    )
    service.cache_service = DummyCacheService()
    service.nasa_client = DummyNasaClient()
    service.settings.nasa_firms_api_key = "demo-key"

    layer = LayerFeature(
        id="sample_area",
        name="sample_area",
        color="#1d4ed8",
        active=True,
        feature_count=1,
        bounds=LayerBounds(min_lat=4.0, min_lon=95.0, max_lat=4.2, max_lon=95.2),
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [95.0, 4.0],
                                [95.2, 4.0],
                                [95.2, 4.2],
                                [95.0, 4.2],
                                [95.0, 4.0],
                            ]
                        ],
                    },
                }
            ],
        },
    )
    service.layer_service.list_layers = lambda: [layer]
    service.layer_service.spatial_layers_for_ids = lambda layer_ids: [
        {
            "id": layer.id,
            "geojson": layer.geojson,
        }
    ]
    service.layer_service.bounds_for_layer_ids = lambda layer_ids: layer.bounds

    query = HotspotQuery(
        start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 5, 7, 23, 59, 59, tzinfo=timezone.utc),
        satellites=["MODIS"],
        active_layers=["sample_area"],
    )

    payload = asyncio.run(service.fetch_filtered_hotspots(query))

    assert payload["count"] == 2
    assert len(payload["hotspots"]) == 2
    assert service.nasa_client.paths == []


def test_fetch_filtered_hotspots_reads_postgres_observations_before_nasa() -> None:
    import asyncio

    from app.models.query import HotspotQuery
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    service.cache_service = DummyCacheService()
    service.history_store = DummyHistoryStore()
    service.nasa_client = DummyNasaClient()
    service.postgres_store = DummyPostgresStore(
        observations=[
            {
                "id": "db-1",
                "source": "MODIS",
                "satellite": "Terra",
                "latitude": 4.1,
                "longitude": 95.1,
                "layer_id": "sample_area",
                "layer_name": "sample_area",
                "agency_name": "LPHD Demo",
                "detected_at": "2026-05-02T12:00:00Z",
            }
        ]
    )

    query = HotspotQuery(
        start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 5, 7, 23, 59, 59, tzinfo=timezone.utc),
        satellites=["MODIS"],
        active_layers=["sample_area"],
    )

    payload = asyncio.run(service.fetch_filtered_hotspots(query))

    assert payload["count"] == 1
    assert payload["hotspots"][0]["id"] == "db-1"
    assert service.nasa_client.paths == []
    assert query.cache_key() in service.cache_service.written


def test_fetch_filtered_hotspots_supports_all_viirs_sensors(monkeypatch) -> None:
    import asyncio

    from app.models.layers import LayerBounds, LayerFeature
    from app.models.query import HotspotQuery
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    service.postgres_store = DummyPostgresStore()
    service.history_store = DummyHistoryStore()
    service.cache_service = DummyCacheService()
    service.nasa_client = DummyNasaClient()
    service.settings.nasa_firms_api_key = "demo-key"

    layer = LayerFeature(
        id="sample_area",
        name="sample_area",
        color="#1d4ed8",
        active=True,
        feature_count=1,
        bounds=LayerBounds(min_lat=4.0, min_lon=95.0, max_lat=4.2, max_lon=95.2),
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [95.0, 4.0],
                                [95.2, 4.0],
                                [95.2, 4.2],
                                [95.0, 4.2],
                                [95.0, 4.0],
                            ]
                        ],
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(service.layer_service, "list_layers", lambda: [layer])
    monkeypatch.setattr(
        service.layer_service,
        "spatial_layers_for_ids",
        lambda layer_ids: [
            {
                "id": layer.id,
                "name": layer.name,
                "bounds": {
                    "min_lat": layer.bounds.min_lat,
                    "min_lon": layer.bounds.min_lon,
                    "max_lat": layer.bounds.max_lat,
                    "max_lon": layer.bounds.max_lon,
                },
                "geojson": layer.geojson,
            }
        ],
    )

    query = HotspotQuery(
        start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 5, 7, 23, 59, 59, tzinfo=timezone.utc),
        satellites=["MODIS", "VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21"],
        active_layers=["sample_area"],
    )

    payload = asyncio.run(service.fetch_filtered_hotspots(query))

    assert payload["count"] == 2
    assert any("MODIS_NRT" in path for path in service.nasa_client.paths)
    assert any("VIIRS_SNPP_NRT" in path for path in service.nasa_client.paths)
    assert any("VIIRS_NOAA20_NRT" in path for path in service.nasa_client.paths)
    assert any("VIIRS_NOAA21_NRT" in path for path in service.nasa_client.paths)


def test_prewarm_year_history_warms_all_layers(monkeypatch) -> None:
    import asyncio

    from app.models.layers import LayerBounds, LayerFeature
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    service.history_store = DummyHistoryStore()
    service.cache_service = DummyCacheService()
    service.nasa_client = DummyNasaClient()
    service.settings.nasa_firms_api_key = "demo-key"

    layer = LayerFeature(
        id="sample_area",
        name="sample_area",
        color="#1d4ed8",
        active=True,
        feature_count=1,
        bounds=LayerBounds(min_lat=4.0, min_lon=95.0, max_lat=4.2, max_lon=95.2),
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [95.0, 4.0],
                                [95.2, 4.0],
                                [95.2, 4.2],
                                [95.0, 4.2],
                                [95.0, 4.0],
                            ]
                        ],
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(service.layer_service, "list_layers", lambda: [layer])
    monkeypatch.setattr(
        service.layer_service,
        "spatial_layers_for_ids",
        lambda layer_ids: [
            {
                "id": layer.id,
                "name": layer.name,
                "bounds": {
                    "min_lat": layer.bounds.min_lat,
                    "min_lon": layer.bounds.min_lon,
                    "max_lat": layer.bounds.max_lat,
                    "max_lon": layer.bounds.max_lon,
                },
                "geojson": layer.geojson,
            }
        ],
    )

    payload = asyncio.run(service.prewarm_year_history(2026))

    assert payload["cached"] is True
    assert payload["layer_count"] == 1
    assert payload["layers"] == ["sample_area"]
    assert "history/2026/sample_area" in service.history_store.written


def test_fetch_filtered_hotspots_returns_empty_without_active_layers() -> None:
    import asyncio

    from app.models.query import HotspotQuery
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    query = HotspotQuery(
        start_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 5, 7, 23, 59, 59, tzinfo=timezone.utc),
        satellites=["MODIS"],
        active_layers=[],
    )

    payload = asyncio.run(service.fetch_filtered_hotspots(query))

    assert payload == {
        "count": 0,
        "hotspots": [],
        "stats": {
            "total": 0,
            "by_source": {},
            "by_layer": {},
        },
    }


def test_refresh_geojson_refreshes_polygon_hotspot_summaries(monkeypatch) -> None:
    from app.services.hotspot_service import HotspotService

    service = HotspotService()
    service.postgres_store = DummyPostgresStore()
    service.cache_service = DummyCacheService()

    sync_calls = {"count": 0}

    def _sync_all():
        sync_calls["count"] += 1
        return {"files_scanned": 1}

    service.geojson_sync_service.sync_all = _sync_all

    summary = service.refresh_geojson()

    assert sync_calls["count"] == 1
    assert service.postgres_store.summary_refreshes == 1
    assert summary["polygon_hotspot_summary"]["rebuilt"] == 1
    assert summary["polygon_hotspot_summary"]["api_cache_cleared"] == 3
    assert service.cache_service.cleared == 1


def test_filter_hotspots_by_datetime_half_open_interval() -> None:
    from datetime import datetime, timezone
    from app.services.hotspot_service import _filter_hotspots_by_datetime

    hotspots = [
        {"id": "h1", "detected_at": "2026-05-30T00:00:00Z"},
        {"id": "h2", "detected_at": "2026-05-30T12:00:00Z"},
        {"id": "h3", "detected_at": "2026-05-31T00:00:00Z"},
    ]
    start = datetime(2026, 5, 30, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 31, 0, 0, 0, tzinfo=timezone.utc)

    filtered = _filter_hotspots_by_datetime(hotspots, start, end)

    # h1 (exactly on start) should be included
    # h2 (middle) should be included
    # h3 (exactly on end) should be excluded because it's half-open: [start, end)
    assert len(filtered) == 2
    assert any(h["id"] == "h1" for h in filtered)
    assert any(h["id"] == "h2" for h in filtered)
    assert not any(h["id"] == "h3" for h in filtered)

