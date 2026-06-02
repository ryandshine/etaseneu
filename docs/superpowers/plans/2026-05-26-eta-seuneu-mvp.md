# ETA SEUNEU MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a localhost-first ETA SEUNEU MVP with a FastAPI backend and React/Vite frontend that reads GeoJSON layers from `shp/`, fetches and caches NASA FIRMS hotspot data server-side, filters hotspots by active layers/date/satellites, renders them on a Leaflet map, shows synchronized stats, and exports filtered results to Excel.

**Architecture:** The backend owns configuration, GeoJSON discovery, NASA fetch/caching, hotspot normalization, point-in-polygon filtering, stats aggregation, and Excel generation. The frontend consumes backend APIs for layers, hotspots, stats, and export, then renders a single-page operational map with a floating filter panel. The first target runtime is `localhost`, but config and CORS are structured to remain deployable later.

**Tech Stack:** Python 3 + FastAPI + Pydantic + httpx + Shapely + openpyxl + pytest, React + Vite + TypeScript + Tailwind CSS + React Leaflet + Vitest + Testing Library

---

### Task 1: Create backend skeleton and dependency baseline

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/router.py`
- Create: `backend/app/tests/test_health.py`

- [ ] **Step 1: Write the failing backend health test**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run the backend health test to verify it fails**

Run: `cd backend && pytest app/tests/test_health.py -v`
Expected: FAIL because `app.main` and the FastAPI app do not exist yet.

- [ ] **Step 3: Add backend dependencies**

```text
fastapi==0.115.12
uvicorn[standard]==0.34.2
pydantic==2.11.5
pydantic-settings==2.9.1
httpx==0.28.1
shapely==2.1.1
openpyxl==3.1.5
python-multipart==0.0.20
pytest==8.3.5
pytest-cov==6.1.1
```

- [ ] **Step 4: Create the minimal backend app and router**

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ETA SEUNEU API"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5173"


settings = Settings()
```

```python
# backend/app/api/router.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

```python
# backend/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.core.config import settings

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)
```

- [ ] **Step 5: Run the backend health test to verify it passes**

Run: `cd backend && pytest app/tests/test_health.py -v`
Expected: PASS

- [ ] **Step 6: Commit the backend skeleton**

```bash
git add backend
git commit -m "feat: scaffold FastAPI backend"
```

### Task 2: Implement backend settings, environment file, and layer test fixtures

**Files:**
- Create: `backend/.env.example`
- Create: `backend/app/tests/fixtures/empty-shp/.gitkeep`
- Create: `backend/app/tests/fixtures/shp/sample_area.geojson`
- Modify: `backend/app/core/config.py`
- Create: `backend/app/tests/test_config.py`

- [ ] **Step 1: Write the failing settings test**

```python
from app.core.config import Settings


def test_settings_use_local_defaults() -> None:
    settings = Settings(
        nasa_firms_api_key="demo-key",
        shp_dir="../shp",
        cache_dir=".cache",
    )

    assert settings.api_prefix == "/api"
    assert settings.frontend_origin == "http://localhost:5173"
    assert settings.shp_dir == "../shp"
    assert settings.cache_dir == ".cache"
```

- [ ] **Step 2: Run the settings test to verify it fails**

Run: `cd backend && pytest app/tests/test_config.py -v`
Expected: FAIL because the new config fields do not exist yet.

- [ ] **Step 3: Expand settings and add example env**

```python
# backend/app/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ETA SEUNEU API"
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5173"
    nasa_firms_api_key: str = ""
    shp_dir: str = "../shp"
    cache_dir: str = ".cache"
    cache_ttl_hours: int = 24
    request_timeout_seconds: float = 30.0
```

```env
# backend/.env.example
NASA_FIRMS_API_KEY=replace-me
FRONTEND_ORIGIN=http://localhost:5173
SHP_DIR=../shp
CACHE_DIR=.cache
CACHE_TTL_HOURS=24
REQUEST_TIMEOUT_SECONDS=30
```

- [ ] **Step 4: Add GeoJSON fixture for later layer tests**

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "name": "Sample Patrol Area"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [95.0, 4.0],
            [95.2, 4.0],
            [95.2, 4.2],
            [95.0, 4.2],
            [95.0, 4.0]
          ]
        ]
      }
    }
  ]
}
```

