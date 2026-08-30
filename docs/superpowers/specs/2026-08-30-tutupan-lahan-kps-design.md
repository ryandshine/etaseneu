# Desain: Analisis Tutupan Lahan per Poligon KPS / Hutan Adat (Sentinel-2 + Random Forest)

Tanggal: 2026-08-30
Status: draft — menunggu review sebelum implementation plan.

## Tujuan

Menu baru **"Tutupan Lahan 2020–2025"** di kartu Detail KPS. User menekan satu
tombol untuk **satu poligon** (KPS `psagustus2026` atau Hutan Adat
`HUTAN_ADAT_APR26`); sistem mengklasifikasikan tutupan lahan poligon itu untuk
tiap tahun 2020–2025 dari citra **Sentinel-2 L2A** via Google Earth Engine,
memakai **Random Forest** yang dilatih otomatis (guru label = Google Dynamic
World). Hasil (tabel luas per kelas per tahun + poligon kelas untuk rona peta)
**disimpan permanen** — buka lagi = tampil instan, tidak menghitung ulang.

Berdiri sendiri: **tidak ada kaitan** dengan data hotspot atau bekas terbakar.

Bukan angka resmi/legal. Selalu berlabel estimasi; "Hutan" pada versi ini
berarti **tutupan berpohon** (kebun berpohon seperti sawit/karet belum tentu
terpisah — pemisahan menyusul lewat shp kebun/HGU, pola sama seperti rencana
shp pemukiman).

## Keputusan (disepakati di diskusi 2026-08-30)

1. **Skema 5 kelas sederhana:** `hutan`, `semak` (Semak/Belukar),
   `pertanian` (Pertanian/Kebun), `terbuka` (Lahan Terbuka), `air` (Badan Air).
   **Pemukiman di-skip** pada versi ini (akan ditumpangkan dari shp terpisah
   nanti).
2. **Guru label = Google Dynamic World** (`GOOGLE/DYNAMICWORLD/V1`), otomatis
   penuh — tidak ada sampling manual pada versi pertama. Tiga pengaman wajib:
   - **Komposit tahunan**, bukan scene tunggal (lawan awan).
   - **Filter keyakinan**: hanya jadikan titik training piksel yang probabilitas
     kelas Dynamic World-nya `≥ 0.6`.
   - "Hutan" = tutupan berpohon (diterima apa adanya untuk sekarang).
3. **Model dilatih per klik, lokal ke poligon itu** — bukan satu model global
   yang disimpan sebagai GEE asset. Alasan: hasil di-cache permanen (tiap
   poligon dianalisis **sekali seumur hidup**), jadi kelemahan "lambat / tak
   identik kalau diulang" tidak relevan; arsitektur paling sederhana; model
   menyesuaikan bioma setempat.
4. **Pemicu: tombol on-demand per poligon** di kartu Detail KPS. Job async
   (butuh ~1–3 menit), frontend polling status. **Tidak ada scheduler, tidak
   ada analisis massal.**
5. **Cakupan: KPS + Hutan Adat** (`layer_key IN ('psagustus2026',
   'HUTAN_ADAT_APR26')`).
6. **Yang disimpan:** tabel luas (ha + persen) per kelas per tahun **DAN**
   poligon kelas (GeoJSON disederhanakan) per tahun — untuk rona warna di peta
   yang bisa di-toggle per tahun 2020–2025. Poligon KPS sendiri tetap tampil
   dengan garis batas tegas di atas isian rona.
7. **Rentang tahun tetap 2020–2025** (6 komposit tahunan). Dynamic World
   tersedia sejak 2015 — 2020 aman.
8. **Jendela komposit = tahun kalender penuh** (1 Jan – 31 Des) median S2 L2A
   dengan cloud-mask SCL. Untuk 2025, jendela dipotong sampai tanggal analisis.
   (Penyempitan ke musim kemarau bisa menyusul kalau tutupan awan bikin tahun
   tertentu tipis data.)

## Data & skema

### Tabel baru (mixin `app/services/postgres_store/_land_cover.py`)

Semua dibuat lewat `_ensure_land_cover_tables(conn)` (pola `_ensure_*` yang
sudah dipakai store lain — tidak ada skrip migrasi manual).

