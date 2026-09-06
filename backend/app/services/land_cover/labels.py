"""Penentuan label latih & klasifikasi aturan mandiri ETA SENEU (tanpa pihak ketiga).

Sistem tidak lagi bergantung pada model pihak ketiga (Google Dynamic World,
ESA WorldCover, Hansen GFC, Descals). Sampel latih dibangkitkan mandiri
dari 'Spectral Endmembers' (titik-titik arketipe spektral murni) yang
diekstraksi langsung dari citra Sentinel-2 L2A + Sentinel-1 SAR.

Taksonomi 5 kelas:
  hutan       (0)  Hutan Alami / Tutupan Pohon Kanopi Rapat
  pertanian   (1)  Pertanian & Perkebunan (kebun sawit, karet, sawah/ladang)
  semak       (2)  Semak & Belukar (alang-alang, vegetasi rendah)
  basah       (3)  Badan Air & Lahan Basah (sungai, danau, rawa basah)
  terbuka     (4)  Lahan Terbuka (tanah terbuka, bekas tebangan/bakar, pasir/batuan)

Semua fungsi menerima modul `ee` sebagai argumen.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("land_cover.labels")


def spectral_seed_image(ee, feat_img, class_idx_of: dict[str, int], use_sar: bool = False):
    """Citra label latih murni ('seed') berband `class_idx`.

    Hanya piksel dengan keyakinan fisik/spektral tinggi untuk salah satu dari 5
    kelas yang diberi nilai (0..4). Piksel ambigu/transisi di-mask, sehingga
    `stratifiedSample` hanya mengambil contoh-contoh murni (endmembers).
    """
    ndvi = feat_img.select("ndvi")
    mndwi = feat_img.select("mndwi")
    bsi = feat_img.select("bsi")
    nbr = feat_img.select("nbr")
    b4 = feat_img.select("B4")
    b8 = feat_img.select("B8")
    b11 = feat_img.select("B11")

    idx_hutan = class_idx_of["hutan"]
    idx_pertanian = class_idx_of["pertanian"]
    idx_semak = class_idx_of["semak"]
    idx_basah = class_idx_of["basah"]
    idx_terbuka = class_idx_of["terbuka"]

    # 1. Badan Air & Lahan Basah: MNDWI tinggi, serapan kuat di NIR, vegetasi rendah
    c_basah = mndwi.gt(0.05).And(b8.lt(0.22)).And(ndvi.lt(0.40))
    if use_sar:
        vh = feat_img.select("VH")
        vv = feat_img.select("VV")
        # Pantulan spekular air pada radar (backscatter sangat rendah)
        c_basah = c_basah.Or(mndwi.gt(0.0).And(vh.lt(-20.0)).And(vv.lt(-14.0)))

    # 2. Lahan Terbuka: BSI positif, NDVI sangat rendah, bukan air, pantulan merah nyata
    c_terbuka = ndvi.lt(0.28).And(bsi.gt(0.0)).And(mndwi.lt(-0.05)).And(b4.gt(0.06))

    # 3. Hutan Alami / Kanopi Rapat: Kehijauan tinggi, NBR tinggi, kanopi tebal
    c_hutan = ndvi.gte(0.76).And(nbr.gte(0.48)).And(b8.gte(0.24)).And(mndwi.lt(-0.15))
    if use_sar:
        vh = feat_img.select("VH")
        # Hamburan volume tajuk pohon tidak beraturan (VH tinggi)
        c_hutan = c_hutan.And(vh.gte(-14.0))

    # 4. Semak / Belukar: Vegetasi sedang-rendah, tanah tertutup, bukan kanopi pohon
    c_semak = ndvi.gte(0.32).And(ndvi.lt(0.55)).And(bsi.lte(0.04)).And(mndwi.lt(-0.05))
    if use_sar:
        vh = feat_img.select("VH")
        c_semak = c_semak.And(vh.lt(-15.0))

    # 5. Pertanian & Perkebunan:
    #    a) Pertanian/ladang: NDVI 0.55 s/d 0.76
    #    b) Perkebunan berkanopi rapat (sawit/karet): NDVI >= 0.76 tapi SWIR tinggi
    c_pertanian_crop = ndvi.gte(0.55).And(ndvi.lt(0.76)).And(mndwi.lt(-0.05))
    c_pertanian_plantation = ndvi.gte(0.76).And(b11.gte(0.14)).And(nbr.lt(0.48))
    c_pertanian = c_pertanian_crop.Or(c_pertanian_plantation)
    if use_sar:
        ratio = feat_img.select("VH_VV_ratio")
        vh = feat_img.select("VH")
        c_pertanian = c_pertanian.Or(ndvi.gte(0.65).And(ratio.lt(-6.5)).And(vh.lt(-14.0)))

    # Gabungkan seed berurutan
    seed = (
        ee.Image.constant(idx_terbuka).updateMask(c_terbuka)
        .where(c_semak, idx_semak)
        .where(c_pertanian, idx_pertanian)
        .where(c_hutan, idx_hutan)
        .where(c_basah, idx_basah)
    )
    valid_seed_mask = c_terbuka.Or(c_semak).Or(c_pertanian).Or(c_hutan).Or(c_basah)
    return seed.updateMask(valid_seed_mask).rename("class_idx")


def rule_based_classify(ee, feat_img, class_idx_of: dict[str, int], use_sar: bool = False):
    """Pengklasifikasi aturan spektral deterministik (Decision Tree).

    Digunakan untuk mengisi sisa celah awan (gap-fill) atau sebagai fallback
    jika Random Forest tidak dapat dilatih (poligon sangat homogen).
    """
    ndvi = feat_img.select("ndvi")
    mndwi = feat_img.select("mndwi")
    bsi = feat_img.select("bsi")
    nbr = feat_img.select("nbr")
    b8 = feat_img.select("B8")
    b11 = feat_img.select("B11")

    idx_hutan = class_idx_of["hutan"]
    idx_pertanian = class_idx_of["pertanian"]
    idx_semak = class_idx_of["semak"]
    idx_basah = class_idx_of["basah"]
    idx_terbuka = class_idx_of["terbuka"]

    # Default baseline: semak (vegetasi menengah)
    classified = ee.Image.constant(idx_semak)

    # Lahan terbuka: NDVI rendah, BSI tinggi
    is_terbuka = ndvi.lt(0.30).And(bsi.gt(0.0)).And(mndwi.lt(0.0))
    classified = classified.where(is_terbuka, idx_terbuka)

    # Pertanian / perkebunan:
    is_pertanian = (
        (ndvi.gte(0.52).And(ndvi.lt(0.74)))
        .Or(ndvi.gte(0.74).And(b11.gte(0.14)).And(nbr.lt(0.50)))
    )
    classified = classified.where(is_pertanian, idx_pertanian)

    # Hutan: kanopi rapat tebal
    is_hutan = ndvi.gte(0.74).And(nbr.gte(0.48)).And(mndwi.lt(-0.10))
    if use_sar:
        vh = feat_img.select("VH")
        is_hutan = is_hutan.And(vh.gte(-14.5))
    classified = classified.where(is_hutan, idx_hutan)

    # Basah / Air: MNDWI > 0 atau MNDWI > -0.05 dengan serapan NIR kuat
    is_basah = mndwi.gt(0.0).Or(mndwi.gt(-0.05).And(b8.lt(0.20)).And(ndvi.lt(0.38)))
    classified = classified.where(is_basah, idx_basah)

    return classified.rename("class_idx")


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
            "LABELS: kelas dengan sampel latih < %d: %s",
            minimum, ", ".join(f"{k}={samples_per_class.get(k, 0)}" for k in out),
        )
    return out
