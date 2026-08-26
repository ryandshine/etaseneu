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

    def _ensure_app_sessions_table(self, conn: Connection) -> None:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_sessions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
                    token_hash TEXT UNIQUE NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL,
                    revoked_at TIMESTAMPTZ,
                    user_agent TEXT,
                    ip_address TEXT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_app_sessions_user_active "
                "ON app_sessions (user_id, expires_at) WHERE revoked_at IS NULL"
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

    def create_session(
        self,
        *,
        user_id: int,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> None:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            self._ensure_app_sessions_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_sessions
                        (user_id, token_hash, created_at, last_seen_at, expires_at, user_agent, ip_address)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (token_hash) DO NOTHING
                    """,
                    (user_id, token_hash, created_at, created_at, expires_at, user_agent, ip_address),
                )

    def validate_session(self, token_hash: str, user_id: int) -> bool:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            self._ensure_app_sessions_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE app_sessions AS sessions
                    SET last_seen_at = NOW()
                    FROM app_users AS users
                    WHERE sessions.token_hash = %s AND sessions.user_id = %s
                      AND sessions.user_id = users.id
                      AND sessions.revoked_at IS NULL AND sessions.expires_at > NOW()
                    RETURNING users.username, users.role
                    """,
                    (token_hash, user_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def revoke_session(self, token_hash: str, user_id: int) -> bool:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            self._ensure_app_sessions_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE app_sessions SET revoked_at = NOW()
                    WHERE token_hash = %s AND user_id = %s AND revoked_at IS NULL
                    """,
                    (token_hash, user_id),
                )
                return cur.rowcount > 0

    def revoke_user_sessions(self, user_id: int, except_token_hash: str | None = None) -> int:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            self._ensure_app_sessions_table(conn)
            with conn.cursor() as cur:
                if except_token_hash:
                    cur.execute(
                        """
                        UPDATE app_sessions SET revoked_at = NOW()
                        WHERE user_id = %s AND token_hash <> %s
                          AND revoked_at IS NULL AND expires_at > NOW()
                        """,
                        (user_id, except_token_hash),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE app_sessions SET revoked_at = NOW()
                        WHERE user_id = %s AND revoked_at IS NULL AND expires_at > NOW()
                        """,
                        (user_id,),
                    )
                return cur.rowcount

    def count_active_sessions(self, user_id: int) -> int:
        with self.connection() as conn:
            self._ensure_app_users_table(conn)
            self._ensure_app_sessions_table(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS n FROM app_sessions
                    WHERE user_id = %s AND revoked_at IS NULL AND expires_at > NOW()
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
                return int(row["n"] if isinstance(row, dict) else row[0]) if row else 0
