# Polygon Metadata Sync and Hotspot Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist GeoJSON polygon metadata in PostgreSQL, track file changes in `shp/`, and power the Data Matrix from database-backed polygon queries and hotspot summaries.

**Architecture:** We will normalize GeoJSON feature properties into a dedicated `polygon_metadata` table, record file sync state in `geojson_file_registry`, and maintain hotspot-to-polygon joins plus summary rows for fast UI queries. Startup and manual refresh will rescan `shp/`, upsert changed features, soft-disable removed features, and rebuild the impacted hotspot mapping and summary data.

**Tech Stack:** FastAPI, PostgreSQL + PostGIS, psycopg, shapely/pyproj, React + Vite, pytest, Vitest.

---

### Task 1: Add polygon metadata tables and registry schema

**Files:**
- Modify: `backend/sql/init_etaseneu.sql:1-120`
- Modify: `backend/app/tests/test_cache_history_api.py:1-240`
- Create: `backend/app/tests/test_polygon_metadata_schema.py`

- [ ] **Step 1: Write the failing test**

```python
def test_polygon_metadata_schema_tables_exist() -> None:
    from pathlib import Path

    schema = Path("backend/sql/init_etaseneu.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS polygon_metadata" in schema
    assert "CREATE TABLE IF NOT EXISTS hotspot_polygon_relation" in schema
    assert "CREATE TABLE IF NOT EXISTS polygon_hotspot_summary" in schema
    assert "CREATE TABLE IF NOT EXISTS geojson_file_registry" in schema
```

```python
def test_polygon_metadata_schema_contains_key_columns() -> None:
    from pathlib import Path

    schema = Path("backend/sql/init_etaseneu.sql").read_text(encoding="utf-8")
    for needle in [
        "layer_key",
        "feature_key",
        "lembaga",
        "nama_prov",
        "nama_kab",
        "nama_kec",
        "nama_desa",
        "ps_id",
        "luas_final",
        "properties_raw",
        "is_active",
    ]:
        assert needle in schema
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && pytest app/tests/test_polygon_metadata_schema.py -v
```

Expected: FAIL because the new schema assertions are not yet implemented.

- [ ] **Step 3: Write minimal implementation**

Add these tables to `backend/sql/init_etaseneu.sql`:

```sql
CREATE TABLE IF NOT EXISTS polygon_metadata (
    id BIGSERIAL PRIMARY KEY,
    layer_key TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    feature_index INTEGER NOT NULL,
    lembaga TEXT,
    nama_prov TEXT,
    nama_kab TEXT,
    nama_kec TEXT,
    nama_desa TEXT,
    skema TEXT,
    no_sk TEXT,
    tgl_sk TEXT,
    status TEXT,
    wilker_bps TEXT,
    ps_id TEXT,
    kode_prov TEXT,
    kode_kab TEXT,
    luas_hk TEXT,
    luas_hl TEXT,
    luas_hpt TEXT,
    luas_hp TEXT,
    luas_hpk TEXT,
    luas_sk TEXT,
    luas_poli TEXT,
    luas_final TEXT,
    jml_kk TEXT,
    shape_leng TEXT,
    shape_area TEXT,
    geometry geometry(MultiPolygon, 4326) NOT NULL,
    properties_raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_file TEXT NOT NULL,
    file_checksum TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (layer_key, feature_key)
);

CREATE TABLE IF NOT EXISTS hotspot_polygon_relation (
    id BIGSERIAL PRIMARY KEY,
    hotspot_observation_id BIGINT NOT NULL,
    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
    layer_key TEXT NOT NULL,
    match_method TEXT NOT NULL,
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (hotspot_observation_id, polygon_metadata_id)
);

CREATE TABLE IF NOT EXISTS polygon_hotspot_summary (
    id BIGSERIAL PRIMARY KEY,
    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
    layer_key TEXT NOT NULL,
    year INTEGER NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    hotspot_count INTEGER NOT NULL DEFAULT 0,
    last_hotspot_at TIMESTAMPTZ,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    satellites JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (polygon_metadata_id, year)
);

CREATE TABLE IF NOT EXISTS geojson_file_registry (
    id BIGSERIAL PRIMARY KEY,
    file_name TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    layer_key TEXT NOT NULL,
    checksum TEXT NOT NULL,
    mtime TIMESTAMPTZ NOT NULL,
    last_synced_at TIMESTAMPTZ,
    last_sync_status TEXT NOT NULL DEFAULT 'pending',
    last_sync_message TEXT NOT NULL DEFAULT '',
    feature_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Also extend the existing hotspot sync-state assertions if needed so the new schema does not regress the current tables.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend && pytest app/tests/test_polygon_metadata_schema.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/sql/init_etaseneu.sql backend/app/tests/test_polygon_metadata_schema.py backend/app/tests/test_cache_history_api.py
git commit -m "feat: add polygon metadata schema"
```

### Task 2: Import GeoJSON files into polygon metadata and file registry

