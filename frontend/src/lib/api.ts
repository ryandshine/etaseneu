import type {
  ApiClient,
  BurnFrequencyResponse,
  BurnedAreaKawasanResponse,
  ClusterCollectionResponse,
  HealthResponse,
  HistoryStatusResponse,
  GeoJsonStatusResponse,
  HotspotClusterQueryParams,
  HotspotCollectionResponse,
  HotspotQueryParams,
  LayerFeature,
  LayerListResponse,
  ManualSyncResponse,
  SchedulerMetricsResponse,
  StatsResponse,
  StorageStatusResponse
} from "../types/api";

type QueryPrimitive = string | number | boolean;
type QueryValue = QueryPrimitive | QueryPrimitive[] | undefined;

function appendQuery(
  searchParams: URLSearchParams,
  key: string,
  value: QueryValue,
): void {
  if (value === undefined) {
    return;
  }

  if (Array.isArray(value)) {
    value.forEach((entry) => searchParams.append(key, String(entry)));
    return;
  }

  searchParams.append(key, String(value));
}

function withQuery(
  path: string,
  query?: Record<string, QueryValue> | undefined,
): string {
  if (!query) {
    return path;
  }

  const searchParams = new URLSearchParams();

  Object.entries(query).forEach(([key, value]) => {
    appendQuery(searchParams, key, value);
  });

  const queryString = searchParams.toString();
  return queryString ? `${path}?${queryString}` : path;
}

function toQueryRecord(params: HotspotQueryParams): Record<string, QueryValue> {
  return {
    start_at: params.start_at,
    end_at: params.end_at,
    start_date: params.start_at.slice(0, 10),
    end_date: params.end_at.slice(0, 10),
    satellites: params.satellites,
    active_layers: params.active_layers,
    view: params.view === "full" ? undefined : params.view,
  };
}

function toHistoryQueryRecord(
  params: HotspotQueryParams & { year: number },
): Record<string, QueryValue> {
  return {
    ...toQueryRecord(params),
    year: params.year
  };
}

// Token sesi JWT & handler 401 disimpan di level modul: hanya ada satu sesi
// aktif per tab, dan `api` di useDashboardData.ts adalah singleton modul.
// App.tsx memanggil setAuthToken() saat login/logout dan
// setUnauthorizedHandler() sekali saat mount.
let authToken: string | null = null;
let unauthorizedHandler: (() => void) | null = null;

export function getEffectiveToken(): string | null {
  if (authToken) return authToken;
  try {
    const raw = localStorage.getItem("etaseneu.session.v1") || localStorage.getItem("etaseneu_app_session");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed?.token && typeof parsed.token === "string") {
        authToken = parsed.token;
        return parsed.token;
      }
    }
  } catch {}
  return null;
}

export function setAuthToken(token: string | null): void {
  authToken = token;
}

export function setUnauthorizedHandler(fn: (() => void) | null): void {
  unauthorizedHandler = fn;
}

/**
 * `fetch` untuk endpoint /api yang dipanggil langsung (bukan lewat
 * createApiClient) -- mis. unduh Excel/PDF, overlay peta, cuaca, detail
 * polygon. Menyisipkan `Authorization: Bearer <token>` kalau ada sesi, dan
 * memicu handler logout saat 401. Wajib dipakai menggantikan `fetch` mentah
 * ke /api supaya tidak putus saat backend API_REQUIRE_AUTH menyala.
 */
export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getEffectiveToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) {
    unauthorizedHandler?.();
  }
  return response;
}

/**
 * Unduh berkas dari endpoint /api yang butuh sesi. `<a href="/api/...">` biasa
 * tidak bisa membawa header Authorization, jadi tarik sebagai blob lalu klik
 * anchor sementara. Dipakai untuk tombol unduh Excel/PDF.
 */
export async function downloadWithAuth(url: string, filename: string): Promise<void> {
  const response = await authFetch(url);
  if (!response.ok) {
    throw new Error(`Download failed with status ${response.status}`);
  }
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 100);
}

async function fetchJson<T>(
  path: string,
  method = "GET",
  extraHeaders?: Record<string, string>
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    ...extraHeaders
  };
  const token = getEffectiveToken();
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(path, { method, headers });

  if (response.status === 401) {
    // Sesi habis / token invalid -- paksa kembali ke halaman login.
    unauthorizedHandler?.();
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    throw new Error(`API request failed with status ${response.status}`);
  }

  return (await response.json()) as T;
}

