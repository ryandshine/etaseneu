"""Penentuan label latih & klasifikasi aturan mandiri ETA SENEU (tanpa pihak ketiga).

Sistem tidak lagi bergantung pada model pihak ketiga (Google Dynamic World,
ESA WorldCover, Hansen GFC, Descals). Sampel latih dibangkitkan mandiri
dari 'Spectral Endmembers' (titik-titik arketipe spektral murni) yang
diekstraksi langsung dari citra Sentinel-2 L2A (multi-indeks + fenologi temporal ndvi_std
+ kelembaban kanopi NDMI) + Sentinel-1 SAR.

Representatif untuk ragam bentang alam Perhutanan Sosial (KPS) di Indonesia:
- Agroforestri rakyat (kopi, kakao, pala di bawah naungan pohon sengon/lamtoro/durian)
- Hutan alami berkanopi stabil & hutan musim (misal jati/meranggas saat kemarau)
- Kebun campuran rakyat (karet, kelapa, aren, buah-buahan, rempah)
- Pertanian semusim (sawah irigasi/tadah hujan, ladang palawija berfenologi tanam-panen)
- Lahan basah & rawa gambut / mangrove
- Semak belukar suksesi & savana/padang rumput

Taksonomi 5 kelas:
  hutan       (0)  Hutan Alami / Tutupan Pohon Kanopi Rapat Permanen
  pertanian   (1)  Pertanian, Agroforestri & Kebun Campuran Rakyat
  semak       (2)  Semak & Belukar (alang-alang, vegetasi rendah, savana)
  basah       (3)  Badan Air & Lahan Basah (sungai, danau, rawa gambut/basah, mangrove)
  terbuka     (4)  Lahan Terbuka (tanah terbuka, bekas tebangan/bakar, pasir/batuan)

Semua fungsi menerima modul `ee` sebagai argumen.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("land_cover.labels")


def spectral_seed_image(ee, feat_img, class_idx_of: dict[str, int], sample_region=None, use_sar: bool = False):
    """Citra label latih murni ('seed') berband `class_idx`.

    Hanya piksel dengan keyakinan fisik/spektral tinggi untuk salah satu dari 5
    kelas yang diberi nilai (0..4). Piksel ambigu/transisi di-mask, sehingga
    `stratifiedSample` hanya mengambil contoh-contoh murni (endmembers).

    Mendukung ambang batas adaptif (Local Percentiles p15/p40/p65/p85) jika
    `sample_region` diberikan, menyesuaikan otomatis dengan biogeografi lokal
    kawasan KPS di seluruh Indonesia (dari hutan hujan basah hingga savana).
    """
    ndvi = feat_img.select("ndvi")
    mndwi = feat_img.select("mndwi")
    bsi = feat_img.select("bsi")
    nbr = feat_img.select("nbr")
    b4 = feat_img.select("B4")
    b8 = feat_img.select("B8")
    b11 = feat_img.select("B11")

    try:
        ndmi = feat_img.select("ndmi")
    except (KeyError, AttributeError):
        ndmi = None

    try:
        ndvi_std = feat_img.select("ndvi_std")
    except (KeyError, AttributeError):
        ndvi_std = None

    try:
        ndvi_cv = feat_img.select("ndvi_cv")
    except (KeyError, AttributeError):
        ndvi_cv = None

    idx_hutan = class_idx_of["hutan"]
    idx_pertanian = class_idx_of["pertanian"]
    idx_semak = class_idx_of["semak"]
    idx_basah = class_idx_of["basah"]
    idx_terbuka = class_idx_of["terbuka"]

    # Ambang adaptif berbasis persentil spasial lokal kawasan
    th_hutan = 0.76
    th_semak_high = 0.70
    th_semak_low = 0.35
    th_terbuka = 0.28
    if sample_region is not None and hasattr(feat_img, "reduceRegion") and hasattr(ee, "Reducer"):
        try:
            pct = feat_img.select(["ndvi"]).reduceRegion(
                reducer=ee.Reducer.percentile([15, 40, 65, 85]),
                geometry=sample_region,
                scale=30,
                maxPixels=1e7,
                tileScale=4,
            )
            p85 = ee.Number(pct.get("ndvi_p85"))
            p65 = ee.Number(pct.get("ndvi_p65"))
            p40 = ee.Number(pct.get("ndvi_p40"))
            p15 = ee.Number(pct.get("ndvi_p15"))
            th_hutan = p85.max(0.68).min(0.84)
            th_semak_high = p65.max(0.50).min(0.72)
            th_semak_low = p40.max(0.28).min(0.42)
            th_terbuka = p15.max(0.18).min(0.32)
        except Exception:  # noqa: BLE001
            pass

    # 1. Badan Air & Lahan Basah (rawa gambut/mangrove/sungai):
    #    MNDWI tinggi, serapan kuat di NIR, atau NDMI tinggi pada genangan/substrat jenuh air
    c_basah = mndwi.gt(0.05).And(b8.lt(0.22)).And(ndvi.lt(0.40))
    if ndmi is not None:
        c_basah = c_basah.Or(mndwi.gt(-0.02).And(ndmi.gt(0.25)).And(b8.lt(0.25)))
    if use_sar:
        vh = feat_img.select("VH")
        vv = feat_img.select("VV")
        # Pantulan spekular air pada radar (backscatter sangat rendah)
        c_basah = c_basah.Or(mndwi.gt(0.0).And(vh.lt(-20.0)).And(vv.lt(-14.0)))

    # 2. Lahan Terbuka: BSI positif, NDVI sangat rendah, bukan air, pantulan merah nyata, NDMI negatif/kering
    c_terbuka = ndvi.lt(th_terbuka).And(bsi.gt(0.0)).And(mndwi.lt(-0.05)).And(b4.gt(0.06))
    if ndmi is not None:
        c_terbuka = c_terbuka.And(ndmi.lt(0.0))

    # 3. Hutan Alami / Kanopi Rapat Permanen:
    #    Kehijauan tinggi (adaptif terhadap tutupan lokal), NBR tinggi, kanopi tebal & lembab, fenologi stabil
    c_hutan = ndvi.gte(th_hutan).And(nbr.gte(0.48)).And(b8.gte(0.24)).And(mndwi.lt(-0.15))
    if ndmi is not None:
        c_hutan = c_hutan.And(ndmi.gte(0.10))
    if ndvi_std is not None:
        # Kanopi pohon hutan mantap relatif stabil sepanjang tahun (stdDev NDVI rendah)
        c_hutan = c_hutan.And(ndvi_std.lt(0.13))
    if ndvi_cv is not None:
        c_hutan = c_hutan.And(ndvi_cv.lt(0.15))
    if use_sar:
        vh = feat_img.select("VH")
        # Hamburan volume tajuk pohon tidak beraturan (VH tinggi)
        c_hutan = c_hutan.And(vh.gte(-14.0))

    # 4. Semak / Belukar & Savana: Vegetasi sedang-rendah, tanah tertutup, bukan pohon tinggi
    #    Rentang adaptif lokal p40..p65, kadar air & biomassa kayu rendah, fenologi stabil
    c_semak = ndvi.gte(th_semak_low).And(ndvi.lt(th_semak_high)).And(bsi.lte(0.04)).And(mndwi.lt(-0.05))
    if ndmi is not None:
        c_semak = c_semak.And(ndmi.lt(0.14))
    if ndvi_std is not None:
        c_semak = c_semak.And(ndvi_std.lt(0.12))
    if ndvi_cv is not None:
        c_semak = c_semak.And(ndvi_cv.lt(0.18))
    if use_sar:
        vh = feat_img.select("VH")
        c_semak = c_semak.And(vh.lt(-14.8))

    # 5. Pertanian, Agroforestri & Kebun Rakyat:
    #    a) Pertanian/ladang semusim: variabilitas fenologi tanam-panen nyata (ndvi_std >= 0.12 atau ndvi_cv >= 0.20)
    #    b) Pertanian/ladang lahan olahan kemarau: reflektansi tanah garapan nyata (B11 >= 0.13, bsi >= -0.04)
    #    c) Agroforestri & kebun campuran berkanopi rapat (kopi, kakao, karet, buah):
    #       NDVI >= 0.70 dengan pantulan SWIR lebih nyata (B11 >= 0.125) dan NBR < 0.48
    #    d) Kebun pohon dengan biomassa tajuk tinggi pada radar SAR (VH >= -14.5 dB)
    c_pertanian_tillage = ndvi.gte(0.45).And(ndvi.lt(0.72)).And(b11.gte(0.13)).And(bsi.gte(-0.04)).And(mndwi.lt(-0.05))
    c_pertanian_agro = ndvi.gte(0.70).And(b11.gte(0.125)).And(nbr.lt(0.48))
    if ndmi is not None:
        c_pertanian_agro = c_pertanian_agro.And(ndmi.gte(0.10))
    c_pertanian = c_pertanian_tillage.Or(c_pertanian_agro)
    if ndvi_std is not None:
        c_pertanian_seasonal = ndvi.gte(0.42).And(ndvi_std.gte(0.12)).And(mndwi.lt(-0.05))
        c_pertanian = c_pertanian.Or(c_pertanian_seasonal)
    if ndvi_cv is not None:
        c_pertanian_cv = ndvi.gte(0.38).And(ndvi_cv.gte(0.20)).And(mndwi.lt(-0.05))
        c_pertanian = c_pertanian.Or(c_pertanian_cv)
    if use_sar:
        ratio = feat_img.select("VH_VV_ratio")
        vh = feat_img.select("VH")
        c_pertanian = c_pertanian.Or(ndvi.gte(0.62).And(vh.gte(-14.5)).And(ratio.lt(-6.2)))

    # Gabungkan seed berurutan pada citra tak termask, lalu mask hanya piksel valid
    valid_seed_mask = c_terbuka.Or(c_semak).Or(c_pertanian).Or(c_hutan).Or(c_basah)
    seed = (
        ee.Image.constant(idx_terbuka)
        .where(c_semak, idx_semak)
        .where(c_pertanian, idx_pertanian)
        .where(c_hutan, idx_hutan)
        .where(c_basah, idx_basah)
        .updateMask(valid_seed_mask)
        .rename("class_idx")
    )
    return seed


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

    try:
        ndmi = feat_img.select("ndmi")
    except (KeyError, AttributeError):
        ndmi = None

    try:
        ndvi_std = feat_img.select("ndvi_std")
    except (KeyError, AttributeError):
        ndvi_std = None

    try:
        ndvi_cv = feat_img.select("ndvi_cv")
    except (KeyError, AttributeError):
        ndvi_cv = None

    idx_hutan = class_idx_of["hutan"]
    idx_pertanian = class_idx_of["pertanian"]
    idx_semak = class_idx_of["semak"]
    idx_basah = class_idx_of["basah"]
    idx_terbuka = class_idx_of["terbuka"]

    # Default baseline: semak (vegetasi menengah)
    classified = ee.Image.constant(idx_semak)

    # 1. Lahan terbuka: NDVI rendah, BSI tinggi, bukan air
    is_terbuka = ndvi.lt(0.30).And(bsi.gt(0.0)).And(mndwi.lt(0.0))
    if ndmi is not None:
        is_terbuka = is_terbuka.And(ndmi.lt(0.02))
    classified = classified.where(is_terbuka, idx_terbuka)

    # 2. Pertanian, agroforestri & kebun rakyat:
    #    Hanya jika memiliki penanda pertanian nyata (fenologi dinamis, tanah garapan kemarau,
    #    atau profil spektral agroforestri), BUKAN sekadar NDVI vegetasi hijau.
    is_pertanian_tillage = ndvi.gte(0.45).And(ndvi.lt(0.72)).And(b11.gte(0.13)).And(bsi.gte(-0.03)).And(mndwi.lt(-0.05))
    is_pertanian_agro = ndvi.gte(0.70).And(b11.gte(0.125)).And(nbr.lt(0.50))
    if ndmi is not None:
        is_pertanian_agro = is_pertanian_agro.And(ndmi.gte(0.08))
    is_pertanian = is_pertanian_tillage.Or(is_pertanian_agro)
    if ndvi_std is not None:
        is_pertanian = is_pertanian.Or(ndvi.gte(0.42).And(ndvi_std.gte(0.12)).And(mndwi.lt(-0.05)))
    if ndvi_cv is not None:
        is_pertanian = is_pertanian.Or(ndvi.gte(0.38).And(ndvi_cv.gte(0.20)).And(mndwi.lt(-0.05)))
    if use_sar:
        vh = feat_img.select("VH")
        is_pertanian = is_pertanian.Or(ndvi.gte(0.62).And(vh.gte(-14.5)).And(nbr.lt(0.50)))
    classified = classified.where(is_pertanian, idx_pertanian)

    # 3. Hutan: kanopi rapat tebal & stabil
    is_hutan = ndvi.gte(0.74).And(nbr.gte(0.48)).And(mndwi.lt(-0.10))
    if ndvi_std is not None:
        is_hutan = is_hutan.And(ndvi_std.lt(0.14))
    if ndmi is not None:
        is_hutan = is_hutan.And(ndmi.gte(0.08))
    if use_sar:
        vh = feat_img.select("VH")
        is_hutan = is_hutan.And(vh.gte(-14.5))
    classified = classified.where(is_hutan, idx_hutan)

    # 4. Basah / Air: MNDWI > 0 atau MNDWI > -0.05 dengan serapan NIR kuat, atau lahan rawa jenuh
    is_basah = mndwi.gt(0.0).Or(mndwi.gt(-0.05).And(b8.lt(0.20)).And(ndvi.lt(0.38)))
    if ndmi is not None:
        is_basah = is_basah.Or(mndwi.gt(-0.02).And(ndmi.gt(0.28)).And(b8.lt(0.22)))
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
