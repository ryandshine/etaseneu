# Hotspot ↔ Poligon: kontrak data, akar masalah, dan rencana penerapan

Dokumen ini hasil audit end-to-end alur hotspot ETA SENEU (21 Okt 2026). Isinya: peta alur data,
laporan akar masalah (terbukti vs belum terverifikasi), kontrak data, perubahan kode, validasi
sebelum/sesudah, rencana migrasi & deployment, dan risiko yang tersisa.

> **Status**: kode sudah diubah di branch `fix/hotspot-polygon-matching` dan diuji. **Belum ada
> perubahan yang diterapkan ke database produksi.** Seluruh angka "sesudah" berasal dari salinan
> produksi di kontainer PostGIS lokal terpisah (lihat bagian 6).

## 1. Ringkasan

- Tabel `hotspot_polygon_relation` hanya memuat **5,19%** pasangan hotspot↔poligon yang benar
  (4.854 dari 93.537 pasangan spasial). Penyebabnya **bug di kode ingest**, bukan perbedaan aturan
  spasial.
- Tabel `polygon_hotspot_summary` hanya akurat untuk 696 dari 2.757 poligon-tahun; 996 poligon
  yang punya hotspot tidak punya baris sama sekali. Rumus ringkasannya benar; yang salah adalah
  **kapan ia dibangun ulang** (turunan dari bug yang sama).
- Pengguna melihat angka salah di fitur yang membaca tabel relasi, mis. statistik "KPS terdampak
  hotspot 30 hari": **46** padahal referensi spasial **1.603**.
- Perbaikan: satu mesin pencocokan spasial di database (`ST_Covers` atas geometri valid, tanpa
  syarat `layer_key`), dipakai oleh ingest, rekonsiliasi, dan ringkasan; error tidak lagi ditelan;
  ada endpoint integritas/rekonsiliasi (aman secara bawaan); tes regresi dan validasi.

## 2. Peta alur data

```
NASA FIRMS (CSV, 4 sensor)
   │  nasa_client.fetch_rows  → hotspot_normalizer.normalize_hotspots
   ▼
HotspotService._read_or_warm_layer_year_archive      (arsip tahunan hotspot_history_archives, cache file)
   │  spatial_service.filter_hotspots_by_layers      ← Shapely STRtree, geojson layer di memori
   │      • di dalam poligon  → layer_id = layer pemuat TITIK ITU (poligon pertama menang), is_perimeter=False
   │      • ≤ 5 km di luar    → layer_id = "perimeter_threat", is_perimeter=True   (sejak 4 Sep 2026)
   ▼
HotspotService.fetch_filtered_hotspots               (dipanggil scheduler tiap 3 jam DAN permintaan API)
   │  _persist_observations_and_relations            [BARU: error dicatat, status ke scheduler]
   │     ├─ postgres_store.upsert_hotspot_observations      → hotspot_observations (unique: source,satelit,lat,lon,waktu,layer_key)
   │     └─ postgres_store.sync_hotspot_relations_and_summaries   [BARU: pencocokan spasial di DB]
   │            ├─ reconcile_hotspot_polygon_relations  → hotspot_polygon_relation   (ST_Covers, idempoten)
   │            └─ rebuild_polygon_hotspot_summary      → polygon_hotspot_summary    (poligon×tahun WIB, atomik)
   │  _hydrate_polygon_metadata → read_hotspot_observations (JOIN spasial ke poligon aktif)
   ▼
API /api/hotspots ──► peta, statistik, matriks, ekspor (frontend memakai daftar titik ini)

Jalur lain yang menyentuh relasi/ringkasan
   geojson_sync_service.sync_all ─► intersect_hotspots_for_layer(layer)  ─► reconcile (seluruh rentang) + ringkasan layer
   POST /api/polygon-hotspot-summary/refresh ─► refresh_polygon_hotspot_summaries (penuh)
   GET  /api/hotspot-relations/integrity      [BARU, baca-saja]
   POST /api/hotspot-relations/reconcile      [BARU, dry_run=true bawaan]

Konsumen tabel relasi (angkanya ikut berubah setelah relasi lengkap)
   kps_catalog_service  (kps_hotspot_30d, filter has_hotspot_30d, hotspot_count_30d per KPS)
   telegram_bot_service (hotspot_count_today)
   run_gee_august_analysis.py (pemilihan KPS target)
Konsumen yang SUDAH spasial langsung (tidak terpengaruh bug relasi)
   early_warning_service, notification_service, fire_spread_service, hotspot_cluster_service, peta
```

