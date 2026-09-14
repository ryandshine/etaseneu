"""Layanan katalog data KPS nasional (7.000+ unit izin/persetujuan Perhutanan Sosial).

Menyediakan:
1. Pencarian, filter berjenjang, dan server-side pagination untuk tabel direktori.
2. Agregat KPI nasional & metadata dropdown filter (dicache).
3. Ekspor data terfilter ke CSV atau streaming data.
"""

from __future__ import annotations

import csv
import io
import time
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


class KpsCatalogService:
    def __init__(self, database_url: str | None = None) -> None:
        db_url = database_url or get_settings().database_url
        self.store = PostgresStore(db_url)
        self._meta_cache: dict[str, Any] | None = None
        self._meta_cache_time: float = 0.0

    def get_catalog_meta(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        # Cache meta selama 10 menit
        if not force_refresh and self._meta_cache is not None and (now - self._meta_cache_time) < 600:
            return self._meta_cache

        if not self.store.enabled:
            return {
                "summary": {
                    "total_kps": 0,
                    "total_luas_ha": 0.0,
                    "total_provinsi": 0,
                    "total_balai": 0,
                    "kps_hotspot_30d": 0,
                    "kps_burned": 0,
                },
                "filters": {
                    "skemas": [],
                    "wilkers": [],
                    "provinces": [],
                },
            }

        with self.store.connection() as conn:
            with conn.cursor() as cur:
                # 1. Total KPS, Luas, Provinsi, Balai
                cur.execute("""
                    SELECT 
                        count(*) as total_kps,
                        COALESCE(sum(luas_final::numeric), 0) as total_luas_ha,
                        count(DISTINCT nama_prov) as total_provinsi,
                        count(DISTINCT wilker_bps) as total_balai
                    FROM polygon_metadata
                    WHERE is_active = true;
                """)
                base_sum = cur.fetchone() or {}

                # 2. KPS terdampak hotspot 30 hari
                cur.execute("""
                    SELECT count(DISTINCT r.polygon_metadata_id) as kps_hotspot_30d
                    FROM hotspot_polygon_relation r
                    JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
                    WHERE h.detected_at >= CURRENT_DATE - INTERVAL '30 days';
                """)
                hs_sum = cur.fetchone() or {}

                # 3. KPS dengan histori terbakar
                cur.execute("""
                    SELECT count(DISTINCT polygon_metadata_id) as kps_burned
                    FROM burned_area_summary;
                """)
                burned_sum = cur.fetchone() or {}

                # 4. List Skema
                cur.execute("""
                    SELECT DISTINCT skema
                    FROM polygon_metadata
                    WHERE is_active = true AND skema IS NOT NULL AND TRIM(skema) != ''
                    ORDER BY skema ASC;
                """)
                skemas = [r["skema"] for r in cur.fetchall()]

                # 5. List Balai PS (Wilker)
                cur.execute("""
                    SELECT DISTINCT wilker_bps
                    FROM polygon_metadata
                    WHERE is_active = true AND wilker_bps IS NOT NULL AND TRIM(wilker_bps) != ''
                    ORDER BY wilker_bps ASC;
                """)
                wilkers = [r["wilker_bps"] for r in cur.fetchall()]

                # 6. List Provinsi
                cur.execute("""
                    SELECT DISTINCT nama_prov
                    FROM polygon_metadata
                    WHERE is_active = true AND nama_prov IS NOT NULL AND TRIM(nama_prov) != ''
                    ORDER BY nama_prov ASC;
                """)
                provinces = [r["nama_prov"] for r in cur.fetchall()]

        meta = {
            "summary": {
                "total_kps": int(base_sum.get("total_kps") or 0),
                "total_luas_ha": float(base_sum.get("total_luas_ha") or 0.0),
                "total_provinsi": int(base_sum.get("total_provinsi") or 0),
                "total_balai": int(base_sum.get("total_balai") or 0),
                "kps_hotspot_30d": int(hs_sum.get("kps_hotspot_30d") or 0),
                "kps_burned": int(burned_sum.get("kps_burned") or 0),
            },
            "filters": {
                "skemas": skemas,
                "wilkers": wilkers,
                "provinces": provinces,
            },
        }
        self._meta_cache = meta
        self._meta_cache_time = now
        return meta

    def get_kps_catalog(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        search: str | None = None,
        wilker: str | None = None,
        province: str | None = None,
        regency: str | None = None,
        skema: str | None = None,
        has_hotspot_30d: bool | None = None,
        has_burned_area: bool | None = None,
        sort_by: str = "lembaga",
        sort_dir: str = "asc",
    ) -> dict[str, Any]:
        """Ambil data KPS berhalaman dengan filter dinamis terindeks."""
        page = max(1, page)
        page_size = max(5, min(page_size, 100))
        offset = (page - 1) * page_size

        if not self.store.enabled:
            return {
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_records": 0,
                    "total_pages": 0,
                },
                "items": [],
            }

        conditions = ["p.is_active = true"]
        params: list[Any] = []

        if search and search.strip():
            pat = f"%{search.strip()}%"
            conditions.append("""
                (
                    p.lembaga ILIKE %s OR 
                    p.no_sk ILIKE %s OR 
                    p.nama_desa ILIKE %s OR 
                    p.nama_kec ILIKE %s OR 
                    p.nama_kab ILIKE %s
                )
            """)
            params.extend([pat, pat, pat, pat, pat])

        if wilker and wilker.strip():
            conditions.append("p.wilker_bps = %s")
            params.append(wilker.strip())

        if province and province.strip():
            conditions.append("p.nama_prov = %s")
            params.append(province.strip())

        if regency and regency.strip():
            conditions.append("p.nama_kab = %s")
            params.append(regency.strip())

        if skema and skema.strip():
            conditions.append("p.skema = %s")
            params.append(skema.strip())

        if has_hotspot_30d:
            conditions.append("""
                p.id IN (
                    SELECT DISTINCT r.polygon_metadata_id
                    FROM hotspot_polygon_relation r
                    JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
                    WHERE h.detected_at >= CURRENT_DATE - INTERVAL '30 days'
                )
            """)

        if has_burned_area:
            conditions.append("""
                p.id IN (
                    SELECT DISTINCT polygon_metadata_id
                    FROM burned_area_summary
                )
            """)

        where_clause = " WHERE " + " AND ".join(conditions)

        # Sanitasi sorting
        sort_map = {
            "lembaga": "p.lembaga",
            "luas_final": "p.luas_final::numeric",
            "nama_prov": "p.nama_prov",
            "nama_kab": "p.nama_kab",
            "skema": "p.skema",
            "tgl_sk": "p.tgl_sk",
            "jml_kk": "p.jml_kk::numeric",
            "id": "p.id",
        }
        order_col = sort_map.get(sort_by, "p.lembaga")
        direction = "DESC" if str(sort_dir).lower() == "desc" else "ASC"
        order_clause = f"ORDER BY {order_col} {direction} NULLS LAST, p.id ASC"

        with self.store.connection() as conn:
            with conn.cursor() as cur:
                # Hitung total data
                count_sql = f"SELECT count(*) as total FROM polygon_metadata p {where_clause}"
                cur.execute(count_sql, tuple(params))
                total_records = int((cur.fetchone() or {}).get("total") or 0)
                total_pages = (total_records + page_size - 1) // page_size if total_records > 0 else 0

                if total_records == 0 or offset >= total_records:
                    items = []
                else:
                    # Ambil baris berhalaman beserta relasi agregat ringan
                    fetch_sql = f"""
                        SELECT 
                            p.id, p.layer_key, p.feature_key, p.lembaga, p.no_sk, p.tgl_sk, p.skema,
                            p.nama_prov, p.nama_kab, p.nama_kec, p.nama_desa,
                            p.wilker_bps, p.ps_id,
                            COALESCE(p.luas_final::numeric, 0) as luas_final,
                            COALESCE(p.luas_hl::numeric, 0) as luas_hl,
                            COALESCE(p.luas_hp::numeric, 0) as luas_hp,
                            COALESCE(p.luas_hpt::numeric, 0) as luas_hpt,
                            COALESCE(p.luas_hpk::numeric, 0) as luas_hpk,
                            COALESCE(p.luas_hk::numeric, 0) as luas_hk,
                            COALESCE(p.jml_kk::numeric, 0) as jml_kk,
                            COALESCE((
                                SELECT count(DISTINCT r.hotspot_observation_id)
                                FROM hotspot_polygon_relation r
                                JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
                                WHERE r.polygon_metadata_id = p.id AND h.detected_at >= CURRENT_DATE - INTERVAL '30 days'
                            ), 0) as hotspot_count_30d,
                            (
                                SELECT max(h.detected_at)
                                FROM hotspot_polygon_relation r
                                JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
                                WHERE r.polygon_metadata_id = p.id AND h.detected_at >= CURRENT_DATE - INTERVAL '30 days'
                            ) as last_hotspot_at,
                            COALESCE((
                                SELECT sum(burned_area_ha)
                                FROM burned_area_summary b
                                WHERE b.polygon_metadata_id = p.id
                            ), 0) as burned_area_ha
                        FROM polygon_metadata p
                        {where_clause}
                        {order_clause}
                        LIMIT %s OFFSET %s;
                    """
                    page_params = tuple(params + [page_size, offset])
                    cur.execute(fetch_sql, page_params)
                    rows = cur.fetchall()

                    items = []
                    for r in rows:
                        last_hs = r.get("last_hotspot_at")
                        items.append({
                            "id": int(r["id"]),
                            "layer_key": r.get("layer_key"),
                            "feature_key": r.get("feature_key"),
                            "lembaga": r.get("lembaga") or "—",
                            "no_sk": r.get("no_sk") or "—",
                            "tgl_sk": str(r["tgl_sk"]) if r.get("tgl_sk") else None,
                            "skema": r.get("skema") or "—",
                            "nama_prov": r.get("nama_prov") or "—",
                            "nama_kab": r.get("nama_kab") or "—",
                            "nama_kec": r.get("nama_kec") or "—",
                            "nama_desa": r.get("nama_desa") or "—",
                            "wilker_bps": r.get("wilker_bps") or "—",
                            "ps_id": r.get("ps_id"),
                            "luas_final": float(r.get("luas_final") or 0.0),
                            "luas_hl": float(r.get("luas_hl") or 0.0),
                            "luas_hp": float(r.get("luas_hp") or 0.0),
                            "luas_hpt": float(r.get("luas_hpt") or 0.0),
                            "luas_hpk": float(r.get("luas_hpk") or 0.0),
                            "luas_hk": float(r.get("luas_hk") or 0.0),
                            "jml_kk": int(float(r.get("jml_kk") or 0)),
                            "hotspot_count_30d": int(r.get("hotspot_count_30d") or 0),
                            "last_hotspot_at": last_hs.isoformat() if hasattr(last_hs, "isoformat") else (str(last_hs) if last_hs else None),
                            "burned_area_ha": round(float(r.get("burned_area_ha") or 0.0), 2),
                        })

        return {
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_records": total_records,
                "total_pages": total_pages,
            },
            "items": items,
        }

    def export_kps_catalog_csv(
        self,
        *,
        search: str | None = None,
        wilker: str | None = None,
        province: str | None = None,
        regency: str | None = None,
        skema: str | None = None,
        has_hotspot_30d: bool | None = None,
        has_burned_area: bool | None = None,
        limit: int = 10000,
    ) -> str:
        """Ekspor data katalog KPS ke format CSV teks."""
        res = self.get_kps_catalog(
            page=1,
            page_size=limit,
            search=search,
            wilker=wilker,
            province=province,
            regency=regency,
            skema=skema,
            has_hotspot_30d=has_hotspot_30d,
            has_burned_area=has_burned_area,
            sort_by="lembaga",
            sort_dir="asc",
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "ID",
            "Nama Lembaga / KPS",
            "Nomor SK",
            "Tanggal SK",
            "Skema",
            "Provinsi",
            "Kabupaten",
            "Kecamatan",
            "Desa",
            "Balai PS",
            "Luas SK (Ha)",
            "HL (Ha)",
            "HP (Ha)",
            "HPT (Ha)",
            "HPK (Ha)",
            "HK (Ha)",
            "Jumlah KK",
            "Hotspot (30 Hari)",
            "Terakhir Hotspot",
            "Luas Terbakar (Ha)",
        ])

        for item in res.get("items", []):
            writer.writerow([
                item["id"],
                item["lembaga"],
                item["no_sk"],
                item["tgl_sk"] or "",
                item["skema"],
                item["nama_prov"],
                item["nama_kab"],
                item["nama_kec"],
                item["nama_desa"],
                item["wilker_bps"],
                item["luas_final"],
                item["luas_hl"],
                item["luas_hp"],
                item["luas_hpt"],
                item["luas_hpk"],
                item["luas_hk"],
                item["jml_kk"],
                item["hotspot_count_30d"],
                item["last_hotspot_at"] or "",
                item["burned_area_ha"],
            ])

        return output.getvalue()


@lru_cache
def get_kps_catalog_service() -> KpsCatalogService:
    return KpsCatalogService()
