"""Ketahanan bot Telegram terhadap token ditolak (401) -- tanpa jaringan & tanpa DB."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.core.telegram_token import describe_token_shape, is_valid_bot_token_format
from app.services.daily_report_service import (
    MAX_DAILY_REPORT_ATTEMPTS,
    next_retry_delay_seconds,
)
from app.services.telegram_bot_service import TelegramBotService

VALID = "1234567890:" + "A" * 35
TRUNCATED = "1234567890:abc"  # bagian rahasia terpotong


def test_token_format():
    assert is_valid_bot_token_format(VALID)
    assert not is_valid_bot_token_format(TRUNCATED)
    assert not is_valid_bot_token_format("")
    assert not is_valid_bot_token_format(None)
    assert not is_valid_bot_token_format("tanpa-pemisah")


def test_describe_token_shape_tidak_membocorkan_isi():
    out = describe_token_shape(TRUNCATED)
    assert "abc" not in out and "1234567890" not in out
    assert "3 karakter" in out


def test_next_retry_delay():
    assert next_retry_delay_seconds({"success": False, "permanent": True}, 1) is None
    assert next_retry_delay_seconds({"success": False}, 1) == 600
    assert next_retry_delay_seconds({"success": False}, 2) == 1200
    assert next_retry_delay_seconds({"success": False}, 4) == 3600
    assert next_retry_delay_seconds({"success": False}, MAX_DAILY_REPORT_ATTEMPTS) is None


def _bot(token: str) -> TelegramBotService:
    settings = MagicMock()
    settings.telegram_bot_token = token
    settings.telegram_chat_id = ""
    return TelegramBotService(settings=settings, store=MagicMock(), report_service=MagicMock())


@pytest.mark.anyio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_polling_berhenti_saat_token_ditolak(status):
    bot = _bot(TRUNCATED)
    resp = MagicMock(status_code=status, text='{"ok":false}')
    with patch("httpx.AsyncClient.get", return_value=resp) as mock_get:
        # Sebelum perbaikan: loop tak pernah selesai (retry tiap 30 dtk) -> wait_for timeout.
        await asyncio.wait_for(bot.polling_loop(), timeout=2)
    assert mock_get.call_count == 1
    assert bot._running is False


@pytest.mark.anyio
async def test_polling_tetap_retry_pada_error_sementara():
    bot = _bot(VALID)
    calls = {"n": 0}

    async def fake_get(*_a, **_k):
        calls["n"] += 1
        if calls["n"] >= 2:
            bot._running = False
        return MagicMock(status_code=502, text="bad gateway")

    with patch("httpx.AsyncClient.get", side_effect=fake_get), patch("asyncio.sleep", return_value=None):
        await asyncio.wait_for(bot.polling_loop(), timeout=2)
    assert calls["n"] == 2  # 502 bukan permanen: loop lanjut mencoba lagi
