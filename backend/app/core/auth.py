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
