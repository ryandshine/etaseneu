"""Koneksi database + helper JSON yang dipakai semua mixin di paket ini."""

import json
from collections.abc import Iterable
from contextlib import contextmanager
from typing import Any

try:
    from psycopg import Connection, connect
    from psycopg.rows import dict_row
    from psycopg.types.json import Json

    PSYCOPG_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised in environments without psycopg
    Connection = Any  # type: ignore[assignment]
    connect = None
    dict_row = None

    def Json(value: object) -> object:  # type: ignore[misc]
        return value

    PSYCOPG_AVAILABLE = False


def _safe_json(value: object, fallback: object) -> object:
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return value


class _ConnectionMixin:
    """Lifecycle koneksi psycopg -- dasar yang dipakai semua mixin domain lain."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url.strip()
        self._available: bool | None = None

    @property
    def enabled(self) -> bool:
        if not self.database_url or not PSYCOPG_AVAILABLE:
            return False

        if self._available is None:
            self._available = self._probe_connection()

        return self._available

    def _probe_connection(self) -> bool:
        if connect is None:
            return False
        try:
            with connect(
                self.database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=2,
            ):
                return True
        except Exception:
            return False

    @contextmanager
    def connection(self) -> Iterable[Connection]:
        if not self.enabled:
            raise RuntimeError("database storage is not available")

        assert connect is not None
        with connect(
            self.database_url,
            autocommit=True,
            row_factory=dict_row,
            connect_timeout=2,
        ) as conn:
            yield conn
