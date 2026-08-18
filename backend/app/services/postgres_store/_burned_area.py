"""Luas kebakaran per poligon KPS per bulan (MODIS MCD64A1 via Google Earth Engine).

Granularitas bulanan -- beda dari hotspot yang sub-harian -- karena itu
cadence terbit produknya (lihat `burned_area_service.py`).
"""

from collections.abc import Sequence


class _BurnedAreaMixin:
    def upsert_burned_area_summary(self, rows: Sequence[dict[str, object]]) -> int:
        """Simpan/perbarui luas terbakar per poligon per bulan.

        `rows` masing-masing butuh: polygon_metadata_id, layer_key, year,
        month, burned_area_ha. `source` opsional (default MCD64A1).
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
            )
            for row in rows
        ]

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO burned_area_summary (
                        polygon_metadata_id, layer_key, year, month,
                        burned_area_ha, source, computed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (polygon_metadata_id, year, month)
                    DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        burned_area_ha = EXCLUDED.burned_area_ha,
                        source = EXCLUDED.source,
                        computed_at = NOW()
                    """,
                    params,
                )
        return len(params)

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