Lokasi kode yang memengaruhi hitungan hotspot:

| Lokasi | Peran |
|---|---|
| `services/spatial_service.py::filter_hotspots_by_layers` | memberi label `layer_id`/`perimeter_threat` saat ingest (Shapely, `covers`, poligon pertama menang) |
| `services/hotspot_service.py` (`fetch_filtered_hotspots`, `_persist_*`) | ingest + penyimpanan |
| `services/postgres_store/_hotspot_match.py` **(baru)** | mesin pencocokan tunggal, rekonsiliasi, laporan integritas |
| `services/postgres_store/_relations.py` | ringkasan tahunan, refresh penuh, `intersect_hotspots_for_layer` |
| `services/postgres_store/_hotspots.py` | upsert observasi; jalur baca peta/klaster |
| `services/scheduler.py` | siklus sinkron, status keberhasilan, metrik Prometheus |
| `services/geojson_sync_service.py` | memicu rekonsiliasi sesudah sinkron layer |
| `api/cache.py` | endpoint refresh/integritas/rekonsiliasi (admin) |
| `services/kps_catalog_service.py`, `telegram_bot_service.py` | konsumen relasi |
| `services/early_warning_service.py`, `notification_service.py`, `fire_spread_service.py` | konsumen spasial langsung |

## 3. Laporan akar masalah

### Terbukti (bukti dapat ditelusuri)

**A. Bug cache pencarian poligon di jalur ingest** — `HotspotService._persist_filtered_hotspots`
(kode lama). `polygon_index_lookup_cache[layer_key]` diisi dengan
`read_polygon_metadata_ids_by_index(feature_indices=[int(feature_index)])`, yaitu **hanya indeks
milik hotspot pertama** di layer itu, lalu dipakai ulang untuk semua hotspot berikutnya (jalur
fallback `feature_key` punya cacat yang sama). Hanya hotspot yang satu poligon dengan hotspot
pertama di layernya yang mendapat relasi.
*Bukti*: replay kode asli atas 2.108 payload hotspot nyata (10–11 Okt) menghasilkan **51** baris
relasi; 48 di antaranya persis hotspot ber-`feature_index` sama dengan hotspot pertama (411 untuk
KPS, 120 untuk Hutan Adat), sisanya via jalur `feature_key`. Sampel memuat 332 poligon berbeda.
Replika tanpa cache meloloskan 2.108/2.108. Tes lama hanya memakai SATU hotspot, sehingga bug ini
tidak mungkin tertangkap.

**B. Ringkasan basi karena dibangun ulang hanya untuk "poligon terdampak"** — setelah A,
`rebuild_polygon_hotspot_summary` dipanggil hanya untuk poligon milik hotspot yang lolos A
(1–3 poligon per hari). Refresh penuh tidak pernah dijadwalkan; hanya jalan manual (1 Sep 2026).
*Bukti*: 1.691 dari 1.761 baris ringkasan terakhir diperbarui 1 Sep, sisanya 1–3 baris/hari.
Per poligon-tahun: 696 sama dengan referensi, 1.065 kurang (selisih 42.646 titik), 996 poligon
(19.157 titik) tanpa baris. **Rumus ringkasan sendiri benar** (696 persis sama).

**C. Kegagalan ditelan diam-diam** — `except Exception: pass` pada upsert observasi, upsert relasi,
pembangunan ringkasan, `refresh_geojson`, dan dua endpoint di `cache.py`; plus **bug
`layer.name`** (`hotspot_service.py:110`, `layer` adalah `dict`): satu error jaringan sesaat dari
FIRMS mengubah handler-nya sendiri menjadi `AttributeError` dan menggagalkan **seluruh siklus
sinkron** (log produksi 19 Okt 2026 20:01: `SCHEDULER: Sync gagal — 'dict' object has no attribute 'name'`).

