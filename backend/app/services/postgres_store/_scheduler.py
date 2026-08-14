"""Status sinkronisasi scheduler NASA FIRMS, dan status penyimpanan keseluruhan."""

from datetime import datetime, timezone

from ._base import Connection, Json, _safe_json


class _SchedulerMetricsMixin:
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
