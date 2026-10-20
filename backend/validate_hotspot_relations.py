"""Validasi BACA-SAJA relasi/ringkasan hotspot terhadap hitungan spasial referensi.

Memakai ``VALIDATE_DATABASE_URL`` (bukan ``DATABASE_URL`` -- supaya tidak menembak produksi tanpa
sengaja). Semua query berjalan dalam transaksi READ ONLY dengan statement_timeout dan diakhiri
rollback; skrip ini tidak pernah menulis. ``VALIDATE_SCHEMA`` (opsional) memilih skema.

    VALIDATE_DATABASE_URL=postgresql://... VALIDATE_SCHEMA=prodcopy \\
        .venv/bin/python backend/validate_hotspot_relations.py [--start 2026-01-01] [--end 2026-11-01] [--json out.json]

Definisi (docs/hotspot-polygon-contract.md): titik di dalam poligon aktif = ``ST_Covers`` atas
geometri valid; satu titik di >1 poligon dihitung SEKALI secara regional, tetapi sekali per poligon
di hitungan per-poligon (jangan dijumlahkan menjadi "total hotspot").
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.services.postgres_store._hotspot_match import (  # noqa: E402
    active_polygons_cte_sql,
    pairs_cte_sql,
)

KPS_LAYER = "psagustus2026"
HUTAN_ADAT_LAYER = "HUTAN_ADAT_APR26"
WIB = "Asia/Jakarta"


def _connect():
    url = os.environ.get("VALIDATE_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Set VALIDATE_DATABASE_URL (sengaja bukan DATABASE_URL).")
    schema = os.environ.get("VALIDATE_SCHEMA", "").strip()
    conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=8)
    conn.execute("BEGIN READ ONLY")
    conn.execute("SET LOCAL statement_timeout = '600s'")
    conn.execute("SET LOCAL lock_timeout = '2s'")
    if schema:
        conn.execute(f'SET LOCAL search_path = "{schema}", public')
    return conn


def _timed(conn, label: str, sql: str, params: dict[str, Any]) -> tuple[list[dict], float]:
    started = time.perf_counter()
    rows = conn.execute(sql, params).fetchall()
    return rows, time.perf_counter() - started


def collect(conn, start: datetime, end: datetime) -> dict[str, Any]:
    window = {"start_at": start, "end_at": end}
    obs_filter = "AND obs.detected_at >= %(start_at)s AND obs.detected_at < %(end_at)s"
    cte = pairs_cte_sql(observation_filter=obs_filter)
    report: dict[str, Any] = {"window": {"start": start.isoformat(), "end": end.isoformat()}, "timing_s": {}}

    # 1. observasi
    row = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE geom IS NULL) AS tanpa_geom, MIN(detected_at) AS awal, MAX(detected_at) AS akhir "
        "FROM hotspot_observations WHERE detected_at >= %(start_at)s AND detected_at < %(end_at)s",
        window,
    ).fetchone()
    report["observasi"] = {
        "jumlah": row["n"],
        "tanpa_geometri": row["tanpa_geom"],
        "awal": row["awal"].isoformat() if row["awal"] else None,
        "akhir": row["akhir"].isoformat() if row["akhir"] else None,
    }

    # 2. integritas relasi (struktur seluruh tabel + pasangan spasial pada jendela)
    rows, took = _timed(
        conn,
        "integritas",
        """
        SELECT
            COUNT(*) AS relation_rows,
            COUNT(*) FILTER (WHERE h.id IS NULL) AS yatim_baris,
            COUNT(DISTINCT r.hotspot_observation_id) FILTER (WHERE h.id IS NULL) AS yatim_hotspot_unik,
            COUNT(*) FILTER (WHERE h.id IS NOT NULL AND p.is_active IS NOT TRUE) AS ke_poligon_nonaktif,
            COUNT(*) FILTER (WHERE h.id IS NOT NULL AND p.is_active IS TRUE) AS valid_baris,
            COUNT(DISTINCT r.hotspot_observation_id) FILTER (WHERE h.id IS NOT NULL AND p.is_active IS TRUE) AS valid_hotspot_unik
        FROM hotspot_polygon_relation r
        LEFT JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
        LEFT JOIN polygon_metadata p ON p.id = r.polygon_metadata_id
        """,
        {},
    )
    report["relasi"] = {k: int(v or 0) for k, v in rows[0].items()}
    report["timing_s"]["integritas_relasi"] = round(took, 2)

    # 3. pasangan spasial referensi: titik unik regional, per layer, tumpang tindih, kelengkapan relasi
    rows, took = _timed(
        conn,
        "spasial",
        f"""
        WITH {cte},
        per_hotspot AS (
            SELECT observation_id,
                   COUNT(*) AS n_polygons,
                   BOOL_OR(polygon_layer_key = '{KPS_LAYER}') AS in_kps,
                   BOOL_OR(polygon_layer_key = '{HUTAN_ADAT_LAYER}') AS in_ha
            FROM pairs GROUP BY observation_id
        )
        SELECT
            COUNT(*) AS titik_unik_regional,
            COUNT(*) FILTER (WHERE in_kps) AS titik_unik_kps,
            COUNT(*) FILTER (WHERE in_ha) AS titik_unik_hutan_adat,
            COUNT(*) FILTER (WHERE in_kps AND in_ha) AS titik_di_kps_dan_hutan_adat,
            COUNT(*) FILTER (WHERE n_polygons > 1) AS titik_di_lebih_dari_satu_poligon,
            COALESCE(MAX(n_polygons), 0) AS maks_poligon_per_titik,
            COALESCE(SUM(n_polygons), 0) AS jumlah_pasangan_titik_poligon
        FROM per_hotspot
        """,
        window,
    )
    report["spasial_referensi"] = {k: int(v or 0) for k, v in rows[0].items()}
    report["timing_s"]["pasangan_spasial"] = round(took, 2)

    rows, took = _timed(
        conn,
        "kelengkapan",
        f"""
        WITH {cte}
        SELECT COUNT(*) AS pasangan_spasial,
               COUNT(*) FILTER (WHERE r.id IS NULL) AS pasangan_belum_di_relasi,
               COUNT(DISTINCT pairs.observation_id) AS titik_unik,
               COUNT(DISTINCT pairs.observation_id) FILTER (WHERE r.id IS NULL) AS titik_unik_tanpa_relasi
        FROM pairs
        LEFT JOIN hotspot_polygon_relation r
          ON r.hotspot_observation_id = pairs.observation_id AND r.polygon_metadata_id = pairs.polygon_id
        """,
        window,
    )
    k = {key: int(v or 0) for key, v in rows[0].items()}
    k["kelengkapan_relasi_pct"] = round(100.0 * (k["pasangan_spasial"] - k["pasangan_belum_di_relasi"]) / max(k["pasangan_spasial"], 1), 2)
    report["kelengkapan_relasi"] = k
    report["timing_s"]["kelengkapan_relasi"] = round(took, 2)

    rows, _ = _timed(
        conn,
        "stale",
        f"""
        WITH {active_polygons_cte_sql()}
        SELECT COUNT(*) AS pasangan_usang
        FROM hotspot_polygon_relation r
        JOIN hotspot_observations obs ON obs.id = r.hotspot_observation_id
        JOIN active_polygons p ON p.id = r.polygon_metadata_id
        WHERE obs.geom IS NOT NULL
          AND obs.detected_at >= %(start_at)s AND obs.detected_at < %(end_at)s
          AND NOT ST_Covers(p.analysis_geometry, obs.geom)
        """,
        window,
    )
    report["relasi"]["pasangan_usang"] = int(rows[0]["pasangan_usang"])

    # 4. ringkasan tahunan vs referensi spasial (per poligon-tahun WIB)
    rows, took = _timed(
        conn,
        "ringkasan",
        f"""
        WITH {pairs_cte_sql()},
        ref AS (
            SELECT polygon_id AS pid, EXTRACT(YEAR FROM detected_at AT TIME ZONE '{WIB}')::int AS year,
                   COUNT(DISTINCT observation_id) AS n
            FROM pairs GROUP BY 1, 2
        ),
        j AS (
            SELECT COALESCE(ref.pid, s.polygon_metadata_id) AS pid, COALESCE(ref.year, s.year) AS year,
                   ref.n AS n_ref, s.hotspot_count AS n_summary
            FROM ref FULL JOIN polygon_hotspot_summary s
              ON s.polygon_metadata_id = ref.pid AND s.year = ref.year
        )
        SELECT
            CASE WHEN n_summary IS NULL THEN '1 punya hotspot, TIDAK ada baris ringkasan'
                 WHEN n_ref IS NULL THEN '2 ada baris ringkasan, referensi 0 (poligon nonaktif/dihapus)'
                 WHEN n_summary = n_ref THEN '3 ringkasan = referensi'
                 WHEN n_summary < n_ref THEN '4 ringkasan < referensi (kurang)'
                 ELSE '5 ringkasan > referensi (lebih)' END AS kategori,
            COUNT(*) AS poligon_tahun,
            COALESCE(SUM(n_ref), 0) AS jumlah_referensi,
            COALESCE(SUM(n_summary), 0) AS jumlah_ringkasan,
            COALESCE(SUM(n_ref), 0) - COALESCE(SUM(n_summary), 0) AS selisih
        FROM j GROUP BY 1 ORDER BY 1
        """,
        {},
    )
    report["ringkasan_vs_referensi"] = [{k: (int(v) if k != "kategori" else v) for k, v in r.items()} for r in rows]
    report["timing_s"]["ringkasan_vs_referensi"] = round(took, 2)

    # 5. per poligon per tahun (agregat) -- untuk diff antar-laporan
    rows, _ = _timed(
        conn,
        "per_tahun",
        f"""
        WITH {pairs_cte_sql()}
        SELECT EXTRACT(YEAR FROM detected_at AT TIME ZONE '{WIB}')::int AS year,
               COUNT(DISTINCT polygon_id) AS poligon_terkena,
               COUNT(DISTINCT observation_id) AS titik_unik_regional,
               COUNT(*) AS jumlah_pasangan
        FROM pairs GROUP BY 1 ORDER BY 1
        """,
        {},
    )
    report["per_tahun"] = [{k: int(v) for k, v in r.items()} for r in rows]

    # 6. konsumen hilir yang membaca tabel relasi (kps_catalog_service): 30 hari terakhir
    rows, _ = _timed(
        conn,
        "konsumen",
        f"""
        WITH {pairs_cte_sql(observation_filter="AND obs.detected_at >= CURRENT_DATE - INTERVAL '30 days'")}
        SELECT
          (SELECT COUNT(DISTINCT r.polygon_metadata_id)
             FROM hotspot_polygon_relation r JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
            WHERE h.detected_at >= CURRENT_DATE - INTERVAL '30 days') AS kps_terdampak_30h_via_relasi,
          (SELECT COUNT(DISTINCT polygon_id) FROM pairs) AS kps_terdampak_30h_referensi_spasial
        """,
        {},
    )
    report["konsumen_relasi_30_hari"] = {k: int(v) for k, v in rows[0].items()}
    return report


def _print(report: dict[str, Any]) -> None:
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-11-01", help="eksklusif")
    parser.add_argument("--json", default=None, help="tulis laporan ke berkas ini")
    args = parser.parse_args()

    start = datetime.fromisoformat(args.start + "T00:00:00+07:00")
    end = datetime.fromisoformat(args.end + "T00:00:00+07:00")
    conn = _connect()
    try:
        report = collect(conn, start, end)
    finally:
        conn.rollback()
        conn.close()
    _print(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
