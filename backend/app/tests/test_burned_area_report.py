from __future__ import annotations

import pytest


_RAW_ROWS = [
    {"polygon_metadata_id": 1, "lembaga": "KOPERASI A", "skema": "PPHKm", "nama_prov": "Riau",
     "wilker_bps": "BPS Kampar", "latest_period": 202604, "burned_months": 2,
     "burned_ha": 1786.3, "is_estimated": False},
    {"polygon_metadata_id": 2, "lembaga": "LPHD B", "skema": "PPHD", "nama_prov": "Riau",
     "wilker_bps": "BPS Kampar", "latest_period": 202603, "burned_months": 2,
     "burned_ha": 694.3, "is_estimated": False},
    {"polygon_metadata_id": 3, "lembaga": "KT C", "skema": "PPHKm", "nama_prov": "Lampung",
     "wilker_bps": "BPS Lampung", "latest_period": 202603, "burned_months": 1,
     "burned_ha": 2.1, "is_estimated": True},
]


class _FakeStore:
    enabled = True

    def __init__(self, rows=None, raises: Exception | None = None) -> None:
        self._rows = _RAW_ROWS if rows is None else rows
        self._raises = raises
        self.calls: list[dict] = []

    def read_burned_area_map_overlay(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        return self._rows


def test_load_burned_area_report_aggregates_by_skema() -> None:
    from app.services.burned_area_report import load_burned_area_report

    report = load_burned_area_report(postgres_store=_FakeStore())

    assert report["kps_count"] == 3
    assert report["total_ha"] == pytest.approx(2482.7)
    # diurutkan dari luas terbesar
    assert [item["skema"] for item in report["by_skema"]] == ["PPHKm", "PPHD"]
    assert report["by_skema"][0]["total_ha"] == pytest.approx(1788.4)
    assert report["by_skema"][0]["kps_count"] == 2


def test_load_burned_area_report_filters_by_province() -> None:
    from app.services.burned_area_report import load_burned_area_report

    report = load_burned_area_report(province="Lampung", postgres_store=_FakeStore())

    assert report["kps_count"] == 1
    assert report["rows"][0]["lembaga"] == "KT C"
    assert report["total_ha"] == pytest.approx(2.1)


def test_load_burned_area_report_filters_by_skema_and_agency() -> None:
    from app.services.burned_area_report import load_burned_area_report

    by_skema = load_burned_area_report(skema="PPHD", postgres_store=_FakeStore())
    assert [row["lembaga"] for row in by_skema["rows"]] == ["LPHD B"]

    by_agency = load_burned_area_report(agency="KOPERASI A", postgres_store=_FakeStore())
    assert [row["lembaga"] for row in by_agency["rows"]] == ["KOPERASI A"]


def test_load_burned_area_report_formats_period_and_estimated_flag() -> None:
    from app.services.burned_area_report import load_burned_area_report

    report = load_burned_area_report(postgres_store=_FakeStore())
    by_name = {row["lembaga"]: row for row in report["rows"]}

    assert by_name["KOPERASI A"]["latest_period"] == "2026-04"
    assert by_name["KOPERASI A"]["is_estimated"] is False
    assert by_name["KT C"]["is_estimated"] is True


def test_load_burned_area_report_survives_database_failure() -> None:
    """Luas terbakar cuma lampiran pelengkap -- kegagalan membacanya tidak
    boleh menggagalkan seluruh laporan hotspot yang jadi isi utamanya."""
    from app.services.burned_area_report import load_burned_area_report

    report = load_burned_area_report(postgres_store=_FakeStore(raises=RuntimeError("db down")))

    assert report == {"rows": [], "by_skema": [], "total_ha": 0.0, "kps_count": 0}


def test_load_burned_area_report_returns_empty_when_store_disabled() -> None:
    from app.services.burned_area_report import load_burned_area_report

    class _Disabled:
        enabled = False

    report = load_burned_area_report(postgres_store=_Disabled())
    assert report["kps_count"] == 0


def test_load_burned_area_report_passes_year_through() -> None:
    from app.services.burned_area_report import load_burned_area_report

    store = _FakeStore()
    load_burned_area_report(year=2026, postgres_store=store)

    assert store.calls == [{"year": 2026}]