**D. Konsumen hilir membaca tabel relasi yang tidak lengkap** — `kps_catalog_service`,
`telegram_bot_service`, `run_gee_august_analysis`. Dampak terukur: "KPS terdampak 30 hari" 46 vs
1.603 (referensi spasial).

**E. Lonjakan hotspot September = perubahan cakupan ingest, bukan kenaikan kejadian** —
observasi berlabel `perimeter_threat` **0** sebelum 4 Sep 2026 dan 307.765 sesudahnya (zona
penyangga ≤ 5 km). Hotspot di dalam poligon hanya naik ±2× (19.472 pada Agu → 38.487 pada Sep).
Tren bulanan total tidak sebanding sebelum/sesudah 4 Sep.

### Terbukti tetapi dampak numeriknya nihil pada data saat ini

**F. Tiga aturan "di dalam" dan kopling `layer_key`** — `ST_Covers` (peta, ringkasan), `ST_Contains`
(relasi massal, Peringatan Dini, laporan, notifikasi), `ST_Intersects` (cek titik, rambatan);
ringkasan memakai `obs.layer_key = p.layer_key`. Pada data saat ini ketiga predikat menghasilkan
**93.537 pasangan yang sama** (tidak ada titik tepat di batas), `ST_MakeValid` tidak mengubah
hasil `ST_Contains`, dan syarat `layer_key` hanya membedakan **5 dari 93.415** titik (4 berlabel
`perimeter_threat` di dalam poligon Hutan Adat, 1 berlabel KPS di dalam Hutan Adat). Dugaan awal
bahwa perbedaan ini penyebab selisih angka **tidak didukung data**; standardisasi dilakukan untuk
mencegah regresi, bukan karena menjelaskan selisih.

**G. Tumpang tindih poligon bukan penyebab fanout** — di basis valid hanya 122 dari 93.415 titik
(0,13%) berada di >1 poligon aktif (maks 2). Fanout besar (12.726 hotspot multi-poligon) yang
terlihat di audit awal berasal dari baris yatim dan poligon nonaktif.

### Belum terverifikasi

**H. Asal 26.006 baris relasi yatim (14.364 id hotspot)** — tidak ada kode aplikasi yang menghapus
`hotspot_observations` atau `hotspot_polygon_relation` (pindai `backend/`, `docs/`; tidak ada FK ke
observasi). Fakta yang ada: semua baris yatim ber-`matched_at` ≤ 21 Agu 2026 (puncak 14.785 relasi
pada 21 Agu, hari layer disinkron ulang); id yatim berada dalam rentang id observasi yang ada.
Hipotesis (belum diuji): observasi lama dihapus/dibangun ulang di luar repo. Pemeriksaan yang
belum dilakukan: log/riwayat DBA, cadangan, `hotspot_history_archives`.
*Catatan*: sequence `hotspot_observations_id_seq` = 11.006.409 untuk 401.211 baris. Itu **tidak**
membuktikan penghapusan, karena `INSERT … ON CONFLICT DO UPDATE` menghabiskan nilai sequence pada
setiap upsert (dugaan penjelasan celah id; juga belum diuji).

## 4. Kontrak data

1. **Observasi hotspot**: satu deteksi satelit, kunci keunikan
   `(source, satellite, latitude, longitude, detected_at, COALESCE(layer_key,''))`. `layer_key`
   observasi adalah **label saat ingest** (layer yang memuat titik waktu itu, atau
   `perimeter_threat`); **bukan fakta spasial** dan bukan syarat pencocokan. Deteksi satelit ≠
   kebakaran terverifikasi.
2. **Relasi hotspot–poligon**: satu baris per pasangan `(observasi, poligon aktif)` dengan
   `ST_Covers(analysis_geometry, obs.geom)` — titik tepat di batas **ikut masuk**.
   `analysis_geometry` = geometri sumber bila valid, kalau tidak
   `ST_CollectionExtract(ST_MakeValid(geometry), 3)`; geometri sumber **tidak pernah diubah**.
   `match_method = 'covers'` (baris lama `'contains'` diselaraskan sekali saat rekonsiliasi).
