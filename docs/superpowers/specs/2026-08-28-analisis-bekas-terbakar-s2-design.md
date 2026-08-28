# Desain: Analisis Bekas Terbakar mandiri (Sentinel-2 dNBR)

Tanggal: 2026-08-28
Status: draft — menunggu review sebelum implementation plan.

## Tujuan

Sistem ETA SENEU bisa **menghitung sendiri** luas bekas terbakar per KPS /
Hutan Adat untuk **Agustus 2026 dan seterusnya**, tanpa menunggu rekap resmi
KLHK (yang telat ~1 bulan). Sumber: citra **Sentinel-2 L2A** via Google Earth
Engine, indeks **dNBR** multi-kriteria.

Bukan pengganti angka KLHK — hasilnya selalu berlabel **"Estimasi Sentinel-2"**
(`source` berbeda) dan tidak pernah menimpa baris KLHK.

## Keputusan (disepakati di diskusi 2026-08-28)

1. **Metode:** Sentinel-2 dNBR yang diperbaiki (bukan MCD64A1 500 m, bukan
   buffer-hotspot yang sudah di-revert).
2. **Pemicu:** tombol admin *on-demand* saja. **Tidak ada scheduler.**
3. **Lingkup:** luas bekas terbakar saja (severitas/perambatan menyusul).
4. **Target = SEMUA poligon `is_active`** (KPS `psagustus2026` + Hutan Adat),
   **bukan** hanya yang ber-hotspot — justru gunanya satelit adalah menangkap
   "terbakar tapi tidak ada hotspot".
5. **Hotspot = penanda keyakinan, bukan filter.**
6. **Tiga tingkat keyakinan** berdasar kekuatan sinyal dNBR:
   - **Tinggi:** `dNBR ≥ 0.27` + gate → scar andal walau tanpa hotspot.
   - **Sedang:** `dNBR 0.12–0.27` + SEMUA gate pendukung → area gambut/terdegradasi
     (sinyal lemah) sekaligus zona rawan false-positive.
   - **Rendah:** lebih lemah, atau `low_data`.
7. **Pelaporan berlapis** (bukan satu angka):
   - `burned_area_ha` (angka utama) = **Tinggi + Sedang**.
   - `burned_area_ha_high` = **Tinggi saja** (konservatif, paling defensible).
   - **Rendah tidak masuk total** → antrean "perlu verifikasi".
8. **Guard:** tolak `(year, month)` yang sudah penuh data `source LIKE 'KLHK%'`
   kecuali `force=true`; per-poligon, skip kalau sudah ada baris KLHK.

## Data & skema

### Perubahan tabel `burned_area_summary` (additive, aman)

```sql
ALTER TABLE burned_area_summary ADD COLUMN IF NOT EXISTS burned_area_ha_high double precision;
ALTER TABLE burned_area_summary ADD COLUMN IF NOT EXISTS confidence text;          -- 'tinggi' | 'sedang' | 'campuran'
ALTER TABLE burned_area_summary ADD COLUMN IF NOT EXISTS hotspot_count_month integer;
```

- UNIQUE `(polygon_metadata_id, year, month)` tetap. `source` untuk hasil ini:
  `'Sentinel-2 dNBR (ETA SENEU)'`.
- Kolom lama tetap dipakai untuk KLHK (nilainya NULL di baris S-2 kecuali yang
  di atas).

### Query target poligon

```sql
SELECT id, layer_key, geometry, nama_prov
FROM polygon_metadata
WHERE layer_key IN ('psagustus2026','HUTAN_ADAT_APR26') AND is_active
```

### Hotspot per poligon per bulan (untuk `hotspot_count_month` + confidence)

Spasial (bukan `hotspot_polygon_relation` yang tidak lengkap):

```sql
SELECT pm.id, COUNT(*) n
FROM polygon_metadata pm
JOIN hotspot_observations ho
  ON ho.detected_at >= :m0 AND ho.detected_at < :m1
 AND ST_Contains(pm.geometry, ho.geom)
WHERE pm.id = ANY(:ids)
GROUP BY pm.id
```

## Arsitektur backend

### `app/services/burned_area_s2_service.py` — `Sentinel2BurnedAreaService`

- `enabled` → `bool(settings.gee_service_account_email and ..._key_path and
  ..._project_id)`. `_ensure_ee()` (salin dari `burned_area_service.py`).
