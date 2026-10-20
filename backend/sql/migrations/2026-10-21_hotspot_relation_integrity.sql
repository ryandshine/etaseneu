-- Migrasi integritas relasi hotspot <-> observasi  (2026-10-21)
--
-- STATUS: RENCANA. TIDAK PERNAH dijalankan otomatis oleh aplikasi dan TIDAK dijalankan oleh sesi
-- audit. Jalankan manual, bertahap, SETELAH kode baru ter-deploy dan relasi direkonsiliasi
-- (lihat docs/hotspot-polygon-contract.md, bagian "Rencana deployment"). Tidak ada staging --
-- database ini produksi (bahaya #1 di CLAUDE.md), jadi setiap langkah punya cadangan + rollback.
--
-- Latar belakang: hotspot_polygon_relation.hotspot_observation_id TIDAK punya foreign key ke
-- hotspot_observations(id). Akibatnya 26.006 baris (14.364 id hotspot) menunjuk observasi yang
-- sudah tidak ada. Asal hilangnya observasi itu BELUM terbukti (tidak ada kode aplikasi yang
-- menghapusnya; semua baris yatim ber-matched_at <= 21 Agu 2026), karena itu baris yatim
-- diarsipkan dulu, bukan langsung dihapus.

-- ---------------------------------------------------------------------------------------------
-- 0. PRASYARAT (baca-saja) -- hentikan bila tidak sesuai harapan
-- ---------------------------------------------------------------------------------------------
-- GET /api/hotspot-relations/integrity (admin) harus menunjukkan:
--   orphan_polygon_rows = 0, missing_pairs = 0 (setelah rekonsiliasi), stale_pairs = 0.
-- Hitung ulang yatim persis sebelum bertindak (angka bisa berubah):
SELECT COUNT(*) AS orphan_rows, COUNT(DISTINCT r.hotspot_observation_id) AS orphan_ids
FROM hotspot_polygon_relation r
WHERE NOT EXISTS (SELECT 1 FROM hotspot_observations h WHERE h.id = r.hotspot_observation_id);

-- ---------------------------------------------------------------------------------------------
-- 1. CADANGAN (sebelum rekonsiliasi PERTAMA di produksi)  -- rollback langkah rekonsiliasi
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hotspot_polygon_relation_backup_20261021 AS
    SELECT * FROM hotspot_polygon_relation;
CREATE TABLE IF NOT EXISTS polygon_hotspot_summary_backup_20261021 AS
    SELECT * FROM polygon_hotspot_summary;
-- Verifikasi: jumlah baris cadangan = jumlah baris asli (32.245 dan 1.761 saat audit).

-- ROLLBACK rekonsiliasi (mengembalikan keadaan sebelum rekonsiliasi; satu transaksi):
--   BEGIN;
--   TRUNCATE hotspot_polygon_relation;
--   INSERT INTO hotspot_polygon_relation SELECT * FROM hotspot_polygon_relation_backup_20261021;
--   TRUNCATE polygon_hotspot_summary;
--   INSERT INTO polygon_hotspot_summary SELECT * FROM polygon_hotspot_summary_backup_20261021;
--   SELECT setval('hotspot_polygon_relation_id_seq', (SELECT MAX(id) FROM hotspot_polygon_relation));
--   SELECT setval('polygon_hotspot_summary_id_seq', (SELECT MAX(id) FROM polygon_hotspot_summary));
--   COMMIT;

-- ---------------------------------------------------------------------------------------------
-- 2. ARSIPKAN relasi yatim (tidak menghapus apa pun)
-- ---------------------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hotspot_polygon_relation_orphan_archive (
    id                     BIGINT PRIMARY KEY,
    hotspot_observation_id BIGINT NOT NULL,
    polygon_metadata_id    BIGINT NOT NULL,
    layer_key              TEXT,
    match_method           TEXT,
    matched_at             TIMESTAMPTZ,
    created_at             TIMESTAMPTZ,
    archived_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO hotspot_polygon_relation_orphan_archive
    (id, hotspot_observation_id, polygon_metadata_id, layer_key, match_method, matched_at, created_at)
SELECT r.id, r.hotspot_observation_id, r.polygon_metadata_id, r.layer_key, r.match_method, r.matched_at, r.created_at
FROM hotspot_polygon_relation r
WHERE NOT EXISTS (SELECT 1 FROM hotspot_observations h WHERE h.id = r.hotspot_observation_id)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------------------------
-- 3. KEPUTUSAN PEMILIK DATA (belum diambil): hapus yatim dari tabel utama?
-- ---------------------------------------------------------------------------------------------
-- Yatim tidak mempengaruhi angka aplikasi (semua konsumen meng-JOIN ke observasi), tetapi
-- menghalangi FK pada langkah 4. Hapus HANYA bila arsip di atas sudah terverifikasi dan tidak
-- ada kebutuhan audit historis atas 26.006 baris itu:
--   DELETE FROM hotspot_polygon_relation r
--   WHERE NOT EXISTS (SELECT 1 FROM hotspot_observations h WHERE h.id = r.hotspot_observation_id);
-- ROLLBACK: INSERT kembali dari hotspot_polygon_relation_orphan_archive (kolom id..created_at).

-- ---------------------------------------------------------------------------------------------
-- 4. FOREIGN KEY ke observasi (hanya setelah langkah 3 dilakukan)
-- ---------------------------------------------------------------------------------------------
-- ON DELETE CASCADE: bila observasi dihapus (retensi/pembersihan), relasinya ikut hilang -- tidak
-- ada lagi yatim. Tidak ada kode aplikasi yang menghapus observasi, jadi tidak mengubah perilaku
-- yang ada. NOT VALID + VALIDATE terpisah supaya penambahan constraint tidak mengunci tabel lama.
ALTER TABLE hotspot_polygon_relation
    ADD CONSTRAINT hotspot_polygon_relation_observation_fk
    FOREIGN KEY (hotspot_observation_id) REFERENCES hotspot_observations (id)
    ON DELETE CASCADE
    NOT VALID;

ALTER TABLE hotspot_polygon_relation
    VALIDATE CONSTRAINT hotspot_polygon_relation_observation_fk;

-- ROLLBACK:
--   ALTER TABLE hotspot_polygon_relation DROP CONSTRAINT hotspot_polygon_relation_observation_fk;

-- ---------------------------------------------------------------------------------------------
-- 5. (OPSIONAL, fase berikutnya) normalisasi geometri analisis tersimpan
-- ---------------------------------------------------------------------------------------------
-- Jalur BACA peta (read_hotspot_observations / get_hotspots_in_range) memakai geometri sumber
-- apa adanya karena ST_MakeValid per baris per permintaan terlalu mahal; pada data saat ini
-- hasilnya identik (93.537 pasangan di kedua cara). Bila nanti perlu menutup celah itu, simpan
-- geometri valid sekali saat sinkron layer:
--   ALTER TABLE polygon_metadata ADD COLUMN analysis_geometry geometry(MultiPolygon, 4326);
--   CREATE INDEX polygon_metadata_analysis_geometry_idx ON polygon_metadata USING gist (analysis_geometry);
--   UPDATE polygon_metadata SET analysis_geometry =
--       ST_Multi(ST_CollectionExtract(ST_MakeValid(geometry), 3)) WHERE geometry IS NOT NULL;
-- lalu isi kolom itu di geojson_sync_service. Tidak termasuk perubahan ini.
