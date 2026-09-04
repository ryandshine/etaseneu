# CLAUDE.md

Panduan untuk Claude Code (dan agent lain) saat bekerja di repo ini.

## Apa sistem ini

**ETA SENEU** — sistem peringatan dini & rekapitulasi titik panas (hotspot) yang beririsan dengan
poligon **Perhutanan Sosial (KPS)** dan **Hutan Adat**. Backend FastAPI + PostgreSQL/PostGIS,
frontend React/Vite/TypeScript (peta Leaflet). Dipakai untuk memantau kebakaran hutan dan lahan di
kawasan-kawasan tersebut, dengan data hotspot dari NASA FIRMS dan data luas bekas terbakar dari
rekap resmi KLHK.

## ⚠️ Bahaya #1: TIDAK ADA pemisahan database dev/test/production

`backend/.env` (dan `.env.dokploy` di server) menunjuk ke **database produksi yang sama** yang
dipakai sistem yang sedang berjalan untuk pengguna sungguhan. Tidak ada database test terpisah.

Ini pernah benar-benar menyebabkan insiden produksi: test `LayerService` yang tidak menyuntikkan
store yang dinonaktifkan terhubung ke `DATABASE_URL` asli, melihat cuma direktori fixture kecil,
lalu `GeoJsonSyncService.sync_all()` menganggap SEMUA layer produksi lain "sudah dihapus" dan
menonaktifkannya. Lihat docstring `_DisabledPostgresStore` di `backend/app/tests/test_layer_service.py`.

**Aturan wajib**: setiap test yang menyentuh `PostgresStore`, `LayerService`, atau
`GeoJsonSyncService` HARUS menyuntikkan store yang dinonaktifkan (pola `_DisabledPostgresStore` /
`_Disabled*` / `DisabledStore` yang sudah dipakai di `test_layer_service.py`, `test_layers_api.py`,
`test_point_match_service.py`, `test_burned_area_report.py`, `test_burned_area_klhk_service.py`).
Jangan pernah menjalankan operasi tulis (sync, upsert, refresh) dari sesi eksplorasi/dev lokal tanpa
sadar bahwa itu langsung mengubah data produksi.

Sebelum menjalankan skrip satu-kali (migrasi data, backfill, dsb.) terhadap DB ini, pikirkan dua kali
— tidak ada "staging" untuk berlatih dulu.

## Arsitektur Backend (`backend/app/`)

```
api/            # satu file per domain: hotspots, hotspot_clusters, layers, polygons,
                # burned_area, land_cover, export, point_match, scheduler, stats, weather,
                # wind, cache, metrics, auth. router.py merakit semuanya ke api_router (prefix /api).
core/           # config.py (Settings via pydantic-settings), auth.py (admin API key + JWT multi-user)
models/         # Pydantic models: hotspots, layers, polygons, query (HotspotQuery)
services/       # logika bisnis (lihat di bawah)
services/postgres_store/  # paket mixin (lihat di bawah)
tests/          # ~34 file test datar, fixtures/shp/ untuk GeoJSON sampel
templates/      # Jinja2, dipakai agency_pdf_service.py (WeasyPrint)
main.py         # create_app(), CORS ke frontend_origin, lifespan menjadwalkan
                # scheduler hotspot & scheduler burned-area di background
```

### `services/postgres_store/` — paket mixin per domain

Dulu satu file 1500+ baris (God Object) yang mencampur 8 tanggung jawab; sekarang `PostgresStore`
di `__init__.py` cuma `class PostgresStore(_ConnectionMixin, _LayerRegistryMixin,
_PolygonMetadataMixin, _HistoryArchiveMixin, _CacheMixin, _SchedulerMetricsMixin,
_HotspotObservationMixin, _PolygonRelationMixin, _SpatialMatchMixin, _BurnedAreaMixin)` — API publik
tidak berubah (`from app.services.postgres_store import PostgresStore`).

| File | Tanggung jawab |
|---|---|
| `_base.py` | Koneksi psycopg (autocommit=True), probe `enabled`, helper JSON |
| `_layers.py` | Registry layer GeoJSON (tabel `layers`) |
| `_polygons.py` | Metadata poligon KPS/Hutan Adat (`polygon_metadata`) |
| `_history.py` | Arsip hotspot tahunan (`hotspot_history_archives`) |
| `_cache.py` | Cache generik berbasis tabel (`api_cache_entries`) |
| `_scheduler.py` | State/metrik scheduler sync NASA FIRMS (`hotspot_sync_state`) |
| `_hotspots.py` | Titik hotspot mentah dari NASA (`hotspot_observations`) |
| `_relations.py` | Relasi hotspot↔poligon + ringkasan agregat per tahun |
| `_spatial.py` | Pencocokan titik→poligon massal (fitur "Cek Titik ke KPS") |
| `_burned_area.py` | Luas bekas terbakar per poligon per bulan (`burned_area_summary`) |
| `_land_cover.py` | Tutupan lahan per poligon per tahun (`land_cover_analysis`, `land_cover_year_class`, `land_cover_year_geom`) |

Karena `connection()` pakai `autocommit=True`, temp table butuh `ON COMMIT PRESERVE ROWS`.

### Layanan kunci lain

- `hotspot_service.py` — orkestrasi fetch/filter hotspot NASA FIRMS vs layer aktif, caching, stats.
  **Punya `print(debug_log, flush=True)` di baris ~194** yang mencetak blok debug filter
  (rentang tanggal, jumlah sebelum/sesudah filter, hotspot pertama/terakhir) ke stdout di SETIAP
  query — bukan bug, memang disengaja untuk diagnosis "kenapa hasil ga sesuai filter", tapi berisik
  di log produksi dan tidak konsisten dengan modul lain yang pakai `logging`.
- `layer_service.py` — baca/list layer GeoJSON dari `SHP_DIR`, reproject ke WGS84 kalau perlu, beri
  nama ramah berdasar prefix filename (`PS_` → "Perhutanan Sosial", `HUTAN_ADAT` → "Hutan Adat").
  **Catatan**: dataset aktif saat ini `psagustus2026.geojson` TIDAK diawali `PS_`, jadi kemungkinan
  tampil dengan nama file mentah, bukan nama ramah — cek kalau ada laporan "nama layer aneh".
- `spatial_service.py` — filter titik-dalam-poligon pakai Shapely `STRtree`, cache in-process.
- `geojson_sync_service.py` — parse/normalisasi GeoJSON dari `SHP_DIR`, sync ke Postgres. Tempat
  fungsi `_field_value(properties, *keys)` — alias nama field lintas skema (KPS pakai `LEMBAGA`,
  Hutan Adat pakai `NAMA_MHA`/`NAMOBJ`). **Kalau menambah field baru dari properti GeoJSON, cek juga
  apakah `spatial_service.py` dan `layer_service.py` punya reimplementasi terpisah yang perlu ikut
  di-update** — pernah ada bug lembaga Hutan Adat tampil sebagai nama layer mentah karena dua
  tempat itu belum ikut dapat alias field yang sama.
- `burned_area_klhk_service.py` — streaming parse (via `ijson`) file GeoJSON resmi KLHK "Areal
  Kebakaran Hutan dan Lahan", filter cuma akurasi H/M (L dan data tidak lengkap dibuang sesuai aturan
  KLHK sendiri), map nama bulan Indonesia → angka bulan.
- `export_service.py` — Excel (openpyxl + chart) untuk laporan hotspot/skema/agency.
- `pdf_export_service.py` — PDF ReportLab (laporan umum, dibatasi 1500 baris tabel detail untuk
  performa — lihat `HOTSPOT_DETAIL_TABLE_MAX_ROWS`); `agency_pdf_service.py` — PDF WeasyPrint/Jinja2
  khusus per lembaga.
- `nasa_client.py` — wrapper httpx async ke NASA FIRMS CSV API. Sengaja LOG error mentah (bukan
  re-raise ke client) karena URL FIRMS menyertakan `MAP_KEY` rahasia di path-nya.
