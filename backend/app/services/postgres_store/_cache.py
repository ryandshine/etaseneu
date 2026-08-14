"""Cache generik berbasis tabel (dipakai endpoint yang mahal dihitung ulang)."""

from datetime import datetime, timedelta, timezone

from ._base import Json, _safe_json


class _CacheMixin:
    def read_cache_entry(self, key: str) -> list[dict] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload, expires_at
                    FROM api_cache_entries
                    WHERE cache_key = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()

        if not row:
            return None

        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            return None

        payload = _safe_json(row.get("payload"), [])
        return payload if isinstance(payload, list) else None

    def write_cache_entry(self, key: str, payload: list[dict], ttl_hours: int) -> None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO api_cache_entries (cache_key, payload, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (cache_key)
                    DO UPDATE SET
                        payload = EXCLUDED.payload,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = NOW()
                    """,
                    (key, Json(payload), expires_at),
                )

    def clear_cache_entries(self) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM api_cache_entries", ())
                return int(getattr(cur, "rowcount", 0) or 0)
