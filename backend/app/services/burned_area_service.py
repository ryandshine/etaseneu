"""Luas kebakaran (burned area) per poligon KPS per bulan.

Sumber utama: MODIS MCD64A1 (Burned Area, band BurnDate, resolusi 500m)
lewat Google Earth Engine. Kalau MCD64A1 belum terbit untuk suatu bulan,
sistem fallback ke VIIRS VNP64A1 (band Burn_Date, resolusi 500m juga, tim &
algoritma sama) -- lihat `_resolve_monthly_source()`. Cadence-nya bulanan
dan biasanya baru terbit dengan lag ~1-3 bulan dari bulan berjalan -- beda
jauh dari sync hotspot NASA FIRMS yang tiap 3 jam. Jangan disamakan
kesegarannya di UI: KPI "luas terbakar bulan ini" pada dasarnya selalu
menampilkan bulan beberapa waktu lalu, bukan bulan sekarang.
"""

from __future__ import annotations

import logging

from shapely.geometry import MultiPolygon as ShapelyMultiPolygon
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import mapping, shape as shapely_shape
from shapely.ops import unary_union

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


logger = logging.getLogger("burned_area")

# Jumlah poligon per panggilan reduceRegions() ke Earth Engine. Dibatasi
# supaya payload FeatureCollection yang dikirim (geometry poligon dikirim
# inline, bukan lewat asset upload) tidak melebihi batas ukuran request EE.
_BATCH_SIZE = 200

MCD64A1_COLLECTION = "MODIS/061/MCD64A1"
MCD64A1_BAND = "BurnDate"

# VIIRS/VNP64A1: algoritma & tim yang sama dengan MCD64A1 (University of
# Maryland), resolusi 500m sama, tapi disokong satelit yang lebih baru
# (Suomi-NPP/NOAA-20) sehingga lag rilisnya cenderung lebih pendek daripada
# MODIS (Terra/Aqua, makin uzur). Dipakai sebagai FALLBACK -- bukan sumber
# utama -- karena histori panjang MCD64A1 lebih mapan untuk baseline.
VNP64A1_COLLECTION = "NASA/VIIRS/002/VNP64A1"
VNP64A1_BAND = "Burn_Date"

# Urutan dicoba: MODIS dulu, VIIRS kalau MODIS belum terbit untuk bulan ini.
_MONTHLY_SOURCES = ((MCD64A1_COLLECTION, MCD64A1_BAND), (VNP64A1_COLLECTION, VNP64A1_BAND))


class BurnedAreaServiceError(Exception):
    """Google Earth Engine belum dikonfigurasi atau gagal diinisialisasi."""


def _month_range(year: int, month: int) -> tuple[str, str]:
    start = f"{year:04d}-{month:02d}-01"
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    end = f"{end_year:04d}-{end_month:02d}-01"
    return start, end


