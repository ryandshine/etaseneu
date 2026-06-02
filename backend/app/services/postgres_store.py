import json
from collections.abc import Sequence
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from psycopg import Connection, connect
    from psycopg.rows import dict_row
    from psycopg.types.json import Json

    PSYCOPG_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without psycopg
    Connection = Any  # type: ignore[assignment]
    connect = None
    dict_row = None
    Json = lambda value: value  # type: ignore[assignment]
    PSYCOPG_AVAILABLE = False


def _safe_json(value: object, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


class PostgresStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.strip()
        self._available: bool | None = None

    @property
    def enabled(self) -> bool:
        if not self.database_url or not PSYCOPG_AVAILABLE:
            return False

        if self._available is None:
            self._available = self._probe_connection()

        return self._available

    def _probe_connection(self) -> bool:
        if connect is None:
            return False
        try:
            with connect(
                self.database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=2,
            ):
                return True
        except Exception:
            return False

    @contextmanager
    def connection(self) -> Iterable[Connection]:
        if not self.enabled:
            raise RuntimeError("database storage is not available")

        assert connect is not None
        with connect(
            self.database_url,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=2,
        ) as conn:
            yield conn

    def upsert_layer(
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
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO layers (
                        layer_key,
                        layer_name,
                        layer_label,
                        feature_count,
                        bounds,
                        agencies,
                        display_geojson,
                        spatial_geojson
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (layer_key)
                    DO UPDATE SET
                        layer_name = EXCLUDED.layer_name,
                        layer_label = EXCLUDED.layer_label,
                        feature_count = EXCLUDED.feature_count,
                        bounds = EXCLUDED.bounds,
                        agencies = EXCLUDED.agencies,
                        display_geojson = EXCLUDED.display_geojson,
                        spatial_geojson = EXCLUDED.spatial_geojson,
                        updated_at = NOW()
                    """,
                    (
                        layer_key,
                        layer_name,
                        layer_label,
                        feature_count,
                        Json(bounds),
                        Json(agencies),
                        Json(display_geojson),
                        Json(spatial_geojson),
                    ),
                )

    def layer_sync_state(self, layer_key: str) -> dict[str, object] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT feature_count, layer_label
                    FROM layers
                    WHERE layer_key = %s
                    """,
                    (layer_key,),
                )
                return cur.fetchone()

    def read_geojson_file_registry(self, file_name: str) -> dict[str, object] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM geojson_file_registry
                    WHERE file_name = %s
                    """,
                    (file_name,),
                )
                return cur.fetchone()

    def read_geojson_file_registry_all(self) -> list[dict[str, object]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM geojson_file_registry
                    ORDER BY file_name ASC
                    """
                )
                rows = cur.fetchall()
        return list(rows)

    def geojson_registry_status(self) -> dict[str, object]:
        rows = self.read_geojson_file_registry_all()
        active_files = sum(1 for row in rows if row.get("is_active", True))
        return {
            "count": len(rows),
            "active_count": active_files,
            "inactive_count": len(rows) - active_files,
            "files": rows,
        }

    def upsert_geojson_file_registry(
        self,
        *,
        file_name: str,
        file_path: str,
        layer_key: str,
        checksum: str,
        mtime: datetime,
        feature_count: int,
        last_sync_status: str,
        last_sync_message: str = "",
        is_active: bool = True,
        last_synced_at: datetime | None = None,
    ) -> None:
        if last_synced_at is None:
            last_synced_at = datetime.now(timezone.utc)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO geojson_file_registry (
                        file_name,
                        file_path,
                        layer_key,
                        checksum,
                        mtime,
                        last_synced_at,
                        last_sync_status,
                        last_sync_message,
                        feature_count,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (file_name)
                    DO UPDATE SET
                        file_path = EXCLUDED.file_path,
                        layer_key = EXCLUDED.layer_key,
                        checksum = EXCLUDED.checksum,
                        mtime = EXCLUDED.mtime,
                        last_synced_at = EXCLUDED.last_synced_at,
                        last_sync_status = EXCLUDED.last_sync_status,
                        last_sync_message = EXCLUDED.last_sync_message,
                        feature_count = EXCLUDED.feature_count,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """,
                    (
                        file_name,
                        file_path,
                        layer_key,
                        checksum,
                        mtime,
                        last_synced_at,
                        last_sync_status,
                        last_sync_message,
                        feature_count,
                        is_active,
                    ),
                )

    def deactivate_geojson_file_registry(
        self,
        file_name: str,
        *,
        message: str = "file missing from scan",
    ) -> bool:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE geojson_file_registry
                    SET
                        is_active = FALSE,
                        last_sync_status = %s,
                        last_sync_message = %s,
                        updated_at = NOW()
                    WHERE file_name = %s
                    RETURNING layer_key
                    """,
                    ("removed", message, file_name),
                )
                row = cur.fetchone()
                if row and row.get("layer_key"):
                    cur.execute(
                        """
                        UPDATE polygon_metadata
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE layer_key = %s AND is_active = TRUE
                        """,
                        (row["layer_key"],),
                    )
                    return True
                return False

    def upsert_polygon_metadata(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0

        params: list[tuple[object, ...]] = []
        for record in records:
            geometry = json.dumps(record["geometry"], ensure_ascii=False)
            params.append(
                (
                    record["layer_key"],
                    record["feature_key"],
                    record["feature_index"],
                    record.get("lembaga"),
                    record.get("nama_prov"),
                    record.get("nama_kab"),
                    record.get("nama_kec"),
                    record.get("nama_desa"),
                    record.get("skema"),
                    record.get("no_sk"),
                    record.get("tgl_sk"),
                    record.get("status"),
                    record.get("wilker_bps"),
                    record.get("ps_id"),
                    record.get("kode_prov"),
                    record.get("kode_kab"),
                    record.get("luas_hk"),
                    record.get("luas_hl"),
                    record.get("luas_hpt"),
                    record.get("luas_hp"),
                    record.get("luas_hpk"),
                    record.get("luas_sk"),
                    record.get("luas_poli"),
                    record.get("luas_final"),
                    record.get("jml_kk"),
                    record.get("shape_leng"),
                    record.get("shape_area"),
                    geometry,
                    Json(record.get("properties_raw", {})),
                    record["source_file"],
                    record["file_checksum"],
                    record.get("is_active", True),
                )
            )

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO polygon_metadata (
                        layer_key,
                        feature_key,
                        feature_index,
                        lembaga,
                        nama_prov,
                        nama_kab,
                        nama_kec,
                        nama_desa,
                        skema,
                        no_sk,
                        tgl_sk,
                        status,
                        wilker_bps,
                        ps_id,
                        kode_prov,
                        kode_kab,
                        luas_hk,
                        luas_hl,
                        luas_hpt,
                        luas_hp,
                        luas_hpk,
                        luas_sk,
                        luas_poli,
                        luas_final,
                        jml_kk,
                        shape_leng,
                        shape_area,
                        geometry,
                        properties_raw,
                        source_file,
                        file_checksum,
                        is_active
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), %s, %s, %s, %s
                    )
                    ON CONFLICT (layer_key, feature_key)
                    DO UPDATE SET
                        feature_index = EXCLUDED.feature_index,
                        lembaga = EXCLUDED.lembaga,
                        nama_prov = EXCLUDED.nama_prov,
                        nama_kab = EXCLUDED.nama_kab,
                        nama_kec = EXCLUDED.nama_kec,
                        nama_desa = EXCLUDED.nama_desa,
                        skema = EXCLUDED.skema,
                        no_sk = EXCLUDED.no_sk,
                        tgl_sk = EXCLUDED.tgl_sk,
                        status = EXCLUDED.status,
                        wilker_bps = EXCLUDED.wilker_bps,
                        ps_id = EXCLUDED.ps_id,
                        kode_prov = EXCLUDED.kode_prov,
                        kode_kab = EXCLUDED.kode_kab,
                        luas_hk = EXCLUDED.luas_hk,
                        luas_hl = EXCLUDED.luas_hl,
                        luas_hpt = EXCLUDED.luas_hpt,
                        luas_hp = EXCLUDED.luas_hp,
                        luas_hpk = EXCLUDED.luas_hpk,
                        luas_sk = EXCLUDED.luas_sk,
                        luas_poli = EXCLUDED.luas_poli,
                        luas_final = EXCLUDED.luas_final,
                        jml_kk = EXCLUDED.jml_kk,
                        shape_leng = EXCLUDED.shape_leng,
                        shape_area = EXCLUDED.shape_area,
                        geometry = EXCLUDED.geometry,
                        properties_raw = EXCLUDED.properties_raw,
                        source_file = EXCLUDED.source_file,
                        file_checksum = EXCLUDED.file_checksum,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """,
                    params,
                )

        return len(params)

    def deactivate_missing_polygons(self, layer_key: str, active_feature_keys: Sequence[str]) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                if active_feature_keys:
                    cur.execute(
                        """
                        UPDATE polygon_metadata
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE layer_key = %s
                          AND is_active = TRUE
                          AND NOT (feature_key = ANY(%s))
                        """,
                        (layer_key, list(active_feature_keys)),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE polygon_metadata
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE layer_key = %s
                          AND is_active = TRUE
                        """,
                        (layer_key,),
                    )
                return cur.rowcount

    def read_history_archive(self, year: int, layer_key: str) -> dict[str, object] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        coverage_start,
                        coverage_end,
                        satellites,
                        hotspot_count,
                        payload
                    FROM hotspot_history_archives
                    WHERE archive_year = %s AND layer_key = %s
                    """,
                    (year, layer_key),
                )
                row = cur.fetchone()

        if not row:
            return None

        payload = _safe_json(row.get("payload"), {"hotspots": []})
        hotspots = payload.get("hotspots", []) if isinstance(payload, dict) else []
        satellites = _safe_json(row.get("satellites"), [])
        return {
            "coverage_start": row["coverage_start"].isoformat(),
            "coverage_end": row["coverage_end"].isoformat(),
            "satellites": satellites,
            "hotspots": hotspots,
            "hotspot_count": row.get("hotspot_count", len(hotspots)),
        }

    def write_history_archive(
        self,
        *,
        year: int,
        layer_key: str,
        coverage_start: str,
        coverage_end: str,
        satellites: list[str],
        hotspots: list[dict],
    ) -> None:
        payload = {"hotspots": hotspots}
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hotspot_history_archives (
                        archive_year,
                        layer_key,
                        satellites,
                        coverage_start,
                        coverage_end,
                        hotspot_count,
                        payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (archive_year, layer_key)
                    DO UPDATE SET
                        satellites = EXCLUDED.satellites,
                        coverage_start = EXCLUDED.coverage_start,
                        coverage_end = EXCLUDED.coverage_end,
                        hotspot_count = EXCLUDED.hotspot_count,
                        payload = EXCLUDED.payload,
                        updated_at = NOW()
                    """,
                    (
                        year,
                        layer_key,
                        Json(satellites),
                        coverage_start,
                        coverage_end,
                        len(hotspots),
                        Json(payload),
                    ),
                )

    def read_cache_entry(self, key: str) -> list[dict] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload, expires_at
                    FROM api_cache_entries
                    WHERE cache_key = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()

        if not row:
            return None

        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return None

        payload = _safe_json(row.get("payload"), [])
        return payload if isinstance(payload, list) else None

    def write_cache_entry(self, key: str, payload: list[dict], ttl_hours: int) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO api_cache_entries (cache_key, payload, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (cache_key)
                    DO UPDATE SET
                        payload = EXCLUDED.payload,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """,
                    (key, Json(payload), expires_at),
                )

    def clear_cache_entries(self) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM api_cache_entries", ())
                return int(getattr(cur, "rowcount", 0) or 0)

    def _ensure_hotspot_sync_state_table(self, conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hotspot_sync_state (
                    sync_key TEXT PRIMARY KEY,
                    last_hotspot_sync_at TIMESTAMPTZ,
                    last_hotspot_sync_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            # Add columns if they do not exist
            cur.execute("ALTER TABLE hotspot_sync_state ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE hotspot_sync_state ADD COLUMN IF NOT EXISTS last_sync_result JSONB")
            cur.execute("ALTER TABLE hotspot_sync_state ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0")
            cur.execute("ALTER TABLE hotspot_sync_state ADD COLUMN IF NOT EXISTS last_hotspot_fingerprints JSONB")
            cur.execute("ALTER TABLE hotspot_sync_state ADD COLUMN IF NOT EXISTS last_new_hotspot_count INTEGER DEFAULT 0")

    def record_hotspot_sync(
        self,
        *,
        hotspot_count: int,
        synced_at: datetime | None = None,
    ) -> None:
        if synced_at is None:
            synced_at = datetime.now(timezone.utc)

        with self.connection() as conn:
            self._ensure_hotspot_sync_state_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hotspot_sync_state (
                        sync_key,
                        last_hotspot_sync_at,
                        last_hotspot_sync_count
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (sync_key)
                    DO UPDATE SET
                        last_hotspot_sync_at = EXCLUDED.last_hotspot_sync_at,
                        last_hotspot_sync_count = EXCLUDED.last_hotspot_sync_count,
                        updated_at = NOW()
                    """,
                    ("nasa_hotspot", synced_at, hotspot_count),
                )

    def read_hotspot_sync_state(self) -> dict[str, object] | None:
        with self.connection() as conn:
            self._ensure_hotspot_sync_state_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        last_hotspot_sync_at,
                        last_hotspot_sync_count
                    FROM hotspot_sync_state
                    WHERE sync_key = %s
                    """,
                    ("nasa_hotspot",),
                )
                row = cur.fetchone()

        if not row:
            return None

        synced_at = row["last_hotspot_sync_at"]
        return {
            "last_hotspot_sync_at": synced_at.isoformat() if synced_at else None,
            "last_hotspot_sync_count": int(row.get("last_hotspot_sync_count", 0)),
        }

    def save_scheduler_metrics(
        self,
        *,
        last_sync_result: dict,
        last_sync_at: datetime | None,
        last_successful_sync_at: datetime | None,
        consecutive_failures: int,
        last_new_hotspot_count: int,
        last_hotspot_fingerprints: list[str] | None,
    ) -> None:
        with self.connection() as conn:
            self._ensure_hotspot_sync_state_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hotspot_sync_state (
                        sync_key,
                        last_hotspot_sync_at,
                        last_hotspot_sync_count,
                        last_sync_at,
                        last_sync_result,
                        consecutive_failures,
                        last_new_hotspot_count,
                        last_hotspot_fingerprints
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (sync_key)
                    DO UPDATE SET
                        last_hotspot_sync_at = EXCLUDED.last_hotspot_sync_at,
                        last_hotspot_sync_count = EXCLUDED.last_hotspot_sync_count,
                        last_sync_at = EXCLUDED.last_sync_at,
                        last_sync_result = EXCLUDED.last_sync_result,
                        consecutive_failures = EXCLUDED.consecutive_failures,
                        last_new_hotspot_count = EXCLUDED.last_new_hotspot_count,
                        last_hotspot_fingerprints = EXCLUDED.last_hotspot_fingerprints,
                        updated_at = NOW()
                    """,
                    (
                        "nasa_hotspot",
                        last_successful_sync_at,
                        int(last_sync_result.get("hotspot_count", 0) or 0),
                        last_sync_at,
                        Json(last_sync_result),
                        consecutive_failures,
                        last_new_hotspot_count,
                        Json(last_hotspot_fingerprints) if last_hotspot_fingerprints is not None else None,
                    ),
                )

    def read_scheduler_metrics(self) -> dict[str, object] | None:
        with self.connection() as conn:
            self._ensure_hotspot_sync_state_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        last_hotspot_sync_at,
                        last_sync_at,
                        last_sync_result,
                        consecutive_failures,
                        last_new_hotspot_count,
                        last_hotspot_fingerprints
                    FROM hotspot_sync_state
                    WHERE sync_key = %s
                    """,
                    ("nasa_hotspot",),
                )
                row = cur.fetchone()

        if not row:
            return None

        last_sync_result = _safe_json(row.get("last_sync_result"), {})
        last_hotspot_fingerprints = _safe_json(row.get("last_hotspot_fingerprints"), None)

        return {
            "last_successful_sync_at": row.get("last_hotspot_sync_at"),
            "last_sync_at": row.get("last_sync_at"),
            "last_sync_result": last_sync_result,
            "consecutive_failures": int(row.get("consecutive_failures", 0) or 0),
            "last_new_hotspot_count": int(row.get("last_new_hotspot_count", 0) or 0),
            "last_hotspot_fingerprints": last_hotspot_fingerprints,
        }

    def upsert_hotspot_observations(self, hotspots: list[dict]) -> None:
        if not hotspots:
            return

        records = []
        for hotspot in hotspots:
            records.append(
                (
                    str(hotspot.get("source", "")),
                    str(hotspot.get("satellite", "")),
                    float(hotspot["latitude"]),
                    float(hotspot["longitude"]),
                    hotspot.get("brightness"),
                    hotspot.get("confidence"),
                    str(hotspot.get("detected_at", "")),
                    hotspot.get("layer_id"),
                    hotspot.get("layer_name"),
                    hotspot.get("agency_name"),
                    Json(hotspot),
                )
            )

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO hotspot_observations (
                        source,
                        satellite,
                        latitude,
                        longitude,
                        brightness,
                        confidence,
                        detected_at,
                        layer_key,
                        layer_name,
                        agency_name,
                        geom,
                        raw_payload
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                        %s
                    )
                    ON CONFLICT (
                        source,
                        satellite,
                        latitude,
                        longitude,
                        detected_at,
                        COALESCE(layer_key, '')
                    )
                    DO UPDATE SET
                        brightness = EXCLUDED.brightness,
                        confidence = EXCLUDED.confidence,
                        layer_name = EXCLUDED.layer_name,
                        agency_name = EXCLUDED.agency_name,
                        geom = EXCLUDED.geom,
                        raw_payload = EXCLUDED.raw_payload
                    """,
                    [
                        (
                            source,
                            satellite,
                            latitude,
                            longitude,
                            brightness,
                            confidence,
                            detected_at,
                            layer_key,
                            layer_name,
                            agency_name,
                            longitude,
                            latitude,
                            raw_payload,
                        )
                        for (
                            source,
                            satellite,
                            latitude,
                            longitude,
                            brightness,
                            confidence,
                            detected_at,
                            layer_key,
                            layer_name,
                            agency_name,
                            raw_payload,
                        ) in records
                    ],
                )

    def read_hotspot_observation_records(self, hotspots: Sequence[dict]) -> list[dict[str, object]]:
        if not hotspots:
            return []

        records: list[dict[str, object]] = []
        with self.connection() as conn:
            with conn.cursor() as cur:
                for hotspot in hotspots:
                    cur.execute(
                        """
                        SELECT id, source, satellite, latitude, longitude, detected_at, layer_key
                        FROM hotspot_observations
                        WHERE source = %s
                          AND satellite = %s
                          AND latitude = %s
                          AND longitude = %s
                          AND detected_at = %s
                          AND COALESCE(layer_key, '') = COALESCE(%s, '')
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (
                            str(hotspot.get("source", "")),
                            str(hotspot.get("satellite", "")),
                            float(hotspot["latitude"]),
                            float(hotspot["longitude"]),
                            hotspot["detected_at"],
                            hotspot.get("layer_id"),
                        ),
                    )
                    row = cur.fetchone()
                    if row:
                        records.append(row)

        return records

    def read_polygon_metadata_ids(
        self,
        *,
        layer_key: str,
        feature_keys: Sequence[str],
    ) -> dict[str, int]:
        if not feature_keys:
            return {}

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, feature_key
                    FROM polygon_metadata
                    WHERE layer_key = %s
                      AND feature_key = ANY(%s)
                    """,
                    (layer_key, list(feature_keys)),
                )
                rows = cur.fetchall()

        return {str(row["feature_key"]): int(row["id"]) for row in rows}

    def read_polygon_metadata_ids_by_index(
        self,
        *,
        layer_key: str,
        feature_indices: Sequence[int],
    ) -> dict[int, int]:
        if not feature_indices:
            return {}

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, feature_index
                    FROM polygon_metadata
                    WHERE layer_key = %s
                      AND feature_index = ANY(%s)
                    """,
                    (layer_key, list(feature_indices)),
                )
                rows = cur.fetchall()

        return {int(row["feature_index"]): int(row["id"]) for row in rows}

    def read_active_polygon_metadata_ids(self, layer_keys: Sequence[str] | None = None) -> list[int]:
        params: tuple[object, ...] = ()
        where_clause = "WHERE is_active = TRUE"
        if layer_keys:
            unique_layer_keys = [str(layer_key) for layer_key in dict.fromkeys(layer_keys)]
            where_clause = "WHERE is_active = TRUE AND layer_key = ANY(%s)"
            params = (unique_layer_keys,)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id
                    FROM polygon_metadata
                    {where_clause}
                    ORDER BY layer_key ASC, feature_index ASC, id ASC
                    """,
                    params,
                )
                rows = cur.fetchall()

        return [int(row["id"]) for row in rows]

    def refresh_polygon_hotspot_summaries(self, layer_keys: Sequence[str] | None = None) -> dict[str, int]:
        active_polygon_ids = self.read_active_polygon_metadata_ids(layer_keys=layer_keys)
        pruned_count = 0

        with self.connection() as conn:
            with conn.cursor() as cur:
                delete_queries = [
                    "DELETE FROM polygon_hotspot_summary s WHERE NOT EXISTS (SELECT 1 FROM polygon_metadata p WHERE p.id = s.polygon_metadata_id)",
                    """
                    DELETE FROM polygon_hotspot_summary s
                    USING polygon_metadata p
                    WHERE s.polygon_metadata_id = p.id
                      AND p.is_active = FALSE
                    """,
                ]

                for query in delete_queries:
                    cur.execute(query, ())
                    pruned_count += int(getattr(cur, "rowcount", 0) or 0)

        rebuilt_count = self.rebuild_polygon_hotspot_summary(active_polygon_ids)
        return {
            "active_polygon_count": len(active_polygon_ids),
            "pruned": pruned_count,
            "rebuilt": rebuilt_count,
        }

    def upsert_hotspot_polygon_relation(self, relations: Sequence[dict[str, Any]]) -> int:
        if not relations:
            return 0

        params = [
            (
                int(relation["hotspot_observation_id"]),
                int(relation["polygon_metadata_id"]),
                str(relation["layer_key"]),
                str(relation.get("match_method", "contains")),
            )
            for relation in relations
        ]

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO hotspot_polygon_relation (
                        hotspot_observation_id,
                        polygon_metadata_id,
                        layer_key,
                        match_method
                    )
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (hotspot_observation_id, polygon_metadata_id)
                    DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        match_method = EXCLUDED.match_method,
                        matched_at = NOW()
                    """,
                    params,
                )

    def intersect_hotspots_for_layer(self, layer_key: str) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                # 1. Insert relations
                cur.execute(
                    """
                    INSERT INTO hotspot_polygon_relation (
                        hotspot_observation_id,
                        polygon_metadata_id,
                        layer_key,
                        match_method
                    )
                    SELECT
                        obs.id AS hotspot_observation_id,
                        poly.id AS polygon_metadata_id,
                        poly.layer_key AS layer_key,
                        'contains' AS match_method
                    FROM polygon_metadata poly
                    JOIN hotspot_observations obs ON ST_Contains(poly.geometry, obs.geom)
                    WHERE poly.layer_key = %s
                      AND poly.is_active = TRUE
                    ON CONFLICT (hotspot_observation_id, polygon_metadata_id) DO NOTHING
                    """,
                    (layer_key,),
                )
                relation_count = getattr(cur, "rowcount", 0) or 0

                # 2. Get all polygon IDs of this layer to rebuild summary
                cur.execute(
                    """
                    SELECT id FROM polygon_metadata
                    WHERE layer_key = %s AND is_active = TRUE
                    """,
                    (layer_key,),
                )
                rows = cur.fetchall()
                polygon_ids = [int(row["id"]) for row in rows if row.get("id") is not None]

        if polygon_ids:
            self.rebuild_polygon_hotspot_summary(polygon_ids)

        return relation_count

    def rebuild_polygon_hotspot_summary(self, polygon_metadata_ids: Sequence[int]) -> int:
        unique_ids = [int(polygon_metadata_id) for polygon_metadata_id in dict.fromkeys(polygon_metadata_ids)]
        if not unique_ids:
            return 0

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM polygon_hotspot_summary
                    WHERE polygon_metadata_id = ANY(%s)
                    """,
                    (unique_ids,),
                )
                cur.execute(
                    """
                    WITH aggregated AS (
                        SELECT
                            p.id AS polygon_metadata_id,
                            p.layer_key,
                            EXTRACT(YEAR FROM obs.detected_at)::int AS year,
                            MIN(obs.detected_at) AS start_at,
                            MAX(obs.detected_at) AS end_at,
                            COUNT(*)::int AS hotspot_count,
                            MAX(obs.detected_at) AS last_hotspot_at,
                            to_jsonb(ARRAY_AGG(DISTINCT obs.source)) AS sources,
                            to_jsonb(ARRAY_AGG(DISTINCT obs.satellite)) AS satellites
                        FROM polygon_metadata p
                        JOIN hotspot_observations obs
                          ON obs.layer_key = p.layer_key
                         AND ST_Covers(p.geometry, obs.geom)
                        WHERE p.id = ANY(%s)
                          AND p.is_active = TRUE
                          AND obs.geom IS NOT NULL
                        GROUP BY p.id, p.layer_key, EXTRACT(YEAR FROM obs.detected_at)
                    )
                    INSERT INTO polygon_hotspot_summary (
                        polygon_metadata_id,
                        layer_key,
                        year,
                        start_at,
                        end_at,
                        hotspot_count,
                        last_hotspot_at,
                        sources,
                        satellites
                    )
                    SELECT
                        polygon_metadata_id,
                        layer_key,
                        year,
                        start_at,
                        end_at,
                        hotspot_count,
                        last_hotspot_at,
                        COALESCE(sources, '[]'::jsonb),
                        COALESCE(satellites, '[]'::jsonb)
                    FROM aggregated
                    ON CONFLICT (polygon_metadata_id, year)
                    DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        start_at = EXCLUDED.start_at,
                        end_at = EXCLUDED.end_at,
                        hotspot_count = EXCLUDED.hotspot_count,
                        last_hotspot_at = EXCLUDED.last_hotspot_at,
                        sources = EXCLUDED.sources,
                        satellites = EXCLUDED.satellites,
                        updated_at = NOW()
                    """,
                    (unique_ids,),
                )
                return cur.rowcount

    def read_polygon_hotspot_summary(
        self,
        polygon_metadata_ids: Sequence[int] | None = None,
    ) -> list[dict[str, object]]:
        params: tuple[object, ...] = ()
        where_clause = ""
        if polygon_metadata_ids:
            unique_ids = [int(polygon_metadata_id) for polygon_metadata_id in dict.fromkeys(polygon_metadata_ids)]
            where_clause = "WHERE s.polygon_metadata_id = ANY(%s)"
            params = (unique_ids,)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        s.polygon_metadata_id,
                        s.layer_key,
                        s.year,
                        s.start_at,
                        s.end_at,
                        s.hotspot_count,
                        s.last_hotspot_at,
                        s.sources,
                        s.satellites,
                        p.feature_key,
                        p.lembaga,
                        p.nama_prov,
                        p.nama_kab,
                        p.nama_kec,
                        p.nama_desa,
                        p.ps_id,
                        p.luas_final,
                        p.properties_raw
                    FROM polygon_hotspot_summary s
                    JOIN polygon_metadata p
                      ON p.id = s.polygon_metadata_id
                    {where_clause}
                    ORDER BY s.layer_key ASC, s.year DESC, p.feature_index ASC
                    """,
                    params,
                )
                rows = cur.fetchall()

        summaries: list[dict[str, object]] = []
        for row in rows:
            summaries.append(
                {
                    "polygon_metadata_id": int(row["polygon_metadata_id"]),
                    "layer_key": str(row["layer_key"]),
                    "year": int(row["year"]),
                    "start_at": row["start_at"].isoformat() if row.get("start_at") else None,
                    "end_at": row["end_at"].isoformat() if row.get("end_at") else None,
                    "hotspot_count": int(row.get("hotspot_count", 0)),
                    "last_hotspot_at": row["last_hotspot_at"].isoformat() if row.get("last_hotspot_at") else None,
                    "sources": _safe_json(row.get("sources"), []),
                    "satellites": _safe_json(row.get("satellites"), []),
                    "polygon_metadata": {
                        "feature_key": row.get("feature_key"),
                        "LEMBAGA": row.get("lembaga"),
                        "NAMA_PROV": row.get("nama_prov"),
                        "NAMA_KAB": row.get("nama_kab"),
                        "NAMA_KEC": row.get("nama_kec"),
                        "NAMA_DESA": row.get("nama_desa"),
                        "PS_ID": row.get("ps_id"),
                        "LuasFinal": row.get("luas_final"),
                        "properties_raw": _safe_json(row.get("properties_raw"), {}),
                    },
                }
            )

        return summaries

    def storage_status(self) -> dict[str, object]:
        if not self.enabled:
            return {
                "database_enabled": False,
                "database_url_present": False,
                "tables": {},
            }

        with self.connection() as conn:
            self._ensure_hotspot_sync_state_table(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS total FROM layers")
                layers_total = int(cur.fetchone()["total"])
                cur.execute("SELECT COUNT(*) AS total FROM geojson_file_registry")
                geojson_registry_total = int(cur.fetchone()["total"])
                cur.execute("SELECT COUNT(*) AS total FROM hotspot_history_archives")
                history_total = int(cur.fetchone()["total"])
                cur.execute("SELECT COUNT(*) AS total FROM api_cache_entries")
                cache_total = int(cur.fetchone()["total"])
                cur.execute("SELECT COUNT(*) AS total FROM hotspot_observations")
                observations_total = int(cur.fetchone()["total"])
                cur.execute("SELECT COUNT(*) AS total FROM hotspot_sync_state")
                sync_state_total = int(cur.fetchone()["total"])
                cur.execute(
                    """
                    SELECT last_hotspot_sync_at, last_hotspot_sync_count
                    FROM hotspot_sync_state
                    WHERE sync_key = %s
                    """,
                    ("nasa_hotspot",),
                )
                sync_state = cur.fetchone()

        last_hotspot_sync_at = None
        last_hotspot_sync_count = 0
        if sync_state:
            synced_at = sync_state.get("last_hotspot_sync_at")
            if synced_at is not None:
                last_hotspot_sync_at = synced_at.isoformat()
            last_hotspot_sync_count = int(sync_state.get("last_hotspot_sync_count", 0))

        return {
            "database_enabled": True,
            "database_url_present": True,
            "last_hotspot_sync_at": last_hotspot_sync_at,
            "last_hotspot_sync_count": last_hotspot_sync_count,
            "tables": {
                "layers": layers_total,
                "geojson_file_registry": geojson_registry_total,
                "hotspot_history_archives": history_total,
                "api_cache_entries": cache_total,
                "hotspot_observations": observations_total,
                "hotspot_sync_state": sync_state_total,
            },
        }

    def read_hotspot_observations(
        self,
        *,
        start_date: str,
        end_date: str,
        sources: list[str],
        layer_ids: list[str],
    ) -> list[dict]:
        if not sources or not layer_ids:
            return []

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH ranked_relation AS (
                        SELECT DISTINCT ON (obs.id)
                            obs.id AS observation_id,
                            obs.raw_payload,
                            p.id AS polygon_metadata_id,
                            p.feature_key,
                            p.feature_index,
                            p.lembaga,
                            p.nama_prov,
                            p.nama_kab,
                            p.nama_kec,
                            p.nama_desa,
                            p.skema,
                            p.no_sk,
                            p.tgl_sk,
                            p.status,
                            p.wilker_bps,
                            p.ps_id,
                            p.kode_prov,
                            p.kode_kab,
                            p.luas_hk,
                            p.luas_hl,
                            p.luas_hpt,
                            p.luas_hp,
                            p.luas_hpk,
                            p.luas_sk,
                            p.luas_poli,
                            p.luas_final,
                            p.jml_kk,
                            p.shape_leng,
                            p.shape_area,
                            p.properties_raw
                        FROM hotspot_observations obs
                        JOIN polygon_metadata p
                          ON p.layer_key = obs.layer_key
                         AND p.is_active = TRUE
                         AND ST_Covers(p.geometry, obs.geom)
                        WHERE obs.detected_at >= %s::timestamptz AND obs.detected_at < %s::timestamptz
                          AND obs.source = ANY(%s)
                          AND obs.layer_key = ANY(%s)
                          AND obs.geom IS NOT NULL
                        ORDER BY obs.id ASC, p.feature_index ASC, p.id ASC
                    )
                    SELECT *
                    FROM ranked_relation
                    ORDER BY observation_id ASC
                    """,
                    (start_date, end_date, sources, layer_ids),
                )
                rows = cur.fetchall()

        payloads: list[dict] = []
        for row in rows:
            payload = _safe_json(row.get("raw_payload"), {})
            if isinstance(payload, dict):
                orig_metadata = payload.get("polygon_metadata") or {}
                polygon_metadata = {
                    "polygon_metadata_id": row.get("polygon_metadata_id"),
                    "feature_key": row.get("feature_key"),
                    "LEMBAGA": row.get("lembaga"),
                    "NAMA_PROV": row.get("nama_prov"),
                    "NAMA_KAB": row.get("nama_kab"),
                    "NAMA_KEC": row.get("nama_kec"),
                    "NAMA_DESA": row.get("nama_desa"),
                    "SKEMA": row.get("skema"),
                    "NO_SK": row.get("no_sk"),
                    "TGL_SK": row.get("tgl_sk"),
                    "Status": row.get("status"),
                    "WILKER_BPS": row.get("wilker_bps"),
                    "PS_ID": row.get("ps_id"),
                    "KODE_PROV": row.get("kode_prov"),
                    "KODE_KAB": row.get("kode_kab"),
                    "Luas_HK": row.get("luas_hk"),
                    "LUAS_HL": row.get("luas_hl"),
                    "LUAS_HPT": row.get("luas_hpt"),
                    "LUAS_HP": row.get("luas_hp"),
                    "LUAS_HPK": row.get("luas_hpk"),
                    "LUAS_SK": row.get("luas_sk"),
                    "Luas_Poli": row.get("luas_poli"),
                    "LuasFinal": row.get("luas_final"),
                    "Jml_KK": row.get("jml_kk"),
                    "Shape_Leng": row.get("shape_leng"),
                    "Shape_Area": row.get("shape_area"),
                    "properties_raw": _safe_json(row.get("properties_raw"), {}),
                }
                db_metadata = {
                    key: value
                    for key, value in polygon_metadata.items()
                    if value is not None and value != ""
                }
                merged_metadata = {**orig_metadata, **db_metadata}
                payload["polygon_metadata"] = merged_metadata
                payloads.append(payload)
        return payloads
