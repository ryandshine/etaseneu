import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import require_admin_key
from app.core.config import get_settings


@pytest.fixture
def protected_app(monkeypatch):
    """App kecil khusus untuk test dependency-nya sendiri, terlepas dari
    endpoint asli mana pun -- fokus hanya pada perilaku require_admin_key."""
    app = FastAPI()

    @app.post("/protected")
    async def protected_route(_: None = Depends(require_admin_key)) -> dict[str, bool]:
        return {"ok": True}

    def _client_with_key(key: str) -> None:
        monkeypatch.setenv("ADMIN_API_KEY", key)
        get_settings.cache_clear()

    yield app, _client_with_key
    get_settings.cache_clear()


def test_fails_closed_when_admin_key_not_configured(protected_app, monkeypatch):
    app, set_key = protected_app
    # Diset kosong, bukan delenv: menghapus env var saja tidak cukup karena
    # Pydantic masih membaca backend/.env milik developer (yang biasanya
    # berisi ADMIN_API_KEY). Env var kosong menang atas isi .env, jadi test
    # ini menguji kode -- bukan konfigurasi lokal siapa pun yang menjalankannya.
    monkeypatch.setenv("ADMIN_API_KEY", "")
    get_settings.cache_clear()

    client = TestClient(app)
    response = client.post("/protected")

    assert response.status_code == 503


def test_rejects_missing_header_when_configured(protected_app):
    app, set_key = protected_app
    set_key("s3cret")

    client = TestClient(app)
    response = client.post("/protected")

    assert response.status_code == 401


def test_rejects_wrong_key(protected_app):
    app, set_key = protected_app
    set_key("s3cret")

    client = TestClient(app)
    response = client.post("/protected", headers={"X-Admin-Key": "wrong"})

    assert response.status_code == 401


