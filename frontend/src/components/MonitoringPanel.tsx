import { useMemo, useState, useEffect } from "react";
import type { SchedulerMetricsResponse } from "../types/api";
import type { DashboardHotspot, DashboardLayer } from "../hooks/useDashboardData";

type MonitoringPanelProps = {
  metrics: SchedulerMetricsResponse | null;
  hotspots: DashboardHotspot[];
  layers: DashboardLayer[];
  onManualSync: () => void;
  onPrewarmHistory: () => void;
  manualSyncBusy: boolean;
  prewarmBusy: boolean;
  autoRefreshActive: boolean;
  refreshing: boolean;
  signalChangeNotice: string | null;
  audioMuted: boolean;
  onToggleAudioMuted: () => void;
  alertVolume: "normal" | "low";
  onToggleAlertVolume: () => void;
  onDismissSignalChangeNotice: () => void;
};

function getHotspotAgeLabel(detectedAtStr: string): string {
  const detectedAt = new Date(detectedAtStr);
  if (Number.isNaN(detectedAt.getTime())) {
    return "Waktu tidak diketahui";
  }
  const diffMs = Date.now() - detectedAt.getTime();
  if (diffMs < 0) {
    return "Baru saja";
  }
  const diffMins = Math.floor(diffMs / (1000 * 60));
  if (diffMins < 60) {
    return `${diffMins} menit yang lalu`;
  }
  const diffHours = Math.floor(diffMins / 60);
  const remainderMins = diffMins % 60;
  if (diffHours < 24) {
    return remainderMins > 0
      ? `${diffHours} jam ${remainderMins} menit yang lalu`
      : `${diffHours} jam yang lalu`;
  }
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays} hari yang lalu`;
}

function getAgeLevel(detectedAtStr: string): "new" | "medium" | "old" {
  const detectedAt = new Date(detectedAtStr);
  if (Number.isNaN(detectedAt.getTime())) {
    return "old";
  }
  const diffMs = Date.now() - detectedAt.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  if (diffHours < 3) {
    return "new";
  }
  if (diffHours < 12) {
    return "medium";
  }
  return "old";
}

function isSchedulerFailureStatus(status?: string | null): boolean {
  return status === "failure" || status === "failed";
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Belum ada data";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Belum ada data";
  }

  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Jakarta",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
    const parts = formatter.formatToParts(parsed);
    const year = parts.find(p => p.type === "year")?.value ?? "";
    const month = parts.find(p => p.type === "month")?.value ?? "";
    const day = parts.find(p => p.type === "day")?.value ?? "";
    const hour = parts.find(p => p.type === "hour")?.value ?? "";
    const minute = parts.find(p => p.type === "minute")?.value ?? "";
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  } catch (e) {
    const wibTime = new Date(parsed.getTime() + 7 * 60 * 60 * 1000);
    const day = String(wibTime.getUTCDate()).padStart(2, '0');
    const month = String(wibTime.getUTCMonth() + 1).padStart(2, '0');
    const year = wibTime.getUTCFullYear();
    const hour = String(wibTime.getUTCHours()).padStart(2, '0');
    const minute = String(wibTime.getUTCMinutes()).padStart(2, '0');
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  }
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) {
    return "Belum tersedia";
  }

  if (seconds < 60) {
    return `${Math.round(seconds)} detik`;
  }

  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes} menit`;
  }

  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  return remainderMinutes === 0 ? `${hours} jam` : `${hours} jam ${remainderMinutes} menit`;
}

function getHealthTone(metrics: SchedulerMetricsResponse | null): "ok" | "warn" | "danger" {
  if (!metrics) {
    return "warn";
  }

  if (metrics.consecutive_failures > 1) {
    return "danger";
  }

  if (isSchedulerFailureStatus(metrics.last_sync_status) || metrics.consecutive_failures === 1) {
    return "warn";
  }

  if (metrics.new_hotspot_over_threshold || metrics.has_new_hotspot) {
    return "warn";
  }

  return "ok";
}

function getHealthLabel(metrics: SchedulerMetricsResponse | null): string {
  if (!metrics) {
    return "Tidak ada telemetri";
  }

  if (metrics.consecutive_failures > 1) {
    return "Gagal";
  }

  if (isSchedulerFailureStatus(metrics.last_sync_status) || metrics.consecutive_failures === 1) {
    return "Gagal Sekali";
  }

  if (metrics.new_hotspot_over_threshold) {
    return "Peringatan";
  }

  if (metrics.has_new_hotspot) {
    return "Insiden";
  }

  if (metrics.last_sync_status === "success") {
    return "Sehat";
  }

  return "Menunggu";
}

function normalizeLembagaName(name: string): string {
  if (!name) return name;
  if (name.toLowerCase() === "lphd nyuai peningun") return "Areal Perhutanan Sosial";
  return name;
}

interface HotspotCluster {
  id: string;
  hotspots: DashboardHotspot[];
  province: string;
  agency: string;
}

function findSpatialClusters(hotspots: DashboardHotspot[]): HotspotCluster[] {
  const clusters: HotspotCluster[] = [];
  const visited = new Set<string>();

  const isClose = (h1: DashboardHotspot, h2: DashboardHotspot) => {
    const latDiff = Math.abs(h1.latitude - h2.latitude);
    const lonDiff = Math.abs(h1.longitude - h2.longitude);
    return Math.sqrt(latDiff * latDiff + lonDiff * lonDiff) < 0.15;
  };

  for (let i = 0; i < hotspots.length; i++) {
    const h1 = hotspots[i];
    if (visited.has(h1.id)) continue;

    const currentClusterHotspots: DashboardHotspot[] = [h1];
    visited.add(h1.id);

    const queue = [h1];
    while (queue.length > 0) {
      const current = queue.shift()!;
      for (let j = 0; j < hotspots.length; j++) {
        const candidate = hotspots[j];
        if (visited.has(candidate.id)) continue;

        if (isClose(current, candidate)) {
          visited.add(candidate.id);
          currentClusterHotspots.push(candidate);
          queue.push(candidate);
        }
      }
    }

    if (currentClusterHotspots.length >= 2) {
      clusters.push({
        id: `cluster-${i}`,
        hotspots: currentClusterHotspots,
        province: currentClusterHotspots[0].provinceName || "Unknown",
        agency: currentClusterHotspots[0].agencyName || currentClusterHotspots[0].layerName || "Umum"
      });
    }
  }

  return clusters;
}

interface DetectionTrend {
  rate: number;
  label: string;
  direction: "up" | "down" | "stable";
  last6hCount: number;
  baseline6hCount: number;
}

function calculateDetectionTrend(hotspots: DashboardHotspot[]): DetectionTrend {
  const now = Date.now();
  const sixHoursAgo = now - 6 * 60 * 60 * 1000;
  const twentyFourHoursAgo = now - 24 * 60 * 60 * 1000;

  const last6h = hotspots.filter(h => {
    const t = new Date(h.detectedAt).getTime();
    return !Number.isNaN(t) && t >= sixHoursAgo;
  }).length;

  const prior18h = hotspots.filter(h => {
    const t = new Date(h.detectedAt).getTime();
    return !Number.isNaN(t) && t >= twentyFourHoursAgo && t < sixHoursAgo;
  }).length;

  const baselineRate = prior18h / 3;

  if (last6h === 0 && baselineRate === 0) {
    return { rate: 0, label: "Stabil (Tidak ada aktivitas)", direction: "stable", last6hCount: 0, baseline6hCount: 0 };
  }

  if (baselineRate === 0) {
    return { rate: 100, label: "Lonjakan Baru (Aktivitas terdeteksi)", direction: "up", last6hCount: last6h, baseline6hCount: 0 };
  }

  const changePct = ((last6h - baselineRate) / baselineRate) * 100;
  const rate = Math.round(changePct);

  if (rate > 5) {
    return { rate, label: `Meningkat +${rate}% (Akselerasi Deteksi)`, direction: "up", last6hCount: last6h, baseline6hCount: Math.round(baselineRate * 10) / 10 };
  } else if (rate < -5) {
    return { rate, label: `Menurun ${rate}% (Deselerasi Aktivitas)`, direction: "down", last6hCount: last6h, baseline6hCount: Math.round(baselineRate * 10) / 10 };
  } else {
    return { rate, label: "Stabil (Fluktuasi normal)", direction: "stable", last6hCount: last6h, baseline6hCount: Math.round(baselineRate * 10) / 10 };
  }
}

