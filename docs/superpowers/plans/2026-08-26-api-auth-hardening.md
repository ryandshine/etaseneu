# API Auth Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kunci semua endpoint baca API di belakang sesi login JWT (dengan rollout bertahap via flag), plus hardening perimeter (security header, CSP, rate limit, CORS).

**Architecture:** Batch A = perubahan nginx + CORS + logging, tidak mengubah otorisasi. Batch B = flag env `API_REQUIRE_AUTH` (default `false`) mengaktifkan dependency FastAPI `require_session_if_enabled` pada router baca; frontend mengalirkan token JWT ke semua panggilan `lib/api.ts` dan auto-logout saat 401. Rollback tanpa revert kode: flip env.

**Tech Stack:** FastAPI + pydantic-settings, nginx (`limit_req`, `add_header`), React/Vite/TypeScript, Vitest, pytest, Dokploy compose.

**Spec:** `docs/superpowers/specs/2026-08-26-api-auth-hardening-design.md`

## Global Constraints

- Tidak ada database/environment staging — `backend/.env` = DB produksi (CLAUDE.md bahaya #1). Test yang menyentuh `PostgresStore`/`LayerService`/`GeoJsonSyncService` WAJIB pakai pola `Disabled*` store. Test auth-gate ini tidak menyentuh Postgres (override dependency).
- Backend test: `cd backend && .venv/bin/python -m pytest app/tests -q`.
- Frontend test: `cd frontend && npm test`. Typecheck: `npm run build`.
- Tidak menambah dependency Python baru di Batch A/B (rate limit lewat nginx). `slowapi` hanya plan B kalau `limit_req_zone` terbukti tak bisa dipasang.
- `API_REQUIRE_AUTH` default `false` — deploy pertama HARUS no-op fungsional.
- Router admin (`cache`, `scheduler` POST `/sync`) TIDAK boleh ketumpuk gate baca — automation `X-Admin-Key`-only harus tetap 200.
- Deploy manual Dokploy; ingatkan user redeploy tiap habis ubah backend/frontend/nginx/compose.
- Commit message: `<type>: <deskripsi>` Bahasa Indonesia. Sertakan trailer `Co-Authored-By` + `Claude-Session` sesuai konvensi repo.
- Balas user dalam Bahasa Indonesia.

---

## FILE STRUCTURE

Backend:
- `backend/app/core/config.py` — tambah field `api_require_auth: bool = False`.
- `backend/app/core/auth.py` — tambah dependency `require_session_if_enabled`; tambah warning `AUTH_JWT_SECRET` kosong.
- `backend/app/api/router.py` — pasang `dependencies=[Depends(require_session_if_enabled)]` di `include_router` router baca.
- `backend/app/api/scheduler.py` — tambah `Depends(require_session_if_enabled)` per-route pada 3 GET baca (`/status`, `/metrics`, `/burned-area/status`); jangan sentuh POST `/sync` (sudah `require_admin_key`).
- `backend/app/main.py` — CORS `allow_methods`/`allow_headers` eksplisit.
- `backend/app/tests/conftest.py` — **baru**, fixture autouse mematikan `API_REQUIRE_AUTH` untuk semua test.
- `backend/app/tests/test_api_auth_gate.py` — **baru**.
- `backend/.env.example`, `backend/.env.dokploy.example` — dokumentasi `API_REQUIRE_AUTH`, `AUTH_JWT_SECRET`.

Frontend:
- `frontend/src/lib/api.ts` — modul token store (`setAuthToken`, `setUnauthorizedHandler`); `fetchJson` lampirkan `Authorization` + tangani 401.
- `frontend/src/hooks/useDashboardData.ts` — panggil `setAuthToken(authToken)` saat token berubah.
- `frontend/src/App.tsx` — daftarkan `setUnauthorizedHandler(() => setSession(null))`.
- `frontend/src/components/KompleksKebakaranView.tsx` — pastikan fetch-nya lewat `lib/api.ts` yang sama (sudah; token otomatis ikut setelah store modul dipakai).
- `frontend/src/test/api.test.ts` — **baru** (atau tambah ke test lib yang ada).

Infra/docs:
- `deploy/nginx/etaseneu.conf` — security header, CSP Report-Only, `real_ip`, `limit_req_zone` + `limit_req`.
- `docker-compose.dokploy.yml` — `environment: API_REQUIRE_AUTH: ${API_REQUIRE_AUTH:-}` di service `api`.
- `CLAUDE.md` — bagian Autentikasi + Deploy.

---

# BATCH A — HARDENING (risiko rendah, tidak mengubah otorisasi)

## Task A1: Security header + CSP Report-Only di nginx

**Files:**
- Modify: `deploy/nginx/etaseneu.conf`

**Interfaces:**
- Produces: response HTTP membawa header keamanan + `Content-Security-Policy-Report-Only`.

- [ ] **Step 1: Tambah blok header di dalam `server { ... }`**

Sisipkan tepat setelah baris `index index.html;` di `deploy/nginx/etaseneu.conf`:

```nginx
    # --- Security headers (Batch A hardening) ---
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # CSP: Report-Only dulu -- pelanggaran hanya muncul di console browser,
    # fitur (peta Leaflet, Turnstile, overlay) TIDAK rusak. Setelah console
    # bersih beberapa hari, ganti nama header ini jadi Content-Security-Policy
    # (Task A6) untuk enforce.
    set $eta_csp "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; connect-src 'self' https://challenges.cloudflare.com; img-src 'self' data: https:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; base-uri 'self'; object-src 'none'; frame-ancestors 'none'";
    add_header Content-Security-Policy-Report-Only $eta_csp always;
```

Catatan: `add_header` di dalam `location` yang punya `add_header` sendiri (mis. `location /api/layers`) akan **menimpa** header dari `server`. Untuk Task ini cukup di `server`; kalau nanti perlu header keamanan juga di `location /api/layers` dan `location ~* \.(...)`, ulangi `add_header` yang sama di sana. **Cek**: setelah deploy, `curl -I https://etaseneu.ditpps.com/` DAN `curl -I https://etaseneu.ditpps.com/api/layers` — dua-duanya harus memuat header keamanan.

- [ ] **Step 2: Validasi sintaks compose + nginx secara statis**

Run: `python3 -c "print(open('deploy/nginx/etaseneu.conf').read().count('{') == open('deploy/nginx/etaseneu.conf').read().count('}'))"`
Expected: `True` (kurung seimbang — sanity check kasar; validasi nyata saat container build).

- [ ] **Step 3: Commit**

```bash
git add deploy/nginx/etaseneu.conf
git commit -m "feat: security header + CSP Report-Only di nginx

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

## Task A2: Rate limiting nginx + real_ip

**Files:**
- Modify: `deploy/nginx/etaseneu.conf`

**Interfaces:**
- Consumes: file yang sama sudah punya blok `server` + `location /api/` dari A1.
- Produces: `limit_req` aktif di `/api/auth/login`, `/api/point-match/analyze`, `/api/export`, `/api/`.

Konteks: `Dockerfile.web` menyalin file ini ke `/etc/nginx/conf.d/default.conf`. `conf.d/*.conf` di-`include` nginx pada konteks **`http`**, jadi `limit_req_zone` boleh diletakkan di file ini **di luar** blok `server {`.

- [ ] **Step 1: Tambah `limit_req_zone` di paling atas file (sebelum `server {`)**

```nginx
# --- Rate limit zones (konteks http; conf.d/*.conf di-include di http) ---
limit_req_zone $binary_remote_addr zone=eta_login:10m rate=5r/m;
limit_req_zone $binary_remote_addr zone=eta_heavy:10m rate=10r/m;
limit_req_zone $binary_remote_addr zone=eta_api:10m   rate=20r/s;
limit_req_status 429;

```

- [ ] **Step 2: Tambah `real_ip` di dalam `server {` (setelah blok security header A1)**

```nginx
    # Di belakang Traefik: tanpa ini $binary_remote_addr = IP Traefik,
    # jadi SEMUA user berbagi satu kuota rate limit.
    set_real_ip_from 10.0.0.0/8;
    set_real_ip_from 172.16.0.0/12;
    set_real_ip_from 192.168.0.0/16;
    real_ip_header X-Forwarded-For;
    real_ip_recursive on;
```

- [ ] **Step 3: Tambah `location = /api/auth/login` (baru, sebelum `location /api/`)**

```nginx
    location = /api/auth/login {
        limit_req zone=eta_login burst=5 nodelay;
        proxy_pass http://api:8000/api/auth/login;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }

    location = /api/point-match/analyze {
        limit_req zone=eta_heavy burst=2;
        client_max_body_size 55m;
        proxy_pass http://api:8000/api/point-match/analyze;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }

    location /api/export {
        limit_req zone=eta_heavy burst=3;
        proxy_pass http://api:8000/api/export;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 10s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
```

- [ ] **Step 4: Tambahkan `limit_req` ke `location /api/` yang sudah ada**

Di dalam `location /api/ { ... }`, tambahkan baris pertama:

```nginx
        limit_req zone=eta_api burst=40 nodelay;
```

- [ ] **Step 5: Sanity check kurung seimbang**

Run: `python3 -c "s=open('deploy/nginx/etaseneu.conf').read(); print(s.count('{')==s.count('}'))"`
Expected: `True`

- [ ] **Step 6: Commit**

```bash
git add deploy/nginx/etaseneu.conf
git commit -m "feat: rate limiting nginx (login/heavy/umum) + real_ip di belakang Traefik

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

- [ ] **Step 7: CHECKPOINT — minta user redeploy `web`, lalu verifikasi live**

Minta user: redeploy stack di Dokploy (rebuild `web`). Setelah selesai, jalankan:

```bash
curl -sI https://etaseneu.ditpps.com/ | grep -iE "x-content-type-options|x-frame-options|referrer-policy|permissions-policy|strict-transport|content-security-policy-report-only"
curl -sI https://etaseneu.ditpps.com/api/layers | grep -iE "x-content-type-options"
for i in $(seq 1 12); do curl -s -o /dev/null -w "%{http_code} " -X POST https://etaseneu.ditpps.com/api/auth/login -H 'Content-Type: application/json' -d '{"username":"x","password":"y"}'; done; echo
```
Expected: header keamanan muncul di `/` (dan minimal `X-Content-Type-Options` di `/api/layers`); loop login menampilkan beberapa `400/401` lalu mulai `429` (rate limit login jalan). Minta user buka dashboard di browser — pastikan TIDAK ada 429 pada pemakaian normal, dan peta tetap muncul (cek console untuk pelanggaran CSP-Report-Only; catat origin yang kelewat).

---

## Task A3: CORS eksplisit + warning AUTH_JWT_SECRET

**Files:**
- Modify: `backend/app/main.py:` (blok `app.add_middleware(CORSMiddleware, ...)`)
- Modify: `backend/app/core/config.py:` (`get_settings()`)
- Modify: `backend/.env.dokploy.example`, `backend/.env.example`

**Interfaces:**
- Produces: CORS hanya izinkan method & header yang dipakai; log `WARNING` sekali saat startup kalau `auth_jwt_secret` kosong.

- [ ] **Step 1: Tulis test CORS**

Tambah ke `backend/app/tests/test_admin_auth.py` (atau file baru `test_cors_config.py`):

```python
def test_cors_allows_expected_headers_and_methods(monkeypatch):
    from app.main import create_app
    monkeypatch.setenv("FRONTEND_ORIGIN", "https://etaseneu.ditpps.com")
    get_settings.cache_clear()
    try:
        app = create_app()
        client = TestClient(app)
        resp = client.options(
            "/api/hotspots",
            headers={
                "Origin": "https://etaseneu.ditpps.com",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert resp.status_code == 200
        allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
        assert "authorization" in allow_headers
        assert resp.headers.get("access-control-allow-origin") == "https://etaseneu.ditpps.com"
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Jalankan test — harus lulus SEKARANG (baseline) atau gagal kalau preflight belum sesuai**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_admin_auth.py -q -k cors`
Expected: PASS (dengan `allow_headers=["*"]` saat ini preflight echo request header → sudah lulus). Ini test regresi supaya perubahan ke daftar eksplisit tidak memecah `authorization`.

- [ ] **Step 3: Ubah CORS di `backend/app/main.py`**

```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "Accept"],
    )
```

- [ ] **Step 4: Tambah warning di `backend/app/core/config.py` `get_settings()`**

Di dalam `get_settings()`, di blok `if not settings.auth_jwt_secret:` yang sudah ada, tambahkan sebelum baris `settings.auth_jwt_secret = secrets.token_urlsafe(48)`:

```python
        import logging
        logging.getLogger("hotspot.config").warning(
            "AUTH_JWT_SECRET kosong -- secret di-generate acak tiap start proses; "
            "semua sesi login jadi invalid tiap restart. Set nilai tetap di produksi."
        )
```

- [ ] **Step 5: Jalankan test CORS + suite auth**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_admin_auth.py app/tests/test_login_turnstile.py -q`
Expected: PASS semua.

- [ ] **Step 6: Update env example**

`backend/.env.example` — tambah di akhir:
```
# Kunci tanda tangan sesi JWT. Kosong = di-generate acak tiap restart (semua
# sesi login putus). Set nilai tetap (mis. `openssl rand -base64 48`) di produksi.
AUTH_JWT_SECRET=
# Kunci semua endpoint baca di belakang sesi login. false = publik (perilaku
# lama). Aktifkan HANYA setelah frontend terverifikasi mengirim token.
API_REQUIRE_AUTH=false
```

`backend/.env.dokploy.example` — tambah setelah baris `APP_LOGIN_PASSWORD=replace-me` (di bawah catatan Turnstile):
```
# Kunci sesi JWT -- set nilai tetap supaya sesi tidak putus tiap deploy.
AUTH_JWT_SECRET=replace-me
# Gate auth API: diisi di tab Environment Dokploy (di-forward ke container api
# lewat docker-compose.dokploy.yml). false/kosong = endpoint baca publik.
API_REQUIRE_AUTH=false
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/main.py backend/app/core/config.py backend/.env.example backend/.env.dokploy.example backend/app/tests/test_admin_auth.py
git commit -m "feat: CORS method/header eksplisit + warning AUTH_JWT_SECRET kosong

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

## Task A4: Audit dependency (laporan saja)

**Files:** tidak ada perubahan kode kecuali bump yang jelas aman.

- [ ] **Step 1: pip-audit**

Run: `cd backend && .venv/bin/pip install pip-audit -q && .venv/bin/pip-audit 2>&1 | tail -40` (kalau `pip-audit` tak boleh diinstall di env ini, lewati & catat).
Catat CVE yang muncul. JANGAN bump mayor. Bump patch hanya kalau: (a) CVE relevan dengan cara kita pakai lib itu, (b) hanya patch version, (c) `pytest` tetap hijau.

- [ ] **Step 2: npm audit**

Run: `cd frontend && npm audit --omit=dev 2>&1 | tail -40`
Catat. Bump hanya `npm audit fix` tanpa `--force`; verifikasi `npm run build` + `npm test`.

- [ ] **Step 3: Tulis ringkasan temuan ke bagian bawah spec**

Tambah section `## Hasil audit dependency (2026-08-26)` ke `docs/superpowers/specs/2026-08-26-api-auth-hardening-design.md` berisi output ringkas + keputusan (bump / terima risiko / follow-up).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: audit dependency backend+frontend (pip-audit, npm audit)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

# BATCH B — KUNCI ENDPOINT BACA (flag `API_REQUIRE_AUTH`)

## Task B1: Flag config + dependency `require_session_if_enabled` + conftest

**Files:**
- Modify: `backend/app/core/config.py` (field baru)
- Modify: `backend/app/core/auth.py` (dependency baru)
- Create: `backend/app/tests/conftest.py`
- Create: `backend/app/tests/test_api_auth_gate.py`

**Interfaces:**
- Produces:
  - `Settings.api_require_auth: bool` (default `False`).
  - `async def require_session_if_enabled(authorization: str | None = Header(default=None)) -> TokenClaims | None` — return `None` kalau flag mati; kalau nyala, delegasi ke `require_authenticated_user` (raise 401 kalau token tak ada/invalid).

- [ ] **Step 1: Tambah field di `backend/app/core/config.py`**

Setelah `turnstile_secret_key: str = ""`:

```python
    # Kalau True, SEMUA endpoint baca API butuh header Authorization: Bearer
    # <jwt> yang sah (lihat core/auth.require_session_if_enabled). Default
    # False = perilaku lama (endpoint baca publik) supaya deploy tidak
    # langsung mengunci situs; dinyalakan manual di Dokploy setelah frontend
    # terverifikasi mengirim token.
    api_require_auth: bool = False
```

- [ ] **Step 2: Tulis test gate (failing)**

Create `backend/app/tests/test_api_auth_gate.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.core.auth import issue_token
from app.core.config import get_settings


@pytest.fixture
def app_with_auth_flag(monkeypatch):
    """create_app() dengan API_REQUIRE_AUTH bisa di-set per test.
    Tidak menyentuh Postgres: endpoint baca yang dites (/api/health,
    /api/stats) tidak butuh store, dan kita tidak memanggil yang butuh."""
    from app.main import create_app

    def _set(flag: str):
        monkeypatch.setenv("API_REQUIRE_AUTH", flag)
        monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret-b1")
        get_settings.cache_clear()
        return create_app()

    yield _set
    get_settings.cache_clear()


def test_read_endpoint_public_when_flag_off(app_with_auth_flag):
    app = app_with_auth_flag("false")
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    # /api/stats butuh store -> pakai health + satu endpoint baca ringan.
    # Gunакан /api/scheduler/status (tidak butuh Postgres store).
    assert client.get("/api/scheduler/status").status_code == 200


def test_read_endpoint_401_when_flag_on_and_no_token(app_with_auth_flag):
    app = app_with_auth_flag("true")
    client = TestClient(app)
    assert client.get("/api/scheduler/status").status_code == 401


def test_read_endpoint_200_when_flag_on_with_valid_token(app_with_auth_flag):
    app = app_with_auth_flag("true")
    client = TestClient(app)
    token = issue_token(user_id=1, username="admin", role="admin")
    resp = client.get("/api/scheduler/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_health_always_public_even_when_flag_on(app_with_auth_flag):
    app = app_with_auth_flag("true")
    client = TestClient(app)
    assert client.get("/api/health").status_code == 200


def test_metrics_always_public_even_when_flag_on(app_with_auth_flag):
    app = app_with_auth_flag("true")
    client = TestClient(app)
    assert client.get("/api/metrics").status_code == 200


def test_admin_endpoint_with_x_admin_key_only_not_blocked_by_read_gate(app_with_auth_flag, monkeypatch):
    """Router admin tidak ketumpuk gate baca: X-Admin-Key tanpa JWT tetap
    lolos gate auth (lalu 200/202/500 dari logika handler-nya sendiri)."""
    monkeypatch.setenv("ADMIN_API_KEY", "s3cret-b1")
    app = app_with_auth_flag("true")  # cache_clear sudah termasuk
    get_settings.cache_clear()
    client = TestClient(app)
    # /api/scheduler/burned-area/status = GET admin? -> cek: pakai POST /sync
    resp = client.post("/api/scheduler/sync", headers={"X-Admin-Key": "s3cret-b1"})
    assert resp.status_code != 401  # 200/202/500 dari logika sync, bukan ditolak auth
```

> Catatan implementer: `/api/scheduler/status` dipilih sebagai contoh endpoint baca karena tidak butuh `PostgresStore`. Kalau ternyata butuh, ganti ke endpoint router baca lain yang murni in-memory, atau override store. JANGAN pilih endpoint yang memanggil DB produksi.

- [ ] **Step 3: Jalankan — harus GAGAL (dependency belum ada / belum dipasang)**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_api_auth_gate.py -q`
Expected: FAIL — `test_read_endpoint_401_when_flag_on_and_no_token` dapat 200 (belum ada gate).

- [ ] **Step 4: Tambah dependency di `backend/app/core/auth.py`**

Setelah `require_authenticated_user`:

```python
async def require_session_if_enabled(
    authorization: str | None = Header(default=None),
) -> TokenClaims | None:
    """Gate baca opsional. Kalau Settings.api_require_auth False -> no-op
    (endpoint baca tetap publik, perilaku lama). Kalau True -> wajib
    'Authorization: Bearer <jwt>' valid (delegasi ke require_authenticated_user,
    401 kalau tidak).
    """
    if not get_settings().api_require_auth:
        return None
    return await require_authenticated_user(authorization)
```

- [ ] **Step 5: Buat `backend/app/tests/conftest.py` (autouse mematikan flag untuk test lama)**

```python
"""Fixture global test.

`disable_api_auth_gate` autouse: mematikan API_REQUIRE_AUTH untuk SEMUA test
kecuali yang secara eksplisit meng-override (test_api_auth_gate.py memakai
monkeypatch.setenv sendiri, yang menang). Tanpa ini, ~belasan test yang hit
endpoint baca tanpa token akan pecah begitu Task B2 memasang gate.
"""

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def disable_api_auth_gate(monkeypatch):
    monkeypatch.setenv("API_REQUIRE_AUTH", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

> Interaksi dengan `test_api_auth_gate.py`: fixture di sana memanggil `monkeypatch.setenv("API_REQUIRE_AUTH","true")` SETELAH autouse ini (fixture lokal jalan setelah autouse), lalu `get_settings.cache_clear()`, jadi nilainya menang. Aman.

- [ ] **Step 6: Jalankan test gate lagi — sebagian masih gagal (gate belum dipasang di router), tapi flag & dependency ada**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_api_auth_gate.py -q`
Expected: `test_read_endpoint_401...` masih FAIL (gate belum dipasang — itu Task B2). Test lain (health/metrics public, flag-off) PASS. Ini titik commit yang sah: infrastruktur flag siap.

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/core/auth.py backend/app/tests/conftest.py backend/app/tests/test_api_auth_gate.py
git commit -m "feat: flag API_REQUIRE_AUTH + dependency require_session_if_enabled (belum dipasang)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

## Task B2: Pasang gate di router baca

**Files:**
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/api/scheduler.py`

**Interfaces:**
- Consumes: `require_session_if_enabled` dari Task B1.
- Produces: router `layers, polygons, point_match, hotspots, hotspot_clusters, stats, export, wind, weather, burned_area` + GET baca `scheduler` terlindungi saat flag on.

- [ ] **Step 1: Ubah `backend/app/api/router.py`**

```python
from fastapi import APIRouter, Depends

from app.core.auth import require_session_if_enabled
# ... import router lain tetap ...

router = APIRouter()
router.include_router(auth_router)  # TIDAK di-gate: harus bisa pra-sesi

_read_gate = [Depends(require_session_if_enabled)]
router.include_router(layers_router, dependencies=_read_gate)
router.include_router(polygons_router, dependencies=_read_gate)
router.include_router(point_match_router, dependencies=_read_gate)
router.include_router(hotspots_router, dependencies=_read_gate)
router.include_router(hotspot_clusters_router, dependencies=_read_gate)
router.include_router(stats_router, dependencies=_read_gate)
router.include_router(export_router, dependencies=_read_gate)
router.include_router(wind_router, dependencies=_read_gate)
router.include_router(weather_router, dependencies=_read_gate)
router.include_router(burned_area_router, dependencies=_read_gate)
router.include_router(cache_router)      # sudah require_admin_key -- JANGAN di-gate baca
router.include_router(scheduler_router)  # per-route (Step 2) -- JANGAN router-level
router.include_router(metrics_router)    # Prometheus -- publik
api_router = router
```

Urutan `include_router` dipertahankan sama seperti semula selain penambahan `dependencies`.

- [ ] **Step 2: Gate per-route di `backend/app/api/scheduler.py`**

Tambah import: `from app.core.auth import require_admin_key, require_session_if_enabled`

Pada 3 route GET baca, tambahkan parameter dependency (JANGAN pada `POST /sync`):

```python
@router.get("/status")
async def scheduler_status(_: object = Depends(require_session_if_enabled)) -> dict:
    ...

@router.get("/metrics")
async def scheduler_metrics(_: object = Depends(require_session_if_enabled)) -> dict:
    ...

@router.get("/burned-area/status")
async def burned_area_status(_: object = Depends(require_session_if_enabled)) -> dict:
    ...
```

(Sesuaikan nama fungsi dengan yang ada di file. Signature lain dibiarkan.)

- [ ] **Step 3: Jalankan test gate**

Run: `cd backend && .venv/bin/python -m pytest app/tests/test_api_auth_gate.py -q`
Expected: PASS semua (401 tanpa token saat flag on; 200 dengan token; health/metrics publik; admin X-Admin-Key lolos).

- [ ] **Step 4: Jalankan SELURUH suite backend**

Run: `cd backend && .venv/bin/python -m pytest app/tests -q`
Expected: PASS semua (conftest autouse mematikan flag untuk test lama). Kalau ada test lama yang pecah karena kebetulan mengandalkan endpoint baca TANPA conftest (mis. bikin app sendiri), perbaiki test itu dengan menambah `monkeypatch.setenv("API_REQUIRE_AUTH","false"); get_settings.cache_clear()` di setup-nya. Catat mana yang diperbaiki.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/router.py backend/app/api/scheduler.py
git commit -m "feat: pasang gate require_session_if_enabled di semua router baca

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

## Task B3: Forward `API_REQUIRE_AUTH` ke container api

**Files:**
- Modify: `docker-compose.dokploy.yml`

- [ ] **Step 1: Tambah ke `environment:` service `api`**

Blok `environment:` sudah ada (dari fitur Turnstile). Tambah satu baris:

```yaml
    environment:
      TURNSTILE_SECRET_KEY: ${TURNSTILE_SECRET_KEY:-}
      API_REQUIRE_AUTH: ${API_REQUIRE_AUTH:-false}
```

- [ ] **Step 2: Validasi YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('docker-compose.dokploy.yml')); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.dokploy.yml
git commit -m "chore: forward API_REQUIRE_AUTH ke container api

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

## Task B4: Frontend — token plumbing di `lib/api.ts`

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/test/api.test.ts`

**Interfaces:**
- Produces (dari `lib/api.ts`):
  - `export function setAuthToken(token: string | null): void`
  - `export function setUnauthorizedHandler(fn: (() => void) | null): void`
  - `fetchJson` melampirkan `Authorization: Bearer <token>` kalau token ada; kalau response `401`, memanggil handler (jika ada) lalu `throw new Error("unauthorized")`.

- [ ] **Step 1: Tulis test (failing)**

Create `frontend/src/test/api.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";
import { createApiClient, setAuthToken, setUnauthorizedHandler } from "../lib/api";

afterEach(() => {
  setAuthToken(null);
  setUnauthorizedHandler(null);
  vi.restoreAllMocks();
});

describe("lib/api auth", () => {
  it("melampirkan Authorization header saat token diset", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);
    setAuthToken("tok-123");

    await createApiClient().getHealth();

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("tidak ada Authorization header saat token null", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    await createApiClient().getHealth();

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("memanggil unauthorized handler saat 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("nope", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const onUnauth = vi.fn();
    setUnauthorizedHandler(onUnauth);

    await expect(createApiClient().getHealth()).rejects.toThrow();
    expect(onUnauth).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Jalankan — FAIL (fungsi belum ada)**

Run: `cd frontend && npx vitest run src/test/api.test.ts`
Expected: FAIL — `setAuthToken is not a function`.

- [ ] **Step 3: Implementasi di `frontend/src/lib/api.ts`**

Di dekat atas file (setelah import), tambah modul store:

```ts
let authToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  unauthorizedHandler = fn;
}
```

Ubah `fetchJson`:

```ts
async function fetchJson<T>(
  path: string,
  method = "GET",
  extraHeaders?: Record<string, string>
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...extraHeaders,
  };
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`;
  }

  const response = await fetch(path, { method, headers });

  if (response.status === 401) {
    unauthorizedHandler?.();
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    throw new Error(`API request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}
```

Catatan: `adminHeaders()` tetap dipakai untuk `X-Admin-Key`; sekarang `Authorization` ditambah otomatis oleh `fetchJson`, jadi baris `headers["Authorization"] = ...` di `adminHeaders` boleh dibiarkan (idempoten, nilai sama) ATAU dihapus untuk DRY — hapus, dan pastikan pemanggil `adminHeaders` yang butuh token tetap dapat lewat `fetchJson`. **Cek** semua pemakaian `adminHeaders(` di `useDashboardData.ts`: kalau ada yang lewat `fetch` mentah (bukan `fetchJson`), tinggalkan `Authorization` di `adminHeaders`. Aman default: BIARKAN `adminHeaders` apa adanya.

- [ ] **Step 4: Jalankan test**

Run: `cd frontend && npx vitest run src/test/api.test.ts`
Expected: PASS (3 test).

- [ ] **Step 5: Typecheck + seluruh test frontend**

Run: `cd frontend && npm run build && npm test`
Expected: PASS semua (44+ test).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/test/api.test.ts
git commit -m "feat: lib/api lampirkan JWT ke semua request + handler 401

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

## Task B5: Frontend — sambungkan token & auto-logout

**Files:**
- Modify: `frontend/src/hooks/useDashboardData.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/test/App.test.tsx` (atau tambah test baru)

**Interfaces:**
- Consumes: `setAuthToken`, `setUnauthorizedHandler` dari Task B4.

- [ ] **Step 1: `useDashboardData.ts` — panggil `setAuthToken` saat token berubah**

Import: `import { createApiClient, setAuthToken } from "../lib/api";`

Di dalam body hook `useDashboardData(activeView, adminKey, authToken)`, tambah efek:

```ts
useEffect(() => {
  setAuthToken(authToken ?? null);
}, [authToken]);
```

(`api` singleton modul tetap; `fetchJson` baca `authToken` modul saat request.)

- [ ] **Step 2: `App.tsx` — daftarkan handler 401 = logout**

Import: `import { setUnauthorizedHandler } from "./lib/api";`

Setelah deklarasi `const [session, setSession] = useState<AppSession | null>(null);`:

```tsx
useEffect(() => {
  setUnauthorizedHandler(() => setSession(null));
  return () => setUnauthorizedHandler(null);
}, []);
```

- [ ] **Step 3: Tulis test auto-logout**

Tambah ke `frontend/src/test/App.test.tsx`:

```tsx
it("kembali ke LoginPage saat API balas 401 (sesi kadaluarsa)", async () => {
  // login dulu, lalu buat fetch berikutnya balas 401
  // (detail mengikuti pola fetchMock file ini — handle /api/auth/login {ok:true,...}
  //  lalu untuk endpoint dashboard balas Response(status:401))
  // Assert: elemen Username muncul lagi (LoginPage kembali dirender).
});
```

> Implementer: sesuaikan dengan pola `fetchMock` yang sudah ada di `App.test.tsx`. Inti assert: setelah 401, `screen.findByLabelText("Username")` resolve (LoginPage kembali).

- [ ] **Step 4: Jalankan test frontend penuh**

Run: `cd frontend && npm run build && npm test`
Expected: PASS semua.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useDashboardData.ts frontend/src/App.tsx frontend/src/test/App.test.tsx
git commit -m "feat: alirkan JWT ke semua panggilan API + auto-logout saat 401

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
```

---

## Task B6: Dokumentasi + verifikasi penuh (flag masih OFF)

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-08-26-api-auth-hardening-design.md` (tandai status: implemented, flag off)

- [ ] **Step 1: Update `CLAUDE.md` bagian Autentikasi**

Tambah paragraf setelah blok Turnstile:

```
**Gate auth API baca** (`API_REQUIRE_AUTH`, default `false`). Kalau `true`, semua
router baca (`hotspots`, `layers` termasuk `view=preview`, `polygons`, `stats`,
`burned_area`, `hotspot_clusters`, `point_match`, `export`, `wind`, `weather`,
GET `scheduler/*`) butuh `Authorization: Bearer <jwt>` sah lewat dependency
`core/auth.require_session_if_enabled`. Publik apa pun nilainya: `/api/health`,
`/api/auth/*`, `/api/metrics` (Prometheus). Router admin (`cache`, `scheduler`
POST `/sync`) TIDAK ketumpuk gate ini — tetap `require_admin_key` (X-Admin-Key
ATAU JWT admin). Frontend `lib/api.ts` melampirkan token ke semua request via
`setAuthToken`; `App.tsx` `setUnauthorizedHandler` → 401 memaksa logout.
Di produksi `API_REQUIRE_AUTH` diisi di tab Environment Dokploy (di-forward ke
container `api` lewat `docker-compose.dokploy.yml`). Rollback = set `false` +
redeploy `api`, tanpa revert kode. Cek cepat: `GET /api/stats` tanpa token →
401 kalau aktif, 200 kalau tidak.
```

Tambah juga catatan di bagian Deploy tentang security header + CSP Report-Only + rate limit nginx.

- [ ] **Step 2: Jalankan semua test (backend + frontend)**

Run:
```bash
cd backend && .venv/bin/python -m pytest app/tests -q
cd ../frontend && npm run build && npm test
```
Expected: hijau semua.

- [ ] **Step 3: Commit + push**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-08-26-api-auth-hardening-design.md
git commit -m "docs: dokumentasikan gate API_REQUIRE_AUTH + hardening nginx

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
git push origin main
```

- [ ] **Step 4: CHECKPOINT — user redeploy stack penuh (`api` + `web`)**

Setelah deploy (flag masih `false` / belum diset), verifikasi live:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://etaseneu.ditpps.com/api/stats            # 200 (flag off)
curl -sI https://etaseneu.ditpps.com/ | grep -i content-security-policy-report-only        # ada
```
Minta user: login browser normal, buka semua view (peta, matriks, KPS, kompleks kebakaran, pengaturan). SEMUA harus jalan seperti biasa. Cek console CSP-Report-Only — catat origin yang kelewat, tambal di `etaseneu.conf` kalau ada, deploy ulang.

---

## Task B7: Aktifkan gate (flag ON) — dipandu, dikerjakan user

**Files:** tidak ada perubahan kode.

- [ ] **Step 1: User set env di Dokploy**

Minta user: tab Environment stack Dokploy → tambah `API_REQUIRE_AUTH=true` → redeploy `api`.

- [ ] **Step 2: Verifikasi live**

```bash
curl -s -o /dev/null -w "tanpa-token=%{http_code}\n" https://etaseneu.ditpps.com/api/stats   # 401
# token dari login:
TOKEN=$(curl -s -X POST https://etaseneu.ditpps.com/api/auth/login -H 'Content-Type: application/json' -d '{"username":"<user>","password":"<pass>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -o /dev/null -w "dengan-token=%{http_code}\n" -H "Authorization: Bearer $TOKEN" https://etaseneu.ditpps.com/api/stats   # 200
curl -s -o /dev/null -w "health=%{http_code}\n" https://etaseneu.ditpps.com/api/health   # 200
curl -s -o /dev/null -w "admin-xkey=%{http_code}\n" -X POST https://etaseneu.ditpps.com/api/scheduler/sync -H "X-Admin-Key: <admin-key>"   # bukan 401
```
Minta user: login browser → seluruh dashboard tetap jalan (token mengalir). Kalau ADA yang rusak → set `API_REQUIRE_AUTH=false` → redeploy `api` → situs pulih; laporkan gejalanya untuk diperbaiki.

- [ ] **Step 3: Update `CLAUDE.md` + spec: status = ENFORCED sejak <tanggal>. Commit + push.**

---

## Task B8: Flip CSP ke enforcing (setelah console bersih)

**Files:**
- Modify: `deploy/nginx/etaseneu.conf`

- [ ] **Step 1: Ganti nama header**

`add_header Content-Security-Policy-Report-Only $eta_csp always;` → `add_header Content-Security-Policy $eta_csp always;`

- [ ] **Step 2: Commit + push + minta user redeploy `web`**

```bash
git add deploy/nginx/etaseneu.conf
git commit -m "feat: enforce CSP (dari Report-Only)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011q12tv9nDAWhmLzqmoKXQF"
git push origin main
```

- [ ] **Step 3: Verifikasi live** — `curl -sI https://etaseneu.ditpps.com/ | grep -i content-security-policy` (tanpa `-report-only`); user cek peta + Turnstile + overlay + export masih jalan.

---

## Self-Review (diisi penulis plan)

**1. Spec coverage:**
- A1 security header → Task A1 ✓
- A2 CSP → Task A1 (Report-Only) + B8 (enforce) ✓
- A3 rate limit + real_ip → Task A2 ✓
- A4 AUTH_JWT_SECRET warning → Task A3 ✓
- A5 CORS → Task A3 ✓
- A6 dependency audit → Task A4 ✓
- B1 flag + dependency → Task B1 ✓
- B2 router mana di-gate → Task B2 (router.py + scheduler.py per-route) ✓
- B3 frontend token plumbing → Task B4 ✓
- B4 test conftest + gate test → Task B1 (conftest) + B2 (suite) ✓
- B5 rollout → Task B3 (compose) + B6 (deploy flag off) + B7 (flag on) ✓
- metrics tetap publik → Task B1 test `test_metrics_always_public...` + B2 komentar ✓
- `layers?view=preview` dikunci → tercakup: `layers_router` dapat `_read_gate` (Task B2) ✓

**2. Placeholder scan:** Task B5 Step 3 test body sengaja deskriptif (pola `fetchMock` spesifik file test yang belum dibaca penuh) — implementer diberi pola konkret + assert inti. Task A4 output audit belum diketahui (memang runtime). Tidak ada "TODO/TBD".

**3. Type consistency:** `require_session_if_enabled` signature konsisten B1↔B2. `setAuthToken`/`setUnauthorizedHandler` konsisten B4↔B5. `_read_gate` nama lokal di router.py.

**Catatan ketidakpastian terselesaikan:** `limit_req_zone` — file di-`COPY` ke `conf.d/default.conf`, di-`include` nginx pada konteks `http`, jadi zona boleh di file ini di luar `server {}`. Plan B `slowapi` tidak diperlukan.
