"""Layanan lapisan asap: citra satelit NASA GIBS + prakiraan PM2.5 CAMS.

Dua sumber, dua sifat berbeda -- keduanya gratis, tanpa API key:

* **Citra satelit (NASA GIBS, WMTS)** -- pengamatan VIIRS true color. Asap
  terlihat langsung sebagai semburan keabuan/cokelat. Resolusi tinggi (sampai
  ~250 m), tapi hanya harian, tertutup awan, dan tanpa nilai angka.
* **Prakiraan PM2.5 (CAMS Copernicus via Open-Meteo Air Quality)** -- model
  global, per jam sampai 72 jam. Grid kasar (titik sampel 1,5 derajat, +/-165
  km) -- indikatif skala regional, bukan skala kecamatan. Pola pengambilan
  sama dengan `wind_service`/`weather_service`: titik sampel jarang ke
  Open-Meteo dalam batch, hasilnya di-cache di disk oleh lapisan API.

Modul ini murni (tanpa cache/HTTP framework); cache & rute ada di
`app/api/smoke.py`. Semua fungsi jaringan `async` dan gampang di-monkeypatch.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from PIL import Image, ImageChops

from app.services.weather_service import AIR_QUALITY_BASE, build_axis

logger = logging.getLogger("smoke.service")

# ---------------------------------------------------------------------------
# Citra satelit NASA GIBS
# ---------------------------------------------------------------------------
GIBS_WMTS_BASE = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"
TILE_MATRIX_SET = "GoogleMapsCompatible_Level9"
MAX_TILE_ZOOM = 9  # batas Level9 pada TileMatrixSet di atas

# Whitelist eksplisit: endpoint proxy tidak boleh jadi proxy terbuka ke path
# lain di GIBS (atau ke host lain). Ketiganya true color VIIRS harian.
IMAGERY_LAYERS: frozenset[str] = frozenset(
    {
        "VIIRS_SNPP_CorrectedReflectance_TrueColor",
        "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
        "VIIRS_NOAA21_CorrectedReflectance_TrueColor",
    }
)
DEFAULT_IMAGERY_LAYER = "VIIRS_SNPP_CorrectedReflectance_TrueColor"

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_IMAGERY_AGE_DAYS = 30


def build_gibs_tile_url(layer: str, date: str, z: int, x: int, y: int) -> str:
    """URL ubin WMTS GIBS. Urutan path GIBS: {z}/{row=y}/{col=x}."""
    return f"{GIBS_WMTS_BASE}/{layer}/default/{date}/{TILE_MATRIX_SET}/{z}/{y}/{x}.jpg"


async def fetch_imagery_tile(
    layer: str, date: str, z: int, x: int, y: int, timeout_seconds: float = 15.0
) -> bytes | None:
    """Ambil satu ubin JPEG dari GIBS. `None` = GIBS 404 (belum ada citra)."""
    url = build_gibs_tile_url(layer, date, z, x, y)
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


# Piksel "tanpa data" pada citra harian GIBS (area yang belum dilewati satelit
# hari itu, celah antar-lintasan) dikirim sebagai HITAM PEKAT dalam JPEG -- bukan
# transparan. Tanpa penanganan, ubin itu menutupi seluruh peta di bawahnya
# (kasus nyata 2026-09-20 siang: citra hari ini belum merekam Indonesia, jadi
# Indonesia tertutup hitam). Ambang kecil menyisakan sedikit derau kompresi JPEG
# di tepi jalur; laut gelap sungguhan (biru tua) tetap jauh di atas ambang ini.
NODATA_MAX_CHANNEL = 10


def make_nodata_transparent(content: bytes) -> bytes:
    """JPEG GIBS -> PNG dengan alpha 0 di piksel tanpa data.

    Ubin tanpa piksel kosong dikembalikan APA ADANYA (tetap JPEG, tidak
    di-encode ulang). Konten yang tidak bisa di-decode juga dikembalikan apa
    adanya -- lebih baik ubin apa adanya daripada error.
    """
    try:
        rgb = Image.open(io.BytesIO(content)).convert("RGB")
    except Exception:  # noqa: BLE001 -- bukan gambar valid: teruskan saja
        return content

    r, g, b = rgb.split()
    brightest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    alpha = brightest.point(lambda v: 0 if v <= NODATA_MAX_CHANNEL else 255)
    if alpha.getextrema()[0] == 255:
        return content  # semua piksel berisi citra

    rgb.putalpha(alpha)
    out = io.BytesIO()
    rgb.save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Grid prakiraan PM2.5 (CAMS via Open-Meteo)
# ---------------------------------------------------------------------------
# Mencakup Indonesia. Sengaja 1,5 derajat (462 titik) -- CAMS global sendiri
# ~0,4 derajat, jadi resolusi lebih halus tidak menambah informasi tapi
# menambah jatah panggilan Open-Meteo (batas gratis 10.000/hari bersama
# lapisan angin & cuaca).
LAT_START = 7.5
LAT_END = -12.0
LON_START = 94.0
LON_END = 142.0
STEP = 1.5

_lats = build_axis(LAT_START, LAT_END, STEP, descending=True)
_lons = build_axis(LON_START, LON_END, STEP)

NX = len(_lons)
NY = len(_lats)

# Baris-mayor, lintang menurun -- konvensi sama dengan lapisan cuaca & angin.
GRID_POINTS: list[tuple[float, float]] = [(lat, lon) for lat in _lats for lon in _lons]

FORECAST_DAYS = 3
BATCH_SIZE = 100  # titik per panggilan (menjaga panjang URL tetap aman)
WIB = timezone(timedelta(hours=7))
SOURCE_LABEL = "CAMS (Copernicus) via Open-Meteo"


def _to_float(value: Any) -> float:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return 0.0  # None = tak ada data di sel itu; jangan bikin peta bolong


async def fetch_pm25_cube(timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Ambil PM2.5 per jam (72 jam ke depan) untuk seluruh titik grid.

    Mengembalikan `{"times": [...ISO WIB...], "hours": [[NY*NX nilai], ...]}`.
    Dilempar exception kalau ada batch yang gagal -- lapisan API yang memutuskan
    menyajikan cache basi.
    """
    times: list[str] | None = None
    per_point: list[list[float]] = []

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        for start in range(0, len(GRID_POINTS), BATCH_SIZE):
            batch = GRID_POINTS[start : start + BATCH_SIZE]
            response = await client.get(
                AIR_QUALITY_BASE,
                params={
                    "latitude": ",".join(str(lat) for lat, _ in batch),
                    "longitude": ",".join(str(lon) for _, lon in batch),
                    "hourly": "pm2_5",
                    "forecast_days": FORECAST_DAYS,
                    "timezone": "Asia/Jakarta",
                    "domains": "cams_global",
                },
            )
            response.raise_for_status()
            payload = response.json()
            items: list[dict[str, Any]] = payload if isinstance(payload, list) else [payload]
            if len(items) != len(batch):
                raise ValueError("Bentuk data PM2.5 dari Open-Meteo tidak sesuai jumlah titik.")
            for item in items:
                hourly = item["hourly"]
                if times is None:
                    times = list(hourly["time"])
                per_point.append([_to_float(v) for v in hourly["pm2_5"]])

    if not times:
        raise ValueError("Open-Meteo tidak mengembalikan deret waktu PM2.5.")

    # transposisi: titik x jam -> jam x titik
    hours = [[series[h] for series in per_point] for h in range(len(times))]
    return {"times": times, "hours": hours}


