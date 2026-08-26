import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException

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


async def require_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    authorization: str | None = Header(default=None),
) -> None:
    """Dependency buat endpoint admin (upload geojson, trigger sync, dst).

    Menerima SALAH SATU dari dua jalur otorisasi:
    - `X-Admin-Key` yang cocok dengan `ADMIN_API_KEY` (jalur lama -- masih
      dipakai user role "user" yang diberi key manual, atau automation tanpa
      sesi login).
    - Sesi JWT valid dengan `role == "admin"` (`Authorization: Bearer <token>`)
      -- supaya akun admin yang sudah login tidak perlu memasukkan password
      admin KEDUA kalinya lewat PasswordGateModal untuk membuka Pengaturan.

    Token JWT yang invalid/kadaluarsa di sini TIDAK melempar 401 langsung --
    dianggap "coba jalur berikutnya" (X-Admin-Key), supaya endpoint ini tetap
    fail-closed lewat `verify_admin_key` seperti sebelumnya kalau kedua jalur
    gagal, bukan lewat exception dari decode_token yang beda pesan.
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token:
            try:
                if decode_token(token).role == "admin":
                    return
            except HTTPException:
                pass
    verify_admin_key(x_admin_key)


# ---------------------------------------------------------------------------
# Akun aplikasi (gerbang login seluruh sistem) -- lihat postgres_store/_users.py
# untuk tabelnya. Password di-hash dengan bcrypt; sesi dibawa lewat token JWT
# bertanda tangan HS256 (auth_jwt_secret), BUKAN cookie/session server-side --
# konsisten dengan pola "state login di memori klien saja" yang sudah dipakai
# sejak LoginPage.tsx pertama dibuat.
# ---------------------------------------------------------------------------

TOKEN_TTL = timedelta(hours=24)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Hash rusak/format tidak dikenal -- perlakukan sebagai tidak cocok,
        # bukan error 500.
        return False


@dataclass
class TokenClaims:
    user_id: int
    username: str
    role: str


def issue_token(*, user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    return jwt.encode(payload, get_settings().auth_jwt_secret, algorithm="HS256")


def decode_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, get_settings().auth_jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesi sudah kadaluarsa, silakan login ulang.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Sesi tidak valid, silakan login ulang.")

    try:
        return TokenClaims(
            user_id=int(payload["sub"]),
            username=str(payload["username"]),
            role=str(payload["role"]),
        )
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Sesi tidak valid, silakan login ulang.")


async def require_authenticated_user(
    authorization: str | None = Header(default=None),
) -> TokenClaims:
    """Dependency: butuh header 'Authorization: Bearer <token>' yang valid."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Belum login.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Belum login.")
    return decode_token(token)


async def require_session_if_enabled(
    authorization: str | None = Header(default=None),
) -> TokenClaims | None:
    """Gate baca opsional untuk endpoint publik-baca.

    - `Settings.api_require_auth` False (default) -> no-op, endpoint tetap
      publik (perilaku lama). Dipakai supaya deploy tidak langsung mengunci
      situs; flag dinyalakan manual di produksi setelah frontend terbukti
      mengirim token.
    - True -> wajib `Authorization: Bearer <jwt>` valid (delegasi ke
      `require_authenticated_user`, 401 kalau tidak ada / invalid / kadaluarsa).

    JANGAN pasang ini menumpuk `require_admin_key` -- automation yang cuma
    pakai `X-Admin-Key` (tanpa sesi JWT) akan putus.
    """
    if not get_settings().api_require_auth:
        return None
    return await require_authenticated_user(authorization)


async def require_admin_role(
    claims: TokenClaims = Depends(require_authenticated_user),
) -> TokenClaims:
    """Dependency: butuh token valid DAN role admin -- untuk endpoint
    Manajemen User (lihat api/auth.py)."""
    if claims.role != "admin":
        raise HTTPException(status_code=403, detail="Aksi ini khusus admin.")
    return claims
