from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import (
    TokenClaims,
    hash_password,
    issue_token,
    require_admin_key,
    require_admin_role,
    verify_password,
)
from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


router = APIRouter()

VALID_ROLES = ("admin", "user")


def get_store() -> PostgresStore:
    """Dependency (bukan dipanggil langsung) supaya test bisa override lewat
    app.dependency_overrides -- proyek ini tidak punya database test
    terpisah (lihat CLAUDE.md), jadi endpoint yang menulis kredensial login
    WAJIB bisa diuji tanpa menyentuh database produksi sungguhan."""
    settings = get_settings()
    store = PostgresStore(settings.database_url)
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database belum dikonfigurasi di server.")
    return store


@router.post("/auth/verify")
async def verify_admin_key_endpoint(_: None = Depends(require_admin_key)) -> dict[str, bool]:
    # Kalau dependency di atas tidak melempar exception, key-nya valid.
    return {"ok": True}


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(payload: LoginRequest, store: PostgresStore = Depends(get_store)) -> dict[str, object]:
    """Login gerbang aplikasi -- lihat postgres_store/_users.py.

    Kalau tabel app_users masih kosong (baru migrasi dari APP_LOGIN_PASSWORD),
    seed satu akun admin dari env itu dulu, supaya kredensial yang sudah
    dipakai produksi tetap jalan tanpa langkah manual di server.
    """
    settings = get_settings()

    if settings.app_login_password:
        store.ensure_seed_admin(
            username="admin",
            password_hash=hash_password(settings.app_login_password),
        )

    user = store.get_user_by_username(payload.username.strip().lower())
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Username atau password salah.")

    token = issue_token(user_id=user["id"], username=user["username"], role=user["role"])
    return {"ok": True, "token": token, "username": user["username"], "role": user["role"]}


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    created_at: str


def _serialize_user(row: dict) -> UserOut:
    return UserOut(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        created_at=str(row["created_at"]),
    )


@router.get("/auth/users")
async def list_users(
    store: PostgresStore = Depends(get_store), _: TokenClaims = Depends(require_admin_role)
) -> list[UserOut]:
    return [_serialize_user(row) for row in store.list_users()]


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
