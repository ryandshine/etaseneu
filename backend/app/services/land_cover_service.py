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
