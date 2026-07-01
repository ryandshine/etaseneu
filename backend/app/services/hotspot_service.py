from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.models.query import HotspotQuery
from app.services.cache_service import CacheService
from app.services.hotspot_history_store import HotspotHistoryStore
from app.services.hotspot_normalizer import normalize_hotspots
from app.services.layer_service import get_layer_service
from app.services.nasa_client import NasaFirmsClient
from app.services.postgres_store import PostgresStore
from app.services.spatial_service import filter_hotspots_by_layers
from app.services.stats_service import build_stats


DATASET_BY_SATELLITE = {
    "MODIS": ("MODIS_NRT", "MODIS"),
    "VIIRS_SNPP": ("VIIRS_SNPP_NRT", "VIIRS S-NPP"),
    "VIIRS_NOAA20": ("VIIRS_NOAA20_NRT", "VIIRS NOAA-20"),
    "VIIRS_NOAA21": ("VIIRS_NOAA21_NRT", "VIIRS NOAA-21"),
}

SUPPORTED_SATELLITES = sorted(DATASET_BY_SATELLITE.keys())


class HotspotService:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.layer_service = get_layer_service(str(settings.resolved_shp_dir))
        self.geojson_sync_service = self.layer_service.geojson_sync_service
        self.history_store = HotspotHistoryStore(
            settings.resolved_cache_dir / "hotspot_history",
            database_url=settings.database_url,
        )
        self.cache_service = CacheService(
            settings.resolved_cache_dir,
            ttl_hours=settings.cache_ttl_hours,
            database_url=settings.database_url,
        )
        self.postgres_store = PostgresStore(settings.database_url)
        self.nasa_client = NasaFirmsClient()

    async def fetch_filtered_hotspots(self, query: HotspotQuery, bypass_cache: bool = False) -> dict[str, object]:
        if not query.active_layers or not query.satellites:
            return {"count": 0, "hotspots": [], "stats": build_stats([])}

        active_layers = self.layer_service.spatial_layers_for_ids(query.active_layers)
        if not active_layers:
            return {"count": 0, "hotspots": [], "stats": build_stats([])}

        hydrated_hotspots: list[dict] = []
        cache_hit = False

        if not bypass_cache:
            cached_hotspots = self.cache_service.read(query.cache_key())
            if cached_hotspots is not None:
                hydrated_hotspots = self._hydrate_polygon_metadata(query, cached_hotspots)
                cache_hit = True

            if not cache_hit and self.postgres_store.enabled:
                try:
                    db_hotspots = self.postgres_store.read_hotspot_observations(
                        start_date=query.start_at.isoformat(),
                        end_date=query.end_at.isoformat(),
                        sources=_query_sources(query.satellites),
                        layer_ids=query.active_layers,
                    )
                    if db_hotspots is not None:
                        self.cache_service.write(query.cache_key(), db_hotspots)
                        hydrated_hotspots = db_hotspots
                        cache_hit = True
                except Exception as e:
                    import logging
                    logging.getLogger("hotspot.service").warning("DB query error: %s", e)

        if not cache_hit:
            yearly_hotspots: list[dict] = []
            for layer in active_layers:
                for year_start, year_end in _iter_year_segments(query.start_at.date(), query.end_at.date()):
                    try:
                        yearly_hotspots.extend(
                            await self._read_or_warm_layer_year_archive(
                                query=query,
                                layer=layer,
                                year_start=year_start,
                                year_end=year_end,
                            )
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger("hotspot.service").warning(
                            "NASA fetch failed for %s %s–%s: %s", layer.name, year_start, year_end, e
                        )

            filtered = _filter_unique_hotspots_by_date(
                yearly_hotspots,
                query.start_at,
                query.end_at,
            )
            if self.postgres_store.enabled:
                try:
                    self.postgres_store.upsert_hotspot_observations(filtered)
                except Exception:
                    pass
                self._persist_filtered_hotspots(filtered)
            hydrated_hotspots = self._hydrate_polygon_metadata(query, filtered)
            self.cache_service.write(query.cache_key(), hydrated_hotspots)

        stats = build_stats(hydrated_hotspots)

        # Inferred Selected Filter
        delta = query.end_at - query.start_at
        selected_filter = "Custom"
        if abs(delta - timedelta(days=1)) < timedelta(minutes=5):
            selected_filter = "24 Jam"
        elif abs(delta - timedelta(days=2)) < timedelta(minutes=5):
            selected_filter = "48 Jam"
        elif abs(delta - timedelta(days=3)) < timedelta(minutes=5):
            selected_filter = "3 Hari"
        elif abs(delta - timedelta(days=7)) < timedelta(minutes=5):
            selected_filter = "7 Hari"
        elif abs(delta - timedelta(days=30)) < timedelta(minutes=5):
            selected_filter = "30 Hari"

        # Timezone & Dates
        from zoneinfo import ZoneInfo
        wib_tz = ZoneInfo("Asia/Jakarta")
        current_date_str = datetime.now(wib_tz).strftime("%Y-%m-%d %H:%M:%S WIB")
        start_wib_str = query.start_at.astimezone(wib_tz).strftime("%Y-%m-%d %H:%M:%S WIB")
        end_wib_str = query.end_at.astimezone(wib_tz).strftime("%Y-%m-%d %H:%M:%S WIB")

        # Total Records Before Filter
        total_before = 0
        if self.postgres_store.enabled:
            try:
                with self.postgres_store.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT COUNT(*) FROM hotspot_observations obs WHERE obs.source = ANY(%s) AND obs.layer_key = ANY(%s)",
                            (_query_sources(query.satellites), query.active_layers),
                        )
                        row = cur.fetchone()
                        if row:
                            total_before = list(row.values())[0] if isinstance(row, dict) else row[0]
            except Exception:
                pass

        # Earliest and Latest datetimes from returned hotspots
        earliest_wib = "N/A"
        latest_wib = "N/A"
        if hydrated_hotspots:
            datetimes = []
            for h in hydrated_hotspots:
                det_str = h.get("detected_at")
                if det_str:
                    try:
                        dt = datetime.fromisoformat(str(det_str).replace("Z", "+00:00"))
                        datetimes.append(dt)
                    except Exception:
                        pass
            if datetimes:
                earliest_wib = min(datetimes).astimezone(wib_tz).strftime("%Y-%m-%d %H:%M:%S WIB")
                latest_wib = max(datetimes).astimezone(wib_tz).strftime("%Y-%m-%d %H:%M:%S WIB")

        debug_log = (
            f"\n--- [HOTSPOT FILTER DEBUG LOG] ---\n"
            f"Selected Filter:               {selected_filter}\n"
            f"Current Date (WIB):            {current_date_str}\n"
            f"Start Datetime (WIB):          {start_wib_str}\n"
            f"End Datetime (WIB):            {end_wib_str}\n"
            f"Timezone Used:                 Asia/Jakarta (WIB)\n"
            f"Total Records Before Filter:   {total_before}\n"
            f"Total Records After Filter:    {len(hydrated_hotspots)}\n"
            f"Earliest Hotspot (WIB):        {earliest_wib}\n"
            f"Latest Hotspot (WIB):          {latest_wib}\n"
            f"------------------------------------\n"
        )
        print(debug_log, flush=True)

        return {"count": len(hydrated_hotspots), "hotspots": hydrated_hotspots, "stats": stats}

    async def prewarm_year_history(
        self,
        year: int,
        satellites: list[str] | None = None,
        layer_ids: list[str] | None = None,
    ) -> dict[str, object]:
        selected_satellites = _normalize_satellites(satellites or SUPPORTED_SATELLITES)
        selected_layer_ids = layer_ids or [layer.id for layer in self.layer_service.list_layers()]
        layers = self.layer_service.spatial_layers_for_ids(selected_layer_ids)

        warmed_layers: list[str] = []
        start_date = date(year, 1, 1)
        end_date = date(year, 12, 31)

        for layer in layers:
            await self._read_or_warm_layer_year_archive(
                query=HotspotQuery(
                    start_at=datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc),
                    end_at=datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc),
                    satellites=selected_satellites,
                    active_layers=[str(layer["id"])],
                ),
                layer=layer,
                year_start=start_date,
                year_end=end_date,
            )
            warmed_layers.append(str(layer["id"]))

        return {
            "year": year,
            "cached": True,
            "layer_count": len(warmed_layers),
            "layers": warmed_layers,
            "satellites": selected_satellites,
        }

    def history_status(
        self,
        year: int,
        satellites: list[str] | None = None,
        layer_ids: list[str] | None = None,
    ) -> dict[str, object]:
        selected_satellites = _normalize_satellites(satellites or SUPPORTED_SATELLITES)
        selected_layer_ids = layer_ids or [layer.id for layer in self.layer_service.list_layers()]
        layers = self.layer_service.spatial_layers_for_ids(selected_layer_ids)

        layer_states: list[dict[str, object]] = []
        for layer in layers:
            archive_key = f"history/{year}/{layer['id']}"
            archive = self.history_store.read(archive_key)
            cached_satellites = _normalize_satellites(archive.get("satellites")) if archive else []
            layer_states.append(
                {
                    "layer_id": layer["id"],
                    "cached": archive is not None and set(selected_satellites).issubset(cached_satellites),
                    "satellites": cached_satellites,
                    "coverage_start": archive.get("coverage_start") if archive else None,
                    "coverage_end": archive.get("coverage_end") if archive else None,
                    "hotspot_count": len(_ensure_hotspots_list(archive.get("hotspots"))) if archive else 0,
                }
            )

        return {
            "year": year,
            "cached": all(layer_state["cached"] for layer_state in layer_states),
            "layers": layer_states,
            "satellites": selected_satellites,
        }

    def storage_status(self) -> dict[str, object]:
        return self.postgres_store.storage_status()

    def geojson_status(self) -> dict[str, object]:
        return self.geojson_sync_service.status()

    def refresh_geojson(self) -> dict[str, object]:
        summary = self.geojson_sync_service.sync_all()
        if self.postgres_store.enabled:
            try:
                summary["polygon_hotspot_summary"] = self.refresh_polygon_hotspot_summaries()
            except Exception:
                summary["polygon_hotspot_summary"] = {
                    "active_polygon_count": 0,
                    "pruned": 0,
                    "rebuilt": 0,
                }
        return summary

    def refresh_polygon_hotspot_summaries(self) -> dict[str, int]:
        if not self.postgres_store.enabled:
            return {
                "active_polygon_count": 0,
                "pruned": 0,
                "rebuilt": 0,
            }
        summary = self.postgres_store.refresh_polygon_hotspot_summaries()
        summary["api_cache_cleared"] = self.cache_service.clear_query_cache()
        return summary

    async def _read_or_warm_layer_year_archive(
        self,
    query: HotspotQuery,
    layer: dict,
    year_start: date,
    year_end: date,
    ) -> list[dict]:
        archive_key = query.yearly_archive_key(year_start.year, str(layer["id"]))
        archive = self.history_store.read(archive_key)
        requested_satellites = _normalize_satellites(query.satellites)

        if archive is None:
            fetch_start = max(year_start, query.start_at.date())
            fetch_end = min(year_end, query.end_at.date())
            
            hotspots = await self._fetch_layer_hotspots(
                layer=layer,
                start_date=fetch_start,
                end_date=fetch_end,
                satellites=requested_satellites,
            )
            self.history_store.write(
                archive_key,
                {
                    "coverage_start": fetch_start.isoformat(),
                    "coverage_end": fetch_end.isoformat(),
                    "satellites": requested_satellites,
                    "hotspots": hotspots,
                },
            )
            return _filter_hotspots_by_datetime(hotspots, query.start_at, query.end_at)

        coverage_start = _parse_date(str(archive.get("coverage_start", year_start.isoformat())))
        coverage_end = _parse_date(str(archive.get("coverage_end", year_start.isoformat())))

        # To ensure we get intra-day and late-arriving real-time updates,
        # we always consider the last 2 days as "uncovered" and force a re-fetch.
        today = datetime.now(timezone.utc).date()
        if coverage_end >= today - timedelta(days=2):
            coverage_end = today - timedelta(days=3)

        cached_hotspots = _ensure_hotspots_list(archive.get("hotspots"))
        cached_satellites = _normalize_satellites(archive.get("satellites"))
        missing_satellites = [satellite for satellite in requested_satellites if satellite not in cached_satellites]
        combined_satellites = _normalize_satellites([*cached_satellites, *requested_satellites])

        requested_start = max(year_start, query.start_at.date())
        requested_end = min(year_end, query.end_at.date())
        fetch_start = min(requested_start, coverage_start)
        fetch_end = max(requested_end, coverage_end)

        fetched_hotspots: list[dict] = []
        fetched_from_nasa = False
        if fetch_start < coverage_start:
            batch = await self._fetch_layer_hotspots(
                layer=layer,
                start_date=fetch_start,
                end_date=coverage_start - timedelta(days=1),
                satellites=combined_satellites,
            )
            if self.settings.nasa_firms_api_key:
                fetched_from_nasa = True
                fetched_hotspots.extend(batch)
        if fetch_end > coverage_end:
            batch = await self._fetch_layer_hotspots(
                layer=layer,
                start_date=coverage_end + timedelta(days=1),
                end_date=fetch_end,
                satellites=combined_satellites,
            )
            if self.settings.nasa_firms_api_key:
                fetched_from_nasa = True
                fetched_hotspots.extend(batch)
        if missing_satellites:
            batch = await self._fetch_layer_hotspots(
                layer=layer,
                start_date=year_start,
                end_date=year_end,
                satellites=missing_satellites,
            )
            if self.settings.nasa_firms_api_key:
                fetched_from_nasa = True
                fetched_hotspots.extend(batch)

        if fetched_hotspots:
            combined_hotspots = _dedupe_hotspots([*cached_hotspots, *fetched_hotspots])
            self.history_store.write(
                archive_key,
                {
                    "coverage_start": min(fetch_start, coverage_start).isoformat(),
                    "coverage_end": max(fetch_end, coverage_end).isoformat(),
                    "satellites": combined_satellites,
                    "hotspots": combined_hotspots,
                },
            )
        else:
            combined_hotspots = cached_hotspots

        if fetched_from_nasa and self.postgres_store.enabled:
            try:
                self.postgres_store.record_hotspot_sync(hotspot_count=len(fetched_hotspots))
            except Exception:
                pass

        return _filter_hotspots_by_datetime(combined_hotspots, query.start_at, query.end_at)

    async def _fetch_layer_hotspots(
        self,
        layer: dict,
        start_date: date,
        end_date: date,
        satellites: list[str],
    ) -> list[dict]:
        if not self.settings.nasa_firms_api_key or not satellites:
            return []

        bounds = layer.get("bounds")
        geojson = layer.get("geojson")
        if bounds is None or geojson is None:
            return []

        normalized: list[dict] = []
        area_coordinates = ",".join(
            [
                _format_coord(float(bounds["min_lon"])),
                _format_coord(float(bounds["min_lat"])),
                _format_coord(float(bounds["max_lon"])),
                _format_coord(float(bounds["max_lat"])),
            ]
        )

        for satellite in satellites:
            dataset_info = DATASET_BY_SATELLITE.get(satellite)
            if dataset_info is None:
                continue

            dataset_code, source = dataset_info
            for chunk_start, chunk_end in _iter_date_chunks(start_date, end_date):
                days = _range_to_days(chunk_start, chunk_end)
                path = (
                    f"{self.settings.nasa_firms_api_key}/{dataset_code}/"
                    f"{area_coordinates}/{days}/{chunk_start.isoformat()}"
                )
                rows = await self.nasa_client.fetch_rows(path)
                normalized.extend(normalize_hotspots(list(rows), source=source))

        return filter_hotspots_by_layers(normalized, [layer])

    def _persist_filtered_hotspots(self, hotspots: list[dict]) -> None:
        if not hotspots or not self.postgres_store.enabled:
            return

        try:
            observation_rows = self.postgres_store.read_hotspot_observation_records(hotspots)
        except Exception:
            return

        observation_index = {
            _hotspot_observation_key(row): int(row["id"])
            for row in observation_rows
            if row.get("id") is not None
        }

        relation_rows: list[dict[str, object]] = []
        impacted_polygon_ids: set[int] = set()
        polygon_lookup_cache: dict[str, dict[str, int]] = {}
        polygon_index_lookup_cache: dict[str, dict[int, int]] = {}

        for hotspot in hotspots:
            polygon_metadata = hotspot.get("polygon_metadata") or {}
            layer_key = str(hotspot.get("layer_id") or hotspot.get("layer_key") or "")
            if not layer_key:
                continue

            polygon_metadata_id = polygon_metadata.get("polygon_metadata_id") or polygon_metadata.get("id")
            feature_index = polygon_metadata.get("feature_index")
            feature_key = polygon_metadata.get("feature_key")
            if polygon_metadata_id is None and feature_index is not None:
                if layer_key not in polygon_index_lookup_cache:
                    try:
                        polygon_index_lookup_cache[layer_key] = self.postgres_store.read_polygon_metadata_ids_by_index(
                            layer_key=layer_key,
                            feature_indices=[int(feature_index)],
                        )
                    except Exception:
                        polygon_index_lookup_cache[layer_key] = {}
                polygon_metadata_id = polygon_index_lookup_cache[layer_key].get(int(feature_index))

            if polygon_metadata_id is None and feature_key:
                if layer_key not in polygon_lookup_cache:
                    try:
                        polygon_lookup_cache[layer_key] = self.postgres_store.read_polygon_metadata_ids(
                            layer_key=layer_key,
                            feature_keys=[str(feature_key)],
                        )
                    except Exception:
                        polygon_lookup_cache[layer_key] = {}
                polygon_metadata_id = polygon_lookup_cache[layer_key].get(str(feature_key))

            if polygon_metadata_id is None:
                continue

            observation_id = observation_index.get(_hotspot_observation_key(hotspot))
            if observation_id is None:
                continue

            polygon_metadata_id = int(polygon_metadata_id)
            relation_rows.append(
                {
                    "hotspot_observation_id": observation_id,
                    "polygon_metadata_id": polygon_metadata_id,
                    "layer_key": layer_key,
                    "match_method": "contains",
                }
            )
            impacted_polygon_ids.add(polygon_metadata_id)

        if relation_rows:
            try:
                self.postgres_store.upsert_hotspot_polygon_relation(relation_rows)
            except Exception:
                pass

        if impacted_polygon_ids:
            try:
                self.postgres_store.rebuild_polygon_hotspot_summary(sorted(impacted_polygon_ids))
            except Exception:
                pass

    def _hydrate_polygon_metadata(self, query: HotspotQuery, hotspots: list[dict]) -> list[dict]:
        if not hotspots or not self.postgres_store.enabled:
            return hotspots

        try:
            hydrated = self.postgres_store.read_hotspot_observations(
                start_date=query.start_at.isoformat(),
                end_date=query.end_at.isoformat(),
                sources=_query_sources(query.satellites),
                layer_ids=query.active_layers,
            )
        except Exception:
            return hotspots

        if not hydrated:
            return hotspots

        hydrated_index = {
            _hotspot_observation_key(hotspot): hotspot for hotspot in hydrated
        }

        merged_hotspots: list[dict] = []
        for hotspot in hotspots:
            hydrated_hotspot = hydrated_index.get(_hotspot_observation_key(hotspot))
            if hydrated_hotspot is None:
                merged_hotspots.append(hotspot)
                continue

            polygon_metadata = dict(hotspot.get("polygon_metadata") or {})
            hydrated_polygon_metadata = hydrated_hotspot.get("polygon_metadata") or {}
            if isinstance(hydrated_polygon_metadata, dict) and hydrated_polygon_metadata:
                polygon_metadata.update(hydrated_polygon_metadata)

            merged_hotspots.append(
                {
                    **hotspot,
                    **{key: value for key, value in hydrated_hotspot.items() if key != "polygon_metadata"},
                    "polygon_metadata": polygon_metadata,
                }
            )

        return merged_hotspots


