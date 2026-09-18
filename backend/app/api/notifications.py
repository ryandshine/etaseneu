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


class DailyReportSendPayload(BaseModel):
    bot_token: str | None = None
    chat_id: str | None = None
    force: bool = True


@router.post("/daily-report/send")
async def trigger_daily_report(
    payload: DailyReportSendPayload | None = None,
    _: None = Depends(require_admin_key),
) -> dict[str, Any]:
    """Picukan pembuatan dan pengiriman Laporan Harian PPTX ke Telegram (khusus admin)."""
    from app.services.daily_report_service import DailyReportService

    service = DailyReportService()
    bot_token = payload.bot_token if payload else None
    chat_id = payload.chat_id if payload else None
    force = payload.force if payload else True
    res = await service.send_daily_telegram_report(bot_token=bot_token, chat_id=chat_id, force=force)
    return res


@router.get("/daily-report/download")
async def download_daily_report(
    _: None = Depends(require_admin_key),
):
    """Unduh file .pptx Laporan Harian Pemantauan Titik Panas secara langsung."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from fastapi.responses import Response
    from app.services.daily_report_service import DailyReportService

    service = DailyReportService()
    data = service.collect_daily_hotspot_data()
    pptx_bytes = service.generate_daily_hotspot_pptx(data)
    date_iso = datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y%m%d")
    filename = f"Laporan_Harian_Hotspot_KPS_{date_iso}_0700WIB.pptx"

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/daily-report/preview")
async def preview_daily_report(
    _: None = Depends(require_admin_key),
) -> dict[str, Any]:
    """Pratinjau data ringkasan Laporan Harian 24 jam."""
    from app.services.daily_report_service import DailyReportService

    service = DailyReportService()
    return service.collect_daily_hotspot_data()

