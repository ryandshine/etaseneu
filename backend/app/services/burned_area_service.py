"""Luas kebakaran (burned area) per poligon KPS per bulan.

Sumber: MODIS MCD64A1 (Burned Area, band BurnDate, resolusi 500m) lewat
Google Earth Engine. Cadence-nya bulanan dan biasanya baru terbit dengan lag
~1-3 bulan dari bulan berjalan -- beda jauh dari sync hotspot NASA FIRMS yang
tiap 3 jam. Jangan disamakan kesegarannya di UI: KPI "luas terbakar bulan
ini" pada dasarnya selalu menampilkan bulan beberapa waktu lalu, bukan bulan
sekarang.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


logger = logging.getLogger("burned_area")

# Jumlah poligon per panggilan reduceRegions() ke Earth Engine. Dibatasi
# supaya payload FeatureCollection yang dikirim (geometry poligon dikirim
# inline, bukan lewat asset upload) tidak melebihi batas ukuran request EE.
_BATCH_SIZE = 200

MCD64A1_COLLECTION = "MODIS/061/MCD64A1"


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
        collection = (
            ee.ImageCollection(MCD64A1_COLLECTION).filterDate(start, end).select("BurnDate")
        )
        if collection.size().getInfo() == 0:
            return {
                "year": year,
                "month": month,
                "polygons_checked": 0,
                "computed": 0,
                "note": (
                    "Citra MCD64A1 belum tersedia untuk periode ini "
                    "(produk biasanya terbit dengan lag beberapa bulan)."
                ),
            }

        area_image = collection.mosaic().gt(0).multiply(ee.Image.pixelArea())

        polygons_checked = 0
        computed_rows: list[dict[str, object]] = []

        for layer_key in target_layer_keys:
            polygon_ids = self.postgres_store.read_active_polygon_metadata_ids(
                layer_keys=[layer_key]
            )
            polygons_checked += len(polygon_ids)

            for batch_start in range(0, len(polygon_ids), _BATCH_SIZE):
                batch_ids = polygon_ids[batch_start : batch_start + _BATCH_SIZE]
                geometries = self.postgres_store.read_polygon_geometries(
                    batch_ids, tolerance=0.001
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
                    computed_rows.append(
                        {
                            "polygon_metadata_id": int(pid),
                            "layer_key": layer_key,
                            "year": year,
                            "month": month,
                            "burned_area_ha": float(sum_sqm) / 10_000.0,
                        }
                    )

        upserted = self.postgres_store.upsert_burned_area_summary(computed_rows)
        return {
            "year": year,
            "month": month,
            "polygons_checked": polygons_checked,
            "computed": upserted,
        }
