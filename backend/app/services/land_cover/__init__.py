"""Sub-modul pendukung analisis tutupan lahan (`land_cover_service.py`).

Dipisah per sumber data supaya `land_cover_service.py` tidak tumbuh jadi
God Object: `sar.py` (Sentinel-1 GRD), berikutnya `labels.py` (konsensus
label latih) dan `temporal.py` (aturan transisi antar-tahun). Semua fungsi
menerima modul `ee` sebagai argumen -- `import ee` di level modul memaksa
inisialisasi kredensial saat test/impor, padahal membaca hasil tidak butuh GEE.
"""
