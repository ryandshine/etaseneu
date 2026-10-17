import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DashboardHotspot, DashboardLayer, LayerFeature } from "../types/api";
import { authFetch } from "../lib/api";
import { mapHotspotRecordToDashboardHotspot } from "../lib/hotspotDisplay";
import { formatDateTimeWIB, formatDateWIB, getTodayWIB } from "../lib/date";
import type { TimePreset } from "../constants/time-windows";

export interface SpotWeatherData {
  temperature?: number;
  relative_humidity?: number;
  precipitation?: number;
  wind_speed?: number;
  wind_direction?: number;
  air_quality?: {
    pm2_5?: number;
    cbi?: {
      cbi_val?: number;
      category?: string;
    };
  };
}

export interface WindVectorFeature {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number];
  };
  properties: {
    u: number;
    v: number;
    speed: number;
    speedKmh: number;
    directionDeg: number;
    directionText: string;
  };
}

export interface WindGeoJson {
  type: "FeatureCollection";
  features: WindVectorFeature[];
}

export function windDegToCompass(deg: number): string {
  const directions = ["U", "UTL", "TL", "TTL", "T", "TGr", "Gr", "SGr", "S", "SBD", "BD", "BBD", "B", "BBL", "BL", "UBL"];
  const index = Math.round(((deg % 360) + 360) % 360 / 22.5) % 16;
  return directions[index] ?? "U";
}

