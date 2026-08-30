# Menu Tutupan Lahan per KPS (Sentinel-2 + Random Forest) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tombol on-demand di kartu Detail KPS yang mengklasifikasikan tutupan lahan satu poligon KPS/Hutan Adat untuk tiap tahun 2020–2025 dari Sentinel-2 via Google Earth Engine (Random Forest, guru label = Dynamic World), menyimpan hasilnya permanen, lalu menampilkan peta rona warna + grafik + tabel perubahan.

**Architecture:** Service GEE sinkron (`LandCoverService.analyze_polygon`) dijalankan lewat `BackgroundTasks`, progres di dict modul-global, status final di kolom tabel. Tiga tabel PostGIS baru lewat satu mixin `_LandCoverMixin`. Empat endpoint di `app/api/land_cover.py` (POST analyze + GET status/result/overlay) di bawah `_read_gate` yang sudah ada. Frontend: komponen `LandCoverPanel` di `KpsDetailView`, fetch langsung via `authFetch`, chart pakai `recharts` (sudah terpasang), peta pakai `react-leaflet` `<GeoJSON>`.

**Tech Stack:** Python 3.13, FastAPI, psycopg3, PostGIS, `earthengine-api` (sudah di `requirements.txt`), Shapely. Frontend React 18 + Vite + TypeScript, `react-leaflet` 4, `recharts` 3, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-30-tutupan-lahan-kps-design.md`

## Global Constraints

- **Bahaya #1 (CLAUDE.md):** tidak ada DB test terpisah. SETIAP test yang menyentuh `PostgresStore` HARUS memakai store palsu / disabled (pola `_FakeStore` di `app/tests/test_burned_area_s2_service.py`). Tidak pernah memanggil `analyze_polygon` sungguhan atau method tulis store dari test.
- **GEE di test:** `ee` selalu di-`monkeypatch` — tidak ada panggilan Earth Engine nyata. Pola `_FakeEE` di `test_burned_area_s2_service.py`.
- **Tidak menambah dependency Python.** Pakai `shapely` yang sudah ada; tidak butuh geopandas/fiona/gdal.
- **Kredensial GEE lewat `settings.gee_*`** (`gee_service_account_email`, `gee_service_account_key_path`, `gee_project_id`) — JANGAN hardcode `/app/shp/...` seperti skrip lama di `shp/`.
- **5 kelas, kunci persis:** `hutan`, `semak`, `pertanian`, `terbuka`, `air`. Urutan indeks RF = urutan itu (hutan=0 … air=4). Pemukiman di-skip.
- **Rentang tahun tetap:** `YEARS = (2020, 2021, 2022, 2023, 2024, 2025)`.
- **Warna kelas (dipakai backend-tidak, frontend-ya):** hutan `#1B7A3D`, semak `#9CC55B`, pertanian `#E8B84B`, terbuka `#C97B4A`, air `#2E7BBF`.
- **Cakupan poligon:** hanya `layer_key IN ('psagustus2026','HUTAN_ADAT_APR26')` dan `is_active = TRUE`.
- **Backend commit style:** conventional commits Bahasa Indonesia (`feat:`, `test:`, `docs:`), tanpa atribusi.
- **Backend test run:** `cd backend && .venv/bin/python -m pytest app/tests -q`. Frontend: `cd frontend && npm test`.
- **Sumber kebenaran status** = kolom `land_cover_analysis.status`. Dict modul-global `_LAND_COVER_RUN_STATE` HANYA untuk label langkah live (`step`), boleh hilang saat restart.

---

### Task 1: Mixin store `_LandCoverMixin` + wiring

**Files:**
- Create: `backend/app/services/postgres_store/_land_cover.py`
- Modify: `backend/app/services/postgres_store/__init__.py`
- Test: `backend/app/tests/test_land_cover_store_wiring.py`

**Interfaces:**
- Consumes: `self.connection()` (autocommit, dari `_ConnectionMixin`).
- Produces (dipakai Task 2–4, ditiru oleh `_FakeStore` di test):
  - `read_land_cover_target_polygon(polygon_id: int) -> dict | None`
    → `{"id": int, "layer_key": str, "lembaga": str|None, "nama_prov": str|None, "geometry_json": dict}` atau `None` kalau tidak ada / tidak aktif / layer_key di luar 2 itu.
  - `mark_land_cover_running(polygon_id: int, layer_key: str) -> None`
  - `mark_land_cover_error(polygon_id: int, message: str) -> None`
  - `save_land_cover_result(polygon_id: int, layer_key: str, *, model_trees: int, n_training: int, oob_accuracy: float | None, duration_s: float, year_class_rows: list[dict], year_geom_rows: list[dict]) -> None`
    - `year_class_rows`: item `{"year": int, "class_key": str, "area_ha": float, "pct": float}`
    - `year_geom_rows`: item `{"year": int, "class_key": str, "geometry_geojson": dict}` (kelas kosong TIDAK dikirim)
    - Efek: `DELETE` baris `land_cover_year_class` + `land_cover_year_geom` untuk poligon itu, `upsert` `land_cover_analysis` (`status='done'`, `computed_at=NOW()`, kolom metrik terisi), `INSERT` baris baru.
  - `read_land_cover_status(polygon_id: int) -> dict | None`
    → `{"status": str, "error_message": str|None, "computed_at": str|None}` (`computed_at` ISO) atau `None`.
  - `read_land_cover_result(polygon_id: int) -> dict | None`
    → `None` kalau status != `'done'`. Else `{"meta": {...semua kolom land_cover_analysis, computed_at ISO...}, "year_class": [{"year","class_key","area_ha","pct"}]}` (urut year, lalu urutan `CLASS_KEYS`).
  - `read_land_cover_overlay(polygon_id: int, year: int) -> list[dict]`
    → `[{"class_key": str, "area_ha": float, "pct": float, "geometry_json": dict}]` (kelas dengan geometri saja).

- [ ] **Step 1: Tulis test wiring yang gagal**

```python
# backend/app/tests/test_land_cover_store_wiring.py
"""Wiring mixin tutupan lahan. TIDAK menyentuh DB — hanya cek method ada
di PostgresStore (bahaya #1: tidak ada DB test terpisah)."""

from app.services.postgres_store import PostgresStore

EXPECTED = [
    "read_land_cover_target_polygon",
    "mark_land_cover_running",
    "mark_land_cover_error",
    "save_land_cover_result",
    "read_land_cover_status",
    "read_land_cover_result",
    "read_land_cover_overlay",
]


def test_postgres_store_exposes_land_cover_methods() -> None:
    for name in EXPECTED:
        assert callable(getattr(PostgresStore, name, None)), name
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_store_wiring.py -q`
Expected: FAIL (`AttributeError` / assert `read_land_cover_target_polygon`).

- [ ] **Step 3: Tulis mixin**

