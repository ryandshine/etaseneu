from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import (
    TOKEN_TTL,
    TokenClaims,
    hash_password,
    hash_session_token,
    issue_token,
    require_admin_key,
    require_admin_role,
    require_authenticated_user,
    verify_password,
)
from app.core.config import get_settings
from app.core.session_store import get_auth_store
from app.services.postgres_store import PostgresStore
from app.services.turnstile_service import verify_turnstile


router = APIRouter()

VALID_ROLES = ("admin", "user")


# Alias dependency bersama: require_authenticated_user memakai objek dependency
# yang sama, sehingga override test dan store sesi produksi tetap konsisten.
get_store = get_auth_store


@router.post("/auth/verify")
async def verify_admin_key_endpoint(_: None = Depends(require_admin_key)) -> dict[str, bool]:
    # Kalau dependency di atas tidak melempar exception, key-nya valid.
    return {"ok": True}


class LoginRequest(BaseModel):
    username: str
    password: str
    # Token dari widget Cloudflare Turnstile di halaman login. Wajib &
    # diverifikasi HANYA kalau TURNSTILE_SECRET_KEY terisi di server; kalau
    # tidak, field ini diabaikan (fail-open, lihat config.py).
    turnstile_token: str | None = None


@router.post("/auth/login")
async def login(
    payload: LoginRequest,
    request: Request,
    store: PostgresStore = Depends(get_store),
) -> dict[str, object]:
    """Login gerbang aplikasi -- lihat postgres_store/_users.py.

    Kalau tabel app_users masih kosong (baru migrasi dari APP_LOGIN_PASSWORD),
    seed satu akun admin dari env itu dulu, supaya kredensial yang sudah
    dipakai produksi tetap jalan tanpa langkah manual di server.
    """
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database belum dikonfigurasi di server.")

    settings = get_settings()

    # Cek captcha sebelum menyentuh kredensial -- percobaan brute-force
    # ditolak lebih awal, dan pesan errornya tidak membocorkan apakah
    # username/password-nya benar.
    if settings.turnstile_secret_key:
        remote_ip = request.client.host if request.client else None
        if not payload.turnstile_token or not await verify_turnstile(
            payload.turnstile_token,
            secret=settings.turnstile_secret_key,
            remote_ip=remote_ip,
        ):
            raise HTTPException(
                status_code=400, detail="Verifikasi captcha gagal, coba lagi."
            )

    if settings.app_login_password:
        store.ensure_seed_admin(
            username="admin",
            password_hash=hash_password(settings.app_login_password),
        )

    user = store.get_user_by_username(payload.username.strip().lower())
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Username atau password salah.")

    token = issue_token(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
        persist_session=True,
    )
    create_session = getattr(store, "create_session", None)
    if create_session is not None:
        now = datetime.now(timezone.utc)
        create_session(
            user_id=user["id"],
            token_hash=hash_session_token(token),
            created_at=now,
            expires_at=now + TOKEN_TTL,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    return {
        "ok": True,
        "token": token,
        "username": user["username"],
        "role": user["role"],
        "expires_at": (datetime.now(timezone.utc) + TOKEN_TTL).isoformat(),
    }


@router.get("/auth/session")
async def get_current_session(
    claims: TokenClaims = Depends(require_authenticated_user),
) -> dict[str, object]:
    return {
        "ok": True,
        "username": claims.username,
        "role": claims.role,
        "expires_at": claims.expires_at.isoformat() if claims.expires_at else None,
    }


@router.post("/auth/logout")
async def logout(
    request: Request,
    claims: TokenClaims = Depends(require_authenticated_user),
    store: PostgresStore = Depends(get_store),
) -> dict[str, bool]:
    authorization = request.headers.get("authorization", "")
    token = authorization.split(" ", 1)[1].strip() if authorization.lower().startswith("bearer ") else ""
    revoke_session = getattr(store, "revoke_session", None)
    if token and revoke_session is not None:
        revoke_session(hash_session_token(token), claims.user_id)
    return {"ok": True}


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    created_at: str
    active_sessions: int = 0


def _serialize_user(row: dict) -> UserOut:
    return UserOut(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        created_at=str(row["created_at"]),
        active_sessions=int(row.get("active_sessions", 0)),
    )


@router.get("/auth/users")
async def list_users(
    store: PostgresStore = Depends(get_store), _: TokenClaims = Depends(require_admin_role)
) -> list[UserOut]:
    rows = store.list_users()
    count_sessions = getattr(store, "count_active_sessions", None)
    if count_sessions is not None:
        for row in rows:
            row["active_sessions"] = count_sessions(row["id"])
    return [_serialize_user(row) for row in rows]


@router.post("/auth/users/{user_id}/sessions/revoke")
async def revoke_user_sessions(
    user_id: int,
    request: Request,
    claims: TokenClaims = Depends(require_admin_role),
    store: PostgresStore = Depends(get_store),
) -> dict[str, int]:
    target = store.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")

    revoke_all = getattr(store, "revoke_user_sessions", None)
    if revoke_all is None:
        return {"revoked": 0}

    authorization = request.headers.get("authorization", "")
    token = authorization.split(" ", 1)[1].strip() if authorization.lower().startswith("bearer ") else ""
    except_hash = hash_session_token(token) if target["id"] == claims.user_id and token else None
    return {"revoked": int(revoke_all(user_id, except_token_hash=except_hash))}


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


@router.post("/auth/users")
async def create_user(
    payload: CreateUserRequest,
    store: PostgresStore = Depends(get_store),
    _: TokenClaims = Depends(require_admin_role),
) -> UserOut:
    username = payload.username.strip().lower()
    if not username:
        raise HTTPException(status_code=400, detail="Username tidak boleh kosong.")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password minimal 6 karakter.")
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Role harus admin atau user.")

    if store.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="Username sudah dipakai.")

    row = store.create_user(
        username=username, password_hash=hash_password(payload.password), role=payload.role
    )
    return _serialize_user(row)


class UpdateUserRequest(BaseModel):
    role: str | None = None
    password: str | None = None


@router.patch("/auth/users/{user_id}")
async def update_user(
    user_id: int,
    payload: UpdateUserRequest,
    store: PostgresStore = Depends(get_store),
    claims: TokenClaims = Depends(require_admin_role),
) -> UserOut:
    target = store.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")

    if payload.role is not None:
        if payload.role not in VALID_ROLES:
            raise HTTPException(status_code=400, detail="Role harus admin atau user.")
        # Jangan sampai admin terakhir diturunkan jadi user biasa -- situs
        # kehilangan admin sama sekali, tidak ada yang bisa mengangkat admin
        # baru lagi lewat UI.
        if target["role"] == "admin" and payload.role != "admin" and store.count_admins() <= 1:
            raise HTTPException(
                status_code=400, detail="Tidak bisa menurunkan role admin terakhir."
            )
        store.update_user_role(user_id, payload.role)

    if payload.password is not None:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password minimal 6 karakter.")
        store.update_user_password(user_id, hash_password(payload.password))

    updated = store.get_user_by_id(user_id)
    return _serialize_user(updated)


@router.delete("/auth/users/{user_id}")
async def delete_user(
    user_id: int,
    store: PostgresStore = Depends(get_store),
    claims: TokenClaims = Depends(require_admin_role),
) -> dict[str, bool]:
    if user_id == claims.user_id:
        raise HTTPException(status_code=400, detail="Tidak bisa menghapus akun sendiri.")

    target = store.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User tidak ditemukan.")

    if target["role"] == "admin" and store.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="Tidak bisa menghapus admin terakhir.")

    store.delete_user(user_id)
    return {"ok": True}
