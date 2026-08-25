import type {
  ApiClient,
  BurnFrequencyResponse,
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

async function fetchJson<T>(
  path: string,
  method = "GET",
  extraHeaders?: Record<string, string>
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: "application/json",
      ...extraHeaders
    }
  });

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