- `analyze_month(year: int, month: int, *, force: bool = False) -> dict`
  1. **Guard bulan:** kalau semua poligon target sudah punya baris
     `source LIKE 'KLHK%'` untuk `(year,month)` dan `not force` → raise
     `Sentinel2BurnedAreaError("bulan ini sudah punya data KLHK resmi")`.
  2. Ambil poligon target + hitung `hotspot_count_month` per poligon.
  3. **Per region** (kelompok provinsi: Sumatera / Kalimantan / Sulawesi /
     Jawa-Bali-Nusra / Maluku-Papua) supaya raster GEE tidak kebesaran:
     - **pre = komposit NBR-MAKSIMUM** (`ee.ImageCollection(...).qualityMosaic('nbr')`
       atau `.max()`), rentang `year-01-01` → `(m0 - 15 hari)`. Cloud-mask SCL.
     - **post = komposit NBR-MINIMUM per piksel** (`.min()` band nbr), rentang
       `m0` → `min(m1, hari ini)`.
     - `dNBR = nbr_pre_max − nbr_post_min`; `dNDVI`, `NDVI_pre`, `MNDWI` seperti
       script lama.
     - **valid-obs count** per piksel (jumlah citra lolos cloud-mask di jendela
       post); piksel `< 2` → di-mask, dan kalau median coverage poligon `< 2`
       → poligon ditandai `low_data`.
     - **mask Tinggi:** `dNBR ≥ 0.27 AND dNDVI ≥ 0.10 AND NDVI_pre ≥ 0.20 AND MNDWI < 0.05`.
     - **mask Sedang:** `dNBR ≥ 0.12 AND dNBR < 0.27 AND dNDVI ≥ 0.12 AND
       NDVI_pre ≥ 0.20 AND MNDWI < 0 AND (B12_post − B12_pre) ≥ 0.02`.
     - **filter noise:** `connectedPixelCount(25, true)`; buang piksel yang
       patch-nya `< 5` px (≈ 0.2 ha @ 20 m) — untuk kedua mask.
     - `reduceRegions` atas FeatureCollection poligon region (batch ≤ 1000,
       `scale=20`, `tileScale=4`, `bestEffort=true`), dua reducer: `sum` luas
       mask Tinggi, `sum` luas mask Sedang → m² → ha.
     - Vektorisasi gabungan (Tinggi ∪ Sedang) → `reduceToVectors(scale=20)` →
       clip ke batas poligon → `ST_SimplifyPreserveTopology(0.0003)`.
  4. Untuk tiap poligon:
     - `ha_high` = luas mask Tinggi; `ha_total` = Tinggi + Sedang.
     - `confidence` = `'tinggi'` kalau `ha_high == ha_total` (semua dari mask
       Tinggi), else `'campuran'`. `low_data` → tambahkan flag di properties.
     - **Skip** kalau `ha_total < 0.2` ha.
     - **Skip** kalau sudah ada baris `source LIKE 'KLHK%'` untuk poligon+bulan
       ini.
  5. **Upsert** `burned_area_summary`:
     `burned_area_ha = ha_total`, `burned_area_ha_high = ha_high`,
     `confidence`, `hotspot_count_month`, `source='Sentinel-2 dNBR (ETA SENEU)'`,
     `computed_at = NOW()`, `geometry`.
  6. Return `{"target": "YYYY-MM", "polygons_target": N, "polygons_burned": B,
     "total_ha": ..., "total_ha_high": ..., "low_data": L, "hotspot_confirmed": H,
     "no_hotspot_but_burned": NH, "duration_s": ...}`.
- Jalan **sinkron**; dipanggil dari `BackgroundTasks`. Progres ditulis ke
  modul-global `_s2_run_state` (dict) + baris hasil terakhir.

### API (`app/api/burned_area.py`)

- `POST /api/burned-area/analyze-s2` — `Depends(require_admin_key)`.
  Query opsional `year`, `month` (default = bulan berjalan WIB), `force` (bool).
  Kalau sudah ada run `state == "running"` → `409`. Else mulai
  `BackgroundTasks`, balas `202 {"started": true, "target": "YYYY-MM"}`.
- `GET /api/burned-area/analyze-s2/status` — `Depends(require_session_if_enabled)`.
  `{"state": "idle|running|done|error", "target", "progress": "12/48 region Kalimantan",
    "result": {...ringkasan...} | null, "message", "started_at", "finished_at"}`.

### Guard konfigurasi

