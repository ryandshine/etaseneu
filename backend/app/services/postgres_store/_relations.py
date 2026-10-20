"""Relasi hotspot <-> polygon: ringkasan agregat per polygon per tahun + upsert relasi.

Pencocokan spasial ada di ``_hotspot_match`` (satu definisi "di dalam" untuk semua jalur)."""

import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from ._base import _safe_json
from ._hotspot_match import (
    ANALYSIS_TIMEZONE,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    SUMMARY_ADVISORY_LOCK_KEY,
    _set_local_timeouts,
    pairs_cte_sql,
)

logger = logging.getLogger("hotspot.postgres")


class _PolygonRelationMixin:
    def ensure_performance_indexes(self) -> None:
        """Memastikan indeks relasi dan performa penting telah dibuat (idempotent)."""
        statements = [
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            "CREATE INDEX IF NOT EXISTS idx_hpr_polygon_metadata_id ON hotspot_polygon_relation (polygon_metadata_id);",
            "CREATE INDEX IF NOT EXISTS idx_polygon_metadata_layer_active ON polygon_metadata (layer_key, is_active);",
            "CREATE INDEX IF NOT EXISTS idx_polygon_metadata_wilker_bps ON polygon_metadata (wilker_bps);",
            "CREATE INDEX IF NOT EXISTS idx_polygon_metadata_nama_kab ON polygon_metadata (nama_kab);",
            "CREATE INDEX IF NOT EXISTS idx_polygon_metadata_nama_prov ON polygon_metadata (nama_prov);",
            "CREATE INDEX IF NOT EXISTS idx_polygon_metadata_lembaga_trgm ON polygon_metadata USING gin (lembaga gin_trgm_ops);",
            "CREATE INDEX IF NOT EXISTS idx_polygon_metadata_desa_trgm ON polygon_metadata USING gin (nama_desa gin_trgm_ops);",
            "CREATE INDEX IF NOT EXISTS idx_polygon_metadata_no_sk_trgm ON polygon_metadata USING gin (no_sk gin_trgm_ops);",
            "CREATE INDEX IF NOT EXISTS idx_hotspots_layer_detected ON hotspot_observations (layer_key, detected_at DESC);",
            "CREATE INDEX IF NOT EXISTS idx_hotspots_source_detected ON hotspot_observations (source, detected_at DESC);",
        ]
        with self.connection() as conn:
            with conn.cursor() as cur:
                for sql in statements:
                    try:
                        cur.execute(sql)
                    except Exception as e:
                        logger.warning("Gagal membuat index performa: %s (%s)", sql, e)

    def refresh_polygon_hotspot_summaries(self, layer_keys: Sequence[str] | None = None) -> dict[str, int]:
        """Refresh PENUH: baris ringkasan basi dibuang, relasi dilengkapi, ringkasan dibangun ulang.

        Urutan sengaja relasi -> ringkasan: kalau rekonsiliasi relasi gagal, exception naik dan
        ringkasan lama tidak diganti. Semua nilai balikan bertipe int (dipakai sebagai response
        model ``dict[str, int]`` di endpoint admin).
        """
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

        relation = self._reconcile_full_range(layer_keys)
        rebuilt_count = self.rebuild_polygon_hotspot_summary(active_polygon_ids)
        return {
            "active_polygon_count": len(active_polygon_ids),
            "pruned": pruned_count,
            "rebuilt": rebuilt_count,
            "relation_spatial_pairs": int(relation.get("spatial_pairs", 0)),
            "relation_inserted": int(relation.get("inserted", 0)),
            "relation_updated": int(relation.get("updated", 0)),
        }

    def _reconcile_full_range(self, layer_keys: Sequence[str] | None = None) -> dict[str, Any]:
        """Rekonsiliasi relasi untuk SELURUH rentang observasi (pada poligon di ``layer_keys``)."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(detected_at) AS first_at, MAX(detected_at) AS last_at FROM hotspot_observations")
                row = cur.fetchone() or {}
        if not row.get("first_at"):
            return {"spatial_pairs": 0, "inserted": 0, "updated": 0, "polygon_ids": []}
        return self.reconcile_hotspot_polygon_relations(
            start_at=row["first_at"],
            end_at=row["last_at"] + timedelta(seconds=1),
            layer_keys=layer_keys,
        )

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
        """Lengkapi relasi untuk poligon aktif di ``layer_key`` (seluruh rentang), lalu ringkasannya.

        Dipanggil sesudah sinkron GeoJSON. Memakai mesin pencocokan yang sama dengan ingest
        (``ST_Covers`` + geometri valid, tanpa syarat ``layer_key`` observasi).
        """
        relation = self._reconcile_full_range([layer_key])
        polygon_ids = self.read_active_polygon_metadata_ids(layer_keys=[layer_key])
        if polygon_ids:
            self.rebuild_polygon_hotspot_summary(polygon_ids)
        return int(relation.get("inserted", 0)) + int(relation.get("updated", 0))

    def rebuild_polygon_hotspot_summary(
        self,
        polygon_metadata_ids: Sequence[int],
        *,
        years: Sequence[int] | None = None,
    ) -> int:
        """Bangun ulang ringkasan (grain: satu poligon aktif per tahun WIB) secara atomik.

        ``hotspot_count`` = jumlah observasi UNIK yang berada di dalam poligon pada tahun itu;
        ``start_at``/``end_at``/``last_hotspot_at``/``sources``/``satellites`` dihitung dari
        himpunan observasi yang SAMA. ``sources``/``satellites`` adalah DAFTAR nilai berbeda
        (terurut), bukan jumlah per sumber. Dihitung langsung dari geometri poligon saat ini
        (bukan dari tabel relasi) lewat mesin pencocokan bersama. DELETE + INSERT dalam satu
        transaksi: pembaca melihat ringkasan lama atau baru, tidak pernah setengah-setengah.
        """
        unique_ids = [int(polygon_metadata_id) for polygon_metadata_id in dict.fromkeys(polygon_metadata_ids)]
        if not unique_ids:
            return 0

        params: dict[str, Any] = {"polygon_ids": unique_ids, "tz": ANALYSIS_TIMEZONE}
        year_delete_filter = ""
        observation_filter = ""
        if years is not None:
            params["years"] = [int(year) for year in years]
            year_delete_filter = " AND year = ANY(%(years)s)"
            observation_filter = (
                "AND EXTRACT(YEAR FROM obs.detected_at AT TIME ZONE %(tz)s)::int = ANY(%(years)s)"
            )

        delete_sql = (
            "DELETE FROM polygon_hotspot_summary "
            "WHERE polygon_metadata_id = ANY(%(polygon_ids)s)" + year_delete_filter
        )
        insert_sql = f"""
            WITH {pairs_cte_sql(polygon_filter="AND p.id = ANY(%(polygon_ids)s)", observation_filter=observation_filter)},
            aggregated AS (
                SELECT
                    polygon_id AS polygon_metadata_id,
                    polygon_layer_key AS layer_key,
                    EXTRACT(YEAR FROM detected_at AT TIME ZONE %(tz)s)::int AS year,
                    MIN(detected_at) AS start_at,
                    MAX(detected_at) AS end_at,
                    COUNT(DISTINCT observation_id)::int AS hotspot_count,
                    MAX(detected_at) AS last_hotspot_at,
                    to_jsonb(ARRAY_AGG(DISTINCT source ORDER BY source)) AS sources,
                    to_jsonb(ARRAY_AGG(DISTINCT satellite ORDER BY satellite)) AS satellites
                FROM pairs
                GROUP BY polygon_id, polygon_layer_key, EXTRACT(YEAR FROM detected_at AT TIME ZONE %(tz)s)
            )
            INSERT INTO polygon_hotspot_summary (
                polygon_metadata_id, layer_key, year, start_at, end_at,
                hotspot_count, last_hotspot_at, sources, satellites
            )
            SELECT
                polygon_metadata_id, layer_key, year, start_at, end_at,
                hotspot_count, last_hotspot_at,
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
        """

        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    _set_local_timeouts(cur, DEFAULT_STATEMENT_TIMEOUT_MS, lock_timeout_ms=30_000)
                    cur.execute("SELECT pg_advisory_xact_lock(%s)", (SUMMARY_ADVISORY_LOCK_KEY,))
                    cur.execute(delete_sql, params)
                    cur.execute(insert_sql, params)
                    return int(cur.rowcount or 0)

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
