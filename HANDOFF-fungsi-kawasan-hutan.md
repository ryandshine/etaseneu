# Handoff — Layer & Atribusi "Fungsi Kawasan Hutan" untuk etaseneu

**Tanggal:** 2026-08-31
**Konteks:** Menambahkan layer Kawasan Hutan KLHK (KWSHUTAN_AR_250K_JUN2026) ke etaseneu
sebagai (a) overlay peta dan (b) atribusi spasial — tiap hotspot & poligon lahan
terbakar tahu masuk fungsi kawasan hutan yang mana.

Dikerjakan menyesuaikan kapasitas server (i7-3770, 15 GB RAM, PostGIS dipakai
bersama 7 app): **geometri detail hanya di PostGIS**, join dikerjakan sekali +
refresh inkremental, etaseneu **tidak pernah** memuat geojson detail penuh ke RAM.

---

## STATUS

| Bagian | Status | Perlu deploy? |
|---|---|---|
| (a) Overlay `fungsi_kawasan_hutan.geojson` | ✅ **LIVE** — file di `/data/apps/etaseneu/shp/`, cache sudah di-refresh | ❌ tidak (file data, di luar repo) |
| (b) Data atribusi di PostGIS (tabel + fungsi) | ✅ **LIVE di DB `etaseneu`** | ❌ tidak (SQL langsung) |
| Cron refresh harian | ⏳ **BELUM** — 1 perintah, lihat §4 | — |
| **Fase 4: tampilkan atribusi di API + PDF + XLSX** | ❌ **BELUM** — ini pekerjaan handoff ini, lihat §5 | ✅ commit + push + redeploy |
| Verifikasi label sub-kode konservasi (~92 hotspot) | ⏳ opsional, lihat §6 | — |

**Kondisi sekarang untuk user:** overlay tampil di peta; data "hotspot/luas terbakar
di kawasan mana" **sudah lengkap di DB** tapi **belum muncul** di UI/laporan sampai
Fase 4 selesai.

---

## 1. Overlay (bagian a) — SELESAI

- File: `/data/apps/etaseneu/shp/fungsi_kawasan_hutan.geojson` (101 MB, 30.883 fitur,
  EPSG:4326/CRS84).
- Dibuat dari `/data/storage/shp/fungsi_kawasan_hutan/KWSHUTAN_AR_250K_JUN2026.shp`
  (985 MB) via:
  `ogr2ogr -f GeoJSON out.geojson in.shp -select FUNGSIKWS,NAMOBJ,KODE_PROV -simplify 0.001 -lco COORDINATE_PRECISION=5`
- Disederhanakan ~110 m (Douglas-Peucker) supaya lebih ringan dari `psagustus2026.geojson`
  (184 MB) yang sudah dipakai. **Hanya untuk tampilan** — atribusi presisi pakai tabel
  PostGIS detail penuh (§2), terpisah.
- Layer otomatis dimuat `LayerService.list_layers()` / `list_preview_layers()` karena
  keduanya `glob("*.geojson")` di `SHP_DIR`. `layer_key` = `fungsi_kawasan_hutan`.
- Cache sudah di-clear: `POST /api/cache/refresh` (header `X-Admin-Key: <ADMIN_API_KEY>`).

**Catatan:** `_friendly_layer_name("fungsi_kawasan_hutan")` menentukan nama tampil.
Cek `app/models/layers.py` / `_friendly_layer_name` kalau mau nama & warna khusus.

---

## 2. Data atribusi di PostGIS (bagian b) — SELESAI

DB: `etaseneu` di container `gealgeolgeo-postgis` (host port `5434`, user `gealgeolgeo`).

### Tabel & fungsi baru

