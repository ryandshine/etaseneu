import logging
import secrets
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
    # Password gerbang login seluruh aplikasi (bukan aksi admin -- itu tetap
    # admin_api_key terpisah). Kosong = tolak semua percobaan login (fail
    # closed), sama seperti admin_api_key. Sejak tabel app_users ada, nilai
    # ini cuma dipakai SEKALI sebagai password akun admin awal (seed) --
    # setelahnya password sungguhan tersimpan (hash) di database, dikelola
    # lewat menu Manajemen User.
    app_login_password: str = ""
    # Kunci penandatanganan token sesi (JWT). BEDA sifat dari admin_api_key/
    # app_login_password: kalau kosong, TIDAK fail-closed -- auto-generate
    # random tiap proses start (lihat get_settings()). Konsekuensinya cuma
    # "token jadi tidak valid tiap restart server, semua orang login ulang",
    # bukan "situs terkunci total". Production sebaiknya tetap set nilai
    # tetap supaya sesi tidak hilang tiap deploy, tapi lupa mengisinya tidak
    # akan mengulang insiden lockout APP_LOGIN_PASSWORD.
    auth_jwt_secret: str = ""
    # Secret key widget Cloudflare Turnstile di halaman login. Sama sifat
    # dengan auth_jwt_secret: kalau KOSONG, verifikasi captcha dilewati total
    # (fail-open) -- halaman login jalan seperti biasa tanpa widget. Diisi =
    # login wajib mengirim turnstile_token yang lolos verifikasi ke server
    # Cloudflare (lihat services/turnstile_service.py). Site key (publik)
    # dipasang terpisah di frontend lewat VITE_TURNSTILE_SITE_KEY.
    turnstile_secret_key: str = ""
    # Kalau True, SEMUA endpoint baca API butuh header Authorization: Bearer
    # <jwt> yang sah (lihat core/auth.require_session_if_enabled). Default
    # False = perilaku lama (endpoint baca publik) supaya deploy tidak
    # langsung mengunci situs; dinyalakan manual di Dokploy setelah frontend
    # terverifikasi mengirim token. Router admin TIDAK terpengaruh ini
    # (tetap require_admin_key). Selalu publik: /api/health, /api/auth/*,
    # /api/metrics.
    api_require_auth: bool = False
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
    # Analisis tutupan lahan: ikutkan fitur Sentinel-1 SAR (VV/VH/rasio) ke
    # Random Forest. false = optik S2 saja (rollback cepat tanpa ubah kode).
    land_cover_use_sar: bool = True
    # Konsensus label latih DW x ESA WorldCover 2021 (lihat
    # services/land_cover/labels.py). false = DW + Hansen saja.
    land_cover_use_consensus_labels: bool = True
    # Auto-refresh burned area lewat Google Earth Engine (MODIS/VIIRS).
    # Default MATI sejak sumber data dipindah ke rekap resmi KLHK (Areal
    # Kebakaran Hutan dan Lahan, klasifikasi akurasi H/M/L) -- lihat
    # burned_area_service.py untuk histori kenapa GEE dipakai sebelumnya.
    # Kode & endpoint manual (/api/burned-area/refresh) tetap ada, cuma tidak
    # lagi dipanggil otomatis. Set true secara eksplisit di env kalau nanti
    # GEE mau dipakai lagi sebagai pelengkap.
    burned_area_scheduler_enabled: bool = False
    burned_area_scheduler_interval_hours: float = 168.0
    burned_area_scheduler_lookback_months: int = 3
    # Direktori tempat admin men-SFTP file resmi KLHK (Areal Kebakaran Hutan
    # dan Lahan) sebelum memicu /api/burned-area/refresh-klhk -- sama pola
    # dengan SHP_DIR, bukan upload lewat HTTP (filenya bisa ratusan MB).
    klhk_burned_area_dir: str = "../burned_area_klhk"

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def resolved_shp_dir(self) -> Path:
        return (BACKEND_DIR / self.shp_dir).resolve()

    @property
    def resolved_klhk_burned_area_dir(self) -> Path:
        return (BACKEND_DIR / self.klhk_burned_area_dir).resolve()

    @property
    def resolved_cache_dir(self) -> Path:
        return (BACKEND_DIR / self.cache_dir).resolve()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.auth_jwt_secret:
        # Sengaja tidak fail-closed -- lihat komentar di field-nya.
        logging.getLogger("hotspot.config").warning(
            "AUTH_JWT_SECRET kosong -- secret di-generate acak tiap start proses; "
            "semua sesi login jadi invalid tiap restart. Set nilai tetap di produksi."
        )
        settings.auth_jwt_secret = secrets.token_urlsafe(48)
    return settings
