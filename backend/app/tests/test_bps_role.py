import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.auth import router as auth_router
from app.core.auth import issue_token, decode_token
from app.core.session_store import get_auth_store


class _MemoryAuthStore:
    def __init__(self):
        self.enabled = True
        self.users = []
        self._next_id = 1
        self.sessions = {}

    def _ensure_app_users_table(self, conn=None):
        pass

    def ensure_seed_admin(self, username, password_hash):
        if not self.users:
            self.create_user(username=username, password_hash=password_hash, role="admin")

    def get_user_by_username(self, username: str):
        for u in self.users:
            if u["username"] == username:
                return dict(u)
        return None

    def get_user_by_id(self, user_id: int):
        for u in self.users:
            if u["id"] == user_id:
                return dict(u)
        return None

    def list_users(self):
        return [dict(u) for u in self.users]

    def create_user(self, *, username: str, password_hash: str, role: str, wilker_bps: str | None = None):
        user = {
            "id": self._next_id,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "wilker_bps": wilker_bps,
            "created_at": "2026-01-01T00:00:00Z",
        }
        self._next_id += 1
        self.users.append(user)
        return dict(user)

    def count_admins(self):
        return sum(1 for u in self.users if u["role"] == "admin")

    def update_user_role(self, user_id: int, role: str, wilker_bps: str | None = None):
        for u in self.users:
            if u["id"] == user_id:
                u["role"] = role
                u["wilker_bps"] = wilker_bps
                return dict(u)
        return None

    def update_user_password(self, user_id: int, password_hash: str):
        for u in self.users:
            if u["id"] == user_id:
                u["password_hash"] = password_hash
                return True
        return False

    def delete_user(self, user_id: int):
        self.users = [u for u in self.users if u["id"] != user_id]
        return True

    def create_session(self, *, user_id, token_hash, created_at, expires_at, user_agent, ip_address):
        self.sessions[token_hash] = {"user_id": user_id, "revoked": False}

    def validate_session(self, token_hash: str, user_id: int):
        sess = self.sessions.get(token_hash)
        if not sess or sess["revoked"]:
            return None
        user = self.get_user_by_id(user_id)
        if not user:
            return None
        return {"username": user["username"], "role": user["role"], "wilker_bps": user.get("wilker_bps")}

    def count_active_sessions(self, user_id: int):
        return sum(1 for s in self.sessions.values() if s["user_id"] == user_id and not s["revoked"])


@pytest.fixture
def auth_app():
    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    store = _MemoryAuthStore()
    app.dependency_overrides[get_auth_store] = lambda: store
    return app, store


def test_bps_token_claims_and_issue():
    token = issue_token(
        user_id=10,
        username="bpsdenpasar",
        role="bps",
        wilker_bps="Balai PS Denpasar",
    )
    claims = decode_token(token)
    assert claims.user_id == 10
    assert claims.username == "bpsdenpasar"
    assert claims.role == "bps"
    assert claims.wilker_bps == "Balai PS Denpasar"


def test_create_and_manage_bps_user(auth_app):
    app, store = auth_app
    client = TestClient(app)

    # Seed admin user
    admin_token = issue_token(user_id=1, username="admin", role="admin")
    store.create_user(username="admin", password_hash="hash", role="admin")

    # Create BPS user without wilker should fail
    resp = client.post(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"username": "bpsbali", "password": "password123", "role": "bps", "wilker_bps": ""},
    )
    assert resp.status_code == 400

    # Create BPS user with wilker should succeed
    resp = client.post(
        "/api/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "username": "bpsdenpasar",
            "password": "password123",
            "role": "bps",
            "wilker_bps": "Balai PS Denpasar",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "bpsdenpasar"
    assert data["role"] == "bps"
    assert data["wilker_bps"] == "Balai PS Denpasar"

    # List users includes wilker_bps
    list_resp = client.get("/api/auth/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert list_resp.status_code == 200
    users = list_resp.json()
    bps_user = next(u for u in users if u["username"] == "bpsdenpasar")
    assert bps_user["wilker_bps"] == "Balai PS Denpasar"