| Objek | Isi | Ukuran |
|---|---|---|
| `ref_kawasan_hutan` | 30.883 poligon referensi detail penuh. Kolom: `id, fungsikws (numeric), namobj (text), kode_prov (numeric), geom (MultiPolygon, 4326)`. GiST index di `geom`. | 976 MB |
| `ref_kawasan_hutan_sub` | `ST_Subdivide(geom, 256)` → 1.032.082 keping kecil. Kolom: `src_id, fungsikws, namobj, kode_prov, geom`. GiST index `ref_khs_gix`. **Ini yang dipakai untuk join** (bbox ketat = cepat). | 1,3 GB |
| `hotspot_kawasan_hutan` | Lookup hasil join. Kolom: `hotspot_id (PK) → hotspot_observations.id`, `kawasan_id`, `fungsikws`, `nama_kawasan`, `kode_prov`, `kelompok`. Index di `fungsikws`. | 3,8 MB |
| `burned_kawasan_hutan` | Rincian per (poligon terbakar × fungsi kawasan). Kolom: `burned_id → s2_burned_area.id`, `fungsikws`, `kelompok`, `luas_ha`. Index di `burned_id`, `fungsikws`. | 280 kB |
| `ref_fungsi_kawasan_label` | Peta `kode (numeric PK) → singkatan, fungsi, kelompok, catatan`. Isi awal di §6. | 32 kB |
| `fungsi_kawasan_kelompok(kode numeric) → text` | Fungsi SQL IMMUTABLE. Fallback kelompok berbasis prefix kode (Konservasi / Lindung / Produksi / Non-Kawasan Hutan). | — |
| `refresh_kawasan_attribution() → (hotspot_baru, hotspot_hapus, burned_rebuild)` | Fungsi plpgsql. Inkremental untuk hotspot (insert yang belum ada + hapus yang sumbernya hilang), rebuild penuh untuk burned (kecil). ~20 dtk. | — |

DB `etaseneu`: 456 MB → **2,7 GB** (semua di SSD `/data`, sisa 922 GB).

### Hasil verifikasi awal (2026-08-31)

- Hotspot: **25.943 / 25.947** ter-atribusi (4 di luar semua kawasan). Join: **2,7 dtk**.
  - per kelompok: Produksi 12.121 · Lindung 8.088 · Konservasi 5.733 · Non-KH 1
- Lahan terbakar: **1.341 / 1.341** poligon ter-atribusi. **22.929 ha** total di kawasan hutan.
  - per kelompok: Produksi 9.949 ha · Lindung 8.191 ha · Konservasi 4.789 ha

### Cara re-run manual / rollback

```bash
# jalankan lagi (kalau tabel sumber berubah)
docker exec gealgeolgeo-postgis psql -U gealgeolgeo -d etaseneu -c "SELECT refresh_kawasan_attribution();"

# rollback total bagian b
docker exec gealgeolgeo-postgis psql -U gealgeolgeo -d etaseneu -c "
DROP TABLE IF EXISTS hotspot_kawasan_hutan, burned_kawasan_hutan,
  ref_kawasan_hutan_sub, ref_kawasan_hutan, ref_fungsi_kawasan_label CASCADE;
DROP FUNCTION IF EXISTS refresh_kawasan_attribution();
DROP FUNCTION IF EXISTS fungsi_kawasan_kelompok(numeric);"
```

**Tuning PostGIS:** `work_mem` HANYA dinaikkan per-sesi saat build (`SET work_mem='96MB'`).
Tidak ada `ALTER SYSTEM`, tidak ada restart container. Persisten tetap `work_mem=4MB`
(di `command:` compose `~/gealgeolgeo/docker-compose.yml`). Query LEFT JOIN di Fase 4
ke tabel ber-index kecil → tidak butuh work_mem besar. Kalau nanti join berat rutin,
naikkan `work_mem` 4→16 MB & `maintenance_work_mem` 64→256 MB di compose (perlu restart
`gealgeolgeo-postgis` = kedip ~15-30 dtk untuk etaseneu + sipekaps + kitapantaups).

---

## 3. Sumber data mentah

- Shapefile: `/data/storage/shp/fungsi_kawasan_hutan/KWSHUTAN_AR_250K_JUN2026.{shp,dbf,shx,prj,cpg}`
  (arsip user di `/data/storage`, di luar sistem app). Sudah masuk `ref_kawasan_hutan`,
  jadi redundan untuk app — tapi **jangan hapus** tanpa konfirmasi user (arsipnya).
- CRS: `GCS_WGS_1984` / EPSG:4326. Extent: 94.97–141.02 E, -11.01–6.08 N.
- Kolom dbf lengkap: `NO_REG, KODE_PROV, FUNGSIKWS, NOSKKWS, TGLSKKWS, LSKKWS, NAMOBJ,
  FCODE, LCODE, METADATA, SRS_ID, REMARK, NOSKTAP, TGLSKTAP, LSKTAP`. Hanya
  `FUNGSIKWS, NAMOBJ, KODE_PROV` yang diambil (sisanya teks SK panjang, tak perlu).

---

