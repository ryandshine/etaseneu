"""Konsensus label latih: Dynamic World x ESA WorldCover (x Hansen di service).

Masalah yang diselesaikan: Random Forest cuma sebaik gurunya. Dynamic World
(DW) per-scene sering "ragu" secara sistematis di Indonesia -- semak tinggi
jadi trees, sawah kering jadi bare, kebun campur jadi crops/trees bergantian.
Ambang keyakinan DW (>= 0,6) menyaring piksel ragu, tapi TIDAK menangkap
kesalahan yang DW yakini. Sumber kedua yang independen dibutuhkan: ESA
WorldCover v200 (referensi 2021, 10 m, model & data latih berbeda dari DW).
Sampel latih hanya dipakai kalau kedua sumber SETUJU -> label lebih bersih,
dengan harga jumlah sampel berkurang (diterima: akurasi > kuota).

Jebakan waktu: WorldCover cuma ada untuk 2021 (v200; v100 = 2020). Untuk tahun
> 2021, piksel yang BENAR-BENAR berubah (hutan -> terbuka) pasti "tidak setuju"
dengan peta 2021 -- kalau semua dibuang, kelas yang cuma muncul di area yang
berubah (lahan terbuka bekas kebakaran) kehilangan seluruh sampelnya dan RF
tidak pernah bisa memprediksinya. Aturannya:

    setuju(t) = WC == DW(t)                       untuk piksel yang DW anggap
                                                  TIDAK berubah sejak 2021
                                                  (DW(t) == DW(2021));
              = tidak dicek (lolos)               kalau DW(t) != DW(2021)
                                                  (perubahan nyata versi DW --
                                                  WC 2021 tak bisa menilai).

Jadi WC dipakai menangkap kesalahan SISTEMATIS DW (kelas yang sama-sama salah
di 2021 dan t), bukan menghukum perubahan tutupan yang sungguhan.

Semua fungsi menerima modul `ee` sebagai argumen (lihat `__init__.py`).
"""

from __future__ import annotations

import logging

logger = logging.getLogger("land_cover.labels")

WORLDCOVER_IMAGE = "ESA/WorldCover/v200/2021"
WORLDCOVER_YEAR = 2021
WORLDCOVER_LABEL = "ESA WorldCover v200 (2021)"

# Kode WorldCover -> kunci kelas IPCC (sama taksonomi 6 kelas dengan
# service). Kode tanpa padanan (70 salju, 100 lumut) di-mask: sampel di
# sana dibuang apa pun kata DW.
#   10 tree cover -> hutan        20 shrubland -> semak
#   30 grassland -> semak         40 cropland -> pertanian
#   50 built-up -> permukiman     60 bare/sparse -> terbuka
#   80 permanent water -> basah   90 herbaceous wetland -> basah
#   95 mangroves -> hutan (forested wetland, disamakan Forest IPCC seperti DW)
WORLDCOVER_MAP: dict[int, str] = {
    10: "hutan", 20: "semak", 30: "semak", 40: "pertanian",
    50: "permukiman", 60: "terbuka", 80: "basah", 90: "basah", 95: "hutan",
}
_WC_TREE_CODES = (10, 95)


def worldcover_class_image(ee, class_idx_of: dict[str, int]):
    """Citra `class_idx` (skema ETA SENEU) dari peta WorldCover, ter-mask di
    kode yang tak punya padanan. `class_idx_of` = {kunci kelas -> indeks}
    milik service supaya modul ini tidak menduplikasi CLASS_KEYS."""
    wc = ee.Image(WORLDCOVER_IMAGE).select("Map")
    from_list = list(WORLDCOVER_MAP)
    to_list = [class_idx_of[WORLDCOVER_MAP[k]] for k in from_list]
    return wc.remap(from_list, to_list).rename("wc_class_idx")


def worldcover_is_tree(ee):
    """Mask 1 = WorldCover tree cover / mangrove. Dipakai untuk sawit: WC
    tidak membedakan kebun sawit dari tutupan pohon lain (menyebut keduanya
    "tree cover"), jadi piksel sawit yang dipaksa ke kelas "pertanian" oleh
    service perlu jalur toleransi tersendiri (lihat `consensus_mask`)."""
    wc = ee.Image(WORLDCOVER_IMAGE).select("Map")
    mask = wc.eq(_WC_TREE_CODES[0])
    for code in _WC_TREE_CODES[1:]:
        mask = mask.Or(wc.eq(code))
    return mask


def consensus_mask(ee, dw_class, dw_class_ref, wc_class, tolerated=None):
    """Mask 1 = sampel boleh dipakai.

    dw_class     : class_idx DW tahun target (sudah termasuk relabel sawit)
    dw_class_ref : class_idx DW tahun referensi WorldCover (2021)
    wc_class     : hasil `worldcover_class_image`
    tolerated    : mask opsional -- piksel yang dianggap "setuju" apa pun
                   kata WC (mis. sawit x `worldcover_is_tree`, lihat
                   pemanggil di service). `None` = tidak ada toleransi
                   tambahan.

    Piksel yang DW anggap berubah sejak 2021 lolos tanpa dicek (lihat
    docstring modul). Untuk yang stabil: WC harus sama, kecuali yang masuk
    `tolerated`. Piksel di kode WC tanpa padanan (salju dsb.) ter-mask di
    `wc_class` -> `eq` menghasilkan mask kosong -> dibuang.
    """
    stable = dw_class.eq(dw_class_ref)
    agree = wc_class.eq(dw_class)
    if tolerated is not None:
        agree = agree.Or(tolerated)
    # unmask(0): piksel WC tanpa padanan -> agree=0 (bukan mask kosong yang
    # oleh Or() dianggap "tidak ada data" dan bisa lolos lewat cabang lain).
    agree = agree.unmask(0)
    changed = stable.Not().unmask(0)
    return agree.Or(changed)


def sparse_classes(samples_per_class: dict[str, int], class_keys, minimum: int) -> list[str]:
    """Kelas yang sampel latihnya (lintas tahun) di bawah `minimum` -- RF
    hampir tidak pernah memprediksinya. Cuma untuk peringatan log + meta;
    dipanggil sesudah sampel dimaterialisasi, jadi tidak ada biaya GEE."""
    out = []
    for key in class_keys:
        n = int(samples_per_class.get(key, 0))
        if 0 < n < minimum:
            out.append(key)
    if out:
        logger.warning(
            "LABELS: kelas dengan sampel latih < %d setelah konsensus: %s",
            minimum, ", ".join(f"{k}={samples_per_class.get(k, 0)}" for k in out),
        )
    return out
