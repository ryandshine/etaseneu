"""Luas kebakaran per poligon KPS per bulan (MODIS MCD64A1 via Google Earth Engine).

Granularitas bulanan -- beda dari hotspot yang sub-harian -- karena itu
cadence terbit produknya (lihat `burned_area_service.py`).
"""

import json
from collections.abc import Sequence
from datetime import datetime

from ._base import Json, _safe_json


class _BurnedAreaMixin:
    def upsert_burned_area_summary(self, rows: Sequence[dict[str, object]]) -> int:
        """Simpan/perbarui luas terbakar per poligon per bulan.

        `rows` masing-masing butuh: polygon_metadata_id, layer_key, year,
        month, burned_area_ha. `source` dan `geometry_geojson` opsional --
        geometry adalah jejak area terbakar hasil vektorisasi, dipakai
        menggambar lapisan di peta detail KPS.
        """
        if not rows:
            return 0

        params = [
            (
                int(row["polygon_metadata_id"]),
                str(row["layer_key"]),
                int(row["year"]),
                int(row["month"]),
                float(row["burned_area_ha"]),
                str(row.get("source") or "MODIS/061/MCD64A1"),
                json.dumps(row["geometry_geojson"]) if row.get("geometry_geojson") else None,
            )
            for row in rows
        ]

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO burned_area_summary (
                        polygon_metadata_id, layer_key, year, month,
                        burned_area_ha, source, geometry, computed_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        -- ST_GeomFromGeoJSON strict: NULL masuk -> NULL keluar,
                        -- jadi baris tanpa geometry tetap tersimpan apa adanya.
                        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)),
                        NOW()
                    )
                    ON CONFLICT (polygon_metadata_id, year, month)
                    DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        burned_area_ha = EXCLUDED.burned_area_ha,
                        source = EXCLUDED.source,
                        geometry = EXCLUDED.geometry,
                        computed_at = NOW()
                    """,
                    params,
                )
        return len(params)

    def read_burned_area_geometries(
        self,
        polygon_ids: Sequence[int],
        *,
        year: int | None = None,
        month: int | None = None,
    ) -> list[dict[str, object]]:
        """Jejak area terbakar sebagai GeoJSON, untuk digambar di peta."""
        if not polygon_ids:
            return []

        clauses = ["polygon_metadata_id = ANY(%s)", "geometry IS NOT NULL"]
        params: list[object] = [[int(pid) for pid in polygon_ids]]
        if year is not None:
            clauses.append("year = %s")
            params.append(int(year))
        if month is not None:
            clauses.append("month = %s")
            params.append(int(month))

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT polygon_metadata_id, year, month, burned_area_ha,
                           ST_AsGeoJSON(geometry)::json AS geometry_json
                    FROM burned_area_summary
                    WHERE {' AND '.join(clauses)}
                    ORDER BY year DESC, month DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
        return list(rows)

    def read_burned_area_summary(
        self,
        *,
        polygon_ids: Sequence[int] | None = None,
        layer_keys: Sequence[str] | None = None,
        year: int | None = None,
        month: int | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []

        if polygon_ids:
            clauses.append("polygon_metadata_id = ANY(%s)")
            params.append([int(pid) for pid in polygon_ids])
        if layer_keys:
            clauses.append("layer_key = ANY(%s)")
            params.append([str(lk) for lk in layer_keys])
        if year is not None:
            clauses.append("year = %s")
            params.append(int(year))
        if month is not None:
            clauses.append("month = %s")
            params.append(int(month))

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT polygon_metadata_id, layer_key, year, month,
                           burned_area_ha, source, computed_at
                    FROM burned_area_summary
                    {where_sql}
                    ORDER BY year DESC, month DESC, burned_area_ha DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
        return list(rows)

    def burned_area_unique_ha(
        self,
        polygon_ids: Sequence[int],
        *,
        year: int | None = None,
    ) -> float | None:
        """Luas lahan terbakar UNIK (bukan penjumlahan bulanan).

        Lahan yang sama bisa terbakar lebih dari sekali dalam setahun, dan
        menjumlahkan angka bulanan akan menghitungnya berkali-kali -- pada
        satu KPS di Bengkalis selisihnya mencapai 536 ha (22%), bahkan bisa
        membuat totalnya melebihi luas kawasannya sendiri.

        Dihitung PER POLIGON dulu (union geometry bulan-bulan yang punya
        geometry, ditambah jumlah bulan yang TIDAK punya geometry -- efek
        piksel yang cuma menyerempet tepi poligon, lihat komentar di
        `burned_area_service.py`), baru dijumlah lintas poligon. Versi
        sebelumnya cuma mengambil ST_Union tanpa filter per-poligon: pada
        poligon yang punya campuran bulan-ada-geometry dan bulan-tanpa-
        geometry, bulan yang tanpa geometry itu diam-diam KETINGGALAN dari
        hasil -- bukan dobel hitung, tapi kurang hitung.

        Return None kalau tidak ada satu baris pun yang cocok filter (tidak
        ada data sama sekali) -- beda dari poligon yang datanya ada tapi
        semuanya tanpa geometry (itu tetap dihitung, cuma dari penjumlahan
        bulanan apa adanya karena tidak ada jejak untuk di-union).
        """
        if not polygon_ids:
            return None

        clauses = ["polygon_metadata_id = ANY(%s)"]
        params: list[object] = [[int(pid) for pid in polygon_ids]]
        if year is not None:
            clauses.append("year = %s")
            params.append(int(year))
        where_sql = " AND ".join(clauses)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    WITH per_polygon AS (
                        SELECT
                            polygon_metadata_id,
                            COALESCE(
                                ST_Area(ST_Union(geometry) FILTER (WHERE geometry IS NOT NULL)::geography) / 10000,
                                0
                            ) AS unioned_ha,
                            COALESCE(SUM(burned_area_ha) FILTER (WHERE geometry IS NULL), 0) AS unvectorized_ha
                        FROM burned_area_summary
                        WHERE {where_sql}
                        GROUP BY polygon_metadata_id
                    )
                    SELECT SUM(unioned_ha + unvectorized_ha) AS ha FROM per_polygon
                    """,
                    params,
                )
                row = cur.fetchone()
        if not row or row.get("ha") is None:
            return None
        return float(row["ha"])

    def burned_area_by_skema(
        self,
        *,
        year: int | None = None,
        month: int | None = None,
        layer_keys: Sequence[str] | None = None,
    ) -> list[dict[str, object]]:
        """Rekap luas terbakar UNIK per skema perhutanan sosial.

        Sama seperti `burned_area_unique_ha`: digabung per poligon dulu
        (union + fallback bulan-tanpa-geometry) baru dijumlah -- kali ini
        dikelompokkan per skema, bukan dijumlah jadi satu angka.
        """
        clauses = ["1 = 1"]
        params: list[object] = []
        if year is not None:
            clauses.append("b.year = %s")
            params.append(int(year))
        if month is not None:
            clauses.append("b.month = %s")
            params.append(int(month))
        if layer_keys:
            clauses.append("b.layer_key = ANY(%s)")
            params.append([str(lk) for lk in layer_keys])
        where_sql = " AND ".join(clauses)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    WITH per_polygon AS (
                        SELECT
                            b.polygon_metadata_id,
                            p.skema,
                            COALESCE(
                                ST_Area(ST_Union(b.geometry) FILTER (WHERE b.geometry IS NOT NULL)::geography) / 10000,
                                0
                            ) AS unioned_ha,
                            COALESCE(SUM(b.burned_area_ha) FILTER (WHERE b.geometry IS NULL), 0) AS unvectorized_ha
                        FROM burned_area_summary b
                        JOIN polygon_metadata p ON p.id = b.polygon_metadata_id
                        WHERE {where_sql}
                        GROUP BY b.polygon_metadata_id, p.skema
                    )
                    SELECT
                        skema,
                        COUNT(*) FILTER (WHERE unioned_ha + unvectorized_ha > 0) AS kps_count,
                        SUM(unioned_ha + unvectorized_ha) AS total_ha
                    FROM per_polygon
                    GROUP BY skema
                    HAVING SUM(unioned_ha + unvectorized_ha) > 0
                    ORDER BY total_ha DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [
            {"skema": r["skema"], "kps_count": int(r["kps_count"]), "total_ha": float(r["total_ha"])}
            for r in rows
        ]

    def _ensure_burned_area_scheduler_state_table(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS burned_area_scheduler_state (
                    id SMALLINT PRIMARY KEY DEFAULT 1,
                    last_run_at TIMESTAMPTZ,
                    last_successful_run_at TIMESTAMPTZ,
                    last_run_result JSONB,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (id = 1)
                )
                """
            )

    def save_burned_area_scheduler_state(
        self,
        *,
        last_run_at: datetime | None,
        last_successful_run_at: datetime | None,
        last_run_result: dict,
        consecutive_failures: int,
    ) -> None:
        """Simpan status siklus auto-refresh burned area (satu baris global,
        beda dari `hotspot_sync_state` yang dipakai scheduler hotspot -- lihat
        `burned_area_scheduler.py` untuk kenapa perlu tabel terpisah."""
        with self.connection() as conn:
            self._ensure_burned_area_scheduler_state_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO burned_area_scheduler_state (
                        id, last_run_at, last_successful_run_at, last_run_result, consecutive_failures
                    )
                    VALUES (1, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        last_run_at = EXCLUDED.last_run_at,
                        last_successful_run_at = EXCLUDED.last_successful_run_at,
                        last_run_result = EXCLUDED.last_run_result,
                        consecutive_failures = EXCLUDED.consecutive_failures,
                        updated_at = NOW()
                    """,
                    (last_run_at, last_successful_run_at, Json(last_run_result), consecutive_failures),
                )

    def read_burned_area_scheduler_state(self) -> dict[str, object] | None:
        with self.connection() as conn:
            self._ensure_burned_area_scheduler_state_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT last_run_at, last_successful_run_at, last_run_result, consecutive_failures
                    FROM burned_area_scheduler_state
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()

        if not row:
            return None

        return {
            "last_run_at": row.get("last_run_at"),
            "last_successful_run_at": row.get("last_successful_run_at"),
            "last_run_result": _safe_json(row.get("last_run_result"), {}),
            "consecutive_failures": int(row.get("consecutive_failures", 0) or 0),
        }

    def latest_burned_area_period(self) -> tuple[int, int] | None:
        """Periode (tahun, bulan) terbaru yang sudah dihitung, kalau ada."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT year, month
                    FROM burned_area_summary
                    ORDER BY year DESC, month DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        if not row:
            return None
        return int(row["year"]), int(row["month"])
