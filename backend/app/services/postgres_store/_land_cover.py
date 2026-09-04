"""Analisis tutupan lahan per poligon KPS/Hutan Adat (Sentinel-2 + Random
Forest). Tiga tabel terisolasi — tidak menyentuh `burned_area_summary`
maupun `s2_burned_area`. Hasil di-cache permanen: satu poligon dianalisis
sekali, lalu dibaca berkali-kali.

Kunci kelas: hutan|semak|pertanian|terbuka|air (pemukiman di-skip).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

_TARGET_LAYERS = ("psagustus2026", "HUTAN_ADAT_APR26")
CLASS_KEYS = ("hutan", "semak", "pertanian", "terbuka", "air")
_CLASS_ORDER = {k: i for i, k in enumerate(CLASS_KEYS)}


class _LandCoverMixin:
    def _ensure_land_cover_tables(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS land_cover_analysis (
                    id BIGSERIAL PRIMARY KEY,
                    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
                    layer_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    year_start INTEGER NOT NULL DEFAULT 2021,
                    year_end INTEGER NOT NULL DEFAULT 2025,
                    model_trees INTEGER,
                    n_training INTEGER,
                    oob_accuracy DOUBLE PRECISION,
                    source TEXT NOT NULL DEFAULT 'Sentinel-2 L2A + Random Forest (ETA SENEU)',
                    label_source TEXT NOT NULL DEFAULT 'Google Dynamic World v1',
                    error_message TEXT,
                    duration_s DOUBLE PRECISION,
                    computed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (polygon_metadata_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS land_cover_year_class (
                    id BIGSERIAL PRIMARY KEY,
                    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
                    year INTEGER NOT NULL,
                    class_key TEXT NOT NULL,
                    area_ha DOUBLE PRECISION NOT NULL,
                    pct DOUBLE PRECISION NOT NULL,
                    UNIQUE (polygon_metadata_id, year, class_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS land_cover_year_geom (
                    id BIGSERIAL PRIMARY KEY,
                    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
                    year INTEGER NOT NULL,
                    class_key TEXT NOT NULL,
                    geometry geometry(MultiPolygon, 4326),
                    UNIQUE (polygon_metadata_id, year, class_key)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS land_cover_year_geom_pid_year_idx "
                "ON land_cover_year_geom (polygon_metadata_id, year)"
            )

    def read_land_cover_target_polygon(self, polygon_id: int) -> dict[str, object] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, layer_key, lembaga, nama_prov,
                           ST_AsGeoJSON(geometry)::json AS geometry_json
                    FROM polygon_metadata
                    WHERE id = %s AND is_active = TRUE
                      AND layer_key = ANY(%s)
                    """,
                    (int(polygon_id), list(_TARGET_LAYERS)),
                )
                row = cur.fetchone()
        if not row or not row.get("geometry_json"):
            return None
        return {
            "id": int(row["id"]),
            "layer_key": row["layer_key"],
            "lembaga": row.get("lembaga"),
            "nama_prov": row.get("nama_prov"),
            "geometry_json": row["geometry_json"],
        }

    def mark_land_cover_running(self, polygon_id: int, layer_key: str) -> None:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO land_cover_analysis (polygon_metadata_id, layer_key, status)
                    VALUES (%s, %s, 'running')
                    ON CONFLICT (polygon_metadata_id) DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        status = 'running',
                        error_message = NULL
                    """,
                    (int(polygon_id), str(layer_key)),
                )

    def mark_land_cover_error(self, polygon_id: int, message: str) -> None:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE land_cover_analysis
                    SET status = 'error', error_message = %s
                    WHERE polygon_metadata_id = %s
                    """,
                    (str(message)[:2000], int(polygon_id)),
                )

    def delete_land_cover_result(self, polygon_id: int) -> bool:
        """Hapus hasil analisis satu poligon (meta + luas + rona) -> kembali ke
        keadaan 'belum pernah dianalisis'. True kalau memang ada yang dihapus."""
        pid = int(polygon_id)
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM land_cover_year_geom WHERE polygon_metadata_id = %s", (pid,))
                cur.execute("DELETE FROM land_cover_year_class WHERE polygon_metadata_id = %s", (pid,))
                cur.execute("DELETE FROM land_cover_analysis WHERE polygon_metadata_id = %s", (pid,))
                return (cur.rowcount or 0) > 0

    def save_land_cover_result(
        self,
        polygon_id: int,
        layer_key: str,
        *,
        model_trees: int,
        n_training: int,
        oob_accuracy: float | None,
        duration_s: float,
        year_class_rows: Sequence[dict[str, object]],
        year_geom_rows: Sequence[dict[str, object]],
    ) -> None:
        pid = int(polygon_id)
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM land_cover_year_class WHERE polygon_metadata_id = %s", (pid,))
                cur.execute("DELETE FROM land_cover_year_geom WHERE polygon_metadata_id = %s", (pid,))
                cur.execute(
                    """
                    INSERT INTO land_cover_analysis (
                        polygon_metadata_id, layer_key, status,
                        model_trees, n_training, oob_accuracy, duration_s, computed_at
                    )
                    VALUES (%s, %s, 'done', %s, %s, %s, %s, NOW())
                    ON CONFLICT (polygon_metadata_id) DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        status = 'done',
                        model_trees = EXCLUDED.model_trees,
                        n_training = EXCLUDED.n_training,
                        oob_accuracy = EXCLUDED.oob_accuracy,
                        duration_s = EXCLUDED.duration_s,
                        error_message = NULL,
                        computed_at = NOW()
                    """,
                    (pid, str(layer_key), int(model_trees), int(n_training),
                     None if oob_accuracy is None else float(oob_accuracy), float(duration_s)),
                )
                cur.executemany(
                    """
                    INSERT INTO land_cover_year_class
                        (polygon_metadata_id, year, class_key, area_ha, pct)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (pid, int(r["year"]), str(r["class_key"]), float(r["area_ha"]), float(r["pct"]))
                        for r in year_class_rows
                    ],
                )
                cur.executemany(
                    """
                    INSERT INTO land_cover_year_geom
                        (polygon_metadata_id, year, class_key, geometry)
                    VALUES (
                        %s, %s, %s,
                        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326))
                    )
                    """,
                    [
                        (pid, int(r["year"]), str(r["class_key"]),
                         json.dumps(r["geometry_geojson"], default=float))
                        for r in year_geom_rows
                        if r.get("geometry_geojson")
                    ],
                )

    def read_land_cover_status(self, polygon_id: int) -> dict[str, object] | None:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, error_message, computed_at
                    FROM land_cover_analysis WHERE polygon_metadata_id = %s
                    """,
                    (int(polygon_id),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "status": row["status"],
            "error_message": row.get("error_message"),
            "computed_at": row["computed_at"].isoformat() if row.get("computed_at") else None,
        }

    def read_land_cover_result(self, polygon_id: int) -> dict[str, object] | None:
        pid = int(polygon_id)
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM land_cover_analysis WHERE polygon_metadata_id = %s", (pid,)
                )
                meta = cur.fetchone()
                if not meta or meta["status"] != "done":
                    return None
                cur.execute(
                    """
                    SELECT year, class_key, area_ha, pct
                    FROM land_cover_year_class WHERE polygon_metadata_id = %s
                    """,
                    (pid,),
                )
                rows = cur.fetchall()
        meta_out = dict(meta)
        if meta_out.get("computed_at"):
            meta_out["computed_at"] = meta_out["computed_at"].isoformat()
        if meta_out.get("created_at"):
            meta_out["created_at"] = meta_out["created_at"].isoformat()
        year_class = sorted(
            (
                {
                    "year": int(r["year"]),
                    "class_key": r["class_key"],
                    "area_ha": round(float(r["area_ha"]), 2),
                    "pct": round(float(r["pct"]), 2),
                }
                for r in rows
            ),
            key=lambda r: (r["year"], _CLASS_ORDER.get(r["class_key"], 99)),
        )
        return {"meta": meta_out, "year_class": year_class}

    def list_polygons_with_land_cover_status(self) -> list[dict[str, object]]:
        """Semua poligon aktif (KPS + Hutan Adat) + status analisis tutupan lahan
        (LEFT JOIN -- status None kalau poligon itu belum pernah dianalisis).
        Dipakai menu "Tutupan Lahan" untuk daftar+cari semua poligon sekaligus,
        BUKAN untuk map/geometry (tidak ada kolom geometry di hasil)."""
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.id, p.layer_key, p.lembaga, p.nama_prov, p.nama_kab,
                           p.nama_kec, p.skema, p.luas_final, p.wilker_bps,
                           lc.status AS land_cover_status,
                           lc.computed_at AS land_cover_computed_at
                    FROM polygon_metadata p
                    LEFT JOIN land_cover_analysis lc ON lc.polygon_metadata_id = p.id
                    WHERE p.is_active = TRUE AND p.layer_key = ANY(%s)
                    ORDER BY p.nama_prov NULLS LAST, p.lembaga NULLS LAST
                    """,
                    (list(_TARGET_LAYERS),),
                )
                rows = cur.fetchall()
        return [
            {
                "polygon_metadata_id": int(r["id"]),
                "layer_key": r["layer_key"],
                "lembaga": r.get("lembaga"),
                "nama_prov": r.get("nama_prov"),
                "nama_kab": r.get("nama_kab"),
                "nama_kec": r.get("nama_kec"),
                "skema": r.get("skema"),
                "wilker_bps": r.get("wilker_bps"),
                "luas_final": float(r["luas_final"]) if r.get("luas_final") is not None else None,
                "land_cover_status": r.get("land_cover_status"),
                "land_cover_computed_at": (
                    r["land_cover_computed_at"].isoformat()
                    if r.get("land_cover_computed_at")
                    else None
                ),
            }
            for r in rows
        ]

    def read_land_cover_overlay(self, polygon_id: int, year: int) -> list[dict[str, object]]:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT g.class_key,
                           COALESCE(c.area_ha, 0) AS area_ha,
                           COALESCE(c.pct, 0) AS pct,
                           ST_AsGeoJSON(g.geometry)::json AS geometry_json
                    FROM land_cover_year_geom g
                    LEFT JOIN land_cover_year_class c
                      ON c.polygon_metadata_id = g.polygon_metadata_id
                     AND c.year = g.year AND c.class_key = g.class_key
                    WHERE g.polygon_metadata_id = %s AND g.year = %s
                      AND g.geometry IS NOT NULL
                    """,
                    (int(polygon_id), int(year)),
                )
                rows = cur.fetchall()
        return [
            {
                "class_key": r["class_key"],
                "area_ha": round(float(r["area_ha"]), 2),
                "pct": round(float(r["pct"]), 2),
                "geometry_json": r["geometry_json"],
            }
            for r in rows
        ]
