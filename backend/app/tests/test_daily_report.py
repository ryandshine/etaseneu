"""Unit tests untuk DailyReportService dan endpoint laporan harian PPTX Telegram."""

import io
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from pptx.util import Inches

from app.main import create_app
from app.services.daily_report_service import DailyReportService, _resolve_bps


def test_resolve_bps():
    # Test valid BPS provided
    assert _resolve_bps("Balai PS Palembang", "Sumatera Selatan") == "Balai PS Palembang"
    # Test fallback by province
    assert _resolve_bps(None, "Riau") == "Balai PS Kampar"
    assert _resolve_bps("—", "Jawa Barat") == "Balai PS Bogor"
    assert _resolve_bps("", "Kalimantan Barat") == "Balai PS Banjarbaru"
    assert _resolve_bps(None, "Unknown Province") == "Balai PS Terkait"


def test_generate_daily_hotspot_pptx():
    service = DailyReportService()
    dummy_data = {
        "report_date": "2026-09-18",
        "report_date_str": "Jumat, 18 September 2026",
        "report_time_str": "07:00 WIB",
        "time_window_str": "17/09/2026 07:00 s.d. 18/09/2026 07:00 WIB",
        "total_hotspots": 12,
        "high_count": 4,
        "medium_count": 6,
        "low_count": 2,
        "max_frp": 65.4,
        "avg_frp": 24.1,
        "status_siaga": "SIAGA DARURAT",
        "siaga_color": None,
        "balai_list": [
            {
                "name": "Balai PS Palembang",
                "high_count": 3,
                "medium_count": 4,
                "low_count": 1,
                "total_priority": 7,
                "priority_score": 10,
                "priority_status": "Prioritas Sedang",
                "max_frp": 65.4,
                "agency_count": 2,
            },
            {
                "name": "Balai PS Banjarbaru",
                "high_count": 1,
                "medium_count": 2,
                "low_count": 1,
                "total_priority": 3,
                "priority_score": 4,
                "priority_status": "Prioritas Rendah",
                "max_frp": 22.0,
                "agency_count": 1,
            },
        ],
        "kps_list": [
            {
                "name": "KTH TELLA SERASAN",
                "bps": "Balai PS Palembang",
                "wilayah": "Desa Teluk Limau, Gelumbang, Muara Enim",
                "high_count": 3,
                "medium_count": 2,
                "low_count": 0,
                "total": 5,
                "priority_score": 8,
                "priority_status": "Prioritas Sedang",
                "max_frp": 65.4,
                "latitude": -3.095974,
                "longitude": 104.376196,
                "google_maps_url": "https://www.google.com/maps?q=-3.095974,104.376196",
            }
        ],
        "has_data": True,
    }

    pptx_bytes = service.generate_daily_hotspot_pptx(dummy_data)
    assert isinstance(pptx_bytes, bytes)
    assert len(pptx_bytes) > 10000

    # Parse generated pptx with python-pptx
    prs = Presentation(io.BytesIO(pptx_bytes))
    assert len(prs.slides) == 6
    assert abs(prs.slide_width - Inches(13.333)) < 1000
    assert abs(prs.slide_height - Inches(7.5)) < 1000


def test_collect_daily_hotspot_data():
    service = DailyReportService()
    data = service.collect_daily_hotspot_data(target_date=date(2026, 9, 18))
    assert "total_hotspots" in data
    assert "high_count" in data
    assert "medium_count" in data
    assert "balai_list" in data
    assert "kps_list" in data
    assert "status_siaga" in data


@pytest.mark.anyio
async def test_send_daily_telegram_report_mocked():
    service = DailyReportService()

    # Missing token test
    res = await service.send_daily_telegram_report(bot_token="", chat_id="")
    assert res["success"] is False
    assert "belum dikonfigurasi" in res["error"]

    from unittest.mock import MagicMock

    # Mocked successful post
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 999},
        }
        mock_post.return_value = mock_response

        res = await service.send_daily_telegram_report(
            bot_token="test_token",
            chat_id="123456",
            target_date=date(2026, 9, 18),
            force=True,
        )
        assert res["success"] is True
        assert res["message_id"] == 999
        assert "filename" in res


def test_api_daily_report_endpoints():
    app = create_app()
    client = TestClient(app)
    admin_headers = {"X-Admin-Key": "admin@5150"}

    # 1. Preview
    resp_prev = client.get("/api/notifications/daily-report/preview", headers=admin_headers)
    assert resp_prev.status_code == 200
    data = resp_prev.json()
    assert "total_hotspots" in data
    assert "balai_list" in data

    # 2. Download PPTX
    resp_dl = client.get("/api/notifications/daily-report/download", headers=admin_headers)
    assert resp_dl.status_code == 200
    assert "presentation" in resp_dl.headers["content-type"]
    assert len(resp_dl.content) > 10000

    # 3. Trigger Send (Mocked)
    with patch("app.services.daily_report_service.DailyReportService.send_daily_telegram_report") as mock_send:
        mock_send.return_value = {
            "success": True,
            "message_id": 123,
            "filename": "test.pptx",
        }
        resp_send = client.post(
            "/api/notifications/daily-report/send",
            json={"force": True},
            headers=admin_headers,
        )
        assert resp_send.status_code == 200
        assert resp_send.json()["success"] is True
