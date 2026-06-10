import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from "react";

import { SATELLITE_OPTIONS } from "../constants/satellites";
import { type TimePreset } from "../constants/time-windows";
import { createApiClient } from "../lib/api";
import { getCurrentDateWIB, formatDateWIB, getTodayWIB } from "../lib/date";
import type {
  GeoJsonStatusResponse,
  HistoryStatusResponse,
  LayerBounds,
  LayerFeature,
  SchedulerMetricsResponse,
  StorageStatusResponse
} from "../types/api";

const api = createApiClient();



export type DashboardLayer = Pick<
  LayerFeature,
  "id" | "name" | "label" | "active" | "color" | "bounds" | "geojson" | "geojson_mode" | "feature_count" | "agencies"
>;
export type DashboardHotspot = {
  id: string;
  latitude: number;
  longitude: number;
  source: string;
  satellite: string;
  layerName: string;
  agencyName: string;
  provinceName: string;
  brightness: number | null;
  frp: number | null;
  confidence: string;
  daynight: string;
  detectedAt: string;
  polygonMetadata: Record<string, string>;
};
type RemoteStats = {
  total: number;
  by_source: Record<string, number>;
  by_layer: Record<string, number>;
};
type QueryPrimitive = string | number | boolean;
type QueryValue = QueryPrimitive | QueryPrimitive[] | undefined;
type TimeRange = {
  startAt: Date;
  endAt: Date;
  label: string;
};

function normalizeLembagaName(name: string): string {
  if (!name) return name;
  if (name.toLowerCase() === "lphd nyuai peningun") return "Areal Perhutanan Sosial";
  return name;
}

function mapLayerResponse(layer: LayerFeature): DashboardLayer {
  return {
    id: layer.id,
    name: normalizeLembagaName(layer.name),
    label: normalizeLembagaName(layer.label),
    active: layer.active,
    color: layer.color,
    bounds: layer.bounds as LayerBounds,
    geojson: layer.geojson,
    geojson_mode: layer.geojson_mode,
    feature_count: layer.feature_count,
    agencies: layer.agencies ?? [],
  };
}

function toIsoDate(value: Date): string {
  return formatDateWIB(value);
}

function getDefaultCustomStartDate(now: Date): string {
  const previousDay = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  return toIsoDate(previousDay);
}

function getDefaultCustomEndDate(now: Date): string {
  return toIsoDate(now);
}

function parseDateStart(value: string): Date {
  return new Date(`${value}T00:00:00.000Z`);
}

function parseDateEnd(value: string): Date {
  return new Date(`${value}T23:59:59.999Z`);
}

function formatSyncTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "never";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "never";
  }

  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
  const parts = formatter.formatToParts(parsed);
  const day = parts.find((part) => part.type === "day")?.value ?? "--";
  const month = parts.find((part) => part.type === "month")?.value ?? "---";
  const hour = parts.find((part) => part.type === "hour")?.value ?? "--";
  const minute = parts.find((part) => part.type === "minute")?.value ?? "--";
  return `${day} ${month} ${hour}:${minute} WIB`;
}

function getWibDate(dateStr: string, dayOffset: number): Date {
  const [year, month, day] = dateStr.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day + dayOffset - 1, 17, 0, 0, 0));
}

export function buildTimeRange(
  timePreset: TimePreset,
  customStartDate: string,
  customEndDate: string,
  clockTick: number,
): TimeRange {
  void clockTick;

  if (timePreset === "custom") {
    const startAt = getWibDate(customStartDate, 0);
    const endAt = getWibDate(customEndDate, 1);
    return {
      startAt,
      endAt,
      label: `${customStartDate} to ${customEndDate}`
    };
  }

  const presetOffset = {
    "24h": { days: 0, label: "Hari ini" },
    "48h": { days: -1, label: "48 jam terakhir" },
    "3d": { days: -2, label: "3 hari terakhir" },
    "7d": { days: -6, label: "7 hari terakhir" },
    "30d": { days: -29, label: "30 hari terakhir" }
  }[timePreset];

  const startAt = getWibDate(customEndDate, presetOffset.days);
  const endAt = getWibDate(customEndDate, 1);

  return {
    startAt,
    endAt,
    label: presetOffset.label
  };
}

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
  query: Record<string, QueryValue>,
): string {
  const searchParams = new URLSearchParams();

  Object.entries(query).forEach(([key, value]) => {
    appendQuery(searchParams, key, value);
  });

  const queryString = searchParams.toString();
  return queryString ? `${path}?${queryString}` : path;
}

