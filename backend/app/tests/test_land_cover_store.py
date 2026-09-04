"""Mixin store tutupan lahan dengan koneksi PALSU -- tidak menyentuh Postgres
(bahaya #1 CLAUDE.md). Yang diuji: save/delete berjalan di dalam SATU
transaksi eksplisit (koneksi produksi autocommit=True), reset 'running' basi
berbasis umur, dan DDL cuma dijalankan sekali per proses."""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from app.services.postgres_store import _land_cover as mod
from app.services.postgres_store._land_cover import _LandCoverMixin


class _FakeCursor:
    def __init__(self, log):
        self._log = log
        self.rowcount = 1

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self._log.append(("execute", " ".join(sql.split()), params))

    def executemany(self, sql, rows):
        self._log.append(("executemany", " ".join(sql.split())[:60], list(rows)))

    def fetchone(self):
        return None


class _FakeConn:
    def __init__(self, log):
        self._log = log
        self.in_tx = False

    def cursor(self):
        # catat apakah cursor dibuka SAAT transaksi aktif
        self._log.append(("cursor", self.in_tx))
        return _FakeCursor(self._log)

    @contextmanager
    def transaction(self):
        self._log.append(("tx", "begin"))
        self.in_tx = True
        try:
            yield
        finally:
            self.in_tx = False
            self._log.append(("tx", "end"))


class _Store(_LandCoverMixin):
    enabled = True

    def __init__(self):
        self.log: list = []

    @contextmanager
    def connection(self):
        yield _FakeConn(self.log)


@pytest.fixture(autouse=True)
def _reset_ddl_flag():
    _LandCoverMixin._land_cover_tables_ready = False
    yield
    _LandCoverMixin._land_cover_tables_ready = False


def _writes_inside_tx(log):
    """Semua DML (execute/executemany) setelah DDL harus berada di antara
    tx begin & end, dan cursor-nya dibuka saat in_tx."""
    tx_open = False
    seen_tx = False
    for entry in log:
        if entry[0] == "tx":
            tx_open = entry[1] == "begin"
            seen_tx = True
        elif entry[0] == "cursor" and seen_tx:
            assert entry[1] is True, "cursor DML dibuka di luar transaksi"
    return seen_tx


def test_save_result_runs_in_single_transaction():
    store = _Store()
    store.save_land_cover_result(
        7, "psagustus2026", model_trees=150, n_training=10, oob_accuracy=0.9,
        duration_s=1.0,
        year_class_rows=[{"year": 2021, "class_key": "hutan", "area_ha": 1, "pct": 100}],
        year_geom_rows=[{"year": 2021, "class_key": "hutan",
                         "geometry_geojson": {"type": "MultiPolygon", "coordinates": []}}],
        formula_version=2, meta={"a": 1}, source="v2",
    )
    assert _writes_inside_tx(store.log)
    tx_begin = [i for i, e in enumerate(store.log) if e == ("tx", "begin")]
    tx_end = [i for i, e in enumerate(store.log) if e == ("tx", "end")]
    assert len(tx_begin) == 1 and len(tx_end) == 1
    dml = [e for e in store.log[tx_begin[0]:tx_end[0]] if e[0] in ("execute", "executemany")]
    # 2 DELETE + 1 UPSERT + 2 executemany, semuanya di dalam transaksi
    assert len(dml) == 5
    upsert = next(e for e in dml if "INSERT INTO land_cover_analysis" in e[1])
    assert upsert[2][-3:] == (2, '{"a": 1}', "v2")


def test_delete_result_runs_in_single_transaction():
    store = _Store()
    assert store.delete_land_cover_result(7) is True
    assert _writes_inside_tx(store.log)
    dml = [e for e in store.log if e[0] == "execute" and "DELETE" in e[1]]
    assert len(dml) == 3


def test_ddl_runs_once_per_process():
    store = _Store()
    store.read_land_cover_status(1)
    n_ddl_first = sum(1 for e in store.log if e[0] == "execute" and e[1].startswith(("CREATE", "ALTER")))
    assert n_ddl_first >= 6
    store.log.clear()
    store.read_land_cover_status(1)
    assert not any(e[1].startswith(("CREATE", "ALTER")) for e in store.log if e[0] == "execute")


def test_reset_stale_running_is_age_based():
    store = _Store()
    store.reset_stale_land_cover_running()
    upd = next(e for e in store.log if e[0] == "execute" and "SET status = 'error'" in e[1])
    sql = upd[1]
    assert "status = 'running'" in sql
    assert "make_interval" in sql
    # parameter pertama = umur maksimum (menit), bukan reset tanpa syarat
    assert upd[2][0] == mod.LAND_COVER_STALE_RUNNING_MIN
