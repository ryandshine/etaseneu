"""Verifikasi token widget Cloudflare Turnstile di halaman login.

Dipakai dari app/api/auth.py::login(). Aktif hanya kalau
Settings.turnstile_secret_key terisi -- kalau kosong, endpoint login tidak
pernah memanggil modul ini (fail-open, lihat komentar di config.py).
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(
    token: str, *, secret: str, remote_ip: str | None = None
) -> bool:
    """Tanya server Cloudflare apakah `token` dari widget itu sah.

    Return True HANYA kalau Cloudflare menjawab ``success: true``. Semua
    bentuk kegagalan lain -- jaringan putus, timeout, status non-2xx, body
    bukan JSON yang diharapkan -- di-map ke False supaya login menolak (bukan
    meloloskan) percobaan yang tidak bisa dipastikan manusiawi.
    """
    payload = {"secret": secret, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    timeout = get_settings().request_timeout_seconds
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(TURNSTILE_VERIFY_URL, data=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # Jangan echo `secret` -- cukup jenis errornya.
        logger.warning("Verifikasi Turnstile tidak bisa diselesaikan: %s", exc)
        return False

    if not isinstance(body, dict) or not body.get("success"):
        logger.info(
            "Turnstile menolak token (error-codes: %s)",
            body.get("error-codes") if isinstance(body, dict) else "?",
        )
        return False
    return True
