"""Akses field polygon_metadata yang dipakai bersama oleh export XLSX & PDF.

polygon_metadata berasal langsung dari properti shapefile KLHK, sehingga nama
fieldnya tidak selalu seragam dan isinya bisa mengandung spasi/baris baru sisa
proses digitasi. Semua pembacaan dilakukan lewat modul ini supaya penanganannya
sama di seluruh laporan.
"""

import re


_WHITESPACE = re.compile(r"\s+")

PROVINSI_FALLBACK = "Tanpa Provinsi"
SKEMA_FALLBACK = "Tanpa Skema"


def polygon_field(hotspot: dict, *keys: str) -> str:
    """Ambil field pertama yang terisi dari polygon_metadata."""
    metadata = hotspot.get("polygon_metadata") or {}
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def sk_number(hotspot: dict) -> str:
    """Nomor SK penetapan izin perhutanan sosial.

    Sebagian nilai di sumber memuat baris baru dan spasi ganda (mis. daftar SK
    yang dipisah "s/d"), yang akan merusak tinggi baris tabel kalau ditulis apa
    adanya -- karena itu spasinya dinormalkan jadi satu spasi.

    Sebagian lain (14 polygon per Agustus 2026) menuliskan nomor yang sama dua
    kali dipisah baris baru, mis. "607/EKBANG/2016\\r\\n607/EKBANG/2016". Baris
    yang isinya persis sama dibuang supaya tidak terbaca sebagai dua SK berbeda;
    baris yang benar-benar berbeda tetap dipertahankan seluruhnya.
    """
    raw = polygon_field(hotspot, "NO_SK")
    if not raw:
        return ""

    segments: list[str] = []
    for line in raw.splitlines():
        cleaned = _WHITESPACE.sub(" ", line).strip()
        if cleaned and cleaned not in segments:
            segments.append(cleaned)

    return " ".join(segments)


def sk_date(hotspot: dict) -> str:
    return _WHITESPACE.sub(" ", polygon_field(hotspot, "TGL_SK")).strip()


def provinsi_name(hotspot: dict) -> str:
    """Provinsi titik panas.

    Hasil spatial join (`province_name`) didahulukan karena sudah dinormalkan;
    properti shapefile baru dipakai kalau kolom itu kosong.
    """
    direct = hotspot.get("province_name")
    if direct not in (None, ""):
        return str(direct)
    return polygon_field(hotspot, "NAMA_PROV", "NAMA_PROVINSI", "PROVINSI") or PROVINSI_FALLBACK


def skema_name(hotspot: dict) -> str:
    """Skema perhutanan sosial (PPHD, PPHKm, PPHTR, PKK, Hutan Adat, IPHPS, ...).

    Sebagian polygon di sumber belum mengisi SKEMA; titiknya tetap dihitung
    lewat label SKEMA_FALLBACK supaya total rekap per skema sama dengan total
    hotspot pada periode yang sama.
    """
    raw = polygon_field(hotspot, "SKEMA", "Skema", "skema")
    return _WHITESPACE.sub(" ", raw).strip() or SKEMA_FALLBACK