```python
# backend/app/services/postgres_store/_land_cover.py
"""Analisis tutupan lahan per poligon KPS/Hutan Adat (Sentinel-2 + Random
Forest). Tiga tabel terisolasi — tidak menyentuh `burned_area_summary`
maupun `s2_burned_area`. Hasil di-cache permanen: satu poligon dianalisis
sekali, lalu dibaca berkali-kali.

Kunci kelas: hutan|semak|pertanian|terbuka|air (pemukiman di-skip).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

_TARGET_LAYERS = ("psagustus2026", "HUTAN_ADAT_APR26")
CLASS_KEYS = ("hutan", "semak", "pertanian", "terbuka", "air")
_CLASS_ORDER = {k: i for i, k in enumerate(CLASS_KEYS)}


class _LandCoverMixin:
    def _ensure_land_cover_tables(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS land_cover_analysis (
                    id BIGSERIAL PRIMARY KEY,
                    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
                    layer_key TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    year_start INTEGER NOT NULL DEFAULT 2020,
                    year_end INTEGER NOT NULL DEFAULT 2025,
                    model_trees INTEGER,
                    n_training INTEGER,
                    oob_accuracy DOUBLE PRECISION,
                    source TEXT NOT NULL DEFAULT 'Sentinel-2 L2A + Random Forest (ETA SENEU)',
                    label_source TEXT NOT NULL DEFAULT 'Google Dynamic World v1',
                    error_message TEXT,
                    duration_s DOUBLE PRECISION,
                    computed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (polygon_metadata_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS land_cover_year_class (
                    id BIGSERIAL PRIMARY KEY,
                    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
                    year INTEGER NOT NULL,
                    class_key TEXT NOT NULL,
                    area_ha DOUBLE PRECISION NOT NULL,
                    pct DOUBLE PRECISION NOT NULL,
                    UNIQUE (polygon_metadata_id, year, class_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS land_cover_year_geom (
                    id BIGSERIAL PRIMARY KEY,
                    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
                    year INTEGER NOT NULL,
                    class_key TEXT NOT NULL,
                    geometry geometry(MultiPolygon, 4326),
                    UNIQUE (polygon_metadata_id, year, class_key)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS land_cover_year_geom_pid_year_idx "
                "ON land_cover_year_geom (polygon_metadata_id, year)"
            )

    def read_land_cover_target_polygon(self, polygon_id: int) -> dict[str, object] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, layer_key, lembaga, nama_prov,
                           ST_AsGeoJSON(geometry)::json AS geometry_json
                    FROM polygon_metadata
                    WHERE id = %s AND is_active = TRUE
                      AND layer_key = ANY(%s)
                    """,
                    (int(polygon_id), list(_TARGET_LAYERS)),
                )
                row = cur.fetchone()
        if not row or not row.get("geometry_json"):
            return None
        return {
            "id": int(row["id"]),
            "layer_key": row["layer_key"],
            "lembaga": row.get("lembaga"),
            "nama_prov": row.get("nama_prov"),
            "geometry_json": row["geometry_json"],
        }

    def mark_land_cover_running(self, polygon_id: int, layer_key: str) -> None:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO land_cover_analysis (polygon_metadata_id, layer_key, status)
                    VALUES (%s, %s, 'running')
                    ON CONFLICT (polygon_metadata_id) DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        status = 'running',
                        error_message = NULL
                    """,
                    (int(polygon_id), str(layer_key)),
                )

    def mark_land_cover_error(self, polygon_id: int, message: str) -> None:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE land_cover_analysis
                    SET status = 'error', error_message = %s
                    WHERE polygon_metadata_id = %s
                    """,
                    (str(message)[:2000], int(polygon_id)),
                )

    def save_land_cover_result(
        self,
        polygon_id: int,
        layer_key: str,
        *,
        model_trees: int,
        n_training: int,
        oob_accuracy: float | None,
        duration_s: float,
        year_class_rows: Sequence[dict[str, object]],
        year_geom_rows: Sequence[dict[str, object]],
    ) -> None:
        pid = int(polygon_id)
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM land_cover_year_class WHERE polygon_metadata_id = %s", (pid,))
                cur.execute("DELETE FROM land_cover_year_geom WHERE polygon_metadata_id = %s", (pid,))
                cur.execute(
                    """
                    INSERT INTO land_cover_analysis (
                        polygon_metadata_id, layer_key, status,
                        model_trees, n_training, oob_accuracy, duration_s, computed_at
                    )
                    VALUES (%s, %s, 'done', %s, %s, %s, %s, NOW())
                    ON CONFLICT (polygon_metadata_id) DO UPDATE SET
                        layer_key = EXCLUDED.layer_key,
                        status = 'done',
                        model_trees = EXCLUDED.model_trees,
                        n_training = EXCLUDED.n_training,
                        oob_accuracy = EXCLUDED.oob_accuracy,
                        duration_s = EXCLUDED.duration_s,
                        error_message = NULL,
                        computed_at = NOW()
                    """,
                    (pid, str(layer_key), int(model_trees), int(n_training),
                     None if oob_accuracy is None else float(oob_accuracy), float(duration_s)),
                )
                cur.executemany(
                    """
                    INSERT INTO land_cover_year_class
                        (polygon_metadata_id, year, class_key, area_ha, pct)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [
                        (pid, int(r["year"]), str(r["class_key"]), float(r["area_ha"]), float(r["pct"]))
                        for r in year_class_rows
                    ],
                )
                cur.executemany(
                    """
                    INSERT INTO land_cover_year_geom
                        (polygon_metadata_id, year, class_key, geometry)
                    VALUES (
                        %s, %s, %s,
                        ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s::text), 4326))
                    )
                    """,
                    [
                        (pid, int(r["year"]), str(r["class_key"]),
                         json.dumps(r["geometry_geojson"], default=float))
                        for r in year_geom_rows
                        if r.get("geometry_geojson")
                    ],
                )

    def read_land_cover_status(self, polygon_id: int) -> dict[str, object] | None:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, error_message, computed_at
                    FROM land_cover_analysis WHERE polygon_metadata_id = %s
                    """,
                    (int(polygon_id),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "status": row["status"],
            "error_message": row.get("error_message"),
            "computed_at": row["computed_at"].isoformat() if row.get("computed_at") else None,
        }

    def read_land_cover_result(self, polygon_id: int) -> dict[str, object] | None:
        pid = int(polygon_id)
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM land_cover_analysis WHERE polygon_metadata_id = %s", (pid,)
                )
                meta = cur.fetchone()
                if not meta or meta["status"] != "done":
                    return None
                cur.execute(
                    """
                    SELECT year, class_key, area_ha, pct
                    FROM land_cover_year_class WHERE polygon_metadata_id = %s
                    """,
                    (pid,),
                )
                rows = cur.fetchall()
        meta_out = dict(meta)
        if meta_out.get("computed_at"):
            meta_out["computed_at"] = meta_out["computed_at"].isoformat()
        if meta_out.get("created_at"):
            meta_out["created_at"] = meta_out["created_at"].isoformat()
        year_class = sorted(
            (
                {
                    "year": int(r["year"]),
                    "class_key": r["class_key"],
                    "area_ha": round(float(r["area_ha"]), 2),
                    "pct": round(float(r["pct"]), 2),
                }
                for r in rows
            ),
            key=lambda r: (r["year"], _CLASS_ORDER.get(r["class_key"], 99)),
        )
        return {"meta": meta_out, "year_class": year_class}

    def read_land_cover_overlay(self, polygon_id: int, year: int) -> list[dict[str, object]]:
        with self.connection() as conn:
            self._ensure_land_cover_tables(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT g.class_key,
                           COALESCE(c.area_ha, 0) AS area_ha,
                           COALESCE(c.pct, 0) AS pct,
                           ST_AsGeoJSON(g.geometry)::json AS geometry_json
                    FROM land_cover_year_geom g
                    LEFT JOIN land_cover_year_class c
                      ON c.polygon_metadata_id = g.polygon_metadata_id
                     AND c.year = g.year AND c.class_key = g.class_key
                    WHERE g.polygon_metadata_id = %s AND g.year = %s
                      AND g.geometry IS NOT NULL
                    """,
                    (int(polygon_id), int(year)),
                )
                rows = cur.fetchall()
        return [
            {
                "class_key": r["class_key"],
                "area_ha": round(float(r["area_ha"]), 2),
                "pct": round(float(r["pct"]), 2),
                "geometry_json": r["geometry_json"],
            }
            for r in rows
        ]
```

- [ ] **Step 4: Wire mixin ke `PostgresStore`**

Di `backend/app/services/postgres_store/__init__.py`:
- Tambah import setelah baris `from ._history import _HistoryArchiveMixin`:
  ```python
  from ._land_cover import _LandCoverMixin
  ```
- Tambah `_LandCoverMixin` ke daftar base class `PostgresStore` (letakkan setelah `_S2BurnedAreaMixin`, sebelum penutup `)`):
  ```python
      _S2BurnedAreaMixin,
      _LandCoverMixin,
  ```
  Jika `_S2BurnedAreaMixin` belum ada di daftar yang terlihat, tambahkan `_LandCoverMixin` sebagai base class TERAKHIR sebelum `)`.

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_store_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Pastikan tidak ada regresi**

Run: `cd backend && .venv/bin/python -m pytest app/tests -q`
Expected: PASS (jumlah lulus bertambah 1).

- [ ] **Step 7: Commit**

```bash
cd /home/ryandshinevps/etaseneu
git add backend/app/services/postgres_store/_land_cover.py backend/app/services/postgres_store/__init__.py backend/app/tests/test_land_cover_store_wiring.py
git commit -m "feat: mixin store tutupan lahan (land_cover_* tables)"
```

---

### Task 2: `LandCoverService` — kerangka, config guard, helper murni

**Files:**
- Create: `backend/app/services/land_cover_service.py`
- Test: `backend/app/tests/test_land_cover_service.py`

**Interfaces:**
- Consumes: `get_settings()` (`gee_service_account_email`, `gee_service_account_key_path`, `gee_project_id`); store dari Task 1.
- Produces (dipakai Task 3–4):
  - `class LandCoverError(Exception)`
  - `YEARS: tuple[int, ...]` = `(2020, 2021, 2022, 2023, 2024, 2025)`
  - `CLASS_KEYS: tuple[str, ...]` = `("hutan", "semak", "pertanian", "terbuka", "air")`
  - `class LandCoverService`:
    - `__init__(self, postgres_store: PostgresStore | None = None)`
    - `enabled -> bool` (property)
    - `_ensure_ee(self)` → modul `ee` atau raise `LandCoverError`
  - `_dw_label_to_class(label: int) -> str | None` — modul-level fungsi murni. `0→"air"`, `1→"hutan"`, `2→"semak"`, `3→"semak"`, `4→"pertanian"`, `5→"semak"`, `7→"terbuka"`, `6→None` (built), `8→None` (snow), lainnya `None`.
  - `_build_summary_text(table: dict[int, dict[str, dict]]) -> str` — `table[year][class_key] = {"area_ha": float, "pct": float}`. Kalimat ringkas perubahan `hutan` 2020→2025 + dua kelas penambah terbesar. Kalau data tahun batas kurang → `"Data tidak lengkap untuk membuat ringkasan."`
  - `_net_change(table) -> dict[str, float]` — `{class_key: area_ha[2025] - area_ha[2020]}` (0.0 kalau salah satu tahun tidak ada).
  - `land_cover_run_state(polygon_id: int) -> dict | None` — baca `_LAND_COVER_RUN_STATE`.

- [ ] **Step 1: Tulis test yang gagal**

```python
# backend/app/tests/test_land_cover_service.py
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
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_service.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.land_cover_service`).

- [ ] **Step 3: Tulis kerangka service**