## 4. Cron refresh harian — JALANKAN INI

Classifier memblokir pemasangan otomatis. Tempel di terminal (user `ryandshinevps`,
sudah di grup `docker` jadi tanpa sudo):

```bash
( crontab -l 2>/dev/null; echo '15 4 * * * docker exec gealgeolgeo-postgis psql -U gealgeolgeo -d etaseneu -c "SELECT refresh_kawasan_attribution();" >> /home/ryandshinevps/etaseneu-kawasan-refresh.log 2>&1' ) | crontab -
crontab -l   # verifikasi
```

Jam 04:15 dipilih setelah sinkron hotspot NASA FIRMS harian. Sesuaikan kalau perlu.

---

## 5. FASE 4 — Tampilkan atribusi di etaseneu (pekerjaan handoff)

**Tujuan:** setiap hotspot & poligon lahan terbakar di response API + laporan PDF +
export XLSX menampilkan `fungsi kawasan` (mis. "Hutan Lindung"), `nama kawasan`
(mis. "Air Bangis"), dan `kelompok` (Konservasi/Lindung/Produksi/Non-KH).

**Prinsip:** cukup `LEFT JOIN` ke tabel lookup `hotspot_kawasan_hutan` /
`burned_kawasan_hutan` yang sudah jadi. **Tidak ada** operasi spasial baru di request
path. Tidak menyentuh `LayerService` (yang muat geojson ke RAM).

### 5.1 Hotspot — `app/services/postgres_store/_hotspots.py`

Fungsi `read_hotspot_observations()` (± baris 139) — query utamanya:

```sql
WITH ranked_relation AS (
    SELECT DISTINCT ON (obs.id)
        obs.id AS observation_id, obs.raw_payload,
        p.id AS polygon_metadata_id, p.feature_key, ... (field polygon_metadata) ...
    FROM hotspot_observations obs
    JOIN polygon_metadata p
      ON p.layer_key = obs.layer_key AND p.is_active = TRUE
     AND ST_Covers(p.geometry, obs.geom)
    WHERE obs.detected_at >= %s AND obs.detected_at < %s
      AND obs.source = ANY(%s) AND obs.layer_key = ANY(%s) AND obs.geom IS NOT NULL
    ORDER BY obs.id ASC, p.feature_index ASC, p.id ASC
)
SELECT * FROM ranked_relation ORDER BY observation_id ASC
```

**Perubahan:**
1. Tambah di `SELECT` dalam `ranked_relation`:
   ```sql
   hkh.fungsikws     AS khutan_kode,
   hkh.nama_kawasan  AS khutan_nama,
   hkh.kelompok      AS khutan_kelompok,
   lbl.singkatan     AS khutan_singkatan,
   COALESCE(lbl.fungsi, 'Kode ' || hkh.fungsikws::text) AS khutan_fungsi
   ```
2. Tambah join (setelah `JOIN polygon_metadata p ...`):
   ```sql
   LEFT JOIN hotspot_kawasan_hutan hkh ON hkh.hotspot_id = obs.id
   LEFT JOIN ref_fungsi_kawasan_label lbl ON lbl.kode = hkh.fungsikws
   ```
   `LEFT` — jangan sampai memfilter hotspot yang di luar kawasan.
3. Di loop `for row in rows:` (± baris 205-245), tambahkan ke `polygon_metadata`
   dict (atau lebih bersih: key top-level `payload["kawasan_hutan"]`):
   ```python
   kawasan = {
       "kode": row.get("khutan_kode"),
       "fungsi": row.get("khutan_fungsi"),
       "singkatan": row.get("khutan_singkatan"),
       "nama_kawasan": row.get("khutan_nama"),
       "kelompok": row.get("khutan_kelompok"),
   }
   if any(v not in (None, "") for v in kawasan.values()):
       payload["kawasan_hutan"] = kawasan
   ```

**Read path lain yang mungkin perlu perlakuan sama** (cek pemakaiannya dulu):
- `get_hotspots_in_range()` (± baris 249, pakai `LEFT JOIN LATERAL`) — dipakai
  cluster/early-warning. Tambah `LEFT JOIN hotspot_kawasan_hutan` kalau outputnya
  masuk ke laporan.
- `_relations.py :: intersect_hotspots_for_layer()` — mekanisme
  `hotspot_polygon_relation` lama; **tidak perlu diubah**.

### 5.2 Lahan terbakar — `app/services/postgres_store/_s2_burned_area.py`