def _now_wib() -> datetime:
    return datetime.now(WIB).replace(tzinfo=None)


def slice_pm25(cube: dict[str, Any], offset_hours: int = 0, now: datetime | None = None) -> dict[str, Any]:
    """Ambil satu irisan waktu dari kubus: jam WIB sekarang + `offset_hours`.

    Indeks dijepit ke jam terakhir yang tersedia (bukan IndexError).
    """
    now = now or _now_wib()
    times: list[str] = cube["times"]
    hours: list[list[float]] = cube["hours"]
    floor = now.replace(minute=0, second=0, microsecond=0)

    idx_now = 0
    for i, stamp in enumerate(times):
        if datetime.fromisoformat(stamp) <= floor:
            idx_now = i
        else:
            break
    idx = max(0, min(idx_now + offset_hours, len(hours) - 1))

    return {
        "header": {
            "parameterName": "pm2_5",
            "unit": "µg/m³",
            "lo1": LON_START,
            "la1": LAT_START,
            "lo2": _lons[-1],
            "la2": _lats[-1],
            "dx": STEP,
            "dy": STEP,
            "nx": NX,
            "ny": NY,
            "valid_time": times[idx],
            "offset_hours": idx - idx_now,
            "source": SOURCE_LABEL,
        },
        "data": hours[idx],
    }
