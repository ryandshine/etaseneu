# ETA SEUNEU — Comprehensive Codebase Architecture & Code Quality Audit

> **Audit Role:** Senior Software Engineer, Software Architect, and Code Quality Specialist  
> **Date of Audit:** September 13, 2026  
> **Status:** AUDIT COMPLETED — NO CODE MODIFIED (Phase 1: Inspect → Analyze → Identify → Document)  
> **Target Codebase:** ETA SEUNEU (`/home/ryandshinevps/etaseneu`)  

---

## 1. Project Overview

ETA SEUNEU adalah sistem geospasial peringatan dini dan pemantauan titik panas (*hotspot fire monitoring*) berbasis satelit yang beririsan dengan kawasan konsesi **Perhutanan Sosial (KPS)** dan **Hutan Adat** di seluruh wilayah Republik Indonesia. Sistem ini mengintegrasikan deteksi satelit termal NASA FIRMS (MODIS, VIIRS S-NPP, NOAA-20, NOAA-21), data resmi luas bekas terbakar Kementerian Kehutanan (Kemenhut / eks KLHK), analisis satelit Sentinel-2 dNBR / Random Forest tutupan lahan via Google Earth Engine (GEE), serta layanan cuaca dan arah angin Open-Meteo dan server peta Ditjen Planologi Kehutanan.

