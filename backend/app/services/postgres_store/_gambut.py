"""Ringkasan irisan gambut FEG (Fungsi Ekosistem Gambut 1:250.000) per poligon
KPS/Hutan Adat -- baca dari `polygon_gambut_overlay`, tabel turunan STATIS yang
dimuat manual ke DB (lihat catatan "Layer Gambut FEG" di CLAUDE.md). Tabel itu
sendiri dan `ref_gambut_feg` TIDAK dibuat lewat `_ensure_*` di sini -- keduanya
sudah ada di database produksi, mixin ini cuma membaca.

Tidak ada lapisan peta untuk ini (keputusan user) -- cuma atribusi tekstual di
kartu Detail KPS, jadi query-nya sengaja ringan: satu SELECT per poligon,
dipanggil dari PolygonService.get_polygon_detail() saat kartu itu dibuka.
"""

from __future__ import annotations

from typing import Any


class _GambutMixin:
    def read_gambut_mask_geometry(
        self,
        bbox: tuple[float, float, float, float],
        *,
        simplify_tolerance: float = 0.001,
    ) -> dict[str, Any] | None:
        """Geometri gabungan (union) seluruh poligon `ref_gambut_feg` yang
        beririsan bbox, disederhanakan -- dipakai `burned_area_s2_service.py`
        untuk membangun mask gambut biner di GEE (bukan tampilan/peta).

        Union dulu baru simplify: union sendiri sudah memangkas ~2.300 poligon
        Kalbar (±625rb titik) jadi satu geometri gabungan (±215rb titik),
        simplify di atasnya turun lagi ke puluhan ribu titik -- payload yang
        cukup ringan buat dikirim sebagai satu ee.Feature inline. Toleransi
        default 0,001 derajat (~110 m) jauh lebih kasar dari resolusi piksel
        Sentinel-2 (20 m) -- cukup untuk keputusan "piksel/cluster ini gambut
        atau tidak", TIDAK untuk presisi batas.

        None kalau tidak ada gambut sama sekali di bbox itu (union kosong).
        """
        minx, miny, maxx, maxy = bbox
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ST_AsGeoJSON(
                        ST_SimplifyPreserveTopology(ST_Union(geom), %s)
                    )::json AS geometry
                    FROM ref_gambut_feg
                    WHERE ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))
                    """,
                    (simplify_tolerance, minx, miny, maxx, maxy),
                )
                row = cur.fetchone()

        if row is None or row.get("geometry") is None:
            return None
        return row["geometry"]


    def read_gambut_summary(self, polygon_metadata_id: int) -> dict[str, Any] | None:
        """None kalau poligon ini tidak beririsan gambut sama sekali (mayoritas
        KPS -- cuma 797 dari ~8.600 poligon aktif nasional yang bergambut)."""
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT kode_khg, nama_khg, fungsi, kubah_gmbt, luas_ha
                    FROM polygon_gambut_overlay
                    WHERE polygon_metadata_id = %s AND luas_ha > 0
                    ORDER BY luas_ha DESC
                    """,
                    (polygon_metadata_id,),
                )
                rows = cur.fetchall()

        if not rows:
            return None

        total_ha = sum(float(r["luas_ha"]) for r in rows)
        by_fungsi: dict[str, float] = {}
        for r in rows:
            fungsi = r["fungsi"] or "Tidak diketahui"
            by_fungsi[fungsi] = by_fungsi.get(fungsi, 0.0) + float(r["luas_ha"])

        return {
            "total_ha": round(total_ha, 2),
            "by_fungsi": {k: round(v, 2) for k, v in by_fungsi.items()},
            "khg": [
                {
                    "kode_khg": r["kode_khg"],
                    "nama_khg": r["nama_khg"],
                    "fungsi": r["fungsi"],
                    "kubah_gmbt": r["kubah_gmbt"],
                    "luas_ha": round(float(r["luas_ha"]), 2),
                }
                for r in rows
            ],
        }
