"""Penyimpanan hasil pencocokan yang berumur pendek, plus pembatas laju.

Kenapa ada: unduhan Excel/PDF butuh hasil pencocokan lagi. Tanpa ini, frontend
harus mengunggah ulang puluhan ribu baris untuk tiap unduhan. Hasil disimpan di
memori proses dengan TTL pendek -- tetap "sekali pakai" (tidak masuk database
permanen), tapi cukup untuk menyelesaikan alur unggah lalu unduh.

Konsekuensi yang disengaja: kalau proses backend restart, token hilang dan
pengguna harus mengunggah ulang. Itu wajar untuk alur sekali pakai, dan jauh
lebih baik daripada menumpuk berkas pengguna di server tanpa pemilik.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

RESULT_TTL_SECONDS = 60 * 60  # 1 jam
MAX_STORED_RESULTS = 50


@dataclass
class StoredResult:
    outcome: Any
    source_name: str
    created_at: float


class PointResultStore:
    def __init__(self, ttl_seconds: int = RESULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, StoredResult] = {}
        self._lock = threading.Lock()

    def _purge_expired(self, now: float) -> None:
        expired = [key for key, item in self._items.items() if now - item.created_at > self._ttl]
        for key in expired:
            self._items.pop(key, None)

        # Batas keras supaya lonjakan unggahan tidak menghabiskan memori.
        if len(self._items) > MAX_STORED_RESULTS:
            oldest = sorted(self._items.items(), key=lambda kv: kv[1].created_at)
            for key, _ in oldest[: len(self._items) - MAX_STORED_RESULTS]:
                self._items.pop(key, None)

    def put(self, outcome: Any, source_name: str) -> str:
        now = time.time()
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._purge_expired(now)
            self._items[token] = StoredResult(outcome, source_name, now)
        return token

    def get(self, token: str) -> StoredResult | None:
        now = time.time()
        with self._lock:
            self._purge_expired(now)
            return self._items.get(token)


class RateLimiter:
    """Pembatas laju per klien berbasis jendela geser, di memori proses.

    Sederhana dan cukup untuk satu instance. Kalau backend nanti diskalakan ke
    banyak proses, pembatas ini perlu pindah ke penyimpanan bersama -- catat
    itu sebelum menambah replika.
    """

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, client_key: str) -> tuple[bool, int]:
        """Kembalikan (diizinkan, detik_tunggu_kalau_ditolak)."""
        now = time.time()
        with self._lock:
            timestamps = [t for t in self._hits.get(client_key, []) if now - t < self._window]

            if len(timestamps) >= self._max:
                retry_after = int(self._window - (now - timestamps[0])) + 1
                self._hits[client_key] = timestamps
                return False, max(retry_after, 1)

            timestamps.append(now)
            self._hits[client_key] = timestamps

            # Buang klien yang sudah tidak aktif supaya dict tidak tumbuh terus.
            if len(self._hits) > 5000:
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self._window]:
                    self._hits.pop(key, None)

            return True, 0


point_result_store = PointResultStore()

# Unggahan diproses sinkron dan menyentuh database; batas ini menahan
# penyalahgunaan tanpa mengganggu pemakaian wajar.
upload_rate_limiter = RateLimiter(max_requests=10, window_seconds=10 * 60)
