"""Luas kebakaran per poligon KPS per bulan.

Sumber: overlay resmi KLHK "Areal Kebakaran Hutan dan Lahan" (lihat
`refresh_burned_area_from_klhk`). Sebelumnya MODIS/VIIRS via Google Earth
Engine (`burned_area_service.py`, sekarang tidak dipakai lagi) -- histori
kenapa diganti ada di situ. Granularitas bulanan -- beda dari hotspot yang
sub-harian -- karena itu cadence terbit rekap resminya.
"""

import json
from collections.abc import Iterable, Sequence
from datetime import datetime

from ._base import Json, _safe_json


class _BurnedAreaMixin:
    def refresh_burned_area_from_klhk(
        self,
        features: Iterable[tuple[int, int, dict]],
        *,
        source: str = "KLHK - Areal Kebakaran Hutan dan Lahan",
    ) -> int:
        """Overlay poligon resmi KLHK (AKURASI H/M, sudah difilter pemanggil)
        terhadap KPS aktif di `polygon_metadata`, lalu upsert hasilnya ke
        `burned_area_summary`.

        `features` adalah iterable (year, month, geometry_geojson) -- month
        didapat dari kolom PERIODE (nama bulan) di file resmi. Poligon
        terbakar dalam BULAN YANG SAMA di-ST_Union dulu sebelum di-intersect
        ke tiap KPS, supaya kebakaran yang tumpang tindih di sumbernya
        sendiri tidak dihitung dobel -- perilaku yang sama seperti dedup
        lintas-bulan di `burned_area_unique_ha()`.

        Hektarnya dihitung lewat ST_Area(...::geography) di database, bukan
        di Python, supaya konsisten dengan semua fungsi burned-area lain di
        modul ini.
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TEMP TABLE IF NOT EXISTS klhk_burned_features (
                        year INT,
                        month INT,
                        geom GEOMETRY(MultiPolygon, 4326)
                    ) ON COMMIT PRESERVE ROWS
                    """
                )
                cur.execute("TRUNCATE klhk_burned_features")

            batch: list[tuple[int, int, str]] = []
            for year, month, geometry_geojson in features:
                batch.append((int(year), int(month), json.dumps(geometry_geojson, default=float)))
                if len(batch) >= 500:
                    self._insert_klhk_batch(conn, batch)
                    batch = []
            if batch:
                self._insert_klhk_batch(conn, batch)

            with conn.cursor() as cur:
                cur.execute("CREATE INDEX IF NOT EXISTS klhk_burned_features_geom_idx ON klhk_burned_features USING GIST (geom)")
                cur.execute("ANALYZE klhk_burned_features")

                cur.execute(
                    """
                    WITH monthly_union AS (
                        SELECT year, month, ST_Union(geom) AS geom
                        FROM klhk_burned_features
                        GROUP BY year, month
                    ),
                    overlay AS (
                        SELECT
                            p.id AS polygon_metadata_id,
                            p.layer_key,
                            m.year,
                            m.month,
                            ST_Intersection(p.geometry, m.geom) AS clip_geom
                        FROM polygon_metadata p
                        JOIN monthly_union m ON ST_Intersects(p.geometry, m.geom)
                        WHERE p.is_active
                    )
                    SELECT
                        polygon_metadata_id, layer_key, year, month,
                        ST_Area(clip_geom::geography) / 10000 AS burned_area_ha,
                        ST_AsGeoJSON(clip_geom)::json AS geometry_json
                    FROM overlay
                    WHERE ST_Area(clip_geom::geography) > 0
                    """
                )
                overlay_rows = cur.fetchall()
                cur.execute("DROP TABLE klhk_burned_features")

        rows = [
            {
                "polygon_metadata_id": row["polygon_metadata_id"],
                "layer_key": row["layer_key"],
                "year": row["year"],
                "month": row["month"],
                "burned_area_ha": float(row["burned_area_ha"]),
                "geometry_geojson": row["geometry_json"],
                "source": source,
            }
            for row in overlay_rows
        ]
        return self.upsert_burned_area_summary(rows)

    def _insert_klhk_batch(self, conn, batch: list[tuple[int, int, str]]) -> None:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO klhk_burned_features (year, month, geom)
                VALUES (%s, %s,
                    ST_Multi(ST_MakeValid(ST_Force2D(ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326)))))
                """,
                batch,
            )

    def clear_burned_area_summary(self) -> int:
        """Kosongkan seluruh rekap burned area -- dipakai sekali saat pindah
        sumber data (GEE -> overlay KLHK) supaya baris lama yang terikat ke
        polygon_metadata_id dari layer yang sudah nonaktif (mis. PS_FEB_26
        lama) tidak nyangkut diam-diam di agregat."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM burned_area_summary")
                return cur.rowcount

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
        """Jejak area terbakar sebagai GeoJSON, untuk digambar di peta.

        Baris yang punya geometry (hasil vektorisasi reduceToVectors) dikirim
        apa adanya. Baris yang burned_area_ha > 0 tapi TIDAK punya geometry --
        piksel MODIS-nya cuma menyerempet tepi KPS sehingga reduceToVectors()
        tidak menghasilkan bentuk apa pun walau reduceRegions() tetap mencatat
        kontribusi luas fraksional kecil (lihat _vectorize_burned_area() di
        burned_area_service.py) -- dikirim sebagai titik centroid poligon,
        ditandai `is_estimated=true` supaya frontend menggambarnya beda
        (penanda perkiraan, bukan bentuk presisi).
        """
        if not polygon_ids:
            return []

        ids_param = [int(pid) for pid in polygon_ids]

        def _clauses(prefix: str) -> tuple[list[str], list[object]]:
            clauses = [f"{prefix}polygon_metadata_id = ANY(%s)"]
            params: list[object] = [ids_param]
            if year is not None:
                clauses.append(f"{prefix}year = %s")
                params.append(int(year))
            if month is not None:
                clauses.append(f"{prefix}month = %s")
                params.append(int(month))
            return clauses, params

        geometry_clauses, geometry_params = _clauses("")
        estimated_clauses, estimated_params = _clauses("b.")

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT polygon_metadata_id, year, month, burned_area_ha,
                           ST_AsGeoJSON(geometry)::json AS geometry_json,
                           FALSE AS is_estimated
                    FROM burned_area_summary
                    WHERE {' AND '.join(geometry_clauses)} AND geometry IS NOT NULL
                    UNION ALL
                    SELECT b.polygon_metadata_id, b.year, b.month, b.burned_area_ha,
                           ST_AsGeoJSON(ST_Centroid(p.geometry))::json AS geometry_json,
                           TRUE AS is_estimated
                    FROM burned_area_summary b
                    JOIN polygon_metadata p ON p.id = b.polygon_metadata_id
                    WHERE {' AND '.join(estimated_clauses)}
                      AND b.geometry IS NULL AND b.burned_area_ha > 0
                    ORDER BY year DESC, month DESC
                    """,
                    geometry_params + estimated_params,
                )
                rows = cur.fetchall()
        return list(rows)

    def read_burned_area_map_overlay(
        self,
        *,
        year: int | None = None,
        layer_keys: Sequence[str] | None = None,
    ) -> list[dict[str, object]]:
        """Satu fitur per KPS untuk lapisan peta utama (bukan per bulan).

        Peta utama menjawab "KPS mana yang terdampak kebakaran", bukan "apa
        yang terbakar di bulan apa" -- jadi geometry bulanan digabung
        (ST_Union) jadi satu bentuk per KPS. Ini juga menjaga payload tetap
        kecil: per-bulan akan mengirim baris berlipat untuk kawasan yang
        terbakar berulang, padahal di peta hasilnya bertumpuk di tempat yang
        sama.

        Geometry disederhanakan (~55 m) khusus untuk tampilan peta -- jauh
        lebih kasar dari yang dipakai perhitungan luas (lihat catatan
        tolerance di burned_area_service.py), tapi di bawah ukuran satu
        piksel MODIS 500 m sehingga tidak mengubah apa yang terlihat.

        KPS yang punya luas terbakar tapi tanpa geometry (piksel cuma
        menyerempet tepi) ikut dikirim sebagai centroid dengan
        `is_estimated=true`, sama seperti read_burned_area_geometries().
        """
        clauses = ["1 = 1"]
        params: list[object] = []
        if year is not None:
            clauses.append("b.year = %s")
            params.append(int(year))
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
                            p.lembaga,
                            p.skema,
                            p.nama_prov,
                            p.wilker_bps,
                            ST_Union(b.geometry) FILTER (WHERE b.geometry IS NOT NULL) AS burned_geom,
                            COALESCE(
                                SUM(b.burned_area_ha) FILTER (WHERE b.geometry IS NULL), 0
                            ) AS unvectorized_ha,
                            ST_Centroid(p.geometry) AS centroid,
                            MAX(b.year * 100 + b.month) FILTER (WHERE b.burned_area_ha > 0) AS latest_period,
                            COUNT(*) FILTER (WHERE b.burned_area_ha > 0) AS burned_months
                        FROM burned_area_summary b
                        JOIN polygon_metadata p ON p.id = b.polygon_metadata_id
                        WHERE {where_sql}
                        GROUP BY b.polygon_metadata_id, p.lembaga, p.skema,
                                 p.nama_prov, p.wilker_bps, p.geometry
                    )
                    SELECT
                        polygon_metadata_id,
                        lembaga,
                        skema,
                        nama_prov,
                        wilker_bps,
                        latest_period,
                        burned_months,
                        COALESCE(ST_Area(burned_geom::geography) / 10000, 0) + unvectorized_ha AS burned_ha,
                        (burned_geom IS NULL) AS is_estimated,
                        ST_AsGeoJSON(
                            COALESCE(
                                ST_SimplifyPreserveTopology(burned_geom, 0.0005),
                                centroid
                            )
                        )::json AS geometry_json
                    FROM per_polygon
                    WHERE burned_geom IS NOT NULL OR unvectorized_ha > 0
                    ORDER BY burned_ha DESC
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

    def read_burned_area_by_kawasan(
        self, province: str | None = None
    ) -> list[dict[str, object]]:
        """Rekap luas terbakar resmi Kementerian Kehutanan per FUNGSI kawasan
        hutan (Hutan Lindung / HP / HPT / HPK / Konservasi / APL).

        Sumbernya tabel materialized `burned_kemenhut_kawasan_hutan` yang
        di-rebuild `refresh_kawasan_attribution()` (union geometry KLHK per KPS
        lintas bulan -> iris `ref_kawasan_hutan`). Label diambil live dari
        `ref_fungsi_kawasan_label`, jadi koreksi kode langsung kelihatan.
        Filter provinsi opsional (lewat `polygon_metadata.nama_prov`)."""
        params: list[object] = []
        where = ""
        if province:
            where = "WHERE pm.nama_prov = %s"
            params.append(str(province))
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT b.fungsikws::bigint AS kode,
                           max(COALESCE(lbl.singkatan, '')) AS singkatan,
                           max(COALESCE(lbl.fungsi, 'Kode ' || b.fungsikws::text)) AS fungsi,
                           max(COALESCE(lbl.kelompok, b.kelompok)) AS kelompok,
                           round(sum(b.luas_ha)::numeric, 2) AS luas_ha
                    FROM burned_kemenhut_kawasan_hutan b
                    LEFT JOIN ref_fungsi_kawasan_label lbl ON lbl.kode = b.fungsikws
                    JOIN polygon_metadata pm ON pm.id = b.polygon_metadata_id
                    {where}
                    GROUP BY b.fungsikws
                    ORDER BY luas_ha DESC
                    """,
                    params,
                )
                rows = cur.fetchall()
        return [
            {
                "kode": int(r["kode"]) if r["kode"] is not None else None,
                "singkatan": r["singkatan"],
                "fungsi": r["fungsi"],
                "kelompok": r["kelompok"],
                "luas_ha": float(r["luas_ha"] or 0),
            }
            for r in rows
        ]

    def refresh_kawasan_attribution(self) -> dict[str, int]:
        """Jalankan fungsi plpgsql `refresh_kawasan_attribution()` di DB:
        atribusi hotspot baru (inkremental) + rebuild penuh luas terbakar
        (Sentinel-2 & Kementerian Kehutanan) per fungsi kawasan hutan.
        ~20 dtk. Dipakai tombol Pengaturan + auto setelah refresh file
        Kementerian Kehutanan. Cron harian tetap jalan sebagai jaring pengaman."""
        if not self.enabled:
            return {"hotspot_baru": 0, "hotspot_hapus": 0, "burned_rebuild": 0}
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT hotspot_baru, hotspot_hapus, burned_rebuild "
                    "FROM refresh_kawasan_attribution()"
                )
                row = cur.fetchone() or {}
        return {
            "hotspot_baru": int(row.get("hotspot_baru") or 0),
            "hotspot_hapus": int(row.get("hotspot_hapus") or 0),
            "burned_rebuild": int(row.get("burned_rebuild") or 0),
        }

    def burn_frequency_by_lembaga(self) -> list[dict[str, object]]:
        """Berapa PERIODE (bulan) TERPISAH tiap KPS pernah tercatat luas bekas
        terbakar resmi KLHK -- dasar kolom "Frekuensi" di Buku Besar. Beda
        dari `burned_area_unique_ha`/`burned_area_by_skema`: di sini yang
        dihitung jumlah BULANnya (deteksi kebakaran berulang), bukan luas
        presisi, jadi tidak perlu union geometry -- COUNT DISTINCT (year,
        month) sudah cukup."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT p.lembaga,
                           COUNT(DISTINCT (b.year, b.month)) AS periode_terbakar,
                           MIN(make_date(b.year, b.month, 1)) AS pertama,
                           MAX(make_date(b.year, b.month, 1)) AS terakhir,
                           SUM(b.burned_area_ha) AS total_ha
                    FROM burned_area_summary b
                    JOIN polygon_metadata p ON p.id = b.polygon_metadata_id
                    GROUP BY p.lembaga
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "lembaga": r["lembaga"],
                "periode_terbakar": int(r["periode_terbakar"]),
                "pertama": r["pertama"].isoformat() if r["pertama"] else None,
                "terakhir": r["terakhir"].isoformat() if r["terakhir"] else None,
                "total_ha": float(r["total_ha"]) if r["total_ha"] is not None else 0.0,
            }
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
