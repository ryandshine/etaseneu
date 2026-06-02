# ETA SEUNEU MVP Design

## Ringkasan

ETA SEUNEU v1 adalah aplikasi pemantauan hotspot berbasis web yang berjalan lokal di `localhost`, dengan arsitektur yang tetap rapi untuk dipindahkan ke lingkungan publik pada tahap berikutnya. Sistem membaca seluruh file GeoJSON dari folder `shp/`, menampilkan semua boundary di peta, lalu hanya menghitung hotspot NASA FIRMS untuk layer yang sedang aktif dicentang pengguna.

Versi ini sengaja tidak memakai database. Semua kebutuhan penyimpanan sementara ditangani dengan cache berbasis file di backend agar integrasi NASA, filtering spasial, statistik, dan ekspor Excel bisa selesai cepat dan tetap konsisten.

## Tujuan V1

- Menjalankan aplikasi end-to-end di `localhost`
- Membaca file GeoJSON lokal secara dinamis dari folder `shp/`
- Menampilkan boundary wilayah di peta interaktif
- Mengambil data hotspot NASA FIRMS menggunakan API key server-side
- Memfilter hotspot berdasarkan tanggal, satelit, dan layer aktif
- Menghitung statistik ringkas dari hasil filter yang sama
- Mengekspor hasil yang sama ke file Excel

## Di Luar Scope V1

- Database relasional atau Redis
- Autentikasi pengguna
- Sinkronisasi background terjadwal yang kompleks
- Multi-tenant atau hak akses per wilayah
- Worker queue atau pemrosesan batch terpisah
- Deployment produksi penuh

## Arsitektur

Sistem dibagi menjadi dua aplikasi:

- `backend/`: FastAPI untuk konfigurasi, pembacaan layer GeoJSON, integrasi NASA FIRMS, cache file-based, filtering point-in-polygon, agregasi statistik, dan ekspor Excel
- `frontend/`: React + Vite untuk peta, filter, statistik, dan interaksi pengguna

Frontend tidak pernah berbicara langsung ke NASA. Semua akses data hotspot melewati backend agar:

- API key NASA tetap aman di server
- filtering spasial dilakukan di satu tempat
- hasil peta, statistik, dan ekspor memakai sumber data yang identik

## Struktur Folder yang Direncanakan

```text
etaseneu/
  backend/
    app/
      api/
      core/
      models/
      services/
      tests/
    requirements.txt
  frontend/
    src/
      components/
      features/
      hooks/
      lib/
      types/
    package.json
  shp/
  docs/
    superpowers/
      specs/
      plans/
```

## Konfigurasi

Backend akan membaca konfigurasi dari `.env`:

- `NASA_FIRMS_API_KEY`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `FRONTEND_ORIGIN`
- `CACHE_DIR`

Frontend akan membaca:

- `VITE_API_BASE_URL`

Default pengembangan diarahkan ke `localhost`. Struktur konfigurasi tetap dibuat cukup rapi agar mudah diubah saat dipindahkan ke server publik.

## Perilaku Layer GeoJSON

- Backend memindai folder `shp/` saat startup
- Semua file `.geojson` yang valid dimuat sebagai layer
- Semua layer tampil default di peta
- Layer memiliki warna berbeda untuk membantu identifikasi visual
- Statistik, hotspot terfilter, dan ekspor Excel hanya memakai layer yang sedang aktif dicentang
- Jika tidak ada layer aktif, hasil hotspot dan statistik kosong

Nama layer default diambil dari nama file GeoJSON.

## Perilaku Data Hotspot

Default filter:

- Tanggal mulai: `1 Januari` tahun berjalan
- Tanggal akhir: `hari ini`
- Satelit aktif: `MODIS`, `VIIRS S-NPP`, dan `VIIRS NOAA-20`

NOAA-21 tidak diwajibkan aktif di v1. Desain kode akan dibuat agar penambahan sensor baru tetap mudah.

Untuk setiap request hotspot:

1. Backend menerima filter tanggal, satelit, dan daftar layer aktif
2. Backend memastikan data sumber tersedia dari cache atau NASA FIRMS
3. Backend melakukan normalisasi data lintas sensor
4. Backend menjalankan filtering point-in-polygon terhadap union layer aktif
5. Backend mengembalikan:
   - koleksi hotspot untuk peta
   - metadata minimum untuk popup
   - ringkasan yang bisa dipakai endpoint statistik atau dibangun dari hasil yang sama

## Strategi Cache

Cache berbasis file lokal digunakan untuk menghindari pemanggilan NASA berulang.

Prinsip cache:

- disimpan per sensor dan rentang tanggal
- format file mudah dibaca ulang oleh backend
- cache historis boleh bertahan lebih lama
- data hari ini boleh disegarkan lebih agresif

Implementasi v1 cukup memakai direktori cache lokal, misalnya di bawah `backend/.cache/` atau path dari `.env`.