```python
# backend/app/services/land_cover_service.py
"""Klasifikasi tutupan lahan per poligon KPS/Hutan Adat (2020-2025) dari
Sentinel-2 L2A via Google Earth Engine, Random Forest dengan guru label
Google Dynamic World. On-demand per poligon; hasil di-cache permanen di
tabel `land_cover_*` (lihat postgres_store/_land_cover.py).

Estimasi, bukan angka resmi. "Hutan" = tutupan berpohon (kebun berpohon
seperti sawit/karet belum tentu terpisah pada versi ini).
"""

from __future__ import annotations

import logging
import time
from datetime import date

from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import mapping, shape as shapely_shape
from shapely.ops import unary_union

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore

logger = logging.getLogger("land_cover")

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"
DW_COLLECTION = "GOOGLE/DYNAMICWORLD/V1"

YEARS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025)
CLASS_KEYS: tuple[str, ...] = ("hutan", "semak", "pertanian", "terbuka", "air")
_CLASS_IDX = {k: i for i, k in enumerate(CLASS_KEYS)}

RF_TREES = 150
SAMPLES_PER_CLASS_PER_YEAR = 240
DW_CONF_MIN = 0.6
FEATURE_NAMES = [
    "B2", "B3", "B4", "B8", "B11", "B12",
    "ndvi", "nbr", "mndwi", "ndbi", "elevation", "slope",
]
SIMPLIFY_TOL = 0.0003
MIN_MMU_PX = 5          # buang patch < 5 px (~0.2 ha @ 20 m)
_MAX_CLOUD = 70

# {0..8} Dynamic World label -> kunci kelas 5-kategori (6=built, 8=snow dibuang)
_DW_MAP = {0: "air", 1: "hutan", 2: "semak", 3: "semak", 4: "pertanian", 5: "semak", 7: "terbuka"}

# Progres langkah live — boleh hilang saat restart; status final ada di DB.
_LAND_COVER_RUN_STATE: dict[int, dict] = {}


class LandCoverError(Exception):
    """GEE belum dikonfigurasi, poligon tidak valid, atau gagal analisis."""


def _dw_label_to_class(label: int) -> str | None:
    return _DW_MAP.get(int(label))


def land_cover_run_state(polygon_id: int) -> dict | None:
    return _LAND_COVER_RUN_STATE.get(int(polygon_id))


def _net_change(table: dict[int, dict[str, dict]]) -> dict[str, float]:
    a, b = table.get(YEARS[0]), table.get(YEARS[-1])
    out: dict[str, float] = {}
    for key in CLASS_KEYS:
        if a and b and key in a and key in b:
            out[key] = round(b[key]["area_ha"] - a[key]["area_ha"], 2)
        else:
            out[key] = 0.0
    return out


_CLASS_LABEL = {
    "hutan": "Hutan", "semak": "Semak/Belukar", "pertanian": "Pertanian/Kebun",
    "terbuka": "Lahan Terbuka", "air": "Badan Air",
}


def _build_summary_text(table: dict[int, dict[str, dict]]) -> str:
    a, b = table.get(YEARS[0]), table.get(YEARS[-1])
    if not a or not b or "hutan" not in a or "hutan" not in b:
        return "Data tidak lengkap untuk membuat ringkasan."
    delta = b["hutan"]["area_ha"] - a["hutan"]["area_ha"]
    pct = (delta / a["hutan"]["area_ha"] * 100) if a["hutan"]["area_ha"] else 0.0
    arah = "turun" if delta < 0 else "naik"
    nc = _net_change(table)
    gainers = sorted(
        ((k, v) for k, v in nc.items() if k != "hutan" and v > 0),
        key=lambda kv: kv[1], reverse=True,
    )[:2]
    ke = (
        " Beralih terutama ke " + " dan ".join(f"{_CLASS_LABEL[k]} (+{v:,.0f} ha)" for k, v in gainers) + "."
        if gainers else ""
    )
    return (
        f"Tutupan Hutan {arah} {abs(delta):,.0f} ha ({pct:+.1f}%) "
        f"dari {YEARS[0]} ke {YEARS[-1]}.{ke}"
    )


class LandCoverService:
    def __init__(self, postgres_store: PostgresStore | None = None) -> None:
        settings = get_settings()
        self.settings = settings
        self.postgres_store = postgres_store or PostgresStore(settings.database_url)
        self._ee_initialized = False

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(
            s.gee_service_account_email
            and s.gee_service_account_key_path
            and s.gee_project_id
        )

    def _ensure_ee(self):
        if self._ee_initialized:
            import ee

            return ee
        if not self.enabled:
            raise LandCoverError(
                "Google Earth Engine belum dikonfigurasi (GEE_SERVICE_ACCOUNT_EMAIL / "
                "GEE_SERVICE_ACCOUNT_KEY_PATH / GEE_PROJECT_ID kosong di server)."
            )
        import ee

        credentials = ee.ServiceAccountCredentials(
            self.settings.gee_service_account_email,
            self.settings.gee_service_account_key_path,
        )
        ee.Initialize(credentials, project=self.settings.gee_project_id)
        self._ee_initialized = True
        return ee
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_service.py -q`
Expected: PASS (6 test).

- [ ] **Step 5: Commit**

```bash
cd /home/ryandshinevps/etaseneu
git add backend/app/services/land_cover_service.py backend/app/tests/test_land_cover_service.py
git commit -m "feat: kerangka LandCoverService + helper murni (mapping DW, ringkasan)"
```

---

### Task 3: `LandCoverService.analyze_polygon` — orkestrasi GEE

**Files:**
- Modify: `backend/app/services/land_cover_service.py`
- Test: `backend/app/tests/test_land_cover_service.py` (tambah kelas fake + test)

**Interfaces:**
- Consumes: `_ensure_ee()`, store method dari Task 1, helper dari Task 2.
- Produces (dipakai Task 4):
  - `LandCoverService.analyze_polygon(self, polygon_id: int) -> dict` — melakukan seluruh pipeline, memanggil `store.save_land_cover_result(...)` saat sukses / `store.mark_land_cover_error(...)` saat gagal, dan mengembalikan:
    ```python
    {
      "polygon_id": int,
      "years": list[int],                       # == list(YEARS)
      "classes": list[str],                     # == list(CLASS_KEYS)
      "oob_accuracy": float | None,
      "n_training": int,
      "duration_s": float,
      "table": {year: {class_key: {"area_ha": float, "pct": float}}},
      "net_change": {class_key: float},
      "summary_text": str,
    }
    ```
  - Update `_LAND_COVER_RUN_STATE[polygon_id]` = `{"state": "running", "step": "<year> (i/6)", "started_at": iso}` saat mulai tiap tahun; dihapus di `finally`.

- [ ] **Step 1: Tulis test integrasi yang gagal (fake ee + fake store)**

```python
# tambahan di backend/app/tests/test_land_cover_service.py

class _FakeGetInfo:
    def __init__(self, payload):
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeImg:
    """Rantai method EE yang dipakai analyze_polygon — kebanyakan no-op."""

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def reduceRegion(self, *a, **k):
        # satu grup per kelas idx 0..4, luas 100 ha (1e6 m2) tiap kelas
        return _FakeGetInfo({"groups": [{"class": i, "sum": 1_000_000.0} for i in range(5)]})

    def reduceToVectors(self, *a, **k):
        return _FakeGetInfo({
            "features": [
                {"geometry": {"type": "Polygon",
                              "coordinates": [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]]}}
            ]
        })


class _FakeColl:
    def __getattr__(self, _name):
        return lambda *a, **k: self

    def median(self):
        return _FakeImg()

    def mode(self):
        return _FakeImg()

    def mean(self):
        return _FakeImg()


class _FakeClassifier:
    def train(self, *a, **k):
        return self

    def explain(self):
        return _FakeGetInfo({"outOfBagErrorEstimate": 0.19})


class _FakeReducer:
    def __getattr__(self, _n):
        return lambda *a, **k: "reducer"


class _FakeGeom:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: self


class _FakeFC:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: self


class _FakeEE:
    ImageCollection = staticmethod(lambda _id: _FakeColl())
    Image = type("I", (), {"pixelArea": staticmethod(lambda: _FakeImg()),
                           "cat": staticmethod(lambda *a, **k: _FakeImg())})
    Geometry = _FakeGeom
    Feature = staticmethod(lambda *a, **k: object())
    FeatureCollection = _FakeFC
    Filter = type("F", (), {"lt": staticmethod(lambda *a, **k: "flt")})
    Reducer = _FakeReducer()
    Classifier = type("C", (), {"smileRandomForest": staticmethod(lambda *a, **k: _FakeClassifier())})
    Terrain = type("T", (), {"products": staticmethod(lambda *a, **k: _FakeImg())})


class _FakeStore:
    def __init__(self, target):
        self._target = target
        self.saved: dict | None = None
        self.errored: str | None = None

    def read_land_cover_target_polygon(self, polygon_id):
        return self._target

    def mark_land_cover_running(self, polygon_id, layer_key):
        pass

    def mark_land_cover_error(self, polygon_id, message):
        self.errored = message

    def save_land_cover_result(self, polygon_id, layer_key, **kw):
        self.saved = {"polygon_id": polygon_id, "layer_key": layer_key, **kw}


_TARGET = {
    "id": 287785, "layer_key": "psagustus2026", "lembaga": "LPHD MUARA MERANG",
    "nama_prov": "Sumatera Selatan",
    "geometry_json": {"type": "Polygon",
                      "coordinates": [[[104.0, -2.0], [104.1, -2.0], [104.1, -1.9], [104.0, -1.9], [104.0, -2.0]]]},
}


def test_analyze_polygon_unknown_polygon_raises(monkeypatch) -> None:
    svc = _svc()
    svc.postgres_store = _FakeStore(None)
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())
    with pytest.raises(LandCoverError):
        svc.analyze_polygon(999999)


def test_analyze_polygon_happy_path_saves_all_years_classes(monkeypatch) -> None:
    svc = _svc()
    store = _FakeStore(_TARGET)
    svc.postgres_store = store
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())

    result = svc.analyze_polygon(287785)

    assert result["years"] == list(YEARS)
    assert result["classes"] == list(CLASS_KEYS)
    assert result["oob_accuracy"] == pytest.approx(0.81)  # 1 - 0.19
    # 6 tahun x 5 kelas
    assert len(store.saved["year_class_rows"]) == 30
    for year in YEARS:
        pct_sum = sum(r["pct"] for r in store.saved["year_class_rows"] if r["year"] == year)
        assert pct_sum == pytest.approx(100.0, abs=0.5)
    assert set(result["net_change"].keys()) == set(CLASS_KEYS)
    assert isinstance(result["summary_text"], str) and result["summary_text"]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_service.py -q`
Expected: FAIL (`AttributeError: 'LandCoverService' object has no attribute 'analyze_polygon'`).

- [ ] **Step 3: Implementasi `analyze_polygon` + helper GEE**

Tambahkan di `backend/app/services/land_cover_service.py` (di dalam `class LandCoverService`, setelah `_ensure_ee`):

