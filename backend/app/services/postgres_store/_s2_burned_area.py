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

    def read_s2_burned_area_pieces(
        self, polygon_ids: Sequence[int]
    ) -> list[dict[str, object]]:
        """Potongan tak-tumpang-tindih per bulan-pertama-terdeteksi untuk KPS
        tertentu yang terbakar di >1 periode (lihat `_s2_period_pieces`).
        Poligon satu periode tidak dikembalikan -- pakai baris aslinya."""
        if not polygon_ids:
            return []
        with self.connection() as conn:
            self._ensure_s2_burned_area_table(conn)
            with conn.cursor() as cur:
                return self._s2_period_pieces(cur, polygon_ids)

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

    def _s2_period_pieces(
        self, cur, polygon_ids: Sequence[int] | None = None
    ) -> list[dict[str, object]]:
        """Pecah footprint poligon yang terbakar di >1 periode jadi potongan
        yang TIDAK saling tumpang tindih, diberi label "bulan pertama terdeteksi".

        `analyze_month` menghitung tiap bulan independen dan jendela
        pra-kebakaran bulan N+1 (46 hari) tumpang tindih bulan N, jadi bekas
        bulan N sering terdeteksi lagi di N+1 (kasus nyata LPHD Kalibandung:
        137 ha dari 481 ha Agustus & 697 ha September beririsan, hotspot di
        irisan itu anjlok 85->6). Menggambar semua periode utuh bertumpuk
        membuat area itu tampil dobel dan luasnya terhitung dua kali.

        Per baris (poligon, periode P), urut kronologis:
          own(P)   = geom(P) - union(periode < P)   -> area yang PERTAMA muncul di P
          ulang(P) = own(P) ∩ union(periode > P)    -> ...lalu terdeteksi lagi belakangan
          baru(P)  = own(P) - union(periode > P)    -> ...dan tidak terdeteksi lagi
        Semua potongan mempartisi union(semua periode) -> jumlah `piece_ha`
        per poligon = footprint riil tanpa hitung ganda. Berlaku untuk berapa
        pun jumlah periode, bukan cuma Agustus+September.

        Cuma poligon dengan >1 periode yang diproses (CTE `multi`) -- operasi
        geometri atas hasil vektorisasi (bisa >10rb vertex) mahal; menjalankan
        operasi spasial ke SEMUA baris pernah bikin endpoint overlay 18 detik.
        `polygon_ids` None = semua poligon multi-periode (Live Map).
        """
        pid_filter = "AND polygon_metadata_id = ANY(%s)" if polygon_ids is not None else ""
        params: tuple = ([int(p) for p in polygon_ids],) if polygon_ids is not None else ()
        cur.execute(
            f"""
            WITH multi AS (
                SELECT polygon_metadata_id FROM s2_burned_area
                WHERE geometry IS NOT NULL {pid_filter}
                GROUP BY polygon_metadata_id HAVING COUNT(*) > 1
            ),
            r AS (
                SELECT s.polygon_metadata_id AS pid, s.year, s.month,
                       s.year * 100 + s.month AS ym, ST_MakeValid(s.geometry) AS g
                FROM s2_burned_area s
                JOIN multi m ON m.polygon_metadata_id = s.polygon_metadata_id
                WHERE s.geometry IS NOT NULL
            ),
            own AS (
                SELECT r.pid, r.year, r.month,
                       COALESCE(ST_Difference(r.g, e.g), r.g) AS g,
                       l.g AS later_g,
                       COALESCE(l.periods, ARRAY[]::text[]) AS later_periods
                FROM r
                LEFT JOIN LATERAL (
                    SELECT ST_Union(e.g) AS g FROM r e
                    WHERE e.pid = r.pid AND e.ym < r.ym
                ) e ON TRUE
                LEFT JOIN LATERAL (
                    SELECT ST_Union(l.g) AS g,
                           array_agg(l.year::text || '-' || lpad(l.month::text, 2, '0')
                                     ORDER BY l.ym) AS periods
                    FROM r l
                    WHERE l.pid = r.pid AND l.ym > r.ym AND ST_Intersects(l.g, r.g)
                ) l ON TRUE
            ),
            parts AS (
                SELECT pid, year, month, ARRAY[]::text[] AS redetected_in,
                       COALESCE(ST_Difference(g, later_g), g) AS g
                FROM own
                UNION ALL
                SELECT pid, year, month, later_periods, ST_Intersection(g, later_g)
                FROM own WHERE later_g IS NOT NULL
            ),
            polys AS (
                SELECT pid, year, month, redetected_in,
                       ST_Multi(ST_CollectionExtract(g, 3)) AS g
                FROM parts WHERE g IS NOT NULL
            )
            SELECT pid, year, month, redetected_in,
                   ST_AsGeoJSON(g)::json AS geometry_json,
                   ST_Area(g::geography) / 10000 AS piece_ha
            FROM polys
            -- buang serpihan sisa operasi overlay (< 0,1 ha) -- bukan bercak nyata
            WHERE NOT ST_IsEmpty(g) AND ST_Area(g::geography) >= 1000
            ORDER BY pid, year, month, cardinality(redetected_in)
            """,
            params,
        )
        return [
            {
                "polygon_metadata_id": int(r["pid"]),
                "year": int(r["year"]),
                "month": int(r["month"]),
                "redetected_in": list(r.get("redetected_in") or []),
                "piece_ha": float(r["piece_ha"] or 0.0),
                "geometry_json": r["geometry_json"],
            }
            for r in cur.fetchall()
        ]

    def _s2_period_pieces_all_cached(self, cur) -> list[dict[str, object]]:
        """`_s2_period_pieces` untuk SEMUA poligon multi-periode (Live Map),
        di-cache di `api_cache_entries`. Versi nasional ~15 detik (diukur
        2026-09-28, 151 poligon multi-periode) -- terlalu lambat untuk dihitung
        tiap toggle peta, padahal datanya cuma berubah saat `analyze_month`
        dijalankan manual. Kunci cache = sidik jari tabel (jumlah baris +
        `MAX(computed_at)`; upsert selalu set `computed_at = NOW()`), jadi
        cache otomatis basi begitu ada analisis baru -- tanpa invalidasi
        manual. Cache gagal dibaca/ditulis -> hitung langsung (non-fatal)."""
        cur.execute(
            "SELECT COUNT(*) AS n, MAX(computed_at) AS ts FROM s2_burned_area WHERE geometry IS NOT NULL"
        )
        fp = cur.fetchone() or {}
        ts = fp.get("ts")
        key = f"s2_period_pieces:v1:{fp.get('n')}:{ts.isoformat() if ts else 'none'}"
        try:
            cached = self.read_cache_entry(key)
        except Exception:  # noqa: BLE001 -- cache opsional
            cached = None
        if isinstance(cached, list):
            return cached
        pieces = self._s2_period_pieces(cur)
        try:
            self.write_cache_entry(key, pieces, ttl_hours=24 * 30)
        except Exception:  # noqa: BLE001 -- cache opsional
            pass
        return pieces

    def read_s2_burned_area_overlay(
        self, year: int | None = None, month: int | None = None
    ) -> dict[str, object]:
        """Poligon estimasi bekas terbakar Sentinel-2 untuk lapisan peta.

        `year`+`month` keduanya diberikan -> satu periode itu saja, satu fitur
        per poligon apa adanya. Salah satu (atau keduanya) None -> mode
        GABUNGAN (Live Map): semua periode tampil sekaligus, tapi poligon yang
        terbakar di >1 periode dipecah jadi potongan tak-tumpang-tindih per
        "bulan pertama terdeteksi" (lihat `_s2_period_pieces`) -- tiap potongan
        satu fitur; `year`/`month` = bulan pertama terdeteksi, `redetected_in`
        = periode belakangan yang mendeteksinya lagi (kosong kalau tidak).
        Frontend mewarnai per bulan dan menandai potongan `redetected_in`.

        `piece_ha` = luas fitur yang tampil; `area_ha` = angka raster GEE
        periode itu (tidak diubah, tetap acuan per-bulan). `periods_breakdown`
        + `footprint_ha` = rincian per poligon untuk popup. `meta.total_ha` =
        footprint riil tanpa hitung ganda (poligon satu periode: `area_ha`;
        multi-periode: jumlah `piece_ha`); `meta.total_ha_raw_sum` = jumlah
        `area_ha` mentah, cuma untuk perbandingan -- jangan ditampilkan sebagai
        total. `meta.polygons` = jumlah poligon KPS/Hutan Adat, bukan fitur.
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
                pieces = [] if single_period else self._s2_period_pieces_all_cached(cur)

        rows_by_pid: dict[int, list[dict]] = {}
        for r in rows:
            rows_by_pid.setdefault(int(r["polygon_metadata_id"]), []).append(r)

        footprint_by_pid: dict[int, float] = {}
        for p in pieces:
            pid = p["polygon_metadata_id"]
            footprint_by_pid[pid] = footprint_by_pid.get(pid, 0.0) + p["piece_ha"]

        features: list[dict[str, object]] = []
        for r in rows:
            pid = int(r["polygon_metadata_id"])
            if pid in footprint_by_pid:
                continue  # diganti potongan per bulan-pertama-terdeteksi di bawah
            features.append(
                {"type": "Feature", "geometry": r["geometry_json"], "properties": _s2_props(r, [r])}
            )
        for p in pieces:
            pid = p["polygon_metadata_id"]
            pid_rows = rows_by_pid.get(pid, [])
            src = next(
                (x for x in pid_rows if int(x["year"]) == p["year"] and int(x["month"]) == p["month"]),
                None,
            )
            if src is None:
                continue
            props = _s2_props(src, pid_rows)
            props["redetected_in"] = p["redetected_in"]
            props["piece_ha"] = round(p["piece_ha"], 1)
            props["footprint_ha"] = round(footprint_by_pid[pid], 1)
            features.append({"type": "Feature", "geometry": p["geometry_json"], "properties": props})

        raw_sum_ha = round(sum(float(r["area_ha"]) for r in rows), 1)
        if single_period:
            total_ha = raw_sum_ha
        else:
            single_ha = sum(
                float(r["area_ha"]) for r in rows if int(r["polygon_metadata_id"]) not in footprint_by_pid
            )
            total_ha = round(single_ha + sum(footprint_by_pid.values()), 1)
        periods = sorted({(int(r["year"]), int(r["month"])) for r in rows})
        return {
            "type": "FeatureCollection",
            "features": features,
            "meta": {
                "year": year if single_period else None,
                "month": month if single_period else None,
                "periods": [f"{y:04d}-{m:02d}" for y, m in periods],
                "polygons": len(rows_by_pid),
                "total_ha": total_ha,
                "total_ha_raw_sum": raw_sum_ha,
                "no_hotspot_but_burned": sum(
                    1
                    for pid_rows in rows_by_pid.values()
                    if not any(bool(x["has_hotspot"]) for x in pid_rows)
                ),
            },
        }


def _s2_props(r: dict, pid_rows: Sequence[dict]) -> dict[str, object]:
    """Properti fitur overlay S2 dari satu baris `s2_burned_area` (`r`) +
    semua baris poligon yang sama (`pid_rows`, untuk rincian per periode).
    Default = fitur utuh satu periode; pemanggil menimpa `redetected_in`/
    `piece_ha`/`footprint_ha` untuk potongan multi-periode."""
    area = round(float(r["area_ha"]), 1)
    return {
        "polygon_metadata_id": int(r["polygon_metadata_id"]),
        "year": int(r["year"]),
        "month": int(r["month"]),
        "lembaga": r.get("lembaga"),
        "nama_prov": r.get("nama_prov"),
        "nama_kab": r.get("nama_kab"),
        "area_ha": area,
        "dnbr_mean": round(float(r["dnbr_mean"]), 3) if r.get("dnbr_mean") is not None else None,
        "hotspot_count_month": int(r["hotspot_count_month"]),
        "has_hotspot": bool(r["has_hotspot"]),
        "computed_at": r["computed_at"].isoformat() if r.get("computed_at") else None,
        "kawasan_rincian": r.get("kawasan_rincian") or [],
        "kawasan_dominan": r.get("kawasan_dominan"),
        "redetected_in": [],
        "piece_ha": area,
        "footprint_ha": area,
        "periods_breakdown": [
            {"year": int(x["year"]), "month": int(x["month"]), "area_ha": round(float(x["area_ha"]), 1)}
            for x in sorted(pid_rows, key=lambda x: (int(x["year"]), int(x["month"])))
        ],
    }