```sql
CREATE TABLE IF NOT EXISTS land_cover_analysis (
    id BIGSERIAL PRIMARY KEY,
    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
    layer_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending|running|done|error
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
);

CREATE TABLE IF NOT EXISTS land_cover_year_class (
    id BIGSERIAL PRIMARY KEY,
    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
    year INTEGER NOT NULL,
    class_key TEXT NOT NULL,                     -- hutan|semak|pertanian|terbuka|air
    area_ha DOUBLE PRECISION NOT NULL,
    pct DOUBLE PRECISION NOT NULL,
    UNIQUE (polygon_metadata_id, year, class_key)
);

CREATE TABLE IF NOT EXISTS land_cover_year_geom (
    id BIGSERIAL PRIMARY KEY,
    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
    year INTEGER NOT NULL,
    class_key TEXT NOT NULL,
    geometry geometry(MultiPolygon, 4326),
    UNIQUE (polygon_metadata_id, year, class_key)
);
CREATE INDEX IF NOT EXISTS land_cover_year_geom_pid_year_idx
    ON land_cover_year_geom (polygon_metadata_id, year);
```

Idempoten: tiap run `DELETE` baris `year_class` + `year_geom` untuk poligon itu,
`upsert` baris `land_cover_analysis`, lalu `INSERT` ulang. Bisa dihapus total
via `DELETE FROM land_cover_* WHERE polygon_metadata_id = ...`.

### Query geometri poligon target

```sql
SELECT id, layer_key, lembaga, nama_prov,
       ST_AsGeoJSON(geometry)::json AS geometry_json
FROM polygon_metadata
WHERE id = %s AND is_active
  AND layer_key IN ('psagustus2026','HUTAN_ADAT_APR26')
```

Geometri mentah (bukan disederhanakan) dipakai sebagai ROI + untuk clip akhir.

### Pemetaan kelas Dynamic World (9) → 5 kelas

| Dynamic World | class_key | Catatan |
|---|---|---|
| `water` (0) | `air` | |
| `trees` (1) | `hutan` | termasuk kebun berpohon (keterbatasan diketahui) |
| `grass` (2) | `semak` | digabung ke Semak/Belukar |
| `flooded_vegetation` (3) | `semak` | rawa bervegetasi → semak |
| `crops` (4) | `pertanian` | |
| `shrub_and_scrub` (5) | `semak` | |
| `built_area` (6) | — | **dibuang** dari titik training (kelas pemukiman di-skip) |
| `bare` (7) | `terbuka` | |
| `snow_and_ice` (8) | — | tidak relevan Indonesia; dibuang |

Piksel `built_area` yang jatuh di dalam poligon: pada peta hasil akan
terklasifikasi ke salah satu dari 5 kelas oleh RF (paling sering `terbuka` atau
`pertanian`). Diterima untuk versi ini; catatan ditampilkan di UI.

## Arsitektur backend

### `app/services/land_cover_service.py` — `LandCoverService`

- `enabled` → `bool(settings.gee_service_account_email and
  settings.gee_service_account_key_path and settings.gee_project_id)`.
  `_ensure_ee()` disalin dari `burned_area_s2_service.py` (pakai `settings.gee_*`,
  **bukan** hardcode `/app/shp/...`).
- Konstanta:
  - `YEARS = (2020, 2021, 2022, 2023, 2024, 2025)`
  - `RF_TREES = 150`
  - `SAMPLES_PER_YEAR = 1200` (titik acak per tahun sebelum filter keyakinan)
  - `DW_CONF_MIN = 0.6`
  - `FEATURE_BANDS = ['B2','B3','B4','B8','B11','B12']`
  - indeks turunan: `NDVI`(B8,B4), `NBR`(B8,B12), `MNDWI`(B3,B11), `NDBI`(B11,B8)
  - topografi: `NASADEM` → `elevation`, `slope`
  - `CLASS_KEYS = ['hutan','semak','pertanian','terbuka','air']`
  - `SIMPLIFY_TOL = 0.0003` (~33 m, konsisten dgn jalur S2 bekas terbakar)
  - `MIN_MAPPING_UNIT_PX = 5` (buang patch < 5 px ≈ 0.2 ha @ 20 m via
    `connectedPixelCount`)

