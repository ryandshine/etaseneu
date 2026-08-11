from fastapi import APIRouter, Depends

from app.core.auth import require_admin_key


router = APIRouter()


@router.post("/auth/verify")
async def verify_admin_key(_: None = Depends(require_admin_key)) -> dict[str, bool]:
    # Kalau dependency di atas tidak melempar exception, key-nya valid.
    return {"ok": True}
