from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import require_admin_key, verify_login_password


router = APIRouter()


@router.post("/auth/verify")
async def verify_admin_key(_: None = Depends(require_admin_key)) -> dict[str, bool]:
    # Kalau dependency di atas tidak melempar exception, key-nya valid.
    return {"ok": True}


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, bool]:
    verify_login_password(payload.username, payload.password)
    return {"ok": True}