class BurnedAreaService:
    def __init__(self, postgres_store: PostgresStore | None = None) -> None:
        settings = get_settings()
        self.settings = settings
        self.postgres_store = postgres_store or PostgresStore(settings.database_url)
        self._ee_initialized = False

    @property
    def enabled(self) -> bool:
        s = self.settings
        return bool(
            s.gee_service_account_email and s.gee_service_account_key_path and s.gee_project_id
        )

    def _ensure_ee(self):
        if self._ee_initialized:
            import ee

            return ee

        if not self.enabled:
            raise BurnedAreaServiceError(
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

    def _vectorize_burned_area(self, ee, burned_mask, polygon_geojson) -> dict | None:
        """Ubah piksel terbakar di dalam satu poligon jadi GeoJSON MultiPolygon.

        Dipakai untuk menggambar lapisan area terbakar di peta detail KPS --
        `reduceRegions()` di pemanggil hanya mengembalikan angka luas, bentuk
        area-nya tidak ikut. Gagal di sini tidak fatal: angka luasnya tetap
        tersimpan, hanya lapisan petanya yang absen.

        `reduceToVectors()` diberi `geometry` cuma untuk MEMILIH piksel mana
        yang diproses -- poligon hasilnya adalah SELURUH piksel MODIS 500m
        (25 ha) yang tersentuh, TIDAK dipotong ke batas KPS. Piksel yang cuma
        menyerempet tepi kawasan tetap ikut utuh, sehingga geometrinya bisa
        meluber jauh melebihi luas KPS-nya sendiri -- ditemukan lewat sanity
        check luas_bakar > luas_poligon: satu KPS 20,7 ha menunjukkan
        geometry 49,7 ha (2,4x lipat), padahal angka `burned_area_ha`
        (dari reduceRegions, yang MEMANG diclip ke batas KPS) di baris yang
        sama cuma 24,1 ha -- dua angka yang seharusnya konsisten tapi
        terpisah 2x lipat karena beda cara hitung. Makanya hasil vektor di
        sini di-intersect ulang ke `polygon_geojson` pakai shapely sebelum
        disimpan, supaya geometry yang tergambar di peta tidak pernah lebih
        luas dari kawasannya sendiri, dan konsisten dengan burned_area_ha.
        """
        try:
            vectors = (
                burned_mask.selfMask()
                .reduceToVectors(
                    geometry=ee.Geometry(polygon_geojson),
                    scale=500,
                    geometryType="polygon",
                    maxPixels=1e9,
                )
                .getInfo()
            )
        except Exception as exc:
            logger.warning("BURNED_AREA: reduceToVectors gagal — %s", exc)
            return None

        try:
            kps_boundary = shapely_shape(polygon_geojson).buffer(0)
            raw_geoms = [
                shapely_shape(feature["geometry"]).buffer(0)
                for feature in vectors.get("features", [])
                if feature.get("geometry")
            ]
            if not raw_geoms:
                return None
            clipped = unary_union(raw_geoms).intersection(kps_boundary)
        except Exception as exc:
            logger.warning("BURNED_AREA: gagal clip geometry ke batas KPS — %s", exc)
            return None

        if clipped.is_empty:
            return None

        if isinstance(clipped, ShapelyPolygon):
            clipped = ShapelyMultiPolygon([clipped])
        elif not isinstance(clipped, ShapelyMultiPolygon):
            # GeometryCollection dsb (potongan garis/titik sisa numerik) --
            # ambil cuma bagian poligonalnya.
            polys = [g for g in getattr(clipped, "geoms", []) if isinstance(g, ShapelyPolygon)]
            if not polys:
                return None
            clipped = ShapelyMultiPolygon(polys)

        return mapping(clipped)

    def _resolve_monthly_source(self, ee, start: str, end: str):
        """Cari sumber burned-area yang sudah punya citra untuk bulan ini.

        Coba MCD64A1 dulu, fallback ke VNP64A1 kalau MODIS belum terbit --
        lihat catatan di konstanta `VNP64A1_COLLECTION` di atas. Return
        `(None, None)` kalau dua-duanya belum ada citra untuk periode ini.
        """
        for collection_id, band in _MONTHLY_SOURCES:
            collection = ee.ImageCollection(collection_id).filterDate(start, end).select(band)
            if collection.size().getInfo() > 0:
                return collection_id, collection.mosaic().gt(0)
        return None, None

    def refresh_burned_area(
        self,
        year: int,
        month: int,
        layer_keys: list[str] | None = None,
    ) -> dict[str, object]:
        """Hitung ulang luas terbakar satu bulan untuk poligon KPS aktif.

        Kalau citra MCD64A1 untuk periode ini belum terbit (lag rilis produk),
        fungsi ini pulang dengan `computed=0` dan catatan -- bukan error --
        supaya pemanggil berkala (scheduler bulanan) bisa coba lagi nanti
        tanpa dianggap gagal.
        """
        ee = self._ensure_ee()

        target_layer_keys = layer_keys or self.postgres_store.read_active_layer_keys()
        if not target_layer_keys:
            return {"year": year, "month": month, "polygons_checked": 0, "computed": 0}

        start, end = _month_range(year, month)
        source_id, burned_mask = self._resolve_monthly_source(ee, start, end)
        if burned_mask is None:
            return {
                "year": year,
                "month": month,
                "polygons_checked": 0,
                "computed": 0,
                "note": (
                    "Citra MCD64A1 maupun VNP64A1 belum tersedia untuk periode ini "
                    "(produk biasanya terbit dengan lag beberapa bulan)."
                ),
            }

        area_image = burned_mask.multiply(ee.Image.pixelArea())

        polygons_checked = 0
        computed_rows: list[dict[str, object]] = []

        for layer_key in target_layer_keys:
            polygon_ids = self.postgres_store.read_active_polygon_metadata_ids(
                layer_keys=[layer_key]
            )
            polygons_checked += len(polygon_ids)

            for batch_start in range(0, len(polygon_ids), _BATCH_SIZE):
                batch_ids = polygon_ids[batch_start : batch_start + _BATCH_SIZE]
                # tolerance jauh lebih ketat dari default (0.001 / ~110m,
                # dipakai tempat lain untuk peta kecil di laporan PDF) --
                # untuk KPS mungil, simplifikasi sekasar itu bisa MENGGEMBUNG-
                # KAN poligon: ditemukan KPS 20,7 ha menyimpang jadi 25,1 ha
                # (+21%) pada tolerance 0.001, dan itu jadi batas clip untuk
                # burned_area_ha/geometry -- inflasi luas kawasannya ikut
                # mengangkat luas terbakar yang dilaporkan. 0.0001 (~11m)
                # cukup presisi dan masih jauh lebih halus dari resolusi
                # piksel MODIS (500m) yang jadi bottleneck presisi sesungguhnya.
                geometries = self.postgres_store.read_polygon_geometries(
                    batch_ids, tolerance=0.0001
                )
                if not geometries:
                    continue

                features = [
                    ee.Feature(ee.Geometry(geometry), {"pid": pid})
                    for pid, geometry in geometries.items()
                ]
                fc = ee.FeatureCollection(features)

                try:
                    reduced = area_image.reduceRegions(
                        collection=fc,
                        reducer=ee.Reducer.sum(),
                        scale=500,
                    )
                    results = reduced.getInfo()["features"]
                except Exception as exc:
                    logger.warning(
                        "BURNED_AREA: reduceRegions gagal untuk layer %s batch %d-%d — %s",
                        layer_key,
                        batch_start,
                        batch_start + len(batch_ids),
                        exc,
                    )
                    continue

                for feature in results:
                    props = feature.get("properties", {})
                    pid = props.get("pid")
                    sum_sqm = props.get("sum") or 0
                    if pid is None:
                        continue

                    # Vektorisasi hanya untuk poligon yang benar-benar terbakar.
                    # reduceToVectors() satu panggilan per poligon, jadi
                    # melakukannya untuk semua (mayoritas nol) akan memperlambat
                    # sinkronisasi berkali-kali lipat tanpa hasil apa pun.
                    geometry_geojson = None
                    if sum_sqm and float(sum_sqm) > 0:
                        geometry_geojson = self._vectorize_burned_area(
                            ee, burned_mask, geometries[int(pid)]
                        )

                    computed_rows.append(
                        {
                            "polygon_metadata_id": int(pid),
                            "layer_key": layer_key,
                            "year": year,
                            "month": month,
                            "burned_area_ha": float(sum_sqm) / 10_000.0,
                            "source": source_id,
                            "geometry_geojson": geometry_geojson,
                        }
                    )

        upserted = self.postgres_store.upsert_burned_area_summary(computed_rows)
        return {
            "year": year,
            "month": month,
            "polygons_checked": polygons_checked,
            "computed": upserted,
        }
