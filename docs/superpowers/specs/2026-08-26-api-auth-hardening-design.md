# Desain: Pengamanan API ETA SENEU (auth + hardening)

Tanggal: 2026-08-26
Status: draft, menunggu review user sebelum implementasi plan.

## Latar belakang & tujuan

Saat ini gerbang login (JWT) hanya mengunci **tampilan React**. Semua endpoint
baca API (`/api/hotspots`, `/api/layers`, `/api/stats`, `/api/burned-area/*`,
`/api/hotspots/clusters`, `/api/point-match/analyze`, `/api/export/*`,
`/api/wind`, `/api/weather`, `/api/scheduler/metrics`) publik tanpa auth. Tidak
ada rate limiting. Tidak ada security header / CSP di nginx.

Endpoint tulis/admin **sudah** aman (`require_admin_key` / `require_admin_role`,
fail-closed). `file_name` di refresh-KLHK sudah disanitasi. TLS + redirect HTTPS
ditangani Traefik.

Tujuan: (A) hardening perimeter risiko rendah, (B) semua endpoint baca butuh
sesi login yang sah. Dikerjakan dengan rollout bertahap karena **tidak ada
database / environment staging** (CLAUDE.md bahaya #1).

## Keputusan yang sudah dikonfirmasi user

1. Rollout Batch B bertahap lewat flag env `API_REQUIRE_AUTH` (default `false`),
   di-`true`-kan manual di Dokploy setelah verifikasi. Pola fail-open sama
   seperti Turnstile.
2. `/api/layers?view=preview` **ikut dikunci** — tidak ada lagi akses tanpa
   login.
3. CSP dikirim sebagai `Content-Security-Policy-Report-Only` dulu (deploy 1),
   lalu di-`enforce` (deploy 2).

## Batch A — hardening (risiko rendah)

### A1. Security header (nginx `deploy/nginx/etaseneu.conf`)

Tambah di level `server` (berlaku semua response, `always`):

```
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

HSTS aman: entri kanonik lewat Traefik (HTTPS), nginx internal `:80` di
belakangnya. `X-Frame-Options: DENY` konsisten dengan tidak ada kebutuhan
embed iframe (Traefik label tidak meng-embed).

### A2. CSP (Report-Only dulu)

Origin eksternal yang benar-benar dipakai frontend (hasil grep
`frontend/src` + `index.html` + `index.css`):

| Direktif | Nilai | Alasan |
|---|---|---|
| `default-src` | `'self'` | |
| `script-src` | `'self' https://challenges.cloudflare.com` | Turnstile `api.js` |
| `frame-src` | `https://challenges.cloudflare.com` | iframe challenge Turnstile |
| `connect-src` | `'self' https://challenges.cloudflare.com` | API same-origin + telemetry Turnstile |
| `img-src` | `'self' data: https:` | tile `*.basemaps.cartocdn.com` & `server.arcgisonline.com`, marker data-URI |
| `style-src` | `'self' 'unsafe-inline' https://fonts.googleapis.com` | Leaflet + React inline style, `@import` Google Fonts |
| `font-src` | `'self' https://fonts.gstatic.com` | Plus Jakarta Sans / IBM Plex Mono |
| `base-uri` | `'self'` | |
| `object-src` | `'none'` | |
| `frame-ancestors` | `'none'` | selaras `X-Frame-Options: DENY` |

Deploy 1: header `Content-Security-Policy-Report-Only`. User cek console
browser beberapa hari (peta, Turnstile, overlay cuaca/angin, export). Deploy 2:
ganti nama header jadi `Content-Security-Policy` (enforce). Tidak pakai
`report-uri` (tidak ada endpoint pengumpul; cukup console).

### A3. Rate limiting (nginx `limit_req`, tanpa dependency Python)

`real_ip` wajib lebih dulu (kalau tidak, semua request tampak dari IP Traefik
→ satu kuota untuk semua):

```
set_real_ip_from 10.0.0.0/8;
set_real_ip_from 172.16.0.0/12;
set_real_ip_from 192.168.0.0/16;
real_ip_header X-Forwarded-For;
real_ip_recursive on;
```

Zona (`http` context — Dokploy: lewat `deploy/nginx/` atau snippet
`conf.d`; perlu cek apakah file ini di-`include` di dalam `http`):

```
limit_req_zone $binary_remote_addr zone=eta_login:10m  rate=5r/m;
limit_req_zone $binary_remote_addr zone=eta_heavy:10m  rate=10r/m;
limit_req_zone $binary_remote_addr zone=eta_api:10m    rate=20r/s;
limit_req_status 429;
```

Penerapan per-location:

| Location | limit | burst |
|---|---|---|
| `= /api/auth/login` | `eta_login` | `burst=5 nodelay` |
| `/api/point-match/analyze` (location baru) | `eta_heavy` | `burst=2` |
| `/api/export` (location baru) | `eta_heavy` | `burst=3` |
| `/api/` (umum) | `eta_api` | `burst=40 nodelay` |

`burst=40` di jalur umum: dashboard menembak beberapa panggilan saat load;
angka ini kompromi supaya pemakaian normal tidak kena 429. **Perlu diuji
manual di produksi setelah deploy** (buka dashboard, pastikan tidak 429).

> Catatan implementasi: kalau `etaseneu.conf` di-`include` di dalam blok
> `server` (bukan `http`), `limit_req_zone` tidak bisa di situ. Alternatif:
> taruh zona di file terpisah yang di-`include` Dokploy pada `http`, atau
> gunakan `map`/`geo`. Dicek saat implementasi; kalau tidak memungkinkan
> tanpa mengubah struktur include Dokploy, rate limiting login dipindah ke
> aplikasi (dependency `slowapi`) sebagai plan B — dicatat di plan.

### A4. `AUTH_JWT_SECRET`

Tetap auto-generate kalau kosong (sesuai desain CLAUDE.md — sengaja tidak
fail-closed untuk hindari lockout). Tambahan:

- `get_settings()` / startup: `logger.warning(...)` mencolok kalau
  `auth_jwt_secret` kosong ("sesi akan invalid tiap restart; set
  AUTH_JWT_SECRET di produksi").
- Tambah `AUTH_JWT_SECRET=` + komentar ke `.env.dokploy.example`.

### A5. CORS (`backend/app/main.py`)

```python
allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "Accept"]
```

Origin tetap `[settings.frontend_origin]`, `allow_credentials=True`.

### A6. Audit dependency

Jalankan `pip-audit` (backend `.venv`) + `npm audit` (frontend). Laporkan
temuan ke user. Bump hanya patch yang jelas aman & lolos test. `earthengine-api`
tidak dihapus (masih di-`import` `burned_area_service.py`).

## Batch B — kunci endpoint baca di belakang JWT

### B1. Flag & dependency

`config.py`: `api_require_auth: bool = False`.

`core/auth.py`: dependency baru

```python
async def require_session_if_enabled(
    authorization: str | None = Header(default=None),
) -> TokenClaims | None:
    if not get_settings().api_require_auth:
        return None
    return await require_authenticated_user(authorization)
```

- `api_require_auth=false` → no-op (perilaku sekarang, aman untuk deploy
  pertama).
- `api_require_auth=true` → wajib `Authorization: Bearer <jwt>` valid, else 401.

### B2. Router mana yang dapat dependency

`api/router.py` — pasang `dependencies=[Depends(require_session_if_enabled)]`
pada `include_router` untuk router **baca**:

`layers`, `polygons`, `point_match`, `hotspots`, `hotspot_clusters`, `stats`,
`export`, `wind`, `weather`, `burned_area`.

**Tidak** dipasang pada:
- `auth` — harus bisa diakses pra-sesi.
- `health` (route `/api/health` di `router.py` sendiri) — publik untuk
  healthcheck Docker/Traefik.
- `metrics` — Prometheus scrape. Tetap publik di aplikasi; kalau perlu
  dibatasi, pakai IP-allowlist di nginx (di luar scope ini, dicatat sebagai
  follow-up).
- `cache`, `scheduler` — sudah `require_admin_key` (menerima X-Admin-Key ATAU
  JWT admin). **Tidak ditumpuk** `require_session_if_enabled` supaya automation
  yang cuma pakai X-Admin-Key tidak putus.

`scheduler.py` punya endpoint metrik non-admin? — dicek saat implementasi;
kalau ada endpoint baca metrik tanpa `require_admin_key`, ikut dilindungi
`require_session_if_enabled`.

### B3. Frontend

- `lib/api.ts`: `createApiClient(baseUrl, getAuthToken?)`. `fetchJson`
  menambahkan `Authorization: Bearer ${token}` kalau ada. Semua method (baca &
  admin) lewat jalur ini.
- `useDashboardData.ts`: teruskan `session.token` ke `createApiClient`; buat
  ulang client saat token berubah (login/logout).
- `KompleksKebakaranView.tsx`: fetch sendiri lewat `lib/api.ts` — pastikan ikut
  mengalirkan token (idealnya pakai client yang sama, bukan `fetch` mentah).
- Handler `401` terpusat di `fetchJson`: lempar error khusus `SessionExpired`
  → `App.tsx` menangkap → `setSession(null)` (paksa login ulang) + pesan
  "Sesi berakhir, silakan login lagi".
- `LoginPage`/`App`: tidak ada perubahan alur; token sudah di memori React.

### B4. Test

- Buat `backend/app/tests/conftest.py`:
  - fixture autouse `disable_api_auth` — `monkeypatch.setenv("API_REQUIRE_AUTH","")`
    + `get_settings.cache_clear()` supaya default test = auth mati (perilaku
    lama, ±14 file test hit endpoint baca tanpa token tetap hijau tanpa diubah).
  - helper `auth_client(app)` / fixture untuk test baru yang memang menguji
    jalur `api_require_auth=true` (override `require_authenticated_user` →
    `TokenClaims(1,"admin","admin")`, atau kirim token asli dari `issue_token`).
- Test baru `test_api_auth_gate.py`:
  1. `API_REQUIRE_AUTH` kosong → `GET /api/hotspots` tanpa token → 200.
  2. `API_REQUIRE_AUTH=true` → tanpa token → 401.
  3. `API_REQUIRE_AUTH=true` + token valid → 200.
  4. `API_REQUIRE_AUTH=true` → endpoint admin dengan X-Admin-Key saja (tanpa
     JWT) tetap 200 (tidak ikut ketumpuk gate baca).
  5. `/api/health` tetap 200 tanpa token walau `API_REQUIRE_AUTH=true`.
- Frontend: test `lib/api.ts` melampirkan header `Authorization` saat token
  ada; test `useDashboardData` / `App` untuk auto-logout saat 401.

### B5. Urutan rollout (dijalankan user, dipandu)

1. Merge + deploy (backend `api_require_auth=false`, frontend sudah kirim
   token). **Perilaku tidak berubah.** Verifikasi situs normal.
2. Cek `curl /api/hotspots` tanpa token → masih 200 (flag mati).
3. Set `API_REQUIRE_AUTH=true` di tab Environment Dokploy (+ forward ke
   container `api` lewat `environment:` di compose, pola sama seperti
   `TURNSTILE_SECRET_KEY`). Redeploy `api`.
4. Verifikasi: `curl /api/hotspots` tanpa token → **401**; login lewat browser
   → dashboard tetap jalan (token mengalir); `curl` dengan `Authorization:
   Bearer <token dari login>` → 200.
5. Kalau ada yang rusak → set `API_REQUIRE_AUTH=false`, redeploy, situs pulih
   seketika tanpa perlu revert kode.

## Berkas yang tersentuh

Backend: `app/core/config.py`, `app/core/auth.py`, `app/api/router.py`,
`app/main.py`, `app/tests/conftest.py` (baru),
`app/tests/test_api_auth_gate.py` (baru), `.env.dokploy.example`,
`.env.example`.

Frontend: `src/lib/api.ts`, `src/hooks/useDashboardData.ts`,
`src/components/KompleksKebakaranView.tsx`, `src/App.tsx`, test terkait.

Infra: `deploy/nginx/etaseneu.conf`, `docker-compose.dokploy.yml` (forward
`API_REQUIRE_AUTH`).

Docs: `CLAUDE.md` (bagian Autentikasi + Deploy).

## Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Bug plumbing token → situs terkunci | Flag `API_REQUIRE_AUTH` default false; aktifkan hanya setelah verifikasi; rollback = flip env, bukan revert kode |
| CSP memblok tile/font/overlay | Report-Only dulu; enforce setelah console bersih |
| `limit_req` terlalu ketat → user normal 429 | `burst` longgar di jalur umum; uji buka dashboard pasca-deploy; zona login ketat karena sudah ada Turnstile |
| `limit_req_zone` tidak bisa di-`include` pada `http` | Plan B: rate limit login pindah ke `slowapi` di aplikasi (dicatat di plan) |
| Test lama pecah karena gate | `conftest.py` autouse mematikan `API_REQUIRE_AUTH` untuk semua test lama |
| Automation X-Admin-Key putus | Router admin tidak ditumpuk gate baca; test #4 menjaga ini |

## Hasil audit dependency (2026-08-26)

**Frontend (`npm audit --omit=dev`)**: 0 kerentanan di dependency produksi.
Dependency dev/build (vite, vitest, esbuild, postcss, nanoid, form-data) punya
8 advisory → `npm audit fix` (tanpa `--force`) menurunkan ke 5; sisanya butuh
mayor bump vite/vitest (breaking) → follow-up. Tidak ikut ke bundle produksi.
Build + 44 test frontend hijau setelah `npm audit fix`.

**Backend (`pip-audit -r requirements.txt`)**:
- `PyJWT 2.10.1` → **di-bump `2.13.0`** (PYSEC-2025-183, PYSEC-2026-120/175-179).
  Kita pakai langsung untuk token sesi — prioritas. API stabil, 297 test hijau.
- `python-multipart 0.0.20` → **di-bump `0.0.31`** (PYSEC-2026-1852/3036-3040,
  DoS parsing multipart). Dipakai Starlette untuk upload. 297 test hijau.
- `starlette 0.46.2` (PYSEC-2026-161/248/249/1941/1942/2280/2281) → **ditunda**.
  Fix (`>=0.47`) di luar rentang pin `fastapi==0.115.12`; butuh upgrade FastAPI
  (perubahan lebih besar, tidak masuk scope ini). Sebagian CVE multipart-DoS
  ter-mitigasi `client_max_body_size` nginx + `limit_req` baru. Follow-up:
  upgrade FastAPI + Starlette bersamaan.
- `pytest 8.3.5` (PYSEC-2026-1845) → **ditunda**, test-only, tidak dikirim ke
  produksi; pytest 9 berpotensi breaking.

Catatan: PyJWT 2.13.0 memunculkan `InsecureKeyLengthWarning` pada test yang
memakai secret pendek (`"test-secret"`). Tidak muncul di produksi selama
`AUTH_JWT_SECRET` ≥ 32 byte (contoh di `.env.example` = `openssl rand -base64 48`).

## Di luar scope (follow-up terpisah)

- IP-allowlist `/api/metrics` untuk Prometheus.
- Refresh token / rotasi (TTL tetap 24 jam).
- Lockout akun setelah N gagal login (Turnstile + `limit_req` dianggap cukup
  untuk sekarang).
- Audit menyeluruh input `HotspotQuery` (sudah lewat Pydantic).