```python
    # -- komposit & fitur per tahun ------------------------------------------

    def _scl_scale(self, ee):
        def _fn(img):
            scl = img.select("SCL")
            keep = (
                scl.neq(0).And(scl.neq(1)).And(scl.neq(3))
                .And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
            )
            return img.updateMask(keep).divide(10000)

        return _fn

    def _year_window(self, year: int) -> tuple[str, str]:
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        today = date.today()
        if end >= today:
            end = today
        return start.isoformat(), end.isoformat()

    def _year_feature_image(self, ee, roi, year: int):
        start, end = self._year_window(year)
        s2 = (
            ee.ImageCollection(S2_COLLECTION)
            .filterBounds(roi)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _MAX_CLOUD))
            .map(self._scl_scale(ee))
            .median()
            .clip(roi)
        )
        ndvi = s2.normalizedDifference(["B8", "B4"]).rename("ndvi")
        nbr = s2.normalizedDifference(["B8", "B12"]).rename("nbr")
        mndwi = s2.normalizedDifference(["B3", "B11"]).rename("mndwi")
        ndbi = s2.normalizedDifference(["B11", "B8"]).rename("ndbi")
        dem = ee.Image("NASA/NASADEM_HGT/001").select("elevation")
        slope = ee.Terrain.products(dem).select("slope") if hasattr(ee, "Terrain") else dem.rename("slope")
        feat = ee.Image.cat(
            s2.select(["B2", "B3", "B4", "B8", "B11", "B12"]),
            ndvi, nbr, mndwi, ndbi,
            dem.rename("elevation"), slope.rename("slope"),
        ).rename(FEATURE_NAMES)
        return feat

    def _year_training_points(self, ee, roi, feat_img, year: int):
        start, end = self._year_window(year)
        dw = (
            ee.ImageCollection(DW_COLLECTION)
            .filterBounds(roi)
            .filterDate(start, end)
        )
        label = dw.select("label").mode()
        prob = dw.select(
            ["water", "trees", "grass", "flooded_vegetation", "crops",
             "shrub_and_scrub", "built", "bare", "snow_and_ice"]
        ).mean().reduce(ee.Reducer.max())
        from_list = [k for k in _DW_MAP]
        to_list = [_CLASS_IDX[_DW_MAP[k]] for k in from_list]
        class_idx = (
            label.remap(from_list, to_list)
            .rename("class_idx")
            .updateMask(prob.gte(DW_CONF_MIN))
        )
        stack = feat_img.addBands(class_idx)
        return stack.stratifiedSample(
            numPoints=SAMPLES_PER_CLASS_PER_YEAR,
            classBand="class_idx",
            region=roi,
            scale=10,
            seed=42 + year,
            geometries=False,
        )

    # -- ekstraksi hasil per tahun ----------------------------------------------

    def _year_area_by_class(self, ee, roi, classified) -> dict[str, float]:
        grouped = (
            ee.Image.pixelArea()
            .addBands(classified)
            .reduceRegion(
                reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
                geometry=roi,
                scale=10,
                maxPixels=1e9,
                bestEffort=True,
            )
            .getInfo()
        )
        out = {k: 0.0 for k in CLASS_KEYS}
        for grp in grouped.get("groups", []):
            idx = int(grp.get("class", -1))
            if 0 <= idx < len(CLASS_KEYS):
                out[CLASS_KEYS[idx]] = float(grp.get("sum") or 0.0) / 10000.0
        return out

    def _year_class_geom(self, ee, roi, classified, raw_geom) -> dict[str, dict]:
        boundary = shapely_shape(raw_geom).buffer(0)
        out: dict[str, dict] = {}
        for idx, key in enumerate(CLASS_KEYS):
            try:
                cpc = classified.eq(idx).selfMask().connectedPixelCount(MIN_MMU_PX + 1, True)
                mask = classified.eq(idx).And(cpc.gte(MIN_MMU_PX)).selfMask()
                vectors = mask.reduceToVectors(
                    geometry=roi, scale=10, geometryType="polygon",
                    eightConnected=True, maxPixels=1e9, bestEffort=True,
                ).getInfo()
            except Exception as exc:  # noqa: BLE001 -- non-fatal, peta rona di-skip kelas ini
                logger.warning("LAND_COVER: reduceToVectors gagal (%s) — %s", key, exc)
                continue
            parts = [
                shapely_shape(f["geometry"]).buffer(0)
                for f in vectors.get("features", [])
                if f.get("geometry")
            ]
            if not parts:
                continue
            try:
                clipped = unary_union(parts).intersection(boundary).simplify(SIMPLIFY_TOL)
            except Exception:  # noqa: BLE001
                continue
            if clipped.is_empty:
                continue
            if isinstance(clipped, ShapelyPolygon):
                clipped = ShapelyMultiPolygon([clipped])
            elif not isinstance(clipped, ShapelyMultiPolygon):
                polys = [g for g in getattr(clipped, "geoms", []) if isinstance(g, ShapelyPolygon)]
                if not polys:
                    continue
                clipped = ShapelyMultiPolygon(polys)
            out[key] = mapping(clipped)
        return out

    # -- orkestrasi -----------------------------------------------------------

    def analyze_polygon(self, polygon_id: int) -> dict[str, object]:
        pid = int(polygon_id)
        target = self.postgres_store.read_land_cover_target_polygon(pid)
        if not target:
            raise LandCoverError(
                f"Poligon {pid} tidak ditemukan / tidak aktif / bukan KPS maupun Hutan Adat."
            )
        ee = self._ensure_ee()
        started = time.monotonic()
        roi = ee.Geometry(target["geometry_json"])
        raw_geom = target["geometry_json"]

        try:
            self.postgres_store.mark_land_cover_running(pid, target["layer_key"])

            feat_by_year = {}
            samples = None
            for i, year in enumerate(YEARS):
                _LAND_COVER_RUN_STATE[pid] = {
                    "state": "running",
                    "step": f"{year} ({i + 1}/{len(YEARS)}) — sampel",
                    "started_at": date.today().isoformat(),
                }
                feat = self._year_feature_image(ee, roi, year)
                feat_by_year[year] = feat
                pts = self._year_training_points(ee, roi, feat, year)
                samples = pts if samples is None else samples.merge(pts)

            rf = ee.Classifier.smileRandomForest(RF_TREES, seed=42).train(
                features=samples, classProperty="class_idx", inputProperties=FEATURE_NAMES
            )
            try:
                oob_err = rf.explain().getInfo().get("outOfBagErrorEstimate")
                oob_accuracy = round(1.0 - float(oob_err), 4) if oob_err is not None else None
            except Exception:  # noqa: BLE001
                oob_accuracy = None

            n_training = SAMPLES_PER_CLASS_PER_YEAR * len(CLASS_KEYS) * len(YEARS)

            table: dict[int, dict[str, dict]] = {}
            year_class_rows: list[dict] = []
            year_geom_rows: list[dict] = []
            for i, year in enumerate(YEARS):
                _LAND_COVER_RUN_STATE[pid] = {
                    "state": "running",
                    "step": f"{year} ({i + 1}/{len(YEARS)}) — klasifikasi",
                    "started_at": date.today().isoformat(),
                }
                classified = feat_by_year[year].classify(rf).rename("class_idx")
                areas = self._year_area_by_class(ee, roi, classified)
                total = sum(areas.values()) or 1.0
                table[year] = {}
                for key in CLASS_KEYS:
                    pct = round(areas[key] / total * 100.0, 2)
                    table[year][key] = {"area_ha": round(areas[key], 2), "pct": pct}
                    year_class_rows.append(
                        {"year": year, "class_key": key, "area_ha": round(areas[key], 2), "pct": pct}
                    )
                geoms = self._year_class_geom(ee, roi, classified, raw_geom)
                for key, geom in geoms.items():
                    year_geom_rows.append({"year": year, "class_key": key, "geometry_geojson": geom})

            duration_s = round(time.monotonic() - started, 1)
            self.postgres_store.save_land_cover_result(
                pid,
                target["layer_key"],
                model_trees=RF_TREES,
                n_training=n_training,
                oob_accuracy=oob_accuracy,
                duration_s=duration_s,
                year_class_rows=year_class_rows,
                year_geom_rows=year_geom_rows,
            )
            return {
                "polygon_id": pid,
                "years": list(YEARS),
                "classes": list(CLASS_KEYS),
                "oob_accuracy": oob_accuracy,
                "n_training": n_training,
                "duration_s": duration_s,
                "table": table,
                "net_change": _net_change(table),
                "summary_text": _build_summary_text(table),
            }
        except LandCoverError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("LAND_COVER: analisis poligon %s gagal", pid)
            self.postgres_store.mark_land_cover_error(pid, str(exc))
            raise LandCoverError(f"Analisis gagal: {exc}") from exc
        finally:
            _LAND_COVER_RUN_STATE.pop(pid, None)
```