def test_accepts_correct_key(protected_app):
    app, set_key = protected_app
    set_key("s3cret")

    client = TestClient(app)
    response = client.post("/protected", headers={"X-Admin-Key": "s3cret"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_verify_endpoint_uses_same_dependency(monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("ADMIN_API_KEY", "s3cret")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)

        assert client.post("/api/auth/verify").status_code == 401
        assert client.post("/api/auth/verify", headers={"X-Admin-Key": "wrong"}).status_code == 401
        ok = client.post("/api/auth/verify", headers={"X-Admin-Key": "s3cret"})
        assert ok.status_code == 200
        assert ok.json() == {"ok": True}
    finally:
        get_settings.cache_clear()


# --- /api/auth/login + Manajemen User (app_users, role admin/user) ---
#
# Endpoint-endpoint ini menulis kredensial login sungguhan ke database, dan
# proyek ini TIDAK punya database test terpisah (lihat CLAUDE.md bahaya #1).
# Karena itu app.api.auth.get_store() dibuat sebagai FastAPI dependency yang
# di-override lewat app.dependency_overrides ke FakeUserStore di bawah --
# test-test ini tidak pernah menyentuh Postgres produksi sungguhan.


class FakeUserStore:
    """Tiruan in-memory dari bagian postgres_store yang dipakai api/auth.py."""

    enabled = True

    def __init__(self):
        self._users: list[dict] = []
        self._next_id = 1

    def ensure_seed_admin(self, *, username: str, password_hash: str) -> None:
        if self._users:
            return
        self._users.append(
            {
                "id": self._next_id,
                "username": username,
                "password_hash": password_hash,
                "role": "admin",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        )
        self._next_id += 1

    def get_user_by_username(self, username: str) -> dict | None:
        return next((u for u in self._users if u["username"] == username), None)

    def get_user_by_id(self, user_id: int) -> dict | None:
        return next((u for u in self._users if u["id"] == user_id), None)

    def list_users(self) -> list[dict]:
        return list(self._users)

    def create_user(self, *, username: str, password_hash: str, role: str) -> dict:
        row = {
            "id": self._next_id,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        self._users.append(row)
        self._next_id += 1
        return row

    def update_user_role(self, user_id: int, role: str) -> dict | None:
        user = self.get_user_by_id(user_id)
        if user:
            user["role"] = role
        return user

    def update_user_password(self, user_id: int, password_hash: str) -> bool:
        user = self.get_user_by_id(user_id)
        if not user:
            return False
        user["password_hash"] = password_hash
        return True

    def delete_user(self, user_id: int) -> bool:
        before = len(self._users)
        self._users = [u for u in self._users if u["id"] != user_id]
        return len(self._users) < before

    def count_admins(self) -> int:
        return sum(1 for u in self._users if u["role"] == "admin")


@pytest.fixture
def auth_app(monkeypatch):
    """App nyata (create_app()) dengan get_store() di-override ke store
    palsu, dan APP_LOGIN_PASSWORD diset supaya seed admin awal jalan."""
    from app.api.auth import get_store
    from app.main import create_app

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "context7")
    get_settings.cache_clear()

    app = create_app()
    fake_store = FakeUserStore()
    app.dependency_overrides[get_store] = lambda: fake_store

    yield app, fake_store

    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_login_fails_closed_when_database_not_configured(monkeypatch):
    """503 (bukan 401) kalau store.enabled False -- get_store() sendiri
    yang melempar ini, tanpa override, jadi database_url asli dipakai."""
    from app.main import create_app

    monkeypatch.setenv("DATABASE_URL", "")
    get_settings.cache_clear()

    try:
        app = create_app()
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": "admin", "password": "context7"})
        assert response.status_code == 503
    finally:
        get_settings.cache_clear()


def test_login_rejects_unknown_user_when_nothing_seeded(monkeypatch):
    """APP_LOGIN_PASSWORD kosong + tabel kosong -> 401 (kredensial salah),
    BUKAN 503 -- 503 sekarang murni soal database tidak terkonfigurasi."""
    from app.api.auth import get_store
    from app.main import create_app

    monkeypatch.setenv("APP_LOGIN_PASSWORD", "")
    get_settings.cache_clear()

    app = create_app()
    app.dependency_overrides[get_store] = lambda: FakeUserStore()
    try:
        client = TestClient(app)
        response = client.post("/api/auth/login", json={"username": "admin", "password": "anything"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_login_seeds_admin_from_app_login_password_and_accepts_it(auth_app):
    app, _store = auth_app
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "context7"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["username"] == "admin"
    assert body["role"] == "admin"
    assert isinstance(body["token"], str) and body["token"]


def test_login_rejects_wrong_password(auth_app):
    app, _store = auth_app
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401


def test_login_rejects_unknown_username(auth_app):
    app, _store = auth_app
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"username": "someone-else", "password": "context7"})

    assert response.status_code == 401


def _login(client: TestClient, username: str = "admin", password: str = "context7") -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def test_user_management_endpoints_reject_missing_token(auth_app):
    app, _store = auth_app
    client = TestClient(app)

    assert client.get("/api/auth/users").status_code == 401
    assert client.post("/api/auth/users", json={"username": "x", "password": "abcdef"}).status_code == 401


def test_user_management_endpoints_reject_non_admin_role(auth_app):
    app, store = auth_app
    client = TestClient(app)
    admin_token = _login(client)

    # Admin membuat user biasa, lalu user itu login dan mencoba mengakses
    # endpoint manajemen user -- harus ditolak 403 (bukan 401, tokennya sah,
    # cuma rolenya tidak cukup).
    create = client.post(
        "/api/auth/users",
        json={"username": "operator", "password": "opsecret1", "role": "user"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create.status_code == 200, create.text

    user_token = _login(client, username="operator", password="opsecret1")
    response = client.get("/api/auth/users", headers={"Authorization": f"Bearer {user_token}"})
    assert response.status_code == 403


def test_admin_can_list_create_and_update_users(auth_app):
    app, store = auth_app
    client = TestClient(app)
    admin_token = _login(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    listing = client.get("/api/auth/users", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1  # cuma admin ter-seed

    created = client.post(
        "/api/auth/users",
        json={"username": "staff1", "password": "staffpass1", "role": "user"},
        headers=headers,
    )
    assert created.status_code == 200
    new_id = created.json()["id"]
    assert created.json()["role"] == "user"

    # Ganti role jadi admin
    updated = client.patch(f"/api/auth/users/{new_id}", json={"role": "admin"}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["role"] == "admin"

    # Ganti password -- login lama tetap gagal, password baru berhasil
    changed = client.patch(
        f"/api/auth/users/{new_id}", json={"password": "brandnewpass1"}, headers=headers
    )
    assert changed.status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "staff1", "password": "staffpass1"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "staff1", "password": "brandnewpass1"}
    ).status_code == 200


def test_create_user_rejects_duplicate_username(auth_app):
    app, store = auth_app
    client = TestClient(app)
    admin_token = _login(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.post(
        "/api/auth/users", json={"username": "admin", "password": "whatever1"}, headers=headers
    )
    assert response.status_code == 409


def test_create_user_rejects_short_password(auth_app):
    app, store = auth_app
    client = TestClient(app)
    admin_token = _login(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = client.post(
        "/api/auth/users", json={"username": "shorty", "password": "123"}, headers=headers
    )
    assert response.status_code == 400


def test_cannot_delete_own_account(auth_app):
    app, store = auth_app
    client = TestClient(app)
    admin_token = _login(client)
    headers = {"Authorization": f"Bearer {admin_token}"}
    admin_id = store.get_user_by_username("admin")["id"]

    response = client.delete(f"/api/auth/users/{admin_id}", headers=headers)

    assert response.status_code == 400
    assert store.get_user_by_id(admin_id) is not None


def test_cannot_delete_last_remaining_admin(auth_app):
    """Guard admin-terakhir hanya bisa dites lewat aktor LAIN (bukan diri
    sendiri, yang sudah tertangkap guard terpisah) -- kasus nyatanya: token
    JWT stateless, jadi admin yang BARU SAJA diturunkan ke role user masih
    punya token lama yang mengaku admin sampai kadaluarsa (24 jam). Token
    basi itu dipakai di sini untuk mencoba menghapus admin asli setelah
    dirinya sendiri diturunkan -- guard-nya harus tetap menolak."""
    app, store = auth_app
    client = TestClient(app)
    admin_token = _login(client)
    headers = {"Authorization": f"Bearer {admin_token}"}

    second = client.post(
        "/api/auth/users",
        json={"username": "admin2", "password": "adminpass1", "role": "admin"},
        headers=headers,
    ).json()
    # Token diambil SEBELUM diturunkan -- mensimulasikan token lama yang
    # belum kadaluarsa saat role pemiliknya sudah berubah di database.
    second_token = _login(client, username="admin2", password="adminpass1")
    second_headers = {"Authorization": f"Bearer {second_token}"}

    demote = client.patch(f"/api/auth/users/{second['id']}", json={"role": "user"}, headers=headers)
    assert demote.status_code == 200  # ada 2 admin saat ini, jadi berhasil

    admin_id = store.get_user_by_username("admin")["id"]
    response = client.delete(f"/api/auth/users/{admin_id}", headers=second_headers)

    assert response.status_code == 400
    assert store.get_user_by_id(admin_id) is not None


def test_cannot_demote_last_remaining_admin(auth_app):
    app, store = auth_app
    client = TestClient(app)
    admin_token = _login(client)
    headers = {"Authorization": f"Bearer {admin_token}"}
    admin_id = store.get_user_by_username("admin")["id"]

    response = client.patch(f"/api/auth/users/{admin_id}", json={"role": "user"}, headers=headers)

    assert response.status_code == 400
    assert store.get_user_by_id(admin_id)["role"] == "admin"
