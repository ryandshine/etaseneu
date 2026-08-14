"""Metadata polygon KPS: upsert dari sinkronisasi, lookup id, dan detail/geometry untuk ditampilkan."""

import json
from collections.abc import Sequence
from typing import Any

from ._base import Json, _safe_json


class _PolygonMetadataMixin:
    def upsert_polygon_metadata(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0

        params: list[tuple[object, ...]] = []
        for record in records:
            geometry = json.dumps(record["geometry"], ensure_ascii=False)
            params.append(
                (
                    record["layer_key"],
                    record["feature_key"],
                    record["feature_index"],
                    record.get("lembaga"),
                    record.get("nama_prov"),
                    record.get("nama_kab"),
                    record.get("nama_kec"),
                    record.get("nama_desa"),
                    record.get("skema"),
                    record.get("no_sk"),
                    record.get("tgl_sk"),
                    record.get("status"),
                    record.get("wilker_bps"),
                    record.get("ps_id"),
                    record.get("kode_prov"),
                    record.get("kode_kab"),
                    record.get("luas_hk"),
                    record.get("luas_hl"),
                    record.get("luas_hpt"),
                    record.get("luas_hp"),
                    record.get("luas_hpk"),
                    record.get("luas_sk"),
                    record.get("luas_poli"),
                    record.get("luas_final"),
                    record.get("jml_kk"),
                    record.get("shape_leng"),
                    record.get("shape_area"),
                    geometry,
                    Json(record.get("properties_raw", {})),
                    record["source_file"],
                    record["file_checksum"],
                    record.get("is_active", True),
                )
            )

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO polygon_metadata (
                        layer_key,
                        feature_key,
                        feature_index,
                        lembaga,
                        nama_prov,
                        nama_kab,
                        nama_kec,
                        nama_desa,
                        skema,
                        no_sk,
                        tgl_sk,
                        status,
                        wilker_bps,
                        ps_id,
                        kode_prov,
                        kode_kab,
                        luas_hk,
                        luas_hl,
                        luas_hpt,
                        luas_hp,
                        luas_hpk,
                        luas_sk,
                        luas_poli,
                        luas_final,
                        jml_kk,
                        shape_leng,
                        shape_area,
                        geometry,
                        properties_raw,
                        source_file,
                        file_checksum,
                        is_active
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)), %s, %s, %s, %s
                    )
                    ON CONFLICT (layer_key, feature_key)
                    DO UPDATE SET
                        feature_index = EXCLUDED.feature_index,
                        lembaga = EXCLUDED.lembaga,
                        nama_prov = EXCLUDED.nama_prov,
                        nama_kab = EXCLUDED.nama_kab,
                        nama_kec = EXCLUDED.nama_kec,
                        nama_desa = EXCLUDED.nama_desa,
                        skema = EXCLUDED.skema,
                        no_sk = EXCLUDED.no_sk,
                        tgl_sk = EXCLUDED.tgl_sk,
                        status = EXCLUDED.status,
                        wilker_bps = EXCLUDED.wilker_bps,
                        ps_id = EXCLUDED.ps_id,
                        kode_prov = EXCLUDED.kode_prov,
                        kode_kab = EXCLUDED.kode_kab,
                        luas_hk = EXCLUDED.luas_hk,
                        luas_hl = EXCLUDED.luas_hl,
                        luas_hpt = EXCLUDED.luas_hpt,
                        luas_hp = EXCLUDED.luas_hp,
                        luas_hpk = EXCLUDED.luas_hpk,
                        luas_sk = EXCLUDED.luas_sk,
                        luas_poli = EXCLUDED.luas_poli,
                        luas_final = EXCLUDED.luas_final,
                        jml_kk = EXCLUDED.jml_kk,
                        shape_leng = EXCLUDED.shape_leng,
                        shape_area = EXCLUDED.shape_area,
                        geometry = EXCLUDED.geometry,
                        properties_raw = EXCLUDED.properties_raw,
                        source_file = EXCLUDED.source_file,
                        file_checksum = EXCLUDED.file_checksum,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """,
                    params,
                )

        return len(params)

    def deactivate_missing_polygons(self, layer_key: str, active_feature_keys: Sequence[str]) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                if active_feature_keys:
                    cur.execute(
                        """
                        UPDATE polygon_metadata
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE layer_key = %s
                          AND is_active = TRUE
                          AND NOT (feature_key = ANY(%s))
                        """,
                        (layer_key, list(active_feature_keys)),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE polygon_metadata
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE layer_key = %s
                          AND is_active = TRUE
                        """,
                        (layer_key,),
                    )
                return cur.rowcount

    def read_polygon_metadata_ids(
        self,
        *,
        layer_key: str,
        feature_keys: Sequence[str],
    ) -> dict[str, int]:
        if not feature_keys:
            return {}

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, feature_key
                    FROM polygon_metadata
                    WHERE layer_key = %s
                      AND feature_key = ANY(%s)
                    """,
                    (layer_key, list(feature_keys)),
                )
                rows = cur.fetchall()

        return {str(row["feature_key"]): int(row["id"]) for row in rows}

    def read_polygon_metadata_ids_by_index(
        self,
        *,
        layer_key: str,
        feature_indices: Sequence[int],
    ) -> dict[int, int]:
        if not feature_indices:
            return {}

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, feature_index
                    FROM polygon_metadata
                    WHERE layer_key = %s
                      AND feature_index = ANY(%s)
                    """,
                    (layer_key, list(feature_indices)),
                )
                rows = cur.fetchall()

        return {int(row["feature_index"]): int(row["id"]) for row in rows}

    def read_active_polygon_metadata_ids(self, layer_keys: Sequence[str] | None = None) -> list[int]:
        params: tuple[object, ...] = ()
        where_clause = "WHERE is_active = TRUE"
        if layer_keys:
            unique_layer_keys = [str(layer_key) for layer_key in dict.fromkeys(layer_keys)]
            where_clause = "WHERE is_active = TRUE AND layer_key = ANY(%s)"
            params = (unique_layer_keys,)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id
                    FROM polygon_metadata
                    {where_clause}
                    ORDER BY layer_key ASC, feature_index ASC, id ASC
                    """,
                    params,
                )
                rows = cur.fetchall()

        return [int(row["id"]) for row in rows]

    def read_polygon_detail(self, polygon_metadata_id: int) -> dict[str, object] | None:
        """Ambil satu polygon (geometry + atribut) buat halaman detail KPS --
        beda dari read_polygon_hotspot_summary yang query banyak sekaligus
        untuk agregat, ini query satu baris by primary key.

        Geometry-nya disederhanakan (ST_SimplifyPreserveTopology) sebelum
        dikirim: beberapa polygon di dataset asli punya puluhan ribu titik
        koordinat (batas administratif detail), dan mengirim itu mentah-mentah
        membuat render peta di HP nge-hang/gagal diam-diam. Toleransi
        0.0001 derajat (~11m) jauh di bawah presisi visual yang kelihatan
        setelah peta di-fit ke batas polygon ini.
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        layer_key,
                        feature_key,
                        lembaga,
                        nama_prov,
                        nama_kab,
                        nama_kec,
                        nama_desa,
                        skema,
                        no_sk,
                        tgl_sk,
                        status,
                        wilker_bps,
                        ps_id,
                        luas_final,
                        jml_kk,
                        ST_AsGeoJSON(COALESCE(ST_SimplifyPreserveTopology(geometry, 0.0001), geometry))::json AS geometry_json
                    FROM polygon_metadata
                    WHERE id = %s AND is_active = TRUE
                    """,
                    (polygon_metadata_id,),
                )
                row = cur.fetchone()

        if row is None:
            return None

        return {
            "id": int(row["id"]),
            "layer_key": row["layer_key"],
            "feature_key": row["feature_key"],
            "lembaga": row.get("lembaga"),
            "nama_prov": row.get("nama_prov"),
            "nama_kab": row.get("nama_kab"),
            "nama_kec": row.get("nama_kec"),
            "nama_desa": row.get("nama_desa"),
            "skema": row.get("skema"),
            "no_sk": row.get("no_sk"),
            "tgl_sk": row.get("tgl_sk"),
            "status": row.get("status"),
            "wilker_bps": row.get("wilker_bps"),
            "ps_id": row.get("ps_id"),
            "luas_final": row.get("luas_final"),
            "jml_kk": row.get("jml_kk"),
            "geometry": _safe_json(row.get("geometry_json"), {}),
        }

    def read_polygon_geometries(
        self, polygon_ids: Sequence[int], *, tolerance: float = 0.001
    ) -> dict[int, dict[str, object]]:
        """Ambil geometry beberapa polygon sekaligus, untuk digambar di laporan.

        Disederhanakan jauh lebih agresif (default ~110m) daripada endpoint
        detail KPS: hasilnya dipakai sebagai peta kecil di PDF, di mana lekuk
        batas sedetail itu tidak akan terlihat, sementara geometry mentah bisa
        berisi puluhan ribu titik dan membuat berkasnya membengkak.
        """
        if not polygon_ids:
            return {}

        unique_ids = sorted({int(pid) for pid in polygon_ids})

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        ST_AsGeoJSON(
                            COALESCE(ST_SimplifyPreserveTopology(geometry, %s), geometry)
                        )::json AS geometry_json
                    FROM polygon_metadata
                    WHERE id = ANY(%s) AND is_active = TRUE
                    """,
                    (tolerance, unique_ids),
                )
                rows = cur.fetchall()

        geometries: dict[int, dict[str, object]] = {}
        for row in rows:
            geometry = _safe_json(row.get("geometry_json"), {})
            if isinstance(geometry, dict) and geometry:
                geometries[int(row["id"])] = geometry
        return geometries
