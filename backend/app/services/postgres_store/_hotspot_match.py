"""Mesin pencocokan spasial hotspot <-> poligon: SATU definisi "di dalam", dipakai bersama.

Kontrak lengkap: docs/hotspot-polygon-contract.md. Ringkasnya:

- Titik dianggap di dalam poligon aktif bila ``ST_Covers(analysis_geometry, obs.geom)`` --
  titik tepat di garis batas ikut terhitung. ``obs.layer_key`` BUKAN syarat spasial: itu label
  yang diberikan saat ingest (layer yang memuat titik waktu itu, atau ``perimeter_threat``),
  bukan fakta geometri.
- ``analysis_geometry`` = geometri sumber bila valid, kalau tidak ``ST_MakeValid`` lalu hanya
  bagian poligonnya (``ST_CollectionExtract(..., 3)``). Geometri sumber di ``polygon_metadata``
  TIDAK pernah diubah.
- Titik yang jatuh di >1 poligon aktif menghasilkan >1 pasangan (satu per poligon) -- semua
  dicatat, tidak ada "poligon pertama menang".
- Semua operasi idempoten (pasangan unik ``(observation, polygon)`` + ``ON CONFLICT``).
"""

import logging
from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("hotspot.postgres")

RELATION_MATCH_METHOD = "covers"
ANALYSIS_TIMEZONE = "Asia/Jakarta"
RECONCILE_CHUNK_DAYS = 31
DEFAULT_STATEMENT_TIMEOUT_MS = 120_000
DEFAULT_LOCK_TIMEOUT_MS = 5_000
# Kunci advisory (transaksi) yang menserialkan pembangunan ringkasan: scheduler dan permintaan
# pengguna bisa membangun ulang poligon yang sama bersamaan (DELETE + INSERT).
SUMMARY_ADVISORY_LOCK_KEY = 7_261_001


class HotspotRelationSyncError(RuntimeError):
    """Rekonsiliasi gagal di tengah jalan. ``progress`` = ringkasan chunk yang SUDAH tersimpan.

    Aman dijalankan ulang: operasi idempoten, jadi chunk yang sudah selesai tidak berubah.
    """

    def __init__(self, message: str, progress: dict[str, Any]) -> None:
        super().__init__(message)
        self.progress = progress


def active_polygons_cte_sql(*, polygon_filter: str = "") -> str:
    """CTE ``active_polygons``: poligon aktif + ``analysis_geometry`` (geometri valid).

    Di-MATERIALIZED supaya ``ST_IsValid``/``ST_MakeValid`` jalan SEKALI per poligon, bukan per
    pasangan. ``polygon_filter`` berupa potongan SQL ``AND ...`` dengan parameter bernama.
    """
    return f"""
        active_polygons AS MATERIALIZED (
            SELECT
                p.id,
                p.layer_key,
                p.geometry,
                CASE
                    WHEN ST_IsValid(p.geometry) THEN p.geometry
                    ELSE ST_CollectionExtract(ST_MakeValid(p.geometry), 3)
                END AS analysis_geometry
            FROM polygon_metadata p
            WHERE p.is_active = TRUE
              AND p.geometry IS NOT NULL
              {polygon_filter}
        )
    """


def pairs_cte_sql(*, polygon_filter: str = "", observation_filter: str = "") -> str:
    """CTE ``active_polygons`` + ``pairs`` (satu baris per pasangan observasi-poligon).

    ``obs.geom && p.geometry`` memakai indeks GiST observasi; bounding box geometri valid
    selalu di dalam bbox geometri sumber, jadi prefilter ini tidak membuang kandidat.
    ``observation_filter`` berupa potongan SQL ``AND ...`` atas alias ``obs`` dengan parameter
    bernama (``%(start_at)s`` ...) yang disuplai pemanggil.
    """
    return f"""
        {active_polygons_cte_sql(polygon_filter=polygon_filter)},
        pairs AS (
            SELECT
                obs.id AS observation_id,
                p.id AS polygon_id,
                p.layer_key AS polygon_layer_key,
                obs.detected_at,
                obs.source,
                obs.satellite
            FROM active_polygons p
            JOIN hotspot_observations obs
              ON obs.geom && p.geometry
             AND ST_Covers(p.analysis_geometry, obs.geom)
            WHERE obs.geom IS NOT NULL
              {observation_filter}
        )
    """


