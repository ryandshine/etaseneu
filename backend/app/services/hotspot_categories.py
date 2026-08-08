"""Ambang batas kategori confidence & FRP yang dipakai bersama.

Sebelumnya tiap modul (export XLSX, endpoint export, laporan PDF per-lembaga)
punya salinan fungsi kategorinya sendiri-sendiri, sehingga ambang batasnya bisa
bergeser diam-diam di salah satu tempat dan bikin angka antar laporan tidak
cocok. Semua konsumen sekarang memanggil fungsi di sini.
"""

# Urutan sengaja dari terberat ke teringan supaya tabel/ringkasan yang
# mengulang urutan ini konsisten di seluruh laporan.
CATEGORY_ORDER = ("Tinggi", "Sedang", "Rendah")


def confidence_category(hotspot: dict) -> str:
    """Kategori keyakinan deteksi.

    NASA FIRMS memakai dua format berbeda tergantung satelit: VIIRS memberi
    kode huruf (h/n/l), MODIS memberi persentase 0-100. Keduanya dipetakan ke
    skala yang sama di sini.
    """
    raw = str(hotspot.get("confidence", "")).strip().lower()

    if raw in ("h", "high"):
        return "Tinggi"
    if raw in ("n", "nominal", "medium"):
        return "Sedang"
    if raw in ("l", "low"):
        return "Rendah"

    try:
        value = int(raw)
    except ValueError:
        return "Rendah"

    return "Tinggi" if value > 80 else "Sedang" if value >= 30 else "Rendah"


def frp_category(hotspot: dict) -> str:
    """Kategori intensitas radiasi api (Fire Radiative Power, satuan MW)."""
    try:
        value = float(hotspot.get("frp") or 0)
    except (ValueError, TypeError):
        return "Rendah"

    return "Tinggi" if value > 30 else "Sedang" if value >= 10 else "Rendah"