- `analyze_polygon(polygon_id: int) -> dict`:
  1. Ambil geometri + metadata poligon target (query di atas). Kalau tidak ada
     / tidak aktif / layer_key di luar 2 itu → `LandCoverError`.
  2. `roi = ee.Geometry(geometry_json)`.
  3. **Bangun tumpukan fitur per tahun** (`_year_feature_image(roi, year)`):
     komposit **median S2 L2A** (`COPERNICUS/S2_SR_HARMONIZED`, cloud-mask SCL,
     `CLOUDY_PIXEL_PERCENTAGE < 70`, `divide(10000)`) untuk jendela tahun itu,
     tambah 4 indeks + 2 band topografi. Semua band di-`rename` berprefiks tahun
     tidak perlu — fitur sama tiap tahun, hanya nilainya beda.
  4. **Titik training per tahun** (`_year_training_points(feat_img, roi, year)`):
     - `dw = ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1').filterDate(...).
       filterBounds(roi)`; ambil `label` = **modus** setahun
       (`.select('label').mode()`) dan `prob_max` = `.select([...9 prob])
       .reduce('max').mode()` — atau lebih sederhana: `.mean()` tiap band
       probabilitas lalu `.reduce(ee.Reducer.max())`.
     - Mask `prob_max ≥ DW_CONF_MIN`.
     - Petakan `label` (0–8) → `class_key` via `remap` (buang 6 & 8).
     - `sample = feat_img.addBands(class_img).stratifiedSample(
       numPoints=SAMPLES_PER_YEAR/5, classBand='class_idx', region=roi,
       scale=10, geometries=False, seed=42+year)` — stratified supaya kelas
       minoritas (air, terbuka) tetap terwakili.
  5. Gabung titik semua tahun jadi satu `FeatureCollection` training.
  6. **Latih** `ee.Classifier.smileRandomForest(RF_TREES, seed=42).train(
     features=training, classProperty='class_idx', inputProperties=FEATURE_NAMES)`.
     Ambil `.explain()` / confusion `errorMatrix` OOB → `oob_accuracy`.
  7. **Untuk tiap tahun**: `classified = feat_img.classify(rf)` →
     - `connectedPixelCount` + buang patch kecil.
     - **Luas per kelas**: `ee.Image.pixelArea().addBands(classified).
       reduceRegion(ee.Reducer.sum().group(groupField=1), roi, scale=10,
       maxPixels=1e9, bestEffort=True)` → m² → ha per `class_idx`.
     - `pct` = `area_ha / total_ha_klasifikasi * 100`.
     - **Vektor per kelas**: `classified.eq(idx).selfMask().reduceToVectors(
       geometry=roi, scale=10, eightConnected=True, maxPixels=1e9)` → union →
       `intersection(shapely_shape(raw_geom))` → `simplify(SIMPLIFY_TOL)` →
       MultiPolygon GeoJSON.
  8. **Simpan** (satu transaksi logis, autocommit store): `DELETE` baris lama
     poligon di `year_class` + `year_geom`; `upsert land_cover_analysis`
     (`status='done'`, `model_trees`, `n_training`, `oob_accuracy`,
     `duration_s`, `computed_at=NOW()`); `INSERT` `year_class` (6×5 baris) +
     `year_geom` (≤ 6×5 baris, lewati kelas kosong).
  9. Return ringkasan `{"polygon_id", "years": [...], "classes": [...],
     "oob_accuracy", "duration_s", "table": {year: {class_key: {area_ha, pct}}},
     "net_change": {class_key: delta_ha_2020_2025}}`.

- Jalan **sinkron**; dipanggil dari `BackgroundTasks`. State progres ditulis ke
  modul-global `_land_cover_run_state: dict[int, dict]` (per `polygon_id`):
  `{"state": "running", "step": "2023 (4/6)", "started_at": ...}`. Saat selesai
  / error, status final juga tercermin di kolom `land_cover_analysis.status`
  (sumber kebenaran; `_run_state` hanya untuk progres langkah live).

### API (`app/api/land_cover.py`, dirakit di `router.py` dengan prefix `/api`)

| Endpoint | Auth | Perilaku |
|---|---|---|
| `POST /api/land-cover/analyze` body `{polygon_id}` | `require_admin_key` ATAU JWT user login (pola `point-match/analyze`) + rate-limit nginx 10r/m | Kalau `not service.enabled` → `503`. Kalau sudah ada baris `status IN ('running')` untuk poligon → `409`. Kalau sudah `done` dan tanpa `?force=true` → `409 {"detail":"sudah dianalisis","done":true}`. Else set/`upsert` baris `status='running'`, mulai `BackgroundTasks`, balas `202 {"started":true,"polygon_id":N}`. |
| `GET /api/land-cover/status?polygon_id=` | `require_session_if_enabled` | `{"state":"idle|running|done|error","step":str|null,"error":str|null,"computed_at":iso|null}` — `state` dibaca dari `land_cover_analysis.status` (fallback `idle` kalau belum ada baris), `step` dari `_run_state`. |
| `GET /api/land-cover/result?polygon_id=` | `require_session_if_enabled` | `404` kalau belum `done`. Else `{"meta": {...land_cover_analysis...}, "years":[2020..2025], "table":{year:{class_key:{area_ha,pct}}}, "net_change":{class_key:delta}, "summary_text": "..."}`. **Tanpa geometri** (payload ringan). |
| `GET /api/land-cover/overlay?polygon_id=&year=` | `require_session_if_enabled` | `404` kalau belum `done` / tahun di luar rentang. Else `FeatureCollection` — satu Feature per kelas, `properties {class_key, area_ha, pct}`, geometri dari `year_geom`. |