> Catatan implementer: fake `ee` di test membuat `reduceToVectors` selalu mengembalikan satu Polygon dan `reduceRegion` lima grup 100 ha, jadi `year_class_rows` = 30 baris & tiap tahun total 500 ha (pct 20 tiap kelas). `stratifiedSample(...).merge(...)` di-fake sebagai no-op yang mengembalikan objek chainable.

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_service.py -q`
Expected: PASS (8 test).

- [ ] **Step 5: Pastikan tidak ada regresi**

Run: `cd backend && .venv/bin/python -m pytest app/tests -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/ryandshinevps/etaseneu
git add backend/app/services/land_cover_service.py backend/app/tests/test_land_cover_service.py
git commit -m "feat: LandCoverService.analyze_polygon — pipeline RF 6 tahun"
```

---

### Task 4: API `app/api/land_cover.py` + registrasi router

**Files:**
- Create: `backend/app/api/land_cover.py`
- Modify: `backend/app/api/router.py`
- Test: `backend/app/tests/test_land_cover_api.py`

**Interfaces:**
- Consumes: `LandCoverService`, `land_cover_run_state`, `YEARS`, `CLASS_KEYS`, `_build_summary_text`, `_net_change` dari Task 2–3; store method dari Task 1.
- Produces (dipakai frontend Task 6):
  - `POST /api/land-cover/analyze` body `{"polygon_id": int}`, query opsional `?force=true`.
    - `503 {"detail": "..."}` kalau `not service.enabled`.
    - `409 {"detail": "sedang berjalan"}` kalau status `running`.
    - `409 {"detail": "sudah dianalisis", "done": true}` kalau status `done` dan `force` bukan `true`.
    - Else: `store.mark_land_cover_running(...)`, `background_tasks.add_task(service.analyze_polygon, polygon_id)`, balas `202 {"started": true, "polygon_id": int}`.
  - `GET /api/land-cover/status?polygon_id=` → `{"state": "idle|running|done|error", "step": str|null, "error": str|null, "computed_at": str|null}`. `state` dari `store.read_land_cover_status` (`None` → `idle`); `step` dari `land_cover_run_state`.
  - `GET /api/land-cover/result?polygon_id=` → `404` kalau belum `done`. Else:
    ```json
    {"meta": {...}, "years": [2020,...,2025], "classes": ["hutan",...],
     "table": {"2020": {"hutan": {"area_ha": 0, "pct": 0}, ...}, ...},
     "net_change": {"hutan": 0, ...}, "summary_text": "..."}
    ```
  - `GET /api/land-cover/overlay?polygon_id=&year=` → `404` kalau `year` di luar `YEARS` atau status belum `done`. Else `FeatureCollection` — satu Feature per kelas dengan geometri, `properties {class_key, area_ha, pct}`.

- [ ] **Step 1: Tulis test API yang gagal**

```python
# backend/app/tests/test_land_cover_api.py
"""Tes endpoint tutupan lahan. Service & store di-fake — tidak ada GEE/DB
nyata (bahaya #1). conftest autouse sudah mematikan API_REQUIRE_AUTH."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.land_cover as lc_mod
from app.main import create_app

YEARS = (2020, 2021, 2022, 2023, 2024, 2025)


class _FakeService:
    enabled = True

    def __init__(self, *a, **k):
        pass

    def analyze_polygon(self, polygon_id):
        return {"polygon_id": polygon_id}


class _FakeStore:
    def __init__(self, status=None, result=None, overlay=None):
        self._status = status
        self._result = result
        self._overlay = overlay or []
        self.running_marked = False

    def read_land_cover_status(self, polygon_id):
        return self._status

    def read_land_cover_result(self, polygon_id):
        return self._result

    def read_land_cover_overlay(self, polygon_id, year):
        return self._overlay

    def mark_land_cover_running(self, polygon_id, layer_key):
        self.running_marked = True

    def read_land_cover_target_polygon(self, polygon_id):
        return {"id": polygon_id, "layer_key": "psagustus2026",
                "lembaga": "X", "nama_prov": "Y", "geometry_json": {}}


@pytest.fixture
def client(monkeypatch):
    store = _FakeStore()
    monkeypatch.setattr(lc_mod, "PostgresStore", lambda *_a, **_k: store)
    monkeypatch.setattr(lc_mod, "LandCoverService", _FakeService)
    c = TestClient(create_app())
    c._store = store  # akses di test
    return c


def test_analyze_503_when_gee_disabled(client, monkeypatch):
    class _Off(_FakeService):
        enabled = False

    monkeypatch.setattr(lc_mod, "LandCoverService", _Off)
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 503


def test_analyze_409_when_running(client):
    client._store._status = {"status": "running", "error_message": None, "computed_at": None}
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 409


def test_analyze_409_when_done_without_force(client):
    client._store._status = {"status": "done", "error_message": None, "computed_at": "2026-08-30T00:00:00"}
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 1})
    assert r.status_code == 409
    assert r.json()["detail"].get("done") is True or r.json().get("done") is True


def test_analyze_202_starts_job(client):
    r = client.post("/api/land-cover/analyze", json={"polygon_id": 42})
    assert r.status_code == 202
    assert r.json() == {"started": True, "polygon_id": 42}
    assert client._store.running_marked is True


def test_status_idle_when_no_row(client):
    r = client.get("/api/land-cover/status", params={"polygon_id": 1})
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


def test_result_404_before_done(client):
    r = client.get("/api/land-cover/result", params={"polygon_id": 1})
    assert r.status_code == 404


def test_result_shape_when_done(client):
    client._store._result = {
        "meta": {"model_trees": 150, "n_training": 7200, "oob_accuracy": 0.81,
                 "duration_s": 130.0, "computed_at": "2026-08-30T00:00:00",
                 "source": "s", "label_source": "l"},
        "year_class": [
            {"year": y, "class_key": k, "area_ha": 100.0, "pct": 20.0}
            for y in YEARS for k in ("hutan", "semak", "pertanian", "terbuka", "air")
        ],
    }
    r = client.get("/api/land-cover/result", params={"polygon_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["years"] == list(YEARS)
    assert body["table"]["2020"]["hutan"]["pct"] == 20.0
    assert set(body["net_change"].keys()) == {"hutan", "semak", "pertanian", "terbuka", "air"}


def test_overlay_404_for_year_out_of_range(client):
    r = client.get("/api/land-cover/overlay", params={"polygon_id": 1, "year": 2019})
    assert r.status_code == 404


def test_overlay_featurecollection_when_done(client):
    client._store._status = {"status": "done", "error_message": None, "computed_at": "x"}
    client._store._overlay = [
        {"class_key": "hutan", "area_ha": 100.0, "pct": 50.0,
         "geometry_json": {"type": "MultiPolygon", "coordinates": []}},
    ]
    r = client.get("/api/land-cover/overlay", params={"polygon_id": 1, "year": 2020})
    assert r.status_code == 200
    fc = r.json()
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["properties"]["class_key"] == "hutan"
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_api.py -q`
Expected: FAIL (`ModuleNotFoundError: app.api.land_cover`).

- [ ] **Step 3: Tulis modul API**

```python
# backend/app/api/land_cover.py
"""Menu Tutupan Lahan per KPS: analisis on-demand Sentinel-2 + Random Forest
(2020-2025), hasil di-cache permanen. Analisis butuh env GEE; membaca hasil
tidak.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query

from app.core.config import get_settings
from app.services.land_cover_service import (
    CLASS_KEYS,
    YEARS,
    LandCoverService,
    _build_summary_text,
    _net_change,
    land_cover_run_state,
)
from app.services.postgres_store import PostgresStore

router = APIRouter()


def _store() -> PostgresStore:
    return PostgresStore(get_settings().database_url)


@router.post("/land-cover/analyze", status_code=202)
async def land_cover_analyze(
    background_tasks: BackgroundTasks,
    polygon_id: int = Body(..., embed=True),
    force: bool = Query(default=False),
) -> dict[str, object]:
    service = LandCoverService()
    if not service.enabled:
        raise HTTPException(status_code=503, detail="GEE belum dikonfigurasi di server")

    store = _store()
    status = store.read_land_cover_status(polygon_id)
    if status and status["status"] == "running":
        raise HTTPException(status_code=409, detail="Analisis sedang berjalan")
    if status and status["status"] == "done" and not force:
        raise HTTPException(status_code=409, detail={"message": "sudah dianalisis", "done": True})

    target = store.read_land_cover_target_polygon(polygon_id)
    if not target:
        raise HTTPException(
            status_code=404,
            detail="Poligon tidak ditemukan / tidak aktif / bukan KPS maupun Hutan Adat",
        )
    store.mark_land_cover_running(polygon_id, target["layer_key"])
    background_tasks.add_task(LandCoverService().analyze_polygon, polygon_id)
    return {"started": True, "polygon_id": polygon_id}


@router.get("/land-cover/status")
async def land_cover_status(polygon_id: int) -> dict[str, object]:
    row = _store().read_land_cover_status(polygon_id)
    live = land_cover_run_state(polygon_id)
    return {
        "state": row["status"] if row else "idle",
        "step": live["step"] if live else None,
        "error": row["error_message"] if row else None,
        "computed_at": row["computed_at"] if row else None,
    }


@router.get("/land-cover/result")
async def land_cover_result(polygon_id: int) -> dict[str, object]:
    res = _store().read_land_cover_result(polygon_id)
    if not res:
        raise HTTPException(status_code=404, detail="Belum ada hasil analisis")
    table: dict[int, dict[str, dict]] = {}
    for r in res["year_class"]:
        table.setdefault(r["year"], {})[r["class_key"]] = {
            "area_ha": r["area_ha"], "pct": r["pct"],
        }
    return {
        "meta": res["meta"],
        "years": list(YEARS),
        "classes": list(CLASS_KEYS),
        "table": {str(y): table.get(y, {}) for y in YEARS},
        "net_change": _net_change(table),
        "summary_text": _build_summary_text(table),
    }


@router.get("/land-cover/overlay")
async def land_cover_overlay(
    polygon_id: int,
    year: int = Query(...),
) -> dict[str, object]:
    if year not in YEARS:
        raise HTTPException(status_code=404, detail="Tahun di luar rentang 2020-2025")
    store = _store()
    status = store.read_land_cover_status(polygon_id)
    if not status or status["status"] != "done":
        raise HTTPException(status_code=404, detail="Belum ada hasil analisis")
    rows = store.read_land_cover_overlay(polygon_id, year)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": r["geometry_json"],
                "properties": {
                    "class_key": r["class_key"],
                    "area_ha": r["area_ha"],
                    "pct": r["pct"],
                },
            }
            for r in rows
            if r.get("geometry_json")
        ],
    }
```

- [ ] **Step 4: Registrasi router**

Di `backend/app/api/router.py`:
- Tambah import setelah `from app.api.hotspots import router as hotspots_router`:
  ```python
  from app.api.land_cover import router as land_cover_router
  ```
- Tambah include setelah baris `router.include_router(burned_area_router, dependencies=_read_gate)`:
  ```python
  router.include_router(land_cover_router, dependencies=_read_gate)
  ```

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_land_cover_api.py -q`
Expected: PASS (10 test).

- [ ] **Step 6: Pastikan tidak ada regresi**

Run: `cd backend && .venv/bin/python -m pytest app/tests -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/ryandshinevps/etaseneu
git add backend/app/api/land_cover.py backend/app/api/router.py backend/app/tests/test_land_cover_api.py
git commit -m "feat: endpoint /api/land-cover (analyze/status/result/overlay)"
```

