"""Relasi hotspot <-> polygon: intersect spasial dan ringkasan agregat per polygon per tahun."""

from collections.abc import Sequence
from typing import Any

from ._base import _safe_json


class _PolygonRelationMixin:
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
