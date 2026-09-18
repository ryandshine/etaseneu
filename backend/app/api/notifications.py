"""Router API untuk notifikasi titik panas (hotspot) baru dan integrasi siaga."""

from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.auth import require_admin_key
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


class TestNotificationPayload(BaseModel):
    bot_token: str | None = None
    chat_id: str | None = None


@router.get("")
async def get_notifications(
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    """Ambil daftar riwayat notifikasi titik panas baru untuk pengguna."""
    service = NotificationService()
    items = service.list_notifications(limit=limit)
    return {
        "total": len(items),
        "notifications": items,
    }


@router.post("/test")
async def trigger_test_notification(
    payload: TestNotificationPayload | None = None,
    _: None = Depends(require_admin_key),
) -> dict[str, Any]:
    """Uji coba pembuatan notifikasi titik panas baru dan integrasi Telegram (khusus admin)."""
    service = NotificationService()
    bot_token = payload.bot_token if payload else None
    chat_id = payload.chat_id if payload else None
    notif = await service.create_test_notification(bot_token=bot_token, chat_id=chat_id)
    return {
        "success": True,
        "notification": notif,
        "message": "Notifikasi uji coba berhasil dibuat.",
    }
