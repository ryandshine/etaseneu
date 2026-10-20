"""Helper ringan untuk token & status error Telegram Bot API (tanpa dependensi internal)."""

from __future__ import annotations

import re

# Token asli: "<bot_id numerik>:<35 karakter [A-Za-z0-9_-]>". Longgar di sisi panjang
# supaya variasi sah tidak ikut ditolak; token terpotong (mis. 18 karakter) tetap terdeteksi.
_BOT_TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")

# Status yang menandakan token/chat salah secara permanen -- mengulang tidak akan pernah berhasil.
PERMANENT_AUTH_STATUSES = frozenset({401, 403, 404})


def is_valid_bot_token_format(token: str | None) -> bool:
    return bool(_BOT_TOKEN_RE.match((token or "").strip()))


def describe_token_shape(token: str | None) -> str:
    """Ringkasan aman (tanpa membocorkan isi) untuk log: panjang total & panjang bagian rahasia."""
    value = (token or "").strip()
    if not value:
        return "kosong"
    head, sep, tail = value.partition(":")
    if not sep:
        return f"panjang={len(value)}, tanpa pemisah ':'"
    return f"panjang={len(value)}, bagian rahasia={len(tail)} karakter (normalnya 35)"
