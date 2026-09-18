"""Penyimpanan riwayat notifikasi peringatan hotspot."""

from datetime import datetime, timezone
from typing import Any

from ._base import Connection, Json, _safe_json


class _NotificationMixin:
    def _ensure_hotspot_notifications_table(self, conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hotspot_notifications (
                    id BIGSERIAL PRIMARY KEY,
                    notification_type TEXT NOT NULL DEFAULT 'hotspot_new',
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    hotspot_count INTEGER NOT NULL DEFAULT 0,
                    severity TEXT NOT NULL DEFAULT 'warning',
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS hotspot_notifications_created_at_idx
                    ON hotspot_notifications (created_at DESC)
                """
            )

    def save_notification(
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
        if created_at is None:
            created_at = datetime.now(timezone.utc)
        meta_dict = metadata or {}

        with self.connection() as conn:
            self._ensure_hotspot_notifications_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hotspot_notifications (
                        notification_type,
                        title,
                        message,
                        hotspot_count,
                        severity,
                        metadata,
                        created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, notification_type, title, message, hotspot_count, severity, metadata, created_at
                    """,
                    (
                        notification_type,
                        title,
                        message,
                        hotspot_count,
                        severity,
                        Json(meta_dict),
                        created_at,
                    ),
                )
                row = cur.fetchone()
                return {
                    "id": str(row["id"]),
                    "type": row["notification_type"],
                    "title": row["title"],
                    "message": row["message"],
                    "hotspot_count": int(row["hotspot_count"]),
                    "severity": row["severity"],
                    "metadata": _safe_json(row["metadata"], {}),
                    "created_at": row["created_at"].isoformat() if row["created_at"] else created_at.isoformat(),
                }

    def list_notifications(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connection() as conn:
            self._ensure_hotspot_notifications_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, notification_type, title, message, hotspot_count, severity, metadata, created_at
                    FROM hotspot_notifications
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "id": str(row["id"]),
                    "type": row["notification_type"],
                    "title": row["title"],
                    "message": row["message"],
                    "hotspot_count": int(row["hotspot_count"]),
                    "severity": row["severity"],
                    "metadata": _safe_json(row["metadata"], {}),
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                }
            )
        return results
