"""Akun aplikasi (login seluruh sistem) -- terpisah dari ADMIN_API_KEY.

ADMIN_API_KEY (lihat core/auth.py::verify_admin_key) melindungi aksi admin
per-endpoint (upload geojson, trigger sync). Tabel di sini adalah gerbang
LOGIN aplikasi itu sendiri: satu baris per akun, dengan role admin/user.
"""

from datetime import datetime, timezone

from ._base import Connection


class _UserAccountMixin:
    def _ensure_app_users_table(self, conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

    def ensure_seed_admin(self, *, username: str, password_hash: str) -> None:
        """Kalau tabel app_users masih kosong, buat satu akun admin awal.

        Dipanggil di awal tiap login supaya kredensial APP_LOGIN_PASSWORD
        yang sudah dipakai produksi (admin/context7) tetap jalan setelah
        migrasi ke tabel user sungguhan -- tanpa perlu langkah manual di
        server.
        """
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM app_users")
                row = cur.fetchone()
                count = (row["n"] if isinstance(row, dict) else row[0]) if row else 0
                if count:
                    return
                cur.execute(
                    """
                    INSERT INTO app_users (username, password_hash, role)
                    VALUES (%s, %s, 'admin')
                    ON CONFLICT (username) DO NOTHING
                    """,
                    (username, password_hash),
                )

    def get_user_by_username(self, username: str) -> dict | None:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, password_hash, role, created_at "
                    "FROM app_users WHERE username = %s",
                    (username,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, role, created_at FROM app_users "
                    "ORDER BY created_at ASC"
                )
                return [dict(row) for row in cur.fetchall()]

    def create_user(self, *, username: str, password_hash: str, role: str) -> dict:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_users (username, password_hash, role)
                    VALUES (%s, %s, %s)
                    RETURNING id, username, role, created_at
                    """,
                    (username, password_hash, role),
                )
                return dict(cur.fetchone())

    def count_admins(self) -> int:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM app_users WHERE role = 'admin'")
                row = cur.fetchone()
                return (row["n"] if isinstance(row, dict) else row[0]) if row else 0

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, username, role, created_at FROM app_users WHERE id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def update_user_role(self, user_id: int, role: str) -> dict | None:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE app_users SET role = %s, updated_at = %s
                    WHERE id = %s
                    RETURNING id, username, role, created_at
                    """,
                    (role, datetime.now(timezone.utc), user_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def update_user_password(self, user_id: int, password_hash: str) -> bool:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE app_users SET password_hash = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (password_hash, datetime.now(timezone.utc), user_id),
                )
                return cur.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM app_users WHERE id = %s", (user_id,))
                return cur.rowcount > 0