- `burned_area_service.py` — jalur GEE/MODIS/VIIRS **lama, sudah tidak dipakai** (lihat bahaya #2).
- `burned_area_s2_service.py` — **analisis MANDIRI** bekas terbakar dari Sentinel-2 L2A dNBR via GEE,
  supaya tidak perlu menunggu rekap KLHK. Dijalankan **manual lewat skrip**
  (`BurnedAreaS2Service().analyze_month(year, month)`), TIDAK ada endpoint admin/tombol UI/scheduler —
  frekuensinya ikut terbitnya rekap KLHK. Endpoint yang ada cuma `GET /api/burned-area/s2-overlay`
  (baca hasil untuk lapisan peta). Menyasar SEMUA poligon aktif
  (`psagustus2026` + `HUTAN_ADAT_APR26`), hotspot = penanda keyakinan bukan filter. Formula
  divalidasi: `dNBR = median(NBR pre) − median(NBR post)` (BUKAN max/min — ekstrem + ambang longgar
  menghasilkan ~20× KLHK), mask `dNBR≥0.40 AND dNDVI≥0.15 AND NDVI_pre≥0.30 AND MNDWI<−0.05 AND
  nobs≥2`, lalu `connectedPixelCount≥25` (~1 ha @ 20 m). Diproses per-provinsi (1 komposit raster per
  bbox provinsi + `reduceRegions` batched). Hasil disimpan di tabel **TERPISAH `s2_burned_area`**
  (mixin `postgres_store/_s2_burned_area.py`), TIDAK dicampur ke `burned_area_summary` — angkanya
  estimasi belum terverifikasi. Dua tempat tampil di frontend: lapisan peta utama "Estimasi
  Sentinel-2" (oranye putus-putus) di `HotspotMap.tsx` (`useS2BurnedAreaOverlay` →
  `GET /api/burned-area/s2-overlay`), DAN bagian "Estimasi bekas terbakar (Sentinel-2)" di kartu
  Detail KPS (`KpsDetailView.tsx` → `GET /api/burned-area/s2-summary?polygon_ids=...`), terpisah dari
  angka KLHK di kartu yang sama. Analisis dijalankan `analyze_month()` (butuh env GEE); menampilkan
  hasilnya TIDAK butuh env — cuma baca tabel.
