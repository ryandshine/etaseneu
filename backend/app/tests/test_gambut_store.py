"""_GambutMixin dengan koneksi PALSU -- tidak menyentuh Postgres (bahaya #1
CLAUDE.md). Yang diuji: agregasi total/by_fungsi dari baris polygon_gambut_overlay,
dan None saat poligon tidak beririsan gambut sama sekali."""

from __future__ import annotations

from contextlib import contextmanager

from app.services.postgres_store._gambut import _GambutMixin


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._executed_params = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class _Store(_GambutMixin):
    def __init__(self, rows):
        self._rows = rows

    @contextmanager
    def connection(self):
        yield _FakeConn(self._rows)


def test_read_gambut_summary_returns_none_when_no_overlap():
    store = _Store([])
    assert store.read_gambut_summary(999) is None


def test_read_gambut_summary_aggregates_total_and_by_fungsi():
    rows = [
        {
            "kode_khg": "KHG.61.06.02",
            "nama_khg": "KHG Sungai Embalon - Sungai Palin",
            "fungsi": "Lindung",
            "kubah_gmbt": "Non Kubah Gambut",
            "luas_ha": 40.0,
        },
        {
            "kode_khg": "KHG.61.06.02",
            "nama_khg": "KHG Sungai Embalon - Sungai Palin",
            "fungsi": "Budidaya",
            "kubah_gmbt": "Non Kubah Gambut",
            "luas_ha": 20.25,
        },
    ]
    store = _Store(rows)

    result = store.read_gambut_summary(287644)

    assert result is not None
    assert result["total_ha"] == 60.25
    assert result["by_fungsi"] == {"Lindung": 40.0, "Budidaya": 20.25}
    assert len(result["khg"]) == 2
    assert result["khg"][0]["kode_khg"] == "KHG.61.06.02"


def test_read_gambut_summary_merges_same_fungsi_across_multiple_khg():
    rows = [
        {"kode_khg": "KHG.A", "nama_khg": "A", "fungsi": "Lindung", "kubah_gmbt": "Kubah Gambut", "luas_ha": 10.0},
        {"kode_khg": "KHG.B", "nama_khg": "B", "fungsi": "Lindung", "kubah_gmbt": "Non Kubah Gambut", "luas_ha": 15.0},
    ]
    store = _Store(rows)

    result = store.read_gambut_summary(1)

    assert result["by_fungsi"] == {"Lindung": 25.0}
    assert result["total_ha"] == 25.0
