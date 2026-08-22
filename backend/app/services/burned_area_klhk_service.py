"""Luas kebakaran (burned area) dari rekap resmi KLHK "Areal Kebakaran Hutan
dan Lahan", menggantikan pendekatan MODIS/VIIRS via Google Earth Engine
(`burned_area_service.py`, sudah tidak dipakai).

KLHK menerbitkan file GeoJSON berisi poligon area terbakar per bulan dengan
klasifikasi akurasi:
  - H (high): terpantau di citra, ada hotspot, ada konfirmasi lapangan/apinya
  - M (medium): terpantau di citra dan ada hotspot
  - L (low): cuma terpantau di citra
Cuma H dan M yang masuk rekapitulasi resmi -- L dan yang datanya belum
lengkap butuh konfirmasi lapangan dulu (aturan KLHK sendiri, bukan pilihan
sistem ini).

File ini ditaruh admin di server (mis. lewat SFTP) lalu diproses lewat
endpoint admin -- bukan dipanggil terjadwal seperti GEE dulu, karena KLHK
menerbitkannya tidak dengan jadwal tetap.
"""

from __future__ import annotations

import logging
from pathlib import Path

import ijson

from app.services.postgres_store import PostgresStore


logger = logging.getLogger("burned_area.klhk")

KLHK_SOURCE_LABEL = "KLHK - Areal Kebakaran Hutan dan Lahan"

_ACCEPTED_AKURASI = ("H", "M")

_MONTH_BY_NAME = {
    "JANUARI": 1,
    "FEBRUARI": 2,
    "MARET": 3,
    "APRIL": 4,
    "MEI": 5,
    "JUNI": 6,
    "JULI": 7,
    "AGUSTUS": 8,
    "SEPTEMBER": 9,
    "OKTOBER": 10,
    "NOVEMBER": 11,
    "DESEMBER": 12,
}


class BurnedAreaKlhkError(Exception):
    """File KLHK tidak valid atau gagal diproses."""


def _month_from_periode(periode: str | None) -> int | None:
    if not periode:
        return None
    return _MONTH_BY_NAME.get(periode.strip().upper())


def _year_from_ket(ket: str | None, fallback_year: int) -> int:
    """KET berisi tanggal akhir periode, mis. "20260531" -> 2026. Kalau
    kosong/tidak terbaca, pakai fallback_year (dari nama file)."""
    if ket and len(ket) >= 4 and ket[:4].isdigit():
        return int(ket[:4])
    return fallback_year


def _guess_year_from_filename(file_path: str) -> int:
    import re

    match = re.search(r"20\d{2}", Path(file_path).stem)
    return int(match.group(0)) if match else 2026


def _iter_hm_features(file_path: str, fallback_year: int):
    """Stream-parse file KLHK, cuma kembalikan fitur AKURASI H/M yang punya
    geometry dan PERIODE yang bisa dipetakan ke bulan."""
    skipped = 0
    with open(file_path, "rb") as f:
        for feature in ijson.items(f, "features.item"):
            props = feature.get("properties") or {}
            if props.get("AKURASI") not in _ACCEPTED_AKURASI:
                continue
            geometry = feature.get("geometry")
            if not geometry:
                skipped += 1
                continue
            month = _month_from_periode(props.get("PERIODE"))
            if month is None:
                skipped += 1
                continue
            year = _year_from_ket(props.get("KET"), fallback_year)
            yield year, month, geometry
    if skipped:
        logger.warning("BURNED_AREA_KLHK: %d fitur dilewati (tanpa geometry/PERIODE tidak dikenali)", skipped)


def refresh_burned_area_from_klhk_file(
    file_path: str,
    *,
    postgres_store: PostgresStore | None = None,
    clear_existing: bool = False,
) -> dict[str, object]:
    """Proses satu file resmi KLHK: overlay ke KPS aktif, simpan ke
    burned_area_summary.

    `clear_existing=True` cuma untuk migrasi sekali (pindah dari GEE) --
    pemanggilan berikutnya harus False supaya upsert per (polygon, year,
    month) yang idempotent tetap berfungsi, bukan hapus-lalu-isi ulang
    setiap kali file baru masuk.
    """
    path = Path(file_path)
    if not path.is_file():
        raise BurnedAreaKlhkError(f"File tidak ditemukan: {file_path}")

    from app.core.config import get_settings

    store = postgres_store or PostgresStore(get_settings().database_url)
    if not store.enabled:
        raise BurnedAreaKlhkError("Database tidak aktif.")

    if clear_existing:
        cleared = store.clear_burned_area_summary()
        logger.info("BURNED_AREA_KLHK: %d baris lama dibersihkan sebelum migrasi.", cleared)

    fallback_year = _guess_year_from_filename(file_path)
    features = _iter_hm_features(file_path, fallback_year)
    computed = store.refresh_burned_area_from_klhk(features, source=KLHK_SOURCE_LABEL)

    return {
        "file": path.name,
        "computed": computed,
    }