def _set_local_timeouts(
    cur: Any,
    statement_timeout_ms: int,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
) -> None:
    # SET tidak menerima parameter terikat; int() menutup kemungkinan injeksi.
    cur.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
    cur.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{name} harus timezone-aware (naive datetime ambigu antara UTC dan WIB)")


def _iter_windows(start_at: datetime, end_at: datetime, days: int) -> Iterator[tuple[datetime, datetime]]:
    step = timedelta(days=days)
    cursor = start_at
    while cursor < end_at:
        yield cursor, min(cursor + step, end_at)
        cursor += step


def window_filters(*, has_start: bool, has_end: bool) -> tuple[str, str]:
    """(polygon_filter, observation_filter) untuk jendela ``detected_at``.

    ``polygon_filter`` mempersempit ``active_polygons`` ke poligon yang bounding-box-nya memotong
    sedikitnya satu observasi di jendela (indeks btree ``detected_at`` + GiST poligon). Tanpa ini
    rencana kueri memvalidasi dan memprobe SELURUH poligon aktif (loops=8.598) walau jendelanya
    hanya 3 hari: filter waktu baru dipakai sesudah probe GiST. Hanya prefilter -- predikat final
    tetap ``ST_Covers`` di ``pairs``, jadi hasilnya tidak berubah.
    """
    conditions = []
    if has_start:
        conditions.append("{alias}.detected_at >= %(start_at)s")
    if has_end:
        conditions.append("{alias}.detected_at < %(end_at)s")
    if not conditions:
        return "", ""
    observation_filter = "AND " + " AND ".join(c.format(alias="obs") for c in conditions)
    candidate_where = " AND ".join(c.format(alias="co") for c in conditions)
    polygon_filter = f"""
              AND p.id IN (
                  SELECT cp.id
                  FROM hotspot_observations co
                  JOIN polygon_metadata cp ON cp.is_active = TRUE AND cp.geometry && co.geom
                  WHERE co.geom IS NOT NULL AND {candidate_where}
              )"""
    return polygon_filter, observation_filter