Tujuan cache v1 adalah kestabilan operasional lokal, bukan throughput tinggi.

## Kontrak API

### `GET /api/health`

Mengembalikan status layanan backend.

### `GET /api/layers`

Mengembalikan:

- daftar layer yang ditemukan
- id layer
- nama layer
- warna layer
- status aktif default
- bounds
- GeoJSON fitur untuk digambar di peta

### `GET /api/hotspots`

Parameter:

- `start_date`
- `end_date`
- `satellites`
- `active_layers`

Mengembalikan hotspot yang sudah:

- dinormalisasi
- difilter secara spasial
- siap ditampilkan sebagai marker atau circle di peta

### `GET /api/stats`

Parameter sama dengan `/api/hotspots`.

Mengembalikan statistik ringkas seperti:

- total hotspot
- breakdown per satelit
- breakdown per layer aktif
- indikator intensitas sederhana berbasis brightness atau confidence jika tersedia

### `GET /api/export.xlsx`

Parameter sama dengan `/api/hotspots`.

Menghasilkan file Excel yang sinkron dengan filter aktif di layar.

Kolom minimum:

- nomor urut
- nama layer atau wilayah
- satelit atau sensor
- waktu deteksi
- latitude
- longitude
- confidence
- brightness

### `POST /api/cache/refresh`

Endpoint utilitas untuk localhost atau admin sederhana.

Fungsinya memaksa backend memperbarui cache untuk kombinasi filter tertentu tanpa menunggu request hotspot reguler.

## UI/UX V1

UI dibuat operasional, ringan, dan jelas dibaca di desktop maupun mobile.

### Tata letak

- satu halaman
- peta sebagai area utama
- panel kontrol melayang pada desktop
- panel berubah menjadi drawer atau collapse pada layar kecil

### Elemen utama

- date range picker
- toggle satelit
- daftar layer GeoJSON dengan checkbox
- statistik ringkas
- tombol refresh data
- tombol ekspor Excel

### Interaksi peta

- aplikasi melakukan auto-fit ke boundary seluruh layer saat pertama dibuka
- setiap hotspot menampilkan popup detail singkat
- boundary layer tampil semi-transparan
- warna boundary dibuat kontras terhadap hotspot

### Prinsip desain

- minimal tetapi tidak membingungkan
- tetap memakai label teks seperlunya
- fokus pada peta dan keputusan lapangan

## Error Handling

Backend harus menangani kondisi ini dengan respons yang jelas:

- API key NASA tidak tersedia
- file GeoJSON rusak atau tidak valid
- folder `shp/` kosong
- NASA API gagal diakses
- request filter tidak valid

Frontend harus menampilkan state yang mudah dimengerti untuk:

- loading
- empty result
- error backend
- layer tidak tersedia

## Strategi Pengujian

### Backend

- test loader GeoJSON
- test spatial filter point-in-polygon
- test normalisasi data NASA
- test endpoint `health`
- test endpoint `layers`
- test endpoint `hotspots`
- test generator Excel

### Frontend

- test utilitas filter dan formatter
- test render panel filter utama
- test alur perubahan filter yang memicu fetch ulang

### Verifikasi manual localhost

- backend hidup dan membaca `.env`
- frontend bisa memuat daftar layer
- semua boundary tampil di peta
- centang layer mengubah hasil hotspot dan statistik
- ubah tanggal mengubah data
- ubah satelit mengubah data
- ekspor Excel menghasilkan file sesuai filter aktif

## Keputusan Teknis Penting

- tanpa database pada v1
- semua logika spasial berada di backend
- semua data NASA diakses server-side
- hasil peta, statistik, dan ekspor harus berasal dari kombinasi filter dan dataset yang sama
- target jalan pertama adalah `localhost`, tetapi struktur config tetap siap dipindahkan ke server publik

## Risiko dan Mitigasi

### Variasi format respons NASA

Mitigasi:

- buat lapisan normalisasi data yang terisolasi
- tulis test untuk sample payload yang berbeda

### Performa filtering spasial saat data banyak

Mitigasi:

- mulai dari Shapely dengan struktur kode yang mudah dioptimalkan
- satukan layer aktif untuk mengurangi pemeriksaan berulang jika perlu

### Ketidaksinkronan antara peta, statistik, dan ekspor

Mitigasi:

- gunakan kontrak filter yang sama di semua endpoint
- pusatkan logika query/filter pada service backend yang sama

## Kriteria Selesai V1

V1 dianggap selesai bila:

- aplikasi backend dan frontend dapat dijalankan lokal
- layer GeoJSON dari folder `shp/` muncul di peta
- hotspot NASA dapat dimuat dengan API key dari `.env`
- filter tanggal, satelit, dan layer aktif bekerja
- statistik mengikuti filter yang sama
- file Excel dapat diunduh dan isinya sesuai filter aktif
- alur dasar telah diuji secara manual di `localhost`
