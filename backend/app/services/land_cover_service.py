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