- `read_s2_burned_area_for_polygons()` (± baris 181) dan
  `read_s2_burned_area_overlay()` (± baris 219): tambah
  ```sql
  LEFT JOIN LATERAL (
      SELECT jsonb_agg(jsonb_build_object(
               'kode', bkh.fungsikws,
               'fungsi', COALESCE(lbl.fungsi, 'Kode '||bkh.fungsikws::text),
               'kelompok', bkh.kelompok,
               'luas_ha', bkh.luas_ha) ORDER BY bkh.luas_ha DESC) AS rincian,
             (SELECT bkh2.kelompok FROM burned_kawasan_hutan bkh2
                WHERE bkh2.burned_id = s.id ORDER BY bkh2.luas_ha DESC LIMIT 1) AS dominan
      FROM burned_kawasan_hutan bkh
      LEFT JOIN ref_fungsi_kawasan_label lbl ON lbl.kode = bkh.fungsikws
      WHERE bkh.burned_id = s.id
  ) khutan ON TRUE
  ```
  lalu masukkan `khutan.rincian` / `khutan.dominan` ke row output.
- Catatan: `s2_burned_area` di-refresh berkala; `refresh_kawasan_attribution()`
  me-rebuild `burned_kawasan_hutan` penuh tiap run (cron §4), jadi selalu sinkron.

### 5.3 Surface ke laporan

- **Model response:** `app/models/hotspots.py` — tambah field opsional `kawasan_hutan`
  (atau field flat `fungsi_kawasan`, `nama_kawasan`, `kelompok_kawasan`).
- **Helper:** `app/services/polygon_fields.py` — tambah:
  ```python
  def fungsi_kawasan(hotspot: dict) -> str:
      return (hotspot.get("kawasan_hutan") or {}).get("fungsi", "")
  def nama_kawasan_hutan(hotspot: dict) -> str:
      return (hotspot.get("kawasan_hutan") or {}).get("nama_kawasan", "")
  def kelompok_kawasan(hotspot: dict) -> str:
      return (hotspot.get("kawasan_hutan") or {}).get("kelompok", "")
  ```
- **XLSX:** `app/services/export_service.py` — tambah kolom "Fungsi Kawasan Hutan",
  "Nama Kawasan", "Kelompok" di sheet hotspot (dan rekap luas terbakar per kelompok
  di sheet burned area).
- **PDF:** `app/services/pdf_export_service.py` / `agency_pdf_service.py` /
  `point_report_service.py` — tambah baris/kolom "Fungsi Kawasan" di tabel hotspot;
  untuk laporan lahan terbakar tampilkan breakdown luas per fungsi kawasan.
- **API map:** `app/api/hotspots.py :: _to_map_hotspot()` (± baris 78) sengaja ramping
  (tak kirim polygon_metadata utuh). Tambah HANYA 2-3 field ringkas:
  `fungsi_kawasan`, `kelompok` — jangan kirim objek besar.

### 5.4 `_extract_polygon_metadata` (spatial_service.py) — path terpisah

`app/services/spatial_service.py :: _extract_polygon_metadata()` (± baris 110) punya
allowlist field HARDCODE untuk skema Perhutanan Sosial. Ini dipakai jalur enrich
**Python/shapely** (bukan jalur DB `read_hotspot_observations`). Kalau ada laporan yang
lewat jalur ini dan butuh fungsi kawasan, tambahkan `"FUNGSIKWS"`, `"NAMOBJ"` ke
`selected_fields`. Kalau tidak, abaikan — jalur DB (§5.1) sudah cukup.

### 5.5 Test

- `app/tests/test_postgres_store_hotspots.py` — ada
  `test_read_hotspot_observations_enriches_polygon_metadata`. Tambah kasus: hotspot di
  dalam poligon `hotspot_kawasan_hutan` → payload punya `kawasan_hutan` dgn `fungsi`/`kelompok`.
- `app/tests/test_export_service.py`, `test_pdf_export_service.py` — assert kolom baru muncul.
- Fixture: buat baris `hotspot_kawasan_hutan` + `ref_fungsi_kawasan_label` di DB test.

### 5.6 Deploy

Repo di GitHub (`ryandshine/etaseneu`?). Dokploy `git pull` tiap deploy → **edit di
`/etc/dokploy/compose/.../code` ketimpa**. Ubah di repo → commit → push → Dokploy
Redeploy app etaseneu. Container gabungan (nginx frontend + backend); redeploy = build
ulang image, downtime singkat.

