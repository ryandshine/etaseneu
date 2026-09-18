"""Layanan bot Telegram interaktif dua arah (inbound & outbound) untuk ETASENEU.

Menangani interaksi publik (staf Balai PS, masyarakat, satgas, pimpinan)
melalui long-polling Telegram Bot API tanpa memerlukan setup webhook khusus.
"""

import asyncio
import html
import io
import logging
import urllib.parse
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.core.config import Settings, get_settings
from app.services.daily_report_service import DailyReportService
from app.services.postgres_store import PostgresStore

logger = logging.getLogger("hotspot.telegram_bot")


class TelegramBotService:
    """Layanan bot interaktif dua arah yang memproses perintah & pesan masuk dari Telegram."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: PostgresStore | None = None,
        report_service: DailyReportService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or PostgresStore(database_url=self.settings.database_url)
        self.report_service = report_service or DailyReportService(store=self.store)
        self.token = (self.settings.telegram_bot_token or "").strip()
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._last_offset = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    # =========================================================================
    # TELEGRAM HTTP API HELPERS
    # =========================================================================

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        """Kirim pesan teks ke chat_id tertentu."""
        if not self.is_configured:
            return {"ok": False, "error": "Bot token not configured"}

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                return resp.json()
        except Exception as e:
            logger.error("Gagal mengirim pesan Telegram ke %s: %s", chat_id, e)
            return {"ok": False, "error": str(e)}

    async def send_chat_action(self, chat_id: int | str, action: str = "typing") -> None:
        """Kirim status indikator pengetikan/pengunggahan dokumen."""
        if not self.is_configured:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendChatAction"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json={"chat_id": chat_id, "action": action})
        except Exception:
            pass

    async def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        """Konfirmasi callback query agar tombol tidak stuck loading."""
        if not self.is_configured:
            return
        url = f"https://api.telegram.org/bot{self.token}/answerCallbackQuery"
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(url, json=payload)
        except Exception:
            pass

    async def send_document(
        self,
        chat_id: int | str,
        document_bytes: bytes,
        filename: str,
        caption: str | None = None,
        parse_mode: str = "HTML",
    ) -> dict[str, Any]:
        """Kirim berkas dokumen (.pptx) langsung ke chat_id."""
        if not self.is_configured:
            return {"ok": False, "error": "Bot token not configured"}

        url = f"https://api.telegram.org/bot{self.token}/sendDocument"
        data: dict[str, Any] = {"chat_id": chat_id, "parse_mode": parse_mode}
        if caption:
            data["caption"] = caption[:1020]

        files = {
            "document": (
                filename,
                document_bytes,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        }

        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(url, data=data, files=files)
                return resp.json()
        except Exception as e:
            logger.error("Gagal mengirim dokumen ke %s: %s", chat_id, e)
            return {"ok": False, "error": str(e)}

    # =========================================================================
    # MENU & KEYBOARD DEFINITIONS
    # =========================================================================

    def _get_main_keyboard(self) -> dict[str, Any]:
        """Inline Keyboard menu navigasi interaktif."""
        dashboard_url = self.settings.frontend_origin or "https://etaseneu.kehutanan.go.id"
        return {
            "inline_keyboard": [
                [
                    {"text": "📊 Status Hotspot Hari Ini", "callback_data": "cmd_status"},
                    {"text": "🚨 KPS Peringatan Dini", "callback_data": "cmd_ew"},
                ],
                [
                    {"text": "🔍 Cari Data KPS", "callback_data": "cmd_cari"},
                    {"text": "📥 Unduh Laporan PPTX", "callback_data": "cmd_laporan"},
                ],
                [
                    {"text": "🏢 Sebaran per Balai PS", "callback_data": "cmd_balai"},
                    {"text": "🆔 Cek ID Saya", "callback_data": "cmd_id"},
                ],
                [
                    {"text": "🌐 Dashboard ETASENEU", "url": dashboard_url},
                ],
            ]
        }

    # =========================================================================
    # COMMAND HANDLERS
    # =========================================================================

    async def handle_start(self, chat_id: int | str, first_name: str) -> None:
        """Respon ramah untuk /start."""
        greeting = (
            f"👋 <b>Halo, {html.escape(first_name)}!</b>\n\n"
            "Selamat datang di <b>ETASENEU Bot</b> — Layanan Resmi Pemantauan Titik Panas (<i>Hotspot</i>) "
            "dan Peringatan Dini Kebakaran Hutan pada Areal <b>Perhutanan Sosial (KPS)</b> "
            "Kementerian Kehutanan Republik Indonesia.\n\n"
            "Bot ini dapat digunakan oleh publik, penyuluh, satgas, dan pimpinan untuk "
            "memantau anomali titik panas serta mengunduh dokumen laporan operasional.\n\n"
            "Silakan pilih menu di bawah atau ketik perintah langsung:"
        )
        await self.send_message(chat_id, greeting, reply_markup=self._get_main_keyboard())

    async def handle_help(self, chat_id: int | str) -> None:
        """Daftar bantuan perintah."""
        text = (
            "📖 <b>PANDUAN PERINTAH ETASENEU BOT</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>/start</b> — Menampilkan menu utama & navigasi bot.\n"
            "• <b>/status</b> — Status siaga nasional & titik panas 24 jam terakhir.\n"
            "• <b>/peringatandini</b> — Daftar KPS terbakar ulang (*Strict Re-burn*) & prioritas mitigasi.\n"
            "• <b>/cari [nama KPS]</b> — Cari profil KPS, koordinat lokasi, status titik panas & riwayat kebakaran.\n"
            "• <b>/laporan</b> — Mengunduh dokumen paparan presentasi PPTX resmi hari ini.\n"
            "• <b>/balai</b> — Rekapitulasi sebaran hotspot per Balai Perhutanan Sosial.\n"
            "• <b>/id</b> — Cek ID Telegram akun Anda (untuk pendaftaran notifikasi).\n"
            "• <b>/help</b> — Menampilkan panduan bantuan ini.\n\n"
            "<i>Data bersumber dari satelit NASA FIRMS (SNPP, NOAA-20, NOAA-21, Terra/Aqua) "
            "dan diproses spasial otomatis oleh sistem ETASENEU.</i>"
        )
        await self.send_message(chat_id, text, reply_markup=self._get_main_keyboard())

    async def handle_status(self, chat_id: int | str) -> None:
        """Menampilkan ringkasan status siaga & hotspot hari ini."""
        await self.send_chat_action(chat_id, "typing")
        data = self.report_service.collect_daily_hotspot_data()

        top_balai = ", ".join([b["name"].replace("Balai PS ", "") for b in data.get("balai_list", [])[:2]]) or "Nihil"
        ew_sum = data.get("early_warning_summary", {})

        text = (
            "📊 <b>STATUS PEMANTAUAN HOTSPOT AREAL KPS HARI INI</b>\n"
            "<i>(Khusus Titik Panas di Dalam Poligon Definitif KPS)</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Tanggal</b>: {data['report_date_str']}\n"
            f"⏱️ <b>Jendela Pantauan</b>: <code>{data.get('time_window_str', '24 Jam Terakhir')}</code> (24 Jam Terakhir)\n"
            "ℹ️ <i>Keterangan: Akumulasi 24 jam ke belakang dari saat ini, khusus titik api yang berada tepat di dalam batas poligon KPS (bukan buffer/luar kawasan).</i>\n\n"
            f"🚨 <b>Status Siaga</b>: <b>{data['status_siaga']}</b>\n"
            f"📈 <b>Total Hotspot di Dalam KPS</b>: <b>{data['total_hotspots']:,} titik</b>\n"
            f"   • High (Tinggi): <b>{data['high_count']}</b> titik\n"
            f"   • Medium (Sedang): <b>{data['medium_count']}</b> titik\n"
            f"   • Low (Rendah): <b>{data['low_count']}</b> titik\n\n"
            f"📊 <b>Tren H vs Kemarin (H-1)</b>:\n"
            f"   • Kemarin: {data['yesterday_total']:,} titik\n"
            f"   • Perubahan: <b>{data['trend_icon']} {data['delta_pct']:+.1f}%</b> ({data['trend_label']})\n\n"
            f"⚡ <b>Indikator Energi Api (FRP)</b>:\n"
            f"   • FRP Maks: <b>{data['max_frp']} MW</b> (Rerata: {data['avg_frp']} MW)\n"
            f"⏰ <b>Puncak Jam Deteksi</b>: Pukul {data['peak_day_hour']:02d}:00 WIB\n"
            f"🏢 <b>Balai Terdampak Utama</b>: {top_balai}\n\n"
            "<b>🔥 Rekap Peringatan Dini:</b>\n"
            f"• 🚨 {ew_sum.get('strict_reburn_kps', 0)} KPS Terbakar Ulang (Re-burn)\n"
            f"• 🟠 {ew_sum.get('expanding_kps', 0)} KPS Ekspansi Bara\n"
            f"• 🟡 {ew_sum.get('ew_new_kps', 0)} KPS Peringatan Dini Baru\n"
            f"<i>(Total {data.get('total_ew_active_today', 0)} KPS aktif titik panas hari ini)</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Ketik <b>/peringatandini</b> untuk rincian KPS atau <b>/laporan</b> untuk file PPTX."
        )
        await self.send_message(chat_id, text, reply_markup=self._get_main_keyboard())

    async def handle_early_warning(self, chat_id: int | str) -> None:
        """Menampilkan daftar KPS prioritas ancaman terbakar ulang."""
        await self.send_chat_action(chat_id, "typing")
        data = self.report_service.collect_daily_hotspot_data()

        strict_kps = [k for k in data.get("burned_kps_list", []) if k.get("hotspots_today_strict_reburn", 0) > 0]
        expanding_kps = [k for k in data.get("burned_kps_list", []) if k.get("hotspots_today_strict_reburn", 0) == 0][:3]
        ew_new = data.get("ew_new_list", [])[:3]

        lines = []
        if strict_kps:
            lines.append("<b>🚨 KPS TERBAKAR ULANG (STRICT RE-BURN):</b>")
            lines.append("<i>Titik api terdeteksi persis di dalam bekas kebakaran:</i>")
            for idx, k in enumerate(strict_kps[:4], 1):
                k_name = k.get("lembaga", "Areal KPS")[:26]
                k_bps = k.get("wilker_bps", "Balai PS").replace("Balai PS ", "")
                k_pts = k.get("hotspots_today") or 0
                k_re = k.get("hotspots_today_strict_reburn") or 0
                k_ftri = k.get("ftri_score") or 0.0
                gmaps = k.get("google_maps_url", "#")
                lines.append(
                    f"{idx}. 🚨 <b>{html.escape(k_name)}</b> ({k_bps})\n"
                    f"   • {k_pts} Titik ({k_re} Re-burn) | FTRI: {k_ftri:.1f} • <a href=\"{gmaps}\">Google Maps</a>"
                )
            if len(strict_kps) > 4:
                lines.append(f"   <i>(+{len(strict_kps) - 4} KPS re-burn lainnya ada di lampiran PPTX)</i>")
            lines.append("")

        if expanding_kps:
            lines.append("<b>🟠 KPS EKSPANSI BARA BEKAS KARHUTLA:</b>")
            for idx, k in enumerate(expanding_kps, 1):
                k_name = k.get("lembaga", "Areal KPS")[:26]
                k_bps = k.get("wilker_bps", "Balai PS").replace("Balai PS ", "")
                k_pts = k.get("hotspots_today") or 0
                k_ftri = k.get("ftri_score") or 0.0
                gmaps = k.get("google_maps_url", "#")
                lines.append(
                    f"{idx}. 🟠 <b>{html.escape(k_name)}</b> ({k_bps}): {k_pts} titik (FTRI: {k_ftri:.1f}) • <a href=\"{gmaps}\">Maps</a>"
                )
            lines.append("")

        if ew_new:
            lines.append("<b>🟡 KPS PERINGATAN DINI BARU (TOP FTRI EKSTREM):</b>")
            for idx, k in enumerate(ew_new, 1):
                k_name = k.get("lembaga", "Areal KPS")[:26]
                k_bps = k.get("wilker_bps", "Balai PS").replace("Balai PS ", "")
                k_pts = k.get("hotspots_today") or 0
                k_ftri = k.get("ftri_score") or 0.0
                gmaps = k.get("google_maps_url", "#")
                lines.append(
                    f"{idx}. 🟡 <b>{html.escape(k_name)}</b> ({k_bps}): {k_pts} titik (FTRI: {k_ftri:.1f}) • <a href=\"{gmaps}\">Maps</a>"
                )
            lines.append("")

        tot_ew = data.get("total_ew_active_today", 0)
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📎 <i>Seluruh 27 KPS areal bekas terbakar & top FTRI dimuat di file PPTX (/laporan).</i>")
        lines.append(f"🔗 <a href=\"{self.settings.frontend_origin}\">Unduh Excel Lengkap {tot_ew} KPS di ETASENEU</a>")

        text = "\n".join(lines)
        await self.send_message(chat_id, text, reply_markup=self._get_main_keyboard())

    async def handle_balai(self, chat_id: int | str) -> None:
        """Menampilkan rekapitulasi sebaran hotspot per Balai PS."""
        await self.send_chat_action(chat_id, "typing")
        data = self.report_service.collect_daily_hotspot_data()
        balai_list = data.get("balai_list", [])

        lines = [
            "🏢 <b>REKAPITULASI SEBARAN PER BALAI PERHUTANAN SOSIAL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Periode: 24 Jam Terakhir ({data['report_date_str']})\n"
        ]

        if not balai_list:
            lines.append("<i>Nihil titik panas di seluruh Balai PS hari ini.</i>")
        else:
            for idx, b in enumerate(balai_list, 1):
                b_name = b["name"].replace("Balai PS ", "")
                icon = "🔴" if b["high_count"] > 0 or b["priority_score"] >= 15 else ("🟡" if b["medium_count"] > 0 else "🟢")
                lines.append(
                    f"{idx}. {icon} <b>{html.escape(b_name)}</b>\n"
                    f"   • Total Pantau: <b>{b['total_priority']} titik</b> ({b['high_count']} High / {b['medium_count']} Med)\n"
                    f"   • Status: <i>{b['priority_status']}</i> (FRP Maks: {b['max_frp']} MW)"
                )

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("Ketik <b>/laporan</b> untuk mengunduh slide presentasi lengkap.")
        await self.send_message(chat_id, "\n".join(lines), reply_markup=self._get_main_keyboard())

    async def handle_laporan(self, chat_id: int | str) -> None:
        """Menghasilkan berkas .pptx dan mengirimkannya langsung ke pengguna."""
        await self.send_chat_action(chat_id, "upload_document")

        # Kirim notifikasi awal proses
        await self.send_message(
            chat_id,
            "⏳ <i>Sedang menyiapkan berkas presentasi PowerPoint 10 slide resmi hari ini. Mohon tunggu beberapa detik...</i>",
        )

        data = self.report_service.collect_daily_hotspot_data()
        pptx_bytes = self.report_service.generate_daily_hotspot_pptx(data)

        jakarta_tz = ZoneInfo("Asia/Jakarta")
        date_iso = datetime.now(jakarta_tz).strftime("%Y%m%d")
        filename = f"Laporan_Harian_Hotspot_KPS_{date_iso}_0700WIB.pptx"

        caption = (
            f"📊 <b>Laporan Harian Titik Panas KPS</b>\n"
            f"📅 <b>Tanggal</b>: {data['report_date_str']}\n"
            f"⏱️ <b>Jendela Pantauan</b>: <code>{data.get('time_window_str', '24 Jam')}</code> (24 Jam)\n"
            "📍 <b>Lingkup Spasial</b>: Khusus titik panas di dalam poligon definitif KPS (luar kawasan/buffer ditiadakan)\n"
            f"🚨 <b>Status Siaga</b>: <b>{data['status_siaga']}</b> | Total: <b>{data['total_hotspots']:,} titik</b>\n\n"
            "<i>Presentasi 10 slide widescreen memuat grafik tren H vs H-1, jam kritis patroli, "
            "daftar seluruh KPS terbakar ulang, dan matriks keputusan satgas.</i>"
        )

        await self.send_document(
            chat_id=chat_id,
            document_bytes=pptx_bytes,
            filename=filename,
            caption=caption,
        )

    async def handle_id(self, chat_id: int | str, from_user: dict[str, Any]) -> None:
        """Menampilkan ID pengguna untuk keperluan registrasi notifikasi."""
        u_id = from_user.get("id", chat_id)
        f_name = from_user.get("first_name", "User")
        u_name = from_user.get("username")
        u_str = f"@{u_name}" if u_name else "(belum disetel)"

        text = (
            "🆔 <b>INFORMASI AKUN TELEGRAM ANDA</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Chat ID</b>: <code>{chat_id}</code>\n"
            f"• <b>User ID</b>: <code>{u_id}</code>\n"
            f"• <b>Nama</b>: {html.escape(f_name)}\n"
            f"• <b>Username</b>: {u_str}\n\n"
            "💡 <i>Kirimkan ID Chat di atas kepada Administrator ETASENEU jika Anda "
            "ingin didaftarkan untuk menerima laporan harian atau notifikasi titik panas otomatis.</i>"
        )
        await self.send_message(chat_id, text, reply_markup=self._get_main_keyboard())

    def _search_kps_in_db(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Mencari KPS di database berdasarkan nama lembaga, desa, kecamatan, kabupaten, provinsi, atau no_sk."""
        clean_q = query.strip()
        if not clean_q or not self.store.enabled:
            return []

        search_pattern = f"%{clean_q}%"
        try:
            with self.store.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 
                            p.id, p.lembaga, p.skema, p.nama_desa, p.nama_kec, p.nama_kab, p.nama_prov, p.wilker_bps, p.no_sk, p.tgl_sk,
                            COALESCE(p.luas_final::numeric, 0) as luas_ha,
                            ST_Y(ST_Centroid(p.geometry)) as lat,
                            ST_X(ST_Centroid(p.geometry)) as lon,
                            COALESCE((
                                SELECT sum(burned_area_ha)
                                FROM burned_area_summary b
                                WHERE b.polygon_metadata_id = p.id
                            ), 0) as burned_area_ha,
                            COALESCE((
                                SELECT count(DISTINCT r.hotspot_observation_id)
                                FROM hotspot_polygon_relation r
                                JOIN hotspot_observations h ON h.id = r.hotspot_observation_id
                                WHERE r.polygon_metadata_id = p.id AND h.detected_at >= NOW() - INTERVAL '24 hours'
                            ), 0) as hotspot_count_today
                        FROM polygon_metadata p
                        WHERE p.lembaga ILIKE %s 
                           OR p.nama_desa ILIKE %s 
                           OR p.nama_kec ILIKE %s 
                           OR p.nama_kab ILIKE %s 
                           OR p.nama_prov ILIKE %s
                           OR p.no_sk ILIKE %s
                        ORDER BY 
                            CASE 
                                WHEN p.lembaga ILIKE %s THEN 1
                                WHEN p.no_sk ILIKE %s THEN 2
                                WHEN p.nama_desa ILIKE %s THEN 3
                                WHEN p.nama_kec ILIKE %s THEN 4
                                WHEN p.nama_kab ILIKE %s THEN 5
                                ELSE 6
                            END ASC,
                            hotspot_count_today DESC,
                            p.id DESC
                        LIMIT %s;
                        """,
                        (
                            search_pattern, search_pattern, search_pattern, search_pattern, search_pattern, search_pattern,
                            search_pattern, search_pattern, search_pattern, search_pattern, search_pattern,
                            limit * 4,
                        ),
                    )
                    rows = [dict(r) for r in cur.fetchall()]

            # Deduplikasi berdasarkan (lembaga, no_sk) agar tidak duplikat lintas shapefile revisi
            seen = set()
            unique_results = []
            for r in rows:
                key = (
                    (r.get("lembaga") or "").strip().upper(),
                    (r.get("no_sk") or "").strip().upper(),
                )
                if key in seen and key != ("", ""):
                    continue
                seen.add(key)
                unique_results.append(r)
                if len(unique_results) >= limit:
                    break

            return unique_results
        except Exception as e:
            logger.error("Gagal melakukan pencarian KPS '%s': %s", clean_q, e)
            return []

    async def handle_search_kps(self, chat_id: int | str, query: str) -> None:
        """Menangani pencarian data KPS dan menampilkan profil, koordinat, dan hotspot terkini."""
        clean_q = query.strip()
        if not clean_q:
            guide_text = (
                "🔍 <b>PENCARIAN DATA KPS (PERHUTANAN SOSIAL)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Gunakan fitur ini untuk mencari profil KPS, titik koordinat, status titik panas hari ini, dan riwayat kebakaran.\n\n"
                "<b>Cara Penggunaan:</b>\n"
                "Ketik: <code>/cari [kata kunci]</code>\n\n"
                "<b>Contoh Pencarian:</b>\n"
                "• <code>/cari Tella Serasan</code> (Nama KPS / Lembaga)\n"
                "• <code>/cari Teluk Limau</code> (Nama Desa)\n"
                "• <code>/cari Ogan Komering Ilir</code> (Nama Kabupaten)\n"
                "• <code>/cari 4284</code> (Nomor SK)\n\n"
                "<i>Anda juga bisa langsung mengetik pesan seperti:</i>\n"
                "<i>\"cari kps tella serasan\"</i> atau <i>\"cek kps lingat\"</i>"
            )
            await self.send_message(chat_id, guide_text, reply_markup=self._get_main_keyboard())
            return

        await self.send_chat_action(chat_id, "typing")
        results = self._search_kps_in_db(clean_q, limit=5)

        if not results:
            not_found = (
                f"🔍 <b>PENCARIAN KPS:</b> <i>\"{html.escape(clean_q)}\"</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "❌ <b>Data KPS tidak ditemukan.</b>\n\n"
                "Tips pencarian:\n"
                "• Pastikan ejaan nama KPS, desa, kecamatan, atau nomor SK benar.\n"
                "• Coba gunakan kata kunci yang lebih ringkas (mis. <i>Tella</i> atau <i>Rimba</i>).\n"
                "• Ketik <b>/help</b> untuk melihat bantuan."
            )
            await self.send_message(chat_id, not_found, reply_markup=self._get_main_keyboard())
            return

        dashboard_url = (self.settings.frontend_origin or "https://etaseneu.kehutanan.go.id").rstrip("/")

        lines = [
            f"🔍 <b>HASIL PENCARIAN KPS:</b> <i>\"{html.escape(clean_q)}\"</i>",
            f"Ditemukan <b>{len(results)}</b> KPS yang cocok:\n━━━━━━━━━━━━━━━━━━━━━━",
        ]

        for idx, k in enumerate(results, 1):
            lembaga = html.escape(k.get("lembaga") or "KPS Tanpa Nama")
            skema = html.escape(k.get("skema") or "-")
            balai = html.escape(k.get("wilker_bps") or "-")
            desa = html.escape(k.get("nama_desa") or "-")
            kec = html.escape(k.get("nama_kec") or "-")
            kab = html.escape(k.get("nama_kab") or "-")
            prov = html.escape(k.get("nama_prov") or "-")
            no_sk = html.escape(k.get("no_sk") or "-")
            tgl_sk = html.escape(str(k.get("tgl_sk") or ""))
            luas = float(k.get("luas_ha") or 0.0)
            lat = float(k.get("lat") or 0.0)
            lon = float(k.get("lon") or 0.0)
            hs_today = int(k.get("hotspot_count_today") or 0)
            burned_ha = float(k.get("burned_area_ha") or 0.0)
            poly_id = k.get("id")

            hs_status = f"🚨 <b>{hs_today} titik panas aktif</b>" if hs_today > 0 else "✅ <b>Nihil (0 titik)</b>"
            burned_str = f"{burned_ha:,.2f} Ha" if burned_ha > 0 else "0 Ha (Tidak terpapar)"

            maps_item = ""
            if lat and lon:
                gmaps_link = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
                maps_item = f"   • 🗺️ <a href=\"{gmaps_link}\">Buka Lokasi Google Maps</a>\n"

            kps_encoded = urllib.parse.quote(k.get("lembaga") or "")
            web_link = f"{dashboard_url}/?view=kps&kps={kps_encoded}&polygon={poly_id}"

            item_text = (
                f"<b>{idx}. 🌲 {lembaga}</b>\n"
                f"   • <b>Skema</b>: {skema}\n"
                f"   • 🏢 <b>Balai PS</b>: {balai}\n"
                f"   • 📍 <b>Lokasi</b>: Desa {desa}, Kec. {kec}, Kab. {kab}, {prov}\n"
                f"   • 📜 <b>No. SK</b>: <code>{no_sk}</code>" + (f" ({tgl_sk})" if tgl_sk else "") + "\n"
                f"   • 📐 <b>Luas SK</b>: {luas:,.2f} Ha\n"
                f"   • 🔥 <b>Hotspot 24 Jam Terakhir</b>: {hs_status}\n"
                f"   • ⬛ <b>Riwayat Kebakaran</b>: {burned_str}\n"
                f"{maps_item}"
                f"   • 🌐 <a href=\"{web_link}\">Buka Detail KPS di ETASENEU</a>"
            )
            lines.append(item_text)
            if idx < len(results):
                lines.append("──────────────────────")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("<i>Gunakan <b>/cari [kata kunci lain]</b> untuk pencarian berikutnya.</i>")
        msg_text = "\n".join(lines)
        await self.send_message(chat_id, msg_text, reply_markup=self._get_main_keyboard())

    async def handle_unknown_or_text(self, chat_id: int | str, text_msg: str, first_name: str) -> None:
        """Respon pintar untuk percakapan bebas atau perintah tidak dikenal."""
        lower = text_msg.lower().strip()

        # Deteksi salam / sapaan ramah
        sapaan_list = ["halo", "hai", "hi", "hey", "pagi", "siang", "sore", "malam", "assalamualaikum", "ping", "tes", "test", "menu"]
        if any(lower.startswith(s) or lower == s for s in sapaan_list):
            await self.handle_start(chat_id, first_name)
            return

        # Deteksi pencarian KPS dengan frasa awalan spesifik
        search_prefixes = [
            "cari kps ", "cari data kps ", "cari kps: ", "cari ",
            "cek kps ", "cek data kps ", "cek kps: ", "cek ",
            "info kps ", "profil kps ", "kps "
        ]
        for prefix in search_prefixes:
            if lower.startswith(prefix):
                q = text_msg[len(prefix):].strip()
                if q and not any(k in q.lower() for k in ["hotspot", "titik panas", "status", "siaga", "laporan", "pptx", "balai"]):
                    await self.handle_search_kps(chat_id, q)
                    return

        # Deteksi kata kunci hotspot / status
        if any(k in lower for k in ["hotspot", "titik panas", "status", "siaga", "kondisi", "karhutla", "kebakaran"]):
            await self.handle_status(chat_id)
            return

        # Deteksi kata kunci peringatan dini / re-burn
        if any(k in lower for k in ["peringatan dini", "reburn", "terbakar ulang", "ekspansi", "ftri", "bekas"]):
            await self.handle_early_warning(chat_id)
            return

        # Deteksi kata kunci laporan / pptx / presentasi
        if any(k in lower for k in ["laporan", "pptx", "ppt", "slide", "unduh", "download", "paparan"]):
            await self.handle_laporan(chat_id)
            return

        # Deteksi balai
        if any(k in lower for k in ["balai", "wilker", "upt", "daerah", "sebaran"]):
            await self.handle_balai(chat_id)
            return

        # Deteksi kata "cari" saja
        if lower in ["cari", "cari kps", "carikps", "search", "find"]:
            await self.handle_search_kps(chat_id, "")
            return

        # Fallback pesan tidak dikenal
        fallback_text = (
            f"Maaf <b>{html.escape(first_name)}</b>, saya belum memahami pesan:\n"
            f"<i>\"{html.escape(text_msg[:100])}\"</i>\n\n"
            "Silakan gunakan tombol menu interaktif di bawah atau ketik perintah:\n"
            "• <b>/status</b> — Cek titik panas & status siaga hari ini\n"
            "• <b>/peringatandini</b> — Cek KPS terbakar ulang & ancaman baru\n"
            "• <b>/cari [nama KPS]</b> — Cari data profil & titik panas KPS\n"
            "• <b>/laporan</b> — Unduh berkas presentasi PPTX\n"
            "• <b>/balai</b> — Sebaran per Balai PS\n"
            "• <b>/help</b> — Panduan lengkap"
        )
        await self.send_message(chat_id, fallback_text, reply_markup=self._get_main_keyboard())

    # =========================================================================
    # UPDATE DISPATCHER
    # =========================================================================

    async def process_update(self, update: dict[str, Any]) -> None:
        """Memproses satu update dari Telegram."""
        # 1. Menangani Callback Query dari Inline Keyboard
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb.get("id")
            cb_data = cb.get("data")
            message = cb.get("message") or {}
            chat_id = (message.get("chat") or {}).get("id")
            from_user = cb.get("from") or {}
            first_name = from_user.get("first_name", "User")

            if cb_id:
                await self.answer_callback_query(cb_id)

            if not chat_id or not cb_data:
                return

            if cb_data == "cmd_status":
                await self.handle_status(chat_id)
            elif cb_data == "cmd_ew":
                await self.handle_early_warning(chat_id)
            elif cb_data == "cmd_laporan":
                await self.handle_laporan(chat_id)
            elif cb_data == "cmd_balai":
                await self.handle_balai(chat_id)
            elif cb_data == "cmd_cari":
                await self.handle_search_kps(chat_id, "")
            elif cb_data == "cmd_id":
                await self.handle_id(chat_id, from_user)
            return

        # 2. Menangani Pesan Masuk Teks
        if "message" in update:
            msg = update["message"]
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            from_user = msg.get("from") or {}
            first_name = from_user.get("first_name", "User")
            text = (msg.get("text") or "").strip()

            if not chat_id or not text:
                return

            # Perintah berbasis Command
            cmd = text.split()[0].lower().split("@")[0]  # Menghilangkan @Etaseneubot jika di grup

            if cmd == "/start":
                await self.handle_start(chat_id, first_name)
            elif cmd in ("/help", "/bantuan"):
                await self.handle_help(chat_id)
            elif cmd in ("/status", "/ringkasan", "/hotspot"):
                await self.handle_status(chat_id)
            elif cmd in ("/peringatandini", "/reburn", "/ew"):
                await self.handle_early_warning(chat_id)
            elif cmd in ("/laporan", "/pptx", "/unduh"):
                await self.handle_laporan(chat_id)
            elif cmd in ("/balai", "/wilker"):
                await self.handle_balai(chat_id)
            elif cmd in ("/cari", "/carikps", "/kps", "/search", "/find"):
                parts = text.split(maxsplit=1)
                search_query = parts[1].strip() if len(parts) > 1 else ""
                await self.handle_search_kps(chat_id, search_query)
            elif cmd in ("/id", "/chatid", "/whoami"):
                await self.handle_id(chat_id, from_user)
            else:
                await self.handle_unknown_or_text(chat_id, text, first_name)

    # =========================================================================
    # POLLING LOOP
    # =========================================================================

    async def polling_loop(self) -> None:
        """Background loop long-polling getUpdates dari Telegram API."""
        if not self.is_configured:
            logger.info("TELEGRAM_BOT: Bot token belum disetel, polling dinonaktifkan.")
            return

        logger.info("TELEGRAM_BOT: Memulai long-polling listener untuk publik...")
        self._running = True

        backoff = 1.0

        async with httpx.AsyncClient(timeout=30.0) as client:
            while self._running:
                try:
                    url = f"https://api.telegram.org/bot{self.token}/getUpdates"
                    params: dict[str, Any] = {
                        "offset": self._last_offset,
                        "timeout": 15,
                        "allowed_updates": ["message", "callback_query"],
                    }

                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("ok"):
                            updates = data.get("result", [])
                            for upd in updates:
                                upd_id = upd.get("update_id", 0)
                                self._last_offset = max(self._last_offset, upd_id + 1)
                                try:
                                    await self.process_update(upd)
                                except Exception as e:
                                    logger.error("Error saat memproses update Telegram %s: %s", upd_id, e)
                        backoff = 1.0
                    else:
                        logger.warning("getUpdates HTTP %s: %s", resp.status_code, resp.text)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 1.5, 30.0)

                except asyncio.CancelledError:
                    logger.info("TELEGRAM_BOT: Polling loop dibatalkan (shutdown).")
                    break
                except Exception as e:
                    logger.error("Exception pada Telegram polling loop: %s", e)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.5, 30.0)

        self._running = False
        logger.info("TELEGRAM_BOT: Polling loop berhenti.")

    def start_polling(self) -> asyncio.Task | None:
        """Mulai polling loop sebagai background asyncio Task."""
        if not self.is_configured:
            return None
        if self._poll_task and not self._poll_task.done():
            return self._poll_task
        self._poll_task = asyncio.create_task(self.polling_loop())
        return self._poll_task

    def stop_polling(self) -> None:
        """Hentikan background polling loop."""
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
