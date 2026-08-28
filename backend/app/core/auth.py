import hmac
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException

from app.core.config import get_settings
from app.core.session_store import get_auth_store


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
                claims = decode_token(token)
                if _is_active_admin_session(token, claims):
                    return
            except HTTPException:
                pass
    verify_admin_key(x_admin_key)


# ---------------------------------------------------------------------------
# Akun aplikasi (gerbang login seluruh sistem) -- lihat postgres_store/_users.py
# untuk tabelnya. Password di-hash dengan bcrypt; sesi dibawa lewat token JWT
# bertanda tangan HS256 (auth_jwt_secret) dan, untuk token login aplikasi,
# dicatat sebagai hash di app_sessions supaya bisa diperpanjang/revoke.
# ---------------------------------------------------------------------------

TOKEN_TTL = timedelta(days=30)


def hash_session_token(token: str) -> str:
    """Hash a bearer token before it is persisted in PostgreSQL."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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
    wilker_bps: str | None = None
    expires_at: datetime | None = None
    session_id: str | None = None


def issue_token(
    *,
    user_id: int,
    username: str,
    role: str,
    wilker_bps: str | None = None,
    persist_session: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    session_id = secrets.token_urlsafe(24)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "wilker_bps": wilker_bps,
        "jti": session_id,
        "iat": now,
        "exp": now + TOKEN_TTL,
    }
    if persist_session:
        payload["sid"] = session_id
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
            wilker_bps=str(payload["wilker_bps"]) if payload.get("wilker_bps") else None,
            expires_at=datetime.fromtimestamp(float(payload["exp"]), tz=timezone.utc),
            session_id=str(payload["sid"]) if payload.get("sid") else None,
        )
    except (KeyError, ValueError, TypeError, OverflowError):
        raise HTTPException(status_code=401, detail="Sesi tidak valid, silakan login ulang.")


def _is_active_admin_session(token: str, claims: TokenClaims) -> bool:
    """Validate persisted admin sessions while preserving legacy JWT support."""

    if not claims.session_id:
        return claims.role == "admin"

    store = get_auth_store()
    validator = getattr(store, "validate_session", None)
    if not store.enabled or validator is None:
        return claims.role == "admin"
    session_user = validator(hash_session_token(token), claims.user_id)
    if not session_user:
        return False
    if isinstance(session_user, dict):
        return session_user.get("role") == "admin"
    return claims.role == "admin"


def _authenticate_bearer_token(authorization: str | None, store) -> TokenClaims:
    """Validate a bearer token against the injected session store."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Belum login.")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Belum login.")
    claims = decode_token(token)
    validator = getattr(store, "validate_session", None)
    if claims.session_id and store.enabled and validator is not None:
        session_user = validator(hash_session_token(token), claims.user_id)
        if not session_user:
            raise HTTPException(status_code=401, detail="Sesi sudah dicabut, silakan login lagi.")
        if isinstance(session_user, dict):
            claims.username = str(session_user.get("username", claims.username))
            claims.role = str(session_user.get("role", claims.role))
            claims.wilker_bps = session_user.get("wilker_bps") or claims.wilker_bps
    return claims


async def require_authenticated_user(
    authorization: str | None = Header(default=None),
    store = Depends(get_auth_store),
) -> TokenClaims:
    """Dependency: butuh header 'Authorization: Bearer <token>' yang valid."""
    return _authenticate_bearer_token(authorization, store)


async def require_session_if_enabled(
    authorization: str | None = Header(default=None),
    store = Depends(get_auth_store),
) -> TokenClaims | None:
    """Gate baca opsional untuk endpoint publik-baca.

    - `Settings.api_require_auth` False (default) -> no-op, endpoint tetap
      publik (perilaku lama). Dipakai supaya deploy tidak langsung mengunci
      situs; flag dinyalakan manual di produksi setelah frontend terbukti
      mengirim token.
    - True -> wajib `Authorization: Bearer <jwt>` valid (401 kalau tidak ada /
      invalid / kadaluarsa).

    JANGAN pasang ini menumpuk `require_admin_key` -- automation yang cuma
    pakai `X-Admin-Key` (tanpa sesi JWT) akan putus.
    """
    if not get_settings().api_require_auth:
        return None
    return _authenticate_bearer_token(authorization, store)


async def get_current_user_claims(
    authorization: str | None = Header(default=None),
    store = Depends(get_auth_store),
) -> TokenClaims | None:
    """Ekstrak sesi user secara non-blocking jika ada token valid.
    
    Digunakan untuk scoping data per wilayah kerja (role bps) tanpa memblokir
    endpoint publik jika api_require_auth belum aktif.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        claims = decode_token(token)
        validator = getattr(store, "validate_session", None)
        if claims.session_id and store.enabled and validator is not None:
            session_user = validator(hash_session_token(token), claims.user_id)
            if session_user and isinstance(session_user, dict):
                claims.username = str(session_user.get("username", claims.username))
                claims.role = str(session_user.get("role", claims.role))
                claims.wilker_bps = session_user.get("wilker_bps") or claims.wilker_bps
        return claims
    except Exception:
        return None


async def require_admin_role(
    claims: TokenClaims = Depends(require_authenticated_user),
) -> TokenClaims:
    """Dependency: butuh token valid DAN role admin -- untuk endpoint
    Manajemen User (lihat api/auth.py)."""
    if claims.role != "admin":
        raise HTTPException(status_code=403, detail="Aksi ini khusus admin.")
    return claims