`summary_text` dibuat backend (contoh: "Tutupan Hutan turun 930 ha (−17,2%)
2020→2025, beralih ke Semak (+410 ha) dan Pertanian/Kebun (+430 ha)").

### Guard konfigurasi

`not service.enabled` → semua endpoint tulis balas `503 {"detail":"GEE belum
dikonfigurasi di server"}` (fail-closed, pola `ADMIN_API_KEY`). Endpoint baca
tetap jalan (baca tabel, tak butuh GEE).

## Frontend

### `KpsDetailView.tsx` — bagian baru "Tutupan Lahan 2020–2025"

Di bawah bagian "Estimasi bekas terbakar (Sentinel-2)" yang sudah ada.
Self-contained fetch lewat `lib/api.ts` (`authFetch`), **tidak** lewat
`useDashboardData`.

Status (hook lokal `useLandCoverAnalysis(polygonId)`):
- **idle** (`GET /status` → `idle`): teks "Belum dianalisis." + tombol
  `▶ Jalankan Analisis`.
- **running**: tombol disabled, spinner + teks `Menghitung… {step}`; polling
  `GET /status` tiap 5 dtk.
- **done**: render panel hasil (di bawah); tombol kecil `↻ Analisis ulang`
  (`POST analyze?force=true`, konfirmasi dulu).
- **error**: pesan + tombol coba lagi.

`POST /api/land-cover/analyze` dipicu tombol; `202` → mulai polling.

### Panel hasil

1. **Peta mini** (`react-leaflet`, `SMOOTH_ZOOM_MAP_PROPS`): batas poligon KPS
   (stroke gelap 2px, tanpa isian) + layer rona kelas dari
   `GET /overlay?polygon_id=&year=`. Penggeser / tombol tahun 2020–2025 ganti
   `year` (fetch overlay per tahun, cache di memori komponen). Warna kelas dari
   konstanta bersama.
2. **Grafik batang bertumpuk %** per tahun (pakai lib chart yang sudah dipakai
   di proyek — cek `HotspotMatrix`/`BurnedAreaCard`; kalau belum ada, SVG
   sederhana). Warna kelas sama.
3. **Tabel** luas (ha) + persen per kelas × 6 tahun + kolom Δ 2020→2025.
4. **Ringkasan** `summary_text` + catatan: "'Hutan' = tutupan berpohon; kebun
   berpohon belum tentu terpisah. Estimasi satelit, bukan angka resmi."
5. **Kaki**: sumber, model (`RF {model_trees} pohon`), `n_training`,
   `oob_accuracy`, `computed_at`, `duration_s`.

### Konstanta warna kelas (`frontend/src/constants/landCover.ts`)

```ts
export const LAND_COVER_CLASSES = [
  { key: 'hutan',     label: 'Hutan',            color: '#1B7A3D' },
  { key: 'semak',     label: 'Semak/Belukar',    color: '#9CC55B' },
  { key: 'pertanian', label: 'Pertanian/Kebun',  color: '#E8B84B' },
  { key: 'terbuka',   label: 'Lahan Terbuka',    color: '#C97B4A' },
  { key: 'air',       label: 'Badan Air',        color: '#2E7BBF' },
] as const;
```

Dipakai bersama oleh peta, grafik, tabel, legenda.

## Test

### Backend — `app/tests/test_land_cover_service.py`

`ee` di-monkeypatch penuh (tak ada panggilan GEE nyata). `PostgresStore` pola
`_Disabled*` (bahaya #1 — WAJIB).

- `enabled` False saat env GEE kosong.
- `analyze_polygon` menolak `polygon_id` tak dikenal / layer_key di luar 2 itu.
- Remap Dynamic World 9→5 benar (unit test murni fungsi `_dw_label_to_class`),
  termasuk `built_area`/`snow` terbuang.
- Simpan: mock store merekam `DELETE` lama + `INSERT` `year_class` 30 baris
  (6×5) + `upsert land_cover_analysis` `status='done'` dgn `oob_accuracy` &
  `duration_s` terisi.
- `pct` per tahun berjumlah ~100.
- `net_change` = luas kelas 2025 − 2020.

### Backend — `app/tests/test_land_cover_api.py`

`conftest.py` autouse sudah mematikan `API_REQUIRE_AUTH`.

- `POST /analyze` tanpa admin key & tanpa JWT → 401; dengan key tapi GEE tak
  dikonfigurasi → 503.
- `POST` saat baris `status='running'` → 409; saat `status='done'` tanpa
  `force` → 409 `{"done":true}`.
- `GET /status` transisi `idle → running → done` (service di-stub, `_run_state`
  + kolom status di-set manual).
- `GET /result` → 404 sebelum `done`; sesudah → struktur `table`/`net_change`
  benar.
- `GET /overlay?year=2019` → 404 (di luar rentang).

### Frontend — `KpsDetailView.test.tsx` (tambahan)

- Bagian "Tutupan Lahan" muncul; state idle menampilkan tombol.
- Klik tombol → `POST analyze` terpanggil, UI pindah ke "Menghitung…".
- `GET /status` = `done` → tabel + legenda 5 kelas + warna dari konstanta.
- Ganti tahun di penggeser → `GET /overlay` dipanggil dgn `year` baru.

## Migrasi & deploy

- `CREATE TABLE` dijalankan otomatis di `_ensure_land_cover_tables` (pola
  `_ensure_*` store) — tidak ada skrip migrasi manual.
- `earthengine-api` sudah di `requirements.txt`. Tidak ada dependency Python
  baru (pakai `shapely` yang sudah ada; **tidak** butuh geopandas/fiona).
- `GEE_SERVICE_ACCOUNT_KEY_PATH` / `GEE_SERVICE_ACCOUNT_EMAIL` /
  `GEE_PROJECT_ID` sudah dikonsumsi `settings.gee_*` dan mount
  `HOST_GEE_KEY_PATH` sudah ada di `docker-compose.dokploy.yml` (dipakai jalur
  S2 bekas terbakar). Tidak ada perubahan compose.
- `deploy/nginx/etaseneu.conf`: tambah `location = /api/land-cover/analyze`
  ke grup `limit_req` 10r/m (sejajar `point-match/analyze` & `export`).
  Rebuild `web`.
- CLAUDE.md: tambah entri layanan `land_cover_service.py` + bagian
  frontend `KpsDetailView`; catat tabel `land_cover_*` di daftar mixin
  `postgres_store/`. **Ingatkan user redeploy manual (api + web).**

## Risiko

| Risiko | Mitigasi |
|---|---|
| Tulis ke DB produksi (tak ada staging) | Semua tabel baru & terisolasi; idempoten per `polygon_id`; hapus via `DELETE FROM land_cover_* WHERE polygon_metadata_id=` |
| Akurasi Dynamic World ~70-an% (hutan vs kebun berpohon tak terpisah) | Label estimasi eksplisit di UI; filter keyakinan ≥0,6; komposit tahunan; catatan "'Hutan' = tutupan berpohon"; pemisahan kebun lewat shp menyusul |
| Kuota / waktu GEE per klik (~1–3 mnt) | On-demand 1 poligon saja; rate-limit 10r/m; `bestEffort=True` + `maxPixels` batas; job async, tidak blok request |
| Poligon KPS sangat besar (>10.000 ha) → GEE timeout | `bestEffort=True`; kalau `reduceToVectors` gagal → simpan tabel luas saja, `year_geom` kosong (peta rona di-skip utk tahun itu, tabel tetap ada) |
| Tutupan awan bikin tahun tertentu tipis data | Median setahun penuh; kalau perlu, versi berikutnya sempitkan ke musim kemarau / naikkan jendela |
| Dua user klik poligon sama bersamaan | Guard `status='running'` → 409 |
| GEE service account tidak valid di server | `enabled` fail-closed → 503, tidak diam-diam menyimpan nol |

## Di luar lingkup (menyusul)

- Kelas **Pemukiman** dari shp terpisah (ditumpangkan sebagai mask setelah
  klasifikasi).
- Pemisahan **kebun berpohon** (sawit/karet) dari hutan alam lewat shp HGU /
  peta perkebunan.
- Sampling manual / QA titik training (lapisan 2 kalau akurasi kurang di
  wilayah tertentu).
- Satu model RF global tersimpan sebagai GEE asset (kalau nanti perlu analisis
  massal / konsistensi antar-KPS).
- Analisis massal semua poligon / scheduler.
- Validasi akurasi terhadap sampel lapangan atau peta tuplah KLHK.
- Penyempitan jendela komposit ke musim kemarau per wilayah.
- Ekspor hasil (Excel / shp) — mengikuti pola `export_service.py`.