- `land_cover_service.py` — **analisis tutupan lahan per poligon** KPS/Hutan Adat, 2021–2025 (5
  tahun, dipersempit dari 2020–2025 semula), dari
  Sentinel-2 L2A via GEE + Random Forest (`ee.Classifier.smileRandomForest`, guru label Google
  Dynamic World, filter keyakinan ≥0,6). **6 kelas**: `hutan|kebun|semak|pertanian|terbuka|air`
  (pemukiman di-skip; `kebun` = sawit, ditambahkan 2026-09-05). **Formula hasil audit 2026-09-05**
  (dibandingkan vs DW mentah/Hansen/Descals di 5 poligon; versi lama: luas berosilasi ratusan ha
  antar-tahun & sawit 271 ha di Muaro Jambi terhitung "hutan"): (1) komposit = median **musim
  kemarau Mei–Okt** (`DRY_SEASON`), celah di-`unmask` median setahun penuh; (2) label latih =
  **argmax rata-rata probabilitas DW** setahun (bukan `mode()` label — bisa beda kelas dari yang
  dipakai ambang keyakinan); (3) piksel DW=trees yang ada di peta sawit Descals
  (`BIOPAMA/GlobalOilPalm/v1`, ref 2019, kelas 1/2) dilabel `kebun` — peta itu cuma GURU, RF
  tetap mengklasifikasi tiap tahun dari citra; (4) `_postprocess_classified`: `setDefaultProjection`
  10 m → `unmask(DW tahun itu)` (lubang awan tadinya dibuang diam-diam, total < luas poligon) →
  `focal_mode` 3×3; (5) `_despike_years`: kelas t ≠ t−1 dan t−1 = t+1 → pakai t−1 (tahun ujung
  tidak diubah). OOB turun ke ~0,84 di area sawit — itu lebih jujur, bukan regresi. Karet/kebun
  campur berpohon masih "hutan". Kalau menambah kelas lagi: `CLASS_KEYS` ada di DUA tempat
  (`land_cover_service.py` + `postgres_store/_land_cover.py`) + `frontend/src/constants/landCover.ts`. **Hemat kuota GEE (2026-09-04)**: sampel latih 5 tahun
  di-`getInfo()` SEKALI lalu dikirim balik sebagai `FeatureCollection` literal
  (`_materialize_samples`) — tanpa ini tiap request berikutnya memaksa GEE mengulang
  `stratifiedSample` + komposit region ber-buffer 3 km dari nol; vektor per tahun = SATU
  `reduceToVectors` pakai `labelProperty="class_idx"` (bukan 1 panggilan per kelas); citra
  klasifikasi di-`clip(roi)` (buffer cuma untuk sampling). Total ≈ 12 request GEE per poligon
  (dulu ≈ 32). Jangan tambah `getInfo()` di dalam loop tahun/kelas tanpa alasan kuat. **Dua jebakan
  GEE yang pernah bikin peta rona KOSONG di produksi (2026-09-05) walau luasnya benar**: (1) citra
  hasil `.classify()` atas komposit median TIDAK berproyeksi (WGS84 1°) → `connectedPixelCount`
  MMU dihitung di skala 1° dan me-mask seluruh poligon; `_year_vectors_expr` WAJIB
  `setDefaultProjection("EPSG:3857", None, 10)` dulu. (2) `reduceToVectors` yang dievaluasi di
  DALAM `ee.Dictionary({...}).getInfo()` selalu mengembalikan 0 fitur (bahkan dengan `reproject`
  eksplisit) — `_year_evaluate` sengaja memakai DUA `getInfo()` terpisah (luas, lalu vektor),
  jangan digabung lagi demi hemat 5 request. Semua `reduceRegion`/`reduceToVectors`
  pakai `tileScale=GEE_TILE_SCALE` (4): poligon besar pernah gagal "User memory limit exceeded"
  (batas memori per-request GEE, bukan server kita); kalau masih habis, `_year_evaluate` mengulang
  SEKALI dengan vektor `VECTOR_FALLBACK_SCALE` (20 m) — luas per kelas tetap 10 m. On-demand: `POST /api/land-cover/analyze` `{polygon_id}` (query
  `?force=true` untuk analisis ulang) → job `BackgroundTasks` (`LandCoverService.analyze_polygon`,
  ~1–3 mnt), progres langkah live di dict modul-global `_LAND_COVER_RUN_STATE` (boleh hilang saat
  restart), **sumber kebenaran status = kolom `land_cover_analysis.status`**. Hasil di tabel
  TERPISAH `land_cover_analysis` / `land_cover_year_class` / `land_cover_year_geom` (mixin
  `postgres_store/_land_cover.py`, `_ensure_land_cover_tables` bikin tabel sendiri — tanpa migrasi
  manual) — di-cache permanen, tiap poligon dianalisis sekali. Baca hasil:
  `GET /api/land-cover/{status,result,overlay}` (TIDAK butuh env GEE). Guard: `not service.enabled`
  → 503; status `running` (poligon sendiri) → 409; status `done` tanpa `force` → 409. **Lock GLOBAL**
  (beda dari guard per-poligon di atas): `land_cover_any_running()` baca `_LAND_COVER_RUN_STATE`
  (dict proses, BUKAN kolom DB) — kalau poligon LAIN sedang beneran jalan di proses ini, `/analyze`
  balas 409 `{"busy_elsewhere": true}` dan `/status` ikut membawa `busy_elsewhere` — **`force` TIDAK
  melewati lock ini** (force cuma untuk override state basi poligon itu sendiri). Tujuannya satu
  analisis GEE/RF-training saja yang boleh jalan bersamaan di seluruh sistem, supaya user lain tidak
  rebutan kuota GEE/CPU. **Asumsi satu proses `api` (tanpa multi-worker)** — kalau nanti di-scale
  horizontal, lock ini perlu pindah ke DB/Redis. "Hutan" = tutupan berpohon (kebun berpohon seperti
  sawit/karet belum tentu terpisah).
  - **Fitur Sentinel-1 SAR + konsensus Hansen (2026-09-05, Langkah 2 menuju v3)**: paket
    `services/land_cover/` (sub-modul menerima `ee` sebagai argumen — TIDAK `import ee` di level
    modul). `sar.py`: `get_dominant_pass()` hitung scene ASC vs DESC `COPERNICUS/S1_GRD` (IW, VV+VH)
    untuk SELURUH rentang tahun dalam SATU `getInfo()` → satu orbit dipakai semua tahun (campur orbit
    = fitur berubah karena geometri pandang, bukan tutupan); seri/kosong/gagal → `DESCENDING`.
    `get_s1_composite()` = median tahunan VV/VH setelah `focal_median(15 m)` per scene, band
    `VH_VV_ratio = VH − VV` (band S1 sudah dB → rasio = selisih, BUKAN pembagian); mengembalikan
    `(image, size)` belum dievaluasi. `s1_scene_counts()` = jumlah scene per tahun, SATU `getInfo()`.
    Di service: `OPTICAL_FEATURE_NAMES` (12) + `SAR_FEATURE_NAMES` (3) = `FEATURE_NAMES` saat
    `USE_SAR`; per run `feature_names` ditentukan `_prepare_sar()` → SAR dipakai hanya kalau toggle
    nyala (`Settings.land_cover_use_sar`, env `LAND_COVER_USE_SAR`, default true) DAN tiap tahun punya
    ≥ `S1_MIN_SCENES` (4) scene; kalau tidak (S1B mati Des 2021 → 2022–2024 jarang di Indonesia
    timur), atau GEE gagal → **log warning, lanjut optik saja, tanpa exception**. SAR di-`addBands`
    ke komposit S2 SEBELUM `stratifiedSample` dan `classify()`; RF `inputProperties=feature_names`.
    `meta.feature_names` = fitur yang BENAR-BENAR dipakai; `meta.sar = {enabled, orbit_pass,
    scenes_per_year, min_scenes}` atau `{enabled:false, reason: toggle_off|no_count|
    insufficient_scenes|error: …}`. Biaya: +2 `getInfo()` per poligon (orbit + hitung scene).
    **Konsensus Hansen** (`_hansen_intact_forest`, `UMD/hansen/global_forest_change_2024_v1_12`):
    sampel latih DW=trees dibuang kecuali `treecover2000 ≥ 50` DAN (`lossyear == 0` ATAU
    `lossyear > tahun analisis`) — hutan yang sudah hilang sebelum/pada tahun itu tidak boleh jadi
    guru "hutan"; kelas lain tidak disentuh. `FORMULA_VERSION` masih 2 — dinaikkan ke 3 di langkah
    akhir (bersama `labels.py`/`temporal.py`) supaya badge "Metode lama" tidak muncul dua kali.
    Test: `test_land_cover_service.py` fake `_FakeColl.size_value` (class attr) mengatur jumlah
    scene S1 → jalur fallback diuji tanpa GEE.
  - **Versi formula & metadata (2026-09-05)**: `FORMULA_VERSION` / `FORMULA_LABEL` di
    `land_cover_service.py` (v1 = sebelum audit 2026-09-05, v2 = formula audit di atas). Kolom
    `land_cover_analysis.formula_version INTEGER`, `meta JSONB` (`method`, `feature_names`,
    `labels.sources`, `labels.samples_per_class`, `temporal.rules`, `coverage_pct` per tahun = Σ luas
    kelas ÷ luas geodesik poligon), `started_at` — ditambah `ALTER TABLE … ADD COLUMN IF NOT EXISTS`
    di `_ensure_land_cover_tables` (backfill: `computed_at < '2026-09-05'` → 1, sisanya 2).
    `_ensure_*` cuma jalan SEKALI per proses (flag kelas `_land_cover_tables_ready`).
    `save_land_cover_result` & `delete_land_cover_result` dibungkus `conn.transaction()` (koneksi
    autocommit → tanpa ini crash di tengah menyisakan baris `done` tanpa geometri). **Reset
    `running` basi berbasis UMUR** (`reset_stale_land_cover_running`, `LAND_COVER_STALE_RUNNING_MIN`
    = 30 mnt): dipanggil di `lifespan` startup + lazy di `read_land_cover_status` — SENGAJA bukan
    "semua running saat boot" karena `uvicorn` dev lokal memakai DB produksi yang sama (bahaya #1)
    dan bisa mematikan job yang beneran jalan di container produksi. `/status` membawa
    `formula_version` (tersimpan) + `current_formula_version`; `/polygons` membawa
    `land_cover_formula_version`; `/result.meta` ikut `current_formula_version`. Frontend:
    badge "Metode lama (vN)" di `LandCoverPanel` (dari `/status`) & di daftar `TutupanLahanView`
    (bandingkan dengan konstanta `LAND_COVER_FORMULA_VERSION` di `constants/landCover.ts` — **WAJIB
    dinaikkan bersamaan dengan `FORMULA_VERSION` backend**). Menaikkan versi TIDAK otomatis
    menghitung ulang: hasil lama tetap tampil dengan badge, admin hapus lalu jalankan lagi.
    **`POST /analyze` & `DELETE /result` = `Depends(require_admin_role)`** (role `user`/`bps` → 403);
    `LandCoverPanel`/`TutupanLahanView` terima prop `isAdmin` dari `App.tsx` (default false → tombol
    Jalankan/Hapus/Mulai ulang tidak dirender, diganti hint). Test API override
    `app.dependency_overrides[require_admin_role]`. nginx: `DELETE /api/land-cover/result` di zona
    `eta_delete` (10r/m, `map $request_method` → cuma DELETE yang dihitung).
  - **Menu tersendiri "Tutupan Lahan"** (`TutupanLahanView.tsx`, self-contained fetch sendiri lewat
    `authFetch` — pola sama seperti `KompleksKebakaranView.tsx`, TIDAK lewat `useDashboardData`):
    daftar SEMUA poligon KPS+Hutan Adat sekaligus status analisisnya (`GET /api/land-cover/polygons`
    — bulk `LEFT JOIN polygon_metadata ↔ land_cover_analysis`, method
    `list_polygons_with_land_cover_status` di `postgres_store/_land_cover.py`), cari + filter
    Provinsi/Kabupaten/Wilker BPS/Status (ringkas jadi tombol "Filter" + popover + pill yang bisa
    dilepas satu-satu, bukan 4 `<select>` berbaris — client-side, dasarnya masih pola Matriks Data),
    klik satu baris → detail me-reuse `LandCoverPanel.tsx` apa adanya. Detailnya dua tab
    ("Peta Spasial" default / "Tren Historis", state lokal `tab`, berbagi state `year` yang sama):
    tab Peta = peta jadi elemen dominan tunggal (`.lc-mapstage`, tinggi `70vh`) dengan toolbar tahun
    & grid ringkasan luas-per-kelas mengambang di atasnya (glassmorphism, `.lc-mapstage__toolbar` /
    `.lc-floatcard` — static/tanpa blur di layar <640px biar tidak menutupi peta); tab Tren = grafik
    garis multi-kelas (bukan stacked bar lagi — recharts `LineChart`), tabel Δ (sel ha tebal/persen
    redup bertingkat vertikal), ringkasan teks, tombol "Jalankan Analisis" manual — TIDAK ada tombol
    massal. Dari state `done` tombolnya **"Hapus hasil"** (`DELETE /api/land-cover/result?polygon_id=`
    → `delete_land_cover_result`, 409 kalau job poligon itu beneran sedang jalan) lalu kembali idle —
    BUKAN "Analisis ulang"; `?force=true` tetap ada cuma untuk "Mulai ulang" dari state running basi. Kelas yang tidak pernah punya luas ≥0,5 ha di poligon itu (`_MEANINGFUL_HA` — konstanta
    sama persis di frontend `LandCoverPanel.tsx` dan backend `land_cover_service.py`) disembunyikan
    total dari tabel/grafik/kartu (bukan ditampilkan "0 ha" yang merebut atensi); `_build_summary_text`
    juga pakai ambang yang sama supaya kalimat ringkasan tidak bilang "beralih ke X (+0 ha)" yang
    kontradiktif atau "naik 0 ha" saat perubahan hutan sebenarnya dianggap "relatif stabil".
    `LandCoverPanel` sekarang **cuma** dirender
    di sini (panel penuhnya dicabut dari `KpsDetailView.tsx`, diganti satu baris ringkas
    `.lc-summary-link` yang fetch `GET /api/land-cover/status` lalu buka menu ini via callback
    `onOpenTutupanLahan` dari `App.tsx`, pola sama seperti `onOpenKpsDetail`). URL
    `?view=landcover&polygon=<id>` bisa dibagikan (`App.tsx`). Konstanta warna kelas dipakai bersama
    di `frontend/src/constants/landCover.ts`. Tidak ada scheduler, tidak ada analisis massal. nginx:
    `POST /api/land-cover/analyze` di grup rate-limit `eta_heavy` (10r/m).
- `hotspot_cluster_service.py` — menu "Kompleks Kebakaran": mengelompokkan titik hotspot yang
  berdekatan ruang (~2km) DAN waktu (~48 jam) sekaligus jadi satu "kompleks" (ST-DBSCAN), dipanggil
  dari `GET /api/hotspots/clusters` (preset `sensitivity` ketat/sedang/longgar, bukan eps/min_samples
  mentah). Pasangan tetangga dihitung via self-join `ST_DWithin` di Postgres
  (`postgres_store/_hotspots.py::find_proximity_edges` — sengaja pakai derajat, BUKAN cast
  `::geography`, supaya index GIST di kolom `geom` tetap kepakai), lalu ekspansi klaster murni Python
  stdlib (BFS di `_graph_cluster`) — sengaja TIDAK pakai numpy/scipy/scikit-learn walau itu yang
  dipakai di prototipe awal, supaya `requirements.txt` tidak nambah dependency berat.

### Atribusi Fungsi Kawasan Hutan (KWSHUTAN_AR_250K KLHK)

Tiap hotspot & poligon estimasi bekas terbakar Sentinel-2 tahu masuk **fungsi kawasan hutan** yang
mana (Hutan Lindung / HP / HPT / HPK / KSA-KPA / APL, dikelompokkan Konservasi/Lindung/Produksi/
Non-Kawasan Hutan). Dibangun di luar repo langsung di DB (lihat `HANDOFF-fungsi-kawasan-hutan.md`),
BUKAN lewat migrasi app:

- **Tabel referensi DB** (dibuat manual via SQL, tidak ada `_ensure_*` di kode app):
  `ref_kawasan_hutan` + `ref_kawasan_hutan_sub` (geometri detail penuh, ~2 GB, cuma dipakai saat
  join), `hotspot_kawasan_hutan` (lookup `hotspot_id → fungsikws/nama_kawasan/kelompok`),
  `burned_kawasan_hutan` (rincian `s2_burned_area.id × fungsi kawasan → luas_ha`),
  `ref_fungsi_kawasan_label` (`kode numeric → singkatan/fungsi/kelompok`),
  `burned_kemenhut_kawasan_hutan` (luas terbakar resmi × fungsi). Fungsi SQL
  `refresh_kawasan_attribution()` me-refresh lookup (inkremental untuk hotspot, rebuild penuh untuk
  burned S2 + burned Kemenhut) — cron harian 04:15 di host (`docker exec gealgeolgeo-postgis psql
  ... -c "SELECT refresh_kawasan_attribution();"`). **Sekarang juga dipanggil dari app**:
  otomatis di akhir `POST /api/burned-area/refresh-klhk`, dan lewat tombol "Segarkan Atribusi
  Kawasan Hutan" di Pengaturan → `POST /api/burned-area/refresh-kawasan` (admin) →
  `_burned_area.py::refresh_kawasan_attribution()` (guard `self.enabled`; test WAJIB
  monkeypatch method kelas ini — pernah lolos & jalan di DB produksi saat test).
  - **Otoritas kode FUNGSIKWS = renderer resmi layanan ArcGIS Planologi**
    (`.../KWSHUTAN_AR_250K/MapServer/0?f=json` → `drawingInfo.renderer.uniqueValueInfos`), bukan
    tebakan. Handoff awal salah geser (100100 dikira KSA-KPA); dikoreksi 2026-09-01:
    **100100=Hutan Lindung, 100300=HP Tetap, 100400=HPT, 100500=HPK, 100700=APL**, `1002xx`=Konservasi.
    `fungsi_kawasan_kelompok()` diubah dari range prefix ke enumerasi. `refresh` inkremental TIDAK
    menulis ulang `kelompok` baris hotspot lama → kalau mapping berubah lagi, jalankan sekali:
    `UPDATE hotspot_kawasan_hutan SET kelompok = fungsi_kawasan_kelompok(fungsikws);`. Query enrich
    ambil `fungsi`/`singkatan`/`kelompok` dari `ref_fungsi_kawasan_label` live (`COALESCE(lbl.*, hkh.*)`),
    jadi koreksi label langsung kelihatan tanpa refresh.
- **Enrich di request path = LEFT JOIN saja, tanpa operasi spasial baru**:
  `postgres_store/_hotspots.py::read_hotspot_observations()` LEFT JOIN `hotspot_kawasan_hutan` +
  `ref_fungsi_kawasan_label` → `payload["kawasan_hutan"] = {kode, fungsi, singkatan, nama_kawasan,
  kelompok}` (key tidak ada kalau titik di luar semua kawasan). `hotspot_service._hydrate_polygon_metadata`
  meneruskan key top-level itu apa adanya. `postgres_store/_s2_burned_area.py::read_s2_burned_area_for_polygons()`
  & `read_s2_burned_area_overlay()` LEFT JOIN LATERAL `burned_kawasan_hutan` → `kawasan_rincian`
  (list per fungsi) + `kawasan_dominan` (kelompok terluas).
- **`get_hotspots_in_range()` (jalur cluster/Kompleks Kebakaran) sengaja TIDAK di-enrich** — outputnya
  cuma untuk UI klaster, bukan laporan. Tambah LEFT JOIN yang sama kalau nanti masuk PDF/XLSX.
- **Surface backend**: `helper polygon_fields.fungsi_kawasan/nama_kawasan_hutan/kelompok_kawasan`;
  XLSX sheet "Data Hotspot" 3 kolom baru di akhir ("Fungsi Kawasan Hutan", "Nama Kawasan",
  "Kelompok"); PDF `create_detailed_hotspot_rows` kolom "Fungsi Kawasan" (lebar tabel tetap 769pt);
  API peta `_to_map_hotspot` cuma `fungsi_kawasan` + `kelompok` ringkas; `GET /api/burned-area/s2-summary`
  & `s2-overlay` bawa `kawasan_rincian`/`kawasan_dominan`.
- **Surface frontend**: `mapHotspotRecordToDashboardHotspot` (`lib/hotspotDisplay.ts`) memetakan
  jadi `fungsiKawasan/namaKawasan/kelompokKawasan` (ambil dari objek `kawasan_hutan` view=full ATAU
  field datar `fungsi_kawasan`/`kelompok` view=map). Tampil di: popup titik hotspot
  (`HotspotPopupContent.tsx`, dipakai peta utama + peta KpsDetail), popup overlay "Estimasi Bekas
  Terbakar" Sentinel-2 di `HotspotMap.tsx` (baris `kawasan_dominan`), kartu "Segmen Lokasi" di
  `KpsDetailView.tsx`, dan **2 kartu di Matriks Data** (`HotspotMatrix.tsx`): "Titik per Kawasan
  Hutan" (hitung client-side dari hotspot yang ter-filter) + "Luas Kebakaran per Kawasan Hutan"
  (fetch endpoint di bawah, ikut filter provinsi Buku Besar).
- **Luas terbakar resmi × fungsi kawasan**: tabel materialized `burned_kemenhut_kawasan_hutan`
  (`polygon_metadata_id, fungsikws, kelompok, luas_ha`) di-rebuild `refresh_kawasan_attribution()`
  (union geometry `burned_area_summary` per KPS lintas bulan → iris `ref_kawasan_hutan_sub`; jumlah
  pecahan = total resmi 10.056 ha). `GET /api/burned-area/kawasan-summary?province=…` →
  `postgres_store/_burned_area.py::read_burned_area_by_kawasan()` (label live dari
  `ref_fungsi_kawasan_label`). Data resmi tersedia Jan–Jul 2026.
- **Overlay peta**: raster LIVE dari layanan ArcGIS resmi Ditjen Planologi Kehutanan
  (`geoportal.planologi.kehutanan.go.id/.../KWSHUTAN_AR_250K/MapServer`, readonly). Layanan tanpa
  WMSServer & tanpa tile cache → `components/KawasanHutanLayer.tsx` = `L.TileLayer` di-extend, minta
  endpoint `export` per-tile (bbox-per-tile ala `L.TileLayer.WMS`). Simbol/warna dari server;
  `constants/kawasanHutan.ts` cuma URL + salinan legenda. Tombol "Fungsi Kawasan Hutan" di
  `HotspotMap.tsx` **default NYALA** (mobile & desktop, sejak 2026-09-04 — sebelumnya mati),
  pane `kawasan-hutan` z360. Saat menyala, isian poligon KPS
  (`batas-kps`) dimatikan (garis batas saja) supaya warna kawasan tidak ketutup tint hijau KPS.
  BUKAN dari file geojson — file KWSHUTAN 1:250k JANGAN ditaruh di `SHP_DIR` (pernah bikin
  `list_preview_layers()` 135 dtk + payload 70 MB + `sync_all()` menulis 30k `polygon_metadata` +
  26k `hotspot_polygon_relation`, sudah di-DELETE) dan JANGAN dicoba di-dissolve/simplify
  (`ST_Union`/`ogr2ogr -simplify` selalu gagal: mixed-dimension, free-hole-to-shell). Raw ada di
  `SHP_DIR/fungsi_kawasan_hutan.geojson.raw` (di luar glob) sebagai arsip user.
  nginx `/api/layers` cache dipangkas 1 jam+SWR24jam → 120 dtk supaya daftar layer yang dihapus
  tidak nyangkut lama di browser/CDN.

## ⚠️ Bahaya #2: GEE sudah digantikan KLHK untuk luas bekas terbakar

Google Earth Engine (MODIS/VIIRS) BUKAN lagi sumber data luas terbakar. Sumber resmi sekarang: file
GeoJSON KLHK "Areal Kebakaran Hutan dan Lahan" yang di-SFTP admin ke `KLHK_BURNED_AREA_DIR`, lalu
di-refresh manual lewat `POST /api/burned-area/refresh-klhk`. `burned_area_scheduler_enabled`
default **False** karena rekap KLHK terbit tidak dengan jadwal tetap (beda dari citra satelit
bulanan). Jangan asumsikan kredensial GEE perlu dikonfigurasi — kode GEE lama masih ada tapi tidak
dipanggil otomatis.

Konsekuensi teknis: `ijson` (di `requirements.txt`) dipakai untuk streaming-parse file KLHK yang bisa
ratusan MB tanpa load penuh ke memori. **`ijson` mengembalikan `Decimal` untuk angka** — kalau
serialize geometry hasil parsingnya ke JSON, wajib `json.dumps(geom, default=float)` (lihat contoh di
`postgres_store/_burned_area.py`), atau akan error `Object of type Decimal is not JSON serializable`.

## Frontend (`frontend/src/`)

```
components/   HotspotMap.tsx (peta Leaflet. Pane: `batas-kps` z400 non-interaktif;
              `kps-interaktif` z420 dipakai BERSAMA polygon bekas terbakar + titik
              hotspot supaya polygon tetap bisa diklik. Titik hotspot dipaksa
              `bringToFront()` tiap render. KONSEKUENSI: `<Popup>` di dalam pane itu
              mewarisi pane z420 dan ketutup marker -> WAJIB `pane="popupPane"` di tiap
              `<Popup>` hotspot, kalau tidak tombol di dalamnya tidak bisa diklik.
              Batas KPS TETAP non-interaktif; info poligon saat diklik ditangani
              `PolygonInfoLayer.tsx` = `useMapEvents({click})` + uji titik-dalam-poligon
              sisi klien (`lib/polygonHit.ts`) atas geojson layer yang termuat, lalu
              satu popup gabungan (layer apa + lembaga/skema/wilayah). Aman karena klik
              hotspot/bekas-terbakar sudah `DomEvent.stop` lewat bindPopup -> map click
              tidak fire -- TAPI cuma untuk hit pas di geometri. `preferCanvas` + titik
              radius 7 -> uji-klik canvas = `radius + renderer.options.tolerance`; renderer
              pane default `tolerance` 0 = target tap ~8px, meleset dikit di HP -> lolos ke
              `PolygonInfoLayer`, muncul popup "Poligon di titik ini" bukan popup hotspot.
              FIX: (1) satu `L.canvas({ pane:"kps-interaktif", tolerance:18 })` dipakai
              bareng SEMUA layer api di pane itu (dua `<GeoJSON>` bekas terbakar via spread
              `{...fireRendererProp}` karena react-leaflet tak mengetik `renderer`, plus
              `pointToLayer` circleMarker & `<CircleMarker>` hotspot) -- target tap ~25px;
              (2) `PolygonInfoLayer` terima prop `hotspots` -> kalau tap dalam 30px dari
              titik mana pun, popup poligon TIDAK ditampilkan (return lebih dulu). Wajib
              SATU canvas: canvas terpisah bikin yang atas menelan klik yang bawah. Sama di
              `KpsDetailView.tsx`. Kalau overlay Fungsi Kawasan Hutan nyala, fungsi kawasan di
              titik itu ikut (fetch `GET /api/burned-area/kawasan-at?lat=&lon=` ->
              `_burned_area.py::read_kawasan_at_point`, `ST_Contains` ke `ref_kawasan_hutan_sub`)),
              HotspotMatrix.tsx ("Matriks Data"), KpsDetailView.tsx,
              KompleksKebakaranView.tsx ("Kompleks Kebakaran" — peta+daftar klaster
              hotspot ST-DBSCAN, self-contained fetch sendiri lewat lib/api.ts, TIDAK
              lewat useDashboardData), FilterPanel.tsx, SidebarNav.tsx (satu area gulir
              di `.side-rail`; menu Pengaturan menampilkan info akun untuk semua role,
              prop `isAdmin` → role user hanya tidak melihat tombol Sync/Prewarm).
              **Sidebar collapse (icon rail)** — HANYA aktif di desktop lebar
              (`hooks/useIsDesktopWide.ts`, matchMedia `>=1024px`); preferensi user
              (`localStorage` `etaseneu.sidebar.collapsed.v1`, default expanded) digabung
              dengan cek viewport itu SEKALI di `App.tsx` (`sidebarCollapsed =
              sidebarCollapsedPref && isDesktopWide`) lalu diteruskan ke `SidebarNav` sebagai
              prop `collapsed` yang sudah final — `SidebarNav` sendiri TIDAK cek viewport
              lagi. Sengaja dibatasi desktop-only: lebar sidebar tablet (640-1023px, fixed
              200px hardcoded) & mobile (off-canvas drawer, <640px) diatur tiga aturan CSS
              terpisah yang sudah pernah bikin bug (lihat komentar `.app-frame`/`.side-rail`
              di index.css) — collapse cuma nambah SATU aturan aditif baru
              (`.app-frame--collapsed` scoped `@media (min-width:1024px)`), tidak menyentuh
              tiga itu. Saat collapsed: label teks nav disembunyikan tapi `aria-label` tetap
              ada (nama aksesibel tidak berubah, query test berbasis `getByRole(...,{name})`
              tetap valid); `filterSlot` (FilterPanel, cuma ada di Live Map) jadi tombol ikon
              yang buka flyout `.side-filter-popover` ke kanan; blok status sinkronisasi
              (grid last-sync/next-sync/scheduler/dst) diringkas SENGAJA jadi cuma titik
              kesehatan + 2 tombol ikon admin (Sync/Prewarm langsung, tanpa detail) — bukan
              dipadatkan jadi tooltip, karena grid itu tidak masuk akal diringkas tanpa
              kehilangan makna; detail lengkap kembali begitu di-expand.
              BurnedAreaCard.tsx, WeatherOverlay.tsx, dll.
              PETA LIVE — MOBILE vs DESKTOP DIVERGEN: `HotspotMap.tsx` pakai
              `hooks/useIsMobile.ts` (matchMedia `<=639px`). Di desktop kontrol
              tetap mengambang (`.map-legend`, `.locate-btn`, `.burned-control`,
              `.basemap-switcher`, `<ZoomControl>`) — di mobile SEMUA itu TIDAK
              dirender, diganti `MapControls.tsx` (kolom FAB kanan-bawah: zoom
              +/- via instance peta dari `ref` MapContainer, + lokasi-saya) dan
              `MapSheet.tsx` (bottom sheet 3-detent peek/half/full berisi
              Lapisan+Basemap+Legenda+Ringkasan). "Ringkasan" di sheet menghitung
              ulang T/S/R + per-satelit dari prop `hotspots` dengan algoritma
              IDENTIK `App.tsx::dynamicConfidenceStats` — kalau ambang FRP/
              normalisasi nama satelit diubah di satu tempat, ubah juga di sini.
              Panel statistik + `.stats-sheet-toggle` + `.ui-toggle-btn` milik
              App.tsx disembunyikan via CSS di `@media (max-width:639px)`
              (`.workspace-stage--map ...`) supaya tidak ada dua sheet.
              `<ScaleControl>` (react-leaflet, metrik) dirender di SEMUA lebar.
              Mock `react-leaflet` di test WAJIB ekspor `ScaleControl`
              (App.test.tsx, HotspotMap.test.tsx sudah).
              **Pemutar waktu "Timeline"** (toggle default mati; desktop di deret
              `burned-control`, mobile baris di `MapSheet` via prop
              `onToggleTimeline`): `hooks/useHotspotTimeline.ts` + fungsi murni
              `lib/hotspotTimeline.ts` (bucketing granularitas otomatis 1j/3j/1h
              ≤120 frame, `opacityForBucket` kumulatif-berpudar, label WIB) —
              loop `setInterval` `TICK_MS/speed`, kecepatan 1/2/4×. Daftar marker
              diekstrak ke `HotspotMarkersLayer` (`React.memo`) — playback TIDAK
              me-render ulang list: `useEffect` driver menata style tiap marker
              imperatif lewat `markerRefs` (`Map<id, L.CircleMarker|L.Marker>`,
              diisi callback-ref) → `applyMarkerOpacity` (setStyle/setOpacity +
              `interactive=false` untuk titik "masa depan"). Bar kontrol
              `HotspotTimelineControl.tsx` (histogram-scrubber + `<input
              type=range>` a11y) dirender di `.map-frame` DI LUAR `<MapContainer>`.
              Murni client-side atas `hotspots` termuat; tak ada endpoint/persist.
              `openKpsDetail` di `App.tsx` di-`useCallback` demi memo ini. Mock
              `CircleMarker`/`Marker` di HotspotMap.test.tsx WAJIB `forwardRef`.
              **Tata letak kontrol melayang (desktop)**: kolom kiri = Lokasi+
              Basemap (top 1rem) → `.burned-control` (top 6.5rem, gulir) →
              `.map-legend` (bottom 6.5rem) → zoom. `max-height` burned-control
              WAJIB menyisakan ruang legenda (`calc(100% - 6.5rem - 16rem)`),
              bukan cuma zoom — dulu 5.5rem dan di laptop 1366×768 kolom itu
              menimpa legenda. `@media (min-width:640px) and (max-height:820px)`
              legenda jadi mendatar. `.timeline-control` TIDAK dipusatkan pakai
              translate: dijepit `left:17rem; right:20rem; max-width:680px;
              margin:auto` (lolos legenda kiri & panel statistik kanan) dan
              `bottom:4.75rem` di atas tombol "Sembunyikan UI" (`.ui-toggle-btn`,
              juga bawah-tengah). Tablet 640–1023px: pemutar melebar penuh dan
              legenda disembunyikan via `.map-frame:has(.timeline-control)`.
hooks/        useDashboardData.ts (hook utama, ~800 baris — lihat di bawah),
              useBurnedAreaOverlay.ts, useIsMobile.ts
lib/          api.ts (client fetch bertipe; `authFetch`/`downloadWithAuth` untuk panggilan
              /api langsung — WAJIB dipakai ganti `fetch` mentah supaya token JWT ikut saat
              API_REQUIRE_AUTH menyala), date.ts (helper WIB/Asia-Jakarta), hotspotDisplay.ts
constants/    satellites.ts, time-windows.ts (TimePreset: 24h/48h/3d/7d/30d/custom),
              map.ts (`SMOOTH_ZOOM_MAP_PROPS` dipakai di 3 peta: scrollWheelZoom off +
              smoothWheelZoom on lewat lib/leaflet-smooth-wheel-zoom.ts [vendor, MIT];
              zoomSnap 0.25/zoomDelta 0.5 untuk pinch/tombol/fitBounds)
test/         Vitest — *.test.tsx
```

`useDashboardData.ts` adalah satu-satunya hook yang memegang hampir seluruh state dashboard: daftar
layer & hotspot dari API, filter satelit & rentang waktu (preset atau custom), status
loading/error per aksi, stats turunan, status scheduler/history/geojson/storage, dan semua aksi
imperatif (`exportDashboard`, `exportPdf`, `prewarmHistory`, `manualSync`, dll) masing-masing dengan
busy-flag dan pesan error sendiri. Dipanggil SATU KALI di `App.tsx` dan hasilnya dibagi ke semua view
(map/matrix/kps/settings) — jangan buat instance kedua dari hook ini di komponen lain, nanti state
filter waktu tidak sinkron antar-view.

Catatan preset waktu: untuk preset selain "custom" (24 Jam/48 Jam/dst), jendela waktu dihitung relatif
ke `endDate` (state "custom end date"), bukan selalu ke waktu sekarang — normalnya `endDate` = hari
ini, tapi kalau pernah diubah lewat mode Custom lalu berpindah ke preset lain, `endDate` TIDAK
otomatis kembali ke hari ini (lihat komentar di `buildTimeRange`).

Persistensi state (`lib/dashboardPersistence.ts`, dipakai `useDashboardData`): Chrome Android agresif
men-discard tab latar → cold-boot bikin dashboard kosong + reset filter. Dua hal disimpan di
localStorage (kunci ber-versi `etaseneu.dashboard.{filters,cache}.v1`, semua akses `try/catch`):
(1) **filter** — preset waktu, satelit, tanggal custom; dipulihkan saat mount (tanggal custom hanya
kalau preset = `custom`, biar preset lain tetap relatif hari ini). (2) **cache data** — `layers` +
`hotspots` + `remoteStats` terakhir, TTL 6 jam, cap 6000 titik, degradasi bertahap kalau kuota penuh
(kosongkan `geojson` layer → potong hotspot). Cache cuma placeholder visual: kalau ada, boot tidak
menampilkan overlay loading, `isInitLoaded` mulai `true`, `loadInitialData()` tetap jalan diam-diam
dan menimpa (kalau gagal → tetap tampilkan data cache + `loadError`, tidak blank). Hook mengembalikan
`usingCachedData` → banner "Menampilkan data tersimpan — memperbarui…" di `App.tsx`. Cache dihapus
saat logout & saat 401 (`clearDashboardCache`), supaya data user lain tidak bocor sekilas. **Kalau
mengubah bentuk `DashboardHotspot`/`DashboardLayer`, naikkan versi kunci cache.** Filter wilker
(state lokal `HotspotMatrix`) BELUM ikut dipersist.

## Testing

**Backend**: `cd backend && .venv/bin/python -m pytest app/tests -q` (pytest-cov terpasang tapi
`--cov` tidak di-wire otomatis di config manapun — tambahkan manual kalau perlu coverage). WAJIB baca
bahaya #1 di atas sebelum menulis test baru yang menyentuh Postgres/layer sync.

**Frontend**: `npm test` (vitest run, environment jsdom). Tidak ada script `lint` terpisah — `npm run
build` (`tsc --noEmit && vite build`) merangkap sebagai typecheck. Tidak ada config ESLint di repo ini.

## Menjalankan lokal

- Backend: `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload` — **cek
  `frontend/vite.config.ts` dulu untuk port proxy aktif** (saat ini `127.0.0.1:8011`, BUKAN 8000
  seperti disebut README — README belum di-update mengikuti port proxy yang dipakai).
- Frontend: `cd frontend && npm run dev` (default Vite, port bisa 5173/5174/5180 tergantung yang
  sedang dipakai/bebas).
- Postgres produksi ada di `127.0.0.1:5434` (bukan 5432 default) — lihat `backend/.env`.

## Deploy

Manual lewat Dokploy, TIDAK ada auto-deploy on push. Alurnya: build image dari
`docker-compose.dokploy.yml` (`Dockerfile.api` + `Dockerfile.web`), lalu trigger deploy manual di
Dokploy UI. Setelah mengubah backend/frontend, **selalu ingatkan user untuk redeploy manual**.

Volume mount penting (read-only) ke container `api`: `HOST_SHP_DIR` → `/app/shp` (GeoJSON KPS/Hutan
Adat), `HOST_KLHK_BURNED_AREA_DIR` → `/app/burned_area_klhk`, `HOST_GEE_KEY_PATH` → kredensial GEE
(legacy). Postgres TIDAK dikontainerisasi — jalan di host, diakses lewat
`host.docker.internal:5434` (compose set `extra_hosts`).

Kalau menambah dependency Python baru yang dipakai backend, **jangan lupa tambahkan ke
`backend/requirements.txt`** — env dev lokal (venv) dan image produksi (`pip install -r
requirements.txt`) tidak otomatis sinkron. Ini pernah menyebabkan outage produksi (502 di semua
endpoint) karena `ijson` terpasang di venv lokal tapi lupa ditambahkan ke `requirements.txt`.

`deploy/nginx/etaseneu.conf` (disalin ke `web` saat build, di-`include` nginx pada konteks `http`)
memasang: security header (`X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy`, HSTS) — diulang di `location` yang punya `add_header` sendiri karena nginx
mengganti bukan menggabung; **CSP `Content-Security-Policy-Report-Only`** (belum enforce — flip nama
header ke `Content-Security-Policy` setelah console browser bersih); `limit_req` (login 5r/m,
`point-match/analyze` & `export` 10r/m, umum 20r/s burst 40) + `real_ip` dari `X-Forwarded-For` (wajib
di belakang Traefik); `location = /sw.js` & `/registerSW.js` & `/manifest.webmanifest` pakai
`Cache-Control: no-cache` (file PWA bernama tetap, bukan ber-hash — kalau `sw.js` ke-cache lama
update aplikasi tidak pernah sampai; `location =` menang atas regex `\.(js|…)$ immutable`). Ubah file
ini → rebuild `web`. Uji `nginx -t` via
`docker run --rm --add-host api:127.0.0.1 -v $PWD/deploy/nginx/etaseneu.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine nginx -t`.

**PWA** (`vite-plugin-pwa`, config di `frontend/vite.config.ts`): `registerType: autoUpdate`,
`injectRegister: auto` (registrasi lewat `/registerSW.js` yang di-inject ke `index.html` saat build —
tidak ada import di source, jadi vitest tidak terpengaruh). Service worker `generateSW` **hanya
precache app shell** (JS/CSS/HTML ber-hash, ~1 MB) — `/api` SENGAJA tidak di-cache SW (caching data
ada di `lib/dashboardPersistence.ts` yang tahu cara revalidasi; SW yang menyajikan JSON API basi
malah mem-bypass itu). `navigateFallbackDenylist: [/^\/api\//]`. Manifest + ikon (`public/pwa-*.png`,
`apple-touch-icon.png`, "ES" oranye di latar gelap) di-generate manual. CSP report-only sudah
menambah `worker-src 'self'; manifest-src 'self'`. `sw.js` memanggil `skipWaiting` + `clientsClaim`
(otomatis dari `autoUpdate`), tapi `registerSW.js` bawaan TIDAK me-reload halaman yang sedang jalan
→ `lib/swReload.ts` (`watchServiceWorkerUpdate`, dipanggil di `main.tsx`) dengar `controllerchange`
dan `location.reload()` SEKALI saat SW baru mengambil alih (aktivasi pertama di-skip). Konsekuensi:
setelah deploy, kunjungan berikutnya reload sendiri sekali ke bundle baru — tidak perlu tutup semua
tab dulu.

## Autentikasi

Dua mekanisme TERPISAH, jangan disamakan:

- **`ADMIN_API_KEY`** — melindungi endpoint admin per-request (upload geojson, trigger sync, refresh
  cache, prewarm, `/api/layers` mode penuh). Header `X-Admin-Key`, diverifikasi lewat
  `POST /api/auth/verify` (`core/auth.py::verify_admin_key`). Dipicu dari modal "Pengaturan"
  (`PasswordGateModal.tsx`). Fail-closed (env kosong → 503).
- **Login multi-user berbasis JWT** (gerbang SELURUH tampilan aplikasi) — awalnya satu password
  bersama (`APP_LOGIN_PASSWORD`, 2026-08-24), sejak itu dikembangkan jadi sistem akun sungguhan
  dengan tabel `app_users` (`id`, `username`, `password_hash` [bcrypt], `role` ∈ {`admin`,`user`},
  `created_at`, `updated_at`) via mixin `postgres_store/_users.py`. Login (`POST /api/auth/login`,
  `core/auth.py`) mem-verifikasi lewat `verify_password`, lalu menerbitkan JWT (`issue_token`, HS256,
  30 hari) berisi klaim `sub`/`username`/`role`. Token login dicatat sebagai hash di tabel
  `app_sessions` agar bisa diverifikasi dan direvoke per akun. Endpoint lain membaca token via header
  `Authorization: Bearer <token>` lewat dependency `require_authenticated_user` /
  `require_admin_role`.
  - Saat tabel `app_users` masih kosong, login pertama otomatis mem-seed satu akun `admin` dari
    `APP_LOGIN_PASSWORD` (`ensure_seed_admin`) — env ini sekarang cuma dipakai untuk seed awal,
    bukan lagi dicek langsung tiap login.
  - Manajemen user (list/create/ubah role/ganti password/hapus) ada di `GET/POST/PATCH/DELETE
    /api/auth/users/*`, semuanya `Depends(require_admin_role)`, dirender di tab Pengaturan lewat
    `UserManagementPanel.tsx` (cuma muncul kalau `session.role === "admin"`). Tersedia jumlah sesi
    aktif dan endpoint revoke seluruh sesi akun (untuk akun sendiri, sesi yang sedang dipakai dipertahankan).
    Dua guard penting:
    tidak bisa hapus akun sendiri, dan tidak bisa hapus/demote admin terakhir
    (`count_admins() <= 1`).
  - `AUTH_JWT_SECRET` — **beda sifat** dari `ADMIN_API_KEY`/`APP_LOGIN_PASSWORD`: kalau kosong,
    `get_settings()` auto-generate secret random tiap restart server (bukan fail-closed 503).
    Konsekuensinya cuma "semua sesi JWT jadi invalid, semua orang login ulang" — bukan seluruh situs
    terkunci. Sengaja dibuat begini untuk menghindari mengulang insiden lockout produksi
    `APP_LOGIN_PASSWORD` di bawah. Production sebaiknya tetap set nilai tetap biar sesi tidak hilang
    tiap deploy, tapi ini opsional, bukan wajib.

Session (token + username + role) disimpan di localStorage agar reload/reset halaman tidak memaksa
login ulang. Saat aplikasi dibuka, token diverifikasi ulang lewat `GET /api/auth/session`; logout
lokal juga memanggil `POST /api/auth/logout`. `AUTH_JWT_SECRET` harus tetap di produksi agar token
tidak invalid saat container restart.

**Cloudflare Turnstile di halaman login** (widget "verifikasi manusia"). Dua env terpisah:
`TURNSTILE_SECRET_KEY` (backend, `.env`) + `VITE_TURNSTILE_SITE_KEY` (frontend, di-*bake* saat `vite
build` — bukan runtime). **Sifat fail-open, sama seperti `AUTH_JWT_SECRET`**: kalau
`TURNSTILE_SECRET_KEY` kosong, `POST /api/auth/login` melewati cek captcha sepenuhnya; kalau
`VITE_TURNSTILE_SITE_KEY` kosong, `LoginPage.tsx` tidak merender widget & tombol tidak diblok.
Sengaja begini supaya menambah/melepas captcha tidak bisa mengunci situs (beda dari insiden
`APP_LOGIN_PASSWORD` di bawah). Backend memverifikasi `turnstile_token` ke
`challenges.cloudflare.com/turnstile/v0/siteverify` lewat `services/turnstile_service.py` (semua
kegagalan jaringan → tolak). Cek captcha jalan **sebelum** cek password. `index.html` memuat
`challenges.cloudflare.com/turnstile/v0/api.js` (async defer) tanpa syarat — kalau nanti ada CSP,
`script-src` **dan** `frame-src` harus mengizinkan `https://challenges.cloudflare.com`. Test key resmi
Cloudflare (selalu lolos) ada di kedua `.env.example`. Di produksi **kedua var diisi di tab
Environment stack Dokploy, BUKAN di `.env.dokploy`**: `TURNSTILE_SECRET_KEY` di-*forward* ke container
`api` lewat `environment: TURNSTILE_SECRET_KEY: ${TURNSTILE_SECRET_KEY:-}` di
`docker-compose.dokploy.yml` (service `api` cuma `env_file` → var tab Environment tidak otomatis masuk
container, itu sebabnya perlu baris `environment:` ini); `VITE_TURNSTILE_SITE_KEY` jadi build arg
image `web` (`web.build.args` → `Dockerfile.web` `ARG` → `.env.production.local`, menimpa default
`frontend/.env.production` yang sudah berisi site key produksi). Sebelum `TURNSTILE_SECRET_KEY` diisi,
verifikasi backend non-aktif (widget tetap tampil dari site key yang di-*commit*). Cara cek cepat
apakah enforcement hidup: `POST /api/auth/login` tanpa `turnstile_token` → **400** kalau aktif, **401**
kalau masih fail-open.

**Gate auth API baca** (`API_REQUIRE_AUTH`, default `false`). Historisnya gerbang login HANYA
mengunci tampilan front-end — endpoint baca publik bisa diakses tanpa login. Sejak fitur ini: kalau
`API_REQUIRE_AUTH=true`, SEMUA router baca (`hotspots`, `layers` termasuk `view=preview`, `polygons`,
`stats`, `burned_area`, `hotspot_clusters`, `point_match`, `export`, `wind`, `weather`, GET
`scheduler/status|metrics|burned-area/status`) butuh `Authorization: Bearer <jwt>` sah lewat
dependency `core/auth.require_session_if_enabled`. Selalu publik apa pun nilainya: `/api/health`,
`/api/auth/*`, `/api/metrics` (Prometheus). Router admin (`cache`, `scheduler` POST `/sync`) TIDAK
ketumpuk gate ini — tetap `require_admin_key` (X-Admin-Key ATAU JWT admin), supaya automation
X-Admin-Key-only tidak putus. Frontend `lib/api.ts` melampirkan token ke semua request via
`setAuthToken`; `App.tsx` `setUnauthorizedHandler` → 401 dari API mana pun memaksa logout ke
LoginPage. Di produksi `API_REQUIRE_AUTH` diisi di tab Environment Dokploy (di-*forward* ke container
`api` lewat `docker-compose.dokploy.yml` `environment:`). Rollback = set `false` + redeploy `api`,
tanpa revert kode. Cek cepat: `GET /api/stats` tanpa token → **401** kalau aktif, **200** kalau tidak.
Test lama tetap hijau karena `app/tests/conftest.py` (autouse) mematikan flag ini.

Sama seperti `ADMIN_API_KEY` (lihat catatan di memory project), **jangan pernah asumsikan nilai
`APP_LOGIN_PASSWORD` produksi dari sesi sebelumnya** — selalu konfirmasi ke user, dan set manual di
`.env.dokploy` produksi (tidak ikut ke-copy otomatis dari `.env.dokploy.example`) sebelum redeploy.
Ini insiden nyata: deploy gerbang login pertama kali (2026-08-24) tanpa `APP_LOGIN_PASSWORD`
ter-set di produksi sempat bikin seluruh situs 503 untuk semua orang.

## Model data poligon

Dua layer aktif saat ini: `psagustus2026` (Perhutanan Sosial/KPS) dan `HUTAN_ADAT_APR26` (Hutan
Adat), keduanya di tabel `polygon_metadata` dengan `layer_key` sebagai pembeda. Field utama: `lembaga`,
`nama_prov`, `nama_kab`, `nama_kec`, `nama_desa`, `skema`, `no_sk`, `tgl_sk`, `status`, `wilker_bps`,
`ps_id`, plus beberapa kolom luas (`luas_hk`, `luas_hl`, `luas_hpt`, `luas_hp`, `luas_hpk`, `luas_sk`,
`luas_poli`, `luas_final`), `jml_kk`, `is_active`.

Dataset Perhutanan Sosial dan Hutan Adat punya SKEMA PROPERTI BERBEDA (mis. Hutan Adat tidak punya
`LEMBAGA`, pakai `NAMA_MHA`/`NAMOBJ`; tidak punya `NAMA_PROV`, pakai `PROVINSI`). Selalu pakai
`_field_value()` di `geojson_sync_service.py` (atau alias yang sama) saat membaca properti mentah,
jangan reimplementasi rantai `or` sendiri di file lain.

### Ekspor geometry poligon = khusus admin

Kekhawatiran: dataset batas KPS/Hutan Adat (geometry + atribut) bocor ke non-admin. Aturannya:
non-admin (`user`/`bps`/anonim) boleh MELIHAT poligon di peta, tidak boleh MENGUNDUHnya sebagai
berkas.

- `GET /api/polygons/{id}` — `read_polygon_detail(tolerance=...)` sekarang parametrik. API-nya cek
  `get_current_user_claims`: admin → `tolerance=0.0001` (~11m, perilaku lama); non-admin → `0.001`
  (~110m, cukup buat outline peta detail KPS tapi terlalu kasar buat direpro jadi batas cadastral).
  `tolerance=None` = geometry mentah, **cuma** dipakai endpoint di bawah.
- `GET /api/polygons/{id}/export.geojson` — `Depends(require_admin_role)`, geometry presisi penuh,
  `Content-Disposition: attachment`. Satu-satunya jalur yang mengeluarkan geometry mentah.
- `GET /api/layers?view=full` / `GET /api/layers/{id}` — sudah `verify_admin_key` (tidak diubah).
- Frontend: kolom "Aksi" + tombol "Unduh GeoJSON" per-KPS di `HotspotMatrix.tsx` hanya render kalau
  prop `isAdmin` (`session?.role === "admin"` dari `App.tsx`); tombolnya fetch `/export.geojson`.
  Tombol "Unduh GeoJSON" versi filter (titik hotspot saja, tanpa geometry poligon) TIDAK di-gate.
- Sisa risiko yang diterima: `view=preview` (peta utama) + `/api/polygons/{id}` kasar masih membawa
  atribut poligon (lembaga, no_sk, dll) untuk popup — bisa dipanen lewat network tab. Menutup itu =
  strip atribut per-role, belum dikerjakan.

## Dokumen lain di repo ini

- `docs/monitoring/scheduler-alerting.md` — nama metrik Prometheus/JSON untuk scheduler
  (`etaseneu_scheduler_last_sync_success`, dst.) — jangan duplikasi di sini, rujuk saja.
- `docs/superpowers/plans/*.md` dan `specs/*.md` — dokumen desain historis dari fitur-fitur
  sebelumnya (MVP, scheduler metrics, sync polygon metadata). Konteks sejarah, bukan konvensi hidup.