3. **Titik di >1 poligon**: dicatat pada **semua** poligon yang memuatnya (tidak ada "poligon
   pertama menang"). Hitungan **per poligon** menghitung titik itu di tiap poligon; hitungan
   **regional** menghitungnya sekali. **Jangan menjumlahkan hitungan per poligon lalu menyebutnya
   total hotspot** (selisih terukur: 93.537 pasangan vs 93.415 titik unik).
4. **Ringkasan** (`polygon_hotspot_summary`): grain = satu poligon aktif per **tahun menurut
   Asia/Jakarta**. `hotspot_count` = observasi unik di dalam poligon pada tahun itu;
   `start_at`/`end_at`/`last_hotspot_at`/`sources`/`satellites` dihitung dari himpunan yang sama.
   `sources`/`satellites` adalah **daftar nilai berbeda terurut**, bukan jumlah per sumber.
   Dihitung langsung dari geometri poligon saat ini (bukan dari tabel relasi); relasi dan ringkasan
   direkonsiliasi satu sama lain oleh laporan integritas.
5. **KPS vs Hutan Adat** dibedakan lewat `polygon_metadata.layer_key` (`psagustus2026`,
   `HUTAN_ADAT_APR26`); satu titik bisa berada di keduanya (1 titik pada data saat ini).
6. **Perlakuan khusus**: observasi tanpa `geom` diabaikan; poligon tidak aktif tidak pernah
   dicocokkan (relasi lama ke poligon nonaktif dipertahankan sebagai riwayat, konsumen menyaring
   `is_active`); observasi duplikat dicegah oleh indeks unik; relasi yatim **dilaporkan, tidak
   dihapus otomatis**.
7. **Jalur baca peta** (`read_hotspot_observations`, `get_hotspots_in_range`): satu baris per
   observasi (bila tumpang tindih: poligon ber-`feature_index` terkecil, lalu `id`), filter layer
   berdasarkan layer **poligon**, dan `layer_id` payload diselaraskan dengan poligon pemuat.

## 5. Perubahan kode

| File | Perubahan dan alasan |
|---|---|
| `postgres_store/_hotspot_match.py` (baru) | Mesin pencocokan tunggal: CTE poligon aktif + geometri valid (di-MATERIALIZED, sekali per poligon), tahap kandidat bbox untuk jendela waktu (rencana kueri hanya memvalidasi/probe poligon yang relevan), `reconcile_hotspot_polygon_relations` (idempoten, per-31-hari, `dry_run`, `HotspotRelationSyncError` membawa progres), `sync_hotspot_relations_and_summaries` (relasi lalu ringkasan; ringkasan tidak disentuh bila relasi gagal), `hotspot_relation_integrity_report` (baca-saja), `prune_orphan_relations` (`dry_run=True` bawaan, tanpa endpoint penghapus). |
| `postgres_store/_relations.py` | `rebuild_polygon_hotspot_summary` ditulis ulang: tanpa kopling `layer_key`, geometri valid, tahun WIB eksplisit, DELETE+INSERT atomik dengan advisory lock; `refresh_polygon_hotspot_summaries` = relasi lengkap lalu ringkasan penuh (nilai balikan tetap `int` untuk response model); `intersect_hotspots_for_layer` memakai mesin yang sama. |
| `postgres_store/_hotspots.py` | Jalur baca peta/klaster: buang `p.layer_key = obs.layer_key`, saring layer lewat poligon, selaraskan label payload, tambah prefilter `&&`. |
| `hotspot_service.py` | Buang pencocokan di memori + cache bermasalah; `_persist_observations_and_relations` mencatat error dengan konteks dan mengembalikan status; perbaiki `layer.name`; hasil `fetch_filtered_hotspots` membawa `persistence: {ok: bool, ...}` (tanpa teks error — respons API ke klien); `refresh_geojson` mencatat kegagalan. |
| `scheduler.py` | Siklus ditandai **gagal** bila persistensi gagal → metrik Prometheus yang sudah ada (`etaseneu_scheduler_last_sync_success`, `…_consecutive_failures`) ikut menangkapnya. |
| `api/cache.py` | `GET /api/hotspot-relations/integrity`, `POST /api/hotspot-relations/reconcile` (`dry_run=true` bawaan), kegagalan refresh dicatat, bukan `pass`. |
| `geojson_sync_service.py` | Kegagalan rekonsiliasi dicatat dengan traceback. |
| `early_warning_service.py`, `notification_service.py` | `ST_Contains` → `ST_Covers` (satu aturan "di dalam"; selisih numerik nol). |
| `validate_hotspot_relations.py` (baru) | Validasi baca-saja relasi/ringkasan vs referensi spasial; hanya memakai `VALIDATE_DATABASE_URL`. |
| `sql/migrations/2026-10-21_hotspot_relation_integrity.sql` (baru) | Rencana cadangan, arsip yatim, FK. **Tidak dieksekusi.** |
| Tes | `test_hotspot_matching_integration.py` (21 tes PostGIS nyata), `test_hotspot_matching_unit.py` (13), tiga tes lama ditulis ulang. |

Tidak diubah (disengaja): `daily_report_service.py` masih `ST_Contains` pada satu join karena file itu
memuat perubahan Anda yang belum di-commit; ganti manual ke `ST_Covers` bila diinginkan. Frontend
tidak berubah (konsumsi hitungan lewat daftar titik `/api/hotspots`).

## 6. Validasi sebelum/sesudah

Dijalankan pada **salinan baca-saja produksi** di kontainer `postgis/postgis:16-3.4` terpisah
(`prodcopy`): 401.211 observasi, 16.612 poligon, 32.245 relasi, 1.761 ringkasan — identik dengan
produksi. "Sebelum" = keadaan salinan apa adanya; "sesudah" = setelah kode baru menjalankan refresh
penuh pada salinan. Skrip: `backend/validate_hotspot_relations.py`.

| Metrik (Jan–Okt 2026) | Sebelum | Sesudah |
|---|---:|---:|
| Observasi | 401.211 | 401.211 |
| Titik unik di dalam poligon aktif (referensi spasial) | 93.415 | 93.415 |
| — di dalam KPS / di dalam Hutan Adat / di keduanya | 92.800 / 616 / 1 | 92.800 / 616 / 1 |
| Titik di >1 poligon aktif (maks) | 122 (2) | 122 (2) |
| Pasangan titik–poligon | 93.537 | 93.537 |
| Relasi valid (observasi ada, poligon aktif) | 4.854 baris / 4.853 titik | **93.537 baris / 93.415 titik** |
| Kelengkapan relasi terhadap referensi | 5,19% | **100%** |
| Relasi yatim (baris / id) | 26.006 / 14.364 | 26.006 / 14.364 *(sengaja tidak disentuh)* |
| Relasi ke poligon nonaktif | 1.385 | 1.385 *(riwayat)* |
| Relasi usang (di poligon aktif tapi tidak lagi di dalam) | 0 | 0 |
| Ringkasan = referensi (poligon-tahun) | 696 dari 2.757 | **2.757 dari 2.757** |
| Poligon punya hotspot tanpa baris ringkasan | 996 (19.157 titik) | 0 |
| Ringkasan kurang dari referensi | 1.065 (selisih 42.646) | 0 |
| Konsumen: "KPS terdampak 30 hari" via relasi | 46 | **1.603** (referensi 1.603) |

Poligon terkena hotspot 2026: 2.757. Jumlah per poligon per tahun ada di `polygon_hotspot_summary`
(tabel hasil, 2.757 baris); jumlah itu **tidak boleh dijumlahkan menjadi total regional** (93.537 vs
93.415).

**Oracle independen**: Shapely (`covers`, `make_valid`) atas 306 poligon — seluruh 58 poligon
invalid + 250 poligon acak — terhadap semua observasi: 7.326 pasangan, **306/306 poligon cocok
persis** dengan relasi hasil kode baru, tanpa selisih di kedua arah.

**Waktu & rencana eksekusi** (salinan, mesin pengembangan):

| Operasi | Sebelum optimasi kandidat | Sesudah |
|---|---:|---:|
| Kueri pasangan, jendela scheduler 3 hari | 1.818 ms (8.598 poligon diprobe) | **651 ms** (794 poligon) |
| Kueri pasangan, 31 hari | 2.030 ms | 1.625 ms |
| Sinkron relasi+ringkasan jendela 3 hari | — | 2,1 s |
| Sinkron relasi+ringkasan Oktober penuh | — | 8,9 s |
| Refresh penuh (idempoten, 0 perubahan) | 41,5 s | **19,2 s** |
| Refresh penuh pertama (87.754 relasi baru + 4.295 diselaraskan) | 43,9 s | — |

Rencana (`EXPLAIN ANALYZE`): `Nested Loop` dari CTE poligon aktif ke `hotspot_observations_geom_idx`
(GiST); kandidat poligon dari `hotspot_observations_detected_at_idx` + `polygon_metadata_geometry_idx`.

Hitungan buffer 0–5 km (fitur Siaga Rambatan Api): observasi berlabel `perimeter_threat` = 307.765
(label saat ingest; belum diverifikasi ulang secara spasial — lihat bagian 8).

## 7. Tes

Backend: `cd backend && .venv/bin/python -m pytest app/tests -q`. Tes integrasi PostGIS dilewati
kecuali `ETASENEU_TEST_DATABASE_URL` diisi (nama database harus mengandung `test`, tidak boleh sama
dengan `DATABASE_URL`, skema sementara per modul):

```
docker run -d --rm --name es-test-pg -e POSTGRES_PASSWORD=... -e POSTGRES_DB=es_test \
  -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql/data postgis/postgis:16-3.4
ETASENEU_TEST_DATABASE_URL=postgresql://postgres:...@127.0.0.1:55432/es_test \
  .venv/bin/python -m pytest app/tests/test_hotspot_matching_integration.py
```

Cakupan: titik di dalam/di batas/di luar/di simpul, poligon invalid (geometri sumber tak berubah),
dua poligon tumpang tindih (titik unik regional vs per poligon), label `layer_key` berbeda,
observasi tanpa geometri, upsert observasi dan rekonsiliasi berulang (idempoten), dry-run,
poligon nonaktif, kegagalan sebagian + retry (chunk selesai tersimpan, ringkasan tidak disentuh),
ringkasan penuh vs inkremental, semantik ringkasan, observasi terhapus (yatim dilaporkan, ringkasan
mengecualikan), pasangan hilang/usang, pergantian tahun WIB, regresi bug cache satu-indeks
(15 hotspot di 3 poligon), kegagalan persistensi tidak ditelan, jalur baca peta.

## 8. Rencana migrasi dan deployment

**Urutan (semua langkah tulis butuh persetujuan Anda; tidak ada yang dijalankan audit ini):**

1. Review dan gabung branch; **redeploy manual** (Dokploy). Kode aman sebelum migrasi apa pun
   (FK bersifat opsional); rekonsiliasi tidak berjalan otomatis untuk data lama.
2. *Baca-saja*: `GET /api/hotspot-relations/integrity` → catat `missing_pairs` (≈ 88,7 rb),
   `stale_pairs` (0 saat audit), `orphan_*`.
3. *Baca-saja*: `POST /api/hotspot-relations/reconcile?start_at=2026-01-01T00:00:00%2B07:00&end_at=2026-11-01T00:00:00%2B07:00`
   (`dry_run=true` bawaan) → bandingkan `missing_pairs` dengan langkah 2.
4. **Cadangan** relasi + ringkasan (migrasi bagian 1). Estimasi dampak: tabel kecil (32 rb + 1,7 rb baris).
5. **Rekonsiliasi nyata** (menulis): `POST /api/polygon-hotspot-summary/refresh` (admin) —
   estimasi pada salinan: ~45 detik, +87,7 rb relasi, 4,3 rb diselaraskan, 2.757 ringkasan. Lakukan di
   luar jam sibuk; tambahan beban DB sedang (satu transaksi per 31 hari).
6. Verifikasi: jalankan lagi langkah 2 → `missing_pairs = 0`, `stale_pairs = 0`; jalankan
   `validate_hotspot_relations.py` dengan `VALIDATE_DATABASE_URL` produksi (baca-saja).
7. **Pengumuman ke pengguna**: angka "KPS terdampak" di katalog KPS dan bot Telegram akan naik
   tajam (46 → ±1.600) — itu koreksi, bukan lonjakan kejadian.
8. *Keputusan pemilik data* (migrasi bagian 2–4): arsipkan lalu hapus 26.006 relasi yatim, lalu
   FK ke observasi (`ON DELETE CASCADE`, `NOT VALID` lalu `VALIDATE`).

**Observabilitas**: log `HOTSPOT RELATION:` (INFO ringkasan rekonsiliasi, ERROR+traceback saat gagal),
`HOTSPOT PERSIST:`, `HOTSPOT SUMMARY:`; siklus scheduler yang gagal menyimpan ditandai `success=false`
(+ `persistence_ok=false` di `last_sync_result`) dan tertangkap alert Prometheus yang sudah ada
(`docs/monitoring/scheduler-alerting.md`); cek berkala `GET /api/hotspot-relations/integrity`
(harapan: `missing_pairs = 0`, `stale_pairs = 0`).

**Kriteria rollback**: error `HOTSPOT RELATION`/`HOTSPOT PERSIST` berulang setelah deploy; durasi
sinkron scheduler > 30 detik secara konsisten; `lock_timeout`/`statement_timeout` sering terjadi;
`stale_pairs` > 0 tanpa perubahan layer. Rollback kode = redeploy image sebelumnya (data aman:
operasi hanya menambah/menyelaraskan). Rollback data = pulihkan dari tabel cadangan (migrasi bagian 1).

## 9. Risiko tersisa

- **Asal 26.006 relasi yatim belum diketahui** (bagian 3H). Perbaikan ini tidak mencegah
  penyebabnya bila itu operasi manual di luar repo; FK (migrasi bagian 4) yang menutup celahnya.
- **Jalur baca peta memakai geometri sumber** (bukan `analysis_geometry`) karena validasi per baris
  per permintaan terlalu mahal. Pada data saat ini hasilnya identik; `stale_pairs`/`missing_pairs` di laporan
  integritas akan memperlihatkan bila menyimpang. Solusi tuntas: kolom `analysis_geometry` tersimpan
  (migrasi bagian 5), belum dikerjakan.
- **`daily_report_service.py`** masih `ST_Contains` pada satu join dan menyaring titik memakai
  label `perimeter_threat`/`is_perimeter` dari payload (label waktu-ingest) — nol selisih sekarang,
  tetapi belum seragam.
- **Hitungan buffer 0–5 km belum diverifikasi spasial** (hanya hitungan label). Kueri jarak geografi
  pada poligon berpuluh ribu titik terlalu berat untuk dijalankan di sini; perlu pendekatan lain
  (mis. bbox + jarak planar terkalibrasi) bila angka ini dibutuhkan laporan.
- **Beban tambahan tiap permintaan yang melewati cache**: rekonsiliasi jendela kecil ±0,7–2 detik
  di jalur ingest. Terukur di salinan, belum di produksi.
- **Konkurensi**: scheduler dan permintaan pengguna bisa merekonsiliasi jendela yang sama
  bersamaan; relasi aman (`ON CONFLICT`), ringkasan diserialkan advisory lock (`lock_timeout` 30 detik).
- **Frontend tidak diaudit sampai tingkat komponen**: hitungan di UI berasal dari daftar titik
  `/api/hotspots`; konsistensinya dengan kartu statistik tidak diuji otomatis di sini.
- Data yang dibutuhkan untuk menutup risiko: log/riwayat database sebelum 21 Agu 2026,
  kebijakan retensi observasi, dan konfirmasi apakah relasi lama (nonaktif) dibutuhkan untuk audit.
