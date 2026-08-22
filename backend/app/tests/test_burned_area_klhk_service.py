from __future__ import annotations

import json

import pytest


def test_month_from_periode_maps_indonesian_month_names() -> None:
    from app.services.burned_area_klhk_service import _month_from_periode

    assert _month_from_periode("MEI") == 5
    assert _month_from_periode("juni") == 6
    assert _month_from_periode(" Juli ") == 7
    assert _month_from_periode(None) is None
    assert _month_from_periode("BULAN_ASING") is None


def test_year_from_ket_parses_date_prefix() -> None:
    from app.services.burned_area_klhk_service import _year_from_ket

    assert _year_from_ket("20260531", fallback_year=2020) == 2026
    assert _year_from_ket(None, fallback_year=2020) == 2020
    assert _year_from_ket("bukan-tanggal", fallback_year=2020) == 2020


def test_guess_year_from_filename() -> None:
    from app.services.burned_area_klhk_service import _guess_year_from_filename

    assert _guess_year_from_filename("burned_area_indonesia_jun_juli_2026.geojson") == 2026
    assert _guess_year_from_filename("tidak_ada_tahun.geojson") == 2026


def _write_geojson(path, features) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def test_iter_hm_features_filters_akurasi_and_requires_geometry_and_periode(tmp_path) -> None:
    from app.services.burned_area_klhk_service import _iter_hm_features

    geojson_path = tmp_path / "burned.geojson"
    _write_geojson(
        geojson_path,
        [
            {"type": "Feature", "properties": {"AKURASI": "H", "PERIODE": "MEI", "KET": "20260531"},
             "geometry": {"type": "Polygon", "coordinates": []}},
            {"type": "Feature", "properties": {"AKURASI": "L", "PERIODE": "MEI", "KET": "20260531"},
             "geometry": {"type": "Polygon", "coordinates": []}},
            {"type": "Feature", "properties": {"AKURASI": "M", "PERIODE": "JUNI", "KET": "20260630"},
             "geometry": None},
            {"type": "Feature", "properties": {"AKURASI": "H", "PERIODE": "BULAN_ASING", "KET": "20260531"},
             "geometry": {"type": "Polygon", "coordinates": []}},
            {"type": "Feature", "properties": {"AKURASI": "M", "PERIODE": "JULI", "KET": "20260731"},
             "geometry": {"type": "Polygon", "coordinates": [[1, 2]]}},
        ],
    )

    results = list(_iter_hm_features(str(geojson_path), fallback_year=2026))

    # Cuma baris pertama (H) dan terakhir (M, JULI) yang lolos: L ditolak,
    # geometry kosong ditolak, PERIODE tak dikenal ditolak.
    assert results == [
        (2026, 5, {"type": "Polygon", "coordinates": []}),
        (2026, 7, {"type": "Polygon", "coordinates": [[1, 2]]}),
    ]


class _FakeStore:
    enabled = True

    def __init__(self) -> None:
        self.cleared = False
        self.refresh_calls: list[tuple[list, str]] = []

    def clear_burned_area_summary(self) -> int:
        self.cleared = True
        return 999

    def refresh_burned_area_from_klhk(self, features, source: str) -> int:
        materialized = list(features)
        self.refresh_calls.append((materialized, source))
        return len(materialized)


def test_refresh_burned_area_from_klhk_file_raises_when_file_missing() -> None:
    from app.services.burned_area_klhk_service import BurnedAreaKlhkError, refresh_burned_area_from_klhk_file

    with pytest.raises(BurnedAreaKlhkError):
        refresh_burned_area_from_klhk_file("/tidak/ada/file.geojson", postgres_store=_FakeStore())


def test_refresh_burned_area_from_klhk_file_processes_hm_features_only(tmp_path) -> None:
    from app.services.burned_area_klhk_service import KLHK_SOURCE_LABEL, refresh_burned_area_from_klhk_file

    geojson_path = tmp_path / "burned.geojson"
    _write_geojson(
        geojson_path,
        [
            {"type": "Feature", "properties": {"AKURASI": "H", "PERIODE": "MEI", "KET": "20260531"},
             "geometry": {"type": "Polygon", "coordinates": []}},
            {"type": "Feature", "properties": {"AKURASI": "L", "PERIODE": "MEI", "KET": "20260531"},
             "geometry": {"type": "Polygon", "coordinates": []}},
        ],
    )
    store = _FakeStore()

    result = refresh_burned_area_from_klhk_file(str(geojson_path), postgres_store=store)

    assert result == {"file": "burned.geojson", "computed": 1}
    assert store.cleared is False
    assert len(store.refresh_calls) == 1
    features, source = store.refresh_calls[0]
    assert features == [(2026, 5, {"type": "Polygon", "coordinates": []})]
    assert source == KLHK_SOURCE_LABEL


def test_refresh_burned_area_from_klhk_file_clears_existing_when_requested(tmp_path) -> None:
    """clear_existing=True cuma untuk migrasi sekali pindah dari GEE -- harus
    membersihkan burned_area_summary lama sebelum mengisi data KLHK baru."""
    from app.services.burned_area_klhk_service import refresh_burned_area_from_klhk_file

    geojson_path = tmp_path / "burned.geojson"
    _write_geojson(geojson_path, [])
    store = _FakeStore()

    refresh_burned_area_from_klhk_file(str(geojson_path), postgres_store=store, clear_existing=True)

    assert store.cleared is True


def test_refresh_burned_area_from_klhk_file_raises_when_store_disabled(tmp_path) -> None:
    from app.services.burned_area_klhk_service import BurnedAreaKlhkError, refresh_burned_area_from_klhk_file

    geojson_path = tmp_path / "burned.geojson"
    _write_geojson(geojson_path, [])

    class _Disabled:
        enabled = False

    with pytest.raises(BurnedAreaKlhkError):
        refresh_burned_area_from_klhk_file(str(geojson_path), postgres_store=_Disabled())