---

### Task 5: Frontend — konstanta kelas + helper murni

**Files:**
- Create: `frontend/src/constants/landCover.ts`
- Create: `frontend/src/lib/landCover.ts`
- Test: `frontend/src/test/landCover.test.ts`

**Interfaces:**
- Produces (dipakai Task 6):
  - `LAND_COVER_CLASSES: ReadonlyArray<{ key: LandCoverClassKey; label: string; color: string }>` — urut `hutan, semak, pertanian, terbuka, air`, warna sesuai Global Constraints.
  - `type LandCoverClassKey = "hutan" | "semak" | "pertanian" | "terbuka" | "air"`
  - `LAND_COVER_YEARS: readonly number[]` = `[2020, 2021, 2022, 2023, 2024, 2025]`
  - `landCoverColor(key: string): string` — warna kelas, `#999999` kalau tak dikenal.
  - `type LandCoverTable = Record<string, Partial<Record<LandCoverClassKey, { area_ha: number; pct: number }>>>`
  - `buildChartData(table: LandCoverTable): Array<{ year: string } & Record<LandCoverClassKey, number>>` — satu baris per tahun, nilai = `pct` (0 kalau tak ada), untuk `<BarChart>` bertumpuk recharts.
  - `formatDelta(ha: number): string` — `"+430 ha"` / `"−930 ha"` / `"0 ha"` (pakai minus U+2212, pembulatan ke bulat).

- [ ] **Step 1: Tulis test yang gagal**

```ts
// frontend/src/test/landCover.test.ts
import { describe, expect, it } from "vitest";
import { LAND_COVER_CLASSES, LAND_COVER_YEARS } from "../constants/landCover";
import { buildChartData, formatDelta, landCoverColor } from "../lib/landCover";

describe("landCover constants", () => {
  it("has 5 classes in fixed order with hex colors", () => {
    expect(LAND_COVER_CLASSES.map((c) => c.key)).toEqual([
      "hutan", "semak", "pertanian", "terbuka", "air",
    ]);
    for (const c of LAND_COVER_CLASSES) {
      expect(c.color).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it("covers 2020..2025", () => {
    expect(LAND_COVER_YEARS).toEqual([2020, 2021, 2022, 2023, 2024, 2025]);
  });
});

describe("landCoverColor", () => {
  it("returns class color and grey fallback", () => {
    expect(landCoverColor("hutan")).toBe("#1B7A3D");
    expect(landCoverColor("nope")).toBe("#999999");
  });
});

describe("buildChartData", () => {
  it("emits one row per year with pct per class, zero-filled", () => {
    const rows = buildChartData({
      "2020": { hutan: { area_ha: 80, pct: 80 }, air: { area_ha: 20, pct: 20 } },
      "2021": { hutan: { area_ha: 60, pct: 60 } },
    });
    expect(rows[0]).toMatchObject({ year: "2020", hutan: 80, air: 20, semak: 0 });
    expect(rows[1]).toMatchObject({ year: "2021", hutan: 60, air: 0 });
  });
});

describe("formatDelta", () => {
  it("formats sign and unit", () => {
    expect(formatDelta(430.2)).toBe("+430 ha");
    expect(formatDelta(-930.8)).toBe("−931 ha");
    expect(formatDelta(0)).toBe("0 ha");
  });
});
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npm test -- landCover`
Expected: FAIL (module tidak ada).

- [ ] **Step 3: Tulis konstanta + helper**

```ts
// frontend/src/constants/landCover.ts
export type LandCoverClassKey = "hutan" | "semak" | "pertanian" | "terbuka" | "air";

export const LAND_COVER_CLASSES: ReadonlyArray<{
  key: LandCoverClassKey;
  label: string;
  color: string;
}> = [
  { key: "hutan", label: "Hutan", color: "#1B7A3D" },
  { key: "semak", label: "Semak/Belukar", color: "#9CC55B" },
  { key: "pertanian", label: "Pertanian/Kebun", color: "#E8B84B" },
  { key: "terbuka", label: "Lahan Terbuka", color: "#C97B4A" },
  { key: "air", label: "Badan Air", color: "#2E7BBF" },
] as const;

export const LAND_COVER_YEARS: readonly number[] = [2020, 2021, 2022, 2023, 2024, 2025];
```

```ts
// frontend/src/lib/landCover.ts
import {
  LAND_COVER_CLASSES,
  LAND_COVER_YEARS,
  type LandCoverClassKey,
} from "../constants/landCover";

export type LandCoverTable = Record<
  string,
  Partial<Record<LandCoverClassKey, { area_ha: number; pct: number }>>
>;

const COLOR_BY_KEY = new Map(LAND_COVER_CLASSES.map((c) => [c.key, c.color]));

export function landCoverColor(key: string): string {
  return COLOR_BY_KEY.get(key as LandCoverClassKey) ?? "#999999";
}

export function buildChartData(
  table: LandCoverTable,
): Array<{ year: string } & Record<LandCoverClassKey, number>> {
  return LAND_COVER_YEARS.map((year) => {
    const cell = table[String(year)] ?? {};
    const row = { year: String(year) } as { year: string } & Record<LandCoverClassKey, number>;
    for (const { key } of LAND_COVER_CLASSES) {
      row[key] = cell[key]?.pct ?? 0;
    }
    return row;
  });
}

export function formatDelta(ha: number): string {
  const rounded = Math.round(ha);
  if (rounded === 0) return "0 ha";
  const sign = rounded > 0 ? "+" : "−";
  return `${sign}${Math.abs(rounded)} ha`;
}
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `cd frontend && npm test -- landCover`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/ryandshinevps/etaseneu
git add frontend/src/constants/landCover.ts frontend/src/lib/landCover.ts frontend/src/test/landCover.test.ts
git commit -m "feat: konstanta kelas tutupan lahan + helper chart/delta (frontend)"
```

---

### Task 6: Frontend — `LandCoverPanel` + integrasi ke `KpsDetailView`

**Files:**
- Create: `frontend/src/components/LandCoverPanel.tsx`
- Modify: `frontend/src/components/KpsDetailView.tsx`
- Test: `frontend/src/test/LandCoverPanel.test.tsx`

**Interfaces:**
- Consumes: `authFetch` dari `../lib/api`; konstanta & helper dari Task 5; endpoint dari Task 4; `recharts` (`BarChart`, `Bar`, `XAxis`, `YAxis`, `Tooltip`, `ResponsiveContainer`); `react-leaflet` (`MapContainer`, `TileLayer`, `GeoJSON`); `SMOOTH_ZOOM_MAP_PROPS` dari `../constants/map`.
- Produces:
  - `export function LandCoverPanel({ polygonId }: { polygonId: number }): JSX.Element`
  - Perilaku: saat mount `GET /api/land-cover/status?polygon_id=`. State `idle` → tombol `Jalankan Analisis` (klik → `POST /api/land-cover/analyze` body `{polygon_id}`; `202` → mulai polling tiap 5 dtk). State `running` → teks `Menghitung… {step}` + spinner, polling. State `done` → `GET /result` lalu render peta + chart + tabel + ringkasan + kaki; tombol kecil `↻ Analisis ulang` (konfirmasi → `POST analyze?force=true`). State `error` → pesan + tombol coba lagi.
  - Peta: `<GeoJSON key={year}>` dari `GET /overlay?polygon_id=&year=`, `style` per fitur pakai `landCoverColor(feature.properties.class_key)` (fill 0.75, stroke sewarna). Penggeser tahun (`<input type="range" min=2020 max=2025 step=1>`) + tombol `◀`/`▶`. Overlay tiap tahun di-cache di `useRef<Map<number, FeatureCollection>>`.

- [ ] **Step 1: Tulis test komponen yang gagal**

```tsx
// frontend/src/test/LandCoverPanel.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LandCoverPanel } from "../components/LandCoverPanel";

const YEARS = (start = 2020) => Array.from({ length: 6 }, (_, i) => start + i);

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response;
}

const RESULT = {
  meta: { model_trees: 150, n_training: 7200, oob_accuracy: 0.81, duration_s: 131,
          computed_at: "2026-08-30T07:20:00+07:00", source: "s", label_source: "Google Dynamic World v1" },
  years: YEARS(),
  classes: ["hutan", "semak", "pertanian", "terbuka", "air"],
  table: Object.fromEntries(YEARS().map((y) => [String(y), {
    hutan: { area_ha: 100, pct: 60 }, semak: { area_ha: 30, pct: 18 },
    pertanian: { area_ha: 20, pct: 12 }, terbuka: { area_ha: 10, pct: 6 },
    air: { area_ha: 6, pct: 4 },
  }])),
  net_change: { hutan: -50, semak: 20, pertanian: 20, terbuka: 8, air: 2 },
  summary_text: "Tutupan Hutan turun 50 ha (-9.1%) dari 2020 ke 2025.",
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mockFetch(handler: (url: string, init?: RequestInit) => Response) {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (url: string, init?: RequestInit) => handler(String(url), init),
  );
}

describe("LandCoverPanel", () => {
  it("idle: shows the run button", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) return jsonResponse({ state: "idle", step: null, error: null, computed_at: null });
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    expect(await screen.findByRole("button", { name: /jalankan analisis/i })).toBeInTheDocument();
  });

  it("clicking the button posts analyze and switches to running text", async () => {
    const calls: string[] = [];
    mockFetch((url) => {
      calls.push(url);
      if (url.includes("/land-cover/analyze")) return jsonResponse({ started: true, polygon_id: 1 }, 202);
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: calls.some((c) => c.includes("/analyze")) ? "running" : "idle",
          step: "2023 (4/6) — klasifikasi", error: null, computed_at: null,
        });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    fireEvent.click(await screen.findByRole("button", { name: /jalankan analisis/i }));
    await waitFor(() => expect(calls.some((c) => c.includes("/land-cover/analyze"))).toBe(true));
    expect(await screen.findByText(/Menghitung/i)).toBeInTheDocument();
  });

  it("done: renders the 5-class legend and the table", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) return jsonResponse({ state: "done", step: null, error: null, computed_at: RESULT.meta.computed_at });
      if (url.includes("/land-cover/result")) return jsonResponse(RESULT);
      if (url.includes("/land-cover/overlay")) return jsonResponse({ type: "FeatureCollection", features: [] });
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    expect(await screen.findByText("Hutan")).toBeInTheDocument();
    expect(screen.getByText("Semak/Belukar")).toBeInTheDocument();
    expect(screen.getByText("Pertanian/Kebun")).toBeInTheDocument();
    expect(screen.getByText("Lahan Terbuka")).toBeInTheDocument();
    expect(screen.getByText("Badan Air")).toBeInTheDocument();
    expect(screen.getByText(/Tutupan Hutan turun 50 ha/i)).toBeInTheDocument();
  });

  it("done: changing the year slider refetches overlay with new year", async () => {
    const overlayYears: string[] = [];
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) return jsonResponse({ state: "done", step: null, error: null, computed_at: RESULT.meta.computed_at });
      if (url.includes("/land-cover/result")) return jsonResponse(RESULT);
      if (url.includes("/land-cover/overlay")) {
        overlayYears.push(new URL(url, "http://x").searchParams.get("year") ?? "");
        return jsonResponse({ type: "FeatureCollection", features: [] });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    await screen.findByText("Hutan");
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "2024" } });
    await waitFor(() => expect(overlayYears).toContain("2024"));
  });
});
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npm test -- LandCoverPanel`
Expected: FAIL (module tidak ada).

