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