function adminHeaders(adminKey?: string | null, authToken?: string | null): Record<string, string> {
  const headers: Record<string, string> = {};
  if (adminKey) {
    headers["X-Admin-Key"] = adminKey;
  }
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  return headers;
}

function toClusterQueryRecord(params: HotspotClusterQueryParams): Record<string, QueryValue> {
  return {
    start_at: params.start_at,
    end_at: params.end_at,
    sensitivity: params.sensitivity,
  };
}

function toLayerQueryRecord(view?: "preview" | "full"): Record<string, QueryValue> | undefined {
  if (!view || view === "full") {
    return undefined;
  }

  return { view };
}

export function createApiClient(baseUrl = "/api"): ApiClient {
  const endpoints = {
    health: `${baseUrl}/health`,
    layers: `${baseUrl}/layers`,
    layer: (id: string) => `${baseUrl}/layers/${encodeURIComponent(id)}`,
    hotspots: `${baseUrl}/hotspots`,
    hotspotClusters: `${baseUrl}/hotspots/clusters`,
    burnFrequency: `${baseUrl}/burned-area/frequency`,
    burnedAreaKawasan: `${baseUrl}/burned-area/kawasan-summary`,
    stats: `${baseUrl}/stats`,
    cacheHistoryStatus: `${baseUrl}/cache/history/status`,
    cacheHistoryPrewarm: `${baseUrl}/cache/history/prewarm`,
    geojsonStatus: `${baseUrl}/geojson/status`,
    storageStatus: `${baseUrl}/storage/status`,
    schedulerMetrics: `${baseUrl}/scheduler/metrics`,
    schedulerSync: `${baseUrl}/scheduler/sync`
  } as const;

  return {
    baseUrl,
    endpoints,
    getHealth: () => fetchJson<HealthResponse>(endpoints.health),
    getLayers: (view) =>
      fetchJson<LayerListResponse>(withQuery(endpoints.layers, toLayerQueryRecord(view))),
    getLayer: (id, view) =>
      fetchJson<LayerFeature>(withQuery(endpoints.layer(id), toLayerQueryRecord(view))),
    getHotspots: (params: HotspotQueryParams) =>
      fetchJson<HotspotCollectionResponse>(
        withQuery(endpoints.hotspots, toQueryRecord(params)),
      ),
    getStats: (params: HotspotQueryParams) =>
      fetchJson<StatsResponse>(withQuery(endpoints.stats, toQueryRecord(params))),
    getHotspotClusters: (params: HotspotClusterQueryParams) =>
      fetchJson<ClusterCollectionResponse>(
        withQuery(endpoints.hotspotClusters, toClusterQueryRecord(params)),
      ),
    getBurnFrequency: () => fetchJson<BurnFrequencyResponse>(endpoints.burnFrequency),
    getBurnedAreaByKawasan: (province?: string) =>
      fetchJson<BurnedAreaKawasanResponse>(
        withQuery(endpoints.burnedAreaKawasan, province ? { province } : {}),
      ),
    getHistoryStatus: (params) =>
      fetchJson<HistoryStatusResponse>(
        withQuery(endpoints.cacheHistoryStatus, toHistoryQueryRecord(params)),
      ),
    prewarmHistory: (params, adminKey, authToken) =>
      fetchJson<HistoryStatusResponse>(
        withQuery(endpoints.cacheHistoryPrewarm, toHistoryQueryRecord(params)),
        "POST",
        adminHeaders(adminKey, authToken),
      ),
    getGeojsonStatus: () => fetchJson<GeoJsonStatusResponse>(endpoints.geojsonStatus),
    getStorageStatus: () => fetchJson<StorageStatusResponse>(endpoints.storageStatus),
    getSchedulerMetrics: () => fetchJson<SchedulerMetricsResponse>(endpoints.schedulerMetrics),
    triggerManualSync: (adminKey, authToken) =>
      fetchJson<ManualSyncResponse>(endpoints.schedulerSync, "POST", adminHeaders(adminKey, authToken))
  };
}