**Files:**
- Modify: `backend/app/services/layer_service.py`
- Modify: `backend/app/services/postgres_store.py`
- Create: `backend/app/services/geojson_sync_service.py`
- Create: `backend/app/tests/test_geojson_sync_service.py`
- Modify: `backend/app/tests/test_layer_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_geojson_sync_service_upserts_polygons_and_registry(tmp_path):
    from app.services.geojson_sync_service import GeoJsonSyncService

    shp_dir = tmp_path / "shp"
    shp_dir.mkdir()
    (shp_dir / "sample.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"LEMBAGA":"Demo","NAMA_PROV":"Jawa Tengah","PS_ID":123},"geometry":{"type":"Polygon","coordinates":[[[110.0,-7.0],[110.1,-7.0],[110.1,-7.1],[110.0,-7.1],[110.0,-7.0]]]}}]}',
        encoding="utf-8",
    )

    service = GeoJsonSyncService(shp_dir=shp_dir, database_url="")
    result = service.sync_all()

    assert result["files_scanned"] == 1
    assert result["files_changed"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && pytest app/tests/test_geojson_sync_service.py -v
```

Expected: FAIL because the sync service does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/geojson_sync_service.py` with a service that:

```python
class GeoJsonSyncService:
    def __init__(self, shp_dir: Path, database_url: str) -> None: ...
    def sync_all(self) -> dict[str, int]: ...
    def sync_file(self, path: Path) -> dict[str, object]: ...
```

Implementation rules:

- compute file checksum and mtime
- compare against `geojson_file_registry`
- upsert `polygon_metadata` rows by `(layer_key, feature_key)`
- mark missing features inactive
- mark removed files inactive
- keep the original `properties` JSON in `properties_raw`

Extend `PostgresStore` with methods that support:

```python
upsert_polygon_metadata(...)
read_geojson_file_registry(...)
upsert_geojson_file_registry(...)
deactivate_missing_polygons(...)
```

Also update `LayerService` so database sync remains a side effect of layer discovery instead of manual duplication.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend && pytest app/tests/test_geojson_sync_service.py app/tests/test_layer_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/geojson_sync_service.py backend/app/services/postgres_store.py backend/app/services/layer_service.py backend/app/tests/test_geojson_sync_service.py backend/app/tests/test_layer_service.py
git commit -m "feat: sync geojson metadata into postgres"
```

### Task 3: Build hotspot-to-polygon relation and summary refresh

**Files:**
- Modify: `backend/app/services/spatial_service.py`
- Modify: `backend/app/services/hotspot_service.py`
- Modify: `backend/app/services/postgres_store.py`
- Create: `backend/app/tests/test_polygon_relation_service.py`
- Modify: `backend/app/tests/test_spatial_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_spatial_service_attaches_polygon_metadata_and_polygon_id() -> None:
    from app.services.spatial_service import filter_hotspots_by_layers

    hotspots = [{"latitude": -7.0, "longitude": 110.0, "source": "MODIS", "satellite": "Terra", "detected_at": "2026-05-28T00:00:00Z"}]
    layers = [
        {
            "id": "sample",
            "name": "Demo",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[109.5, -7.5], [110.5, -7.5], [110.5, -6.5], [109.5, -6.5], [109.5, -7.5]]],
            },
            "province_name": "Jawa Tengah",
            "metadata": {"LEMBAGA": "Demo Lembaga", "NAMA_PROV": "Jawa Tengah"},
        }
    ]

    result = filter_hotspots_by_layers(hotspots, layers)
    assert result[0]["polygon_metadata"]["LEMBAGA"] == "Demo Lembaga"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && pytest app/tests/test_spatial_service.py -v
```

Expected: FAIL if the new relation metadata hooks are not yet complete.

- [ ] **Step 3: Write minimal implementation**

Add relation and summary persistence helpers to `PostgresStore`:

```python
upsert_hotspot_polygon_relation(...)
rebuild_polygon_hotspot_summary(...)
read_polygon_hotspot_summary(...)
```

Update `HotspotService.fetch_filtered_hotspots()` so after filtering hotspots it:

1. writes the filtered hotspot rows to `hotspot_observations`
2. writes hotspot-polygon relations for each matched hotspot
3. rebuilds the impacted `polygon_hotspot_summary` rows

Keep the current cache and history archive behavior intact.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend && pytest app/tests/test_spatial_service.py app/tests/test_hotspot_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/spatial_service.py backend/app/services/hotspot_service.py backend/app/services/postgres_store.py backend/app/tests/test_polygon_relation_service.py backend/app/tests/test_spatial_service.py backend/app/tests/test_hotspot_service.py
git commit -m "feat: link hotspots to polygon metadata"
```

### Task 4: Expose polygon metadata status and refresh endpoints

**Files:**
- Modify: `backend/app/api/cache.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/services/postgres_store.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/tests/test_geojson_sync_api.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import json


async def _request_geojson_refresh() -> tuple[int, dict]:
    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/geojson/refresh",
        "raw_path": b"/api/geojson/refresh",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)

    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")
    payload = json.loads(body["body"].decode("utf-8"))
    return start["status"], payload