def _range_to_days(start_date: date, end_date: date) -> int:
    delta = (end_date - start_date).days + 1
    return max(delta, 1)


def _iter_date_chunks(start_date: date, end_date: date) -> list[tuple[date, date]]:
    chunks: list[tuple[date, date]] = []
    cursor = start_date

    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=4), end_date)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)

    return chunks


def _format_coord(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _iter_year_segments(start_date: date, end_date: date) -> list[tuple[date, date]]:
    segments: list[tuple[date, date]] = []
    cursor = start_date

    while cursor <= end_date:
        segment_end = date(cursor.year, 12, 31)
        if segment_end > end_date:
            segment_end = end_date
        segments.append((cursor, segment_end))
        cursor = segment_end + timedelta(days=1)

    return segments


def _filter_hotspots_by_datetime(hotspots: list[dict], start_at: datetime, end_at: datetime) -> list[dict]:
    filtered: list[dict] = []
    for hotspot in hotspots:
        detected_at = str(hotspot.get("detected_at", ""))
        if not detected_at:
            continue
        detected_datetime = _parse_detected_datetime(detected_at)
        if start_at <= detected_datetime < end_at:
            filtered.append(hotspot)
    return filtered


def _filter_unique_hotspots_by_date(hotspots: list[dict], start_at: datetime, end_at: datetime) -> list[dict]:
    return _dedupe_hotspots(_filter_hotspots_by_datetime(hotspots, start_at, end_at))


def _parse_detected_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _ensure_hotspots_list(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [hotspot for hotspot in value if isinstance(hotspot, dict)]


def _normalize_satellites(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item)})


