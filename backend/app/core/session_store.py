"""Shared dependency for session-aware authentication.

Kept separate from ``api.auth`` so the authentication dependencies and the
login/user-management routes can use the same dependency object. This also
lets tests override the application user store without importing API modules
back into the auth core.
"""

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


def get_auth_store() -> PostgresStore:
    """Return the configured user/session store.

    The caller decides whether an unavailable database is a hard error. JWT
    validation can still work in the small preview/test deployments where the
    database is intentionally disabled.
    """

    return PostgresStore(get_settings().database_url)
