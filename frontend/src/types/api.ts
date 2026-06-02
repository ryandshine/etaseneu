export interface HealthResponse {
  status: string;
}

export interface LayerBounds {
  min_lat: number;
  min_lon: number;
  max_lat: number;
  max_lon: number;
}

export interface LayerFeature {
  id: string;
  name: string;
  label: string;
  color: string;
  active: boolean;
  feature_count: number;
  bounds: LayerBounds;
  geojson: Record<string, unknown>;
  geojson_mode?: "preview" | "full";
  agencies?: string[];
}

export interface LayerListResponse {
  count: number;
  layers: LayerFeature[];
}

export interface HotspotQueryParams {
  start_at: string;
  end_at: string;
  satellites?: string[];
  active_layers?: string[];
  view?: "map" | "full";
}

export interface HotspotRecord {
  id?: string;
  source?: string;
  satellite?: string;
  latitude?: number;
  longitude?: number;
  brightness?: number | null;
  frp?: number | null;
  confidence?: string | null;
  daynight?: string | null;
  detected_at?: string;
  layer_id?: string;
  layer_name?: string;
  agency_name?: string;
  province_name?: string;
  polygon_metadata?: Record<string, string>;
}

export interface StatsSummary {
  total: number;
  by_source: Record<string, number>;
  by_layer: Record<string, number>;
}

export interface HotspotCollectionResponse {
  count: number;
  hotspots: HotspotRecord[];
  stats: StatsSummary;
}

export type StatsResponse = StatsSummary;

export interface HistoryLayerStatus {
  layer_id: string;
  cached: boolean;
  satellites: string[];
  coverage_start: string | null;
  coverage_end: string | null;
  hotspot_count: number;
}

export interface HistoryStatusResponse {
  year: number;
  cached: boolean;
  satellites: string[];
  layers: HistoryLayerStatus[];
}

export interface StorageStatusResponse {
  database_enabled: boolean;
  database_url_present: boolean;
  last_hotspot_sync_at: string | null;
  last_hotspot_sync_count: number;
  tables: {
    layers: number;
    geojson_file_registry: number;
    hotspot_history_archives: number;
    api_cache_entries: number;
    hotspot_observations: number;
    hotspot_sync_state: number;
  };
}

export interface GeoJsonRegistryFile {
  file_name: string;
  file_path: string;
  layer_key: string;
  checksum: string;
  mtime: string;
  last_synced_at: string | null;
  last_sync_status: string;
  last_sync_message: string;
  feature_count: number;
  is_active: boolean;
}

export interface GeoJsonStatusResponse {
  database_enabled: boolean;
  database_url_present: boolean;
  count: number;
  active_count: number;
  inactive_count: number;
  files: GeoJsonRegistryFile[];
}

export interface SchedulerMetricsResponse {
  scheduler_enabled: boolean;
  interval_hours: number;
  schedule_hours?: number[];
  schedule_label?: string;
  schedule_timezone?: string;
  nasa_api_configured: boolean;
  current_time_utc: string;
  last_sync_at: string | null;
  last_successful_sync_at: string | null;
  last_sync_status: string;
  last_sync_hotspot_count: number;
  last_new_hotspot_count: number;
  has_new_hotspot: boolean;
  new_hotspot_over_threshold: boolean;
  new_hotspot_alert_threshold: number;
  seconds_since_last_sync: number | null;
  seconds_since_last_successful_sync: number | null;
  consecutive_failures: number;
  last_error: string | null;
  next_scheduled_sync_at: string | null;
}

export interface ManualSyncResponse {
  triggered: boolean;
  message?: string;
  reason?: string;
}

export interface ApiClient {
  baseUrl: string;
  endpoints: {
    health: string;
    layers: string;
    hotspots: string;
    stats: string;
    cacheHistoryStatus: string;
    cacheHistoryPrewarm: string;
    geojsonStatus: string;
    storageStatus: string;
    schedulerMetrics: string;
    schedulerSync: string;
  };
  getHealth: () => Promise<HealthResponse>;
  getLayers: (view?: "preview" | "full") => Promise<LayerListResponse>;
  getHotspots: (params: HotspotQueryParams) => Promise<HotspotCollectionResponse>;
  getStats: (params: HotspotQueryParams) => Promise<StatsResponse>;
  getHistoryStatus: (params: HotspotQueryParams & { year: number }) => Promise<HistoryStatusResponse>;
  prewarmHistory: (params: HotspotQueryParams & { year: number }) => Promise<HistoryStatusResponse>;
  getGeojsonStatus: () => Promise<GeoJsonStatusResponse>;
  getStorageStatus: () => Promise<StorageStatusResponse>;
  getSchedulerMetrics: () => Promise<SchedulerMetricsResponse>;
  triggerManualSync: () => Promise<ManualSyncResponse>;
}
