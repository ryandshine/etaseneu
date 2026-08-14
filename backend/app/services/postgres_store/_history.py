"""Arsip histori hotspot tahunan per layer (dipakai untuk data tahun-tahun lalu)."""

from ._base import Json, _safe_json


class _HistoryArchiveMixin:
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