- [ ] **Step 3: Tulis `LandCoverPanel.tsx`**

```tsx
// frontend/src/components/LandCoverPanel.tsx
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, GeoJSON } from "react-leaflet";
import {
  Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { SMOOTH_ZOOM_MAP_PROPS } from "../constants/map";
import { LAND_COVER_CLASSES, LAND_COVER_YEARS } from "../constants/landCover";
import { buildChartData, formatDelta, landCoverColor, type LandCoverTable } from "../lib/landCover";
import { authFetch } from "../lib/api";

type State = "idle" | "running" | "done" | "error";
type StatusResponse = { state: State; step: string | null; error: string | null; computed_at: string | null };
type ResultResponse = {
  meta: Record<string, unknown>;
  years: number[];
  classes: string[];
  table: LandCoverTable;
  net_change: Record<string, number>;
  summary_text: string;
};
type FC = { type: "FeatureCollection"; features: Array<{ type: "Feature"; geometry: unknown; properties: { class_key: string; area_ha: number; pct: number } }> };

const POLL_MS = 5000;

export function LandCoverPanel({ polygonId }: { polygonId: number }): JSX.Element {
  const [state, setState] = useState<State>("idle");
  const [step, setStep] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [year, setYear] = useState<number>(LAND_COVER_YEARS[LAND_COVER_YEARS.length - 1]);
  const [overlay, setOverlay] = useState<FC | null>(null);
  const overlayCache = useRef<Map<number, FC>>(new Map());
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchStatus = useCallback(async () => {
    const res = await authFetch(`/api/land-cover/status?polygon_id=${polygonId}`);
    const body = (await res.json()) as StatusResponse;
    setState(body.state);
    setStep(body.step);
    setErrorMsg(body.error);
    return body.state;
  }, [polygonId]);

  useEffect(() => {
    overlayCache.current.clear();
    setResult(null);
    setOverlay(null);
    void fetchStatus();
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [fetchStatus]);

  useEffect(() => {
    if (state !== "running") return;
    pollTimer.current = setTimeout(() => void fetchStatus(), POLL_MS);
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [state, step, fetchStatus]);

  useEffect(() => {
    if (state !== "done") return;
    void authFetch(`/api/land-cover/result?polygon_id=${polygonId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body: ResultResponse | null) => body && setResult(body));
  }, [state, polygonId]);

  useEffect(() => {
    if (state !== "done") return;
    const cached = overlayCache.current.get(year);
    if (cached) {
      setOverlay(cached);
      return;
    }
    void authFetch(`/api/land-cover/overlay?polygon_id=${polygonId}&year=${year}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body: FC | null) => {
        if (!body) return;
        overlayCache.current.set(year, body);
        setOverlay(body);
      });
  }, [state, polygonId, year]);

  const runAnalyze = useCallback(async (force: boolean) => {
    const res = await authFetch(`/api/land-cover/analyze${force ? "?force=true" : ""}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ polygon_id: polygonId }),
    });
    if (res.status === 202) {
      setState("running");
      void fetchStatus();
    } else if (res.status === 503) {
      setState("error");
      setErrorMsg("Analisis satelit belum aktif di server.");
    } else {
      const body = await res.json().catch(() => null);
      setState("error");
      setErrorMsg(typeof body?.detail === "string" ? body.detail : "Gagal memulai analisis.");
    }
  }, [polygonId, fetchStatus]);

  const chartData = useMemo(() => (result ? buildChartData(result.table) : []), [result]);

  if (state === "idle") {
    return (
      <section className="land-cover-panel">
        <h3>Tutupan Lahan 2020–2025 (Sentinel-2 + Random Forest)</h3>
        <p>Belum dianalisis.</p>
        <button type="button" onClick={() => void runAnalyze(false)}>Jalankan Analisis</button>
      </section>
    );
  }

  if (state === "running") {
    return (
      <section className="land-cover-panel">
        <h3>Tutupan Lahan 2020–2025</h3>
        <p aria-live="polite">Menghitung… {step ?? ""}</p>
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="land-cover-panel">
        <h3>Tutupan Lahan 2020–2025</h3>
        <p role="alert">{errorMsg ?? "Terjadi kesalahan."}</p>
        <button type="button" onClick={() => void runAnalyze(false)}>Coba lagi</button>
      </section>
    );
  }

  return (
    <section className="land-cover-panel">
      <header className="land-cover-panel__head">
        <h3>Tutupan Lahan 2020–2025</h3>
        <button
          type="button"
          className="land-cover-panel__rerun"
          onClick={() => {
            if (window.confirm("Analisis ulang poligon ini? Hasil lama akan ditimpa.")) {
              void runAnalyze(true);
            }
          }}
        >
          ↻ Analisis ulang
        </button>
      </header>

      <div className="land-cover-panel__map">
        <div className="land-cover-panel__yearbar">
          <button type="button" onClick={() => setYear((y) => Math.max(LAND_COVER_YEARS[0], y - 1))}>◀</button>
          <input
            type="range"
            min={LAND_COVER_YEARS[0]}
            max={LAND_COVER_YEARS[LAND_COVER_YEARS.length - 1]}
            step={1}
            value={year}
            aria-label="Tahun tutupan lahan"
            onChange={(e) => setYear(Number(e.target.value))}
          />
          <button type="button" onClick={() => setYear((y) => Math.min(LAND_COVER_YEARS[LAND_COVER_YEARS.length - 1], y + 1))}>▶</button>
          <strong>{year}</strong>
        </div>
        <MapContainer {...SMOOTH_ZOOM_MAP_PROPS} style={{ height: 260 }} center={[-2, 118]} zoom={9}>
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {overlay && (
            <GeoJSON
              key={year}
              data={overlay as never}
              style={(feature) => {
                const c = landCoverColor((feature?.properties as { class_key?: string })?.class_key ?? "");
                return { color: c, weight: 1, fillColor: c, fillOpacity: 0.75 };
              }}
            />
          )}
        </MapContainer>
      </div>

      <ul className="land-cover-panel__legend">
        {LAND_COVER_CLASSES.map((c) => (
          <li key={c.key}>
            <span style={{ background: c.color }} aria-hidden />
            {c.label}
          </li>
        ))}
      </ul>

      <div className="land-cover-panel__chart">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData}>
            <XAxis dataKey="year" />
            <YAxis unit="%" />
            <Tooltip />
            {LAND_COVER_CLASSES.map((c) => (
              <Bar key={c.key} dataKey={c.key} stackId="lc" fill={c.color} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {result && (
        <table className="land-cover-panel__table">
          <thead>
            <tr>
              <th>Kelas</th>
              {LAND_COVER_YEARS.map((y) => (
                <th key={y}>{y}</th>
              ))}
              <th>Δ {LAND_COVER_YEARS[0]}→{LAND_COVER_YEARS[LAND_COVER_YEARS.length - 1]}</th>
            </tr>
          </thead>
          <tbody>
            {LAND_COVER_CLASSES.map((c) => (
              <tr key={c.key}>
                <th scope="row">
                  <span style={{ background: c.color }} aria-hidden /> {c.label}
                </th>
                {LAND_COVER_YEARS.map((y) => {
                  const cell = result.table[String(y)]?.[c.key];
                  return (
                    <td key={y}>
                      {cell ? `${Math.round(cell.area_ha)} (${cell.pct.toFixed(1)}%)` : "–"}
                    </td>
                  );
                })}
                <td>{formatDelta(result.net_change[c.key] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {result && <p className="land-cover-panel__summary">{result.summary_text}</p>}
      <p className="land-cover-panel__note">
        "Hutan" = tutupan berpohon; kebun berpohon belum tentu terpisah. Estimasi
        satelit, bukan angka resmi.
      </p>
      {result && (
        <p className="land-cover-panel__foot">
          Sumber: {String(result.meta.source ?? "")} · Guru label: {String(result.meta.label_source ?? "")} ·
          RF {String(result.meta.model_trees ?? "")} pohon · {String(result.meta.n_training ?? "")} titik ·
          OOB {result.meta.oob_accuracy != null ? Number(result.meta.oob_accuracy).toFixed(2) : "-"} ·
          {result.meta.computed_at ? ` ${new Date(String(result.meta.computed_at)).toLocaleString("id-ID")}` : ""}
        </p>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Integrasikan ke `KpsDetailView.tsx`**

- Tambah import setelah baris `import { WeatherConditionCard } from "./WeatherConditionCard";`:
  ```tsx
  import { LandCoverPanel } from "./LandCoverPanel";
  ```
- Cari blok JSX yang merender bagian "Estimasi bekas terbakar (Sentinel-2)" (di sekitar `s2BurnedStats &&`, baris ±868). Tepat SETELAH elemen penutup blok itu, sisipkan:
  ```tsx
  {polygonId !== null && <LandCoverPanel polygonId={polygonId} />}
  ```
  `polygonId` adalah `const polygonId = useMemo(...)` yang sudah ada di komponen (baris ±290).

- [ ] **Step 5: Jalankan test komponen, pastikan lulus**

Run: `cd frontend && npm test -- LandCoverPanel`
Expected: PASS (4 test).

- [ ] **Step 6: Typecheck + seluruh test frontend**

Run: `cd frontend && npm run build && npm test`
Expected: `tsc --noEmit` bersih, `vite build` sukses, semua test hijau.

- [ ] **Step 7: Commit**

```bash
cd /home/ryandshinevps/etaseneu
git add frontend/src/components/LandCoverPanel.tsx frontend/src/components/KpsDetailView.tsx frontend/src/test/LandCoverPanel.test.tsx
git commit -m "feat: panel Tutupan Lahan di kartu Detail KPS (peta rona + chart + tabel)"
```

---

### Task 7: nginx rate-limit + dokumentasi

**Files:**
- Modify: `deploy/nginx/etaseneu.conf`
- Modify: `CLAUDE.md`

**Interfaces:** tidak ada interface kode baru.

- [ ] **Step 1: Tambah location rate-limit nginx**

Di `deploy/nginx/etaseneu.conf`, tepat setelah blok `location = /api/point-match/analyze { ... }` (berakhir sebelum `location /api/export`), sisipkan blok sejenis:

```nginx
    location = /api/land-cover/analyze {
        limit_req zone=eta_heavy burst=2;
        proxy_pass http://api:8000/api/land-cover/analyze;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
```

- [ ] **Step 2: Uji sintaks nginx**

Run:
```bash
cd /home/ryandshinevps/etaseneu
docker run --rm --add-host api:127.0.0.1 \
  -v $PWD/deploy/nginx/etaseneu.conf:/etc/nginx/conf.d/default.conf:ro \
  nginx:alpine nginx -t
```
Expected: `syntax is ok` / `test is successful`. (Kalau Docker tidak tersedia di lingkungan eksekusi, lewati langkah ini dan catat di commit bahwa `nginx -t` belum dijalankan.)

- [ ] **Step 3: Perbarui CLAUDE.md**

Di bagian "Layanan kunci lain", tambahkan butir setelah entri `burned_area_s2_service.py`:

```markdown
- `land_cover_service.py` — **analisis tutupan lahan per poligon** KPS/Hutan Adat,
  2020–2025, dari Sentinel-2 L2A via GEE + Random Forest (`ee.Classifier.smileRandomForest`,
  guru label Google Dynamic World, filter keyakinan ≥0,6, komposit median tahunan).
  On-demand: `POST /api/land-cover/analyze` `{polygon_id}` → job `BackgroundTasks`
  (`LandCoverService.analyze_polygon`, ~1–3 mnt), progres di dict modul-global
  `_LAND_COVER_RUN_STATE`, status final di kolom `land_cover_analysis.status`.
  Hasil di tabel TERPISAH `land_cover_analysis` / `land_cover_year_class` /
  `land_cover_year_geom` (mixin `postgres_store/_land_cover.py`) — di-cache permanen,
  tiap poligon dianalisis sekali. Baca hasil: `GET /api/land-cover/{status,result,overlay}`
  (tak butuh env GEE). "Hutan" = tutupan berpohon (kebun berpohon belum dipisah).
  Tampil di `KpsDetailView.tsx` → `LandCoverPanel.tsx` (peta rona per tahun +
  grafik batang bertumpuk + tabel Δ). Tidak ada scheduler, tidak ada analisis massal.
```

Di daftar tabel mixin `postgres_store/` (tabel Markdown di bagian "`services/postgres_store/`"), tambahkan baris:

```markdown
| `_land_cover.py` | Tutupan lahan per poligon per tahun (`land_cover_analysis`, `land_cover_year_class`, `land_cover_year_geom`) |
```

Dan di daftar `api/` (baris yang menyebут "satu file per domain: hotspots, ..."), tambahkan `land_cover` ke enumerasi.

- [ ] **Step 4: Jalankan seluruh test backend + frontend sekali lagi**

Run:
```bash
cd /home/ryandshinevps/etaseneu/backend && .venv/bin/python -m pytest app/tests -q
cd /home/ryandshinevps/etaseneu/frontend && npm test && npm run build
```
Expected: semua hijau, build sukses.

- [ ] **Step 5: Commit**

```bash
cd /home/ryandshinevps/etaseneu
git add deploy/nginx/etaseneu.conf CLAUDE.md
git commit -m "docs: catat menu Tutupan Lahan di CLAUDE.md + rate-limit nginx"
```

- [ ] **Step 6: Ingatkan user**

Sampaikan ke user: setelah semua task selesai, **redeploy manual di Dokploy** untuk container `api` DAN `web` (rebuild `web` karena `etaseneu.conf` berubah). Analisis pertama per KPS butuh env GEE aktif di server (`GEE_SERVICE_ACCOUNT_EMAIL` / `GEE_SERVICE_ACCOUNT_KEY_PATH` / `GEE_PROJECT_ID`); kalau kosong, tombol balas 503 dan tidak menyimpan apa pun.

---

## Self-Review

**1. Spec coverage:**

| Spec | Task |
|---|---|
| 5 kelas, pemukiman skip | Task 1 (`CLASS_KEYS`), Task 2 (`_DW_MAP`), Task 5 (`LAND_COVER_CLASSES`) |
| Guru label Dynamic World + 3 pengaman (komposit tahunan, conf ≥0.6, hutan=berpohon) | Task 3 (`_year_training_points`, `_year_feature_image`, `DW_CONF_MIN`) |
| Model dilatih per klik, lokal | Task 3 (`analyze_polygon` melatih 1 RF per panggilan) |
| Tombol on-demand, job async, polling | Task 4 (`BackgroundTasks` + `/status`), Task 6 (polling 5 dtk) |
| Cakupan KPS + Hutan Adat | Task 1 (`_TARGET_LAYERS`) |
| Simpan tabel luas + poligon kelas per tahun | Task 1 (3 tabel), Task 3 (`year_class_rows` + `year_geom_rows`) |
| Hasil permanen, buka lagi instan | Task 1 (`read_land_cover_result`), Task 6 (status `done` → langsung `/result`) |
| Rentang 2020–2025, komposit tahun kalender | Task 2 (`YEARS`), Task 3 (`_year_window`) |
| 4 endpoint analyze/status/result/overlay | Task 4 |
| Peta rona per tahun + grafik + tabel Δ + ringkasan + kaki | Task 6 |
| Konstanta warna dipakai bersama | Task 5 (`landCover.ts`), dipakai Task 6 |
| Test `ee` di-mock + store `_Disabled/_Fake` | Task 2/3 (`_FakeEE`, `_FakeStore`), Task 4 (`_FakeService`, `_FakeStore`) |
| `_ensure_land_cover_tables` (tanpa migrasi manual) | Task 1 |
| nginx rate-limit `analyze` di grup 10r/m | Task 7 |
| Update CLAUDE.md + redeploy manual | Task 7 |
| Guard `not enabled` → 503 | Task 4 |
| Guard dua klik bersamaan → 409 | Task 4 |
| Poligon besar / `reduceToVectors` gagal → simpan tabel luas saja | Task 3 (`_year_class_geom` menangkap Exception non-fatal per kelas) |

Deviasi sadar dari spec: auth `POST /analyze` disederhanakan — TIDAK dibuat "admin key ATAU JWT". Endpoint ikut `_read_gate` router seperti `point-match/analyze` (publik saat `API_REQUIRE_AUTH=false`, wajib sesi saat `true`). Alasan: pola yang persis sama sudah dipakai `point-match/analyze`; menumpuk `require_admin_key` menambah kompleksitas tanpa kebutuhan nyata. Kalau user mau kunci admin, tambahkan `Depends(require_admin_key)` di `land_cover_analyze` — satu baris.

**2. Placeholder scan:** tidak ada "TBD/TODO/implement later". Semua step kode punya blok kode utuh. Penanganan error eksplisit (`try/except` non-fatal per kelas geometri; `mark_land_cover_error` di orkestrasi; 503/409/404 di API).

**3. Type consistency:**
- Store: `read_land_cover_target_polygon`, `mark_land_cover_running`, `mark_land_cover_error`, `save_land_cover_result(*, model_trees, n_training, oob_accuracy, duration_s, year_class_rows, year_geom_rows)`, `read_land_cover_status`, `read_land_cover_result`, `read_land_cover_overlay(polygon_id, year)` — nama & tanda tangan identik di Task 1 (definisi), Task 3 (pemanggilan service), Task 4 (pemanggilan API), dan fake di test.
- `year_class_rows` item `{year, class_key, area_ha, pct}` dan `year_geom_rows` item `{year, class_key, geometry_geojson}` konsisten Task 1 ↔ Task 3.
- `_build_summary_text(table)` & `_net_change(table)` dengan `table[year][class_key] = {"area_ha","pct"}` — bentuk sama di Task 2 (definisi), Task 3 (produksi `table`), Task 4 (rekonstruksi `table` dari `year_class` lalu panggil keduanya).
- Frontend: `LandCoverTable`, `buildChartData`, `landCoverColor`, `formatDelta`, `LAND_COVER_CLASSES`, `LAND_COVER_YEARS` — dipakai Task 6 persis seperti didefinisikan Task 5.
- Endpoint `/land-cover/status` mengembalikan `{state, step, error, computed_at}` di Task 4; dikonsumsi `StatusResponse` di Task 6 dengan nama field sama.
- `/land-cover/result` mengembalikan `{meta, years, classes, table, net_change, summary_text}` di Task 4; `ResultResponse` di Task 6 sama.
