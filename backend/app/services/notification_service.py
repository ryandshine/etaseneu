"""Layanan notifikasi titik panas (hotspot) baru untuk pengguna & integrasi Telegram."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

import html
from app.core.config import get_settings
from app.services.hotspot_categories import confidence_category
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
        parse_mode: str = "HTML",
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
            "parse_mode": parse_mode,
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

        # Saring HANYA titik panas dengan confidence Sedang (medium/nominal) dan Tinggi (high)
        qualifying_hotspots: list[tuple[dict, str]] = []
        for h in new_hotspots:
            cat = confidence_category(h)
            if cat in ("Tinggi", "Sedang"):
                qualifying_hotspots.append((h, cat))

        if not qualifying_hotspots:
            logger.info(
                "Semua %d titik panas baru terdeteksi berkeyakinan Rendah (low). Notifikasi disaring/dilewati.",
                len(new_hotspots),
            )
            return {}

        # Susun data detail tiap hotspot (FRP, Google Maps URL, keyakinan, lembaga)
        hotspot_details: list[dict[str, Any]] = []
        provinces_set = set()
        agencies_set = set()
        satellites_set = set()
        frp_vals: list[float] = []
        has_high_conf = False

        for h, conf_cat in qualifying_hotspots:
            try:
                lat = float(h["latitude"])
                lon = float(h["longitude"])
            except (KeyError, ValueError, TypeError):
                continue

            frp_val: float | None = None
            if h.get("frp") is not None:
                try:
                    frp_val = round(float(h["frp"]), 1)
                    frp_vals.append(frp_val)
                except (ValueError, TypeError):
                    frp_val = None

            if conf_cat == "Tinggi":
                has_high_conf = True

            prov = (
                (h.get("polygonMetadata") or {}).get("NAMA_PROV")
                or h.get("provinceName")
                or ""
            ).strip()
            if prov and prov != "—" and prov != "-":
                provinces_set.add(prov)
            else:
                prov = "Indonesia"

            agency = (
                h.get("agencyName")
                or (h.get("polygonMetadata") or {}).get("LEMBAGA")
                or h.get("layer_name")
                or ""
            ).strip()
            if agency and agency != "—" and agency != "-":
                agencies_set.add(agency)
            else:
                agency = "Areal Perhutanan Sosial"

            sat = str(h.get("satellite") or h.get("source") or "NASA").strip()
            if sat:
                satellites_set.add(sat)

            gmaps_url = f"https://www.google.com/maps?q={lat:.5f},{lon:.5f}"

            hotspot_details.append({
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "frp": frp_val,
                "confidence": conf_cat,  # "Tinggi" atau "Sedang"
                "raw_confidence": str(h.get("confidence") or ""),
                "agency_name": agency,
                "province_name": prov,
                "satellite": sat,
                "google_maps_url": gmaps_url,
            })

        count = len(hotspot_details)
        if count == 0:
            return {}

        provinces = sorted(list(provinces_set))
        agencies = sorted(list(agencies_set))
        satellites = sorted(list(satellites_set))
        max_frp = max(frp_vals, default=0.0)

        severity = "danger" if (has_high_conf or max_frp > 30 or count >= 10) else "warning"
        title = f"🔥 {count} Titik Panas Baru Terdeteksi"

        if provinces:
            prov_text = ", ".join(provinces[:3])
            if len(provinces) > 3:
                prov_text += f" dan {len(provinces) - 3} provinsi lain"
            message = f"Terdeteksi {count} titik panas (Keyakinan Sedang & Tinggi) di areal Perhutanan Sosial ({prov_text})."
        else:
            message = f"Terdeteksi {count} titik panas (Keyakinan Sedang & Tinggi) di areal Perhutanan Sosial."

        metadata = {
            "provinces": provinces,
            "agencies": agencies[:10],
            "satellites": satellites,
            "max_frp": round(max_frp, 1),
            "has_high_confidence": has_high_conf,
            "hotspots": hotspot_details[:50],  # simpan rincian titik panas lengkap dengan frp & gmaps
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

            # Susun daftar rincian per hotspot (maks 8 titik agar nyaman dibaca di layar HP)
            item_lines: list[str] = []
            for idx, item in enumerate(hotspot_details[:8], 1):
                frp_text = f"{item['frp']} MW" if item['frp'] is not None else "—"
                conf_badge = f"<b>{item['confidence']}</b>"
                if item.get("raw_confidence"):
                    conf_badge += f" ({html.escape(item['raw_confidence'])})"

                item_lines.append(
                    f"{idx}. 🏛️ <b>{html.escape(item['agency_name'])}</b> ({html.escape(item['province_name'])})\n"
                    f"   • Keyakinan: {conf_badge}\n"
                    f"   • FRP: <b>{frp_text}</b>\n"
                    f"   • 📍 <a href=\"{item['google_maps_url']}\">Buka di Google Maps</a>"
                )

            if len(hotspot_details) > 8:
                item_lines.append(f"<i>... dan {len(hotspot_details) - 8} titik panas lainnya.</i>")

            hotspots_block = "\n\n".join(item_lines)

            status_label = "TINGGI / BAHAYA" if severity == "danger" else "WASPADA"
            tg_text = (
                "🔥 <b>PERINGATAN TITIK PANAS (HOTSPOT) KPS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"🚨 <b>Status</b>: {status_label} ({count} Titik Baru — Keyakinan Sedang & Tinggi)\n"
                f"⚡ <b>FRP Maksimum</b>: {round(max_frp, 1)} MW\n"
                f"📅 <b>Waktu Deteksi</b>: {wib_time}\n\n"
                "<b>Rincian Titik Panas:</b>\n\n"
                f"{hotspots_block}\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔗 <a href=\"{self.settings.frontend_origin}\">Pantau Live di Dashboard ETASENEU</a>"
            )
            # Jalankan kirim Telegram di background asyncio task agar tidak memblokir siklus sync
            asyncio.create_task(self.send_telegram_alert(tg_text, parse_mode="HTML"))

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
                "🧪 <b>UJI COBA NOTIFIKASI ETASENEU</b>\n"
                "Integrasi notifikasi Telegram telah berhasil dikonfigurasi!",
                bot_token=bot_token,
                chat_id=chat_id,
                parse_mode="HTML",
            )
        return notif
