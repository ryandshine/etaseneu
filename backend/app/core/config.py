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
    shp_dir: str = "../shp"
    cache_dir: str = ".cache"
    cache_ttl_hours: int = 24
    request_timeout_seconds: float = 30.0
    scheduler_enabled: bool = True
    scheduler_interval_hours: float = 3.0
    scheduler_fixed_hours: str = "0,3,6,9,12,15,18,21"
    scheduler_timezone: str = "Asia/Jakarta"
    scheduler_new_hotspot_alert_threshold: int = 1

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
