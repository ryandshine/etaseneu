"""Titik hotspot mentah dari NASA FIRMS: simpan, cari record-nya, dan baca terenrich metadata polygon."""

from collections.abc import Sequence
from datetime import datetime

from ._base import Json, _safe_json


class _HotspotObservationMixin:
    def upsert_hotspot_observations(self, hotspots: list[dict]) -> None:
        if not hotspots:
            return

        records = []
        for hotspot in hotspots:
            records.append(
                (
                    str(hotspot.get("source", "")),
                    str(hotspot.get("satellite", "")),
                    float(hotspot["latitude"]),
                    float(hotspot["longitude"]),
                    hotspot.get("brightness"),
                    hotspot.get("confidence"),
                    str(hotspot.get("detected_at", "")),
                    hotspot.get("layer_id"),
                    hotspot.get("layer_name"),
                    hotspot.get("agency_name"),
                    Json(hotspot),
                )
            )

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO hotspot_observations (
                        source,
                        satellite,
                        latitude,
                        longitude,
                        brightness,
                        confidence,
                        detected_at,
                        layer_key,
                        layer_name,
                        agency_name,
                        geom,
                        raw_payload
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                        %s
                    )
                    ON CONFLICT (
                        source,
                        satellite,
                        latitude,
                        longitude,
                        detected_at,
                        COALESCE(layer_key, '')
                    )
                    DO UPDATE SET
                        brightness = EXCLUDED.brightness,
                        confidence = EXCLUDED.confidence,
                        layer_name = EXCLUDED.layer_name,
                        agency_name = EXCLUDED.agency_name,
                        geom = EXCLUDED.geom,
                        raw_payload = EXCLUDED.raw_payload
                    """,
                    [
                        (
                            source,
                            satellite,
                            latitude,
                            longitude,
                            brightness,
                            confidence,
                            detected_at,
                            layer_key,
                            layer_name,
                            agency_name,
                            longitude,
                            latitude,
                            raw_payload,
                        )
                        for (
                            source,
                            satellite,
                            latitude,
                            longitude,
                            brightness,
                            confidence,
                            detected_at,
                            layer_key,
                            layer_name,
                            agency_name,
                            raw_payload,
                        ) in records
                    ],
                )

    def read_hotspot_observation_records(self, hotspots: Sequence[dict]) -> list[dict[str, object]]:
        if not hotspots:
            return []

        records: list[dict[str, object]] = []
        with self.connection() as conn:
            with conn.cursor() as cur:
                for hotspot in hotspots:
                    cur.execute(
                        """
                        SELECT id, source, satellite, latitude, longitude, detected_at, layer_key
                        FROM hotspot_observations
                        WHERE source = %s
                          AND satellite = %s
                          AND latitude = %s
                          AND longitude = %s
                          AND detected_at = %s
                          AND COALESCE(layer_key, '') = COALESCE(%s, '')
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (
                            str(hotspot.get("source", "")),
                            str(hotspot.get("satellite", "")),
                            float(hotspot["latitude"]),
                            float(hotspot["longitude"]),
                            hotspot["detected_at"],
                            hotspot.get("layer_id"),
                        ),
                    )
                    row = cur.fetchone()
                    if row:
                        records.append(row)

        return records

    def read_hotspot_observations(
        self,
        *,
        start_date: str,
        end_date: str,
        sources: list[str],
        layer_ids: list[str],
    ) -> list[dict]:
        if not sources or not layer_ids:
            return []

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH ranked_relation AS (
                        SELECT DISTINCT ON (obs.id)
                            obs.id AS observation_id,
                            obs.raw_payload,
                            p.id AS polygon_metadata_id,
                            p.feature_key,
                            p.feature_index,
                            p.lembaga,
                            p.nama_prov,
                            p.nama_kab,
                            p.nama_kec,
                            p.nama_desa,
                            p.skema,
                            p.no_sk,
                            p.tgl_sk,
                            p.status,
                            p.wilker_bps,
                            p.ps_id,
                            p.kode_prov,
                            p.kode_kab,
                            p.luas_hk,
                            p.luas_hl,
                            p.luas_hpt,
                            p.luas_hp,
                            p.luas_hpk,
                            p.luas_sk,
                            p.luas_poli,
                            p.luas_final,
                            p.jml_kk,
                            p.shape_leng,
                            p.shape_area,
                            p.properties_raw,
                            hkh.fungsikws AS khutan_kode,
                            hkh.nama_kawasan AS khutan_nama,
                            hkh.kelompok AS khutan_kelompok,
                            lbl.singkatan AS khutan_singkatan,
                            COALESCE(lbl.fungsi, 'Kode ' || hkh.fungsikws::text) AS khutan_fungsi
                        FROM hotspot_observations obs
                        JOIN polygon_metadata p
                          ON p.layer_key = obs.layer_key
                         AND p.is_active = TRUE
                         AND ST_Covers(p.geometry, obs.geom)
                        LEFT JOIN hotspot_kawasan_hutan hkh ON hkh.hotspot_id = obs.id
                        LEFT JOIN ref_fungsi_kawasan_label lbl ON lbl.kode = hkh.fungsikws
                        WHERE obs.detected_at >= %s::timestamptz AND obs.detected_at < %s::timestamptz
                          AND obs.source = ANY(%s)
                          AND obs.layer_key = ANY(%s)
                          AND obs.geom IS NOT NULL
                        ORDER BY obs.id ASC, p.feature_index ASC, p.id ASC
                    )
                    SELECT *
                    FROM ranked_relation
                    ORDER BY observation_id ASC
                    """,
                    (start_date, end_date, sources, layer_ids),
                )
                rows = cur.fetchall()

        payloads: list[dict] = []
        for row in rows:
            payload = _safe_json(row.get("raw_payload"), {})
            if isinstance(payload, dict):
                orig_metadata = payload.get("polygon_metadata") or {}
                polygon_metadata = {
                    "polygon_metadata_id": row.get("polygon_metadata_id"),
                    "feature_key": row.get("feature_key"),
                    "LEMBAGA": row.get("lembaga"),
                    "NAMA_PROV": row.get("nama_prov"),
                    "NAMA_KAB": row.get("nama_kab"),
                    "NAMA_KEC": row.get("nama_kec"),
                    "NAMA_DESA": row.get("nama_desa"),
                    "SKEMA": row.get("skema"),
                    "NO_SK": row.get("no_sk"),
                    "TGL_SK": row.get("tgl_sk"),
                    "Status": row.get("status"),
                    "WILKER_BPS": row.get("wilker_bps"),
                    "PS_ID": row.get("ps_id"),
                    "KODE_PROV": row.get("kode_prov"),
                    "KODE_KAB": row.get("kode_kab"),
                    "Luas_HK": row.get("luas_hk"),
                    "LUAS_HL": row.get("luas_hl"),
                    "LUAS_HPT": row.get("luas_hpt"),
                    "LUAS_HP": row.get("luas_hp"),
                    "LUAS_HPK": row.get("luas_hpk"),
                    "LUAS_SK": row.get("luas_sk"),
                    "Luas_Poli": row.get("luas_poli"),
                    "LuasFinal": row.get("luas_final"),
                    "Jml_KK": row.get("jml_kk"),
                    "Shape_Leng": row.get("shape_leng"),
                    "Shape_Area": row.get("shape_area"),
                    "properties_raw": _safe_json(row.get("properties_raw"), {}),
                }
                db_metadata = {
                    key: value
                    for key, value in polygon_metadata.items()
                    if value is not None and value != ""
                }
                merged_metadata = {**orig_metadata, **db_metadata}
                payload["polygon_metadata"] = merged_metadata

                kode = row.get("khutan_kode")
                kawasan = {
                    "kode": int(kode) if kode is not None else None,
                    "fungsi": row.get("khutan_fungsi"),
                    "singkatan": row.get("khutan_singkatan"),
                    "nama_kawasan": row.get("khutan_nama"),
                    "kelompok": row.get("khutan_kelompok"),
                }
                if any(value not in (None, "") for value in kawasan.values()):
                    payload["kawasan_hutan"] = kawasan

                payloads.append(payload)
        return payloads

    def get_hotspots_in_range(self, start_at: datetime, end_at: datetime) -> list[dict]:
        """Titik hotspot mentah dalam rentang waktu -- dipakai HotspotClusterService
        untuk menyusun ringkasan kompleks kebakaran (lihat find_proximity_edges
        untuk daftar pasangan tetangganya)."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        obs.id,
                        obs.latitude,
                        obs.longitude,
                        obs.detected_at,
                        obs.agency_name,
                        poly.polygon_metadata_id,
                        poly.polygon_agency_name,
                        poly.wilker_bps,
                        poly.nama_prov AS province_name
                    FROM hotspot_observations obs
                    LEFT JOIN LATERAL (
                        SELECT
                            p.id AS polygon_metadata_id,
                            p.lembaga AS polygon_agency_name,
                            p.wilker_bps,
                            p.nama_prov
                        FROM polygon_metadata p
                        WHERE p.is_active
                          AND p.layer_key = obs.layer_key
                          AND ST_Covers(p.geometry, obs.geom)
                        ORDER BY p.id ASC
                        LIMIT 1
                    ) poly ON TRUE
                    WHERE obs.detected_at >= %s::timestamptz AND obs.detected_at <= %s::timestamptz
                    ORDER BY obs.id ASC
                    """,
                    (start_at, end_at),
                )
                return cur.fetchall()

    def find_proximity_edges(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        eps_km: float,
        eps_hours: float,
    ) -> list[tuple[int, int]]:
        """Pasangan id hotspot yang "bertetangga" -- dekat secara ruang DAN waktu
        sekaligus -- dasar untuk pengelompokan graph-expansion (ST-DBSCAN) di
        HotspotClusterService.

        Threshold jarak dikonversi ke DERAJAT, bukan ST_DWithin(...::geography, ...):
        cast geography per-baris pada self-join sebesar ini bisa menggagalkan
        pemakaian index GIST yang sudah ada di kolom geom (geometry, SRID 4326).
        Konversi kasar 1 derajat ~= 111.32km cukup akurat untuk threshold
        skala kilometer-tunggal di rentang lintang Indonesia (-11 s.d. 6 derajat) --
        distorsi longitude akibat proyeksi di lintang ini di bawah 2%.
        """
        eps_degrees = eps_km / 111.32
        eps_seconds = eps_hours * 3600
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT a.id AS id_a, b.id AS id_b
                    FROM hotspot_observations a
                    JOIN hotspot_observations b
                      ON a.id < b.id
                     AND ST_DWithin(a.geom, b.geom, %s)
                     AND abs(extract(epoch FROM a.detected_at - b.detected_at)) <= %s
                    WHERE a.detected_at >= %s::timestamptz AND a.detected_at <= %s::timestamptz
                      AND b.detected_at >= %s::timestamptz AND b.detected_at <= %s::timestamptz
                    """,
                    (eps_degrees, eps_seconds, start_at, end_at, start_at, end_at),
                )
                rows = cur.fetchall()
        return [(row["id_a"], row["id_b"]) for row in rows]
