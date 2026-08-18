"""Luas kebakaran per poligon KPS per bulan (MODIS MCD64A1 via Google Earth Engine).

Granularitas bulanan -- beda dari hotspot yang sub-harian -- karena itu
cadence terbit produknya (lihat `burned_area_service.py`).
"""

import json
from collections.abc import Sequence


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
        membuat totalnya melebihi luas kawasannya sendiri. ST_Union
        menggabungkan jejak bulanan jadi satu area sehingga tumpang tindihnya
        dihitung sekali.

        Return None kalau tidak ada satu pun jejak geometry tersimpan --
        pemanggil sebaiknya jatuh kembali ke penjumlahan bulanan dan
        melabelinya sebagai akumulasi, bukan luas unik.
        """
        if not polygon_ids:
            return None

        clauses = ["polygon_metadata_id = ANY(%s)", "geometry IS NOT NULL"]
        params: list[object] = [[int(pid) for pid in polygon_ids]]
        if year is not None:
            clauses.append("year = %s")
            params.append(int(year))

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT ST_Area(ST_Union(geometry)::geography) / 10000 AS ha
                    FROM burned_area_summary
                    WHERE {' AND '.join(clauses)}
                    """,
                    params,
                )
                row = cur.fetchone()
        if not row or row.get("ha") is None:
            return None
        return float(row["ha"])

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
