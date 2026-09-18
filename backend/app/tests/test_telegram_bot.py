"""Unit tests untuk TelegramBotService (layanan interaktif publik)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.telegram_bot_service import TelegramBotService


@pytest.fixture
def mock_report_service():
    service = MagicMock()
    service.collect_daily_hotspot_data.return_value = {
        "report_date_str": "Jumat, 18 September 2026",
        "time_window_str": "17 Sep 2026, 07:00 - 18 Sep 2026, 07:00 WIB",
        "status_siaga": "SIAGA DARURAT",
        "total_hotspots": 6061,
        "high_count": 120,
        "medium_count": 450,
        "low_count": 5491,
        "yesterday_total": 4500,
        "trend_icon": "🔺",
        "delta_pct": 34.7,
        "trend_label": "MENINGKAT TAJAM",
        "max_frp": 120.5,
        "avg_frp": 32.1,
        "peak_day_hour": 13,
        "balai_list": [
            {
                "name": "Balai PS Kampar",
                "total_priority": 150,
                "high_count": 40,
                "medium_count": 110,
                "priority_status": "Prioritas Tinggi",
                "max_frp": 120.5,
                "priority_score": 190,
            }
        ],
        "burned_kps_list": [
            {
                "lembaga": "LPHD DANAU PALUH LESTARI",
                "wilker_bps": "Balai PS Banjarbaru",
                "hotspots_today": 23,
                "hotspots_today_strict_reburn": 1,
                "ftri_score": 74.2,
                "google_maps_url": "https://www.google.com/maps?q=-2.81,110.76",
                "ew_category": "Strict Re-burn",
            }
        ],
        "ew_new_list": [
            {
                "lembaga": "GAPOKTANHUT BERKAH",
                "wilker_bps": "Balai PS Kampar",
                "hotspots_today": 77,
                "ftri_score": 100.0,
                "google_maps_url": "https://www.google.com/maps?q=0.5,101.5",
                "ew_category": "Peringatan Dini Baru",
            }
        ],
        "early_warning_summary": {
            "strict_reburn_kps": 4,
            "expanding_kps": 23,
            "ew_new_kps": 190,
        },
        "total_ew_active_today": 217,
    }
    service.generate_daily_hotspot_pptx.return_value = b"PK\x03\x04fake_pptx_content"
    return service


@pytest.mark.anyio
async def test_telegram_bot_send_message_mocked():
    bot = TelegramBotService()
    bot.token = "fake_token_123"

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 101}}
        mock_post.return_value = mock_resp

        res = await bot.send_message(chat_id="12345", text="Hello world")
        assert res["ok"] is True
        assert res["result"]["message_id"] == 101


@pytest.mark.anyio
async def test_telegram_bot_send_document_mocked():
    bot = TelegramBotService()
    bot.token = "fake_token_123"

    with patch("httpx.AsyncClient.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "result": {"message_id": 102}}
        mock_post.return_value = mock_resp

        res = await bot.send_document(
            chat_id="12345",
            document_bytes=b"dummy_bytes",
            filename="report.pptx",
            caption="Test caption",
        )
        assert res["ok"] is True
        assert res["result"]["message_id"] == 102


@pytest.mark.anyio
async def test_handle_commands(mock_report_service):
    bot = TelegramBotService(report_service=mock_report_service)
    bot.token = "fake_token_123"

    with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send_msg, \
         patch.object(bot, "send_document", new_callable=AsyncMock) as mock_send_doc, \
         patch.object(bot, "send_chat_action", new_callable=AsyncMock):

        # 1. /start
        await bot.handle_start(chat_id="111", first_name="Apud")
        mock_send_msg.assert_called_once()
        assert "Halo, Apud" in mock_send_msg.call_args[0][1]

        # 2. /status
        mock_send_msg.reset_mock()
        await bot.handle_status(chat_id="111")
        assert "SIAGA DARURAT" in mock_send_msg.call_args[0][1]
        assert "6,061 titik" in mock_send_msg.call_args[0][1]

        # 3. /peringatandini
        mock_send_msg.reset_mock()
        await bot.handle_early_warning(chat_id="111")
        assert "LPHD DANAU PALUH LESTARI" in mock_send_msg.call_args[0][1]
        assert "GAPOKTANHUT BERKAH" in mock_send_msg.call_args[0][1]

        # 4. /balai
        mock_send_msg.reset_mock()
        await bot.handle_balai(chat_id="111")
        assert "Kampar" in mock_send_msg.call_args[0][1]

        # 5. /id
        mock_send_msg.reset_mock()
        await bot.handle_id(chat_id="111", from_user={"id": 111, "first_name": "Apud", "username": "apudhaha"})
        assert "111" in mock_send_msg.call_args[0][1]
        assert "@apudhaha" in mock_send_msg.call_args[0][1]

        # 6. /laporan
        await bot.handle_laporan(chat_id="111")
        mock_send_doc.assert_called_once()
        assert "Laporan_Harian_Hotspot_KPS" in mock_send_doc.call_args[1]["filename"]


@pytest.mark.anyio
async def test_process_update_dispatch(mock_report_service):
    bot = TelegramBotService(report_service=mock_report_service)
    bot.token = "fake_token_123"

    with patch.object(bot, "handle_start", new_callable=AsyncMock) as mock_start, \
         patch.object(bot, "handle_status", new_callable=AsyncMock) as mock_status, \
         patch.object(bot, "answer_callback_query", new_callable=AsyncMock):

        # Update text command /start
        upd_start = {
            "update_id": 1,
            "message": {
                "chat": {"id": 123},
                "from": {"first_name": "Ryan"},
                "text": "/start",
            },
        }
        await bot.process_update(upd_start)
        mock_start.assert_called_once_with(123, "Ryan")

        # Update callback query cmd_status
        upd_cb = {
            "update_id": 2,
            "callback_query": {
                "id": "cb_99",
                "data": "cmd_status",
                "message": {"chat": {"id": 123}},
                "from": {"first_name": "Ryan"},
            },
        }
        await bot.process_update(upd_cb)
        mock_status.assert_called_once_with(123)


@pytest.mark.anyio
async def test_handle_search_kps():
    bot = TelegramBotService()
    bot.token = "fake_token_123"

    # 1. Search empty query (guidance)
    with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send_msg:
        await bot.handle_search_kps(chat_id="111", query="")
        mock_send_msg.assert_called_once()
        assert "PENCARIAN DATA KPS" in mock_send_msg.call_args[0][1]
        assert "/cari" in mock_send_msg.call_args[0][1]

    # 2. Search with results found
    fake_kps = [
        {
            "id": 292491,
            "lembaga": "KTH TELLA SERASAN",
            "skema": "HKm",
            "nama_desa": "Teluk Limau",
            "nama_kec": "Gelumbang",
            "nama_kab": "Muara Enim",
            "nama_prov": "Sumatera Selatan",
            "wilker_bps": "Balai PS Wilayah Sumatera",
            "no_sk": "SK.4284/MENLHK-PSKL/PKPS/PSL.0/6/2018",
            "tgl_sk": "2018-06-25",
            "luas_ha": 5800.0,
            "lat": -3.095974,
            "lon": 104.376196,
            "burned_area_ha": 12.5,
            "hotspot_count_today": 3,
        }
    ]
    with patch.object(bot, "_search_kps_in_db", return_value=fake_kps), \
         patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send_msg, \
         patch.object(bot, "send_chat_action", new_callable=AsyncMock):
        await bot.handle_search_kps(chat_id="111", query="tella")
        mock_send_msg.assert_called_once()
        msg_text = mock_send_msg.call_args[0][1]
        assert "KTH TELLA SERASAN" in msg_text
        assert "3 titik panas aktif" in msg_text
        assert "12.50 Ha" in msg_text
        assert "Google Maps" in msg_text
        assert "view=kps" in msg_text

    # 3. Search not found
    with patch.object(bot, "_search_kps_in_db", return_value=[]), \
         patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send_msg, \
         patch.object(bot, "send_chat_action", new_callable=AsyncMock):
        await bot.handle_search_kps(chat_id="111", query="nonexistentkpsxyz")
        mock_send_msg.assert_called_once()
        assert "Data KPS tidak ditemukan" in mock_send_msg.call_args[0][1]


@pytest.mark.anyio
async def test_search_dispatch():
    bot = TelegramBotService()
    bot.token = "fake_token_123"

    with patch.object(bot, "handle_search_kps", new_callable=AsyncMock) as mock_search, \
         patch.object(bot, "answer_callback_query", new_callable=AsyncMock):

        # Command /cari
        upd_cmd = {
            "update_id": 10,
            "message": {
                "chat": {"id": 123},
                "from": {"first_name": "Ryan"},
                "text": "/cari Tella Serasan",
            },
        }
        await bot.process_update(upd_cmd)
        mock_search.assert_called_once_with(123, "Tella Serasan")

        # Callback cmd_cari
        mock_search.reset_mock()
        upd_cb = {
            "update_id": 11,
            "callback_query": {
                "id": "cb_100",
                "data": "cmd_cari",
                "message": {"chat": {"id": 123}},
                "from": {"first_name": "Ryan"},
            },
        }
        await bot.process_update(upd_cb)
        mock_search.assert_called_once_with(123, "")

        # Natural language: "cari kps lingat"
        mock_search.reset_mock()
        upd_natural = {
            "update_id": 12,
            "message": {
                "chat": {"id": 123},
                "from": {"first_name": "Ryan"},
                "text": "cari kps lingat",
            },
        }
        await bot.process_update(upd_natural)
        mock_search.assert_called_once_with(123, "lingat")

