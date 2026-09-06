"""Tes logika land_cover/temporal.py & land_cover/labels.py dengan citra
"skalar" palsu yang benar-benar menghitung (eq/neq/And/Or/where/gt/lt), bukan
no-op -- supaya aturan transisi & penentuan seed spektral teruji. Tanpa GEE/DB.

Taksonomi 5 kelas mandiri (formula v5): hutan|pertanian|semak|basah|terbuka.
"""

from __future__ import annotations

import pytest

from app.services.land_cover import labels, temporal
from app.services.land_cover_service import CLASS_KEYS, _CLASS_IDX

IDX = _CLASS_IDX
H, P, S, B, T = (IDX[k] for k in ("hutan", "pertanian", "semak", "basah", "terbuka"))


class Px:
    """Satu piksel: nilai int/float atau None (= ter-mask)."""

    def __init__(self, v):
        self.v = v

    def _bin(self, other, fn):
        o = other.v if isinstance(other, Px) else other
        if self.v is None or o is None:
            return Px(None)
        return Px(int(fn(self.v, o)))

    def eq(self, o):
        return self._bin(o, lambda a, b: a == b)

    def neq(self, o):
        return self._bin(o, lambda a, b: a != b)

    def gt(self, o):
        return self._bin(o, lambda a, b: a > b)

    def gte(self, o):
        return self._bin(o, lambda a, b: a >= b)

    def lt(self, o):
        return self._bin(o, lambda a, b: a < b)

    def lte(self, o):
        return self._bin(o, lambda a, b: a <= b)

    def And(self, o):
        return self._bin(o, lambda a, b: bool(a) and bool(b))

    def Or(self, o):
        # GEE: piksel ter-mask dianggap tidak ada -> hasil ter-mask
        return self._bin(o, lambda a, b: bool(a) or bool(b))

    def Not(self):
        return Px(None if self.v is None else int(not self.v))

    def unmask(self, fill):
        return Px(fill if self.v is None else self.v)

    def where(self, test, value):
        val = value.v if isinstance(value, Px) else value
        if test.v:
            return Px(val)
        return Px(self.v)

    def rename(self, _n):
        return self

    def updateMask(self, m):
        return Px(None if not m.v else self.v)


class FakeImage:
    """Mock Image yang mendukung .constant() untuk tes rule spektral."""

    @staticmethod
    def constant(v):
        return Px(v)


class FakeEE:
    Image = FakeImage


class FakeFeatImage:
    def __init__(self, bands: dict[str, float]):
        self.bands = {k: Px(v) for k, v in bands.items()}

    def select(self, name: str) -> Px:
        return self.bands[name]


def _series(*vals):
    return {2021 + i: Px(v) for i, v in enumerate(vals)}


def _vals(per_year):
    return [per_year[y].v for y in sorted(per_year)]


# --- temporal ------------------------------------------------------------


def test_despike_symmetric_restores_spike_only() -> None:
    out = temporal.despike_symmetric(None, _series(H, T, H, H, H))
    assert _vals(out) == [H, H, H, H, H]


def test_despike_leaves_real_change_alone() -> None:
    out = temporal.despike_symmetric(None, _series(H, H, T, T, T))
    assert _vals(out) == [H, H, T, T, T]


def test_forest_gain_one_year_reverts_to_previous_class() -> None:
    # semak -> hutan (1 th) -> terbuka: hutan tidak tumbuh & hilang setahun
    out = temporal.forest_gain_must_persist(None, _series(S, H, T, T, T), H, P)
    assert _vals(out) == [S, S, T, T, T]


def test_forest_gain_that_persists_is_kept() -> None:
    out = temporal.forest_gain_must_persist(None, _series(S, H, H, H, H), H, P)
    assert _vals(out) == [S, H, H, H, H]