---

## 6. Verifikasi label `ref_fungsi_kawasan_label`

Isi awal (kode utama **confident**, sub-kode konservasi **perlu verifikasi**):

| kode | singkatan | fungsi | kelompok | catatan |
|---|---|---|---|---|
| 0 | — | Tidak terkategori / luar kawasan hutan | Non-Kawasan Hutan | verifikasi |
| 100000 | — | Kawasan hutan (tanpa rincian fungsi) | Kawasan Hutan | verifikasi |
| 100100 | KSA-KPA | Kawasan Suaka Alam & Pelestarian Alam | Konservasi | ✅ |
| 100200 | KKP | KSA-KPA Perairan / Kawasan Konservasi Perairan | Konservasi | verifikasi |
| 100201,100210,100211,100220,100221,100230,100240,100241,100250,100251,100260 | — | (kosong) | Konservasi | **sub-kelas KSA-KPA — verifikasi nama** |
| 100300 | HL | Hutan Lindung | Lindung | ✅ |
| 100400 | HPT | Hutan Produksi Terbatas | Produksi | ✅ |
| 100500 | HP | Hutan Produksi Tetap | Produksi | ✅ |
| 100700 | HPK | Hutan Produksi yang dapat Dikonversi | Produksi | ✅ |
| 500100 | — | Tubuh Air | Non-Kawasan Hutan | verifikasi |
| 500300 | APL | Areal Penggunaan Lain | Non-Kawasan Hutan | verifikasi |

Hotspot yang kena sub-kode konservasi: hanya **~92** (100240=81, 100260=5, 100220=3,
100210=2, 100230=1). `kelompok` untuk semua ini tetap benar ("Konservasi") lewat
`fungsi_kawasan_kelompok()`. Yang kurang cuma `fungsi` spesifik (CA/SM/TN/TWA/Tahura/TB).

**Update label:**
```sql
UPDATE ref_fungsi_kawasan_label SET singkatan='TN', fungsi='Taman Nasional', catatan=NULL
 WHERE kode = 100241;   -- dst, isi dari skema KLHK
```
Setelah update, tidak perlu re-run apa pun — Fase 4 join ambil label saat query.

---

## 7. Kenapa dibangun begini (kapasitas server)

- **CPU i7-3770 (2012), 4C/8T; RAM 15 GB; PostGIS dipakai 7 app** (etaseneu, sipekaps,
  kitapantaups, dll — `DATABASE_URL` sama).
- etaseneu `LayerService` memuat **seluruh** geojson via `json.loads(path.read_text())`
  + shapely per fitur. Geojson Kawasan Hutan detail penuh ~1,5-2,5 GB → **OOM**. Karena
  itu: overlay pakai file 101 MB tersimplifikasi; atribusi pakai tabel PostGIS detail
  penuh yang di-load via `ogr2ogr` streaming (tanpa ledakan RAM).
- `ST_Subdivide` + GiST → join point-in-polygon 25.947 titik × 30.883 poligon = **2,7 dtk**
  di hardware ini (tanpa subdivide bisa menit).
- Hasil di-materialkan jadi lookup kecil (`hotspot_kawasan_hutan` 3,8 MB) → biaya per
  request Fase 4 cuma `LEFT JOIN` ber-index, bukan komputasi spasial.
- Refresh inkremental (cron) → hanya hotspot baru yang di-join.

---

## 8. Checklist lanjutan

- [ ] Pasang cron refresh (§4)
- [ ] Fase 4: `_hotspots.py` LEFT JOIN + enrich (§5.1)
- [ ] Fase 4: `_s2_burned_area.py` LEFT JOIN breakdown (§5.2)
- [ ] Fase 4: model + `polygon_fields.py` helper (§5.3)
- [ ] Fase 4: XLSX + PDF kolom baru (§5.3)
- [ ] Fase 4: test (§5.5)
- [ ] Commit + push + Dokploy redeploy etaseneu (§5.6)
- [ ] (opsional) Verifikasi 11 sub-kode konservasi di `ref_fungsi_kawasan_label` (§6)
- [ ] (opsional) Nama & warna layer overlay di `_friendly_layer_name` (§1)
- [ ] (opsional) Tuning `work_mem`/`maintenance_work_mem` compose gealgeolgeo (§2)
