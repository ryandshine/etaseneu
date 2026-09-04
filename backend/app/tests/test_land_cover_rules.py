"""Tes logika land_cover/temporal.py & land_cover/labels.py dengan citra
"skalar" palsu yang benar-benar menghitung (eq/neq/And/Or/where), bukan
no-op -- supaya aturan transisinya teruji, bukan cuma jalan. Tanpa GEE/DB."""

from __future__ import annotations

import pytest

from app.services.land_cover import labels, temporal
from app.services.land_cover_service import CLASS_KEYS, _CLASS_IDX

IDX = _CLASS_IDX
H, K, S, P, T, A = (IDX[k] for k in ("hutan", "kebun", "semak", "pertanian", "terbuka", "air"))


class Px:
    """Satu piksel: nilai int atau None (= ter-mask)."""

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
    out = temporal.forest_gain_must_persist(None, _series(S, H, T, T, T), H, K)
    assert _vals(out) == [S, S, T, T, T]


def test_forest_gain_that_persists_is_kept() -> None:
    out = temporal.forest_gain_must_persist(None, _series(S, H, H, H, H), H, K)
    assert _vals(out) == [S, H, H, H, H]


def test_forest_after_kebun_not_treated_as_gain_by_rule2() -> None:
    # kebun -> hutan -> semak: rule 2 tidak menyentuh (prev == kebun); rule 3 yang menangani
    out = temporal.forest_gain_must_persist(None, _series(K, H, S, S, S), H, K)
    assert _vals(out) == [K, H, S, S, S]
    out = temporal.kebun_to_forest_must_persist(None, out, H, K)
    assert _vals(out) == [K, K, S, S, S]


def test_kebun_to_forest_persisting_is_kept() -> None:
    out = temporal.kebun_to_forest_must_persist(None, _series(K, H, H, H, H), H, K)
    assert _vals(out) == [K, H, H, H, H]


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


# --- labels --------------------------------------------------------------


@pytest.mark.parametrize(
    "dw,ref,wc,wc_tree,expected",
    [
        (H, H, H, 1, 1),        # stabil, WC setuju
        (H, H, S, 0, 0),        # stabil, WC bilang semak -> buang (DW salah sistematis)
        (T, H, H, 1, 1),        # DW anggap berubah sejak 2021 -> lolos tanpa dicek
        (K, K, H, 1, 1),        # kebun: WC "pohon" sudah cukup setuju
        (K, K, P, 0, 0),        # kebun tapi WC bilang pertanian -> buang
        (P, P, None, 0, 0),     # WC built-up (tanpa padanan) -> buang
    ],
)
def test_consensus_mask_rules(dw, ref, wc, wc_tree, expected) -> None:
    ok = labels.consensus_mask(None, Px(dw), Px(ref), Px(wc), Px(wc_tree), K)
    assert ok.v == expected


def test_worldcover_map_only_uses_known_class_keys() -> None:
    assert set(labels.WORLDCOVER_MAP.values()) <= set(CLASS_KEYS)
    assert 50 not in labels.WORLDCOVER_MAP  # built-up sengaja tidak dipetakan


def test_sparse_classes_flags_only_small_nonzero_counts() -> None:
    counts = {"hutan": 400, "kebun": 12, "semak": 0, "air": 30}
    assert labels.sparse_classes(counts, CLASS_KEYS, 30) == ["kebun"]