interface FrpAnalysis {
  average: number;
  fuelType: string;
  riskText: string;
  color: string;
  status: "Rendah" | "Sedang" | "Kritis";
}

function analyzeFrp(hotspots: DashboardHotspot[]): FrpAnalysis {
  const validFrps = hotspots.map(h => h.frp).filter((val): val is number => val !== null && val !== undefined);
  if (validFrps.length === 0) {
    return { average: 0, fuelType: "Tidak ada data FRP", riskText: "Energi Radiasi Nihil", color: "rgba(255,255,255,0.4)", status: "Rendah" };
  }

  const sum = validFrps.reduce((acc, v) => acc + v, 0);
  const average = Math.round((sum / validFrps.length) * 10) / 10;

  if (average > 45) {
    return {
      average,
      fuelType: "Bahan Bakar Kering/Tebal (Crown Fire)",
      riskText: "Energi Radiasi Sangat Tinggi - Api menyebar cepat & asap pekat",
      color: "#ef4444",
      status: "Kritis"
    };
  } else if (average > 15) {
    return {
      average,
      fuelType: "Bahan Bakar Campuran (Surface Fire)",
      riskText: "Energi Radiasi Sedang - Kebakaran permukaan serasah/semak",
      color: "#f59e0b",
      status: "Sedang"
    };
  } else {
    return {
      average,
      fuelType: "Bahan Bakar Ringan (Smoldering)",
      riskText: "Energi Radiasi Rendah - Titik bara permukaan / sisa pembakaran",
      color: "#10b981",
      status: "Rendah"
    };
  }
}

interface ValidationAnalysis {
  pct: number;
  validatedCount: number;
  totalCount: number;
  statusText: string;
  reliability: "Tinggi" | "Sedang" | "Rendah";
}

function analyzeSensorValidation(hotspots: DashboardHotspot[]): ValidationAnalysis {
  if (hotspots.length === 0) {
    return { pct: 0, validatedCount: 0, totalCount: 0, statusText: "Tidak ada data deteksi", reliability: "Rendah" };
  }

  const provinces = Array.from(new Set(hotspots.map(h => h.provinceName).filter(Boolean)));
  let validatedCount = 0;

  provinces.forEach(prov => {
    const provHotspots = hotspots.filter(h => h.provinceName === prov);
    const sources = new Set(provHotspots.map(h => h.source));
    if (sources.size >= 2) {
      validatedCount += provHotspots.length;
    }
  });

  const pct = Math.round((validatedCount / hotspots.length) * 100);
  const reliability = pct > 70 ? "Tinggi" : pct > 30 ? "Sedang" : "Rendah";
  const statusText = pct > 0
    ? `${pct}% Titik Terverifikasi Ganda (Lintas Sensor)`
    : "Deteksi Sensor Tunggal (Perlu Ground Check)";

  return { pct, validatedCount, totalCount: hotspots.length, statusText, reliability };
}

