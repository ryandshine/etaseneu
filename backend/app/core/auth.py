import hmac

from fastapi import Header, HTTPException

from app.core.config import get_settings


def verify_admin_key(x_admin_key: str | None) -> None:
    """Validasi X-Admin-Key, lempar HTTPException kalau tidak sah.

    Dipisah dari dependency di bawah supaya endpoint yang proteksinya
    bersyarat (lihat /layers: mode preview publik, mode penuh admin-only)
    bisa memanggilnya di tengah handler tanpa menduplikasi logika ini.

    Fail closed: kalau ADMIN_API_KEY belum diisi di server, SEMUA request
    ditolak -- bukan diloloskan. Sebelumnya endpoint-endpoint ini publik
    tanpa proteksi apa pun; jangan ulangi kesalahan yang sama lewat default
    yang permisif.
    """
    settings = get_settings()
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="Admin API belum dikonfigurasi di server.")

    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Admin key tidak valid.")


async def require_admin_key(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> None:
    """Dependency buat endpoint admin (upload geojson, trigger sync, dst)."""
    verify_admin_key(x_admin_key)


def verify_login_password(username: str | None, password: str | None) -> None:
    """Validasi login gerbang aplikasi, lempar HTTPException kalau tidak sah.

    Terpisah dari verify_admin_key: ini gerbang MASUK aplikasi (satu user
    bersama, "admin"), bukan aksi admin per-endpoint. Username tidak
    menambah keamanan (cuma satu user), sekadar konsisten dengan bentuk
    form login biasa -- kontrol sebenarnya ada di password.

    Fail closed: APP_LOGIN_PASSWORD kosong -> semua percobaan login
    ditolak, sama seperti verify_admin_key.
    """
    settings = get_settings()
    if not settings.app_login_password:
        raise HTTPException(status_code=503, detail="Login belum dikonfigurasi di server.")

    if (username or "").strip().lower() != "admin":
        raise HTTPException(status_code=401, detail="Username atau password salah.")

    if not password or not hmac.compare_digest(password, settings.app_login_password):
        raise HTTPException(status_code=401, detail="Username atau password salah.")