- Kalau `not service.enabled` → endpoint balas `503 {"detail": "GEE belum
  dikonfigurasi di server"}` (fail-closed, pola sama `ADMIN_API_KEY`).

## Frontend (`SettingsPanel.tsx`, khusus `session.role === "admin"`)

Kartu baru **"Analisis Bekas Terbakar — Sentinel-2 dNBR"**:
- `<select>` bulan (opsi: bulan berjalan + 3 bulan ke belakang; label
  "Agustus 2026", dst). Default bulan berjalan.
- Tombol **"Hitung sekarang"** — `authFetch POST /api/burned-area/analyze-s2?...`.
  Disabled saat `state === "running"` (polling `/status` tiap 4 dtk).
- Baris status:
  - idle: "Belum pernah dijalankan bulan ini."
  - running: "Menghitung… {progress}"
  - done: "{polygons_burned} KPS terbakar · estimasi ±{total_ha} ha
    (tingkat tinggi ±{total_ha_high} ha) · {no_hotspot_but_burned} terbakar
    tanpa hotspot · {low_data} data tipis"
  - error: pesan.
- Catatan kecil: "Estimasi satelit, bukan angka resmi KLHK. Bulan Jan–Jul
  tidak bisa dihitung ulang (sudah ada data resmi)."

## Test

- `app/tests/test_burned_area_s2_service.py` — `ee` di-monkeypatch penuh
  (tidak ada panggilan GEE nyata), `PostgresStore` pola `Disabled*` (bahaya #1):
  - `enabled` False saat env GEE kosong.
  - `analyze_month` menolak bulan yang penuh KLHK tanpa `force`.
  - upsert dipanggil dengan kolom baru terisi benar (mock store merekam args).
  - poligon dengan baris KLHK → di-skip.
  - confidence: semua-Tinggi → `'tinggi'`; campuran → `'campuran'`.
  - ringkasan menghitung `no_hotspot_but_burned` benar.
- `app/tests/test_burned_area_s2_api.py`:
  - `POST` tanpa admin key → 401; dengan key, GEE tak dikonfigurasi → 503.
  - `POST` saat sudah running → 409.
  - `GET /status` transisi idle → running → done (service di-stub).
- Frontend `SettingsPanel.test.tsx` — kartu muncul hanya untuk admin; tombol
  disabled saat running; teks status dari respons `/status`.

## Migrasi & deploy

- `ALTER TABLE` additive dijalankan otomatis di `_ensure_*` store (pola yang
  sudah dipakai `_ensure_burned_area_scheduler_state_table`) — tidak ada skrip
  migrasi manual.
- Tambah `HOST_GEE_KEY_PATH` sudah ada di `docker-compose.dokploy.yml`
  (mount ke `/app/secrets/gee-service-account-key.json`). Pastikan
  `GEE_SERVICE_ACCOUNT_KEY_PATH` di `.env.dokploy` menunjuk ke situ (script
  lama meng-hardcode `/app/shp/...` — service baru pakai `settings.gee_*`).
- `earthengine-api` sudah di `requirements.txt`.
- CLAUDE.md: perbarui bahaya #2 — GEE dipakai lagi untuk jalur Sentinel-2
  on-demand (bukan MODIS terjadwal); KLHK tetap sumber resmi.

## Risiko

| Risiko | Mitigasi |
|---|---|
| Menimpa data KLHK resmi | Guard per-bulan + per-poligon (skip kalau ada `source LIKE 'KLHK%'`) |
| Kuota / waktu GEE | On-demand saja; raster per-region + `reduceRegions` batch (bukan loop per-poligon); `bestEffort` + `tileScale` |
| Formula belum tervalidasi lapangan | Selalu label "Estimasi Sentinel-2"; simpan angka Tinggi terpisah; Rendah dikecualikan |
| Tulis ke DB produksi (tak ada staging) | Upsert idempotent per `(poligon, tahun, bulan)`; `source` khusus; bisa dihapus via `DELETE ... WHERE source='Sentinel-2 dNBR (ETA SENEU)'` |
| GEE service account/key tidak valid di server | `enabled` fail-closed → endpoint 503, tidak diam-diam menulis nol |

## Di luar lingkup (menyusul)

- Klasifikasi severitas (rendah/sedang/tinggi Key–Benson) per area terbakar.
- Analisis perambatan/dampak otomatis.
- Scheduler otomatis (sekarang on-demand saja).
- Validasi akurasi terhadap sampel KLHK saat rekap Agustus terbit.