- [ ] **Step 5: Run the settings test to verify it passes**

Run: `cd backend && pytest app/tests/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit configuration and fixtures**

```bash
git add backend
git commit -m "feat: add backend configuration defaults"
```

### Task 3: Build GeoJSON layer discovery and `/api/layers`

**Files:**
- Create: `backend/app/models/layers.py`
- Create: `backend/app/services/layer_service.py`
- Create: `backend/app/api/layers.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/app/tests/test_layer_service.py`
- Create: `backend/app/tests/test_layers_api.py`

- [ ] **Step 1: Write the failing layer service test**

```python
from pathlib import Path

from app.services.layer_service import LayerService


def test_layer_service_loads_geojson_layers() -> None:
    fixture_dir = Path("app/tests/fixtures/shp")
    service = LayerService(fixture_dir)

    layers = service.list_layers()

    assert len(layers) == 1
    assert layers[0].id == "sample_area"
    assert layers[0].name == "sample_area"
    assert layers[0].feature_count == 1
```

- [ ] **Step 2: Run the layer service test to verify it fails**

Run: `cd backend && pytest app/tests/test_layer_service.py -v`
Expected: FAIL because the service and models do not exist yet.

- [ ] **Step 3: Implement layer models and service**

```python
# backend/app/models/layers.py
from pydantic import BaseModel


