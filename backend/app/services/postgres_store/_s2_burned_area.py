"""Estimasi bekas terbakar dari Sentinel-2 dNBR (analisis mandiri sistem).

TERPISAH dari `burned_area_summary` (rekap resmi KLHK). Tabel ini menampung
poligon bekas terbakar yang DIHITUNG SENDIRI oleh sistem lewat Google Earth
Engine (`burned_area_s2_service.py`) untuk bulan berjalan -- supaya tidak
perlu menunggu rekap KLHK yang telat ~1 bulan. Angkanya **estimasi, belum
terverifikasi**; jangan dicampur ke agregat resmi.
"""

import json
from collections.abc import Sequence


class _S2BurnedAreaMixin:
    def _ensure_s2_burned_area_table(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS s2_burned_area (
                    id BIGSERIAL PRIMARY KEY,
                    polygon_metadata_id BIGINT NOT NULL
                        REFERENCES polygon_metadata(id),
                    layer_key TEXT NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    area_ha DOUBLE PRECISION NOT NULL,
                    dnbr_mean DOUBLE PRECISION,
                    hotspot_count_month INTEGER NOT NULL DEFAULT 0,
                    has_hotspot BOOLEAN NOT NULL DEFAULT FALSE,
                    source TEXT NOT NULL DEFAULT 'Sentinel-2 dNBR (ETA SENEU)',
                    geometry geometry(MultiPolygon, 4326),
                    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (polygon_metadata_id, year, month)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS s2_burned_area_year_month_idx "
                "ON s2_burned_area (year, month)"
            )

    def read_active_polygons_for_s2(
        self, provinces: Sequence[str] | None = None
    ) -> list[dict[str, object]]:
        """KPS + Hutan Adat aktif (id, layer_key, provinsi, geometry disederhanakan).

        `tolerance` 0.0004 (~44 m) -- cukup halus untuk clip hasil dNBR (piksel
        Sentinel-2 20 m) tapi jauh lebih ringan dari geometry mentah.
        """
        params: list[object] = []
        where = "WHERE is_active = TRUE AND layer_key IN ('psagustus2026','HUTAN_ADAT_APR26')"
        if provinces:
            where += " AND nama_prov = ANY(%s)"
            params.append([str(p) for p in provinces])
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, layer_key, nama_prov,
                           ST_AsGeoJSON(
                               COALESCE(ST_SimplifyPreserveTopology(geometry, 0.0004), geometry)
                           )::json AS geometry_json
                    FROM polygon_metadata
                    {where}
                    ORDER BY nama_prov, id
                    """,
                    params,
                )
                rows = cur.fetchall()
        out: list[dict[str, object]] = []
        for r in rows:
            geom = r.get("geometry_json")
            if geom:
                out.append(
                    {
                        "id": int(r["id"]),
                        "layer_key": r["layer_key"],
                        "nama_prov": r.get("nama_prov"),
                        "geometry": geom,
                    }
                )
        return out

    def hotspot_counts_in_polygons(
        self, polygon_ids: Sequence[int], start_iso: str, end_iso: str
    ) -> dict[int, int]:
        if not polygon_ids:
            return {}
        ids = sorted({int(p) for p in polygon_ids})
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pm.id AS pid, COUNT(*) AS n
                    FROM polygon_metadata pm
                    JOIN hotspot_observations ho
                      ON ho.detected_at >= %s AND ho.detected_at < %s
                     AND ST_Contains(pm.geometry, ho.geom)
                    WHERE pm.id = ANY(%s)
                    GROUP BY pm.id
                    """,
                    (start_iso, end_iso, ids),
                )
                rows = cur.fetchall()
        return {int(r["pid"]): int(r["n"]) for r in rows}

    def upsert_s2_burned_area(self, rows: Sequence[dict[str, object]]) -> int:
        """Simpan/perbarui estimasi bekas terbakar Sentinel-2 per poligon/bulan.

        `rows`: polygon_metadata_id, layer_key, year, month, area_ha wajib.
        Opsional: dnbr_mean, hotspot_count_month, has_hotspot, geometry_geojson.
        """
        if not rows:
            return 0
        params = [
            (
                int(r["polygon_metadata_id"]),
                str(r["layer_key"]),
                int(r["year"]),
                int(r["month"]),
                float(r["area_ha"]),
                float(r["dnbr_mean"]) if r.get("dnbr_mean") is not None else None,
                int(r.get("hotspot_count_month") or 0),
                bool(r.get("has_hotspot")),
                json.dumps(r["geometry_geojson"]) if r.get("geometry_geojson") else None,
            )
            for r in rows
        ]
        with self.connection() as conn:
            self._ensure_s2_burned_area_table(conn)
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO s2_burned_area (
                        polygon_metadata_id, layer_key, year, month, area_ha,
                        dnbr_mean, hotspot_count_month, has_hotspot, geometry, computed_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)),
                        NOW()
                    )
                    ON CONFLICT (polygon_metadata_id, year, month)
                    DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        area_ha = EXCLUDED.area_ha,
                        dnbr_mean = EXCLUDED.dnbr_mean,
                        hotspot_count_month = EXCLUDED.hotspot_count_month,
                        has_hotspot = EXCLUDED.has_hotspot,
                        geometry = EXCLUDED.geometry,
                        computed_at = NOW()
                    """,
                    params,
                )
        return len(params)

    def clear_s2_burned_area(
        self, year: int, month: int, provinces: Sequence[str] | None = None
    ) -> int:
        with self.connection() as conn:
            self._ensure_s2_burned_area_table(conn)
            with conn.cursor() as cur:
                if provinces:
                    cur.execute(
                        """
                        DELETE FROM s2_burned_area s
                        USING polygon_metadata pm
                        WHERE s.polygon_metadata_id = pm.id
                          AND s.year = %s AND s.month = %s
                          AND pm.nama_prov = ANY(%s)
                        """,
                        (year, month, [str(p) for p in provinces]),
                    )
                else:
                    cur.execute(
                        "DELETE FROM s2_burned_area WHERE year = %s AND month = %s",
                        (year, month),
                    )
                return cur.rowcount

    def read_s2_burned_area_for_polygons(
        self, polygon_ids: Sequence[int]
    ) -> list[dict[str, object]]:
        """Baris estimasi Sentinel-2 untuk KPS tertentu (semua bulan), berikut
        geometri poligonnya -- dipakai kartu Detail KPS."""
        if not polygon_ids:
            return []
        ids = sorted({int(p) for p in polygon_ids})
        with self.connection() as conn:
            self._ensure_s2_burned_area_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.polygon_metadata_id, s.layer_key, s.year, s.month,
                           s.area_ha, s.hotspot_count_month, s.has_hotspot, s.computed_at,
                           ST_AsGeoJSON(s.geometry)::json AS geometry_json,
                           khutan.rincian AS kawasan_rincian,
                           khutan.dominan AS kawasan_dominan
                    FROM s2_burned_area s
                    LEFT JOIN LATERAL (
                        SELECT
                            jsonb_agg(jsonb_build_object(
                                'kode', bkh.fungsikws,
                                'fungsi', COALESCE(lbl.fungsi, 'Kode ' || bkh.fungsikws::text),
                                'kelompok', bkh.kelompok,
                                'luas_ha', round(bkh.luas_ha::numeric, 2)
                            ) ORDER BY bkh.luas_ha DESC) AS rincian,
                            (SELECT bkh2.kelompok FROM burned_kawasan_hutan bkh2
                               WHERE bkh2.burned_id = s.id
                               ORDER BY bkh2.luas_ha DESC LIMIT 1) AS dominan
                        FROM burned_kawasan_hutan bkh
                        LEFT JOIN ref_fungsi_kawasan_label lbl ON lbl.kode = bkh.fungsikws
                        WHERE bkh.burned_id = s.id
                    ) khutan ON TRUE
                    WHERE s.polygon_metadata_id = ANY(%s)
                    ORDER BY s.year DESC, s.month DESC
                    """,
                    (ids,),
                )
                rows = cur.fetchall()
        return [
            {
                "polygon_metadata_id": int(r["polygon_metadata_id"]),
                "layer_key": r["layer_key"],
                "year": int(r["year"]),
                "month": int(r["month"]),
                "area_ha": round(float(r["area_ha"]), 2),
                "hotspot_count_month": int(r["hotspot_count_month"]),
                "has_hotspot": bool(r["has_hotspot"]),
                "computed_at": r["computed_at"].isoformat() if r.get("computed_at") else None,
                "geometry_json": r.get("geometry_json"),
                "kawasan_rincian": r.get("kawasan_rincian") or [],
                "kawasan_dominan": r.get("kawasan_dominan"),
            }
            for r in rows
        ]

    def read_s2_burned_area_overlay(self, year: int, month: int) -> dict[str, object]:
        with self.connection() as conn:
            self._ensure_s2_burned_area_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.polygon_metadata_id, s.area_ha, s.dnbr_mean,
                           s.hotspot_count_month, s.has_hotspot, s.computed_at,
                           pm.lembaga, pm.nama_prov, pm.nama_kab,
                           ST_AsGeoJSON(s.geometry)::json AS geometry_json,
                           khutan.rincian AS kawasan_rincian,
                           khutan.dominan AS kawasan_dominan
                    FROM s2_burned_area s
                    JOIN polygon_metadata pm ON pm.id = s.polygon_metadata_id
                    LEFT JOIN LATERAL (
                        SELECT
                            jsonb_agg(jsonb_build_object(
                                'kode', bkh.fungsikws,
                                'fungsi', COALESCE(lbl.fungsi, 'Kode ' || bkh.fungsikws::text),
                                'kelompok', bkh.kelompok,
                                'luas_ha', round(bkh.luas_ha::numeric, 2)
                            ) ORDER BY bkh.luas_ha DESC) AS rincian,
                            (SELECT bkh2.kelompok FROM burned_kawasan_hutan bkh2
                               WHERE bkh2.burned_id = s.id
                               ORDER BY bkh2.luas_ha DESC LIMIT 1) AS dominan
                        FROM burned_kawasan_hutan bkh
                        LEFT JOIN ref_fungsi_kawasan_label lbl ON lbl.kode = bkh.fungsikws
                        WHERE bkh.burned_id = s.id
                    ) khutan ON TRUE
                    WHERE s.year = %s AND s.month = %s AND s.geometry IS NOT NULL
                    ORDER BY s.area_ha DESC
                    """,
                    (year, month),
                )
                rows = cur.fetchall()
        features = [
            {
                "type": "Feature",
                "geometry": r["geometry_json"],
                "properties": {
                    "polygon_metadata_id": int(r["polygon_metadata_id"]),
                    "lembaga": r.get("lembaga"),
                    "nama_prov": r.get("nama_prov"),
                    "nama_kab": r.get("nama_kab"),
                    "area_ha": round(float(r["area_ha"]), 1),
                    "dnbr_mean": round(float(r["dnbr_mean"]), 3) if r.get("dnbr_mean") is not None else None,
                    "hotspot_count_month": int(r["hotspot_count_month"]),
                    "has_hotspot": bool(r["has_hotspot"]),
                    "computed_at": r["computed_at"].isoformat() if r.get("computed_at") else None,
                    "kawasan_rincian": r.get("kawasan_rincian") or [],
                    "kawasan_dominan": r.get("kawasan_dominan"),
                },
            }
            for r in rows
        ]
        total_ha = round(sum(f["properties"]["area_ha"] for f in features), 1)
        return {
            "type": "FeatureCollection",
            "features": features,
            "meta": {
                "year": year,
                "month": month,
                "polygons": len(features),
                "total_ha": total_ha,
                "no_hotspot_but_burned": sum(
                    1 for f in features if not f["properties"]["has_hotspot"]
                ),
            },
        }