def test_geojson_refresh_endpoint_returns_summary(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / ".cache"))

    try:
        status, body = asyncio.run(_request_geojson_refresh())

        assert status == 200
        assert "files_scanned" in body
        assert "files_changed" in body
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && pytest app/tests/test_geojson_sync_api.py app/tests/test_cache_history_api.py -v
```

Expected: FAIL until the new endpoint and table status are wired.

- [ ] **Step 3: Write minimal implementation**

Add endpoints:

```python
@router.post("/geojson/refresh")
async def refresh_geojson() -> dict[str, object]:
    ...

@router.get("/geojson/status")
async def geojson_status() -> dict[str, object]:
    ...
```

Expose registry counts in `storage_status()`:

```python
"geojson_file_registry": geojson_registry_total
```

Wire the app startup hook so GeoJSON sync runs once at boot, but keep it fast when no files changed.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend && pytest app/tests/test_geojson_sync_api.py app/tests/test_cache_history_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/cache.py backend/app/api/router.py backend/app/main.py backend/app/services/postgres_store.py backend/app/tests/test_geojson_sync_api.py
git commit -m "feat: add geojson sync endpoints"
```

### Task 5: Switch Data Matrix to database-backed polygon queries

**Files:**
- Modify: `frontend/src/components/HotspotMatrix.tsx`
- Modify: `frontend/src/hooks/useDashboardData.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/types/api.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/index.css`
- Create: `frontend/src/test/HotspotMatrix.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { HotspotMatrix } from "../components/HotspotMatrix";

test("renders polygon metadata groups from hotspot metadata", () => {
  render(
    <HotspotMatrix
      hotspots={[
        {
          id: "1",
          detectedAt: "2026-05-28T00:00:00Z",
          latitude: -7,
          longitude: 110,
          layerName: "sample",
          agencyName: "Demo Lembaga",
          provinceName: "Jawa Tengah",
          polygonMetadata: {
            LEMBAGA: "Demo Lembaga",
            NAMA_PROV: "Jawa Tengah",
            PS_ID: "123",
            LuasFinal: "99.1",
            Jml_KK: "42",
          },
          source: "MODIS",
          satellite: "Terra",
          brightness: 123.45,
          confidence: "n",
        },
      ]}
      onExport={() => undefined}
      isExporting={false}
      dateRangeLabel="24 jam terakhir"
    />
  );

  expect(screen.getByText("Identity")).toBeInTheDocument();
  expect(screen.getByText("LEMBAGA")).toBeInTheDocument();
  expect(screen.getByText("Demo Lembaga")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend && npm test -- --runInBand
```

Expected: FAIL until the matrix rendering matches the new grouped query layout.

- [ ] **Step 3: Write minimal implementation**

Update the UI so the matrix:

- reads `polygonMetadata` from the API payload
- renders the new group/stack query layout
- keeps the current dark command-center styling
- shows summary rows above detail rows

Extend API typings to include the new polygon metadata fields returned by the backend, especially:

```ts
polygon_metadata?: Record<string, string>;
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd frontend && npm test -- --runInBand && npm run build
```

Expected: PASS for tests and build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HotspotMatrix.tsx frontend/src/hooks/useDashboardData.ts frontend/src/lib/api.ts frontend/src/types/api.ts frontend/src/App.tsx frontend/src/index.css frontend/src/test/HotspotMatrix.test.tsx
git commit -m "feat: render polygon metadata matrix from db"
```

### Task 6: Verify startup sync and local end-to-end behavior

**Files:**
- Modify: `backend/app/tests/test_geojson_sync_api.py`
- Modify: `backend/app/tests/test_layers_api.py`
- Modify: `frontend/src/test/App.test.tsx`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
import json


async def _request_geojson_status() -> tuple[int, dict]:
    from app.main import create_app

    app = create_app()
    messages: list[dict] = []
    request_sent = False

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/geojson/status",
        "raw_path": b"/api/geojson/status",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    await app(scope, receive, send)

    start = next(message for message in messages if message["type"] == "http.response.start")
    body = next(message for message in messages if message["type"] == "http.response.body")
    payload = json.loads(body["body"].decode("utf-8"))
    return start["status"], payload


def test_geojson_status_endpoint_reports_registry(monkeypatch, tmp_path) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SHP_DIR", "app/tests/fixtures/shp")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / ".cache"))

    try:
        status, body = asyncio.run(_request_geojson_status())

        assert status == 200
        assert "files" in body
        assert "registry" in body
    finally:
        get_settings.cache_clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend && pytest app/tests/test_geojson_sync_api.py app/tests/test_layers_api.py -v
```

Expected: PASS only after the startup sync and refresh flow is wired.

- [ ] **Step 3: Write minimal implementation**

Confirm the app boots, layers still load, polygon sync status is visible, and the matrix still loads hotspot data after the new database tables are introduced.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend && pytest app/tests/test_geojson_sync_api.py app/tests/test_layers_api.py -v && cd ../frontend && npm test -- --runInBand && npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tests/test_geojson_sync_api.py backend/app/tests/test_layers_api.py frontend/src/test/App.test.tsx
git commit -m "test: verify geojson sync and matrix flow"
```