def _query_sources(satellites: list[str]) -> list[str]:
    sources: list[str] = []
    for satellite in satellites:
        dataset_info = DATASET_BY_SATELLITE.get(satellite)
        if dataset_info is None:
            continue
        _, source = dataset_info
        if source not in sources:
            sources.append(source)
    return sources


def _dedupe_hotspots(hotspots: Iterable[dict]) -> list[dict]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict] = []

    for hotspot in hotspots:
        identity = (
            str(hotspot.get("id", "")),
            str(hotspot.get("detected_at", "")),
            str(hotspot.get("latitude", "")),
            str(hotspot.get("longitude", "")),
            str(hotspot.get("layer_id", hotspot.get("layer_name", ""))),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(hotspot)

    return deduped


def _hotspot_observation_key(hotspot: dict) -> tuple[str, str, float, float, str, str]:
    detected_at_value = _canonical_detected_at_value(hotspot.get("detected_at"))

    return (
        str(hotspot.get("source", "")),
        str(hotspot.get("satellite", "")),
        float(hotspot["latitude"]),
        float(hotspot["longitude"]),
        detected_at_value,
        str(hotspot.get("layer_id") or hotspot.get("layer_key") or ""),
    )


def _canonical_detected_at_value(value: object) -> str:
    if hasattr(value, "isoformat"):
        detected_at = value  # type: ignore[assignment]
        if detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
        else:
            detected_at = detected_at.astimezone(timezone.utc)
        return detected_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    if value is None:
        return ""

    try:
        detected_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if detected_at.tzinfo is None:
            detected_at = detected_at.replace(tzinfo=ZoneInfo("Asia/Jakarta"))
        else:
            detected_at = detected_at.astimezone(timezone.utc)
    except Exception:
        return str(value)

    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=timezone.utc)
    else:
        detected_at = detected_at.astimezone(timezone.utc)
    return detected_at.replace(microsecond=0).isoformat().replace("+00:00", "Z")
