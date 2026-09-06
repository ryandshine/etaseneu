"""Klasifikasi tutupan lahan per poligon KPS/Hutan Adat (2021-2025) dari
Sentinel-2 L2A + Sentinel-1 SAR via Google Earth Engine, Random Forest dengan
label latih mandiri berbasis arketipe spektral (spectral endmembers).
On-demand per poligon; hasil di-cache permanen di tabel `land_cover_*`
(lihat postgres_store/_land_cover.py).

Estimasi, bukan angka resmi. 5 kelas mandiri ETA SENEU (tanpa ketergantungan
pada model/guru pihak ketiga seperti Google Dynamic World, ESA WorldCover,
Hansen GFC, atau Descals):
  hutan       tutupan berpohon alami kanopi rapat
  pertanian   perkebunan (sawit/karet/campuran) & pertanian (sawah/ladang)
  semak       semak/belukar/alang-alang/vegetasi rendah
  basah       badan air (sungai/danau) & lahan basah/rawa
  terbuka     lahan terbuka/tandus/bekas tebangan/pasir

Formula v5 (2026-09-06, keputusan user: sistem mandiri & bebas awan):
1. Komposit tahunan = median MUSIM KEMARAU (Mei-Okt) dengan cloud-mask SCL
   Sentinel-2 ketat; celah diisi median setahun penuh.
2. Label latih mandiri (spectral endmembers): diekstraksi langsung dari citra
   lokal poligon menggunakan indeks kanonik (NDVI, EVI, MNDWI, BSI, NBR) dan
   fitur radar Sentinel-1 SAR (VV, VH, VH/VV ratio).
3. Random Forest lokal dilatih dari titik-titik endmembers murni tersebut.
4. Pasca-klasifikasi: gap-fill aturan spektral internal, filter mayoritas 3x3,
   dan aturan konsistensi transisi temporal.
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
from app.services.land_cover.labels import (
    rule_based_classify,
    sparse_classes,
    spectral_seed_image,
)
from app.services.land_cover.sar import (
    S1_MIN_SCENES,
    SAR_FEATURE_NAMES,
    get_dominant_pass,
    get_s1_composite,
    s1_scene_counts,
)
from app.services.land_cover.temporal import apply_transition_rules
from app.services.postgres_store import PostgresStore

logger = logging.getLogger("land_cover")

S2_COLLECTION = "COPERNICUS/S2_SR_HARMONIZED"

# Versi formula yang tersimpan di land_cover_analysis.formula_version.
# Naikkan tiap kali metode berubah sehingga hasil lama bisa dibedakan di UI.
#   1 = S2 median setahun, 5 kelas, DW mode label, tanpa despike
#   2 = 2026-09-05: median kemarau, DW argmax, kelas kebun (Descals),
#       postprocess (proyeksi/gap-fill/focal_mode), despike simetris
#   3 = 2026-09-05: + Sentinel-1 SAR, konsensus label Hansen + WorldCover,
#       aturan transisi temporal, sampel 200/kelas/tahun
#   4 = 2026-09-05: taksonomi 6 kelas standar IPCC (kebun/sawit dilebur ke
#       pertanian/Cropland, kelas permukiman/Settlement diaktifkan, air+rawa
#       digabung jadi basah/Wetland); toleransi konsensus khusus sawit
#   5 = 2026-09-06: 5 kelas mandiri ETA SENEU (hutan, pertanian, semak, basah, terbuka),
#       tanpa guru eksternal (Dynamic World/WorldCover/Hansen/Descals dibuang);
#       label latih dibangkitkan mandiri dari arketipe spektral (spectral endmembers);
#       Sentinel-2 SCL cloud masking + kemarau median + fallback aturan spektral
FORMULA_VERSION = 5
FORMULA_LABEL = (
    "Sentinel-2 L2A median kemarau + Sentinel-1 SAR + Random Forest; "
    "5 kelas mandiri ETA SENEU (tanpa guru eksternal); "
    "endmember spektral adaptif; filter awan SCL multi-layer; "
    "aturan transisi temporal (ETA SENEU v5)"
)

YEARS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
CLASS_KEYS: tuple[str, ...] = ("hutan", "pertanian", "semak", "basah", "terbuka")
_CLASS_IDX = {k: i for i, k in enumerate(CLASS_KEYS)}

RF_TREES = 150
SAMPLES_PER_CLASS_PER_YEAR = 200
MIN_SAMPLES_PER_CLASS = 30
DRY_SEASON = ("05-01", "10-31")
OPTICAL_FEATURE_NAMES = [
    "B2", "B3", "B4", "B8", "B11", "B12",
    "ndvi", "evi", "nbr", "mndwi", "ndbi", "bsi", "elevation", "slope",
]
USE_SAR = True
FEATURE_NAMES = OPTICAL_FEATURE_NAMES + (list(SAR_FEATURE_NAMES) if USE_SAR else [])

SIMPLIFY_TOL = 0.00004
MIN_MMU_PX = 10
GEE_TILE_SCALE = 4
VECTOR_FALLBACK_SCALE = 20
_MAX_CLOUD = 50
_S2_BANDS = ["B2", "B3", "B4", "B8", "B11", "B12"]
TRAIN_BUFFER_M = 3000

# Pemetaan DW lama untuk kompatibilitas fungsi _dw_label_to_class
_DW_MAP = {
    0: "basah", 1: "hutan", 2: "semak", 3: "basah",
    4: "pertanian", 5: "semak", 7: "terbuka",
}

# Progres langkah live — boleh hilang saat restart; status final ada di DB.
_LAND_COVER_RUN_STATE: dict[int, dict] = {}


class LandCoverError(Exception):
    """GEE belum dikonfigurasi, poligon tidak valid, atau gagal analisis."""


def _dw_label_to_class(label: int) -> str | None:
    return _DW_MAP.get(int(label))


def land_cover_any_running() -> dict[str, object] | None:
    """Poligon mana pun yang analisisnya BENERAN sedang jalan di proses ini
    sekarang (bukan status 'running' basi di DB -- dict ini otomatis kosong
    lagi kalau proses restart, lihat catatan di atas). Dipakai buat lock
    GLOBAL: cuma 1 analisis boleh jalan bersamaan di seluruh sistem, supaya
    kuota GEE & CPU training Random Forest tidak diperebutkan banyak user
    sekaligus. Asumsi: satu proses `api` (tidak ada multi-worker) -- kalau
    nanti di-scale ke >1 worker/container, lock ini perlu pindah ke DB/Redis."""
    for pid, info in _LAND_COVER_RUN_STATE.items():
        return {"polygon_id": pid, "step": info.get("step")}
    return None


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
    "hutan": "Hutan", "pertanian": "Pertanian/Perkebunan", "semak": "Semak/Belukar",
    "basah": "Lahan Basah/Perairan", "terbuka": "Lahan Terbuka",
}

# Ambang "berarti" dalam hektar -- dipakai supaya kalimat ringkasan tidak
# menyebut perubahan yang dibulatkan jadi "+0 ha" (kontradiktif: bilang
# "beralih ke X" tapi angkanya nol). Sama dengan ambang di frontend (lihat
# threshold .lc-delta / hasData() di LandCoverPanel.tsx).
_MEANINGFUL_HA = 0.5


def _build_summary_text(table: dict[int, dict[str, dict]]) -> str:
    a, b = table.get(YEARS[0]), table.get(YEARS[-1])
    if not a or not b or "hutan" not in a or "hutan" not in b:
        return "Data tidak lengkap untuk membuat ringkasan."
    delta = b["hutan"]["area_ha"] - a["hutan"]["area_ha"]
    pct = (delta / a["hutan"]["area_ha"] * 100) if a["hutan"]["area_ha"] else 0.0
    nc = _net_change(table)
    gainers = sorted(
        ((k, v) for k, v in nc.items() if k != "hutan" and v > _MEANINGFUL_HA),
        key=lambda kv: kv[1], reverse=True,
    )[:2]
    ke = (
        " Beralih terutama ke " + " dan ".join(f"{_CLASS_LABEL[k]} (+{v:,.0f} ha)" for k, v in gainers) + "."
        if gainers else ""
    )
    if abs(delta) <= _MEANINGFUL_HA:
        return (
            f"Tutupan Hutan relatif stabil ({pct:+.1f}%) "
            f"dari {YEARS[0]} ke {YEARS[-1]}.{ke}"
        )
    arah = "turun" if delta < 0 else "naik"
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

    def _dry_window(self, year: int) -> tuple[str, str]:
        start = date.fromisoformat(f"{year}-{DRY_SEASON[0]}")
        end = date.fromisoformat(f"{year}-{DRY_SEASON[1]}")
        today = date.today()
        if end >= today:
            end = today
        return start.isoformat(), end.isoformat()

    def _s2_median(self, ee, region, start: str, end: str):
        return (
            ee.ImageCollection(S2_COLLECTION)
            .filterBounds(region)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", _MAX_CLOUD))
            .select(_S2_BANDS + ["SCL"])
            .map(self._scl_scale(ee))
            .median()
        )

    def _year_feature_image(self, ee, roi, year: int, region=None, sar_img=None):
        """Tumpukan fitur satu tahun: optik S2 + indeks + DEM, plus band SAR
        (`sar_img` dari land_cover/sar.py) kalau diberikan. Urutan band =
        OPTICAL_FEATURE_NAMES (+ SAR_FEATURE_NAMES)."""
        clip_to = region if region is not None else roi
        # Prioritas musim kemarau: lebih sedikit awan/haze dan fenologi lebih
        # seragam antar-tahun. Piksel yang tetap kosong (kemarau berawan
        # terus, lazim di Kalbar/Riau) diisi median setahun penuh.
        dry_start, dry_end = self._dry_window(year)
        full_start, full_end = self._year_window(year)
        dry = self._s2_median(ee, clip_to, dry_start, dry_end)
        if dry_start >= dry_end:
            # tahun berjalan sebelum Mei: belum ada data kemarau
            s2 = self._s2_median(ee, clip_to, full_start, full_end).clip(clip_to)
        else:
            s2 = dry.unmask(self._s2_median(ee, clip_to, full_start, full_end)).clip(clip_to)
        ndvi = s2.normalizedDifference(["B8", "B4"]).rename("ndvi")
        nbr = s2.normalizedDifference(["B8", "B12"]).rename("nbr")
        mndwi = s2.normalizedDifference(["B3", "B11"]).rename("mndwi")
        ndbi = s2.normalizedDifference(["B11", "B8"]).rename("ndbi")
        bsi = (
            s2.select("B11").add(s2.select("B4"))
            .subtract(s2.select("B8").add(s2.select("B2")))
            .divide(
                s2.select("B11").add(s2.select("B4"))
                .add(s2.select("B8").add(s2.select("B2")))
            )
            .rename("bsi")
        )
        evi = (
            s2.select("B8").subtract(s2.select("B4"))
            .multiply(2.5)
            .divide(
                s2.select("B8")
                .add(s2.select("B4").multiply(6.0))
                .subtract(s2.select("B2").multiply(7.5))
                .add(1.0)
            )
            .rename("evi")
        )
        dem = ee.Image("NASA/NASADEM_HGT/001").select("elevation")
        slope = ee.Terrain.products(dem).select("slope") if hasattr(ee, "Terrain") else dem.rename("slope")
        feat = ee.Image.cat(
            s2.select(["B2", "B3", "B4", "B8", "B11", "B12"]),
            ndvi, evi, nbr, mndwi, ndbi, bsi,
            dem.rename("elevation"), slope.rename("slope"),
        ).rename(OPTICAL_FEATURE_NAMES)
        if sar_img is not None:
            feat = feat.addBands(sar_img.select(list(SAR_FEATURE_NAMES)))
        return feat

    def _sar_enabled(self) -> bool:
        settings = getattr(self, "settings", None)
        return bool(getattr(settings, "land_cover_use_sar", USE_SAR))

    def _prepare_sar(self, ee, roi, train_region) -> tuple[dict[int, object], dict]:
        """Komposit S1 per tahun untuk poligon ini, atau `{}` kalau SAR tidak
        layak dipakai (toggle mati / koleksi kosong / scene kurang / GEE
        gagal). Selalu graceful: kegagalan apa pun di sini -> optik saja,
        BUKAN exception. `info` disimpan ke meta.sar untuk audit."""
        if not self._sar_enabled():
            return {}, {"enabled": False, "reason": "toggle_off"}
        windows = {y: self._year_window(y) for y in YEARS}
        start, end = windows[YEARS[0]][0], windows[YEARS[-1]][1]
        try:
            dominant_pass = get_dominant_pass(ee, train_region, start, end)
            counts = s1_scene_counts(ee, train_region, YEARS, dominant_pass, windows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LAND_COVER: SAR dilewati, gagal memeriksa S1 (%s)", exc)
            return {}, {"enabled": False, "reason": f"error: {exc}"[:200]}
        if not counts:
            logger.warning("LAND_COVER: SAR dilewati, koleksi S1 tidak bisa dihitung")
            return {}, {"enabled": False, "reason": "no_count"}
        short = {y: n for y, n in counts.items() if n < S1_MIN_SCENES}
        info = {"orbit_pass": dominant_pass, "scenes_per_year": {str(y): n for y, n in counts.items()},
                "min_scenes": S1_MIN_SCENES}
        if short:
            logger.warning(
                "LAND_COVER: SAR dilewati, scene S1 (%s) kurang dari %d di tahun %s",
                dominant_pass, S1_MIN_SCENES, sorted(short),
            )
            return {}, {**info, "enabled": False, "reason": "insufficient_scenes"}
        by_year = {}
        for y in YEARS:
            s, e = windows[y]
            img, _ = get_s1_composite(ee, train_region, y, dominant_pass, start=s, end=e)
            by_year[y] = img
        return by_year, {**info, "enabled": True}

    def _year_training_points(self, ee, roi, feat_img, year: int, region=None, use_sar: bool = False):
        sample_region = region if region is not None else roi
        class_idx = spectral_seed_image(ee, feat_img, _CLASS_IDX, use_sar=use_sar)
        stack = feat_img.addBands(class_idx)
        return stack.stratifiedSample(
            numPoints=SAMPLES_PER_CLASS_PER_YEAR,
            classBand="class_idx",
            region=sample_region,
            scale=10,
            seed=42 + year,
            geometries=False,
        )

    def _materialize_samples(
        self, ee, samples, feature_names: list[str] | None = None
    ) -> tuple[list[dict], object]:
        """Tarik sampel latih ke klien SEKALI, lalu kirim balik sebagai
        FeatureCollection literal.

        Ini optimasi terpenting: tanpa ini, tiap `getInfo()` berikutnya
        (luas per tahun, vektor per tahun, OOB) memaksa GEE mengulang
        stratifiedSample 5 tahun + median komposit region ber-buffer dari nol,
        karena GEE tidak menyimpan hasil antar-request. Payload-nya kecil
        (~500 titik x 12 fitur), jauh lebih murah daripada mengulang sampling.
        """
        names = list(feature_names) if feature_names is not None else list(FEATURE_NAMES)
        info = samples.getInfo() or {}
        rows: list[dict] = []
        keep = set(names) | {"class_idx"}
        for f in info.get("features", []):
            props = f.get("properties") or {}
            if props.get("class_idx") is None:
                continue
            if any(props.get(k) is None for k in names):
                continue  # piksel tertutup mask di salah satu band -> buang
            rows.append({k: props[k] for k in keep})
        fc = ee.FeatureCollection([ee.Feature(None, r) for r in rows])
        return rows, fc

    def _distinct_class_count(self, rows: list[dict]) -> int:
        """Berapa nilai `class_idx` berbeda ada di sampel latih (sudah
        dimaterialisasi). < 2 -> Random Forest tak bisa dilatih, orkestrasi
        jatuh ke Dynamic World."""
        return len({int(r["class_idx"]) for r in rows})

    # -- ekstraksi hasil per tahun ----------------------------------------------

    def _postprocess_classified(self, ee, roi, classified, gap_fill=None):
        """Pasca-klasifikasi standar sebelum luas & vektor dihitung.

        1. `setDefaultProjection` 10 m — WAJIB duluan: hasil `.classify()` atas
           komposit median tidak berproyeksi (WGS84 1°), sehingga operasi
           bertetangga (`focal_mode`, `connectedPixelCount`) jalan di skala 1°.
        2. `unmask(gap_fill)` — piksel yang tertutup awan/bayangan sepanjang
           tahun (mask SCL) tadinya DIBUANG diam-diam: total luas < luas
           poligon dan persen dihitung dari piksel tersisa saja. Sekarang
           lubang diisi label Dynamic World tahun itu (10 m juga) supaya
           luas mengisi poligon penuh.
        3. `focal_mode` 3x3 — filter mayoritas menghilangkan "salt & pepper"
           piksel tunggal yang lazim pada RF per-piksel; luas per kelas berubah
           kecil (<1-2 %), peta rona jauh lebih bersih.
        """
        img = classified.setDefaultProjection("EPSG:3857", None, 10)
        if gap_fill is not None:
            img = img.unmask(gap_fill).clip(roi)
        img = img.focal_mode(1, "square", "pixels").rename("class_idx")
        return img.setDefaultProjection("EPSG:3857", None, 10)

    def _apply_temporal_rules(self, ee, per_year: dict[int, object]) -> tuple[dict[int, object], list[str]]:
        """Despike + aturan transisi (land_cover/temporal.py). Tahun pertama &
        terakhir tidak diubah -> perubahan nyata di 2025 tetap terlihat.
        Biaya: tiap tahun tengah mengevaluasi 3 komposit."""
        return apply_transition_rules(ee, per_year, _CLASS_IDX)

    def _year_area_expr(self, ee, roi, classified):
        """Ekspresi (belum di-evaluate) luas per kelas: ee.Dictionary {groups}."""
        return (
            ee.Image.pixelArea()
            .addBands(classified)
            .reduceRegion(
                reducer=ee.Reducer.sum().group(groupField=1, groupName="class"),
                geometry=roi,
                scale=10,
                maxPixels=1e9,
                bestEffort=True,
                tileScale=GEE_TILE_SCALE,
            )
        )

    def _year_vectors_expr(self, ee, roi, classified, scale: int = 10):
        """Ekspresi vektor per kelas untuk lapisan peta — SATU `reduceToVectors`
        per tahun (label per fitur = `class_idx`), bukan satu per kelas.
        `connectedPixelCount` menghitung komponen per NILAI piksel, jadi MMU
        tetap berlaku per kelas.

        WAJIB `setDefaultProjection` dulu: hasil `.classify()` atas komposit
        median tidak punya proyeksi (GEE: WGS84 1 derajat, transform
        [1,0,0,0,1,0]) sehingga `connectedPixelCount` dihitung di skala 1° ->
        seluruh poligon cuma 1 "piksel" < MMU -> semua ter-mask -> 0 vektor
        (luas tetap benar karena reduceRegion pakai scale eksplisit). Citra
        Dynamic World tidak kena karena sudah 10 m."""
        classified = classified.setDefaultProjection("EPSG:3857", None, 10)
        cpc = classified.connectedPixelCount(MIN_MMU_PX + 1, True)
        mask = classified.updateMask(cpc.gte(MIN_MMU_PX))
        return mask.reduceToVectors(
            geometry=roi, scale=scale, geometryType="polygon",
            labelProperty="class_idx", eightConnected=True,
            maxPixels=1e9, bestEffort=True, tileScale=GEE_TILE_SCALE,
        )

    def _year_evaluate(self, ee, roi, classified) -> tuple[dict, dict]:
        """Luas + vektor satu tahun = DUA `getInfo()` terpisah.

        Sengaja TIDAK digabung dalam satu `ee.Dictionary({...}).getInfo()`:
        diuji nyata 2026-09-05, `reduceToVectors` yang dievaluasi di dalam
        Dictionary selalu mengembalikan 0 fitur (bahkan dengan `reproject`
        eksplisit), sedangkan `getInfo()` langsung pada FeatureCollection-nya
        memberi belasan fitur -- rona peta kosong di produksi. Biaya: +5
        request per poligon (≈12 total), masih jauh di bawah ≈32 semula."""
        areas = self._year_area_expr(ee, roi, classified).getInfo() or {}
        try:
            vectors = self._year_vectors_expr(ee, roi, classified).getInfo() or {}
        except Exception as exc:  # noqa: BLE001
            if "memory limit" not in str(exc).lower():
                raise
            # Vektorisasi 10 m poligon besar bisa melampaui memori per-request
            # GEE walau sudah tileScale. Ulang dengan vektor 20 m supaya
            # analisis tetap selesai (luas per kelas tetap 10 m), bukan gagal.
            logger.warning(
                "LAND_COVER: memori GEE habis pada vektorisasi 10 m, ulang dengan %d m",
                VECTOR_FALLBACK_SCALE,
            )
            vectors = self._year_vectors_expr(
                ee, roi, classified, scale=VECTOR_FALLBACK_SCALE
            ).getInfo() or {}
        return areas, vectors

    def _parse_area_by_class(self, grouped: dict) -> dict[str, float]:
        out = {k: 0.0 for k in CLASS_KEYS}
        for grp in grouped.get("groups", []):
            idx = int(grp.get("class", -1))
            if 0 <= idx < len(CLASS_KEYS):
                out[CLASS_KEYS[idx]] = float(grp.get("sum") or 0.0) / 10000.0
        return out

    def _parse_class_geom(self, vectors: dict, raw_geom) -> dict[str, dict]:
        boundary = shapely_shape(raw_geom).buffer(0)
        out: dict[str, dict] = {}
        parts_by_key: dict[str, list] = {k: [] for k in CLASS_KEYS}
        for f in vectors.get("features", []):
            geom = f.get("geometry")
            props = f.get("properties") or {}
            if not geom or props.get("class_idx") is None:
                continue
            idx = int(props["class_idx"])
            if not 0 <= idx < len(CLASS_KEYS):
                continue
            parts_by_key[CLASS_KEYS[idx]].append(shapely_shape(geom).buffer(0))
        for key in CLASS_KEYS:
            parts = parts_by_key[key]
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
        train_region = roi.buffer(TRAIN_BUFFER_M).bounds()

        try:
            self.postgres_store.mark_land_cover_running(pid, target["layer_key"])

            # -- Sentinel-1: satu orbit dominan untuk seluruh rentang, lalu
            # guard jumlah scene per tahun. Kalau ada tahun yang kurang scene
            # (atau S1 kosong sama sekali -- pulau terluar), SAR dimatikan
            # untuk poligon INI dan analisis lanjut optik saja: satu model RF
            # butuh daftar fitur yang sama di semua tahun.
            _LAND_COVER_RUN_STATE[pid] = {
                "state": "running",
                "step": "memeriksa cakupan Sentinel-1",
                "started_at": date.today().isoformat(),
            }
            sar_by_year, sar_info = self._prepare_sar(ee, roi, train_region)
            use_sar = bool(sar_by_year)
            feature_names = list(OPTICAL_FEATURE_NAMES) + (list(SAR_FEATURE_NAMES) if use_sar else [])

            feat_by_year = {}
            samples = None
            for i, year in enumerate(YEARS):
                _LAND_COVER_RUN_STATE[pid] = {
                    "state": "running",
                    "step": f"{year} ({i + 1}/{len(YEARS)}) — sampel",
                    "started_at": date.today().isoformat(),
                }
                feat = self._year_feature_image(
                    ee, roi, year, region=train_region,
                    sar_img=sar_by_year.get(year) if use_sar else None,
                )
                feat_by_year[year] = feat
                pts = self._year_training_points(ee, roi, feat, year, region=train_region, use_sar=use_sar)
                samples = pts if samples is None else samples.merge(pts)

            _LAND_COVER_RUN_STATE[pid] = {
                "state": "running",
                "step": "mengunduh sampel latih",
                "started_at": date.today().isoformat(),
            }
            sample_rows, samples_fc = self._materialize_samples(ee, samples, feature_names)
            use_rf = self._distinct_class_count(sample_rows) >= 2
            if use_rf:
                _LAND_COVER_RUN_STATE[pid]["step"] = "melatih Random Forest"
                rf = ee.Classifier.smileRandomForest(RF_TREES, seed=42).train(
                    features=samples_fc, classProperty="class_idx", inputProperties=feature_names
                )
                try:
                    oob_err = rf.explain().getInfo().get("outOfBagErrorEstimate")
                    oob_accuracy = round(1.0 - float(oob_err), 4) if oob_err is not None else None
                except Exception:  # noqa: BLE001
                    oob_accuracy = None
                model_trees = RF_TREES
                n_training = len(sample_rows)
            else:
                # Poligon homogen: sampel latih < 2 kelas. Random Forest tak
                # bisa dilatih ("Only one class") -> pakai aturan spektral langsung.
                logger.warning(
                    "LAND_COVER: poligon %s homogen (sampel latih < 2 kelas) — "
                    "fallback ke klasifikasi aturan spektral mandiri",
                    pid,
                )
                rf = None
                oob_accuracy = None
                model_trees = 0
                n_training = 0

            # Klasifikasi & pengukuran cukup di dalam poligon: klip ke ROI
            # supaya GEE tidak menghitung komposit/RF untuk seluruh bbox
            # ber-buffer 3 km (yang cuma perlu saat sampling latih).
            per_year: dict[int, object] = {}
            for year in YEARS:
                fallback_img = rule_based_classify(ee, feat_by_year[year], _CLASS_IDX, use_sar=use_sar)
                if use_rf:
                    classified = feat_by_year[year].clip(roi).classify(rf).rename("class_idx")
                    per_year[year] = self._postprocess_classified(
                        ee, roi, classified, gap_fill=fallback_img
                    )
                else:
                    per_year[year] = self._postprocess_classified(ee, roi, fallback_img)
            per_year, temporal_rules = self._apply_temporal_rules(ee, per_year)

            table: dict[int, dict[str, dict]] = {}
            year_class_rows: list[dict] = []
            year_geom_rows: list[dict] = []
            for i, year in enumerate(YEARS):
                _LAND_COVER_RUN_STATE[pid] = {
                    "state": "running",
                    "step": f"{year} ({i + 1}/{len(YEARS)}) — klasifikasi",
                    "started_at": date.today().isoformat(),
                }
                grouped, vectors = self._year_evaluate(ee, roi, per_year[year])
                areas = self._parse_area_by_class(grouped)
                total = sum(areas.values()) or 1.0
                table[year] = {}
                for key in CLASS_KEYS:
                    pct = round(areas[key] / total * 100.0, 2)
                    table[year][key] = {"area_ha": round(areas[key], 2), "pct": pct}
                    year_class_rows.append(
                        {"year": year, "class_key": key, "area_ha": round(areas[key], 2), "pct": pct}
                    )
                geoms = self._parse_class_geom(vectors, raw_geom)
                for key, geom in geoms.items():
                    year_geom_rows.append({"year": year, "class_key": key, "geometry_geojson": geom})

            duration_s = round(time.monotonic() - started, 1)
            samples_per_class: dict[str, int] = {}
            for r in sample_rows:
                key = CLASS_KEYS[int(r["class_idx"])]
                samples_per_class[key] = samples_per_class.get(key, 0) + 1
            # coverage < ~95 % = ada piksel yang tetap kosong walau sudah
            # gap-fill (awan permanen); UI bisa memperingatkan.
            poly_ha = target.get("area_ha")
            coverage_pct = {}
            if poly_ha:
                for year, row in table.items():
                    total_ha = sum(v["area_ha"] for v in row.values())
                    coverage_pct[str(year)] = round(total_ha / float(poly_ha) * 100.0, 1)
            label_sources = ["Sentinel-2 L2A + Sentinel-1 SAR Spectral Endmembers (ETA SENEU v5)"]
            meta = {
                "method": "random_forest" if use_rf else "spectral_rules",
                "feature_names": feature_names,
                "sar": sar_info,
                "labels": {
                    "sources": label_sources,
                    "requested_per_class_per_year": SAMPLES_PER_CLASS_PER_YEAR,
                    "samples_per_class": samples_per_class,
                    "sparse_classes": sparse_classes(samples_per_class, CLASS_KEYS, MIN_SAMPLES_PER_CLASS),
                    "min_samples_per_class": MIN_SAMPLES_PER_CLASS,
                },
                "temporal": {"rules": temporal_rules},
                "coverage_pct": coverage_pct,
            }
            self.postgres_store.save_land_cover_result(
                pid,
                target["layer_key"],
                model_trees=model_trees,
                n_training=n_training,
                oob_accuracy=oob_accuracy,
                duration_s=duration_s,
                year_class_rows=year_class_rows,
                year_geom_rows=year_geom_rows,
                formula_version=FORMULA_VERSION,
                meta=meta,
                source=FORMULA_LABEL,
                label_source="Autonomous Spectral Endmembers (ETA SENEU v5)",
            )
            return {
                "polygon_id": pid,
                "years": list(YEARS),
                "classes": list(CLASS_KEYS),
                "method": "random_forest" if use_rf else "spectral_rules",
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