export function useDashboardData(activeView: "map" | "matrix" | "monitoring" | "settings" = "map") {
  const today = getCurrentDateWIB();
  const [layers, setLayers] = useState<DashboardLayer[]>([]);
  const [hotspots, setHotspots] = useState<DashboardHotspot[]>([]);
  const [selectedSatellites, setSelectedSatellites] = useState<string[]>([
    ...SATELLITE_OPTIONS.map((option) => option.value)
  ]);
  const [timePreset, setTimePreset] = useState<TimePreset>("24h");
  const [startDate, setStartDate] = useState(() => getDefaultCustomStartDate(today));
  const [endDate, setEndDate] = useState(() => getDefaultCustomEndDate(today));
  const [clockTick, setClockTick] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [remoteStats, setRemoteStats] = useState<RemoteStats>({
    total: 0,
    by_source: {},
    by_layer: {}
  });
  const [historyStatus, setHistoryStatus] = useState<HistoryStatusResponse | null>(null);
  const [geojsonStatus, setGeojsonStatus] = useState<GeoJsonStatusResponse | null>(null);
  const [storageStatus, setStorageStatus] = useState<StorageStatusResponse | null>(null);
  const [schedulerMetrics, setSchedulerMetrics] = useState<SchedulerMetricsResponse | null>(null);
  const [isRefreshingScheduler, setIsRefreshingScheduler] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [isExportingPdf, setIsExportingPdf] = useState(false);
  const [isPrewarming, setIsPrewarming] = useState(false);
  const [isTriggeringManualSync, setIsTriggeringManualSync] = useState(false);
  const [isPending, startTransition] = useTransition();

  const [initialLoading, setInitialLoading] = useState({
    isLoading: true,
    error: null as string | null,
  });
  const [isInitLoaded, setIsInitLoaded] = useState(false);
  const hasStartedInitialLoadRef = useRef(false);
  const hotspotView: "map" | "full" = (activeView === "matrix" || activeView === "monitoring") ? "full" : "map";

  const handleLoadingFadeEnd = useCallback(() => {
    // Called by onTransitionEnd on the overlay (visual cleanup only)
    setInitialLoading((prev) => ({ ...prev, isLoading: false }));
  }, []);

  const loadInitialData = useCallback(async () => {
    setInitialLoading({ isLoading: true, error: null });
    setIsInitLoaded(false);

    try {
      const [schedulerRes, storageRes, layersRes] = await Promise.all([
        api.getSchedulerMetrics(),
        api.getStorageStatus(),
        api.getLayers("preview"),
      ]);
      const mappedLayers = layersRes.layers.map(mapLayerResponse);

      const activeLayerIds = mappedLayers.filter((layer) => layer.active).map((layer) => layer.id);
      const initialTimeRange = buildTimeRange(timePreset, startDate, endDate, clockTick);
      const initialQueryParams = {
        start_at: initialTimeRange.startAt.toISOString(),
        end_at: initialTimeRange.endAt.toISOString(),
        start_date: initialTimeRange.startAt.toISOString().slice(0, 10),
        end_date: initialTimeRange.endAt.toISOString().slice(0, 10),
        satellites: selectedSatellites,
        active_layers: activeLayerIds,
        view: hotspotView,
      };
      const hotspotsRes = await api.getHotspots(initialQueryParams);

      const mappedHotspots = hotspotsRes.hotspots.map((hotspot, index) => ({
        id: String(hotspot.id ?? `${hotspot.latitude}-${hotspot.longitude}-${index}`),
        latitude: Number(hotspot.latitude ?? 0),
        longitude: Number(hotspot.longitude ?? 0),
        source: String(hotspot.source ?? "Unknown"),
        satellite: String(hotspot.satellite ?? "Unknown"),
        layerName: normalizeLembagaName(String(hotspot.layer_name ?? "Unassigned")),
        agencyName: normalizeLembagaName(String(hotspot.agency_name ?? hotspot.layer_name ?? "Unassigned")),
        provinceName: String(hotspot.province_name ?? ""),
        polygonMetadata: Object.entries(hotspot.polygon_metadata ?? {}).reduce<Record<string, string>>(
          (accumulator, [key, value]) => {
            if (value !== undefined && value !== null && value !== "") {
              accumulator[key] = key === "LEMBAGA" ? normalizeLembagaName(String(value)) : String(value);
            }
            return accumulator;
          },
          {},
        ),
        brightness:
          hotspot.brightness === null || hotspot.brightness === undefined
            ? null
            : Number(hotspot.brightness),
        frp:
          hotspot.frp === null || hotspot.frp === undefined
            ? null
            : Number(hotspot.frp),
        confidence: String(hotspot.confidence ?? "Unknown"),
        daynight: String(hotspot.daynight ?? ""),
        detectedAt: String(hotspot.detected_at ?? "")
      }));

      setLayers(mappedLayers);
      setSchedulerMetrics(schedulerRes);
      setStorageStatus(storageRes);
      setHotspots(mappedHotspots);
      setRemoteStats(hotspotsRes.stats);

      // Data ready — dismiss overlay immediately, no animation
      setIsInitLoaded(true);
      setInitialLoading({ isLoading: false, error: null });

    } catch (err) {
      console.error("Failed to load initial dashboard data", err);
      setInitialLoading({ isLoading: true, error: "Gagal Memuat Data" });
    }
  }, [clockTick, endDate, hotspotView, selectedSatellites, startDate, timePreset]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockTick((current) => current + 1);
    }, 60_000);

    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (hasStartedInitialLoadRef.current) {
      return;
    }

    hasStartedInitialLoadRef.current = true;
    void loadInitialData();
  }, [loadInitialData]);

  useEffect(() => {
    if (!isInitLoaded) return;

    let isMounted = true;
    const refreshSchedulerMetrics = async () => {
      setIsRefreshingScheduler(true);
      try {
        const response = await api.getSchedulerMetrics();
        if (!isMounted) return;
        setSchedulerMetrics(response);
      } catch {
        if (!isMounted) return;
        setSchedulerMetrics((current) => current);
      } finally {
        if (isMounted) {
          setIsRefreshingScheduler(false);
        }
      }
    };

    const timer = window.setInterval(() => {
      void refreshSchedulerMetrics();
    }, 60_000);

    return () => {
      isMounted = false;
      window.clearInterval(timer);
    };
  }, [isInitLoaded]);

  const isFirstStorageRef = useRef(true);
  useEffect(() => {
    if (!isInitLoaded) return;
    if (isFirstStorageRef.current) {
      isFirstStorageRef.current = false;
      return;
    }
    let isMounted = true;

    api
      .getStorageStatus()
      .then((response) => {
        if (!isMounted) return;
        setStorageStatus(response);
      })
      .catch(() => {
        if (!isMounted) return;
        setStorageStatus(null);
      });

    return () => {
      isMounted = false;
    };
  }, [clockTick, isInitLoaded]);

  const activeLayerIds = useMemo(
    () => layers.filter((layer) => layer.active).map((layer) => layer.id),
    [layers],
  );
  const timeRange = useMemo(
    () => buildTimeRange(timePreset, startDate, endDate, clockTick),
    [clockTick, endDate, startDate, timePreset],
  );
  const lastHotspotSyncLabel = useMemo(
    () => formatSyncTimestamp(storageStatus?.last_hotspot_sync_at),
    [storageStatus?.last_hotspot_sync_at],
  );
  const queryParams = useMemo(
    () => ({
      start_at: timeRange.startAt.toISOString(),
      end_at: timeRange.endAt.toISOString(),
      start_date: timeRange.startAt.toISOString().slice(0, 10),
      end_date: timeRange.endAt.toISOString().slice(0, 10),
      satellites: selectedSatellites,
      active_layers: activeLayerIds,
    }),
    [activeLayerIds, selectedSatellites, timeRange.endAt, timeRange.startAt],
  );
  const hotspotQueryParams = useMemo(
    () => ({
      ...queryParams,
      view: hotspotView,
    }),
    [queryParams, hotspotView],
  );

  const isFirstHotspotsRef = useRef(true);
  useEffect(() => {
    if (!isInitLoaded) return;
    if (isFirstHotspotsRef.current) {
      isFirstHotspotsRef.current = false;
      return;
    }
    let isMounted = true;

    startTransition(() => {
      api
        .getHotspots(hotspotQueryParams)
        .then((response) => {
          if (!isMounted) return;
          setHotspots(
            response.hotspots.map((hotspot, index) => ({
              id: String(hotspot.id ?? `${hotspot.latitude}-${hotspot.longitude}-${index}`),
              latitude: Number(hotspot.latitude ?? 0),
              longitude: Number(hotspot.longitude ?? 0),
              source: String(hotspot.source ?? "Unknown"),
              satellite: String(hotspot.satellite ?? "Unknown"),
              layerName: normalizeLembagaName(String(hotspot.layer_name ?? "Unassigned")),
              agencyName: normalizeLembagaName(String(hotspot.agency_name ?? hotspot.layer_name ?? "Unassigned")),
              provinceName: String(hotspot.province_name ?? ""),
              polygonMetadata: Object.entries(hotspot.polygon_metadata ?? {}).reduce<Record<string, string>>(
                (accumulator, [key, value]) => {
                  if (value !== undefined && value !== null && value !== "") {
                    accumulator[key] = key === "LEMBAGA" ? normalizeLembagaName(String(value)) : String(value);
                  }
                  return accumulator;
                },
                {},
              ),
              brightness:
                hotspot.brightness === null || hotspot.brightness === undefined
                  ? null
                  : Number(hotspot.brightness),
              frp:
                hotspot.frp === null || hotspot.frp === undefined
                  ? null
                  : Number(hotspot.frp),
              confidence: String(hotspot.confidence ?? "Unknown"),
              daynight: String(hotspot.daynight ?? ""),
              detectedAt: String(hotspot.detected_at ?? "")
            })),
          );
          setRemoteStats(response.stats);
          setLoadError(null);
        })
        .catch(() => {
          if (!isMounted) return;
          setHotspots([]);
          setRemoteStats({
            total: 0,
            by_source: {},
            by_layer: {}
          });
          setLoadError("Hotspot data is unavailable.");
        });
    });

    return () => {
      isMounted = false;
    };
  }, [hotspotQueryParams, isInitLoaded]);

  useEffect(() => {
    if (!isInitLoaded) return;
    let isMounted = true;
    const historyYear = timeRange.endAt.getUTCFullYear() || parseInt(getTodayWIB().slice(0, 4), 10);

    api
      .getHistoryStatus({
        ...queryParams,
        year: historyYear
      })
      .then((response) => {
        if (!isMounted) return;
        setHistoryStatus(response);
      })
      .catch(() => {
        if (!isMounted) return;
        setHistoryStatus(null);
      });

    return () => {
      isMounted = false;
    };
  }, [queryParams, timeRange.endAt, isInitLoaded]);

  useEffect(() => {
    if (!isInitLoaded) return;
    let isMounted = true;

    api
      .getGeojsonStatus()
      .then((response) => {
        if (!isMounted) return;
        setGeojsonStatus(response);
      })
      .catch(() => {
        if (!isMounted) return;
        setGeojsonStatus(null);
      });

    return () => {
      isMounted = false;
    };
  }, [isInitLoaded]);

  const stats = useMemo(
    () => ({
      layerCount: layers.length,
      activeLayerCount: activeLayerIds.length,
      satelliteCount: selectedSatellites.length,
      dateRangeLabel: timeRange.label,
      hotspotCount: remoteStats.total
    }),
    [
      activeLayerIds.length,
      layers.length,
      remoteStats.total,
      selectedSatellites.length,
      timeRange.label
    ],
  );
  const sourceBreakdown = useMemo(
    () =>
      Object.entries(remoteStats.by_source).map(([label, count]) => ({
        label,
        count
      })),
    [remoteStats.by_source],
  );

  const layerBreakdown = useMemo(
    () =>
      layers.map((layer) => ({
        color: layer.color,
        count: layer.feature_count,
        id: layer.id,
        label: layer.label || layer.name
      })),
    [layers],
  );
  const agencyBreakdown = useMemo(
    () =>
      Object.entries(remoteStats.by_layer).map(([label, count]) => ({
        label,
        count
      })),
    [remoteStats.by_layer],
  );

  function toggleLayer(id: string) {
    setLayers((currentLayers) =>
      currentLayers.map((layer) =>
        layer.id === id ? { ...layer, active: !layer.active } : layer,
      ),
    );
  }

  function toggleSatellite(value: string) {
    setSelectedSatellites((currentSatellites) => {
      if (currentSatellites.includes(value)) {
        return currentSatellites.filter((satellite) => satellite !== value);
      }

      return [...currentSatellites, value];
    });
  }

  function updateDate(field: "startDate" | "endDate", value: string) {
    setTimePreset("custom");
    if (field === "startDate") {
      setStartDate(value);
      return;
    }

    setEndDate(value);
  }

  async function exportDashboard(filters?: { province?: string; wilker?: string; confidence?: string }) {
    setIsExporting(true);
    setExportError(null);

    try {
      const params = {
        ...queryParams,
        ...(filters?.province ? { province: filters.province } : {}),
        ...(filters?.wilker ? { wilker: filters.wilker } : {}),
        ...(filters?.confidence ? { confidence: filters.confidence } : {})
      };
      const response = await fetch(withQuery(`${api.baseUrl}/export.xlsx`, params), {
        headers: {
          Accept: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }
      });

      if (!response.ok) {
        throw new Error(`Export failed with status ${response.status}`);
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");

      anchor.href = objectUrl;
      anchor.download = "eta-seuneu-hotspots.xlsx";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 100);
    } catch {
      setExportError("Export is unavailable.");
    } finally {
      setIsExporting(false);
    }
  }

  async function exportPdf(filters?: { province?: string; wilker?: string; confidence?: string; agency?: string }) {
    setIsExportingPdf(true);
    setExportError(null);

    try {
      const params = {
        ...queryParams,
        ...(filters?.province ? { province: filters.province } : {}),
        ...(filters?.wilker ? { wilker: filters.wilker } : {}),
        ...(filters?.confidence ? { confidence: filters.confidence } : {}),
        ...(filters?.agency ? { agency: filters.agency } : {})
      };
      const response = await fetch(withQuery(`${api.baseUrl}/export.pdf`, params), {
        headers: {
          Accept: "application/pdf"
        }
      });

      if (!response.ok) {
        throw new Error(`Export failed with status ${response.status}`);
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");

      anchor.href = objectUrl;
      anchor.download = filters?.agency 
        ? `eta-seuneu-laporan-${filters.agency.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.pdf`
        : "eta-seuneu-hotspots-report.pdf";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 100);
    } catch {
      setExportError("Export PDF is unavailable.");
    } finally {
      setIsExportingPdf(false);
    }
  }

  async function prewarmHistory() {
    setIsPrewarming(true);
    setExportError(null);

    try {
      const historyYear = timeRange.endAt.getUTCFullYear() || parseInt(getTodayWIB().slice(0, 4), 10);
      const response = await api.prewarmHistory({ ...queryParams, year: historyYear });
      setHistoryStatus(response);
    } catch {
      setExportError("History prewarm is unavailable.");
    } finally {
      setIsPrewarming(false);
    }
  }

  async function manualSync() {
    setIsTriggeringManualSync(true);
    setSyncError(null);

    try {
      await api.triggerManualSync();
      setClockTick((current) => current + 1);
    } catch {
      setSyncError("Manual sync is unavailable.");
    } finally {
      setIsTriggeringManualSync(false);
    }
  }

  return {
    activeLayerIds,
    endDate,
    exportDashboard,
    exportError,
    hotspots,
    isExporting,
    isExportingPdf,
    isPrewarming,
    isTriggeringManualSync,
    isPending,
    historyStatus,
    geojsonStatus,
    layerBreakdown,
    agencyBreakdown,
    layers,
    loadError,
    syncError,
    selectedSatellites,
    sourceBreakdown,
    startDate,
    stats,
    storageStatus,
    schedulerMetrics,
    isRefreshingScheduler,
    lastHotspotSyncLabel,
    timePreset,
    timeRange,
    setTimePreset,
    toggleLayer,
    toggleSatellite,
    updateDate,
    manualSync,
    prewarmHistory,
    exportPdf,
    initialLoading,
    onLoadingFadeEnd: handleLoadingFadeEnd,
    retryInitialLoad: loadInitialData
  };
}