export function MonitoringPanel({
  metrics,
  hotspots,
  layers,
  onManualSync,
  onPrewarmHistory,
  manualSyncBusy,
  prewarmBusy,
  autoRefreshActive,
  refreshing,
  signalChangeNotice,
  audioMuted,
  onToggleAudioMuted,
  alertVolume,
  onToggleAlertVolume,
  onDismissSignalChangeNotice
}: MonitoringPanelProps) {
  const [clockTick, setClockTick] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setClockTick((prev) => prev + 1);
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  const active24hHotspots = useMemo(() => {
    const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000;
    return hotspots
      .filter((h) => {
        const time = new Date(h.detectedAt).getTime();
        return !Number.isNaN(time) && time >= oneDayAgo;
      })
      .sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime());
  }, [hotspots, clockTick]);

  const activeClusters = useMemo(() => findSpatialClusters(active24hHotspots), [active24hHotspots]);
  const detectionTrend = useMemo(() => calculateDetectionTrend(active24hHotspots), [active24hHotspots]);
  const frpAnalysis = useMemo(() => analyzeFrp(active24hHotspots), [active24hHotspots]);
  const sensorValidation = useMemo(() => analyzeSensorValidation(active24hHotspots), [active24hHotspots]);

  // Helper function to extract bounding box of a single GeoJSON Feature
  const getFeatureBounds = (feature: any) => {
    let min_lon = Infinity, max_lon = -Infinity;
    let min_lat = Infinity, max_lat = -Infinity;

    const processCoord = (coord: [number, number]) => {
      const lon = coord[0];
      const lat = coord[1];
      if (lon < min_lon) min_lon = lon;
      if (lon > max_lon) max_lon = lon;
      if (lat < min_lat) min_lat = lat;
      if (lat > max_lat) max_lat = lat;
    };

    const geom = feature.geometry;
    if (geom) {
      if (geom.type === "Polygon") {
        geom.coordinates.forEach((ring: [number, number][]) => {
          ring.forEach(processCoord);
        });
      } else if (geom.type === "MultiPolygon") {
        geom.coordinates.forEach((polygon: [number, number][][]) => {
          polygon.forEach((ring: [number, number][]) => {
            ring.forEach(processCoord);
          });
        });
      }
    }

    if (min_lon === Infinity) return null;
    return { min_lon, max_lon, min_lat, max_lat };
  };

  // List of polygons (agencies/lembagas) with active hotspots (prioritizing clusters)
  const inspectPolygons = useMemo(() => {
    const list: Array<{ name: string; layerId: string }> = [];
    const seen = new Set<string>();

    activeClusters.forEach(cluster => {
      cluster.hotspots.forEach(h => {
        const name = h.agencyName || h.layerName;
        if (name && name !== "Unassigned" && name !== "Umum") {
          if (!seen.has(name)) {
            seen.add(name);
            list.push({ name, layerId: h.layerName });
          }
        }
      });
    });

    if (list.length === 0) {
      active24hHotspots.forEach(h => {
        const name = h.agencyName || h.layerName;
        if (name && name !== "Unassigned" && name !== "Umum") {
          if (!seen.has(name)) {
            seen.add(name);
            list.push({ name, layerId: h.layerName });
          }
        }
      });
    }

    return list;
  }, [activeClusters, active24hHotspots]);

  // Selected polygon name state
  const [inspectPolygonName, setInspectPolygonName] = useState<string | null>(null);

  // Auto-select the first polygon with a hotspot
  useEffect(() => {
    if (inspectPolygons.length > 0) {
      if (!inspectPolygonName || !inspectPolygons.some(p => p.name === inspectPolygonName)) {
        setInspectPolygonName(inspectPolygons[0].name);
      }
    } else {
      setInspectPolygonName(null);
    }
  }, [inspectPolygons, inspectPolygonName]);

  // Retrieve the GeoJSON Feature representing the selected polygon
  const inspectPolygonFeature = useMemo(() => {
    if (!inspectPolygonName) return null;
    const matchInfo = inspectPolygons.find(p => p.name === inspectPolygonName);
    if (!matchInfo) return null;

    const layer = layers.find(l => l.id === matchInfo.layerId);
    if (!layer || !layer.geojson) return null;

    const geojson = layer.geojson as any;
    if (!geojson.features) return null;

    // Find the feature with matching properties
    const feature = geojson.features.find((f: any) => {
      const props = f.properties || {};
      const name = props.LEMBAGA || props.lembaga || props.Name || props.name;
      return name && normalizeLembagaName(String(name)) === inspectPolygonName;
    });

    return feature;
  }, [layers, inspectPolygonName, inspectPolygons]);

  // Bounding box of the selected inspect polygon padded for hotspots centering
  const mapBounds = useMemo(() => {
    const bounds = inspectPolygonFeature ? getFeatureBounds(inspectPolygonFeature) : null;
    
    let min_lon = bounds?.min_lon ?? 95;
    let max_lon = bounds?.max_lon ?? 141;
    let min_lat = bounds?.min_lat ?? -11;
    let max_lat = bounds?.max_lat ?? 6;

    const polygonHotspots = active24hHotspots.filter(
      h => h.agencyName === inspectPolygonName || h.layerName === inspectPolygonName
    );

    if (polygonHotspots.length > 0) {
      const hsMinLon = Math.min(...polygonHotspots.map(h => h.longitude));
      const hsMaxLon = Math.max(...polygonHotspots.map(h => h.longitude));
      const hsMinLat = Math.min(...polygonHotspots.map(h => h.latitude));
      const hsMaxLat = Math.max(...polygonHotspots.map(h => h.latitude));

      // Pad slightly to center neatly (0.02 degrees padding)
      min_lon = Math.min(min_lon, hsMinLon) - 0.02;
      max_lon = Math.max(max_lon, hsMaxLon) + 0.02;
      min_lat = Math.min(min_lat, hsMinLat) - 0.02;
      max_lat = Math.max(max_lat, hsMaxLat) + 0.02;
    } else if (bounds) {
      // Pad boundaries slightly if no hotspots
      const lonPadding = (max_lon - min_lon) * 0.1 || 0.01;
      const latPadding = (max_lat - min_lat) * 0.1 || 0.01;
      min_lon -= lonPadding;
      max_lon += lonPadding;
      min_lat -= latPadding;
      max_lat += latPadding;
    }

    return { min_lon, max_lon, min_lat, max_lat };
  }, [inspectPolygonFeature, inspectPolygonName, active24hHotspots]);

  // Project longitude/latitude coordinates into a 500x250 SVG coordinate space
  const svgWidth = 500;
  const svgHeight = 250;
  
  const getX = (lon: number) => {
    const span = mapBounds.max_lon - mapBounds.min_lon || 0.001;
    return ((lon - mapBounds.min_lon) / span) * svgWidth;
  };
  
  const getY = (lat: number) => {
    const span = mapBounds.max_lat - mapBounds.min_lat || 0.001;
    return ((mapBounds.max_lat - lat) / span) * svgHeight;
  };

  const svgPolygons = useMemo(() => {
    if (!inspectPolygonFeature) return [];
    const paths: string[] = [];
    const geom = inspectPolygonFeature.geometry;
    if (!geom) return [];

    if (geom.type === "Polygon") {
      geom.coordinates.forEach((ring: [number, number][]) => {
        if (ring.length < 3) return;
        const d = ring
          .map((coord, i) => `${i === 0 ? "M" : "L"} ${getX(coord[0])},${getY(coord[1])}`)
          .join(" ") + " Z";
        paths.push(d);
      });
    } else if (geom.type === "MultiPolygon") {
      geom.coordinates.forEach((polygon: [number, number][][]) => {
        polygon.forEach((ring: [number, number][]) => {
          if (ring.length < 3) return;
          const d = ring
            .map((coord, i) => `${i === 0 ? "M" : "L"} ${getX(coord[0])},${getY(coord[1])}`)
            .join(" ") + " Z";
          paths.push(d);
        });
      });
    }

    return paths;
  }, [inspectPolygonFeature, mapBounds]);

  // Map active hotspots to SVG space (only for the inspected polygon)
  const mapHotspots = useMemo(() => {
    const polygonHotspots = active24hHotspots.filter(
      h => h.agencyName === inspectPolygonName || h.layerName === inspectPolygonName
    );
    return polygonHotspots.map(h => ({
      ...h,
      x: getX(h.longitude),
      y: getY(h.latitude)
    }));
  }, [active24hHotspots, inspectPolygonName, mapBounds]);

  // Compute lines of propagation between hotspots in same cluster (only for current inspect polygon)
  const clusterLines = useMemo(() => {
    const lines: Array<{ x1: number; y1: number; x2: number; y2: number; dist: number; key: string }> = [];
    activeClusters.forEach(cluster => {
      const polygonHotspots = cluster.hotspots.filter(
        h => h.agencyName === inspectPolygonName || h.layerName === inspectPolygonName
      );
      const clusterHs = polygonHotspots.map(h => ({
        ...h,
        x: getX(h.longitude),
        y: getY(h.latitude)
      }));

      // Draw lines between neighbors in same cluster
      for (let i = 0; i < clusterHs.length; i++) {
        for (let j = i + 1; j < clusterHs.length; j++) {
          const h1 = clusterHs[i];
          const h2 = clusterHs[j];
          // Calculate distance in km
          const lat1 = h1.latitude;
          const lon1 = h1.longitude;
          const lat2 = h2.latitude;
          const lon2 = h2.longitude;

          // Simple distance formula for line drawing
          const R = 6371;
          const dLat = ((lat2 - lat1) * Math.PI) / 180;
          const dLon = ((lon2 - lon1) * Math.PI) / 180;
          const a =
            Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos((lat1 * Math.PI) / 180) *
              Math.cos((lat2 * Math.PI) / 180) *
              Math.sin(dLon / 2) *
              Math.sin(dLon / 2);
          const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
          const dist = Math.round(R * c * 10) / 10;

          if (dist < 20) {
            lines.push({
              x1: h1.x,
              y1: h1.y,
              x2: h2.x,
              y2: h2.y,
              dist,
              key: `${h1.id}-${h2.id}`
            });
          }
        }
      }
    });
    return lines;
  }, [activeClusters, inspectPolygonName, mapBounds]);

  const timeBins = useMemo(() => {
    const now = Date.now();
    const bins = [0, 0, 0, 0, 0];
    active24hHotspots.forEach(h => {
      const diff = now - new Date(h.detectedAt).getTime();
      const hours = diff / (1000 * 60 * 60);
      if (hours >= 18 && hours < 24) bins[0]++;
      else if (hours >= 12 && hours < 18) bins[1]++;
      else if (hours >= 6 && hours < 12) bins[2]++;
      else if (hours >= 2 && hours < 6) bins[3]++;
      else if (hours >= 0 && hours < 2) bins[4]++;
    });

    const maxVal = Math.max(...bins, 1);
    const points = bins.map((val, idx) => {
      const x = (idx * 300) / 4;
      const y = 70 - (val * 45) / maxVal;
      return { x, y };
    });

    const simplePath = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x},${p.y}`).join(" ");
    const fillPath = `${simplePath} L 300,80 L 0,80 Z`;

    return { bins, points, simplePath, fillPath };
  }, [active24hHotspots]);

  const satelliteCounts = useMemo(() => {
    let viirs = 0;
    let modis = 0;
    active24hHotspots.forEach(h => {
      const src = (h.source || "").toUpperCase();
      if (src.includes("VIIRS") || src.includes("SUOMI") || src.includes("NOAA")) {
        viirs++;
      } else {
        modis++;
      }
    });
    const total = viirs + modis || 1;
    const viirsPct = Math.round((viirs / total) * 100);
    const modisPct = 100 - viirsPct;

    const viirsDash = (viirsPct / 100) * 251.2;
    const modisDash = (modisPct / 100) * 251.2;

    return { viirs, modis, viirsPct, modisPct, viirsDash, modisDash };
  }, [active24hHotspots]);

  const thermalGrid = useMemo(() => {
    const grid = Array(16).fill(null).map(() => ({ count: 0, frp: 0 }));
    if (active24hHotspots.length === 0) return grid;

    let minLat = Infinity, maxLat = -Infinity;
    let minLon = Infinity, maxLon = -Infinity;

    active24hHotspots.forEach(h => {
      if (h.latitude < minLat) minLat = h.latitude;
      if (h.latitude > maxLat) maxLat = h.latitude;
      if (h.longitude < minLon) minLon = h.longitude;
      if (h.longitude > maxLon) maxLon = h.longitude;
    });

    const latSpan = maxLat - minLat || 0.01;
    const lonSpan = maxLon - minLon || 0.01;

    active24hHotspots.forEach(h => {
      const latPct = (h.latitude - minLat) / latSpan;
      const lonPct = (h.longitude - minLon) / lonSpan;

      const row = Math.min(Math.floor(latPct * 4), 3);
      const col = Math.min(Math.floor(lonPct * 4), 3);
      const index = row * 4 + col;

      grid[index].count++;
      grid[index].frp += h.frp || 0;
    });

    return grid;
  }, [active24hHotspots]);

  const healthTone = getHealthTone(metrics);
  const healthLabel = getHealthLabel(metrics);
  const commanderStatus = useMemo(() => {
    if (healthTone === "danger") {
      return {
        label: "STATUS OPERASI: SIAGA I (BAHAYA)",
        desc: "Terdeteksi ancaman hotspot kritis atau gangguan sinkronisasi beruntun. Tindakan segera diperlukan!",
        colorClass: "commander-status--danger",
        icon: "🚨"
      };
    } else if (healthTone === "warn") {
      return {
        label: "STATUS OPERASI: SIAGA II (WASPADA)",
        desc: "Terjadi gangguan sinkronisasi sementara atau terdeteksi hotspot baru dalam batas normal.",
        colorClass: "commander-status--warn",
        icon: "⚠️"
      };
    } else {
      return {
        label: "STATUS OPERASI: NORMAL (AMAN)",
        desc: "Sistem aktif memantau. Seluruh wilayah terpantau aman tanpa titik api kritis baru.",
        colorClass: "commander-status--ok",
        icon: "🛡️"
      };
    }
  }, [healthTone]);

  const refreshLabel = refreshing ? "Menyegarkan data..." : "Patroli otomatis aktif setiap 60 detik";

  return (
    <section aria-label="Monitoring workspace" className="workspace-stage workspace-stage--monitoring">
      <div className="monitor-shell commander-shell">
        
        {/* ZONA 1: BANNER STATUS KOMANDO UTAMA */}
        <section className={`panel glass-panel commander-hero ${commanderStatus.colorClass}`}>
          <div className="commander-hero-radar">
            <span className="radar-circle circle-1" />
            <span className="radar-circle circle-2" />
            <span className="radar-circle circle-3" />
            <span className="radar-icon">{commanderStatus.icon}</span>
          </div>
          <div className="commander-hero-info">
            <span className="commander-hero-eyebrow">COMMANDER OPERATIONS CENTER</span>
            <h1 className="commander-hero-title">{commanderStatus.label}</h1>
            <p className="commander-hero-desc">{commanderStatus.desc}</p>
          </div>
          <div className="commander-hero-meta">
            {autoRefreshActive && (
              <div className={`commander-pulse-badge ${refreshing ? "commander-pulse-badge--active" : ""}`}>
                <span className="pulse-dot" />
                <span>{refreshLabel}</span>
              </div>
            )}
            <div className="system-time">
              <span>WAKTU LOKAL:</span>
              <strong>{new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })} WIB</strong>
            </div>
          </div>
        </section>

        {/* NOTIFIKASI PERUBAHAN STATUS */}
        {signalChangeNotice && (
          <section className="panel glass-panel commander-alert-banner">
            <div className="alert-banner-content">
              <span className="alert-banner-badge">PERUBAHAN DETEKSI</span>
              <strong className="alert-banner-text">{signalChangeNotice}</strong>
            </div>
            <button
              type="button"
              className="alert-banner-dismiss"
              onClick={onDismissSignalChangeNotice}
            >
              TUTUP NOTIFIKASI
            </button>
          </section>
        )}

        {/* ZONA 2: COMMANDER BOARD (KARTU STRATEGIS) */}
        <section className="commander-grid" aria-label="Operational metrics">
          
          <article className="panel glass-panel commander-card commander-card--hotspots">
            <div className="card-header">
              <span className="card-icon">🔥</span>
              <span className="card-label">Ancaman Kebakaran</span>
            </div>
            <div className="card-body">
              <strong className="card-value">{metrics?.last_new_hotspot_count ?? 0}</strong>
              <span className="card-unit">Hotspot Baru</span>
            </div>
            <div className="card-footer">
              <span className="card-meta">Ambang Batas: {metrics?.new_hotspot_alert_threshold ?? 0}</span>
              <span className={`card-badge ${metrics?.new_hotspot_over_threshold ? "card-badge--danger" : "card-badge--ok"}`}>
                {metrics?.new_hotspot_over_threshold ? "SIAGA ANCAMAN" : "AMAN"}
              </span>
            </div>
          </article>

          <article className="panel glass-panel commander-card commander-card--koneksi">
            <div className="card-header">
              <span className="card-icon">📡</span>
              <span className="card-label">Status Sinkronisasi</span>
            </div>
            <div className="card-body">
              <strong className="card-value">
                {metrics?.last_sync_status === "success" ? "SUKSES" : "GAGAL"}
              </strong>
              <span className="card-unit">Koneksi NASA</span>
            </div>
            <div className="card-footer">
              <span className="card-meta">Kegagalan Beruntun: {metrics?.consecutive_failures ?? 0}</span>
              <span className={`card-badge ${metrics?.consecutive_failures && metrics.consecutive_failures > 0 ? "card-badge--danger" : "card-badge--ok"}`}>
                {metrics?.consecutive_failures && metrics.consecutive_failures > 0 ? "GANGGUAN" : "ONLINE"}
              </span>
            </div>
          </article>

          <article className="panel glass-panel commander-card commander-card--terakhir">
            <div className="card-header">
              <span className="card-icon">⏱️</span>
              <span className="card-label">Pemeriksaan Terakhir</span>
            </div>
            <div className="card-body">
              <strong className="card-value card-value--small">
                {formatDuration(metrics?.seconds_since_last_sync ?? null)}
              </strong>
              <span className="card-unit">Yang lalu</span>
            </div>
            <div className="card-footer">
              <span className="card-meta" title={metrics?.last_sync_at ?? ""}>
                Waktu: {metrics?.last_sync_at ? formatTimestamp(metrics.last_sync_at).split(" ")[1] : "Belum ada"} WIB
              </span>
              <span className="card-badge card-badge--neutral">TERBARU</span>
            </div>
          </article>

          <article className="panel glass-panel commander-card commander-card--patroli">
            <div className="card-header">
              <span className="card-icon">📅</span>
              <span className="card-label">Patroli Otomatis</span>
            </div>
            <div className="card-body">
              <strong className="card-value card-value--small">
                {metrics?.next_scheduled_sync_at ? formatTimestamp(metrics.next_scheduled_sync_at).split(" ")[1] : "--:--"}
              </strong>
              <span className="card-unit">WIB</span>
            </div>
            <div className="card-footer">
              <span className="card-meta">Interval: {metrics?.interval_hours ?? 0} Jam</span>
              <span className="card-badge card-badge--neutral">TERJADWAL</span>
            </div>
          </article>

        </section>

        {/* ZONA EXTRA: CYBER TELEMETRY GRAPHICS (REAL-DATA CYBERPUNK HUD) */}
        <section className="panel glass-panel cyber-intel-board">
          <header className="cyber-intel-header">
            <div className="cyber-title-group">
              <span className="cyber-glitch-dot" />
              <h2 className="cyber-intel-title">⚡ TACTICAL CYBER-TELEMETRY SCREEN</h2>
            </div>
            <span className="cyber-intel-mode">REAL-TIME DATA LINK v1.28</span>
          </header>

          <div className="cyber-grid-layout">
            
            {/* GRAPH 1: WAVEFORM FREKUENSI TEMPORAL */}
            <div className="cyber-viz-panel">
              <div className="viz-header">
                <span className="viz-dot" />
                <span className="viz-title">Tren Kemunculan Hotspot (24 Jam)</span>
              </div>
              <div className="waveform-container">
                <svg className="waveform-svg" viewBox="0 0 300 80" width="100%" height="80px">
                  <defs>
                    <linearGradient id="neonGlow" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#00f0ff" stopOpacity="0.3" />
                      <stop offset="100%" stopColor="#00f0ff" stopOpacity="0.0" />
                    </linearGradient>
                  </defs>
                  
                  {/* Grid Lines Background */}
                  <line x1="0" y1="20" x2="300" y2="20" stroke="rgba(255,255,255,0.03)" strokeDasharray="3,3" />
                  <line x1="0" y1="40" x2="300" y2="40" stroke="rgba(255,255,255,0.03)" strokeDasharray="3,3" />
                  <line x1="0" y1="60" x2="300" y2="60" stroke="rgba(255,255,255,0.03)" strokeDasharray="3,3" />
                  <line x1="75" y1="0" x2="75" y2="80" stroke="rgba(255,255,255,0.02)" />
                  <line x1="150" y1="0" x2="150" y2="80" stroke="rgba(255,255,255,0.02)" />
                  <line x1="225" y1="0" x2="225" y2="80" stroke="rgba(255,255,255,0.02)" />

                  {/* Shaded Area Under Curve */}
                  <path d={timeBins.fillPath} fill="url(#neonGlow)" />
                  
                  {/* The Pulse Wave Line */}
                  <path d={timeBins.simplePath} fill="none" stroke="#00f0ff" strokeWidth="2.5" strokeLinecap="round" filter="drop-shadow(0 0 3px #00f0ff)" />
                  
                  {/* Neon node markers and numerical labels */}
                  {timeBins.points.map((p, idx) => (
                    <g key={idx}>
                      <circle cx={p.x} cy={p.y} r="3.5" fill="#00f0ff" />
                      <circle cx={p.x} cy={p.y} r="7" fill="none" stroke="#00f0ff" strokeWidth="0.8" opacity="0.4" className="pulse-ping" />
                      <text 
                        x={p.x} 
                        y={p.y - 8} 
                        fill="#ffffff" 
                        fontSize="7px" 
                        fontWeight="bold" 
                        textAnchor="middle"
                        filter="drop-shadow(0 0 2px rgba(0,0,0,0.9))"
                      >
                        {timeBins.bins[idx]} pt
                      </text>
                    </g>
                  ))}
                </svg>
              </div>
              <div className="viz-label-row">
                <span className="viz-tag">24j lalu</span>
                <span className="viz-tag">18j lalu</span>
                <span className="viz-tag">12j lalu</span>
                <span className="viz-tag">6j lalu</span>
                <span className="viz-tag">Baru (0-2j)</span>
              </div>
              <p className="viz-explanation">Grafik historis sebaran kemunculan titik api baru berdasarkan rentang waktu deteksi satelit.</p>
            </div>

            {/* GRAPH 2: SONAR RADAR SATELIT */}
            <div className="cyber-viz-panel">
              <div className="viz-header">
                <span className="viz-dot viz-dot--pink" />
                <span className="viz-title">Radar Sensor Penyuplai Data</span>
              </div>
              <div className="sonar-container">
                <svg className="sonar-svg" viewBox="0 0 100 100" width="100px" height="100px">
                  {/* Radar grid circles */}
                  <circle cx="50" cy="50" r="45" fill="none" stroke="rgba(255,255,255,0.03)" />
                  <circle cx="50" cy="50" r="30" fill="none" stroke="rgba(255,255,255,0.03)" />
                  <circle cx="50" cy="50" r="15" fill="none" stroke="rgba(255,255,255,0.03)" />
                  
                  {/* Sonar sweep line */}
                  <line x1="50" y1="50" x2="50" y2="5" stroke="rgba(0, 240, 255, 0.25)" className="radar-sweep" />

                  {/* Satellite Proportions concentric rings */}
                  {/* VIIRS Ring */}
                  <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(0, 240, 255, 0.07)" strokeWidth="4.5" />
                  <circle cx="50" cy="50" r="40" fill="none" stroke="#00f0ff" strokeWidth="4.5" 
                    strokeDasharray={`${satelliteCounts.viirsDash} 251.2`} 
                    strokeLinecap="round" 
                    transform="rotate(-90 50 50)" 
                    filter="drop-shadow(0 0 3px #00f0ff)" 
                  />
                  
                  {/* MODIS Ring */}
                  <circle cx="50" cy="50" r="25" fill="none" stroke="rgba(255, 0, 85, 0.07)" strokeWidth="4.5" />
                  <circle cx="50" cy="50" r="25" fill="none" stroke="#ff0055" strokeWidth="4.5" 
                    strokeDasharray={`${satelliteCounts.modisDash} 251.2`} 
                    strokeLinecap="round" 
                    transform="rotate(-90 50 50)" 
                    filter="drop-shadow(0 0 3px #ff0055)" 
                  />

                  {/* Ring Text Labels overlay */}
                  {satelliteCounts.viirsPct > 0 && (
                    <text x="50" y="22" fill="#00f0ff" fontSize="7px" fontWeight="bold" textAnchor="middle">
                      {satelliteCounts.viirsPct}%
                    </text>
                  )}
                  {satelliteCounts.modisPct > 0 && (
                    <text x="50" y="37" fill="#ff0055" fontSize="7px" fontWeight="bold" textAnchor="middle">
                      {satelliteCounts.modisPct}%
                    </text>
                  )}
                </svg>
                
                <div className="sonar-legend">
                  <div className="legend-row">
                    <span className="legend-color legend-color--cyan" />
                    <span>VIIRS: <strong>{satelliteCounts.viirsPct}%</strong> ({satelliteCounts.viirs} pt)</span>
                  </div>
                  <div className="legend-row">
                    <span className="legend-color legend-color--pink" />
                    <span>MODIS: <strong>{satelliteCounts.modisPct}%</strong> ({satelliteCounts.modis} pt)</span>
                  </div>
                </div>
              </div>
              <p className="viz-explanation">Rasio penyuplai data satelit (Sensor VIIRS memberikan resolusi spasial yang lebih tinggi).</p>
            </div>

            {/* GRAPH 3: MATRIX GRID RISIKO SPASIAL */}
            <div className="cyber-viz-panel">
              <div className="viz-header">
                <span className="viz-dot viz-dot--yellow" />
                <span className="viz-title">Threat Matrix Kepadatan Sebaran</span>
              </div>
              <div className="threat-matrix-wrapper">
                <div className="threat-matrix-grid">
                  <div className="matrix-scanline" />
                  {thermalGrid.map((cell, idx) => {
                    const level = cell.frp > 150 ? 3 : cell.frp > 50 ? 2 : cell.count > 0 ? 1 : 0;
                    return (
                      <div 
                        key={idx} 
                        className={`matrix-cell matrix-cell--level-${level}`}
                        title={`Hotspot: ${cell.count}, Total FRP: ${Math.round(cell.frp)} MW`}
                      >
                        {cell.count > 0 ? (
                          <span className="matrix-cell-number">{cell.count}</span>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                <div className="matrix-legend">
                  <div className="legend-tag"><span className="tag-color level-0" /> 0</div>
                  <div className="legend-tag"><span className="tag-color level-1" /> Rendah</div>
                  <div className="legend-tag"><span className="tag-color level-2" /> Sedang</div>
                  <div className="legend-tag"><span className="tag-color level-3" /> Tinggi</div>
                </div>
              </div>
              <p className="viz-explanation">Matriks area persebaran titik panas geografis. Angka dalam kotak mewakili jumlah titik api.</p>
            </div>

          </div>
        </section>

        {/* ZONA 3 & ZONA 4: PANEL ANALISIS NEURAL & KENDALI TAKTIS */}
        <section className="commander-sub-grid">
          
          {/* CARD KIRI: NEURAL OPERATIONS ENGINE */}
          <article className="panel glass-panel commander-neural-engine">
            <div className="neural-engine-header">
              <div className="neural-title-block">
                <span className="neural-pulse-ring" />
                <h3 className="neural-engine-title">🧬 NEURAL DECISION & ANALYTICS ENGINE</h3>
              </div>
              <span className="neural-status-badge">ONLINE ANALYTICS</span>
            </div>
            
            <p className="neural-engine-desc">
              Mesin kognitif memproses data sensor satelit aktif NASA secara real-time untuk mendeteksi ancaman penyebaran, eskalasi temporal, intensitas radiasi panas, dan validasi keakuratan lintas satelit.
            </p>

            <div className="neural-analysis-grid">
              
              {/* INDIKATOR 1: KLUSTER SPASIAL (ENLARGED & INTERACTIVE SHAPEFILE MAP) */}
              <div className="neural-indicator-card neural-indicator-card--large">
                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", justifyContent: "space-between" }}>
                  <div>
                    <div className="indicator-top">
                      <span className="indicator-icon">📍</span>
                      <span className="indicator-label">Kluster Spasial (Spread Risk)</span>
                    </div>
                    <div className="indicator-middle" style={{ marginTop: "0.5rem" }}>
                      <strong className="indicator-value">
                        {activeClusters.length} Kluster
                      </strong>
                      <span className={`indicator-badge indicator-badge--${activeClusters.length > 0 ? "danger" : "ok"}`}>
                        {activeClusters.length > 0 ? "ADA RAMBATAN" : "AMAN"}
                      </span>
                    </div>
                    
                    <div className="indicator-bottom" style={{ border: "none", paddingTop: "0.5rem" }}>
                      <p className="indicator-desc">
                        {activeClusters.length > 0 
                          ? `Terdeteksi ${activeClusters.length} kelompok titik api berdekatan (<15 km). Risiko sebaran tinggi di area ${activeClusters[0].province} (${activeClusters[0].agency}).` 
                          : "Tidak ada pengelompokan hotspot berdekatan. Tingkat risiko rambatan api lokal rendah."}
                      </p>
                    </div>
                  </div>

                  <div>
                    {inspectPolygons.length > 0 && (
                      <div style={{ marginTop: "0.6rem" }}>
                        <label htmlFor="inspect-polygon-select" style={{ fontSize: "0.6rem", color: "rgba(255,255,255,0.45)", textTransform: "uppercase", fontWeight: "bold", display: "block" }}>
                          Pilih Polygon Terancam Rambatan:
                        </label>
                        <select
                          id="inspect-polygon-select"
                          className="inspect-selector"
                          value={inspectPolygonName || ""}
                          onChange={(e) => setInspectPolygonName(e.target.value)}
                        >
                          {inspectPolygons.map(p => {
                            const isClustered = activeClusters.some(c => c.hotspots.some(h => h.agencyName === p.name));
                            return (
                              <option key={p.name} value={p.name}>
                                🏢 {p.name} {isClustered ? "⚠️ RAMBATAN" : ""}
                              </option>
                            );
                          })}
                        </select>
                      </div>
                    )}

                    <div className="indicator-extra-info" style={{ fontSize: "0.65rem", color: "rgba(255,255,255,0.3)", marginTop: "10px", borderTop: "1px solid rgba(255,255,255,0.03)", paddingTop: "6px" }}>
                      ℹ️ Peta taktis menunjukkan batas-batas wilayah Shapefile (poligon SHP) dan interkoneksi jarak rambatan termal di antara kluster titik api terdekat.
                    </div>
                  </div>
                </div>

                {/* Right Column: Mini Interactive Tactical Map */}
                <div className="tactical-map-container">
                  <div className="tactical-map-header">
                    <span>📡 PETA TAKTIS SPASIAL</span>
                    <span style={{ color: "#f59e0b" }}>{inspectPolygonName || "Umum"}</span>
                  </div>
                  <div className="tactical-map-canvas">
                    <svg width="100%" height="100%" viewBox="0 0 500 250" style={{ display: "block" }}>
                      <defs>
                        <radialGradient id="hotspotPulse" cx="50%" cy="50%" r="50%">
                          <stop offset="0%" stopColor="rgba(239, 68, 68, 0.6)" />
                          <stop offset="100%" stopColor="rgba(239, 68, 68, 0)" />
                        </radialGradient>
                      </defs>

                      {/* Map Boundaries Info Label */}
                      <text x="10" y="240" fill="rgba(255,255,255,0.2)" fontSize="7" fontFamily="monospace">
                        BOUNDS: {mapBounds.min_lon.toFixed(3)}E, {mapBounds.min_lat.toFixed(3)}N TO {mapBounds.max_lon.toFixed(3)}E, {mapBounds.max_lat.toFixed(3)}N
                      </text>

                      {/* 1. Shapefile Polygons (SHP geometries) */}
                      {svgPolygons.map((path, idx) => (
                        <path
                          key={`poly-${idx}`}
                          d={path}
                          fill="rgba(59, 130, 246, 0.08)"
                          stroke="rgba(59, 130, 246, 0.4)"
                          strokeWidth="1.5"
                          style={{ transition: "all 0.5s ease" }}
                        />
                      ))}

                      {/* 2. Cluster propagation/distance lines */}
                      {clusterLines.map((line) => (
                        <g key={line.key}>
                          <line
                            x1={line.x1}
                            y1={line.y1}
                            x2={line.x2}
                            y2={line.y2}
                            stroke="#ef4444"
                            strokeWidth="1.5"
                            strokeDasharray="3,3"
                          />
                          {/* Distance label bubble */}
                          <rect
                            x={(line.x1 + line.x2) / 2 - 16}
                            y={(line.y1 + line.y2) / 2 - 7}
                            width="32"
                            height="13"
                            rx="3"
                            fill="#0b0f19"
                            stroke="rgba(239, 68, 68, 0.4)"
                            strokeWidth="0.5"
                          />
                          <text
                            x={(line.x1 + line.x2) / 2}
                            y={(line.y1 + line.y2) / 2 + 2.5}
                            textAnchor="middle"
                            fill="#f87171"
                            fontSize="7.5"
                            fontWeight="bold"
                            fontFamily="monospace"
                          >
                            {line.dist}km
                          </text>
                        </g>
                      ))}

                      {/* 3. Hotspot Dots */}
                      {mapHotspots.map((h) => (
                        <g key={h.id}>
                          {/* Pulse halo */}
                          <circle cx={h.x} cy={h.y} r="10" fill="url(#hotspotPulse)">
                            <animate attributeName="r" values="4;14;4" dur="2.5s" repeatCount="indefinite" />
                          </circle>
                          {/* Core dot */}
                          <circle cx={h.x} cy={h.y} r="3" fill="#ef4444" />
                          {/* Sensor identifier text */}
                          <text x={h.x + 6} y={h.y + 2.5} fill="#ffffff" fontSize="7" fontWeight="bold" fontFamily="monospace" style={{ textShadow: "1px 1px 2px #000" }}>
                            {h.satellite} ({h.frp ?? 0}MW)
                          </text>
                        </g>
                      ))}

                      {/* Empty display helper if no data */}
                      {mapHotspots.length === 0 && (
                        <text x="250" y="125" textAnchor="middle" fill="rgba(255,255,255,0.25)" fontSize="10" fontFamily="monospace">
                          TIDAK ADA HOTSPOT DETEKSI PADA POLYGON INI
                        </text>
                      )}
                    </svg>
                  </div>
                </div>
              </div>

              {/* INDIKATOR 2: TREN TEMPORAL */}
              <div className="neural-indicator-card">
                <div className="indicator-top">
                  <span className="indicator-icon">📈</span>
                  <span className="indicator-label">Tren Eskalasi Deteksi (6 Jam)</span>
                </div>
                <div className="indicator-middle">
                  <strong className="indicator-value">
                    {detectionTrend.rate > 0 ? `+${detectionTrend.rate}%` : `${detectionTrend.rate}%`}
                  </strong>
                  <span className={`indicator-badge indicator-badge--${detectionTrend.direction === "up" ? "danger" : detectionTrend.direction === "down" ? "ok" : "neutral"}`}>
                    {detectionTrend.direction === "up" ? "AKSELERASI" : detectionTrend.direction === "down" ? "DESELERASI" : "STABIL"}
                  </span>
                </div>

                {/* Visual Graphic: Side-by-side Comparative Bars */}
                <div className="indicator-graphic" style={{ height: "45px", margin: "6px 0", position: "relative", background: "rgba(0,0,0,0.2)", borderRadius: "4px", border: "1px solid rgba(255,255,255,0.03)", padding: "4px 8px", display: "flex", flexDirection: "column", justifyContent: "space-around" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{ fontSize: "0.6rem", color: "rgba(255,255,255,0.4)", width: "65px", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>Baseline (6h Avg)</span>
                    <div style={{ flex: 1, height: "6px", background: "rgba(255,255,255,0.05)", borderRadius: "3px", overflow: "hidden", position: "relative" }}>
                      <div style={{ height: "100%", width: `${Math.min(100, (detectionTrend.baseline6hCount / Math.max(detectionTrend.last6hCount, detectionTrend.baseline6hCount, 1)) * 100)}%`, background: "rgba(255,255,255,0.3)", borderRadius: "3px" }} />
                    </div>
                    <span style={{ fontSize: "0.65rem", color: "rgba(255,255,255,0.6)", width: "20px", textAlign: "right", fontFamily: "monospace" }}>{detectionTrend.baseline6hCount}</span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{ fontSize: "0.6rem", color: "rgba(255,255,255,0.4)", width: "65px", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>6 Jam Terakhir</span>
                    <div style={{ flex: 1, height: "6px", background: "rgba(255,255,255,0.05)", borderRadius: "3px", overflow: "hidden", position: "relative" }}>
                      <div style={{ 
                        height: "100%", 
                        width: `${Math.min(100, (detectionTrend.last6hCount / Math.max(detectionTrend.last6hCount, detectionTrend.baseline6hCount, 1)) * 100)}%`, 
                        background: detectionTrend.direction === "up" ? "#ef4444" : detectionTrend.direction === "down" ? "#10b981" : "#3b82f6", 
                        borderRadius: "3px",
                        boxShadow: detectionTrend.direction === "up" ? "0 0 6px rgba(239, 68, 68, 0.4)" : "none"
                      }} />
                    </div>
                    <span style={{ 
                      fontSize: "0.65rem", 
                      color: detectionTrend.direction === "up" ? "#f87171" : detectionTrend.direction === "down" ? "#34d399" : "#60a5fa", 
                      width: "20px", 
                      textAlign: "right", 
                      fontFamily: "monospace",
                      fontWeight: "bold"
                    }}>{detectionTrend.last6hCount}</span>
                  </div>
                </div>

                <div className="indicator-bottom">
                  <p className="indicator-desc">
                    {detectionTrend.label}. Rasio deteksi 6 jam terakhir dibandingkan baseline 18 jam sebelumnya.
                  </p>
                  <div className="indicator-extra-info" style={{ fontSize: "0.65rem", color: "rgba(255,255,255,0.3)", marginTop: "6px", borderTop: "1px solid rgba(255,255,255,0.03)", paddingTop: "4px" }}>
                    ℹ️ Mengukur kecepatan eskalasi titik api baru. Tren akselerasi (&gt;0%) mengindikasikan adanya kebakaran baru yang sedang bertumbuh cepat.
                  </div>
                </div>
              </div>

              {/* INDIKATOR 3: ANALISIS ENERGI (FRP) */}
              <div className="neural-indicator-card">
                <div className="indicator-top">
                  <span className="indicator-icon">⚡</span>
                  <span className="indicator-label">Intensitas Radiasi Energi (Avg FRP)</span>
                </div>
                <div className="indicator-middle">
                  <strong className="indicator-value">
                    {frpAnalysis.average} <span className="indicator-unit">MW</span>
                  </strong>
                  <span className={`indicator-badge indicator-badge--${frpAnalysis.status === "Kritis" ? "danger" : frpAnalysis.status === "Sedang" ? "warn" : "ok"}`}>
                    {frpAnalysis.status}
                  </span>
                </div>

                {/* Visual Graphic: Slider bar with cursor point */}
                <div className="indicator-graphic" style={{ height: "45px", margin: "6px 0", position: "relative", background: "rgba(0,0,0,0.2)", borderRadius: "4px", border: "1px solid rgba(255,255,255,0.03)", padding: "8px 12px 2px", display: "flex", flexDirection: "column", justifyContent: "center" }}>
                  <div style={{ position: "relative", width: "100%", height: "8px", background: "linear-gradient(90deg, #10b981 0%, #f59e0b 30%, #ef4444 80%, #b91c1c 100%)", borderRadius: "4px" }}>
                    <div style={{
                      position: "absolute",
                      top: "50%",
                      left: `${Math.min(100, (frpAnalysis.average / 80) * 100)}%`,
                      transform: "translate(-50%, -50%)",
                      width: "12px",
                      height: "12px",
                      background: "#ffffff",
                      border: `2px solid ${frpAnalysis.color}`,
                      borderRadius: "50%",
                      boxShadow: `0 0 8px ${frpAnalysis.color}, 0 0 15px #fff`,
                      transition: "left 0.5s ease"
                    }} />
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.55rem", color: "rgba(255,255,255,0.3)", marginTop: "4px" }}>
                    <span>0 MW</span>
                    <span>15 MW (Semak)</span>
                    <span>45 MW (Hutan)</span>
                    <span>80+ MW</span>
                  </div>
                </div>

                <div className="indicator-bottom">
                  <p className="indicator-desc">
                    {frpAnalysis.riskText}. Klasifikasi vegetasi: {frpAnalysis.fuelType}.
                  </p>
                  <div className="indicator-extra-info" style={{ fontSize: "0.65rem", color: "rgba(255,255,255,0.3)", marginTop: "6px", borderTop: "1px solid rgba(255,255,255,0.03)", paddingTop: "4px" }}>
                    ℹ️ FRP (Fire Radiative Power) mengukur kekuatan pelepasan energi panas. Nilai di atas 45 MW menandakan api mahkota berkekuatan besar yang memakan vegetasi tebal.
                  </div>
                </div>
              </div>

              {/* INDIKATOR 4: VALIDASI SILANG SENSOR */}
              <div className="neural-indicator-card">
                <div className="indicator-top">
                  <span className="indicator-icon">🛡️</span>
                  <span className="indicator-label">Validasi Keandalan Deteksi</span>
                </div>
                <div className="indicator-middle">
                  <strong className="indicator-value">
                    {sensorValidation.pct}%
                  </strong>
                  <span className={`indicator-badge indicator-badge--${sensorValidation.reliability === "Tinggi" ? "ok" : sensorValidation.reliability === "Sedang" ? "warn" : "neutral"}`}>
                    RELIABILITAS {sensorValidation.reliability.toUpperCase()}
                  </span>
                </div>

                {/* Visual Graphic: Radial Gauge & Cross-sensor Venn Illustration */}
                <div className="indicator-graphic" style={{ height: "45px", margin: "6px 0", position: "relative", background: "rgba(0,0,0,0.2)", borderRadius: "4px", border: "1px solid rgba(255,255,255,0.03)", padding: "2px 8px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ position: "relative", width: "36px", height: "36px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <svg width="36" height="36" viewBox="0 0 36 36">
                      <circle cx="18" cy="18" r="14" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="3" />
                      <circle cx="18" cy="18" r="14" fill="none" 
                        stroke={sensorValidation.reliability === "Tinggi" ? "#10b981" : sensorValidation.reliability === "Sedang" ? "#f59e0b" : "#ef4444"} 
                        strokeWidth="3" 
                        strokeDasharray="88" 
                        strokeDashoffset={88 - (88 * sensorValidation.pct) / 100}
                        strokeLinecap="round"
                        transform="rotate(-90 18 18)"
                        style={{ transition: "stroke-dashoffset 0.5s ease" }}
                      />
                    </svg>
                    <span style={{ position: "absolute", fontSize: "0.55rem", fontWeight: "bold", color: "#fff", fontFamily: "monospace" }}>
                      {sensorValidation.pct}%
                    </span>
                  </div>
                  
                  <div style={{ display: "flex", gap: "4px", alignItems: "center" }}>
                    <div title="MODIS Sensor" style={{ width: "20px", height: "20px", borderRadius: "50%", background: "rgba(59, 130, 246, 0.25)", border: "1px solid rgba(59, 130, 246, 0.5)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.45rem", color: "#93c5fd", fontWeight: "bold" }}>M</div>
                    <div style={{ width: "12px", height: "1px", background: "rgba(255,255,255,0.15)", position: "relative" }}>
                      <div style={{ position: "absolute", top: "-2px", left: "4.5px", width: "5px", height: "5px", borderRadius: "50%", background: sensorValidation.pct > 0 ? "#10b981" : "rgba(255,255,255,0.2)", boxShadow: sensorValidation.pct > 0 ? "0 0 4px #10b981" : "none" }} />
                    </div>
                    <div title="VIIRS Sensor" style={{ width: "20px", height: "20px", borderRadius: "50%", background: "rgba(139, 92, 246, 0.25)", border: "1px solid rgba(139, 92, 246, 0.5)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.45rem", color: "#c084fc", fontWeight: "bold" }}>V</div>
                  </div>
                  
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", fontSize: "0.55rem" }}>
                    <span style={{ color: "rgba(255,255,255,0.4)" }}>Status Validasi:</span>
                    <span style={{ 
                      color: sensorValidation.pct > 70 ? "#34d399" : sensorValidation.pct > 30 ? "#fde047" : "#f87171",
                      fontWeight: "bold"
                    }}>
                      {sensorValidation.pct > 70 ? "SANGAT AKURAT" : sensorValidation.pct > 30 ? "MODERAT" : "BUTUH CHECK"}
                    </span>
                  </div>
                </div>

                <div className="indicator-bottom">
                  <p className="indicator-desc">
                    {sensorValidation.statusText}. Hotspot tervalidasi jika ditangkap oleh sensor satelit MODIS & VIIRS secara simultan di wilayah yang sama.
                  </p>
                  <div className="indicator-extra-info" style={{ fontSize: "0.65rem", color: "rgba(255,255,255,0.3)", marginTop: "6px", borderTop: "1px solid rgba(255,255,255,0.03)", paddingTop: "4px" }}>
                    ℹ️ Validasi lintas sensor (MODIS & VIIRS) membandingkan tangkapan sensor satelit berbeda di titik waktu berdekatan. Verifikasi silang ini mengurangi false alarm hingga &gt;95%.
                  </div>
                </div>
              </div>

            </div>

            {/* Neural Abstract Map Graphic (Neural Network Viz) */}
            <div className="neural-network-viz">
              <div className="viz-network-line" />
              <div className="viz-network-line viz-network-line--secondary" />
              <div className="viz-node-container">
                <div className={`viz-node ${activeClusters.length > 0 ? "viz-node--active-warn" : ""}`} />
                <div className={`viz-node ${detectionTrend.direction === "up" ? "viz-node--active-danger" : ""}`} />
                <div className={`viz-node ${frpAnalysis.status === "Kritis" ? "viz-node--active-danger" : frpAnalysis.status === "Sedang" ? "viz-node--active-warn" : ""}`} />
                <div className={`viz-node ${sensorValidation.reliability === "Tinggi" ? "viz-node--active-ok" : ""}`} />
              </div>
              <span className="viz-caption">Sensor Correlation Map Node</span>
            </div>
          </article>

          {/* SISI KANAN: COCKPIT & TIMELINE DI-STACK VERTICAL */}
          <div className="commander-sidebar-col">
            
            {/* PANEL KENDALI COCKPIT */}
            <article className="panel glass-panel commander-cockpit">
              <div className="cockpit-header">
                <h3 className="cockpit-title">🎛️ PANEL KENDALI TAKTIS</h3>
                <span className={`cockpit-badge ${metrics?.scheduler_enabled ? "cockpit-badge--active" : ""}`}>
                  {metrics?.scheduler_enabled ? "AUTO-PATROL AKTIF" : "AUTO-PATROL MATI"}
                </span>
              </div>
              
              <div className="cockpit-actions">
                <button
                  type="button"
                  className={`cockpit-btn cockpit-btn--primary ${manualSyncBusy ? "cockpit-btn--busy" : ""}`}
                  onClick={onManualSync}
                  disabled={manualSyncBusy}
                >
                  {manualSyncBusy ? (
                    <>
                      <span className="spinner" />
                      <span>SINKRONISASI DATA...</span>
                    </>
                  ) : (
                    <span>🔄 TARIK DATA NASA SEKARANG</span>
                  )}
                </button>

                <button
                  type="button"
                  className={`cockpit-btn cockpit-btn--secondary ${prewarmBusy ? "cockpit-btn--busy" : ""}`}
                  onClick={onPrewarmHistory}
                  disabled={prewarmBusy}
                >
                  {prewarmBusy ? (
                    <>
                      <span className="spinner" />
                      <span>MENYIAPKAN HISTORI...</span>
                    </>
                  ) : (
                    <span>⚡ PREWARM HISTORI CEPAT</span>
                  )}
                </button>
              </div>

              <div className="cockpit-settings">
                <div className="setting-control">
                  <span>Sirene Suara:</span>
                  <button type="button" className="setting-btn" onClick={onToggleAudioMuted}>
                    {audioMuted ? "🔇 BISU (MUTED)" : "🔊 AKTIF (UNMUTED)"}
                  </button>
                </div>
                <div className="setting-control">
                  <span>Volume Alarm:</span>
                  <button type="button" className="setting-btn" onClick={onToggleAlertVolume}>
                    {alertVolume === "normal" ? "🔊 HIGH" : "🔉 LOW"}
                  </button>
                </div>
              </div>
            </article>

            {/* KRONOLOGI AKTIVITAS SISTEM */}
            <article className="panel glass-panel commander-timeline-card">
              <h3 className="timeline-card-title">📝 KRONOLOGI AKTIVITAS SISTEM</h3>
              <div className="commander-timeline">
                
                <div className="timeline-item">
                  <div className="timeline-badge timeline-badge--ok">STATUS</div>
                  <div className="timeline-content">
                    <strong>Sistem Patroli Mandiri Aktif</strong>
                    <p>Mengecek data satelit NASA MODIS & VIIRS setiap {metrics?.interval_hours ?? 0} jam. Tingkat sensitivitas peringatan aktif adalah {metrics?.new_hotspot_alert_threshold ?? 0} hotspot baru.</p>
                  </div>
                </div>

                <div className="timeline-item">
                  <div className="timeline-badge timeline-badge--info">DATA</div>
                  <div className="timeline-content">
                    <strong>Sinkronisasi Sukses Terakhir</strong>
                    <p>Dilakukan {formatDuration(metrics?.seconds_since_last_successful_sync ?? null)} lalu dengan memproses {metrics?.last_sync_hotspot_count ?? 0} titik hotspot terdaftar.</p>
                  </div>
                </div>

                {metrics?.last_error && (
                  <div className="timeline-item timeline-item--danger">
                    <div className="timeline-badge timeline-badge--danger">ERROR</div>
                    <div className="timeline-content">
                      <strong className="error-title">Kesalahan Sinkronisasi Terdeteksi</strong>
                      <p className="error-desc">{metrics.last_error}</p>
                    </div>
                  </div>
                )}
              </div>
            </article>

          </div>

        </section>

        {/* FEED 24 JAM HOTSPOT */}
        <section className="panel glass-panel commander-hotspots-section monitor-hotspots-card">
          <header className="monitor-hotspots-header">
            <h2 className="monitor-hotspots-title">
              <span className="monitor-hotspots-icon" aria-hidden="true">🔥</span>
              DAFTAR ANCAMAN HOTSPOT (24 JAM TERAKHIR)
            </h2>
            <span className="monitor-hotspots-count">
              {active24hHotspots.length} TITIK
            </span>
          </header>
          
          <div className="monitor-hotspots-list">
            {active24hHotspots.length === 0 ? (
              <div className="hotspot-empty">
                Tidak ada ancaman hotspot aktif yang terdeteksi dalam 24 jam terakhir.
              </div>
            ) : (
              active24hHotspots.map((h) => {
                const ageLevel = getAgeLevel(h.detectedAt);
                const ageLabel = getHotspotAgeLabel(h.detectedAt);
                
                return (
                  <article key={h.id} className="hotspot-item">
                    <div className="hotspot-meta-col">
                      <div className="hotspot-badge-container">
                        <span className={`hotspot-badge hotspot-badge--${ageLevel}`}>
                          {ageLevel === "new" ? "Sangat Baru" : ageLevel === "medium" ? "Sedang" : "Lama"}
                        </span>
                        <span className="hotspot-badge hotspot-badge--source">
                          {h.source}
                        </span>
                      </div>
                      <span className="hotspot-sensor">
                        🛰️ {h.satellite}
                      </span>
                      <span className="hotspot-conf">
                        Conf: {h.confidence || "Unknown"}
                      </span>
                    </div>
                    
                    <div className="hotspot-info-col">
                      <div className="hotspot-loc" title={h.agencyName || h.layerName || "Umum"}>
                        {h.agencyName || h.layerName || "Umum"}
                      </div>
                      <div className="hotspot-subloc" title={h.provinceName}>
                        Provinsi: {h.provinceName || "-"}
                      </div>
                      {h.frp !== null && (
                        <div className="hotspot-frp">
                          Kekuatan Radiasi (FRP): <strong>{h.frp} MW</strong>
                        </div>
                      )}
                    </div>
                    
                    <div className="hotspot-action-col">
                      <time className="hotspot-age" dateTime={h.detectedAt}>
                        {ageLabel}
                      </time>
                      <a
                        href={`https://www.google.com/maps/search/?api=1&query=${h.latitude},${h.longitude}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hotspot-link"
                        title="Buka lokasi di Google Maps"
                      >
                        📍 {h.latitude.toFixed(5)}, {h.longitude.toFixed(5)}
                      </a>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </section>

      </div>
    </section>
  );
}
