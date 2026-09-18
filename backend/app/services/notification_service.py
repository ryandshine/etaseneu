"""Layanan notifikasi titik panas (hotspot) baru untuk pengguna & integrasi Telegram."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore

logger = logging.getLogger("hotspot.notifications")

_FALLBACK_NOTIFICATIONS: list[dict[str, Any]] = []


class NotificationService:
    def __init__(self, store: PostgresStore | None = None) -> None:
        self.settings = get_settings()
        self.store = store or PostgresStore(self.settings.database_url)

    def _save_fallback(
        self,
        *,
        title: str,
        message: str,
        hotspot_count: int,
        severity: str = "warning",
        notification_type: str = "hotspot_new",
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        global _FALLBACK_NOTIFICATIONS
        now = created_at or datetime.now(timezone.utc)
        item = {
            "id": f"mem-{len(_FALLBACK_NOTIFICATIONS) + 1}-{int(now.timestamp())}",
            "type": notification_type,
            "title": title,
            "message": message,
            "hotspot_count": hotspot_count,
            "severity": severity,
            "metadata": metadata or {},
            "created_at": now.isoformat(),
        }
        _FALLBACK_NOTIFICATIONS.insert(0, item)
        if len(_FALLBACK_NOTIFICATIONS) > 100:
            _FALLBACK_NOTIFICATIONS = _FALLBACK_NOTIFICATIONS[:100]
        return item

    async def send_telegram_alert(
        self,
        text: str,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> bool:
        token = (bot_token or self.settings.telegram_bot_token or "").strip()
        target_chat = (chat_id or self.settings.telegram_chat_id or "").strip()

        if not token or not target_chat:
            logger.debug("Telegram notification dilewati: bot token / chat id belum disetel.")
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info("Telegram notification terkirim ke chat_id=%s", target_chat)
                    return True
                logger.warning(
                    "Gagal mengirim Telegram notification (HTTP %s): %s",
                    resp.status_code,
                    resp.text,
                )
                return False
        except Exception as exc:
            logger.error("Error koneksi Telegram notification: %s", exc)
            return False

    async def notify_new_hotspots(
        self,
        new_hotspots: list[dict],
        sync_time: datetime | None = None,
    ) -> dict[str, Any]:
        if not new_hotspots:
            return {}

        now = sync_time or datetime.now(timezone.utc)
        count = len(new_hotspots)

        provinces_set = set()
        agencies_set = set()
        satellites_set = set()
        frp_vals: list[float] = []
        has_high_conf = False

        for h in new_hotspots:
            prov = (
                (h.get("polygonMetadata") or {}).get("NAMA_PROV")
                or h.get("provinceName")
                or ""
            ).strip()
            if prov and prov != "—" and prov != "-":
                provinces_set.add(prov)

            agency = (
                h.get("agencyName")
                or (h.get("polygonMetadata") or {}).get("LEMBAGA")
                or h.get("layer_name")
                or ""
            ).strip()
            if agency and agency != "—" and agency != "-":
                agencies_set.add(agency)

            sat = str(h.get("satellite") or h.get("source") or "NASA").strip()
            if sat:
                satellites_set.add(sat)

            frp = h.get("frp")
            if frp is not None:
                try:
                    frp_vals.append(float(frp))
                except (ValueError, TypeError):
                    pass

            conf = str(h.get("confidence") or "").lower()
            if conf in ("h", "high", "tinggi") or (frp and float(frp) > 30):
                has_high_conf = True

        provinces = sorted(list(provinces_set))
        agencies = sorted(list(agencies_set))
        satellites = sorted(list(satellites_set))
        max_frp = max(frp_vals, default=0.0)

        severity = "danger" if (has_high_conf or count >= 10) else "warning"
        title = f"🔥 {count} Titik Panas Baru Terdeteksi"

        if provinces:
            prov_text = ", ".join(provinces[:3])
            if len(provinces) > 3:
                prov_text += f" dan {len(provinces) - 3} provinsi lain"
            message = f"Terdeteksi {count} titik panas baru di areal Perhutanan Sosial ({prov_text})."
        else:
            message = f"Terdeteksi {count} titik panas baru di areal Perhutanan Sosial."

        metadata = {
            "provinces": provinces,
            "agencies": agencies[:10],
            "satellites": satellites,
            "max_frp": round(max_frp, 1),
            "has_high_confidence": has_high_conf,
            "synced_at": now.isoformat(),
        }

        # Simpan ke database atau memori
        if self.store.enabled:
            try:
                notif = self.store.save_notification(
                    title=title,
                    message=message,
                    hotspot_count=count,
                    severity=severity,
                    notification_type="hotspot_new",
                    metadata=metadata,
                    created_at=now,
                )
            except Exception as e:
                logger.error("Gagal menyimpan notifikasi ke DB: %s", e)
                notif = self._save_fallback(
                    title=title,
                    message=message,
                    hotspot_count=count,
                    severity=severity,
                    notification_type="hotspot_new",
                    metadata=metadata,
                    created_at=now,
                )
        else:
            notif = self._save_fallback(
                title=title,
                message=message,
                hotspot_count=count,
                severity=severity,
                notification_type="hotspot_new",
                metadata=metadata,
                created_at=now,
            )

        # Kirim Telegram jika dikonfigurasi
        if self.settings.telegram_bot_token and self.settings.telegram_chat_id:
            try:
                wib_time = now.astimezone(ZoneInfo("Asia/Jakarta")).strftime(
                    "%d %b %Y %H:%M WIB"
                )
            except Exception:
                wib_time = now.strftime("%Y-%m-%d %H:%M UTC")

            tg_text = (
                "🔥 *PERINGATAN TITIK PANAS BARU (ETA SENEU)*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"🚨 *Jumlah Hotspot*: {count} Titik Baru\n"
                f"⚠️ *Tingkat Siaga*: {'TINGGI / BAHAYA' if severity == 'danger' else 'WASPADA'}\n"
                f"📍 *Wilayah*: {', '.join(provinces) if provinces else 'Kawasan Hutan / KPS'}\n"
                f"🏛️ *KPS / Lembaga*: {', '.join(agencies[:5]) if agencies else 'Areal PS'}\n"
                f"🛰️ *Satelit*: {', '.join(satellites) if satellites else 'VIIRS / MODIS'}\n"
                f"⚡ *FRP Maks*: {round(max_frp, 1)} MW\n"
                f"📅 *Waktu Deteksi*: {wib_time}\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 Pantau Live: {self.settings.frontend_origin}"
            )
            # Jalankan kirim Telegram di background asyncio task agar tidak memblokir siklus sync
            asyncio.create_task(self.send_telegram_alert(tg_text))

        return notif

    def list_notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        if self.store.enabled:
            try:
                db_items = self.store.list_notifications(limit=limit)
                if db_items:
                    return db_items
            except Exception as e:
                logger.error("Gagal mengambil notifikasi dari DB: %s", e)

        global _FALLBACK_NOTIFICATIONS
        if _FALLBACK_NOTIFICATIONS:
            return _FALLBACK_NOTIFICATIONS[:limit]

        # Jika belum ada notifikasi sama sekali, buat notifikasi default siaga
        now = datetime.now(timezone.utc)
        return [
            {
                "id": "init-status-1",
                "type": "system_status",
                "title": "Sistem Siaga Pemantauan Aktif",
                "message": "Sistem ETASENEU memantau titik panas NASA FIRMS secara otomatis setiap jadwal sinkronisasi.",
                "hotspot_count": 0,
                "severity": "info",
                "metadata": {
                    "synced_at": now.isoformat(),
                    "schedule": self.settings.scheduler_fixed_hours,
                },
                "created_at": now.isoformat(),
            }
        ]

    async def create_test_notification(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        mock_hotspots = [
            {
                "source": "VIIRS NOAA-20",
                "satellite": "NOAA-20",
                "latitude": 0.5123,
                "longitude": 101.4421,
                "confidence": "high",
                "frp": 38.5,
                "agencyName": "KTH Tella Serasan",
                "polygonMetadata": {"NAMA_PROV": "Riau", "LEMBAGA": "KTH Tella Serasan"},
            },
            {
                "source": "VIIRS S-NPP",
                "satellite": "S-NPP",
                "latitude": -2.3123,
                "longitude": 104.2123,
                "confidence": "nominal",
                "frp": 16.2,
                "agencyName": "KUPS Muara Medak",
                "polygonMetadata": {"NAMA_PROV": "Sumatera Selatan", "LEMBAGA": "KUPS Muara Medak"},
            },
        ]
        notif = await self.notify_new_hotspots(mock_hotspots, sync_time=now)
        if bot_token and chat_id:
            await self.send_telegram_alert(
                "🧪 *UJI COBA NOTIFIKASI ETASENEU*\n"
                "Integrasi notifikasi Telegram telah berhasil dikonfigurasi!",
                bot_token=bot_token,
                chat_id=chat_id,
            )
        return notif