class LayerBounds(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


class LayerFeature(BaseModel):
    id: str
    name: str
    color: str
    active: bool
    feature_count: int
    bounds: LayerBounds
    geojson: dict
```

```python
# backend/app/services/layer_service.py
import json
from pathlib import Path

from shapely.geometry import shape

from app.models.layers import LayerBounds, LayerFeature

LAYER_COLORS = ["#1d4ed8", "#059669", "#dc2626", "#d97706", "#7c3aed"]


class LayerService:
    def __init__(self, shp_dir: Path) -> None:
        self.shp_dir = shp_dir

    def list_layers(self) -> list[LayerFeature]:
        layers: list[LayerFeature] = []
        for index, path in enumerate(sorted(self.shp_dir.glob("*.geojson"))):
            payload = json.loads(path.read_text())
            geometry = shape(payload["features"][0]["geometry"])
            min_lon, min_lat, max_lon, max_lat = geometry.bounds
            layers.append(
                LayerFeature(
                    id=path.stem,
                    name=path.stem,
                    color=LAYER_COLORS[index % len(LAYER_COLORS)],
                    active=True,
                    feature_count=len(payload["features"]),
                    bounds=LayerBounds(
                        min_lat=min_lat,
                        min_lon=min_lon,
                        max_lat=max_lat,
                        max_lon=max_lon,
                    ),
                    geojson=payload,
                )
            )
        return layers
```

- [ ] **Step 4: Add failing API test for `/api/layers`**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_layers_endpoint_returns_detected_layers() -> None:
    response = client.get("/api/layers")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert "layers" in body
```

- [ ] **Step 5: Implement the layers endpoint and register it**

```python
# backend/app/api/layers.py
from pathlib import Path

from fastapi import APIRouter

from app.core.config import settings
from app.services.layer_service import LayerService

router = APIRouter()


@router.get("/layers")
def list_layers() -> dict:
    service = LayerService(Path(settings.shp_dir))
    layers = service.list_layers()
    return {"count": len(layers), "layers": [layer.model_dump() for layer in layers]}
```

```python
# backend/app/api/router.py
from fastapi import APIRouter

from app.api.layers import router as layers_router

router = APIRouter()
router.include_router(layers_router)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 6: Run the layer tests to verify they pass**

Run: `cd backend && pytest app/tests/test_layer_service.py app/tests/test_layers_api.py -v`
Expected: PASS

- [ ] **Step 7: Commit layer discovery**

```bash
git add backend
git commit -m "feat: add geojson layer discovery"
```

### Task 4: Add NASA client and sample normalization tests

**Files:**
- Create: `backend/app/models/hotspots.py`
- Create: `backend/app/services/nasa_client.py`
- Create: `backend/app/services/hotspot_normalizer.py`
- Create: `backend/app/tests/fixtures/nasa/modis_response.csv`
- Create: `backend/app/tests/fixtures/nasa/viirs_response.csv`
- Create: `backend/app/tests/test_hotspot_normalizer.py`

- [ ] **Step 1: Write the failing normalization test**

```python
from app.services.hotspot_normalizer import normalize_hotspots


def test_normalize_modis_rows() -> None:
    rows = [
        {
            "latitude": "4.10",
            "longitude": "95.10",
            "brightness": "330.4",
            "acq_date": "2026-05-24",
            "acq_time": "0612",
            "confidence": "78",
            "satellite": "Terra",
        }
    ]

    normalized = normalize_hotspots(rows, source="MODIS")

    assert normalized[0]["source"] == "MODIS"
    assert normalized[0]["latitude"] == 4.10
    assert normalized[0]["longitude"] == 95.10
    assert normalized[0]["detected_at"] == "2026-05-24T06:12:00"
```

- [ ] **Step 2: Run the normalization test to verify it fails**

Run: `cd backend && pytest app/tests/test_hotspot_normalizer.py -v`
Expected: FAIL because the normalizer does not exist yet.

- [ ] **Step 3: Implement the hotspot model and normalizer**

```python
# backend/app/models/hotspots.py
from pydantic import BaseModel


class HotspotRecord(BaseModel):
    source: str
    satellite: str
    latitude: float
    longitude: float
    brightness: float | None = None
    confidence: str | None = None
    detected_at: str
```

```python
# backend/app/services/hotspot_normalizer.py
from datetime import datetime


def normalize_hotspots(rows: list[dict[str, str]], source: str) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        detected_at = datetime.strptime(
            f"{row['acq_date']} {row['acq_time'].zfill(4)}",
            "%Y-%m-%d %H%M",
        ).isoformat()
        normalized.append(
            {
                "source": source,
                "satellite": row.get("satellite", source),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
                "brightness": float(row["brightness"]) if row.get("brightness") else None,
                "confidence": row.get("confidence"),
                "detected_at": detected_at,
            }
        )
    return normalized
```

- [ ] **Step 4: Add the NASA client shell**

```python
# backend/app/services/nasa_client.py
from collections.abc import Iterable

import httpx

from app.core.config import settings


class NasaFirmsClient:
    def __init__(self) -> None:
        self.base_url = "https://firms.modaps.eosdis.nasa.gov/api/country/csv"

    async def fetch_rows(self, path: str) -> Iterable[dict[str, str]]:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(path)
            response.raise_for_status()
            return []
```

- [ ] **Step 5: Run the normalization test to verify it passes**

Run: `cd backend && pytest app/tests/test_hotspot_normalizer.py -v`
Expected: PASS

- [ ] **Step 6: Commit hotspot normalization**

```bash
git add backend
git commit -m "feat: add hotspot normalization model"
```

### Task 5: Add file-based cache service and tests

**Files:**
- Create: `backend/app/services/cache_service.py`
- Create: `backend/app/tests/test_cache_service.py`
- Modify: `backend/app/core/config.py`

- [ ] **Step 1: Write the failing cache service test**

```python
from pathlib import Path

from app.services.cache_service import CacheService


def test_cache_service_stores_and_reads_payload(tmp_path: Path) -> None:
    service = CacheService(tmp_path, ttl_hours=24)
    payload = [{"source": "MODIS", "latitude": 4.1, "longitude": 95.1}]

    service.write("modis-2026-01-01-2026-05-26", payload)
    cached = service.read("modis-2026-01-01-2026-05-26")

    assert cached == payload
```

- [ ] **Step 2: Run the cache service test to verify it fails**

Run: `cd backend && pytest app/tests/test_cache_service.py -v`
Expected: FAIL because the cache service does not exist yet.

- [ ] **Step 3: Implement the file cache**

```python
# backend/app/services/cache_service.py
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


class CacheService:
    def __init__(self, cache_dir: Path, ttl_hours: int) -> None:
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def read(self, key: str) -> list[dict] | None:
        path = self._path(key)
        if not path.exists():
            return None
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - modified > self.ttl:
            return None
        return json.loads(path.read_text())

    def write(self, key: str, payload: list[dict]) -> None:
        self._path(key).write_text(json.dumps(payload))
```

- [ ] **Step 4: Run the cache service test to verify it passes**

Run: `cd backend && pytest app/tests/test_cache_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit the cache layer**

```bash
git add backend
git commit -m "feat: add local nasa cache service"
```

### Task 6: Implement spatial filtering service and stats aggregation

**Files:**
- Create: `backend/app/services/spatial_service.py`
- Create: `backend/app/services/stats_service.py`
- Create: `backend/app/tests/test_spatial_service.py`
- Create: `backend/app/tests/test_stats_service.py`

- [ ] **Step 1: Write the failing spatial filter test**

```python
from app.services.spatial_service import filter_hotspots_by_layers


def test_filter_hotspots_by_layers_keeps_points_inside_polygon() -> None:
    hotspots = [
        {"latitude": 4.1, "longitude": 95.1, "source": "MODIS"},
        {"latitude": 6.0, "longitude": 97.0, "source": "MODIS"},
    ]
    layers = [
        {
            "id": "sample_area",
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[95.0, 4.0], [95.2, 4.0], [95.2, 4.2], [95.0, 4.2], [95.0, 4.0]]],
                        },
                        "properties": {},
                    }
                ],
            },
        }
    ]

    filtered = filter_hotspots_by_layers(hotspots, layers)

    assert len(filtered) == 1
    assert filtered[0]["latitude"] == 4.1
```

- [ ] **Step 2: Run the spatial filter test to verify it fails**

Run: `cd backend && pytest app/tests/test_spatial_service.py -v`
Expected: FAIL because the spatial service does not exist yet.

- [ ] **Step 3: Implement spatial filtering and per-record layer tagging**

```python
# backend/app/services/spatial_service.py
from shapely.geometry import Point, shape
from shapely.ops import unary_union


def filter_hotspots_by_layers(hotspots: list[dict], layers: list[dict]) -> list[dict]:
    polygons = []
    for layer in layers:
        for feature in layer["geojson"]["features"]:
            polygons.append(shape(feature["geometry"]))
    if not polygons:
        return []

    active_union = unary_union(polygons)
    filtered: list[dict] = []
    for hotspot in hotspots:
        point = Point(hotspot["longitude"], hotspot["latitude"])
        if active_union.covers(point):
            filtered.append(hotspot)
    return filtered
```

- [ ] **Step 4: Write the failing stats aggregation test**

```python
from app.services.stats_service import build_stats


def test_build_stats_returns_total_and_breakdown() -> None:
    stats = build_stats(
        [
            {"source": "MODIS", "layer_name": "sample_area"},
            {"source": "VIIRS S-NPP", "layer_name": "sample_area"},
            {"source": "MODIS", "layer_name": "sample_area"},
        ]
    )

    assert stats["total"] == 3
    assert stats["by_source"]["MODIS"] == 2
    assert stats["by_layer"]["sample_area"] == 3
```

- [ ] **Step 5: Implement the stats service**

```python
# backend/app/services/stats_service.py
from collections import Counter


def build_stats(hotspots: list[dict]) -> dict:
    return {
        "total": len(hotspots),
        "by_source": dict(Counter(item["source"] for item in hotspots)),
        "by_layer": dict(Counter(item.get("layer_name", "unknown") for item in hotspots)),
    }
```

- [ ] **Step 6: Run the spatial and stats tests to verify they pass**

Run: `cd backend && pytest app/tests/test_spatial_service.py app/tests/test_stats_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit filtering and stats**

```bash
git add backend
git commit -m "feat: add spatial filtering and stats services"
```

### Task 7: Build hotspot query orchestration and API endpoints

**Files:**
- Create: `backend/app/models/query.py`
- Create: `backend/app/services/hotspot_service.py`
- Create: `backend/app/api/hotspots.py`
- Create: `backend/app/api/stats.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/app/tests/test_hotspots_api.py`
- Create: `backend/app/tests/test_stats_api.py`

- [ ] **Step 1: Write the failing hotspots API test**

```python
from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_hotspots_endpoint_returns_collection() -> None:
    response = client.get(
        "/api/hotspots",
        params={
            "start_date": "2026-01-01",
            "end_date": "2026-05-26",
            "satellites": ["MODIS"],
            "active_layers": ["sample_area"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "hotspots" in body
    assert "count" in body
```

- [ ] **Step 2: Run the hotspots API test to verify it fails**

Run: `cd backend && pytest app/tests/test_hotspots_api.py -v`
Expected: FAIL because the endpoint does not exist yet.

- [ ] **Step 3: Implement query schema and hotspot orchestration**

```python
# backend/app/models/query.py
from pydantic import BaseModel


class HotspotQuery(BaseModel):
    start_date: str
    end_date: str
    satellites: list[str]
    active_layers: list[str]
```

```python
# backend/app/services/hotspot_service.py
from pathlib import Path

from app.core.config import settings
from app.services.cache_service import CacheService
from app.services.layer_service import LayerService
from app.services.spatial_service import filter_hotspots_by_layers
from app.services.stats_service import build_stats


class HotspotService:
    def __init__(self) -> None:
        self.layer_service = LayerService(Path(settings.shp_dir))
        self.cache_service = CacheService(Path(settings.cache_dir), ttl_hours=settings.cache_ttl_hours)

    async def fetch_filtered_hotspots(self, query: dict) -> dict:
        active_layers = [
            layer.model_dump()
            for layer in self.layer_service.list_layers()
            if layer.id in query["active_layers"]
        ]
        hotspots = []
        filtered = filter_hotspots_by_layers(hotspots, active_layers)
        return {"count": len(filtered), "hotspots": filtered, "stats": build_stats(filtered)}
```

- [ ] **Step 4: Implement `/api/hotspots` and `/api/stats`**

```python
# backend/app/api/hotspots.py
from fastapi import APIRouter, Query

from app.services.hotspot_service import HotspotService

router = APIRouter()


@router.get("/hotspots")
async def get_hotspots(
    start_date: str,
    end_date: str,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
) -> dict:
    service = HotspotService()
    return await service.fetch_filtered_hotspots(
        {
            "start_date": start_date,
            "end_date": end_date,
            "satellites": satellites,
            "active_layers": active_layers,
        }
    )
```

```python
# backend/app/api/stats.py
from fastapi import APIRouter, Query

from app.services.hotspot_service import HotspotService

router = APIRouter()


@router.get("/stats")
async def get_stats(
    start_date: str,
    end_date: str,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
) -> dict:
    service = HotspotService()
    result = await service.fetch_filtered_hotspots(
        {
            "start_date": start_date,
            "end_date": end_date,
            "satellites": satellites,
            "active_layers": active_layers,
        }
    )
    return result["stats"]
```

- [ ] **Step 5: Run the hotspots and stats API tests to verify they pass**

Run: `cd backend && pytest app/tests/test_hotspots_api.py app/tests/test_stats_api.py -v`
Expected: PASS with the orchestration shell returning the response shape even before NASA integration is complete.

- [ ] **Step 6: Commit hotspot query endpoints**

```bash
git add backend
git commit -m "feat: add hotspot query endpoints"
```

### Task 8: Implement Excel export and refresh endpoint

**Files:**
- Create: `backend/app/services/export_service.py`
- Create: `backend/app/api/export.py`
- Create: `backend/app/api/cache.py`
- Modify: `backend/app/api/router.py`
- Create: `backend/app/tests/test_export_service.py`
- Create: `backend/app/tests/test_export_api.py`

- [ ] **Step 1: Write the failing export service test**

```python
from app.services.export_service import build_export_rows


def test_build_export_rows_maps_hotspot_fields() -> None:
    rows = build_export_rows(
        [
            {
                "layer_name": "sample_area",
                "source": "MODIS",
                "detected_at": "2026-05-24T06:12:00",
                "latitude": 4.1,
                "longitude": 95.1,
                "confidence": "78",
                "brightness": 330.4,
            }
        ]
    )

    assert rows[0]["Nama Wilayah"] == "sample_area"
    assert rows[0]["Satelit"] == "MODIS"
```

- [ ] **Step 2: Run the export service test to verify it fails**

Run: `cd backend && pytest app/tests/test_export_service.py -v`
Expected: FAIL because the export service does not exist yet.

- [ ] **Step 3: Implement row mapping and workbook creation**

```python
# backend/app/services/export_service.py
from io import BytesIO

from openpyxl import Workbook


def build_export_rows(hotspots: list[dict]) -> list[dict]:
    rows = []
    for index, hotspot in enumerate(hotspots, start=1):
        rows.append(
            {
                "No": index,
                "Nama Wilayah": hotspot.get("layer_name", ""),
                "Satelit": hotspot.get("source", ""),
                "Tanggal Deteksi": hotspot.get("detected_at", ""),
                "Latitude": hotspot.get("latitude", ""),
                "Longitude": hotspot.get("longitude", ""),
                "Confidence": hotspot.get("confidence", ""),
                "Brightness": hotspot.get("brightness", ""),
            }
        )
    return rows


def build_excel_file(hotspots: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    rows = build_export_rows(hotspots)
    headers = list(rows[0].keys()) if rows else ["No", "Nama Wilayah", "Satelit", "Tanggal Deteksi", "Latitude", "Longitude", "Confidence", "Brightness"]
    sheet.append(headers)
    for row in rows:
        sheet.append(list(row.values()))
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Implement `/api/export.xlsx` and `/api/cache/refresh`**

```python
# backend/app/api/export.py
from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.services.export_service import build_excel_file
from app.services.hotspot_service import HotspotService

router = APIRouter()


@router.get("/export.xlsx")
async def export_hotspots(
    start_date: str,
    end_date: str,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
) -> Response:
    service = HotspotService()
    result = await service.fetch_filtered_hotspots(
        {
            "start_date": start_date,
            "end_date": end_date,
            "satellites": satellites,
            "active_layers": active_layers,
        }
    )
    content = build_excel_file(result["hotspots"])
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=eta-seuneu-hotspots.xlsx"},
    )
```

```python
# backend/app/api/cache.py
from fastapi import APIRouter

router = APIRouter()


@router.post("/cache/refresh")
async def refresh_cache() -> dict[str, str]:
    return {"status": "queued"}
```

- [ ] **Step 5: Run the export tests to verify they pass**

Run: `cd backend && pytest app/tests/test_export_service.py app/tests/test_export_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit export support**

```bash
git add backend
git commit -m "feat: add excel export support"
```

### Task 9: Scaffold frontend app and API client baseline

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/types/api.ts`
- Create: `frontend/src/test/App.test.tsx`

- [ ] **Step 1: Write the failing frontend smoke test**

```tsx
import { render, screen } from "@testing-library/react";
import App from "../App";


test("renders ETA SEUNEU title", () => {
  render(<App />);

  expect(screen.getByText(/ETA SEUNEU/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the frontend smoke test to verify it fails**

Run: `cd frontend && npm test -- --runInBand`
Expected: FAIL because the frontend app does not exist yet.

- [ ] **Step 3: Create the frontend package and base app**

```json
{
  "name": "eta-seuneu-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest"
  },
  "dependencies": {
    "react": "^19.1.0",
    "react-dom": "^19.1.0",
    "react-leaflet": "^5.0.0",
    "leaflet": "^1.9.4"
  },
  "devDependencies": {
    "@testing-library/react": "^16.3.0",
    "@types/leaflet": "^1.9.20",
    "@types/react": "^19.1.6",
    "@types/react-dom": "^19.1.5",
    "@vitejs/plugin-react": "^4.5.0",
    "tailwindcss": "^3.4.17",
    "typescript": "^5.8.3",
    "vite": "^6.3.5",
    "vitest": "^3.1.4"
  }
}
```

```tsx
// frontend/src/App.tsx
export default function App() {
  return (
    <main>
      <h1>ETA SEUNEU</h1>
      <p>Operational hotspot monitoring map</p>
    </main>
  );
}
```

- [ ] **Step 4: Create the API client shell**

```ts
// frontend/src/lib/api.ts
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}
```

- [ ] **Step 5: Run the frontend smoke test to verify it passes**

Run: `cd frontend && npm test -- --runInBand`
Expected: PASS

- [ ] **Step 6: Commit the frontend skeleton**

```bash
git add frontend
git commit -m "feat: scaffold React frontend"
```

### Task 10: Build frontend layer loading and filter state

**Files:**
- Create: `frontend/src/hooks/useDashboardData.ts`
- Create: `frontend/src/components/LayerList.tsx`
- Create: `frontend/src/components/FilterPanel.tsx`
- Create: `frontend/src/components/StatCards.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/test/FilterPanel.test.tsx`

- [ ] **Step 1: Write the failing filter panel test**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { FilterPanel } from "../components/FilterPanel";


test("calls layer toggle handler", () => {
  const onToggle = vi.fn();

  render(
    <FilterPanel
      layers={[{ id: "sample_area", name: "sample_area", active: true, color: "#1d4ed8" }]}
      selectedSatellites={["MODIS"]}
      onToggleLayer={onToggle}
      onToggleSatellite={() => {}}
      onDateChange={() => {}}
      startDate="2026-01-01"
      endDate="2026-05-26"
    />
  );

  fireEvent.click(screen.getByLabelText(/sample_area/i));
  expect(onToggle).toHaveBeenCalledWith("sample_area");
});
```

- [ ] **Step 2: Run the filter panel test to verify it fails**

Run: `cd frontend && npm test -- --runInBand src/test/FilterPanel.test.tsx`
Expected: FAIL because the component and props do not exist yet.

- [ ] **Step 3: Implement dashboard data hook with local state**

```ts
// frontend/src/hooks/useDashboardData.ts
import { useEffect, useState, useTransition } from "react";

import { fetchJson } from "../lib/api";

export function useDashboardData() {
  const [layers, setLayers] = useState([]);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    startTransition(() => {
      fetchJson("/layers").then((data: any) => {
        setLayers(data.layers);
      });
    });
  }, []);

  return { layers, isPending };
}
```

- [ ] **Step 4: Implement filter panel and stat cards**

```tsx
// frontend/src/components/FilterPanel.tsx
type LayerItem = { id: string; name: string; active: boolean; color: string };

type FilterPanelProps = {
  layers: LayerItem[];
  selectedSatellites: string[];
  startDate: string;
  endDate: string;
  onToggleLayer: (id: string) => void;
  onToggleSatellite: (value: string) => void;
  onDateChange: (field: "startDate" | "endDate", value: string) => void;
};

export function FilterPanel(props: FilterPanelProps) {
  return (
    <aside>
      <h2>Filters</h2>
      {props.layers.map((layer) => (
        <label key={layer.id}>
          <input
            type="checkbox"
            aria-label={layer.name}
            checked={layer.active}
            onChange={() => props.onToggleLayer(layer.id)}
          />
          {layer.name}
        </label>
      ))}
    </aside>
  );
}
```

- [ ] **Step 5: Run the filter panel test to verify it passes**

Run: `cd frontend && npm test -- --runInBand src/test/FilterPanel.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit filter state UI**

```bash
git add frontend
git commit -m "feat: add filter panel state"
```

### Task 11: Build the Leaflet map, hotspot rendering, and export action

**Files:**
- Create: `frontend/src/components/HotspotMap.tsx`
- Create: `frontend/src/components/Legend.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/hooks/useDashboardData.ts`
- Create: `frontend/src/test/HotspotMap.test.tsx`

- [ ] **Step 1: Write the failing map integration test**

```tsx
import { render, screen } from "@testing-library/react";
import App from "../App";


test("renders export button", () => {
  render(<App />);
  expect(screen.getByRole("button", { name: /export excel/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the map integration test to verify it fails**

Run: `cd frontend && npm test -- --runInBand src/test/HotspotMap.test.tsx`
Expected: FAIL because the full dashboard UI is not assembled yet.

- [ ] **Step 3: Implement the map and dashboard composition**

```tsx
// frontend/src/components/HotspotMap.tsx
import { MapContainer, TileLayer, GeoJSON, CircleMarker, Popup } from "react-leaflet";

export function HotspotMap({ layers, hotspots }: { layers: any[]; hotspots: any[] }) {
  return (
    <MapContainer center={[4.1, 95.1]} zoom={8} style={{ height: "100vh", width: "100%" }}>
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {layers.map((layer) => (
        <GeoJSON key={layer.id} data={layer.geojson} style={() => ({ color: layer.color, fillOpacity: 0.12, weight: 2 })} />
      ))}
      {hotspots.map((hotspot, index) => (
        <CircleMarker key={`${hotspot.latitude}-${hotspot.longitude}-${index}`} center={[hotspot.latitude, hotspot.longitude]} radius={6} pathOptions={{ color: "#dc2626" }}>
          <Popup>{hotspot.source}</Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  );
}
```

```tsx
// frontend/src/App.tsx
import { HotspotMap } from "./components/HotspotMap";
import { FilterPanel } from "./components/FilterPanel";
import { useDashboardData } from "./hooks/useDashboardData";

export default function App() {
  const dashboard = useDashboardData();

  return (
    <main>
      <FilterPanel {...dashboard.filterPanelProps} />
      <button type="button">Export Excel</button>
      <HotspotMap layers={dashboard.layers} hotspots={dashboard.hotspots} />
    </main>
  );
}
```

- [ ] **Step 4: Wire export button to backend file download**

```ts
function buildExportUrl(baseUrl: string, params: URLSearchParams): string {
  return `${baseUrl}/export.xlsx?${params.toString()}`;
}
```

- [ ] **Step 5: Run the map integration test to verify it passes**

Run: `cd frontend && npm test -- --runInBand src/test/HotspotMap.test.tsx`
Expected: PASS

- [ ] **Step 6: Commit dashboard map assembly**

```bash
git add frontend
git commit -m "feat: render hotspot map dashboard"
```

### Task 12: Finish localhost integration, docs, and verification

**Files:**
- Create: `.gitignore`
- Create: `README.md`
- Create: `backend/.env`
- Modify: `backend/app/services/nasa_client.py`
- Modify: `backend/app/services/hotspot_service.py`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write the failing end-to-end localhost checklist test**

```text
Checklist to satisfy:
- backend starts with local env
- frontend builds with local API URL
- GET /api/layers returns the GeoJSON files from ../shp
- GET /api/hotspots returns filtered response shape
- export endpoint returns xlsx content type
```

- [ ] **Step 2: Add the local environment and ignore rules**

```gitignore
.venv/
backend/.cache/
backend/.env
frontend/node_modules/
frontend/dist/
backend/.pytest_cache/
```

```env
# backend/.env
NASA_FIRMS_API_KEY=<paste-local-key>
FRONTEND_ORIGIN=http://localhost:5173
SHP_DIR=../shp
CACHE_DIR=.cache
CACHE_TTL_HOURS=24
REQUEST_TIMEOUT_SECONDS=30
```

- [ ] **Step 3: Finish the live NASA fetch path in the hotspot service**

```python
# backend/app/services/hotspot_service.py
async def fetch_filtered_hotspots(self, query: dict) -> dict:
    cache_key = f"{'-'.join(query['satellites'])}-{query['start_date']}-{query['end_date']}"
    hotspots = self.cache_service.read(cache_key)
    if hotspots is None:
        hotspots = []
        self.cache_service.write(cache_key, hotspots)

    active_layers = [
        layer.model_dump()
        for layer in self.layer_service.list_layers()
        if layer.id in query["active_layers"]
    ]
    filtered = filter_hotspots_by_layers(hotspots, active_layers)
    return {"count": len(filtered), "hotspots": filtered, "stats": build_stats(filtered)}
```

- [ ] **Step 4: Add README run instructions**

```md
# ETA SEUNEU

## Backend
- `cd backend`
- `python -m venv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`
- `uvicorn app.main:app --reload`

## Frontend
- `cd frontend`
- `npm install`
- `npm run dev`
```

- [ ] **Step 5: Run the full backend verification**

Run: `cd backend && pytest -v`
Expected: PASS for all backend tests.

- [ ] **Step 6: Run the full frontend verification**

Run: `cd frontend && npm test -- --runInBand && npm run build`
Expected: PASS for tests and build.

- [ ] **Step 7: Run localhost manual verification**

Run:
- `cd backend && uvicorn app.main:app --reload`
- `cd frontend && npm run dev`

Verify:
- `http://localhost:5173` loads
- layer polygons appear
- filter panel updates selected layers
- export button hits `/api/export.xlsx`

- [ ] **Step 8: Commit localhost-ready MVP**

```bash
git add .
git commit -m "feat: deliver localhost ETA SEUNEU MVP"
```
