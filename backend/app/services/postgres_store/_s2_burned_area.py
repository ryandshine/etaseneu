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
                                'kelompok', COALESCE(lbl.kelompok, bkh.kelompok),
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

    def latest_s2_burned_area_period(self) -> tuple[int, int] | None:
        with self.connection() as conn:
            self._ensure_s2_burned_area_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT year, month
                    FROM s2_burned_area
                    WHERE geometry IS NOT NULL
                    ORDER BY year DESC, month DESC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
        if not row:
            return None
        return int(row["year"]), int(row["month"])

    def read_s2_burned_area_overlay(
        self, year: int | None = None, month: int | None = None
    ) -> dict[str, object]:
        """Poligon estimasi bekas terbakar Sentinel-2 untuk lapisan peta.

        `year`+`month` keduanya diberikan -> satu periode itu saja. Salah satu
        (atau keduanya) None -> SEMUA periode yang tersimpan digabung (tiap
        poligon bisa muncul >1 kali kalau terbakar di beberapa bulan). Live Map
        memanggil tanpa argumen supaya Agustus + September tampil sekaligus.

        Mode gabungan: dua periode untuk poligon yang sama sering beririsan
        secara spasial -- bukan berarti kebakaran baru, karena `analyze_month`
        dihitung independen per bulan dan jendela pra-kebakaran bulan N+1
        (46 hari sebelum awal bulan) tumpang tindih dengan bulan N (lihat
        catatan proyek). Kalau di-SUM apa adanya, `total_ha` gabungan
        menghitung ganda irisan itu. Jadi tiap fitur di mode gabungan dapat
        properti tambahan `overlap_ha` (irisan dengan periode LAIN milik
        poligon yang sama, dari geometri hasil vektorisasi) + `overlap_periods`,
        dan `meta.total_ha` dikoreksi dengan mengurangi overlap itu dari sum
        `area_ha` mentah (`total_ha_raw_sum`). `area_ha` per fitur TETAP angka
        mentah tersimpan (raster GEE, tidak diubah) -- itu tetap angka valid
        untuk KPS Detail per-bulan, cuma tidak boleh dijumlah naif lintas
        periode untuk satu poligon yang sama.

        Perf: overlap HANYA dihitung untuk poligon yang benar-benar py>1
        periode (biasanya segelintir dari ratusan baris) -- ST_Intersection
        atas geometri hasil vektorisasi (bisa >10rb vertex) mahal, jadi
        menjalankannya ke SEMUA baris (termasuk yang jelas tidak beririsan)
        pernah bikin endpoint ini 18 detik (diukur 2026-09-27). Query kedua
        di-scope lewat CTE `multi` supaya cuma poligon yang perlu saja yang
        kena operasi spasial mahal.
        """
        single_period = year is not None and month is not None
        period_filter = "AND s.year = %s AND s.month = %s" if single_period else ""
        params = (year, month) if single_period else ()
        with self.connection() as conn:
            self._ensure_s2_burned_area_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT s.id, s.polygon_metadata_id, s.year, s.month, s.area_ha,
                           s.dnbr_mean, s.hotspot_count_month, s.has_hotspot, s.computed_at,
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
                                'kelompok', COALESCE(lbl.kelompok, bkh.kelompok),
                                'luas_ha', round(bkh.luas_ha::numeric, 2)
                            ) ORDER BY bkh.luas_ha DESC) AS rincian,
                            (SELECT bkh2.kelompok FROM burned_kawasan_hutan bkh2
                               WHERE bkh2.burned_id = s.id
                               ORDER BY bkh2.luas_ha DESC LIMIT 1) AS dominan
                        FROM burned_kawasan_hutan bkh
                        LEFT JOIN ref_fungsi_kawasan_label lbl ON lbl.kode = bkh.fungsikws
                        WHERE bkh.burned_id = s.id
                    ) khutan ON TRUE
                    WHERE s.geometry IS NOT NULL {period_filter}
                    ORDER BY s.area_ha DESC
                    """,
                    params,
                )
                rows = cur.fetchall()

                # Overlap: cuma dihitung untuk mode gabungan, dan cuma untuk
                # poligon yang punya >1 baris (>1 periode) -- mayoritas baris
                # tidak beririsan dengan apa pun, jadi tidak perlu operasi
                # spasial sama sekali.
                overlap_by_id: dict[int, tuple[float, list[str]]] = {}
                if not single_period:
                    cur.execute(
                        """
                        WITH multi AS (
                            SELECT polygon_metadata_id FROM s2_burned_area
                            WHERE geometry IS NOT NULL
                            GROUP BY polygon_metadata_id HAVING COUNT(*) > 1
                        ),
                        cand AS (
                            SELECT s.id, s.polygon_metadata_id, s.year, s.month, s.geometry
                            FROM s2_burned_area s
                            JOIN multi m ON m.polygon_metadata_id = s.polygon_metadata_id
                            WHERE s.geometry IS NOT NULL
                        )
                        SELECT cand.id,
                               ST_Area(ST_Intersection(cand.geometry, other.geometry)::geography)
                                   / 10000 AS overlap_ha,
                               other.year AS other_year, other.month AS other_month
                        FROM cand
                        JOIN cand other
                          ON other.polygon_metadata_id = cand.polygon_metadata_id
                         AND other.id <> cand.id
                         AND ST_Intersects(cand.geometry, other.geometry)
                        """
                    )
                    for r in cur.fetchall():
                        rid = int(r["id"])
                        ha, periods_list = overlap_by_id.get(rid, (0.0, []))
                        ha += float(r["overlap_ha"] or 0.0)
                        periods_list = periods_list + [f"{int(r['other_year']):04d}-{int(r['other_month']):02d}"]
                        overlap_by_id[rid] = (ha, periods_list)
        features = [
            {
                "type": "Feature",
                "geometry": r["geometry_json"],
                "properties": {
                    "polygon_metadata_id": int(r["polygon_metadata_id"]),
                    "year": int(r["year"]),
                    "month": int(r["month"]),
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
                    "overlap_ha": round(overlap_by_id.get(int(r["id"]), (0.0, []))[0], 1),
                    "overlap_periods": sorted(overlap_by_id.get(int(r["id"]), (0.0, []))[1]),
                },
            }
            for r in rows
        ]
        raw_sum_ha = round(sum(f["properties"]["area_ha"] for f in features), 1)
        # Koreksi inclusion-exclusion: tiap pasangan overlap muncul di KEDUA baris
        # (simetris), jadi dibagi 2 supaya cuma dikurangi sekali dari total.
        # Eksak untuk maksimal 2 periode per poligon (kondisi saat ini, Agustus+
        # September) -- kalau nanti ada 3+ periode yang beririsan tiga arah
        # sekaligus, ini jadi under-correction ringan (tidak pernah over-correct),
        # cukup untuk kebutuhan tampilan (data mentah per-periode tetap presisi).
        total_overlap_ha = sum(f["properties"]["overlap_ha"] for f in features) / 2
        total_ha = raw_sum_ha if single_period else round(raw_sum_ha - total_overlap_ha, 1)
        periods = sorted({(f["properties"]["year"], f["properties"]["month"]) for f in features})
        return {
            "type": "FeatureCollection",
            "features": features,
            "meta": {
                "year": year if single_period else None,
                "month": month if single_period else None,
                "periods": [f"{y:04d}-{m:02d}" for y, m in periods],
                "polygons": len(features),
                "total_ha": total_ha,
                "total_ha_raw_sum": raw_sum_ha,
                "no_hotspot_but_burned": sum(
                    1 for f in features if not f["properties"]["has_hotspot"]
                ),
            },
        }
