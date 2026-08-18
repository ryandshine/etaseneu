from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


APP_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = APP_DIR.parent
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = "ETA SEUNEU API"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5173"
    nasa_firms_api_key: str = ""
    database_url: str = ""
    # Kosong secara default = tolak semua aksi admin (fail closed), bukan
    # izinkan semua. Endpoint yang butuh ini lihat app/core/auth.py.
    admin_api_key: str = ""
    shp_dir: str = "../shp"
    cache_dir: str = ".cache"
    cache_ttl_hours: int = 24
    request_timeout_seconds: float = 30.0
    scheduler_enabled: bool = True
    scheduler_interval_hours: float = 3.0
    scheduler_fixed_hours: str = "0,3,6,9,12,15,18,21"
    scheduler_timezone: str = "Asia/Jakarta"
    scheduler_new_hotspot_alert_threshold: int = 1
    # Luas kebakaran (burned area) dari MODIS MCD64A1 lewat Google Earth Engine.
    # Kosong = fitur nonaktif (fail closed, sama seperti admin_api_key) --
    # service account punya proyek GCP yang sudah teregistrasi Earth Engine.
    gee_service_account_email: str = ""
    gee_service_account_key_path: str = ""
    gee_project_id: str = ""
    # Auto-refresh burned area. Beda dari scheduler_interval_hours (hotspot,
    # tiap 3 jam) -- produk MCD64A1/VNP64A1 terbit BULANAN, jadi mengecek
    # tiap hari sia-sia. Default mingguan, coba ulang 3 bulan ke belakang
    # tiap kali supaya begitu NASA merilis citra baru sistem otomatis
    # menangkapnya tanpa perlu tahu persis tanggal rilisnya.
    burned_area_scheduler_enabled: bool = True
    burned_area_scheduler_interval_hours: float = 168.0
    burned_area_scheduler_lookback_months: int = 3

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_shp_dir(self) -> Path:
        return (BACKEND_DIR / self.shp_dir).resolve()

    @property
    def resolved_cache_dir(self) -> Path:
        return (BACKEND_DIR / self.cache_dir).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