export function useWildfire3DData(active = true) {
  const [timePreset, setTimePreset] = useState<TimePreset>("24h");
  const [customStartDate, setCustomStartDate] = useState<string>(getTodayWIB());
  const [customEndDate, setCustomEndDate] = useState<string>(getTodayWIB());

  const [hotspots, setHotspots] = useState<DashboardHotspot[]>([]);
  const [layers, setLayers] = useState<DashboardLayer[]>([]);
  const [windGeoJson, setWindGeoJson] = useState<WindGeoJson | null>(null);
  const [windSummary, setWindSummary] = useState<{
    avgSpeedKmh: number;
    dominantDirectionDeg: number;
    dominantDirectionText: string;
    updatedAt: string;
  } | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [syncMetrics, setSyncMetrics] = useState<{
    lastSync: string | null;
    nextSync: string | null;
    status: string | null;
    hotspotLatest: string | null;
  } | null>(null);

  // Layer Toggles
  const [showHotspots, setShowHotspots] = useState(true);
  const [showHighConf, setShowHighConf] = useState(true);
  const [showMedConf, setShowMedConf] = useState(true);
  const [showLowConf, setShowLowConf] = useState(true);
  const [showKps, setShowKps] = useState(true);
  const [showTerrain, setShowTerrain] = useState(true);
  const [terrainExaggeration, setTerrainExaggeration] = useState(1.5);
  const [showWind, setShowWind] = useState(true);
  const [basemap, setBasemap] = useState<"satellite" | "dark" | "topo">("satellite");

  // Selection & Spot Weather
  const [selectedHotspot, setSelectedHotspot] = useState<DashboardHotspot | null>(null);
  const [spotWeather, setSpotWeather] = useState<SpotWeatherData | null>(null);
  const [spotWeatherLoading, setSpotWeatherLoading] = useState(false);
  const [spotWeatherError, setSpotWeatherError] = useState<string | null>(null);

  // Timeline Playback
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<1 | 2 | 4>(1);
  const [timelineProgress, setTimelineProgress] = useState(100); // 0 - 100%

  // Compute UTC start/end datetimes based on preset
  const { startIso, endIso } = useMemo(() => {
    const now = new Date();
    let start = new Date(now);
    let end = new Date(now);

    if (timePreset === "custom") {
      const s = new Date(`${customStartDate}T00:00:00Z`);
      const e = new Date(`${customEndDate}T23:59:59Z`);
      return { startIso: s.toISOString(), endIso: e.toISOString() };
    }

    const hoursMap: Record<string, number> = {
      "24h": 24,
      "48h": 48,
      "3d": 72,
      "7d": 168,
      "30d": 720
    };
    const hours = hoursMap[timePreset] ?? 24;
    start = new Date(now.getTime() - hours * 3600 * 1000);
    return { startIso: start.toISOString(), endIso: end.toISOString() };
  }, [timePreset, customStartDate, customEndDate]);

  // Fetch Hotspots & Sync Metrics
  const loadHotspotData = useCallback(async () => {
    if (!active) return;
    try {
      setLoading(true);
      setError(null);

      const params = new URLSearchParams({
        view: "map",
        start_at: startIso,
        end_at: endIso
      });

      // Satelit NASA FIRMS default
      ["MODIS", "VIIRS_NOAA20", "VIIRS_NOAA21", "VIIRS_SNPP"].forEach((s) => {
        params.append("satellites", s);
      });

      // Layer KPS aktif (default fallback bila layer belum selesai dimuat)
      const activeLayerIds =
        layers.length > 0
          ? layers.filter((l) => l.active).map((l) => l.id)
          : ["psagustus2026", "HUTAN_ADAT_APR26", "PS_FEB_26"];
      activeLayerIds.forEach((l) => {
        params.append("active_layers", l);
      });

      const [hotspotRes, metricsRes] = await Promise.all([
        authFetch(`/api/hotspots?${params.toString()}`),
        authFetch("/api/scheduler/metrics").catch(() => null)
      ]);

      if (!hotspotRes.ok) {
        throw new Error(`Gagal memuat hotspot: HTTP ${hotspotRes.status}`);
      }

      const hotspotJson = await hotspotRes.json();
      const rawHotspots = (hotspotJson.hotspots ?? []) as any[];
      const mapped = rawHotspots.map((h, i) => mapHotspotRecordToDashboardHotspot(h, i));
      setHotspots(mapped);
      setLastUpdated(new Date().toISOString());

      if (metricsRes && metricsRes.ok) {
        const m = await metricsRes.json();
        setSyncMetrics({
          lastSync: m.last_sync_time ?? null,
          nextSync: m.next_scheduled_sync ?? null,
          status: m.scheduler_status ?? "OK",
          hotspotLatest: m.latest_hotspot_time ?? null
        });
      }
    } catch (err: any) {
      setError(err?.message || "Terjadi kesalahan saat memuat data hotspot 3D");
    } finally {
      setLoading(false);
    }
  }, [active, startIso, endIso]);

  // Fetch KPS Layers once
  const loadLayers = useCallback(async () => {
    if (!active || layers.length > 0) return;
    try {
      const res = await authFetch("/api/layers?view=preview");
      if (res.ok) {
        const json = await res.json();
        const mapped = (json.layers ?? []).map((l: LayerFeature) => ({
          id: l.id,
          name: l.name,
          label: l.label,
          active: l.active,
          color: l.color,
          bounds: l.bounds,
          geojson: l.geojson,
          geojson_mode: l.geojson_mode,
          feature_count: l.feature_count,
          agencies: l.agencies
        }));
        setLayers(mapped);
      }
    } catch {
      // Non-fatal fallback
    }
  }, [active, layers.length]);

  // Fetch Wind Data from Open-Meteo endpoint
  const loadWindData = useCallback(async () => {
    if (!active) return;
    try {
      const res = await authFetch("/api/wind");
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length >= 2) {
          const uEntry = data.find((e) => e.header?.parameterNumber === 2) || data[0];
          const vEntry = data.find((e) => e.header?.parameterNumber === 3) || data[1];

          const header = uEntry.header;
          const uList = uEntry.data as number[];
          const vList = vEntry.data as number[];

          const { lo1, la1, dx, dy, nx, ny } = header;
          const features: WindVectorFeature[] = [];

          let totalSpeed = 0;
          let count = 0;
          let sumU = 0;
          let sumV = 0;

          // Downsample grid slightly for 3D visual clarity: step every 2 points
          const stride = 2;
          for (let y = 0; y < ny; y += stride) {
            const lat = la1 - y * dy;
            for (let x = 0; x < nx; x += stride) {
              const idx = y * nx + x;
              const u = uList[idx] ?? 0;
              const v = vList[idx] ?? 0;
              const lon = lo1 + x * dx;

              const speed = Math.sqrt(u * u + v * v);
              const speedKmh = Math.round(speed * 3.6 * 10) / 10;
              // Direction from which wind blows
              const dirRad = Math.atan2(-u, -v);
              const directionDeg = Math.round(((dirRad * 180) / Math.PI + 360) % 360);

              totalSpeed += speedKmh;
              sumU += u;
              sumV += v;
              count++;

              features.push({
                type: "Feature",
                geometry: {
                  type: "Point",
                  coordinates: [lon, lat]
                },
                properties: {
                  u,
                  v,
                  speed,
                  speedKmh,
                  directionDeg,
                  directionText: windDegToCompass(directionDeg)
                }
              });
            }
          }

          setWindGeoJson({
            type: "FeatureCollection",
            features
          });

          if (count > 0) {
            const meanDirRad = Math.atan2(-sumU / count, -sumV / count);
            const domDeg = Math.round(((meanDirRad * 180) / Math.PI + 360) % 360);
            setWindSummary({
              avgSpeedKmh: Math.round((totalSpeed / count) * 10) / 10,
              dominantDirectionDeg: domDeg,
              dominantDirectionText: windDegToCompass(domDeg),
              updatedAt: formatDateTimeWIB(new Date().toISOString())
            });
          }
        }
      }
    } catch {
      // Wind error non-fatal
    }
  }, [active]);

  // Load Spot Weather on selected hotspot
  useEffect(() => {
    if (!selectedHotspot) {
      setSpotWeather(null);
      setSpotWeatherError(null);
      return;
    }

    let isMounted = true;
    setSpotWeatherLoading(true);
    setSpotWeatherError(null);

    const lat = selectedHotspot.latitude;
    const lon = selectedHotspot.longitude;

    authFetch(`/api/weather/spot?lat=${lat}&lon=${lon}`)
      .then((res) => {
        if (!res.ok) throw new Error("Gagal mengambil prakiraan cuaca Open-Meteo");
        return res.json();
      })
      .then((data) => {
        if (isMounted) {
          setSpotWeather(data);
          setSpotWeatherLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setSpotWeatherError(err?.message || "Data cuaca spot tidak tersedia");
          setSpotWeatherLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [selectedHotspot]);

  // Initial and reactive data loads
  useEffect(() => {
    void loadHotspotData();
  }, [loadHotspotData]);

  useEffect(() => {
    void loadLayers();
    void loadWindData();
  }, [loadLayers, loadWindData]);

  // Timeline min/max timestamps
  const { minTimestamp, maxTimestamp } = useMemo(() => {
    if (hotspots.length === 0) {
      const now = new Date().getTime();
      return { minTimestamp: now - 86400000, maxTimestamp: now };
    }
    let min = Infinity;
    let max = -Infinity;
    hotspots.forEach((h) => {
      const t = new Date(h.detectedAt).getTime();
      if (!Number.isNaN(t)) {
        if (t < min) min = t;
        if (t > max) max = t;
      }
    });
    if (min === Infinity || max === -Infinity || min === max) {
      const now = new Date().getTime();
      return { minTimestamp: now - 86400000, maxTimestamp: now };
    }
    return { minTimestamp: min, maxTimestamp: max };
  }, [hotspots]);

  // Current timeline cutoff time
  const currentCutoffTime = useMemo(() => {
    if (timelineProgress >= 100) return maxTimestamp;
    return minTimestamp + ((maxTimestamp - minTimestamp) * timelineProgress) / 100;
  }, [minTimestamp, maxTimestamp, timelineProgress]);

  // Animation frame loop
  const animRef = useRef<number | null>(null);
  useEffect(() => {
    if (!isPlaying) {
      if (animRef.current) cancelAnimationFrame(animRef.current);
      return;
    }

    let lastTick = performance.now();
    const stepDuration = 8000 / playbackSpeed; // 8 seconds per full cycle at 1x

    const loop = (time: number) => {
      const delta = time - lastTick;
      lastTick = time;

      setTimelineProgress((prev) => {
        const next = prev + (delta / stepDuration) * 100;
        if (next >= 100) {
          setIsPlaying(false);
          return 100;
        }
        return next;
      });

      animRef.current = requestAnimationFrame(loop);
    };

    animRef.current = requestAnimationFrame(loop);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [isPlaying, playbackSpeed]);

  // Filtered hotspots based on toggles and timeline
  const filteredHotspots = useMemo(() => {
    if (!showHotspots) return [];

    return hotspots.filter((h) => {
      const conf = (h.confidence || "").toLowerCase();
      const isHigh = conf === "h" || conf === "high";
      const isMed = conf === "m" || conf === "nominal" || conf === "medium";
      const isLow = conf === "l" || conf === "low";

      if (isHigh && !showHighConf) return false;
      if (isMed && !showMedConf) return false;
      if (isLow && !showLowConf) return false;

      const t = new Date(h.detectedAt).getTime();
      if (!Number.isNaN(t) && timelineProgress < 100) {
        if (t > currentCutoffTime) return false;
      }

      return true;
    });
  }, [hotspots, showHotspots, showHighConf, showMedConf, showLowConf, currentCutoffTime, timelineProgress]);

  // Calculated Real Analytics & Distributions
  const analytics = useMemo(() => {
    let high = 0;
    let med = 0;
    let low = 0;
    let maxF = 0;
    let sumF = 0;
    let fCount = 0;

    const kpsMap = new Map<string, { count: number; province: string }>();
    const provMap = new Map<string, number>();

    filteredHotspots.forEach((h) => {
      const c = (h.confidence || "").toLowerCase();
      if (c === "h" || c === "high") high++;
      else if (c === "m" || c === "nominal" || c === "medium") med++;
      else low++;

      const frp = Number(h.frp || 0);
      if (frp > 0) {
        if (frp > maxF) maxF = frp;
        sumF += frp;
        fCount++;
      }

      const rawAgency = h.agencyName || h.layerName || "";
      const isLuar = !rawAgency || rawAgency === "Unassigned" || rawAgency.startsWith("Luar Kawasan");
      const agency = isLuar ? "Luar KPS" : rawAgency;
      const prov = h.provinceName && h.provinceName !== "Tanpa Provinsi" ? h.provinceName : "Indonesia";

      if (!isLuar) {
        const existingKps = kpsMap.get(agency);
        if (existingKps) {
          existingKps.count++;
        } else {
          kpsMap.set(agency, { count: 1, province: prov });
        }
      }

      provMap.set(prov, (provMap.get(prov) || 0) + 1);
    });

    const kpsDistribution = Array.from(kpsMap.entries())
      .map(([name, data]) => ({ name, count: data.count, province: data.province }))
      .sort((a, b) => b.count - a.count);

    const provinceDistribution = Array.from(provMap.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);

    // Latest hotspot detection
    let latestTime: string | null = null;
    if (filteredHotspots.length > 0) {
      const sorted = [...filteredHotspots].sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime());
      latestTime = formatDateTimeWIB(sorted[0]?.detectedAt);
    }

    return {
      total: filteredHotspots.length,
      high,
      med,
      low,
      maxFrp: Math.round(maxF * 10) / 10,
      avgFrp: fCount > 0 ? Math.round((sumF / fCount) * 10) / 10 : 0,
      kpsDistribution,
      provinceDistribution,
      topKps: kpsDistribution,
      topProvinces: provinceDistribution,
      latestTime
    };
  }, [filteredHotspots]);

  return {
    timePreset,
    setTimePreset,
    customStartDate,
    setCustomStartDate,
    customEndDate,
    setCustomEndDate,
    hotspots,
    filteredHotspots,
    layers,
    windGeoJson,
    windSummary,
    loading,
    error,
    lastUpdated: lastUpdated ? formatDateTimeWIB(lastUpdated) : null,
    syncMetrics,
    loadHotspotData,
    // Toggles
    showHotspots,
    setShowHotspots,
    showHighConf,
    setShowHighConf,
    showMedConf,
    setShowMedConf,
    showLowConf,
    setShowLowConf,
    showKps,
    setShowKps,
    showTerrain,
    setShowTerrain,
    terrainExaggeration,
    setTerrainExaggeration,
    showWind,
    setShowWind,
    basemap,
    setBasemap,
    // Selection & Weather
    selectedHotspot,
    setSelectedHotspot,
    spotWeather,
    spotWeatherLoading,
    spotWeatherError,
    // Timeline
    isPlaying,
    setIsPlaying,
    playbackSpeed,
    setPlaybackSpeed,
    timelineProgress,
    setTimelineProgress,
    currentCutoffTimeFormatted: formatDateTimeWIB(new Date(currentCutoffTime).toISOString()),
    minTimestamp,
    maxTimestamp,
    // Analytics
    analytics
  };
}
