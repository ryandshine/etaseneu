export interface HealthResponse {
  status: string;
}

// Sesi login (POST /api/auth/login). Token disimpan di localStorage agar
// reload/reset web tidak memaksa login ulang; endpoint /api/auth/session
// tetap memvalidasi token dan status revoke di server.
export type UserRole = "admin" | "user" | "bps";

export interface AppSession {
  token: string;
  username: string;
  role: UserRole;
  wilker_bps?: string | null;
  expiresAt?: string | null;
}

export interface AppUser {
  id: number;
  username: string;
  role: UserRole;
  wilker_bps?: string | null;
  created_at: string;
  active_sessions?: number;
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

export interface PolygonDetail {
  id: number;
  layer_key: string;
  feature_key: string;
  lembaga: string | null;
  nama_prov: string | null;
  nama_kab: string | null;
  nama_kec: string | null;
  nama_desa: string | null;
  skema: string | null;
  no_sk: string | null;
  tgl_sk: string | null;
  status: string | null;
  wilker_bps: string | null;
  ps_id: string | null;
  luas_final: string | null;
  jml_kk: string | null;
  geometry: Record<string, unknown>;
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
  // Atribusi fungsi kawasan hutan KLHK. Bentuk objek `kawasan_hutan` datang
  // dari view=full; `fungsi_kawasan`/`kelompok` datar datang dari view=map.
  kawasan_hutan?: KawasanHutan | null;
  fungsi_kawasan?: string;
  kelompok?: string;
}

export interface KawasanHutan {
  kode?: number | null;
  fungsi?: string | null;
  singkatan?: string | null;
  nama_kawasan?: string | null;
  kelompok?: string | null;
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

// Kompleks Kebakaran: kelompok titik hotspot yang berdekatan ruang & waktu
// (ST-DBSCAN dihitung server-side lewat self-join PostGIS, lihat
// backend/app/services/hotspot_cluster_service.py). "sensitivity" adalah
// preset bahasa awam (ketat/sedang/longgar) -- parameter mentah (eps_km dst)
// sengaja tidak diekspos ke frontend.
export type ClusterSensitivity = "ketat" | "sedang" | "longgar";

export interface ClusterLocation {
  location_id: number;
  hotspot_count: number;
  centroid_lat: number;
  centroid_lon: number;
  first_detected_at: string;
  last_detected_at: string;
  polygon_hotspot_count: number;
  outside_polygon_hotspot_count: number;
}

export interface ClusterPolygonSummary {
  polygon_metadata_id: number;
  name: string | null;
  wilker_bps: string | null;
  province_name: string | null;
  hotspot_count: number;
  location_count: number;
}

export interface ClusterRecord {
  cluster_id: number;
  hotspot_count: number;
  centroid_lat: number;
  centroid_lon: number;
  first_detected_at: string;
  last_detected_at: string;
  dominant_agency: string | null;
  core_point_count?: number;
  dominant_wilker?: string | null;
  dominant_province?: string | null;
  /** Union buffer ε dari seluruh core point; footprint audit cluster. */
  footprint?: Record<string, unknown> | null;
  affected_wilkers?: Array<{ name: string; hotspot_count: number }>;
  affected_provinces?: Array<{ name: string; hotspot_count: number }>;
  affected_agencies?: Array<{ name: string; hotspot_count: number }>;
  location_count?: number;
  locations_in_polygon?: number;
  polygon_hotspot_count?: number;
  outside_polygon_hotspot_count?: number;
  dominant_polygon?: ClusterPolygonSummary | null;
  polygons?: ClusterPolygonSummary[];
  locations?: ClusterLocation[];
}

export interface ClusterPoint {
  id: number;
  latitude: number;
  longitude: number;
  detected_at: string;
  agency_name: string | null;
  polygon_metadata_id?: number | null;
  polygon_agency_name?: string | null;
  wilker_bps?: string | null;
  province_name?: string | null;
  cluster_id: number;
  is_core?: boolean;
}

export interface ClusterStats {
  total_hotspots_in_range: number;
  clustered_hotspots: number;
  unclustered_hotspots: number;
}

export interface ClusterCollectionResponse {
  count: number;
  clusters: ClusterRecord[];
  stats: ClusterStats;
  sensitivity: ClusterSensitivity;
  range_start: string;
  range_end: string;
  points?: ClusterPoint[];
}

export interface HotspotClusterQueryParams {
  start_at?: string;
  end_at?: string;
  sensitivity?: ClusterSensitivity;
}

// Frekuensi Kebakaran per KPS: berapa periode (bulan) terpisah tiap KPS
// pernah tercatat luas bekas terbakar resmi KLHK (bukan dari hotspot NASA
// FIRMS) -- dipakai kolom "Frekuensi" di Buku Besar dan badge di halaman
// Detail KPS. Lihat backend/app/services/postgres_store/_burned_area.py::burn_frequency_by_lembaga.
export interface BurnFrequencyRecord {
  lembaga: string;
  periode_terbakar: number;
  pertama: string | null;
  terakhir: string | null;
  total_ha: number;
}

export interface BurnFrequencyResponse {
  rows: BurnFrequencyRecord[];
}

export interface BurnedAreaKawasanRow {
  kode: number | null;
  singkatan: string;
  fungsi: string;
  kelompok: string;
  luas_ha: number;
}

export interface BurnedAreaKawasanResponse {
  rows: BurnedAreaKawasanRow[];
  total_ha: number;
  source: string;
  period: string;
}

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
    layer: (id: string) => string;
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
  getLayer: (id: string, view?: "preview" | "full") => Promise<LayerFeature>;
  getHotspots: (params: HotspotQueryParams) => Promise<HotspotCollectionResponse>;
  getStats: (params: HotspotQueryParams) => Promise<StatsResponse>;
  getHotspotClusters: (params: HotspotClusterQueryParams) => Promise<ClusterCollectionResponse>;
  getBurnFrequency: () => Promise<BurnFrequencyResponse>;
  getBurnedAreaByKawasan: (province?: string) => Promise<BurnedAreaKawasanResponse>;
  getHistoryStatus: (params: HotspotQueryParams & { year: number }) => Promise<HistoryStatusResponse>;
  prewarmHistory: (
    params: HotspotQueryParams & { year: number },
    adminKey?: string | null,
    authToken?: string | null
  ) => Promise<HistoryStatusResponse>;
  getGeojsonStatus: () => Promise<GeoJsonStatusResponse>;
  getStorageStatus: () => Promise<StorageStatusResponse>;
  getSchedulerMetrics: () => Promise<SchedulerMetricsResponse>;
  triggerManualSync: (adminKey?: string | null, authToken?: string | null) => Promise<ManualSyncResponse>;
}