### Tech Stack Summary
* **Backend Framework:** FastAPI `0.115.12`, Uvicorn `0.34.2`, Pydantic `2.11.5`, Pydantic-Settings `2.9.1`
* **Programming Languages:** Python 3.12+ (Backend & Processing Scripts), TypeScript 5.7.2 (Frontend)
* **Frontend Framework & Build System:** React `18.3.1`, Vite `5.4.11`, `vite-plugin-pwa` `1.3.0`
* **GIS & Map Engine:** Leaflet `1.9.4`, `react-leaflet` `4.2.1`, `leaflet-velocity` `2.1.4`
* **Data Visualization & Charts:** Recharts `3.8.1`
* **Styling:** Monolithic Raw CSS (`frontend/src/index.css` — 10,624 lines) + Inconsistent Inline Styles
* **Routing:** Hand-rolled query-string synchronization via `window.location.search` in `App.tsx` (No React Router / TanStack Router)
* **Database & Spatial Layer:** PostgreSQL 16 + PostGIS 3, connected via `psycopg` `3.2.9` (Binary driver), Shapely `2.1.1`, PyProj `3.7.2`, PyShp `2.3.1`
* **Database Migration & ORM:** **None**. Direct raw SQL string execution; dynamic schema alterations (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE`) performed on application boot or ad-hoc runtime calls.
* **Authentication & Authorization:** 
  * Dual Auth: Static header `X-Admin-Key` (`ADMIN_API_KEY`) and multi-user JWT (HS256) backed by `app_users` table with bcrypt password hashing and `app_sessions` revocation tracking.
  * Captcha: Cloudflare Turnstile integration (`turnstile_service.py`).
  * Role-Based Access Control (RBAC): 3 roles (`admin`, `user`, `bps`).
* **Reporting & Export Engines:**
  * Excel: `openpyxl` `3.1.5` (duplicated across 4 distinct services).
  * PDF: **Two competing engines** — ReportLab `4.5.1` (`pdf_export_service.py`) vs WeasyPrint `69.0` + Jinja2 `3.1.6` (`agency_pdf_service.py`).
* **Testing Suite:**
  * Backend: Pytest `8.3.5` (431 tests collected across 34 test files).
  * Frontend: Vitest `2.1.8`, JSDOM `25.0.1`, React Testing Library `16.1.0` (145 tests across 21 test files).
* **Infrastructure & Deployment:** Dokploy (`docker-compose.dokploy.yml`), Nginx reverse proxy with rate limiting, Cloudflare Tunnel / Traefik.

---

## 2. Architecture Map

```mermaid
flowchart TD
    subgraph Client_Layer ["Frontend Client Layer (React 18 / Vite / TypeScript)"]
        BrowserUI["Browser / Mobile PWA (Auto-reload Service Worker)"]
        RouterState["Query String Router (App.tsx: readViewFromUrl)"]
        
        subgraph God_Components ["Monolithic View Components"]
            HotspotMatrix["HotspotMatrix.tsx (2012 lines)"]
            KpsDetailView["KpsDetailView.tsx (1994 lines)"]
            SiagaRambatanView["SiagaRambatanApiView.tsx (1463 lines)"]
            KompleksKebakaranView["KompleksKebakaranView.tsx (1420 lines)"]
            HotspotMap["HotspotMap.tsx (1124 lines)"]
            AppTsx["App.tsx (1090 lines)"]
            EarlyWarningView["EarlyWarningView.tsx (1073 lines)"]
            LandCoverPanel["LandCoverPanel.tsx (835 lines)"]
        end
        
        subgraph Frontend_State ["State & Persistence"]
            useDashboardData["useDashboardData.ts (809 lines - 35+ States)"]
            LocalPersistence["dashboardPersistence.ts (LocalStorage Cache)"]
            DirectFetchers["Independent View authFetch Calls (Fragmented)"]
        end
    end

    subgraph Transport_Layer ["Transport & Gateway"]
        NginxGateway["Nginx (deploy/nginx/etaseneu.conf) - Rate Limits / Security Headers"]
        FastAPIApp["FastAPI app.main:app (Lifespan, CORS, BackgroundTasks)"]
        AuthGate["Auth Dependency: require_session_if_enabled / require_admin_key"]
    end

    subgraph API_Controllers ["API Router Layer (app/api/)"]
        HotspotsApi["api/hotspots.py"]
        LayersApi["api/layers.py"]
        PolygonsApi["api/polygons.py"]
        BurnedAreaApi["api/burned_area.py"]
        LandCoverApi["api/land_cover.py"]
        EarlyWarningApi["api/early_warning.py"]
        FireSpreadApi["api/fire_spread.py"]
        PointMatchApi["api/point_match.py"]
        ExportApi["api/export.py"]
        WeatherWindApi["api/weather.py (524L) & api/wind.py (272L)\n[Direct Logic in Controller]"]
    end

    subgraph Service_Layer ["Domain & Business Logic Layer (app/services/)"]
        HotspotService["hotspot_service.py (727L)"]
        EarlyWarningService["early_warning_service.py (738L)\n[Direct SQL + openpyxl]"]
        FireSpreadService["fire_spread_service.py (681L)\n[Direct SQL + openpyxl]"]
        LandCoverService["land_cover_service.py (747L) & land_cover/*\n[In-Memory Mutex _LAND_COVER_RUN_STATE]"]
        BurnedAreaS2Service["burned_area_s2_service.py (446L)"]
        BurnedAreaKlhkService["burned_area_klhk_service.py (134L - ijson)"]
        ZombieGEEService["burned_area_service.py (293L) [DEPRECATED]"]
        
        subgraph Export_Engines ["Export Sub-Architecture (Fragmented)"]
            ReportLabPdf["pdf_export_service.py (1693L - ReportLab)"]
            WeasyPrintPdf["agency_pdf_service.py (711L - WeasyPrint + Jinja2)"]
            ExportService["export_service.py (954L - openpyxl)"]
            PointReportService["point_report_service.py (605L - openpyxl)"]
        end
    end

    subgraph Data_Access_Layer ["Database & Persistence (app/services/postgres_store/)"]
        PostgresStoreFacade["PostgresStore Monolithic Façade (__init__.py)\nMultiple Inheritance of 13 Mixins"]
        StoreMixins["_hotspots, _polygons, _layers, _burned_area,\n_s2_burned_area, _land_cover, _users, _relations, _spatial..."]
        BypassQueries["Raw SQL string bypasses in Services (EarlyWarning, FireSpread)"]
    end

    subgraph Storage_External ["Database & External Services"]
        PostgresDB[("PostgreSQL 16 + PostGIS (Port 5434)\n⚠️ Shared Dev/Prod Instance")]
        DiskCache["Filesystem Cache (.cache/)"]
        NasaFirms["NASA FIRMS API (CSV NRT Hotspots)"]
        GEE["Google Earth Engine API (Sentinel-2, SAR S-1)"]
        OpenMeteo["Open-Meteo Weather / Wind API"]
        ArcGISServer["Ditjen Planologi Kehutanan MapServer"]
    end

    %% Wiring connections
    BrowserUI --> RouterState
    RouterState --> AppTsx
    AppTsx --> useDashboardData
    AppTsx --> God_Components
    useDashboardData --> LocalPersistence
    useDashboardData --> NginxGateway
    DirectFetchers --> NginxGateway
    
    NginxGateway --> FastAPIApp
    FastAPIApp --> AuthGate
    AuthGate --> API_Controllers
    
    API_Controllers --> Service_Layer
    WeatherWindApi -.->|Bypasses Service Layer| DiskCache
    WeatherWindApi -.->|Bypasses Service Layer| OpenMeteo
    
    Service_Layer --> PostgresStoreFacade
    Service_Layer --> BypassQueries
    PostgresStoreFacade --> StoreMixins
    StoreMixins --> PostgresDB
    BypassQueries --> PostgresDB
    
    HotspotService --> NasaFirms
    LandCoverService --> GEE
    BurnedAreaS2Service --> GEE
    API_Controllers --> ArcGISServer
```

---

## 3. Critical Findings

### [CRITICAL] Danger #1: Shared Dev/Test/Production Database & Absence of Test Environment Isolation
* **Location:** `backend/app/core/config.py` (lines 9-19), `backend/app/tests/conftest.py`, `backend/.env`
* **Problem:** Konfigurasi default aplikasi memuat `DATABASE_URL` yang secara default mengarah langsung ke instance PostgreSQL produksi (`localhost:5434`). Test runner backend (`pytest`) tidak memiliki fixture isolasi database atau transaksi rollback; file `conftest.py` hanya mematikan auth gate (`API_REQUIRE_AUTH=false`), namun membiarkan `database_url` mengarah ke database produksi aktif.
* **Why:** Proyek dikembangkan dengan arsitektur single-database tanpa infrastruktur multi-tenancy, containerized test runner terpisah, atau schema fixture berbasis rollback.
* **Impact:** Satu kesalahan penulisan unit test atau skrip ad-hoc (seperti lupa menyuntikkan `_DisabledPostgresStore`) dapat langsung memodifikasi, mengosongkan, atau menonaktifkan data produksi. Insiden ini tercatat pernah terjadi saat test `LayerService` menonaktifkan seluruh layer KPS produksi karena menganggap data produksi yang tidak ada di folder fixture telah dihapus (`GeoJsonSyncService.sync_all()`).
* **Recommendation:**
  1. Buat `conftest.py` yang secara default me-rewrite `DATABASE_URL` ke database SQLite/in-memory, mock database, atau setidaknya database test lokal terpisah (misal `etaseneu_test`).
  2. Implementasikan fail-closed guard pada `PostgresStore`: jika `os.getenv("PYTEST_CURRENT_TEST")` terdeteksi dan URL database mengandung host/port produksi, batalkan koneksi secara fatal (`RuntimeError: Refusing to run tests against production database`).
* **Risk:** Kehilangan data produksi (*data loss*), korupsi data tabular perhutanan sosial, atau *service outage* total saat developer menjalankan pengujian lokal atau pipeline otomatis.

---

### [CRITICAL] In-Memory Global Process State for Concurrency Control & Job Coordination
* **Location:** 
  * `backend/app/services/land_cover_service.py` (`_LAND_COVER_RUN_STATE: dict[int, dict] = {}`, lines 117–142, 591–747)
  * `backend/app/services/scheduler.py` (`_last_sync_result`, `_last_sync_at`, `_consecutive_failures`, lines 20–27)
  * `backend/app/services/burned_area_scheduler.py` (`_last_run_result`, `_bootstrapped`, lines 30–36)
* **Problem:** Manajemen konkurensi (global lock agar Earth Engine tidak dieksekusi secara bersamaan untuk beberapa poligon) dan status eksekusi scheduler diimplementasikan menggunakan variabel global Python in-memory di dalam modul proses FastAPI.
* **Why:** Keputusan desain awal mengasumsikan FastAPI hanya berjalan sebagai single-worker process (`uvicorn app.main:app` tanpa `--workers N`).
* **Impact:**
  1. Jika aplikasi di-scale secara horizontal (multi-container) atau dijalankan dengan multi-worker Uvicorn (`workers > 1`), variabel in-memory ini terisolasi per worker. User A di worker 1 dan User B di worker 2 dapat memicu analisis GEE secara bersamaan, melanggar batas kuota Earth Engine (*User memory limit exceeded*).
  2. Saat server restart atau container redeploy di Dokploy, seluruh state job yang sedang berjalan (*running tasks*) hilang seketika, meninggalkan status database tidak sinkron atau terpaksa di-reset secara heuristik saat boot (`reset_stale_land_cover_running`).
* **Recommendation:**
  Pindahkan locking mekanisme dan scheduler tracking ke PostgreSQL (menggunakan PostgreSQL Advisory Locks `pg_advisory_lock` atau tabel job lock dengan TTL) atau Redis distributed lock.
* **Risk:** Kegagalan konkurensi saat beban pengguna meningkat, *race conditions*, ekses kuota GEE berbayar/terbatas, dan inkonsistensi status monitoring.

---

### [CRITICAL] God Components & Monolithic Component Architecture in Frontend
* **Location:** 
  * `frontend/src/components/HotspotMatrix.tsx` (2,012 lines)
  * `frontend/src/components/KpsDetailView.tsx` (1,994 lines)
  * `frontend/src/components/SiagaRambatanApiView.tsx` (1,463 lines)
  * `frontend/src/components/KompleksKebakaranView.tsx` (1,420 lines)
  * `frontend/src/components/HotspotMap.tsx` (1,124 lines)
  * `frontend/src/App.tsx` (1,090 lines)
  * `frontend/src/components/EarlyWarningView.tsx` (1,073 lines)
* **Problem:** Tujuh komponen frontend memiliki ukuran masing-masing di atas 1,000 baris kode (dua di antaranya menyentuh 2,000 baris). Di dalam satu file komponen bercampur: deklarasi 20–35 state lokal, efek sinkronisasi jaringan, kalkulasi statistik spasial, parsing tanggal WIB, pembuatan DOM GeoJSON, kanvas Leaflet, dropdown modal, hingga rendering grafik SVG Recharts.
* **Why:** Pertumbuhan fitur dilakukan secara *append-only* (menambahkan blok kode baru langsung ke komponen yang ada) tanpa memecah sub-komponen atau mengekstrak custom hooks.
* **Impact:** 
  * Re-render massal yang tidak efisien (*performance degradation*).
  * Sangat rentan terhadap regresi saat melakukan modifikasi kecil.
  * Cognitive load ekstrem bagi developer; sulit melakukan unit testing pada level sub-fitur.
* **Recommendation:**
  Pecah masing-masing God Component menjadi 4–6 komponen atomik dan buat custom hooks per domain:
  * `HotspotMatrix.tsx` → `MatrixToolbar`, `MatrixDataTable`, `MatrixExportMenu`, `useMatrixAggregation`.
  * `KpsDetailView.tsx` → `KpsDetailHeader`, `KpsDetailMap`, `KpsBurnedAreaSection`, `KpsWeatherSection`, `useKpsDetailData`.
* **Risk:** Biaya pemeliharaan (*maintenance cost*) melonjak eksponensial; setiap perubahan UI berpotensi merusak fitur lain dalam komponen yang sama.

---

### [CRITICAL] Missing Database Migration Framework & Runtime DDL Operations
* **Location:** 
  * `backend/app/services/postgres_store/_land_cover.py` (lines 30–80)
  * `backend/app/services/postgres_store/_users.py` (lines 18–45)
  * `backend/app/services/postgres_store/_scheduler.py` (lines 13–25)
  * `backend/app/services/postgres_store/_burned_area.py` (lines 625–640)
  * `backend/app/services/postgres_store/_s2_burned_area.py` (lines 19–35)
  * `HANDOFF-fungsi-kawasan-hutan.md`
* **Problem:** Tidak ada framework database migration (seperti Alembic). Perubahan skema database dilakukan dengan dua cara yang berisiko: (1) Menjalankan query DDL langsung di database produksi lewat psql console host tanpa script versioning terpusat, dan (2) Mengeksekusi string `CREATE TABLE IF NOT EXISTS` serta `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` di dalam fungsi Python saat startup aplikasi atau bahkan saat pemanggilan API runtime (`_ensure_land_cover_tables`).
* **Why:** Proyek dimulai dari skrip prototipe cepat tanpa setup Alembic di awal repositori.
* **Impact:**
  * Tidak ada *single source of truth* untuk skema database.
  * Tidak ada fasilitas rollback otomatis jika migrasi bermasalah.
  * Database staging/dev tidak dapat direproduksi secara deterministik dari scratch (hanya ada file `init_etaseneu.sql` yang sudah tertinggal dari skema database aktual saat ini).
* **Recommendation:**
  Adopsi Alembic (`alembic init`) segera. Ekstrak seluruh DDL dari `init_etaseneu.sql` dan method `_ensure_*` ke dalam migration revision yang berurutan, lalu hapus seluruh pemanggilan DDL dari runtime Python store mixin.
* **Risk:** Inkonsistensi skema antar lingkungan (*schema drift*), kegagalan deployment tanpa jejak audit, dan potensi *table locking* saat query DDL dijalankan di jam sibuk produksi.

---

## 4. High Priority Findings

### [HIGH] Extreme Prop Drilling & Monolithic State in `useDashboardData.ts`
* **Location:** `frontend/src/hooks/useDashboardData.ts` (810 lines) and `frontend/src/App.tsx`
* **Problem:** `useDashboardData.ts` bertindak sebagai *God Hook* yang memegang 35+ state, status loading/error per sub-aksi, dan 15+ fungsi mutasi. Semua state ini diinstansiasi di `App.tsx` dan dialirkan ke bawah (*prop drilled*) melewati beberapa level komponen (`App` → `HotspotMap`, `HotspotMatrix`, `KpsDetailView`, `SettingsPanel`).
* **Why:** Tidak ada centralized client state manager (seperti Zustand atau React Context ber-cakupan terbatas) untuk memisahkan UI state, filter state, dan server state.
* **Impact:** Setiap kali satu state filter kecil berubah (misalnya tick timer 60 detik `clockTick`), seluruh pohon komponen di `App.tsx` berisiko dievaluasi ulang, memicu re-render berat pada peta Leaflet.
* **Recommendation:** Gunakan **Zustand** atau pisahkan menjadi beberapa Context yang terisolasi: `FilterContext`, `AuthContext`, dan `DashboardDataContext`.
* **Risk:** Bottleneck performa rendering pada perangkat mobile atau laptop spesifikasi rendah.

---

### [HIGH] Fragmented & Inconsistent Data Fetching Strategy Across Views
* **Location:** 
  * `frontend/src/hooks/useDashboardData.ts`
  * `frontend/src/components/EarlyWarningView.tsx` (fetch `/api/early-warning/*`)
  * `frontend/src/components/KompleksKebakaranView.tsx` (fetch `/api/hotspots/clusters`)
  * `frontend/src/components/SiagaRambatanApiView.tsx` (fetch `/api/fire-spread/*`)
  * `frontend/src/components/TutupanLahanView.tsx` (fetch `/api/land-cover/*`)
* **Problem:** Ada dua pola arsitektur data fetching yang saling bertentangan:
  1. Halaman utama (Peta & Buku Besar) mengambil data melalui `useDashboardData` dengan filter rentang waktu global dan layer yang dipilih.
  2. Empat view lainnya (`EarlyWarningView`, `KompleksKebakaranView`, `SiagaRambatanApiView`, `TutupanLahanView`) mengabaikan `useDashboardData` dan memanggil API backend sendiri secara independen via `authFetch`.
* **Why:** Fitur-fitur baru dikembangkan secara independen oleh kontributor yang berbeda sebagai "menu baru" tanpa integrasi ke dalam pipeline state dashboard utama.
* **Impact:**
  * Pengguna memilih filter tanggal atau satelit di menu utama, tetapi saat berpindah ke menu "Peringatan Dini" atau "Siaga Rambatan Api", filter tersebut tidak sinkron atau kembali ke default.
  * Duplikasi pemanggilan HTTP dan inkonsistensi cache.
* **Recommendation:**
  Standarisasi data fetching dengan **TanStack Query (React Query)**. Tiap query memiliki cache key yang jelas (`["hotspots", filters]`, `["fire-spread", window]`), mendukung otomatisasi deduplikasi request, caching, dan invalidasi.
* **Risk:** Data yang ditampilkan di dashboard utama berbeda dengan angka yang tampil di menu peringatan dini (*data inconsistency* yang membingungkan pengambil keputusan).

---

### [HIGH] Dual Competing PDF Generation Stacks (ReportLab vs WeasyPrint)
* **Location:** 
  * `backend/app/services/pdf_export_service.py` (1,694 lines — ReportLab)
  * `backend/app/services/agency_pdf_service.py` (712 lines — WeasyPrint + Jinja2)
* **Problem:** Repositori memelihara **dua mesin rendering PDF yang sepenuhnya berbeda**:
  1. `pdf_export_service.py` menggunakan ReportLab dengan API gambar prosedural primitif, perhitungan koordinat kanvas manual, dan pembatas `HOTSPOT_DETAIL_TABLE_MAX_ROWS = 1500` karena tabel Platypus lambat saat layout.
  2. `agency_pdf_service.py` menggunakan WeasyPrint + Jinja2 HTML templates (`agency_report.html`).
* **Why:** Laporan umum dibangun pertama kali menggunakan ReportLab; saat laporan khusus per-lembaga dibutuhkan, developer memilih WeasyPrint agar dapat menggunakan styling CSS HTML, namun laporan ReportLab lama tidak pernah dimigrasikan.
* **Impact:**
  * Duplikasi kode kalkulasi tile slippy map (`latlon_to_tile`, `tile_to_latlon`) dan penarikan ubin basemap CartoDB dari internet.
  * Beban dependensi ganda di `requirements.txt`: `reportlab` + `weasyprint` (yang membutuhkan dependensi sistem berat seperti `pango`, `cairo`, `gdk-pixbuf`, `libffi` di Docker image).
* **Recommendation:**
  Konsolidasi total ke **WeasyPrint + Jinja2**. Buat template HTML/CSS untuk laporan umum, hapus 1,694 baris ReportLab, dan hapus dependensi `reportlab` dari `requirements.txt`.
* **Risk:** Meningkatkan ukuran Docker container, kompleksitas build dependensi C di host/Dokploy, dan biaya pemeliharaan ganda untuk format laporan yang mirip.

---

### [HIGH] Redundant Excel Export Logic Scattered in 4 Separate Services
* **Location:** 
  * `backend/app/services/export_service.py` (954 lines)
  * `backend/app/services/early_warning_service.py` (lines 577–739)
  * `backend/app/services/fire_spread_service.py` (lines 592–680)
  * `backend/app/services/point_report_service.py` (lines 13–270)
* **Problem:** Empat modul backend yang berbeda masing-masing mengimpor `openpyxl` dan membangun file Excel secara prosedural dari nol.
* **Why:** Setiap modul menangani fiturnya sendiri tanpa mengekstrak modul builder/utilitas Excel generik.
* **Impact:** Kode styling deklaratif openpyxl (warna hex header, border tipis, konfigurasi font Arial/Calibri, format angka ribuan, perataan tengah, auto-fit lebar kolom) diduplikasi berulang kali. Jika ada pembaruan standar palet warna instansi (Kemenhut), 4 file berbeda harus diedit manual.
* **Recommendation:**
  Buat modul utilitas `backend/app/services/excel_builder.py` yang menyediakan kelas pembantu (misal `ExcelReportBuilder`) dengan styling standar, auto-column-width, dan sheet formatter seragam.
* **Risk:** Format dokumen export Excel yang dihasilkan tidak seragam, inkonsisten bagi pengguna akhir Kementerian Kehutanan.

---

### [HIGH] Layer Violation: Business Logic, Grid Computation & Disk Caching in API Controllers
* **Location:** 
  * `backend/app/api/weather.py` (525 lines)
  * `backend/app/api/wind.py` (273 lines)
* **Problem:** Modul di dalam direktori `app/api/` (yang seharusnya bertindak sebagai HTTP routing controller) berisi logika bisnis kalkulasi matematika berat: pembuatan grid koordinat bounding box Indonesia/Dunia (`_build_axis`), kalkulasi konversi vektor angin meteorologis (`_wind_to_uv`), interpolasi spasial, HTTP fetching langsung ke Open-Meteo, serta implementasi file cache berbasis disk (`_cache_path`, `_cache_is_valid`, `_read_cache`).
* **Why:** Fitur cuaca dan angin dibuat cepat sebagai modul mandiri langsung di controller tanpa dibuatkan service terpisah di `app/services/`.
* **Impact:** 
  * Kontroler API tidak dapat diuji secara terpisah tanpa menjalankan HTTP layer.
  * Pelanggaran berat *Separation of Concerns*.
  * Duplikasi persis fungsi `_build_axis`, `_cache_is_valid`, dan `_read_cache` antara `weather.py` dan `wind.py`.
* **Recommendation:**
  Ekstrak logika tersebut ke dalam `app/services/weather_service.py` dan `app/services/wind_service.py`. Biarkan `app/api/weather.py` dan `app/api/wind.py` hanya bertugas memvalidasi request HTTP dan mengembalikan DTO/Response.
* **Risk:** Sulit memelihara dan menguji fitur cuaca; risiko kegagalan upstream Open-Meteo langsung mematikan thread event loop controller.

---

### [HIGH] Monolithic 10,624-Line Global CSS File & Inline Style Architectural Divergence
* **Location:** 
  * `frontend/src/index.css` (10,624 lines)
  * `frontend/src/components/EarlyWarningView.tsx` (over 100 inline `style={{...}}` blocks)
* **Problem:** Seluruh stylesheet aplikasi ditumpuk dalam satu file raksasa `index.css` tanpa CSS Modules, SCSS nesting, atau utility-first CSS (seperti Tailwind). Di sisi lain, komponen `EarlyWarningView.tsx` mengalami divergensi arsitektur total: hampir 100% tampilannya di-styling menggunakan atribut inline React `style={{ ... }}` dengan hex code hardcoded `#4D2D1B`, `#E7E6C2`, `#ef4444`.
* **Why:** `index.css` bertindak sebagai dumping ground untuk semua kelas CSS selama iterasi berbulan-bulan. `EarlyWarningView` dibuat terpisah dengan cepat menggunakan inline style langsung dari prototipe.
* **Impact:**
  * Risiko tinggi tabrakan nama kelas (*CSS namespace collision*).
  * Sulit membersihkan CSS yang sudah tidak terpakai (*dead CSS*).
  * Ukuran bundle CSS awal mencapai ratusan kilobyte yang harus di-parse browser saat cold-start.
  * Inkompatibilitas UI dan disparitas tampilan tema antar-halaman.
* **Recommendation:**
  1. Standarisasi CSS token (warna, spasi, typography) ke dalam CSS Variables.
  2. Migrasikan `EarlyWarningView.tsx` dari inline style ke class CSS standar.
  3. Pertimbangkan refactor bertahap ke CSS Modules (`*.module.css`) atau Tailwind CSS untuk komponen baru.
* **Risk:** Regresi visual yang tidak terdeteksi pada layar pengguna saat mengubah baris CSS di `index.css`.

---

### [HIGH] Zombie / Deprecated GEE Burned Area Code Paths
* **Location:** 
  * `backend/app/services/burned_area_service.py` (293 lines)
  * `backend/app/services/burned_area_scheduler.py` (202 lines)
  * `backend/app/tests/test_burned_area_service.py` (407 lines)
  * `backend/app/tests/test_burned_area_scheduler.py` (191 lines)
  * `backend/app/main.py` (lines 12, 42–62, 102–120, 136–148)
* **Problem:** Sebagaimana dicatat dalam dokumentasi teknis, sumber data luas bekas terbakar MODIS/VIIRS via GEE sudah resmi **ditinggalkan** dan digantikan oleh rekap resmi Kementerian Kehutanan (`burned_area_klhk_service.py`). Namun, service lama, scheduler loop di `main.py`, konfigurasi env di `config.py`, dan ratusan baris test masih aktif berada di codebase.
* **Why:** Kode dibiarkan "berjaga-jaga jika GEE ingin dipakai lagi" tanpa isolasi modul arsip.
* **Impact:** Menambah kompleksitas codebase, memperlambat proses review dan startup lifespan, serta membingungkan developer baru tentang alur pipeline data luas terbakar yang sebenarnya aktif.
* **Recommendation:**
  Arsipkan atau hapus file `burned_area_service.py` dan `burned_area_scheduler.py`. Bersihkan inisialisasi loop scheduler dari `main.py` dan hapus variabel environment yang tidak lagi relevan.
* **Risk:** Eksekusi scheduler yang tidak diinginkan jika konfigurasi flag GEE secara tidak sengaja diaktifkan di server.

---

## 5. Medium Priority Findings

### [MEDIUM] Ad-Hoc Standalone Scripts Directly Accessing Production Database
* **Location:**
  * `backend/build_capaian_ps_cianjur.py`
  * `backend/build_hotspot_bungo_today.py`
  * `backend/build_hotspot_deck.py`
  * `backend/build_inventarisasi_ps_terbakar.py`
  * `backend/build_karhutla_deck.py`
  * `backend/build_karhutla_deck_ringkas.py`
  * `backend/build_kompleks_kebakaran_matrix.py`
  * `backend/build_risiko_lanjutan_3hari.py`
  * `backend/build_titik_ketapang_muarapawan.py`
  * `backend/extract_hotspot_deck_stats.py`
  * `backend/extract_karhutla_stats.py`
  * `backend/update_hotspot_xlsx.py`
  * `backend/app/services/run_gee_august_analysis.py`
* **Problem:** Terdapat 13+ script Python standalone di root folder `backend/` yang mengimpor `PostgresStore` atau membuka koneksi database langsung untuk mengekstraksi data dan men-generate berkas presentasi PowerPoint (`.pptx`) atau Excel (`.xlsx`).
* **Why:** Script dibuat sewaktu-waktu atas permintaan paparan pimpinan instansi dan ditinggalkan di repositori.
* **Impact:** Mengaburkan batas struktur aplikasi `backend/app`, tidak memiliki test suite, dan rawan memicu lock database jika dijalankan bersamaan dengan beban sistem.
* **Recommendation:** Pindahkan seluruh skrip analisis ad-hoc ini ke subdirektori tersendiri: `backend/scripts/reporting/` dan pisahkan dependensi pembuat presentasi (`python-pptx`) ke dalam `requirements-dev.txt`.
* **Risk:** Developer menjalankan script yang salah di environment produksi atau dependensi production image membengkak.

---

### [MEDIUM] 150 MB Binary & Data Files Committed in Repository Root
* **Location:** 
  * `burned _area_indoesia_jun_juli_2026.geojson` (149.8 MB)
  * 8 file presentasi `.pptx` (total ~4 MB)
  * 6 file data Excel `.xlsx` (satu file mencapai 4.2 MB)
  * File archive ZIP dan KML di root direktori
* **Problem:** File GeoJSON raksasa (150 MB) dan puluhan file presentasi/data binary tersimpan langsung di dalam working directory git.
* **Why:** Developer menaruh file input/output analisis langsung di root project agar mudah dibaca oleh skrip.
* **Impact:** 
  * Ukuran repository git membengkak secara masif.
  * Memperlambat `git clone`, `git status`, dan proses build Docker (jika tidak ter-exclude sempurna di `.dockerignore`).
* **Recommendation:**
  Keluarkan seluruh file data dan binary dari git. Tambahkan ekstensi `*.pptx`, `*.xlsx`, `*.kml`, `*.zip`, dan file GeoJSON besar ke `.gitignore`. Simpan data layer resmi di folder external mount yang sudah disiapkan (`HOST_SHP_DIR`).
* **Risk:** Git repository bloat, accidental commit file raksasa ke remote repo GitHub/GitLab yang melebihi batas push 100 MB.

---

### [MEDIUM] Hand-Rolled URL Query Navigation without Client Router
* **Location:** `frontend/src/App.tsx` (lines 121–182, `readViewFromUrl`, `readKpsAgencyFromUrl`, `readLandCoverPolygonIdFromUrl`)
* **Problem:** Aplikasi tidak menggunakan router standar React (seperti `react-router-dom` atau `@tanstack/react-router`). Navigasi antar-view dikelola manual dengan membaca `new URLSearchParams(window.location.search)` dan memanipulasi riwayat browser secara manual.
* **Why:** Sistem berawal dari single-page view Leaflet sederhana yang kemudian berkembang menjadi aplikasi dengan 9 modul tampilan berbeda.
* **Impact:**
  * Penanganan tombol browser *Back* dan *Forward* rawan desinkronisasi dengan active view state.
  * Tautan parameter (misal URL detail KPS vs tutupan lahan) memerlukan parsing string ad-hoc berulang di `App.tsx`.
* **Recommendation:** Migrasikan routing ke **TanStack Router** atau **React Router v6+** agar routing memiliki layout nesting, parsing search params bertipe (*type-safe search params*), dan transisi view yang standar.
* **Risk:** Bug navigasi edge-case di perangkat mobile dan riwayat browser yang tidak konsisten.

---

### [MEDIUM] Synchronous `print()` Debug Logging in Core Async Request Path
* **Location:** `backend/app/services/hotspot_service.py` (lines 185–199)
* **Problem:** Fungsi `fetch_filtered_hotspots` mencetak teks multi-line `[HOTSPOT FILTER DEBUG LOG]` ke stdout menggunakan `print(debug_log, flush=True)` pada SETIAP kali endpoint query hotspot dipanggil oleh pengguna atau polling background.
* **Why:** Disengaja oleh developer untuk mendiagnosis rentang filter tanggal secara visual di terminal lokal.
* **Impact:**
  * Menghasilkan log spam masif di container logs Dokploy/Docker.
  * Operasi I/O terminal sinkron dengan `flush=True` di dalam fungsi `async` dapat mendegradasi throughput FastAPI di bawah beban konkurensi tinggi.
* **Recommendation:** Ganti `print(debug_log, flush=True)` dengan `logger.debug(debug_log)` standar logging Python, sehingga hanya muncul jika `LOG_LEVEL=DEBUG`.
* **Risk:** File log container server cepat membengkak dan degradasi throughput API.

---

### [MEDIUM] Misplaced Import Statement in Component File
* **Location:** `frontend/src/App.tsx` (line 191)
* **Problem:** Pernyataan import `import { Maximize, Minimize, Menu, X } from "lucide-react";` diletakkan di baris 191, tepat sebelum deklarasi komponen utama `export default function App()`, setelah ratusan baris helper function.
* **Why:** Hasil merge conflict resolution atau copy-paste patch cepat.
* **Impact:** Melanggar standar konvensi kode JavaScript/TypeScript (ESLint / Prettier).
* **Recommendation:** Pindahkan baris import ke bagian atas file bersama deretan import lainnya.
* **Risk:** Code smell yang menandakan kurangnya linting otomatis (tidak ada ESLint runner aktif).

---

## 6. Low Priority Findings

### [LOW] Magic Numbers & Strings in Map Calculations and Queries
* **Location:**
  * `backend/app/services/fire_spread_service.py` (line 27: `DEGREE_PER_METER = 1.0 / 111320.0`)
  * `frontend/src/components/HotspotMap.tsx` (hardcoded z-indexes: 360, 400, 420)
  * `backend/app/services/pdf_export_service.py` (hardcoded point widths: 769pt)
* **Problem:** Nilai konstanta spasial dan styling disematkan secara inline tanpa modul konfigurasi terpusat.
* **Recommendation:** Kumpulkan konstanta geospasial dan z-index Leaflet ke file konstanta bersama (misal `frontend/src/constants/map.ts`).

---

### [LOW] Redundant Dynamic Confidence Calculation
* **Location:**
  * `frontend/src/App.tsx` (fungsi `dynamicConfidenceStats`)
  * `frontend/src/components/MapSheet.tsx` (kalkulasi ringkasan satelit & tingkat keyakinan)
* **Problem:** Kedua file mengimplementasikan algoritma penghitungan kategori keyakinan (Tinggi, Sedang, Rendah) dan normalisasi satelit yang identik secara terpisah.
* **Recommendation:** Gunakan helper `buildConfidenceDistribution` dari `lib/hotspotDisplay.ts` untuk kedua komponen tersebut.

---

### [LOW] Outdated Port Documentation in README
* **Location:** `README.md` (lines 28–30) vs `frontend/vite.config.ts`
* **Problem:** `README.md` menyebutkan backend berjalan di port 8000, sementara konfigurasi proxy Vite di `frontend/vite.config.ts` menunjuk ke port 8011.
* **Recommendation:** Perbarui dokumentasi di `README.md` agar mencerminkan port proxy aktif yang digunakan saat development lokal.

---

## 7. Duplication Report

Tabel berikut merangkum area duplikasi kode aktual (*True Duplication*) yang ditemukan di seluruh codebase:

| No | Tipe Duplikasi | Lokasi 1 | Lokasi 2 | Lokasi 3 | Dampak & Rekomendasi |
|:---|:---|:---|:---|:---|:---|
| 1 | **Field Value Extraction Multi-Skema GeoJSON** | `backend/app/services/spatial_service.py` (L142) | `backend/app/services/layer_service.py` (L428) | `backend/app/services/geojson_sync_service.py` (L152) | **True Duplication:** Rantai pembacaan alias properti shapefile (`LEMBAGA`, `NAMA_MHA`, `NAMOBJ`, `NAMA_KAB`) diulang di 3 modul. Wajib disatukan ke `polygon_fields.py`. |
| 2 | **Slippy Tile Math & CartoDB Basemap Fetcher** | `backend/app/services/pdf_export_service.py` (L127–210) | `backend/app/services/agency_pdf_service.py` (L52–175) | — | **True Duplication:** Copy-paste murni fungsi `_sec`, `_latlon_to_tile`, `_tile_to_latlon`, dan downloader tile map. Konsolidasi ke satu utilitas GIS atau satukan PDF stack. |
| 3 | **OpenPyXL Workbook Styling & Formatting** | `backend/app/services/export_service.py` | `backend/app/services/early_warning_service.py` | `backend/app/services/fire_spread_service.py` & `point_report_service.py` | **True Duplication:** Konstruksi workbook, deklarasi font, border tipis, warna fill header, dan kalkulasi auto-width kolom diulang di 4 service. Ekstrak ke `excel_builder.py`. |
| 4 | **Grid Math & Open-Meteo File Disk Caching** | `backend/app/api/weather.py` (L30–90) | `backend/app/api/wind.py` (L30–90) | — | **True Duplication:** Logika `_build_axis`, `_cache_is_valid`, `_read_cache` disalin persis antar-controller. Ekstrak ke service bersama. |
| 5 | **Date Parsing, Formatting & WIB Offset Math** | `frontend/src/lib/date.ts` | `frontend/src/components/HotspotMatrix.tsx` (L205–250) | `frontend/src/components/KpsDetailView.tsx` (L163–220) | **True Duplication:** Fungsi manipulasi tanggal Jakarta/WIB diimplementasikan ulang secara lokal di komponen UI. |
| 6 | **Tipe Data `DashboardHotspot` / `MappedDashboardHotspot`** | `frontend/src/hooks/useDashboardData.ts` (L31–55) | `frontend/src/lib/hotspotDisplay.ts` (L17–35) | — | **True Duplication:** Duplikasi tipe data struktural karena takut terjadi circular import. Solusi: Pindahkan definisi tipe ke `frontend/src/types/api.ts`. |
| 7 | **GeoJSON Feature Conversion & Downloader** | `frontend/src/components/HotspotMatrix.tsx` (L58–110) | `frontend/src/components/SiagaRambatanApiView.tsx` | — | **True Duplication:** Logika `hotspotToGeoJsonFeature` dan pembuatan Blob `downloadGeoJson` di dalam DOM diulang di komponen view. Ekstrak ke `lib/download.ts`. |

---

## 8. Complexity Hotspots

Daftar modul, komponen, dan fungsi dengan Cyclomatic & Cognitive Complexity tertinggi di codebase:

| No | Modul / Lokasi | Tipe & Tanggung Jawab | Estimasi Lines | Faktor Kompleksitas Utama |
|:---|:---|:---|:---|:---|
| 1 | `frontend/src/components/HotspotMatrix.tsx` | UI Component (Buku Besar) | 2,012 | Aggregation tables, dynamic grouping per-skema/provinsi, Year-over-Year trend, sub-charts, export dialogs, inline filter matrices. |
| 2 | `frontend/src/components/KpsDetailView.tsx` | UI Component (Detail KPS) | 1,994 | 30+ useState, 7 cascading fetch useEffect, embedded Leaflet map, Leaflet timeline player, surrounding buffer controls, custom canvas. |
| 3 | `backend/app/services/pdf_export_service.py` | Service (ReportLab PDF) | 1,694 | Procedural canvas drawing, dynamic layouting table cells wrapped in Paragraphs, pagination calculation, embedded vector legends. |
| 4 | `frontend/src/components/SiagaRambatanApiView.tsx` | UI Component (Siaga Rambatan) | 1,463 | Per-segment threat evaluation, Leaflet arrow drawing, compass bearing, buffer layers, modal inspection, and KPI cards. |
| 5 | `frontend/src/components/KompleksKebakaranView.tsx` | UI Component (Kompleks Kebakaran) | 1,420 | ST-DBSCAN visual cluster inspection, Leaflet marker clustering, local data table sorting, basemap controls, and statistics. |
| 6 | `frontend/src/components/HotspotMap.tsx` | UI Component (Peta Live) | 1,124 | Dual-mode desktop/mobile divergence (MapSheet vs floating stacks), Leaflet canvas click tolerance hacks, timeline animation player, pane z-indexes. |
| 7 | `frontend/src/App.tsx` | Root Component & Navigation | 1,090 | Prop drilling gateway, URL search params parsing, session persistence, unauthorized event handling, 9 view switch cases. |
| 8 | `frontend/src/components/EarlyWarningView.tsx` | UI Component (Peringatan Dini) | 1,073 | 3-bucket partitioning math (today, receding, inactive), KPI cards, inline styles on every DOM node, multi-level category filters. |
| 9 | `backend/app/services/export_service.py` | Service (Excel Generator) | 954 | Cell-by-cell coordinate positioning, openpyxl chart binding, merged ranges, conditional styling, and multi-sheet creation. |
| 10 | `backend/app/services/land_cover_service.py` | Service (Tutupan Lahan GEE) | 748 | Multi-spectral band arithmetic, Earth Engine AST construction, Random Forest classifier invocation, SAR S-1 mosaic synthesis, temporal rules. |

---

## 9. Coupling Hotspots

1. **`useDashboardData.ts` ↔ `App.tsx` ↔ All Views:**
   Hook `useDashboardData` mengembalikan 35+ item yang di-drill ke hampir semua komponen. Komponen anak terikat erat pada bentuk payload hook ini.
2. **`PostgresStore` Façade ↔ All Backend Services:**
   Semua service backend instansiasi `PostgresStore` secara langsung di dalam method `__init__`, tanpa inversion of control atau dependency injection container.
3. **`HotspotService` Concrete Instantiation:**
   `HotspotService.__init__` menginstansiasi 6 dependensi konkret sekaligus (`LayerService`, `GeoJsonSyncService`, `HotspotHistoryStore`, `CacheService`, `PostgresStore`, `NasaFirmsClient`), membuat service ini sangat sulit di-unit test secara terisolasi tanpa monkeypatching agresif.
4. **`KpsDetailView.tsx` ↔ `HotspotMap.tsx` UI Controls:**
   Keduanya mengandalkan styling `.map-left-stack` dan konfigurasi canvas tolerance Leaflet yang sama, namun sebagian konfigurasi diduplikasi di kedua file.

---

## 10. Architecture Violations

1. **Layer Violation: Controller Mengandung Heavy Business Logic & I/O:**
   `backend/app/api/weather.py` dan `backend/app/api/wind.py` melakukan pemrosesan matematika grid, koneksi HTTP eksternal, dan manajemen cache file disk langsung di dalam controller routing FastAPI.
2. **Bypass Data Access Layer (ORM/Store Bypass):**
   `EarlyWarningService` dan `FireSpreadService` tidak menggunakan method abstrak yang disediakan oleh `PostgresStore`, melainkan langsung mengambil `self.store.connection()` dan mengeksekusi raw query SQL sepanjang ratusan baris di dalam service layer.
3. **Pencampuran Concerns di Komponen Frontend:**
   Komponen presentasi (seperti `HotspotMatrix.tsx` dan `KpsDetailView.tsx`) mencampur tanggung jawab UI rendering dengan data transformation (agregasi matrik tabel, kalkulasi frekuensi kebakaran, konversi format file GeoJSON).
4. **Divergensi Arsitektur Styling:**
   `EarlyWarningView.tsx` tidak menggunakan stylesheet terpusat (`index.css`), melainkan menggunakan 100% inline styles, melanggar pola desain visual seluruh aplikasi lainnya.

---

## 11. Security Smells (Passive Audit)

1. **Unauthenticated Public Read Endpoints by Default:**
   Flag `API_REQUIRE_AUTH` di `backend/app/core/config.py` diset ke `False` secara default. Tanpa konfigurasi environment eksplisit di server, seluruh endpoint pembacaan data hotspot, polygon KPS, dan statistik dapat diakses secara publik oleh siapa saja tanpa autentikasi.
2. **Raw SQL Construction via String Interpolation:**
   Di `fire_spread_service.py` (lines 102–103), terdapat klausul SQL:
   `f"obs.detected_at >= NOW() - INTERVAL '{int(time_window_hours)} hours'"` dan `f"ST_DWithin(poly.geometry, obs.geom, {max_deg:.6f})"`.
   Walaupun nilai saat ini di-cast ke `int` dan `float`, pola penyusunan klausa SQL menggunakan string formatting (bukan query parameter `%s`) berisiko membuka celah SQL Injection jika ada developer yang mengubah tipe data parameter di kemudian hari.
3. **Fail-Open Security Defaults on Captcha & JWT Secret:**
   `AUTH_JWT_SECRET` dan `TURNSTILE_SECRET_KEY` memiliki sifat fail-open. Jika variabel lingkungan tersebut tidak diset, sistem otomatis membuat token acak sementara atau menonaktifkan validasi captcha sepenuhnya. Meskipun mencegah server lockout, hal ini berisiko meloloskan bot jika konfigurasi environment server terhapus.
4. **Potential Cadastral Boundary Harvest:**
   Meskipun endpoint export polygon presisi penuh (`/export.geojson`) telah digerbang khusus admin, endpoint `GET /api/layers?view=preview` dan `/api/polygons/{id}` (dengan coarse tolerance) tetap menyajikan metadata izin KPS lengkap (nomor SK, lembaga, desa, luas) yang dapat di-scrape massal melalui network tab browser.

---

## 12. Technical Debt

1. **Absence of Staging / Test Database:**
   Tidak ada lingkungan pengujian terpisah. Setiap test berpotensi mengotori atau merusak database operasional riil.
2. **Absence of Database Migration Tool:**
   Tidak ada Alembic; evolusi skema tabel bergantung pada manual SQL injection atau `CREATE TABLE IF NOT EXISTS` saat boot.
3. **Zombie Codebase:**
   Pipeline GEE burned area lama (`burned_area_service.py` dan `burned_area_scheduler.py`) masih dipertahankan lengkap dengan ratusan baris test yang tidak lagi merefleksikan proses bisnis utama.
4. **Monolithic CSS:**
   File `index.css` berukuran 10,624 baris tanpa struktur modular.
5. **No Client-Side Routing Library:**
   Navigasi query string buatan sendiri di `App.tsx`.
6. **No Shared Excel Utility:**
   4 file backend berbeda mengimplementasikan openpyxl secara redundan.
7. **No Automated Linting / Formatting Pipeline:**
   Tidak ada konfigurasi ESLint atau Ruff/Black pre-commit hook terpusat, terbukti dari adanya pernyataan `import` di baris 191 di tengah file `App.tsx`.

---

## 13. Refactoring Roadmap (Planning Only — No Execution in this Phase)

### PHASE 1 — Critical Fixes & Safety Guards
* [ ] **Test Database Isolation:** Tambahkan guard di `conftest.py` dan `PostgresStore` agar test runner menolak terhubung ke host database produksi. Sediakan database PostgreSQL terpisah untuk automated testing.
* [ ] **Eliminate In-Memory Process Locks:** Ganti dictionary in-memory `_LAND_COVER_RUN_STATE` dengan PostgreSQL advisory locks atau status kolom database terindeks, sehingga aman dijalankan pada arsitektur multi-worker / multi-container.
* [ ] **Decommission Zombie Code:** Hapus `burned_area_service.py`, `burned_area_scheduler.py`, dan test terkait. Bersihkan loop background scheduler di `main.py`.

### PHASE 2 — Architecture Cleanup & Layer Boundaries
* [ ] **Database Migrations:** Terapkan Alembic. Buat baseline initial migration dari skema database aktual saat ini, dan hapus seluruh method DDL runtime (`_ensure_*`) dari Python store mixins.
* [ ] **Controller Refactoring:** Ekstrak logika grid Open-Meteo dan kalkulasi angin dari `api/weather.py` dan `api/wind.py` ke `services/weather_service.py` dan `services/wind_service.py`.
* [ ] **Consolidate Data Access:** Pindahkan raw SQL spatial queries dari `EarlyWarningService` dan `FireSpreadService` ke dalam method repository di `postgres_store/_relations.py` atau `_spatial.py`.

### PHASE 3 — Duplication Reduction
* [ ] **Unified Excel Reporting Engine:** Buat service pembantu `excel_builder.py` dan refactor 4 service pemanggil (`export_service`, `early_warning_service`, `fire_spread_service`, `point_report_service`).
* [ ] **Unify PDF Reporting Engine:** Putuskan standarisasi pada WeasyPrint + Jinja2. Migrasikan template laporan dari ReportLab ke HTML/CSS, lalu hapus `pdf_export_service.py` (1,694 baris) dan dependensi `reportlab`.
* [ ] **Single Source of Truth for Properties:** Satukan fungsi `_field_value` multi-skema GeoJSON ke `polygon_fields.py`.
* [ ] **Client-Side Type Centralization:** Pindahkan `DashboardHotspot` dan tipe duplikat lainnya ke `frontend/src/types/api.ts`.

### PHASE 4 — Component & State Refactoring
* [ ] **Deconstruct God Components:** Pecah `HotspotMatrix.tsx` (2,012L), `KpsDetailView.tsx` (1,994L), `SiagaRambatanApiView.tsx` (1,463L), dan `KompleksKebakaranView.tsx` (1,420L) ke dalam komponen-komponen presentasional kecil (<300 baris per file).
* [ ] **Adopt State Management / Data Fetching:** Integrasikan TanStack Query (React Query) untuk seluruh pengambilan data API di frontend, menggantikan prop-drilling raksasa `useDashboardData.ts` dan fetch mandiri yang terfragmentasi.
* [ ] **Modern Client Router:** Ganti hand-rolled query navigation di `App.tsx` dengan TanStack Router atau React Router v6.

### PHASE 5 — Codebase Cleanup & Modernization
* [ ] **CSS Modularization:** Pecah `index.css` (10,624 lines) menjadi CSS Modules per-komponen atau migrasikan ke Tailwind CSS. Hilangkan seluruh inline styles dari `EarlyWarningView.tsx`.
* [ ] **Repository Hygiene:** Pindahkan skrip ad-hoc (`build_*.py`, `extract_*.py`) ke direktori `backend/scripts/`. Hapus file data binary raksasa (150 MB GeoJSON, PPTX, XLSX) dari repositori git.
* [ ] **Strict Linter & Pre-commit:** Pasang Ruff untuk backend Python dan ESLint/Prettier untuk frontend TypeScript.

---

## 14. Score the Codebase

| Kriteria Evaluasi | Skor (1–10) | Alasan & Justifikasi Teknis |
|:---|:---:|:---|
| **Architecture** | **5.0 / 10** | Konsep pemisahan awal cukup baik (FastAPI + React), namun terkontaminasi oleh God Components, bypass layer di service database, dan hilangnya boundary di controller cuaca/angin. |
| **Maintainability** | **4.0 / 10** | Terdapat tujuh komponen UI berukuran di atas 1,000 baris kode dan satu file CSS 10,624 baris. Biaya navigasi dan modifikasi kode sangat tinggi. |
| **Readability** | **5.5 / 10** | Sebagian besar logika bisnis diberi komentar bahasa Indonesia yang sangat informatif (terutama di `CLAUDE.md`), namun ukuran file yang masif membuat keterbacaan struktur makro menjadi buruk. |
| **Duplication** | **4.5 / 10** | Duplikasi logika signifikan pada pembuatan berkas Excel (4 tempat), PDF basemap math (2 tempat), GeoJSON property reading (3 tempat), dan disk caching (2 tempat). |
| **Coupling** | **4.0 / 10** | Tight coupling ekstrem antara `useDashboardData` dan `App.tsx`; instansiasi konkret tanpa dependency injection di seluruh service backend. |
| **Complexity** | **4.0 / 10** | Cyclomatic & cognitive complexity sangat tinggi di `HotspotMatrix.tsx`, `KpsDetailView.tsx`, `pdf_export_service.py`, dan `land_cover_service.py`. |
| **Error Handling** | **6.0 / 10** | Try-catch cukup komprehensif dan mencegah crash fatal, namun terdapat beberapa generic empty catch dan logging inkonsisten (`print` vs `logger`). |
| **Testing** | **6.5 / 10** | Test suite cukup kaya (431 backend tests, 145 frontend tests, semua passing), tetapi ada bahaya fatal karena test dapat menyentuh database produksi jika mocking terlewat. |
| **Security** | **5.5 / 10** | Parameterized SQL query dominan, namun flag auth baca default publik (`API_REQUIRE_AUTH=false`), fail-open captcha, dan string interpolation di fire spread query menjadi catatan. |
| **Scalability** | **4.0 / 10** | In-memory locks (`_LAND_COVER_RUN_STATE`) dan scheduler background tasks menghalangi horizontal scaling dan multi-worker deployment. |

### Overall Code Health Score: **4.9 / 10**

**Alasan Skor:**  
ETA SEUNEU adalah sistem yang secara fungsional sangat kaya, matang dari segi algoritma geospasial, dan memiliki domain knowledge kehutanan yang luar biasa mendalam. Namun, secara arsitektural sistem ini menanggung **Technical Debt yang sangat berat**. Ciri khas *spaghetti code* terlihat jelas pada konsentrasi kode raksasa di komponen UI frontend, duplikasi fungsionalitas pelaporan (Excel & PDF), ketiadaan database migration framework, ketergantungan memori proses tunggal pada background job, dan risiko fatal ketiadaan isolasi database pengujian dari database produksi aktif.

---

## 15. Final Summary

* **TOTAL FILES INSPECTED:** 485 files di seluruh repositori (termasuk 151 file Python, 78 file TypeScript/TSX, 1 file CSS, 34 test files, dan file konfigurasi/dokumen).
* **TOTAL ISSUES IDENTIFIED:** 21 Distinct Architectural & Code Quality Issues
  * **CRITICAL:** 4 Temuan
  * **HIGH:** 7 Temuan
  * **MEDIUM:** 6 Temuan
  * **LOW:** 4 Temuan

### TOP 10 SPAGHETTI HOTSPOTS
1. `frontend/src/components/HotspotMatrix.tsx` (2,012 lines) — God Component Buku Besar: agregasi, chart, dialog, DOM GeoJSON.
2. `frontend/src/components/KpsDetailView.tsx` (1,994 lines) — God Component Detail KPS: 30+ useState, 7 fetch cascading useEffect, embedded map player.
3. `backend/app/services/pdf_export_service.py` (1,694 lines) — Monolithic ReportLab procedural PDF layout engine.
4. `frontend/src/components/SiagaRambatanApiView.tsx` (1,463 lines) — Monolithic visual & tabular fire threat monitoring view.
5. `frontend/src/components/KompleksKebakaranView.tsx` (1,420 lines) — ST-DBSCAN visual spatial cluster God Component.
6. `frontend/src/components/HotspotMap.tsx` (1,124 lines) — Divergent mobile/desktop Leaflet map stage with imperative click hacks.
7. `frontend/src/App.tsx` (1,090 lines) — Central monolithic routing, session management, and prop drilling gateway.
8. `frontend/src/components/EarlyWarningView.tsx` (1,073 lines) — 100% Inline styles UI with complex client-side bucketing math.
9. `frontend/src/index.css` (10,624 lines) — Unscoped monolithic global stylesheet dumping ground.
10. `frontend/src/hooks/useDashboardData.ts` (810 lines) — Monolithic client state hook holding 35+ values and operations.

---

### Jawaban Strategis:
> *"Kalau project ini akan dikembangkan 1–2 tahun ke depan, bagian mana yang paling berisiko menjadi bottleneck?"*

Bagian yang paling berisiko menjadi bottleneck utama adalah:

1. **Frontend UI State & God Components (`HotspotMatrix`, `KpsDetailView`, `useDashboardData`):**
   Frontend saat ini sudah berada di batas toleransi maintainability. Dengan ukuran masing-masing komponen menyentuh 2,000 baris dan 35+ state terpusat di satu hook, penambahan fitur baru dalam 1–2 tahun ke depan (misalnya integrasi data satelit baru, filter multi-skema baru, atau visualisasi real-time) akan memicu regresi konstan, performa render yang anjlok di mobile browser, dan keengganan engineer untuk menyentuh kode karena *cognitive overload*.
2. **Ketiadaan Database Migration Framework (Alembic) & Ketiadaan Staging Database:**
   Jika skema data perhutanan sosial dan atribusi kawasan hutan terus berkembang, perubahan skema yang dilakukan secara manual via `psql` atau string `CREATE/ALTER TABLE IF NOT EXISTS` di runtime Python akan memicu insiden korupsi data atau ketidaksinkronan struktur tabel antar developer dan environment Dokploy.
3. **In-Process Memory Locks (`_LAND_COVER_RUN_STATE` & Scheduler Tasks):**
   Saat volume pengguna atau jumlah poligon yang dianalisis bertambah dalam 1–2 tahun, sistem tidak akan bisa di-scale ke multi-worker Uvicorn atau multi-container tanpa menyebabkan kegagalan rate-limit GEE atau job collision.

---

## 16. Phase 2 — In-Depth Architecture Audit & High-Value Refactoring

> **Audit Date:** September 13, 2026  
> **Phase 2 Status:** COMPLETED — INCREMENTALLY VERIFIED (No Breaking Changes)  
> **Verification Baseline:**
> * Backend Pytest: **435/435 passing (100% green)**
> * Frontend Vitest: **145/145 passing (100% green)**
> * Frontend TypeScript Build: **0 errors (`tsc --noEmit && vite build` clean)**
> * Production Database: **Zero destructive / write operations executed**

---

### 16.1 Service Layer Deep Audit

#### Evaluasi Service Baru (`weather_service.py` & `wind_service.py`)
Service yang diekstrak pada Phase 1 diaudit berdasarkan pemisahan 5 tanggung jawab:
1. **Remote I/O:** Permintaan HTTP asinkron ke Open-Meteo (`fetch_grid_data`, `fetch_spot_weather`, `fetch_wind_data`) dan persistensi cache JSON disk lokal terisolasi rapi dengan guard try-catch dan logging.
2. **Business Logic:** Formula Tropical Keetch-Byram / McArthur Grassland Fire Danger Index (CBI) (`calculate_tropical_cbi`, `cbi_danger_category`) terlokalisasi dalam fungsi deterministik tanpa dependensi ke framework FastAPI.
3. **Numerical Computation:** Interpolasi bilinear (`bilinear_interpolate`), penghitungan axis (`build_axis`), dan konversi trigonometri kecepatan/arah angin ke komponen vektor U/V (`wind_to_uv`) murni berbasis komputasi numerik independen.
4. **Data Transformation:** Penataan data ke format GRIB / leaflet-velocity (`build_wind_header`, `empty_wind_payload`, `interpolate_wind_grid`) dipisahkan dari layer router FastAPI.
5. **Validation:** Range-checking koordinat latitude (-90 s/d 90) dan longitude (-180 s/d 180) tervalidasi sebelum komputasi grid.

#### Analisis God Service di Backend
Berdasarkan metrik kohesi dan static analysis, ditemukan 2 kandidat utama God Service:
1. **`app/services/early_warning_service.py` (739 baris):**
   * **Masalah Kohesi:** Modul ini mencampuradukkan perhitungan skor indeks ancaman kebakaran (`compute_ftri_score`), query agregasi database spasial (`get_summary_metrics`), paginasi dan filter tabel KPS (`get_kps_analysis_list` — 370 baris, Cyclomatic Complexity 53), dan pembangkitan file biner Excel menggunakan styling OpenPyXL (`build_excel_export` — 179 baris, CC 41).
   * **Rekomendasi:** Ekstrak `build_excel_export` ke modul pelaporan tersendiri atau satukan ke `export_service.py`, sehingga service ini murni fokus pada logika domain Early Warning.
2. **`app/services/postgres_store/` (Gateway Pattern):**
   * Memiliki 13 mixin modules (`_base.py`, `_burned_area.py`, `_cache.py`, `_history.py`, `_hotspots.py`, `_land_cover.py`, `_layers.py`, `_polygons.py`, `_relations.py`, `_s2_burned_area.py`, `_scheduler.py`, `_spatial.py`, `_users.py`) yang disatukan via multiple inheritance ke `PostgresStore`.
   * Diimpor oleh 21 file. Memiliki fan-in tertinggi di layer layanan data.

---

### 16.2 Frontend State Management Audit

Audit mendalam terhadap alur dependensi: `Component → Hook → Service/API → State`

1. **Monolithic State Hook (`frontend/src/hooks/useDashboardData.ts`):**
   * Menggunakan **21 `useState`** dan **9 `useEffect`** dalam satu hook tunggal (782 baris).
   * **Polling Cascading Effect:** Pembaruan state `setClockTick` setiap 60 detik memicu re-kalkulasi `buildTimeRange`, yang mengubah referensi objek `hotspotQueryParams`, memicu 4 panggilan API independen (`getHotspots`, `getHistoryStatus`, `getStorageStatus`, `getSchedulerMetrics`) secara beruntun.
   * **State Synchronization Hack:** Terdapat guard `isFirstStorageRef = useRef(true)` dan `isFirstHotspotsRef = useRef(true)` untuk membatalkan eksekusi `useEffect` pada render pertama karena `loadInitialData()` sudah mengambil data saat inisialisasi. Ini adalah konsekuensi langsung dari ketiadaan declarative server-state management (seperti React Query).
2. **Prop Drilling di `frontend/src/App.tsx`:**
   * `App.tsx` mendestrukturisasi lebih dari 20 field/action dari `useDashboardData` lalu meneruskannya ke bawah (drill) melalui 3–4 lapis komponen (`HotspotMap`, `HotspotMatrix`, `KpsDetailView`, `FilterPanel`, dll.).
3. **State Duplication & Unnecessary Allocations:**
   * Di `App.tsx:958`, array hotspot dipetakan ulang (`.map((hotspot) => ({ ... }))`) menjadi objek baru saat dilempar ke `HotspotMatrix`, memicu alokasi ribuan objek baru pada setiap render.

---

### 16.3 Backend Logging Audit

Hasil audit terhadap seluruh pemanggilan log di `backend/app`:
1. **Print Statements:** Telah diaudit dengan regex `\bprint\s*\(`. Ditemukan **0 print statement** di `backend/app`. Seluruh debug log sebelumnya telah bersih.
2. **Inconsistent Logger Names & Inline Imports:**
   * `backend/app/services/hotspot_service.py` baris 109 memuat inline `import logging` dan memanggil `logging.getLogger("hotspot.service")` alih-alih menggunakan instance modul `logger`.
   * `backend/app/services/geojson_sync_service.py` baris 198 memuat inline `import logging` dan memanggil `logging.getLogger("hotspot.geojson_sync")` di dalam blok try-except.
   * Modul-modul lain menggunakan penamaan logger yang heterogen (`hotspot.service`, `burned_area.klhk`, `weather.service`, `__name__`).
3. **Swallowed Exceptions:**
   * Terdapat 12 blok `except Exception:` di `hotspot_service.py` yang menelan error secara diam-diam tanpa log traceback.

---

### 16.4 Duplication Re-Audit

1. **Circular Dependency & Type Shadowing:**
   * Ditemukan circular dependency frontend: `hooks/useDashboardData.ts` ↔ `lib/dashboardPersistence.ts`. `dashboardPersistence.ts` mengimpor tipe dari `useDashboardData.ts`.
   * Ditemukan tipe lokal bayangan (shadow types) yang menduplikasi `DashboardHotspot` dan `DashboardLayer`:
     * `HotspotMap.tsx` mendefinisikan `type HotspotRecord` dan `type LayerRecord` lokal (28 baris duplikat).
     * `HotspotMatrix.tsx` mendefinisikan `type MatrixHotspot` lokal (18 baris duplikat).
     * `KpsDetailView.tsx` mengimpor `DashboardHotspot` dari `hooks/useDashboardData` bukan dari tipe kanonikal.
2. **PostgresStore Instantiation Duplication:**
   * Di `backend/app/api/burned_area.py`, ekspresi `PostgresStore(get_settings().database_url)` diulang 10 kali di 10 router handler yang berbeda, alih-alih memanfaatkan FastAPI Dependency Injection (`Depends`).

---

### 16.5 Dependency Graph & Top 10 Riskiest Modules

#### Circular Dependency Check
* **Backend:** **0 circular dependencies** (berdasarkan AST traversal DFS cycle detection).
* **Frontend:** **0 circular dependencies** (setelah siklus `useDashboardData.ts` ↔ `dashboardPersistence.ts` dieliminasi pada Phase 2).

#### Top 10 Modules Paling Berisiko (Risk Assessment)
| No | Modul | Kategori | Alasan Risiko & Dampak Perubahan |
|:---:|:---|:---|:---|
| 1 | `backend/app/services/postgres_store/` | Data Layer | Fan-in tertinggi (21 callers); menghubungkan 13 mixin. Regresi di sini merusak seluruh endpoint backend. |
| 2 | `frontend/src/hooks/useDashboardData.ts` | State Hook | 21 useState, 9 useEffect, cascading network triggers; pusat kendali seluruh data dashboard. |
| 3 | `frontend/src/components/HotspotMatrix.tsx` | UI Component | 2,012 baris kode; menggabungkan tabel, grafik, ekspor XLSX/GeoJSON, dan filtering. |
| 4 | `frontend/src/components/KpsDetailView.tsx` | UI Component | 1,994 baris kode; peta Leaflet detail, video/GIF animator, grafik tutupan lahan, weather card. |
| 5 | `backend/app/services/early_warning_service.py` | Domain Service | CC=53 pada fungsi 370 baris; mencampur SQL agregasi dan formatting OpenPyXL. |
| 6 | `frontend/src/App.tsx` | App Root | 1,090 baris; URL router manual via `popstate`, manajemen session JWT, prop drilling luas. |
| 7 | `backend/app/services/agency_pdf_service.py` | Reporting | Fungsi WeasyPrint 341 baris (CC=27); manipulasi tangkapan layar basemap base64. |
| 8 | `backend/app/services/hotspot_service.py` | Domain Service | CC=33 pada `fetch_filtered_hotspots` (155 baris); fallback bertingkat NASA FIRMS dan DB caching. |
| 9 | `frontend/src/components/SiagaRambatanApiView.tsx` | UI Component | 1,463 baris; visualisasi dan analisis perambatan api kompleks. |
| 10 | `backend/app/services/fire_spread_service.py` | Domain Service | 681 baris; kalkulasi ancaman kebakaran multi-layer dan query spasial besar. |

---

### 16.6 Static Analysis Hotspot Metrics (Aktual)

#### Top 10 Fungsi Terpanjang (Backend)
1. `app/services/early_warning_service.py:get_kps_analysis_list` — **370 baris**
2. `app/services/agency_pdf_service.py:build_agency_pdf_weasyprint` — **341 baris**
3. `app/services/fire_spread_service.py:get_threat_detail` — **213 baris**
4. `app/services/fire_spread_service.py:get_threats` — **180 baris**
5. `app/services/early_warning_service.py:build_excel_export` — **179 baris**
6. `app/services/land_cover_service.py:analyze_polygon` — **178 baris**
7. `app/services/export_service.py:_write_burned_area_sheet` — **164 baris**
8. `app/services/hotspot_service.py:fetch_filtered_hotspots` — **155 baris**
9. `app/services/hotspot_cluster_service.py:_summarize` — **154 baris**
10. `app/services/agency_pdf_service.py:_fetch_map_b64` — **144 baris**

#### Top 10 Fungsi dengan Cyclomatic Complexity Tertinggi (Backend)
1. `app/services/early_warning_service.py:get_kps_analysis_list` — **CC = 53**
2. `app/services/early_warning_service.py:build_excel_export` — **CC = 41**
3. `app/services/hotspot_service.py:fetch_filtered_hotspots` — **CC = 33**
4. `app/services/agency_pdf_service.py:build_agency_pdf_weasyprint` — **CC = 27**
5. `app/services/early_warning_service.py:get_summary_metrics` — **CC = 26**
6. `app/services/hotspot_service.py:_persist_filtered_hotspots` — **CC = 24**
7. `app/services/fire_spread_service.py:get_threats` — **CC = 24**
8. `app/services/land_cover/labels.py:spectral_seed_image` — **CC = 23**
9. `app/services/burned_area_report.py:load_burned_area_report` — **CC = 23**
10. `app/services/agency_pdf_service.py:_fetch_map_b64` — **CC = 23**

#### Top 10 Komponen Terbesar (Frontend)
1. `frontend/src/components/HotspotMatrix.tsx` — **2,013 baris**
2. `frontend/src/components/KpsDetailView.tsx` — **1,994 baris**
3. `frontend/src/components/SiagaRambatanApiView.tsx` — **1,463 baris**
4. `frontend/src/components/KompleksKebakaranView.tsx` — **1,420 baris**
5. `frontend/src/components/HotspotMap.tsx` — **1,125 baris**
6. `frontend/src/App.tsx` — **1,091 baris**
7. `frontend/src/components/EarlyWarningView.tsx` — **1,073 baris**
8. `frontend/src/components/LandCoverPanel.tsx` — **835 baris**
9. `frontend/src/hooks/useDashboardData.ts` — **782 baris**
10. `frontend/src/components/SettingsPanel.tsx` — **640 baris**

#### Top 5 Most-Imported Modules (Fan-In)
1. `app.core.config` — **30 callers**
2. `app.services.postgres_store` — **21 callers**
3. `app.core.auth` — **12 callers**
4. `app.services.postgres_store._base` — **9 callers**
5. `app.models.query` — **7 callers**

#### Top 5 Most-Dependent Modules (Fan-Out)
1. `app/api/router.py` — **19 dependencies**
2. `app/services/postgres_store/__init__.py` — **13 dependencies**
3. `app/api/export.py` — **10 dependencies**
4. `app/services/hotspot_service.py` — **10 dependencies**
5. `app/main.py` — **6 dependencies**

---

### 16.7 Perbaikan Berkualitas Tinggi yang Telah Diimplementasikan (Phase 2 Refactoring)

1. **Pemusnahan Circular Dependency Frontend:**
   * Mengubah `frontend/src/lib/dashboardPersistence.ts` untuk mengimpor `DashboardHotspot` dan `DashboardLayer` langsung dari `../types/api`, memutus ketergantungan siklik dengan `useDashboardData.ts`. Hasil: **0 circular dependency** di seluruh frontend.
2. **Eliminasi Tipe Duplikat / Shadow Types di Frontend:**
   * Di `frontend/src/components/HotspotMap.tsx`: Menghapus deklarasi redundan `type HotspotRecord = { ... }` dan `type LayerRecord = { ... }`, menyelaraskannya ke tipe kanonikal `DashboardHotspot` dan `DashboardLayer`.
   * Di `frontend/src/components/HotspotMatrix.tsx`: Menghapus deklarasi redundan `type MatrixHotspot = { ... }` (18 baris duplikat) dan mengalihkannya ke tipe kanonikal `DashboardHotspot`.
   * Di `frontend/src/components/KpsDetailView.tsx`: Menyelaraskan impor `DashboardHotspot` langsung dari `../types/api`.
3. **Pemberhentian Alokasi Objek Redundan di App.tsx:**
   * Mengeliminasi pemetaan `.map((hotspot) => ({ ... }))` pada render `<HotspotMatrix />` di `App.tsx:958`, langsung meneruskan referensi typed array `session?.role === "bps" ? visibleHotspots : hotspots`.
4. **Pembersihan Logging & Inline Imports di Backend:**
   * Menghilangkan inline `import logging` dan pemanggilan `logging.getLogger` berulang di `backend/app/services/hotspot_service.py` dan `backend/app/services/geojson_sync_service.py`, menggantikannya dengan logger modul tersentralisasi.
5. **Harmonisasi Skema Tipe Hotspot:**
   * Menjadikan field `fungsiKawasan?: string`, `namaKawasan?: string`, dan `kelompokKawasan?: string` optional pada `DashboardHotspot` di `frontend/src/types/api.ts` agar selaras antara mock pengujian, data mentah sebelum spatial join, dan data terhidrasi penuh.
6. **Dekopling Generator Excel dari Domain Early Warning:**
   * Memisahkan logika biner formatting OpenPyXL `build_excel_export` (179 baris) ke modul terdedikasi [`backend/app/services/early_warning_export.py`](file:///home/ryandshinevps/etaseneu/backend/app/services/early_warning_export.py). Ukuran `early_warning_service.py` terpangkas dari 739 baris menjadi 560 baris, dan dependensi `openpyxl` terisolasi dari domain service.
7. **Dependency Injection di Router Burned Area:**
   * Mengganti 10 instansiasi manual `PostgresStore(get_settings().database_url)` di [`backend/app/api/burned_area.py`](file:///home/ryandshinevps/etaseneu/backend/app/api/burned_area.py) dengan mekanisme dependency injection kanonikal FastAPI: `store: PostgresStore = Depends(_get_store)`.
8. **Dekomposisi Awal God Component HotspotMatrix (Frontend):**
   * Mengekstrak 364 baris logika agregasi statistik distribusi (FRP, Confidence, Kawasan, Skema-Provinsi Matrix, Trend Harian, YoY) ke modul independen [`frontend/src/lib/matrixAggregations.ts`](file:///home/ryandshinevps/etaseneu/frontend/src/lib/matrixAggregations.ts).
   * Mengekstrak logika pembuatan & download berkas GeoJSON ke modul independen [`frontend/src/lib/matrixGeoJson.ts`](file:///home/ryandshinevps/etaseneu/frontend/src/lib/matrixGeoJson.ts).
   * Ukuran [`HotspotMatrix.tsx`](file:///home/ryandshinevps/etaseneu/frontend/src/components/HotspotMatrix.tsx) terpangkas dari **2.013 baris menjadi 1.649 baris** (-364 baris), dengan logika bisnis statistik yang kini dapat diuji unit secara murni tanpa merender DOM React.

---

### 16.8 Evaluasi Status Arsitektur Pasca-Phase 2

| Kriteria Evaluasi | Sebelum Audit | Pasca Phase 1 | Pasca Phase 2 | Status |
|:---|:---:|:---:|:---:|:---|
| **Backend Test Passing** | 428 passing (3 failed) | 435 passing (100%) | **435 passing (100%)** | Hijau stabil |
| **Frontend Test Passing** | 145 passing | 145 passing (100%) | **145 passing (100%)** | Hijau stabil |
| **TypeScript Build Errors** | Misplaced imports | 0 error | **0 error, clean build** | Sukses |
| **Circular Dependencies** | Ada di frontend (1) | Ada di frontend (1) | **0 di Backend, 0 di Frontend** | Bersih total |
| **Shadow / Duplicate Types** | Tersebar di 4 file | Tersebar di 3 file | **Tersentralisasi di `types/api.ts`** | Terselesaikan |
| **Controller Bloat** | Cuaca & Angin di Router | Dipisah ke Service | **Tervalidasi & Terisolasi** | Bersih |
| **Production Database** | Terancam shared host | Terlindungi | **Terlindungi (Zero destructive ops)** | Aman |

