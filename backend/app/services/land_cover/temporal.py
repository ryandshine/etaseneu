"""Aturan transisi antar-tahun (post-klasifikasi) untuk deret 2021-2025.

Klasifikasi per tahun dibuat independen; RF tidak tahu bahwa tutupan lahan
punya "fisika": hutan alam tidak tumbuh dari lahan terbuka dalam setahun, dan
kebun (termasuk sawit, kelas "pertanian" di taksonomi IPCC) tidak berubah
jadi hutan alam. Pola yang melanggar itu hampir selalu sisa awan/haze atau
kebingungan spektral satu tahun. Aturan di bawah memperbaikinya dengan cara
KONSERVATIF: hanya tahun TENGAH (punya t-1 dan t+1) yang bisa diubah, dan
selalu ke arah kelas tetangganya -- tidak pernah mengarang kelas baru. Tahun
pertama & terakhir tidak disentuh, jadi perubahan nyata di tahun terakhir
(kebakaran 2025) tetap terlihat.

Urutan:
1. despike_symmetric        : t != t-1 dan t-1 == t+1                -> t := t-1
2. forest_gain_must_persist : t == hutan, t-1 bukan hutan/pertanian,
                              t+1 != hutan                            -> t := t-1
   (hutan yang "muncul" satu tahun lalu hilang lagi = bukan hutan; kalau
   hutan bertahan di t+1, dibiarkan -- regenerasi/kesalahan t-1 tidak
   bisa dibedakan dari sini, dan menghukumnya justru menghapus tren)
3. cropland_to_forest_must_persist: t-1 == pertanian, t == hutan,
                              t+1 != hutan                            -> t := pertanian
   (sawit/kebun tua vs hutan spektralnya mepet; satu tahun "hutan" di
   tengah deret pertanian = flicker, bukan konversi balik -- ini aturan
   pemisah eksplisit tambahan di atas guru Descals, bukan pengganti)

Semua fungsi menerima modul `ee` sebagai argumen (lihat `__init__.py`).
"""

from __future__ import annotations

RULES: tuple[str, ...] = (
    "despike_symmetric",
    "forest_gain_must_persist",
    "cropland_to_forest_must_persist",
)


def despike_symmetric(ee, per_year: dict[int, object]) -> dict[int, object]:
    years = sorted(per_year)
    out = dict(per_year)
    for i in range(1, len(years) - 1):
        prev, cur, nxt = per_year[years[i - 1]], per_year[years[i]], per_year[years[i + 1]]
        spike = cur.neq(prev).And(prev.eq(nxt))
        out[years[i]] = cur.where(spike, prev).rename("class_idx")
    return out


def forest_gain_must_persist(ee, per_year: dict[int, object], hutan_idx: int,
                             pertanian_idx: int) -> dict[int, object]:
    years = sorted(per_year)
    out = dict(per_year)
    for i in range(1, len(years) - 1):
        prev, cur, nxt = per_year[years[i - 1]], per_year[years[i]], per_year[years[i + 1]]
        gain = cur.eq(hutan_idx).And(prev.neq(hutan_idx)).And(prev.neq(pertanian_idx))
        transient = gain.And(nxt.neq(hutan_idx))
        out[years[i]] = cur.where(transient, prev).rename("class_idx")
    return out


def cropland_to_forest_must_persist(ee, per_year: dict[int, object], hutan_idx: int,
                                    pertanian_idx: int) -> dict[int, object]:
    years = sorted(per_year)
    out = dict(per_year)
    for i in range(1, len(years) - 1):
        prev, cur, nxt = per_year[years[i - 1]], per_year[years[i]], per_year[years[i + 1]]
        flicker = prev.eq(pertanian_idx).And(cur.eq(hutan_idx)).And(nxt.neq(hutan_idx))
        out[years[i]] = cur.where(flicker, prev).rename("class_idx")
    return out


def apply_transition_rules(ee, per_year: dict[int, object], class_idx_of: dict[str, int]
                           ) -> tuple[dict[int, object], list[str]]:
    """Terapkan semua aturan berurutan; mengembalikan `(per_year, rules)`.
    `rules` disimpan ke meta.temporal.rules supaya hasil bisa diaudit.
    Deret < 3 tahun: tidak ada tahun tengah, dikembalikan apa adanya."""
    if len(per_year) < 3:
        return dict(per_year), []
    hutan, pertanian = class_idx_of["hutan"], class_idx_of["pertanian"]
    out = despike_symmetric(ee, per_year)
    out = forest_gain_must_persist(ee, out, hutan, pertanian)
    out = cropland_to_forest_must_persist(ee, out, hutan, pertanian)
    return out, list(RULES)
