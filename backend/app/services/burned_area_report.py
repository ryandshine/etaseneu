"""Data luas bekas terbakar yang siap dipakai laporan (Excel & PDF).

Dipisah dari `burned_area_service.py` (yang urusannya menghitung dari Earth
Engine) supaya lapisan laporan cuma membaca hasil yang sudah tersimpan --
membuat PDF/Excel tidak pernah memicu panggilan ke Earth Engine.

Filternya (provinsi/skema/lembaga) sengaja diterapkan di Python, bukan SQL:
sumbernya `read_burned_area_map_overlay()` yang sudah menggabung geometry
bulanan per KPS dan sudah teruji, dan jumlah barisnya kecil (satu baris per
KPS terdampak, puluhan, bukan ribuan) sehingga tidak sepadan menduplikasi
logika union-nya cuma untuk memindahkan filter ke SQL.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


logger = logging.getLogger("burned_area.report")


def load_burned_area_report(
    *,
    province: str | None = None,
    skema: str | None = None,
    agency: str | None = None,
    year: int | None = None,
    postgres_store: PostgresStore | None = None,
) -> dict[str, object]:
    """Rekap luas terbakar untuk lampiran laporan.

    Gagal baca database tidak dianggap fatal: laporan hotspot tetap terbit
    tanpa bagian luas terbakar (dict kosong), karena burned area adalah
    lampiran pelengkap -- bukan isi utama laporan.
    """
    store = postgres_store or PostgresStore(get_settings().database_url)

    empty: dict[str, object] = {"rows": [], "by_skema": [], "total_ha": 0.0, "kps_count": 0}
    if not store.enabled:
        return empty

    try:
        rows = store.read_burned_area_map_overlay(year=year)
    except Exception as exc:
        logger.warning("BURNED_AREA_REPORT: gagal membaca rekap luas terbakar — %s", exc)
        return empty

    def _matches(row: dict[str, object]) -> bool:
        if province and (row.get("nama_prov") or "") != province:
            return False
        if skema and (row.get("skema") or "") != skema:
            return False
        if agency and (row.get("lembaga") or "") != agency:
            return False
        return True

    filtered = [row for row in rows if _matches(row)]

    by_skema: dict[str, dict[str, float]] = {}
    for row in filtered:
        key = str(row.get("skema") or "Lainnya")
        bucket = by_skema.setdefault(key, {"total_ha": 0.0, "kps_count": 0})
        bucket["total_ha"] += float(row.get("burned_ha") or 0)
        bucket["kps_count"] += 1

    return {
        "rows": [
            {
                "lembaga": row.get("lembaga") or "-",
                "skema": row.get("skema") or "-",
                "nama_prov": row.get("nama_prov") or "-",
                "wilker_bps": row.get("wilker_bps") or "-",
                "burned_area_ha": float(row.get("burned_ha") or 0),
                "burned_months": int(row.get("burned_months") or 0),
                "latest_period": _period_label(row.get("latest_period")),
                "is_estimated": bool(row.get("is_estimated")),
            }
            for row in filtered
        ],
        "by_skema": sorted(
            (
                {"skema": key, "total_ha": value["total_ha"], "kps_count": int(value["kps_count"])}
                for key, value in by_skema.items()
            ),
            key=lambda item: item["total_ha"],
            reverse=True,
        ),
        "total_ha": sum(float(row.get("burned_ha") or 0) for row in filtered),
        "kps_count": len(filtered),
    }


def _period_label(raw: object) -> str:
    """`202604` (integer, supaya bisa di-MAX() di SQL) -> `2026-04`."""
    if not raw:
        return "-"
    value = int(raw)
    return f"{value // 100:04d}-{value % 100:02d}"
