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
api/            # satu file per domain: hotspots, layers, polygons, burned_area,
                # export, point_match, scheduler, stats, weather, wind, cache,
                # metrics, auth. router.py merakit semuanya ke api_router (prefix /api).
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
components/   HotspotMap.tsx (peta Leaflet, pane z-index: KPS=400, bekas terbakar=420,
              hotspot=450), HotspotMatrix.tsx ("Matriks Data"), KpsDetailView.tsx,
              FilterPanel.tsx, SidebarNav.tsx, BurnedAreaCard.tsx, WeatherOverlay.tsx, dll.
hooks/        useDashboardData.ts (hook utama, ~800 baris — lihat di bawah),
              useBurnedAreaOverlay.ts
lib/          api.ts (client fetch bertipe), date.ts (helper WIB/Asia-Jakarta), hotspotDisplay.ts
constants/    satellites.ts, time-windows.ts (TimePreset: 24h/48h/3d/7d/30d/custom)
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
  24 jam) berisi klaim `sub`/`username`/`role`. Endpoint lain membaca token via header
  `Authorization: Bearer <token>` lewat dependency `require_authenticated_user` /
  `require_admin_role`.
  - Saat tabel `app_users` masih kosong, login pertama otomatis mem-seed satu akun `admin` dari
    `APP_LOGIN_PASSWORD` (`ensure_seed_admin`) — env ini sekarang cuma dipakai untuk seed awal,
    bukan lagi dicek langsung tiap login.
  - Manajemen user (list/create/ubah role/ganti password/hapus) ada di `GET/POST/PATCH/DELETE
    /api/auth/users/*`, semuanya `Depends(require_admin_role)`, dirender di tab Pengaturan lewat
    `UserManagementPanel.tsx` (cuma muncul kalau `session.role === "admin"`). Dua guard penting:
    tidak bisa hapus akun sendiri, dan tidak bisa hapus/demote admin terakhir
    (`count_admins() <= 1`).
  - `AUTH_JWT_SECRET` — **beda sifat** dari `ADMIN_API_KEY`/`APP_LOGIN_PASSWORD`: kalau kosong,
    `get_settings()` auto-generate secret random tiap restart server (bukan fail-closed 503).
    Konsekuensinya cuma "semua sesi JWT jadi invalid, semua orang login ulang" — bukan seluruh situs
    terkunci. Sengaja dibuat begini untuk menghindari mengulang insiden lockout produksi
    `APP_LOGIN_PASSWORD` di bawah. Production sebaiknya tetap set nilai tetap biar sesi tidak hilang
    tiap deploy, tapi ini opsional, bukan wajib.

Session (token + username + role) disimpan di memori React saja (bukan localStorage) — reload
halaman = harus login ulang, konsisten dengan pola `adminKey` yang sudah ada duluan.

**Penting**: gerbang login ini HANYA mengunci tampilan front-end. Endpoint baca publik (mis.
`/api/layers?view=preview`, `/api/hotspots`) TIDAK ikut terkunci olehnya — itu tetap seperti semula,
bisa diakses langsung tanpa lewat halaman login sama sekali. Kalau nanti diminta "kunci semua data",
itu perubahan jauh lebih besar (butuh session/token di level API, bukan cuma gerbang render React).

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

## Dokumen lain di repo ini

- `docs/monitoring/scheduler-alerting.md` — nama metrik Prometheus/JSON untuk scheduler
  (`etaseneu_scheduler_last_sync_success`, dst.) — jangan duplikasi di sini, rujuk saja.
- `docs/superpowers/plans/*.md` dan `specs/*.md` — dokumen desain historis dari fitur-fitur
  sebelumnya (MVP, scheduler metrics, sync polygon metadata). Konteks sejarah, bukan konvensi hidup.