def test_forest_after_cropland_not_treated_as_gain_by_rule2() -> None:
    # pertanian (sawit) -> hutan -> semak: rule 2 tidak menyentuh (prev ==
    # pertanian); rule 3 yang menangani flicker sawit/hutan
    out = temporal.forest_gain_must_persist(None, _series(P, H, S, S, S), H, P)
    assert _vals(out) == [P, H, S, S, S]
    out = temporal.cropland_to_forest_must_persist(None, out, H, P)
    assert _vals(out) == [P, P, S, S, S]


def test_cropland_to_forest_persisting_is_kept() -> None:
    out = temporal.cropland_to_forest_must_persist(None, _series(P, H, H, H, H), H, P)
    assert _vals(out) == [P, H, H, H, H]


def test_apply_transition_rules_never_touches_first_and_last_year() -> None:
    series = _series(T, H, T, H, H)   # 2025 = hutan "baru" -> harus tetap
    out, rules = temporal.apply_transition_rules(None, series, IDX)
    vals = _vals(out)
    assert vals[0] == T and vals[-1] == H
    # 2022: spike (T,H,T) -> T; 2023: spike (H,T,H) -> H, lalu hutan itu
    # bertahan 2024-2025 -> rule 2 membiarkannya (bukan gain sesaat)
    assert vals == [T, T, H, H, H]
    assert rules == list(temporal.RULES)


def test_apply_transition_rules_short_series_is_noop() -> None:
    out, rules = temporal.apply_transition_rules(None, {2024: Px(H), 2025: Px(T)}, IDX)
    assert _vals(out) == [H, T] and rules == []


# --- labels (spectral endmembers & rule classifier) -----------------------


def test_spectral_seed_identifies_clean_endmembers() -> None:
    ee = FakeEE

    # Hutan kanopi rapat (stabil & lembab)
    hutan_feat = FakeFeatImage({
        "ndvi": 0.82, "nbr": 0.55, "B8": 0.30, "mndwi": -0.25,
        "bsi": -0.10, "B4": 0.03, "B11": 0.08, "ndmi": 0.20, "ndvi_std": 0.05,
    })
    assert labels.spectral_seed_image(ee, hutan_feat, IDX, use_sar=False).v == H

    # Badan air
    water_feat = FakeFeatImage({
        "ndvi": -0.10, "nbr": -0.20, "B8": 0.05, "mndwi": 0.20,
        "bsi": -0.20, "B4": 0.03, "B11": 0.02, "ndmi": -0.10, "ndvi_std": 0.02,
    })
    assert labels.spectral_seed_image(ee, water_feat, IDX, use_sar=False).v == B

    # Lahan terbuka
    bare_feat = FakeFeatImage({
        "ndvi": 0.15, "nbr": -0.10, "B8": 0.18, "mndwi": -0.30,
        "bsi": 0.12, "B4": 0.18, "B11": 0.25, "ndmi": -0.15, "ndvi_std": 0.04,
    })
    assert labels.spectral_seed_image(ee, bare_feat, IDX, use_sar=False).v == T

    # Semak belukar
    shrub_feat = FakeFeatImage({
        "ndvi": 0.42, "nbr": 0.30, "B8": 0.22, "mndwi": -0.15,
        "bsi": 0.01, "B4": 0.07, "B11": 0.12, "ndmi": 0.08, "ndvi_std": 0.06,
    })
    assert labels.spectral_seed_image(ee, shrub_feat, IDX, use_sar=False).v == S

    # Pertanian / perkebunan
    crop_feat = FakeFeatImage({
        "ndvi": 0.65, "nbr": 0.40, "B8": 0.25, "mndwi": -0.15,
        "bsi": -0.02, "B4": 0.05, "B11": 0.12, "ndmi": 0.10, "ndvi_std": 0.08,
    })
    assert labels.spectral_seed_image(ee, crop_feat, IDX, use_sar=False).v == P

    # Piksel ambigu (tidak ada endmember yang cocok) -> harus ter-mask (None)
    ambiguous = FakeFeatImage({
        "ndvi": 0.30, "nbr": 0.20, "B8": 0.20, "mndwi": -0.02,
        "bsi": 0.08, "B4": 0.05, "B11": 0.10, "ndmi": 0.05, "ndvi_std": 0.05,
    })
    assert labels.spectral_seed_image(ee, ambiguous, IDX, use_sar=False).v is None


