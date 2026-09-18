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

        # Saring HANYA titik panas yang berada DI DALAM poligon KPS (bukan buffer perimeter)
        # serta berkeyakinan Sedang (medium/nominal) dan Tinggi (high)
        qualifying_hotspots: list[tuple[dict, str]] = []
        for h in new_hotspots:
            raw_payload = h.get("raw_payload") or {}
            is_perimeter = (
                h.get("is_perimeter") is True
                or raw_payload.get("is_perimeter") is True
                or str(raw_payload.get("is_perimeter")).lower() == "true"
                or str(h.get("layer_id")) == "perimeter_threat"
                or str(h.get("layer_key")) == "perimeter_threat"
                or str(h.get("agency_name") or "").startswith("Luar Kawasan")
            )
            if is_perimeter:
                continue

            cat = confidence_category(h)
            if cat in ("Tinggi", "Sedang"):
                qualifying_hotspots.append((h, cat))

        if not qualifying_hotspots:
            logger.info(
                "Tidak ada titik panas baru di dalam poligon KPS berkategori Sedang/Tinggi. Notifikasi dilewati.",
            )
            return {}

        # Susun data detail tiap hotspot (FRP, Google Maps URL, keyakinan, lembaga, Balai PS)
        hotspot_details: list[dict[str, Any]] = []
        provinces_set = set()
        agencies_set = set()
        bps_set = set()
        satellites_set = set()
        frp_vals: list[float] = []
        has_high_conf = False

        for h, conf_cat in qualifying_hotspots:
            try:
                lat = float(h["latitude"])
                lon = float(h["longitude"])
                if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                    continue
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

            poly_meta = (
                h.get("polygonMetadata")
                or h.get("polygon_metadata")
                or (h.get("raw_payload") or {}).get("polygon_metadata")
                or {}
            )
            raw_payload = h.get("raw_payload") or {}

            prov = (
                poly_meta.get("NAMA_PROV")
                or h.get("provinceName")
                or h.get("province_name")
                or raw_payload.get("province_name")
                or ""
            ).strip()
            if prov and prov not in ("—", "-"):
                provinces_set.add(prov)
            else:
                prov = "Indonesia"

            kab = (
                poly_meta.get("NAMA_KAB")
                or h.get("kabupatenName")
                or h.get("kabupaten_name")
                or raw_payload.get("kabupaten_name")
                or ""
            ).strip()

            kec = (
                poly_meta.get("NAMA_KEC")
                or h.get("kecamatanName")
                or h.get("kecamatan_name")
                or ""
            ).strip()

            desa = (
                poly_meta.get("NAMA_DESA")
                or h.get("desaName")
                or h.get("desa_name")
                or ""
            ).strip()

            agency = (
                h.get("agencyName")
                or h.get("agency_name")
                or poly_meta.get("LEMBAGA")
                or raw_payload.get("agency_name")
                or h.get("layer_name")
                or ""
            ).strip()
            if agency and agency not in ("—", "-"):
                agencies_set.add(agency)
            else:
                agency = "Areal Perhutanan Sosial"

            # Ekstraksi nama Balai PS (Wilker BPS)
            bps = (
                poly_meta.get("WILKER_BPS")
                or poly_meta.get("wilker_bps")
                or h.get("wilker_bps")
                or h.get("wilkerBps")
                or raw_payload.get("wilker_bps")
                or ""
            ).strip()

            if not bps and self.store.enabled:
                lookup_target = raw_payload.get("nearest_kps_name") or agency
                if lookup_target and lookup_target not in ("Areal Perhutanan Sosial", "—", "-"):
                    try:
                        with self.store.connection() as conn:
                            with conn.cursor() as cur:
                                cur.execute(
                                    "SELECT wilker_bps FROM polygon_metadata WHERE lembaga = %s AND wilker_bps IS NOT NULL LIMIT 1;",
                                    (lookup_target,),
                                )
                                row = cur.fetchone()
                                if row and row.get("wilker_bps"):
                                    bps = row["wilker_bps"].strip()
                    except Exception:
                        pass

            if bps and bps not in ("—", "-"):
                bps_set.add(bps)
            else:
                bps = None

            sat = str(h.get("satellite") or h.get("source") or "NASA").strip()
            if sat:
                satellites_set.add(sat)

            # URL Google Maps presisi 6 desimal (~0.11 m) dengan pin langsung
            gmaps_url = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"

            hotspot_details.append({
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "frp": frp_val,
                "confidence": conf_cat,  # "Tinggi" atau "Sedang"
                "raw_confidence": str(h.get("confidence") or ""),
                "agency_name": agency,
                "wilker_bps": bps,
                "province_name": prov,
                "kabupaten_name": kab if kab and kab not in ("—", "-") else None,
                "kecamatan_name": kec if kec and kec not in ("—", "-") else None,
                "desa_name": desa if desa and desa not in ("—", "-") else None,
                "satellite": sat,
                "google_maps_url": gmaps_url,
            })

        count = len(hotspot_details)
        if count == 0:
            return {}

        provinces = sorted(list(provinces_set))
        agencies = sorted(list(agencies_set))
        bps_list = sorted(list(bps_set))
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
            "wilker_bps": bps_list,
            "satellites": satellites,
            "max_frp": round(max_frp, 1),
            "has_high_confidence": has_high_conf,
            "hotspots": hotspot_details[:50],  # simpan rincian titik panas lengkap dengan frp, gmaps, dan Balai PS
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

            # Susun daftar rincian per hotspot dengan lokasi teliti, Balai PS, dan koordinat presisi
            item_lines: list[str] = []
            for idx, item in enumerate(hotspot_details[:8], 1):
                frp_text = f"{item['frp']} MW" if item['frp'] is not None else "—"
                conf_badge = f"<b>{item['confidence']}</b>"
                if item.get("raw_confidence"):
                    conf_badge += f" ({html.escape(item['raw_confidence'])})"

                # Baris Balai PS
                bps_line = f"   • Balai PS: <b>{html.escape(item['wilker_bps'])}</b>\n" if item.get("wilker_bps") else ""

                # Susun label wilayah yang teliti (Desa, Kecamatan, Kabupaten, Provinsi)
                loc_parts = []
                if item.get("desa_name"):
                    loc_parts.append(f"Desa {item['desa_name']}")
                if item.get("kecamatan_name"):
                    loc_parts.append(f"Kec. {item['kecamatan_name']}")
                if item.get("kabupaten_name"):
                    loc_parts.append(f"Kab. {item['kabupaten_name']}")
                if item.get("province_name") and item["province_name"] != "Indonesia":
                    loc_parts.append(item["province_name"])

                loc_str = ", ".join(loc_parts) if loc_parts else item.get("province_name") or "Indonesia"

                item_lines.append(
                    f"{idx}. 🏛️ <b>{html.escape(item['agency_name'])}</b>\n"
                    f"{bps_line}"
                    f"   • Wilayah: <b>{html.escape(loc_str)}</b>\n"
                    f"   • Koordinat: <code>{item['latitude']:.6f}, {item['longitude']:.6f}</code>\n"
                    f"   • Keyakinan: {conf_badge}\n"
                    f"   • FRP: <b>{frp_text}</b>\n"
                    f"   • 📍 <a href=\"{item['google_maps_url']}\">Buka di Google Maps ({item['latitude']:.5f}, {item['longitude']:.5f})</a>"
                )

            if len(hotspot_details) > 8:
                item_lines.append(f"<i>... dan {len(hotspot_details) - 8} titik panas lainnya.</i>")

            hotspots_block = "\n\n".join(item_lines)

            status_label = "TINGGI / BAHAYA" if severity == "danger" else "WASPADA"
            balai_summary_line = f"🏢 <b>Balai PS</b>: {', '.join(bps_list)}\n" if bps_list else ""
            tg_text = (
                "🔥 <b>PERINGATAN TITIK PANAS (HOTSPOT) KPS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"🚨 <b>Status</b>: {status_label} ({count} Titik Baru — Keyakinan Sedang & Tinggi)\n"
                f"{balai_summary_line}"
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
        real_hotspots = []

        # Coba ambil titik panas aktual dari tabel hotspot_observations beserta Balai PS
        if self.store.enabled:
            try:
                with self.store.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT h.latitude, h.longitude,
                                   (h.raw_payload->>'frp')::float as frp,
                                   h.confidence, h.satellite, h.source,
                                   h.agency_name,
                                   h.raw_payload->>'province_name' as prov,
                                   h.raw_payload->'polygon_metadata' as poly_meta,
                                   p.wilker_bps,
                                   p.nama_kab,
                                   p.nama_kec,
                                   p.nama_desa
                            FROM hotspot_observations h
                            LEFT JOIN polygon_metadata p ON (
                                p.is_active = TRUE AND (
                                    ST_Contains(p.geometry, ST_SetSRID(ST_Point(h.longitude, h.latitude), 4326))
                                    OR p.lembaga = h.agency_name
                                    OR p.lembaga = (h.raw_payload->>'nearest_kps_name')
                                )
                            )
                            WHERE (h.raw_payload->>'frp') IS NOT NULL
                              AND (h.confidence IN ('high', 'h', 'nominal', 'n')
                                   OR (h.confidence ~ '^[0-9]+$' AND h.confidence::int >= 30))
                            ORDER BY h.detected_at DESC
                            LIMIT 5;
                        """)
                        for r in cur.fetchall():
                            poly_meta = r["poly_meta"] or {}
                            if r.get("wilker_bps"):
                                poly_meta["WILKER_BPS"] = r["wilker_bps"]
                            if r.get("nama_kab"):
                                poly_meta["NAMA_KAB"] = r["nama_kab"]
                            if r.get("nama_kec"):
                                poly_meta["NAMA_KEC"] = r["nama_kec"]
                            if r.get("nama_desa"):
                                poly_meta["NAMA_DESA"] = r["nama_desa"]

                            real_hotspots.append({
                                "latitude": float(r["latitude"]),
                                "longitude": float(r["longitude"]),
                                "frp": float(r["frp"]) if r["frp"] is not None else None,
                                "confidence": str(r["confidence"] or ""),
                                "satellite": str(r["satellite"] or "NASA"),
                                "source": str(r["source"] or "NASA"),
                                "agencyName": r["agency_name"],
                                "provinceName": r["prov"],
                                "wilker_bps": r.get("wilker_bps"),
                                "polygonMetadata": poly_meta,
                            })
            except Exception as exc:
                logger.warning("Gagal query hotspot riil untuk test notifikasi: %s", exc)

        if not real_hotspots:
            # Koordinat spasial riil poligon KPS yang terverifikasi di PostGIS
            # KTH TELLA SERASAN: Desa Teluk Limau, Kec. Gelumbang, Kab. Muara Enim, Sumatera Selatan (Balai PS Palembang)
            # KTH MEDAK LESTARI: Desa Muara Medak, Kec. Bayung Lencir, Kab. Musi Banyuasin, Sumatera Selatan (Balai PS Palembang)
            real_hotspots = [
                {
                    "source": "VIIRS NOAA-20",
                    "satellite": "NOAA-20",
                    "latitude": -3.095974,
                    "longitude": 104.376196,
                    "confidence": "high",
                    "frp": 38.5,
                    "agencyName": "KTH TELLA SERASAN",
                    "wilker_bps": "Balai PS Palembang",
                    "polygonMetadata": {
                        "NAMA_PROV": "Sumatera Selatan",
                        "NAMA_KAB": "Muara Enim",
                        "NAMA_KEC": "Gelumbang",
                        "NAMA_DESA": "Teluk Limau",
                        "LEMBAGA": "KTH TELLA SERASAN",
                        "WILKER_BPS": "Balai PS Palembang",
                    },
                },
                {
                    "source": "VIIRS S-NPP",
                    "satellite": "S-NPP",
                    "latitude": -1.871053,
                    "longitude": 103.889048,
                    "confidence": "nominal",
                    "frp": 16.2,
                    "agencyName": "KTH MEDAK LESTARI",
                    "wilker_bps": "Balai PS Palembang",
                    "polygonMetadata": {
                        "NAMA_PROV": "Sumatera Selatan",
                        "NAMA_KAB": "Musi Banyuasin",
                        "NAMA_KEC": "Bayung Lencir",
                        "NAMA_DESA": "Muara Medak",
                        "LEMBAGA": "KTH MEDAK LESTARI",
                        "WILKER_BPS": "Balai PS Palembang",
                    },
                },
            ]

        notif = await self.notify_new_hotspots(real_hotspots, sync_time=now)
        if bot_token and chat_id:
            await self.send_telegram_alert(
                "🧪 <b>UJI COBA NOTIFIKASI ETASENEU</b>\n"
                "Integrasi notifikasi Telegram telah berhasil dikonfigurasi!",
                bot_token=bot_token,
                chat_id=chat_id,
                parse_mode="HTML",
            )
        return notif
