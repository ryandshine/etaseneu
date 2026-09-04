"""Fitur Sentinel-1 GRD (C-band SAR) untuk klasifikasi tutupan lahan.

Kenapa SAR: optik S2 melihat "hijau berpohon" -- sawit dewasa, karet, dan
hutan alam punya NDVI/NBR yang mirip. Backscatter C-band membedakan struktur
kanopi: VH (cross-pol) naik dengan volume scattering tajuk tak beraturan
(hutan alam), sedangkan barisan sawit yang teratur + tanah terbuka di antaranya
memberi VV relatif tinggi dan rasio VH/VV lebih rendah. Selain itu SAR tembus
awan -> fitur tetap ada di tahun/daerah yang kemaraunya berawan terus.

Konvensi GEE `COPERNICUS/S1_GRD`: band VV/VH sudah dalam **dB** (log10).
Rasio VH/VV dalam skala dB = pengurangan `VH - VV`, BUKAN pembagian.

Semua fungsi menerima modul `ee` sebagai argumen (lihat `__init__.py`).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("land_cover.sar")

S1_COLLECTION = "COPERNICUS/S1_GRD"
SAR_FEATURE_NAMES: tuple[str, ...] = ("VV", "VH", "VH_VV_ratio")
# Radius speckle filter (meter). 15 m @ piksel 10 m ~= jendela 3x3 --
# "ringan": meredam salt-and-pepper tanpa meleburkan tepi kebun/hutan.
SPECKLE_RADIUS_M = 15
# Di bawah ini komposit median tahunan dianggap tidak bisa dipercaya (S1B mati
# Des 2021, S1C baru 2025 -> 2022-2024 revisit lebih jarang di sebagian
# Indonesia timur). Median dari 1-2 scene masih sangat berbintik.
S1_MIN_SCENES = 4
_DEFAULT_PASS = "DESCENDING"


def s1_base_collection(ee, roi, start: str, end: str):
    """Koleksi S1 GRD IW dual-pol (VV+VH) di `roi` & rentang tanggal, belum
    difilter orbit. Dipakai bersama oleh deteksi orbit & komposit tahunan
    supaya filternya identik."""
    return (
        ee.ImageCollection(S1_COLLECTION)
        .filterBounds(roi)
        .filterDate(start, end)
        .filter(ee.Filter.eq("instrumentMode", "IW"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VH"))
    )


def get_dominant_pass(ee, roi, start_date: str, end_date: str) -> str:
    """Orbit (ASCENDING/DESCENDING) dengan scene terbanyak di `roi` sepanjang
    seluruh rentang analisis.

    Satu orbit saja yang dipakai untuk SEMUA tahun: geometri pandang asc vs
    desc berbeda (efek lereng/bayangan radar), mencampurnya membuat fitur
    berubah antar-tahun bukan karena tutupan lahannya berubah. Dua `size()`
    dievaluasi dalam SATU `getInfo()` (hemat kuota GEE). Fallback DESCENDING
    kalau seimbang/kosong/gagal -- pemanggil yang memutuskan apakah SAR
    layak dipakai (lihat `get_s1_composite` -> `nobs`).
    """
    base = s1_base_collection(ee, roi, start_date, end_date)
    counts = ee.Dictionary({
        "asc": base.filter(ee.Filter.eq("orbitProperties_pass", "ASCENDING")).size(),
        "desc": base.filter(ee.Filter.eq("orbitProperties_pass", "DESCENDING")).size(),
    })
    try:
        info = counts.getInfo() or {}
        n_asc = int(info.get("asc") or 0)
        n_desc = int(info.get("desc") or 0)
    except Exception as exc:  # noqa: BLE001 -- GEE throttling/timeout
        logger.warning("SAR: gagal menghitung scene S1 per orbit (%s); pakai %s", exc, _DEFAULT_PASS)
        return _DEFAULT_PASS
    logger.info("SAR: scene S1 %s..%s asc=%d desc=%d", start_date, end_date, n_asc, n_desc)
    if n_asc > n_desc:
        return "ASCENDING"
    return _DEFAULT_PASS


def _despeckle(ee):
    """Speckle filter ringan per scene. Median spasial dikerjakan langsung pada
    dB: median invarian terhadap transformasi monoton (log), jadi hasilnya
    sama dengan median di skala linear -- tidak perlu konversi bolak-balik
    seperti untuk mean."""

    def _fn(img):
        filtered = img.select(["VV", "VH"]).focal_median(
            radius=SPECKLE_RADIUS_M, units="meters", kernelType="circle"
        )
        return filtered.copyProperties(img, ["system:time_start"])

    return _fn


def get_s1_composite(ee, roi, year: int, dominant_pass: str, *, start: str | None = None,
                     end: str | None = None):
    """Komposit median tahunan S1 untuk satu orbit.

    Mengembalikan `(image, size)`: citra 3 band `VV, VH, VH_VV_ratio` (dB) dan
    objek `ee.Number` jumlah scene (BELUM dievaluasi -- pemanggil yang
    menggabungkannya ke satu `getInfo()` bila perlu). `start`/`end` opsional
    supaya tahun berjalan bisa dipotong ke hari ini oleh pemanggil.
    """
    start = start or f"{year}-01-01"
    end = end or f"{year}-12-31"
    coll = (
        s1_base_collection(ee, roi, start, end)
        .filter(ee.Filter.eq("orbitProperties_pass", dominant_pass))
        .map(_despeckle(ee))
    )
    median = coll.median()
    vv = median.select("VV")
    vh = median.select("VH")
    ratio = vh.subtract(vv).rename("VH_VV_ratio")  # dB: rasio = selisih
    img = ee.Image.cat(vv, vh, ratio).rename(list(SAR_FEATURE_NAMES)).clip(roi)
    return img, coll.size()


def s1_scene_counts(ee, roi, years, dominant_pass: str, windows: dict[int, tuple[str, str]]) -> dict[int, int]:
    """Jumlah scene per tahun dalam SATU `getInfo()`. Dipakai untuk guard:
    tahun dengan scene < `S1_MIN_SCENES` -> SAR dinonaktifkan untuk seluruh
    poligon (fitur harus konsisten antar-tahun untuk satu model RF).
    Kegagalan jaringan/GEE -> dict kosong (pemanggil memperlakukan sebagai
    "tidak tersedia")."""
    sizes = {}
    for y in years:
        s, e = windows[y]
        _, n = get_s1_composite(ee, roi, y, dominant_pass, start=s, end=e)
        sizes[str(y)] = n
    try:
        info = ee.Dictionary(sizes).getInfo() or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("SAR: gagal menghitung scene S1 per tahun (%s)", exc)
        return {}
    return {int(k): int(v or 0) for k, v in info.items()}
