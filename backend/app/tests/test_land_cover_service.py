"""Tes LandCoverService. Tidak ada panggilan GEE/DB nyata (bahaya #1)."""

from __future__ import annotations

import pytest

from app.services.land_cover_service import (
    YEARS,
    LandCoverError,
    LandCoverService,
    _build_summary_text,
    _dw_label_to_class,
    _net_change,
)


def _svc() -> LandCoverService:
    return LandCoverService.__new__(LandCoverService)


def test_years_constant() -> None:
    assert YEARS == (2020, 2021, 2022, 2023, 2024, 2025)


@pytest.mark.parametrize(
    "label,expected",
    [(0, "air"), (1, "hutan"), (2, "semak"), (3, "semak"), (4, "pertanian"),
     (5, "semak"), (7, "terbuka"), (6, None), (8, None), (99, None)],
)
def test_dw_label_to_class(label, expected) -> None:
    assert _dw_label_to_class(label) == expected


def test_enabled_false_without_credentials(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    for k in ("GEE_SERVICE_ACCOUNT_EMAIL", "GEE_SERVICE_ACCOUNT_KEY_PATH", "GEE_PROJECT_ID"):
        monkeypatch.setenv(k, "")
    try:
        svc = _svc()
        svc.settings = get_settings()
        assert svc.enabled is False
    finally:
        get_settings.cache_clear()


def test_ensure_ee_raises_when_not_configured(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    for k in ("GEE_SERVICE_ACCOUNT_EMAIL", "GEE_SERVICE_ACCOUNT_KEY_PATH", "GEE_PROJECT_ID"):
        monkeypatch.setenv(k, "")
    try:
        svc = _svc()
        svc.settings = get_settings()
        svc._ee_initialized = False
        with pytest.raises(LandCoverError):
            svc._ensure_ee()
    finally:
        get_settings.cache_clear()


def test_net_change_and_summary() -> None:
    table = {
        2020: {"hutan": {"area_ha": 5400.0, "pct": 74.9}, "semak": {"area_ha": 1150.0, "pct": 15.9},
               "pertanian": {"area_ha": 380.0, "pct": 5.3}, "terbuka": {"area_ha": 180.0, "pct": 2.5},
               "air": {"area_ha": 101.0, "pct": 1.4}},
        2025: {"hutan": {"area_ha": 4470.0, "pct": 62.0}, "semak": {"area_ha": 1560.0, "pct": 21.6},
               "pertanian": {"area_ha": 810.0, "pct": 11.2}, "terbuka": {"area_ha": 270.0, "pct": 3.7},
               "air": {"area_ha": 101.0, "pct": 1.4}},
    }
    nc = _net_change(table)
    assert nc["hutan"] == pytest.approx(-930.0)
    assert nc["pertanian"] == pytest.approx(430.0)
    text = _build_summary_text(table)
    assert "Hutan" in text and "930" in text


def test_summary_incomplete_data() -> None:
    assert "tidak lengkap" in _build_summary_text({2020: {}}).lower()
