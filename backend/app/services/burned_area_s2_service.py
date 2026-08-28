"""Analisis MANDIRI luas bekas terbakar dari Sentinel-2 dNBR (Google Earth Engine).

Berbeda dari `burned_area_service.py` (produk MODIS/VIIRS bulanan, lag rilis
berbulan-bulan) dan dari rekap resmi KLHK (`burned_area_summary`, telat ~1
bulan): service ini menghitung SENDIRI bekas terbakar bulan berjalan dari
citra Sentinel-2 L2A, supaya peta bisa menampilkan estimasi tanpa menunggu
pihak lain. Hasilnya ESTIMASI, belum terverifikasi -- disimpan di tabel
terpisah `s2_burned_area`, tidak dicampur ke agregat resmi.

Formula (divalidasi pada 120 poligon Kalbar, Agustus 2026 -- konsisten dengan
rekap KLHK 2026 dan menangkap kawasan terbakar yang TIDAK punya hotspot):

    dNBR   = median(NBR pre) - median(NBR post)          NBR  = (B8-B12)/(B8+B12)
    dNDVI  = median(NDVI pre) - median(NDVI post)         NDVI = (B8-B4)/(B8+B4)
    MNDWI  = median(MNDWI post)                           MNDWI= (B3-B11)/(B3+B11)
    nobs   = jumlah observasi post yang valid per piksel

    scar   = dNBR >= 0.40  AND  dNDVI >= 0.15  AND  NDVI_pre >= 0.30
             AND  MNDWI < -0.05  AND  nobs >= 2
    scar_c = scar AND connectedPixelCount(scar, 30) >= 25   (~1 ha @ 20 m)

Ambang 0.40 + komposit MEDIAN (bukan max-pre/min-post) sengaja ketat: ambang
longgar + ekstrem membuat penurunan NBR musim kemarau ikut terhitung sebagai
terbakar (pernah menghasilkan 20x luas rekap KLHK).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import mapping, shape as shapely_shape
from shapely.ops import unary_union

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore

logger = logging.getLogger("burned_area_s2")

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

# Ambang & gate -- lihat docstring modul.
DNBR_MIN = 0.40
DNDVI_MIN = 0.15
NDVI_PRE_MIN = 0.30
MNDWI_MAX = -0.05
NOBS_MIN = 2
MIN_CLUSTER_PX = 25  # @ 20 m ~= 1 ha
MIN_REPORT_HA = 1.0

# reduceRegions per panggilan -- geometry dikirim inline, jaga ukuran request.
_BATCH_SIZE = 150
# Hari jendela "pra-kebakaran" sebelum awal bulan target.
_PRE_WINDOW_DAYS = 46
_MAX_CLOUD = 80


class BurnedAreaS2Error(Exception):
    """GEE belum dikonfigurasi atau gagal init."""


def _month_bounds(year: int, month: int) -> tuple[str, str, str, str]:
    """(pre_start, pre_end, post_start, post_end) sebagai string ISO.

    post = awal bulan target s/d awal bulan berikutnya (atau besok, kalau
    bulan target adalah bulan berjalan). pre = `_PRE_WINDOW_DAYS` hari
    sebelum awal bulan target.
    """
    post_start = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    today = date.today()
    post_end = min(nxt, today + timedelta(days=1)) if nxt > today else nxt
    pre_start = post_start - timedelta(days=_PRE_WINDOW_DAYS)
    return (
        pre_start.isoformat(),
        post_start.isoformat(),
        post_start.isoformat(),
        post_end.isoformat(),
    )


class BurnedAreaS2Service:
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
            raise BurnedAreaS2Error(
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

    # -- pipeline raster per-region -------------------------------------------------

    def _scl_scale(self, ee):
        """Fungsi map: buang awan/bayangan/salju via SCL, skala reflektansi ke 0..1."""

        def _fn(img):
            scl = img.select("SCL")
            keep = (
                scl.neq(0)
                .And(scl.neq(1))
                .And(scl.neq(3))
                .And(scl.neq(8))
                .And(scl.neq(9))
                .And(scl.neq(10))
                .And(scl.neq(11))
            )
            return img.updateMask(keep).divide(10000)

        return _fn

    def _scar_mask(self, ee, region_geom):
        """Bangun mask bekas terbakar (scar_c) untuk satu bbox region."""
        pre_start, pre_end, post_start, post_end = self._pre_post
        scl_scale = self._scl_scale(ee)

        def _coll(start, end):
            return (
                ee.ImageCollection(S2_COLLECTION)
                .filterBounds(region_geom)
                .filterDate(start, end)
                .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _MAX_CLOUD))
                .map(scl_scale)
            )

        pre = _coll(pre_start, pre_end)
        post = _coll(post_start, post_end)

        def _nd(bands):
            return lambda img: img.normalizedDifference(bands)

        nbr_pre = pre.map(_nd(["B8", "B12"])).median()
        nbr_post = post.map(_nd(["B8", "B12"])).median()
        dnbr = nbr_pre.subtract(nbr_post)

        ndvi_pre = pre.map(_nd(["B8", "B4"])).median()
        ndvi_post = post.map(_nd(["B8", "B4"])).median()
        dndvi = ndvi_pre.subtract(ndvi_post)

        mndwi_post = post.map(_nd(["B3", "B11"])).median()
        nobs = post.map(lambda img: img.select("B8").mask()).sum()

        scar = (
            dnbr.gte(DNBR_MIN)
            .And(dndvi.gte(DNDVI_MIN))
            .And(ndvi_pre.gte(NDVI_PRE_MIN))
            .And(mndwi_post.lt(MNDWI_MAX))
            .And(nobs.gte(NOBS_MIN))
        )
        cpc = scar.selfMask().connectedPixelCount(MIN_CLUSTER_PX + 5, True)
        scar_c = scar.And(cpc.gte(MIN_CLUSTER_PX))
        return scar_c, dnbr

    def _vectorize(self, ee, scar_c, polygon_geojson) -> dict | None:
        """Piksel scar di dalam satu poligon -> GeoJSON MultiPolygon, diclip ke KPS."""
        try:
            vectors = (
                scar_c.selfMask()
                .reduceToVectors(
                    geometry=ee.Geometry(polygon_geojson),
                    scale=20,
                    geometryType="polygon",
                    eightConnected=True,
                    maxPixels=1e9,
                )
                .getInfo()
            )
        except Exception as exc:  # noqa: BLE001 -- non-fatal, angka luas tetap tersimpan
            logger.warning("S2_BURNED: reduceToVectors gagal — %s", exc)
            return None

        try:
            boundary = shapely_shape(polygon_geojson).buffer(0)
            parts = [
                shapely_shape(f["geometry"]).buffer(0)
                for f in vectors.get("features", [])
                if f.get("geometry")
            ]
            if not parts:
                return None
            clipped = unary_union(parts).intersection(boundary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("S2_BURNED: clip geometry gagal — %s", exc)
            return None

        if clipped.is_empty:
            return None
        if isinstance(clipped, ShapelyPolygon):
            clipped = ShapelyMultiPolygon([clipped])
        elif not isinstance(clipped, ShapelyMultiPolygon):
            polys = [g for g in getattr(clipped, "geoms", []) if isinstance(g, ShapelyPolygon)]
            if not polys:
                return None
            clipped = ShapelyMultiPolygon(polys)
        return mapping(clipped)

    # -- orkestrasi ---------------------------------------------------------------

    def analyze_month(
        self, year: int, month: int, *, provinces: list[str] | None = None
    ) -> dict[str, object]:
        """Hitung ulang estimasi bekas terbakar Sentinel-2 untuk satu bulan.

        Diproses per-provinsi: satu komposit raster per bbox provinsi, lalu
        `reduceRegions` batched atas poligon di provinsi itu. Poligon dengan
        estimasi >= `MIN_REPORT_HA` divektorkan supaya tampil di peta.
        """
        ee = self._ensure_ee()
        self._pre_post = _month_bounds(year, month)

        polygons = self.postgres_store.read_active_polygons_for_s2(provinces=provinces)
        if not polygons:
            return {"year": year, "month": month, "polygons_checked": 0, "computed": 0}

        by_prov: dict[str, list[dict]] = {}
        for poly in polygons:
            by_prov.setdefault(poly.get("nama_prov") or "TANPA_PROVINSI", []).append(poly)

        month_start = date(year, month, 1).isoformat()
        nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        hotspot_counts = self.postgres_store.hotspot_counts_in_polygons(
            [p["id"] for p in polygons], month_start, nxt.isoformat()
        )

        rows: list[dict[str, object]] = []
        polygons_checked = 0

        for prov, prov_polys in by_prov.items():
            polygons_checked += len(prov_polys)
            region = self._province_bbox(ee, prov_polys)
            try:
                scar_c, _dnbr = self._scar_mask(ee, region)
                area_img = scar_c.multiply(ee.Image.pixelArea()).rename("ha")
            except Exception as exc:  # noqa: BLE001
                logger.warning("S2_BURNED: gagal bangun mask untuk %s — %s", prov, exc)
                continue

            for start in range(0, len(prov_polys), _BATCH_SIZE):
                batch = prov_polys[start : start + _BATCH_SIZE]
                fc = ee.FeatureCollection(
                    [
                        ee.Feature(ee.Geometry(p["geometry"]), {"pid": p["id"]})
                        for p in batch
                    ]
                )
                try:
                    reduced = area_img.reduceRegions(
                        collection=fc,
                        reducer=ee.Reducer.sum(),
                        scale=20,
                        tileScale=4,
                    ).getInfo()["features"]
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "S2_BURNED: reduceRegions gagal (%s batch %d) — %s",
                        prov,
                        start,
                        exc,
                    )
                    continue

                geom_by_pid = {p["id"]: p for p in batch}
                for feat in reduced:
                    props = feat.get("properties", {})
                    pid = int(props.get("pid"))
                    area_ha = float(props.get("sum") or 0.0) / 10000.0
                    if area_ha < MIN_REPORT_HA:
                        continue
                    poly = geom_by_pid[pid]
                    geom = self._vectorize(ee, scar_c, poly["geometry"])
                    hs = int(hotspot_counts.get(pid, 0))
                    rows.append(
                        {
                            "polygon_metadata_id": pid,
                            "layer_key": poly["layer_key"],
                            "year": year,
                            "month": month,
                            "area_ha": round(area_ha, 2),
                            "dnbr_mean": None,
                            "hotspot_count_month": hs,
                            "has_hotspot": hs > 0,
                            "geometry_geojson": geom,
                        }
                    )

        cleared = self.postgres_store.clear_s2_burned_area(year, month, provinces=provinces)
        saved = self.postgres_store.upsert_s2_burned_area(rows)
        total_ha = round(sum(float(r["area_ha"]) for r in rows), 1)
        logger.info(
            "S2_BURNED: %d/%d poligon terbakar (%.1f ha), %d dihapus, bulan %d-%02d",
            saved,
            polygons_checked,
            total_ha,
            cleared,
            year,
            month,
        )
        return {
            "year": year,
            "month": month,
            "polygons_checked": polygons_checked,
            "computed": saved,
            "total_ha": total_ha,
            "no_hotspot_but_burned": sum(1 for r in rows if not r["has_hotspot"]),
        }

    def _province_bbox(self, ee, prov_polys: list[dict]):
        """Rectangle EE yang membungkus semua poligon di satu provinsi (+ pad kecil)."""
        minx = miny = 1e9
        maxx = maxy = -1e9
        for poly in prov_polys:
            for x, y in _iter_coords(poly["geometry"]):
                minx, miny = min(minx, x), min(miny, y)
                maxx, maxy = max(maxx, x), max(maxy, y)
        pad = 0.01
        return ee.Geometry.Rectangle(
            [minx - pad, miny - pad, maxx + pad, maxy + pad], None, False
        )


def _iter_coords(geojson: dict):
    """Yield (x, y) dari geometry GeoJSON Polygon/MultiPolygon."""
    gtype = geojson.get("type")
    coords = geojson.get("coordinates") or []
    if gtype == "Polygon":
        rings = coords
    elif gtype == "MultiPolygon":
        rings = [ring for poly in coords for ring in poly]
    else:
        return
    for ring in rings:
        for pt in ring:
            yield pt[0], pt[1]