class _HotspotMatchMixin:
    def reconcile_hotspot_polygon_relations(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        polygon_ids: Sequence[int] | None = None,
        layer_keys: Sequence[str] | None = None,
        dry_run: bool = False,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> dict[str, Any]:
        """Lengkapi ``hotspot_polygon_relation`` untuk observasi pada ``[start_at, end_at)``.

        Hanya MENAMBAH pasangan yang hilang (dan menyelaraskan ``match_method``/``layer_key``
        pasangan lama); tidak menghapus apa pun. Rentang panjang dipecah per
        ``RECONCILE_CHUNK_DAYS`` hari, tiap chunk satu transaksi -- kalau satu chunk gagal,
        chunk sebelumnya tetap tersimpan dan ``HotspotRelationSyncError`` membawa progresnya.

        ``dry_run=True`` hanya menghitung (transaksi READ ONLY), tidak menulis.
        """
        _require_aware("start_at", start_at)
        _require_aware("end_at", end_at)
        totals: dict[str, Any] = {
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "dry_run": dry_run,
            "chunks": 0,
            "spatial_pairs": 0,
            "inserted": 0,
            "updated": 0,
            "missing_pairs": 0,
            "polygon_ids": [],
        }
        if end_at <= start_at:
            return totals

        affected: set[int] = set()
        for chunk_start, chunk_end in _iter_windows(start_at, end_at, RECONCILE_CHUNK_DAYS):
            try:
                chunk = self._reconcile_chunk(
                    chunk_start,
                    chunk_end,
                    polygon_ids=polygon_ids,
                    layer_keys=layer_keys,
                    dry_run=dry_run,
                    statement_timeout_ms=statement_timeout_ms,
                )
            except Exception as exc:
                totals["polygon_ids"] = sorted(affected)
                logger.exception(
                    "HOTSPOT RELATION: rekonsiliasi gagal pada chunk %s..%s (selesai sebelumnya: "
                    "%d chunk, +%d relasi)",
                    chunk_start.isoformat(),
                    chunk_end.isoformat(),
                    totals["chunks"],
                    totals["inserted"],
                )
                raise HotspotRelationSyncError(
                    f"Rekonsiliasi relasi gagal pada {chunk_start.isoformat()}..{chunk_end.isoformat()}: {exc}",
                    totals,
                ) from exc
            totals["chunks"] += 1
            for key in ("spatial_pairs", "inserted", "updated", "missing_pairs"):
                totals[key] += chunk[key]
            affected.update(chunk["polygon_ids"])

        totals["polygon_ids"] = sorted(affected)
        logger.info(
            "HOTSPOT RELATION: rekonsiliasi %s..%s selesai | pasangan spasial=%d, baru=%d, "
            "diselaraskan=%d, poligon terdampak=%d, dry_run=%s",
            totals["start_at"],
            totals["end_at"],
            totals["spatial_pairs"],
            totals["inserted"],
            totals["updated"],
            len(affected),
            dry_run,
        )
        return totals

    def _reconcile_chunk(
        self,
        start_at: datetime,
        end_at: datetime,
        *,
        polygon_ids: Sequence[int] | None,
        layer_keys: Sequence[str] | None,
        dry_run: bool,
        statement_timeout_ms: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "start_at": start_at,
            "end_at": end_at,
            "method": RELATION_MATCH_METHOD,
        }
        polygon_filter, observation_filter = window_filters(has_start=True, has_end=True)
        if polygon_ids is not None:
            params["polygon_ids"] = [int(pid) for pid in polygon_ids]
            polygon_filter += " AND p.id = ANY(%(polygon_ids)s)"
        if layer_keys is not None:
            params["layer_keys"] = [str(key) for key in layer_keys]
            polygon_filter += " AND p.layer_key = ANY(%(layer_keys)s)"
        cte = pairs_cte_sql(polygon_filter=polygon_filter, observation_filter=observation_filter)

        if dry_run:
            sql = f"""
                WITH {cte}
                SELECT
                    COUNT(*) AS spatial_pairs,
                    COUNT(*) FILTER (WHERE r.id IS NULL) AS missing_pairs,
                    COALESCE(
                        ARRAY_AGG(DISTINCT pairs.polygon_id) FILTER (WHERE r.id IS NULL), '{{}}'
                    ) AS polygon_ids
                FROM pairs
                LEFT JOIN hotspot_polygon_relation r
                  ON r.hotspot_observation_id = pairs.observation_id
                 AND r.polygon_metadata_id = pairs.polygon_id
            """
        else:
            sql = f"""
                WITH {cte},
                written AS (
                    INSERT INTO hotspot_polygon_relation (
                        hotspot_observation_id, polygon_metadata_id, layer_key, match_method
                    )
                    SELECT observation_id, polygon_id, polygon_layer_key, %(method)s FROM pairs
                    ON CONFLICT (hotspot_observation_id, polygon_metadata_id) DO UPDATE
                    SET match_method = EXCLUDED.match_method,
                        layer_key = EXCLUDED.layer_key,
                        matched_at = NOW()
                    WHERE hotspot_polygon_relation.match_method IS DISTINCT FROM EXCLUDED.match_method
                       OR hotspot_polygon_relation.layer_key IS DISTINCT FROM EXCLUDED.layer_key
                    RETURNING (xmax = 0) AS inserted
                )
                SELECT
                    (SELECT COUNT(*) FROM pairs) AS spatial_pairs,
                    (SELECT COUNT(*) FILTER (WHERE inserted) FROM written) AS inserted,
                    (SELECT COUNT(*) FILTER (WHERE NOT inserted) FROM written) AS updated,
                    (SELECT COALESCE(ARRAY_AGG(DISTINCT polygon_id), '{{}}') FROM pairs) AS polygon_ids
            """

        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if dry_run:
                        cur.execute("SET TRANSACTION READ ONLY")
                    _set_local_timeouts(cur, statement_timeout_ms)
                    cur.execute(sql, params)
                    row = cur.fetchone() or {}

        return {
            "spatial_pairs": int(row.get("spatial_pairs") or 0),
            "inserted": int(row.get("inserted") or 0),
            "updated": int(row.get("updated") or 0),
            "missing_pairs": int(row.get("missing_pairs") or 0) if dry_run else 0,
            "polygon_ids": [int(pid) for pid in (row.get("polygon_ids") or [])],
        }

    def sync_hotspot_relations_and_summaries(
        self, *, start_at: datetime, end_at: datetime
    ) -> dict[str, Any]:
        """Relasi dulu, ringkasan sesudahnya -- ringkasan TIDAK disentuh bila relasi gagal.

        Ringkasan dibangun ulang untuk poligon yang memuat hotspot pada jendela itu; isinya
        dihitung dari himpunan observasi lengkap poligon tersebut (bukan hanya jendela).
        """
        relation = self.reconcile_hotspot_polygon_relations(start_at=start_at, end_at=end_at)
        polygon_ids = relation.pop("polygon_ids")
        try:
            rebuilt = self.rebuild_polygon_hotspot_summary(polygon_ids) if polygon_ids else 0
        except Exception as exc:
            logger.exception(
                "HOTSPOT SUMMARY: relasi tersimpan (+%d) tetapi pembangunan ringkasan %d poligon gagal",
                relation["inserted"],
                len(polygon_ids),
            )
            raise HotspotRelationSyncError(
                f"Relasi tersimpan, ringkasan gagal dibangun: {exc}", relation
            ) from exc
        return {**relation, "polygon_count": len(polygon_ids), "summary_rebuilt": rebuilt}

    def hotspot_relation_integrity_report(
        self,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> dict[str, Any]:
        """Laporan integritas BACA-SAJA (transaksi READ ONLY).

        - ``orphan_*``: relasi yang menunjuk observasi/poligon yang tidak ada.
        - ``inactive_polygon_rows``: relasi ke poligon nonaktif (riwayat layer lama).
        - ``missing_pairs``: pasangan yang SECARA SPASIAL benar tetapi belum ada di relasi.
        - ``stale_pairs``: relasi ke poligon aktif yang secara spasial tidak lagi benar.
        ``start_at``/``end_at`` (opsional) membatasi pemeriksaan spasial berdasarkan waktu deteksi.
        """
        params: dict[str, Any] = {}
        if start_at is not None:
            _require_aware("start_at", start_at)
            params["start_at"] = start_at
        if end_at is not None:
            _require_aware("end_at", end_at)
            params["end_at"] = end_at
        polygon_filter, observation_filter = window_filters(
            has_start=start_at is not None, has_end=end_at is not None
        )

        structure_sql = """
            SELECT
                (SELECT COUNT(*) FROM hotspot_observations) AS observations,
                COUNT(*) AS relation_rows,
                COUNT(*) FILTER (WHERE h.id IS NULL) AS orphan_hotspot_rows,
                COUNT(DISTINCT r.hotspot_observation_id) FILTER (WHERE h.id IS NULL) AS orphan_hotspot_ids,
                COUNT(*) FILTER (WHERE p.id IS NULL) AS orphan_polygon_rows,
                COUNT(*) FILTER (
                    WHERE h.id IS NOT NULL AND p.id IS NOT NULL AND p.is_active IS NOT TRUE
                ) AS inactive_polygon_rows,
                COUNT(*) FILTER (WHERE h.id IS NOT NULL AND p.is_active IS TRUE) AS valid_rows,
                COUNT(DISTINCT r.hotspot_observation_id) FILTER (
                    WHERE h.id IS NOT NULL AND p.is_active IS TRUE
                ) AS valid_hotspots
            FROM hotspot_polygon_relation r
            LEFT JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
            LEFT JOIN polygon_metadata p ON p.id = r.polygon_metadata_id
        """
        missing_sql = f"""
            WITH {pairs_cte_sql(polygon_filter=polygon_filter, observation_filter=observation_filter)}
            SELECT
                COUNT(*) AS spatial_pairs,
                COUNT(DISTINCT pairs.observation_id) AS spatial_hotspots,
                COUNT(*) FILTER (WHERE r.id IS NULL) AS missing_pairs,
                COUNT(DISTINCT pairs.observation_id) FILTER (WHERE r.id IS NULL) AS hotspots_missing_relation
            FROM pairs
            LEFT JOIN hotspot_polygon_relation r
              ON r.hotspot_observation_id = pairs.observation_id
             AND r.polygon_metadata_id = pairs.polygon_id
        """
        stale_sql = f"""
            -- tanpa filter kandidat bbox: poligon yang geometrinya berubah bisa tak lagi memotong
            -- bbox titiknya, dan justru pasangan semacam itulah yang dicari di sini
            WITH {active_polygons_cte_sql()}
            SELECT COUNT(*) AS stale_pairs
            FROM hotspot_polygon_relation r
            JOIN hotspot_observations obs ON obs.id = r.hotspot_observation_id
            JOIN active_polygons p ON p.id = r.polygon_metadata_id
            WHERE obs.geom IS NOT NULL
              {observation_filter}
              AND NOT ST_Covers(p.analysis_geometry, obs.geom)
        """

        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    _set_local_timeouts(cur, statement_timeout_ms)
                    cur.execute(structure_sql)
                    structure = dict(cur.fetchone() or {})
                    cur.execute(missing_sql, params)
                    missing = dict(cur.fetchone() or {})
                    cur.execute(stale_sql, params)
                    stale = dict(cur.fetchone() or {})

        report = {key: int(value or 0) for key, value in {**structure, **missing, **stale}.items()}
        report["window"] = {
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
        }
        return report

    def prune_orphan_relations(self, *, dry_run: bool = True) -> dict[str, int]:
        """Hapus relasi yatim (observasi sudah tidak ada). ``dry_run=True`` secara bawaan.

        JANGAN dijalankan di produksi tanpa persetujuan: verifikasi dulu bahwa baris yatim memang
        tidak dibutuhkan untuk audit historis (lihat migration plan). Tidak ada endpoint yang
        memanggil dengan ``dry_run=False``.
        """
        count_sql = """
            SELECT COUNT(*) AS orphan_rows, COUNT(DISTINCT r.hotspot_observation_id) AS orphan_ids
            FROM hotspot_polygon_relation r
            WHERE NOT EXISTS (SELECT 1 FROM hotspot_observations h WHERE h.id = r.hotspot_observation_id)
        """
        with self.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    if dry_run:
                        cur.execute("SET TRANSACTION READ ONLY")
                    _set_local_timeouts(cur, DEFAULT_STATEMENT_TIMEOUT_MS)
                    cur.execute(count_sql)
                    counts = cur.fetchone() or {}
                    deleted = 0
                    if not dry_run:
                        cur.execute(
                            """
                            DELETE FROM hotspot_polygon_relation r
                            WHERE NOT EXISTS (
                                SELECT 1 FROM hotspot_observations h WHERE h.id = r.hotspot_observation_id
                            )
                            """
                        )
                        deleted = int(getattr(cur, "rowcount", 0) or 0)
        return {
            "orphan_rows": int(counts.get("orphan_rows") or 0),
            "orphan_ids": int(counts.get("orphan_ids") or 0),
            "deleted": deleted,
        }
