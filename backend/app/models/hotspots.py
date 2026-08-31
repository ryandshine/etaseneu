from pydantic import BaseModel


class KawasanHutan(BaseModel):
    """Atribusi fungsi kawasan hutan KLHK (KWSHUTAN_AR_250K) untuk satu titik.

    Diisi lewat lookup `hotspot_kawasan_hutan` (join spasial pra-komputasi),
    bukan operasi spasial di jalur request. Kosong kalau titik di luar semua
    kawasan hutan.
    """

    kode: int | None = None
    fungsi: str | None = None
    singkatan: str | None = None
    nama_kawasan: str | None = None
    kelompok: str | None = None


class HotspotRecord(BaseModel):
    source: str
    satellite: str
    latitude: float
    longitude: float
    brightness: float | None = None
    frp: float | None = None
    confidence: str | None = None
    daynight: str | None = None
    detected_at: str
    kawasan_hutan: KawasanHutan | None = None
