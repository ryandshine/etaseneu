# Standar Metodologi & Formula Monitoring Hotspot Areal Perhutanan Sosial (KPS)

Dokumen ini adalah acuan resmi sistem monitoring, *early warning*, dan pembuatan laporan/paparan PPTX untuk seluruh wilayah kerja Balai Perhutanan Sosial (BPS).

---

## 1. Formula Skor Prioritas Monitoring

$$\text{Skor Prioritas} = (\text{Jumlah Hotspot HIGH} \times 2) + (\text{Jumlah Hotspot MEDIUM} \times 1)$$

* **Label Wajib**: *"Indikator Prioritas Monitoring – Analisis Internal"*
* **Catatan Status**: BUKAN indeks resmi Kementerian Kehutanan dan BUKAN klasifikasi tingkat keparahan kebakaran, melainkan alat bantu operasional untuk menentukan urutan prioritas verifikasi lapangan (ground check).

### Stratifikasi Prioritas:
* 🔴 **Prioritas Tinggi**:
  * **Kriteria**: Skor Prioritas $\ge 15$ ATAU memiliki $\ge 2$ Hotspot HIGH.
  * **Tindakan**: Verifikasi lapangan / *ground check* wajib dalam 1x24 jam, koordinasi KPH dan MPA.
* 🟠 **Prioritas Sedang**:
  * **Kriteria**: Skor Prioritas $6 - 14$ (terutama KPS dengan deteksi berulang multi-bulan).
  * **Tindakan**: Komunikasi intensif pendamping PS & pengurus KPS, pemantauan citra harian, patroli berkala.
* 🟢 **Prioritas Rendah**:
  * **Kriteria**: Skor Prioritas $1 - 5$ (kejadian tunggal/terisolasi).
  * **Tindakan**: Pemantauan rutin melalui dasbor ETA SENEU dan edukasi pencegahan karhutla.

---

## 2. Prinsip Dasar Kedinasan

* **HOTSPOT BUKAN KEBAKARAN TERKONFIRMASI**.
* Gunakan istilah baku: **"Hotspot terdeteksi"** atau **"Indikasi hotspot"**.
* Hotspot adalah anomali termal berbasis deteksi satelit penginderaan jauh yang memerlukan validasi lapangan untuk memastikan kejadian kebakaran riil.

---

## 3. Filter Keyakinan (Confidence Level)

* 🔴 **HIGH**: Fokus utama analisis dan target prioritas verifikasi lapangan tingkat pertama.
* 🟠 **MEDIUM**: Indikator pendukung untuk melihat sebaran spasial dan potensi wilayah rawan.
* ⚪ **LOW**: **DIEKSKLUSI** dari analisis utama.

### Ambang Batas Satelit:
* **VIIRS (NOAA-20, NOAA-21, Suomi-NPP)**: `h` = HIGH, `n` = MEDIUM, `l` = LOW.
* **MODIS (Terra, Aqua)**: `> 80` = HIGH, `30 - 80` = MEDIUM, `< 30` = LOW.

---

## 4. Analisis Spasial & Buffer Perimeter

* **Di Dalam KPS (*In-Polygon*)**: Kueri PostGIS `ST_Covers(pm.geometry, ho.geom)`.
* **Dekat Batas KPS**: Radius `0 - 1 km` luar poligon KPS (zona kritis ancaman perambatan api).
* **Buffer Sekitar KPS**: Radius `1 - 3 km` dan `3 - 5 km` luar poligon KPS (faktor risiko perimetral).
* *Penting*: Jangan mencampuradukkan hotspot di buffer sekitar KPS sebagai hotspot di dalam KPS.

---

## 5. Kejadian Berulang (*Temporal Persistence*)

* KPS dengan deteksi $\ge 5$ hari berbeda di beberapa bulan dikategorikan sebagai **KPS Rawan Kronis**.
* Menunjukkan indikasi tekanan aktivitas antropogenik berkala atau titik bara gambut persisten.

---

## 6. Generator Skrip & Template PPTX

Skrip otomatisasi yang telah teruji untuk menghasilkan paparan lengkap (16 slide, 16:9 widescreen):
* Ekstraksi data: `backend/extract_bps_medan_data.py`
* Pembuatan visual peta GIS & chart: `backend/generate_bps_medan_visuals.py`
* Penyusunan deck PPTX: `backend/build_bps_medan_monitoring_deck.py`