def test_formula_v6_phenology_and_moisture_discrimination() -> None:
    ee = FakeEE

    # 1. Pertanian/ladang pangan semusim: fenologi tahunan tinggi (ndvi_std = 0.16)
    #    terdeteksi sebagai Pertanian (P) meskipun NDVI komposit kemarau di tingkat sedang (0.50)
    seasonal_crop = FakeFeatImage({
        "ndvi": 0.50, "nbr": 0.25, "B8": 0.20, "mndwi": -0.10,
        "bsi": 0.02, "B4": 0.08, "B11": 0.15, "ndmi": 0.05, "ndvi_std": 0.16,
    })
    assert labels.spectral_seed_image(ee, seasonal_crop, IDX, use_sar=False).v == P
    assert labels.rule_based_classify(ee, seasonal_crop, IDX, use_sar=False).v == P

    # 2. Agroforestri kanopi rapat (kopi/kakao di bawah naungan pohon):
    #    NDVI tinggi (0.78), SWIR tinggi (B11 = 0.14), NBR moderat (0.42)
    #    teridentifikasi sebagai Pertanian/Agroforestri (P), bukan Hutan Alami (H)
    agroforestry = FakeFeatImage({
        "ndvi": 0.78, "nbr": 0.42, "B8": 0.28, "mndwi": -0.18,
        "bsi": -0.05, "B4": 0.04, "B11": 0.14, "ndmi": 0.16, "ndvi_std": 0.07,
    })
    assert labels.spectral_seed_image(ee, agroforestry, IDX, use_sar=False).v == P
    assert labels.rule_based_classify(ee, agroforestry, IDX, use_sar=False).v == P

    # 3. Lahan basah rawa gambut / mangrove jenuh air:
    #    NDMI sangat tinggi (0.30), MNDWI mendekati nol (-0.01), NIR teredam air (B8 = 0.18)
    #    teridentifikasi sebagai Basah (B)
    wetland_peat = FakeFeatImage({
        "ndvi": 0.35, "nbr": 0.10, "B8": 0.18, "mndwi": -0.01,
        "bsi": -0.08, "B4": 0.04, "B11": 0.08, "ndmi": 0.30, "ndvi_std": 0.04,
    })
    assert labels.spectral_seed_image(ee, wetland_peat, IDX, use_sar=False).v == B
    assert labels.rule_based_classify(ee, wetland_peat, IDX, use_sar=False).v == B


def test_rule_based_classify_assigns_all_classes() -> None:
    ee = FakeEE

    # Hutan
    hutan_feat = FakeFeatImage({
        "ndvi": 0.78, "nbr": 0.52, "B8": 0.28, "mndwi": -0.20,
        "bsi": -0.05, "B4": 0.03, "B11": 0.08,
    })
    assert labels.rule_based_classify(ee, hutan_feat, IDX, use_sar=False).v == H

    # Air
    water_feat = FakeFeatImage({
        "ndvi": -0.05, "nbr": 0.0, "B8": 0.06, "mndwi": 0.10,
        "bsi": -0.10, "B4": 0.02, "B11": 0.02,
    })
    assert labels.rule_based_classify(ee, water_feat, IDX, use_sar=False).v == B

    # Lahan terbuka
    bare_feat = FakeFeatImage({
        "ndvi": 0.18, "nbr": -0.10, "B8": 0.15, "mndwi": -0.20,
        "bsi": 0.10, "B4": 0.15, "B11": 0.22,
    })
    assert labels.rule_based_classify(ee, bare_feat, IDX, use_sar=False).v == T


def test_sparse_classes_flags_only_small_nonzero_counts() -> None:
    counts = {"hutan": 400, "pertanian": 12, "semak": 0, "basah": 30}
    assert labels.sparse_classes(counts, CLASS_KEYS, 30) == ["pertanian"]

