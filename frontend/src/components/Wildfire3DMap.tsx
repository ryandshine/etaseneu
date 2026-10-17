import React, { useEffect, useRef, useState, useCallback, useMemo } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DashboardHotspot, DashboardLayer } from "../types/api";
import type { SpotWeatherData, WindGeoJson } from "../hooks/useWildfire3DData";
import { formatDateTimeWIB } from "../lib/date";
import { 
  Compass, 
  Layers, 
  Minus, 
  Plus, 
  Flame, 
  Navigation,
  Zap
} from "lucide-react";

export interface Wildfire3DMapProps {
  hotspots: DashboardHotspot[];
  layers: DashboardLayer[];
  windGeoJson: WindGeoJson | null;
  showHotspots: boolean;
  showKps: boolean;
  showTerrain: boolean;
  terrainExaggeration: number;
  showWind: boolean;
  basemap: "satellite" | "dark" | "topo";
  onSelectHotspot: (hotspot: DashboardHotspot | null) => void;
  selectedHotspot: DashboardHotspot | null;
  spotWeather: SpotWeatherData | null;
  spotWeatherLoading: boolean;
  spotWeatherError: string | null;
  showRambatan?: boolean;
}

const REGION_BOOKMARKS = [
  { name: "Seluruh RI", center: [118.0, -2.5] as [number, number], zoom: 4.6, pitch: 45, bearing: -5 },
  { name: "Sumatera", center: [102.5, 0.5] as [number, number], zoom: 6.2, pitch: 55, bearing: -15 },
  { name: "Kalimantan", center: [114.0, -0.5] as [number, number], zoom: 6.2, pitch: 55, bearing: -10 },
  { name: "Sulawesi", center: [121.5, -1.8] as [number, number], zoom: 6.5, pitch: 55, bearing: 5 },
  { name: "Jawa", center: [110.5, -7.2] as [number, number], zoom: 6.8, pitch: 50, bearing: 0 },
  { name: "Maluku & Papua", center: [134.0, -3.5] as [number, number], zoom: 5.8, pitch: 50, bearing: 5 },
];

const BASEMAP_TILES: Record<string, string[]> = {
  satellite: [
    "https://mt0.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    "https://mt2.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    "https://mt3.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
  ],
  dark: [
    "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
  ],
  topo: [
    "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
    "https://b.tile.opentopomap.org/{z}/{x}/{y}.png",
    "https://c.tile.opentopomap.org/{z}/{x}/{y}.png",
  ]
};

// Compute Haversine distance in km
function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// Compute bearing angle in degrees
function getBearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const y = Math.sin(toRad(lon2 - lon1)) * Math.cos(toRad(lat2));
  const x =
    Math.cos(toRad(lat1)) * Math.sin(toRad(lat2)) -
    Math.sin(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.cos(toRad(lon2 - lon1));
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

const CARDINAL_DIRS = ["Utara", "Timur Laut", "Timur", "Tenggara", "Selatan", "Barat Daya", "Barat", "Barat Laut"];
function getCardinal(deg: number): string {
  return CARDINAL_DIRS[Math.round(deg / 45) % 8] || "Utara";
}

// Extract chronological propagation vectors across spatial clusters
function computePropagationVectors(hotspots: DashboardHotspot[]) {
  if (hotspots.length < 2) {
    return {
      lineFeatures: [] as any[],
      frontFeatures: [] as any[]
    };
  }

  // 1. Filter valid coordinates & sort chronologically
  const valid = hotspots
    .filter(h => typeof h.latitude === "number" && !isNaN(h.latitude) && typeof h.longitude === "number" && !isNaN(h.longitude) && h.detectedAt)
    .sort((a, b) => new Date(a.detectedAt).getTime() - new Date(b.detectedAt).getTime());

  if (valid.length < 2) {
    return { lineFeatures: [], frontFeatures: [] };
  }

  // 2. Spatial clustering (within 25 km)
  const CLUSTER_THRESHOLD_KM = 25.0;
  const clusters: DashboardHotspot[][] = [];

  for (const h of valid) {
    let matchedCluster: DashboardHotspot[] | null = null;
    for (const cluster of clusters) {
      const isClose = cluster.some(
        c => haversineKm(c.latitude, c.longitude, h.latitude, h.longitude) <= CLUSTER_THRESHOLD_KM
      );
      if (isClose) {
        matchedCluster = cluster;
        break;
      }
    }
    if (matchedCluster) {
      matchedCluster.push(h);
    } else {
      clusters.push([h]);
    }
  }

  const lineFeatures: any[] = [];
  const frontFeatures: any[] = [];

  clusters.forEach((cluster, clusterIdx) => {
    // Sort points inside cluster chronologically
    const clusterSorted = [...cluster].sort(
      (a, b) => new Date(a.detectedAt).getTime() - new Date(b.detectedAt).getTime()
    );

    if (clusterSorted.length >= 2) {
      for (let i = 0; i < clusterSorted.length - 1; i++) {
        const p1 = clusterSorted[i];
        const p2 = clusterSorted[i + 1];

        const dist = haversineKm(p1.latitude, p1.longitude, p2.latitude, p2.longitude);
        if (dist < 0.05) continue; // Skip identical point

        const t1 = new Date(p1.detectedAt).getTime();
        const t2 = new Date(p2.detectedAt).getTime();
        const hours = Math.max(0.1, Math.abs(t2 - t1) / 3600000);
        const speedKmH = Math.round((dist / hours) * 10) / 10;
        const bearing = Math.round(getBearing(p1.latitude, p1.longitude, p2.latitude, p2.longitude));

        lineFeatures.push({
          type: "Feature" as const,
          geometry: {
            type: "LineString" as const,
            coordinates: [
              [p1.longitude, p1.latitude],
              [p2.longitude, p2.latitude]
            ]
          },
          properties: {
            id: `rambatan-${clusterIdx}-${i}`,
            clusterId: clusterIdx,
            fromTime: p1.detectedAt,
            toTime: p2.detectedAt,
            distanceKm: Math.round(dist * 100) / 100,
            durationHours: Math.round(hours * 10) / 10,
            speedKmH,
            bearingDeg: bearing,
            cardinalDir: getCardinal(bearing),
            frp: p2.frp ?? p1.frp ?? 0
          }
        });
      }
    }

    // Active advancing fire front: latest detection of this cluster
    const latest = clusterSorted[clusterSorted.length - 1];
    frontFeatures.push({
      type: "Feature" as const,
      geometry: { type: "Point" as const, coordinates: [latest.longitude, latest.latitude] },
      properties: {
        id: `front-${clusterIdx}`,
        clusterId: clusterIdx,
        frp: latest.frp ?? 0,
        detectedAt: latest.detectedAt,
        agencyName: latest.agencyName,
        provinceName: latest.provinceName
      }
    });
  });

  return { lineFeatures, frontFeatures };
}

export const Wildfire3DMap: React.FC<Wildfire3DMapProps> = ({
  hotspots,
  layers,
  windGeoJson,
  showHotspots,
  showKps,
  showTerrain,
  terrainExaggeration,
  showWind,
  basemap,
  onSelectHotspot,
  selectedHotspot,
  spotWeather,
  spotWeatherLoading,
  spotWeatherError,
  showRambatan = true,
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  const [mapReady, setMapReady] = useState(false);
  const [currentPitch, setCurrentPitch] = useState(50);
  const [currentBearing, setCurrentBearing] = useState(-5);
  const [currentZoom, setCurrentZoom] = useState(4.6);
  const [activeBookmark, setActiveBookmark] = useState("Seluruh RI");

  // 1. Format Hotspots to GeoJSON FeatureCollection
  const hotspotsGeoJson = useMemo(() => {
    return {
      type: "FeatureCollection" as const,
      features: hotspots.map((h) => {
        const confRaw = (h.confidence || "").toLowerCase();
        const numConf = Number.parseInt(confRaw, 10);
        let normalizedConf = "high";
        if (confRaw === "l" || confRaw === "low" || (!Number.isNaN(numConf) && numConf < 30)) {
          normalizedConf = "low";
        } else if (
          confRaw === "m" ||
          confRaw === "medium" ||
          confRaw === "nominal" ||
          (!Number.isNaN(numConf) && numConf >= 30 && numConf < 80)
        ) {
          normalizedConf = "medium";
        }

        return {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: [h.longitude, h.latitude]
          },
          properties: {
            id: h.id,
            source: h.source,
            satellite: h.satellite,
            agencyName: h.agencyName,
            provinceName: h.provinceName,
            brightness: h.brightness ?? 0,
            frp: h.frp ?? 0,
            confidence: normalizedConf,
            detectedAt: h.detectedAt,
            detectedAtWib: formatDateTimeWIB(h.detectedAt),
            fungsiKawasan: h.fungsiKawasan || "Luar Kawasan Hutan",
            isInside: h.is_inside ?? false
          }
        };
      })
    };
  }, [hotspots]);

  // 2. Compute Fire Propagation / Rambatan Api GeoJSON
  const { rambatanGeoJson, rambatanFrontsGeoJson, rambatanCount } = useMemo(() => {
    const { lineFeatures, frontFeatures } = computePropagationVectors(hotspots);
    return {
      rambatanGeoJson: {
        type: "FeatureCollection" as const,
        features: lineFeatures
      },
      rambatanFrontsGeoJson: {
        type: "FeatureCollection" as const,
        features: frontFeatures
      },
      rambatanCount: lineFeatures.length
    };
  }, [hotspots]);

  // 3. Format KPS Polygons to GeoJSON FeatureCollection (Clean & Robust)
  const kpsGeoJson = useMemo(() => {
    const features: any[] = [];
    layers.forEach((l) => {
      let g: any = l.geojson;
      if (typeof g === "string") {
        try {
          g = JSON.parse(g);
        } catch {
          g = null;
        }
      }
      if (!g) return;

      const layerColor = l.color || "#10b981";
      const pushFeature = (f: any) => {
        if (!f || !f.geometry) return;
        features.push({
          type: "Feature" as const,
          geometry: f.geometry,
          properties: {
            ...(f.properties || {}),
            layerName: l.name,
            layerLabel: l.label,
            layerColor
          }
        });
      };

      if (g.type === "FeatureCollection" && Array.isArray(g.features)) {
        g.features.forEach(pushFeature);
      } else if (g.type === "Feature") {
        pushFeature(g);
      } else if (g.type === "Polygon" || g.type === "MultiPolygon") {
        pushFeature({ type: "Feature", geometry: g, properties: {} });
      }
    });

    return {
      type: "FeatureCollection" as const,
      features
    };
  }, [layers]);

  // 4. Format Wind to line segments
  const windLinesGeoJson = useMemo(() => {
    if (!windGeoJson) return { type: "FeatureCollection" as const, features: [] };

    const scale = 0.08;
    return {
      type: "FeatureCollection" as const,
      features: windGeoJson.features.map((f, i) => {
        const [lon, lat] = f.geometry.coordinates;
        const u = f.properties.u;
        const v = f.properties.v;
        const speed = Math.sqrt(u * u + v * v);
        const normU = speed > 0 ? (u / speed) * Math.min(speed * scale, 0.5) : 0;
        const normV = speed > 0 ? (v / speed) * Math.min(speed * scale, 0.5) : 0;

        return {
          type: "Feature" as const,
          geometry: {
            type: "LineString" as const,
            coordinates: [
              [lon, lat],
              [lon + normU, lat + normV]
            ]
          },
          properties: {
            id: `wind-${i}`,
            speedKmh: f.properties.speedKmh,
            directionDeg: f.properties.directionDeg,
            directionText: f.properties.directionText
          }
        };
      })
    };
  }, [windGeoJson]);

  // Live references for async MapLibre callbacks
  const hotspotsGeoJsonRef = useRef(hotspotsGeoJson);
  hotspotsGeoJsonRef.current = hotspotsGeoJson;

  const rambatanGeoJsonRef = useRef(rambatanGeoJson);
  rambatanGeoJsonRef.current = rambatanGeoJson;

  const rambatanFrontsGeoJsonRef = useRef(rambatanFrontsGeoJson);
  rambatanFrontsGeoJsonRef.current = rambatanFrontsGeoJson;

  const kpsGeoJsonRef = useRef(kpsGeoJson);
  kpsGeoJsonRef.current = kpsGeoJson;

  const windLinesGeoJsonRef = useRef(windLinesGeoJson);
  windLinesGeoJsonRef.current = windLinesGeoJson;

  const hotspotsRef = useRef(hotspots);
  hotspotsRef.current = hotspots;

  const onSelectHotspotRef = useRef(onSelectHotspot);
  onSelectHotspotRef.current = onSelectHotspot;

  // Initialize MapLibre
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const initialTiles = BASEMAP_TILES[basemap] || BASEMAP_TILES.satellite;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: {
        version: 8,
        sources: {
          "basemap-tiles": {
            type: "raster",
            tiles: initialTiles,
            tileSize: 256,
            attribution: "Basemap &copy; Google / CARTO / OpenTopoMap"
          },
          "terrain-dem": {
            type: "raster-dem",
            tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
            encoding: "terrarium",
            tileSize: 256,
            maxzoom: 15
          }
        },
        layers: [
          {
            id: "basemap-layer",
            type: "raster",
            source: "basemap-tiles",
            paint: { "raster-opacity": 1.0 }
          },
          {
            id: "hillshade-layer",
            type: "hillshade",
            source: "terrain-dem",
            paint: {
              "hillshade-exaggeration": 0.5,
              "hillshade-shadow-color": "#05070a",
              "hillshade-highlight-color": "#475569"
            }
          }
        ],
        sky: {
          "sky-color": "#090d16",
          "sky-horizon-blend": 0.6,
          "horizon-color": "#1e293b",
          "horizon-fog-blend": 0.7,
          "fog-color": "#05070c",
          "fog-ground-blend": 0.5
        }
      },
      center: [118.0, -2.5],
      zoom: 4.6,
      pitch: 50,
      bearing: -5,
      maxPitch: 85,
      minZoom: 3,
      maxZoom: 18,
      attributionControl: false
    });

    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      // 1. 3D Terrain setup
      try {
        if (showTerrain) {
          map.setTerrain({ source: "terrain-dem", exaggeration: terrainExaggeration });
        }
      } catch (err) {
        console.warn("Terrain setup failed:", err);
      }

      // 2. Hotspots Layer (FIRST, guaranteed render with map pitch alignment)
      try {
        map.addSource("hotspots-source", {
          type: "geojson",
          data: hotspotsGeoJsonRef.current
        });

        map.addLayer({
          id: "hotspots-glow-layer",
          type: "circle",
          source: "hotspots-source",
          layout: { visibility: showHotspots ? "visible" : "none" },
          paint: {
            "circle-pitch-alignment": "map",
            "circle-pitch-scale": "map",
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4, 8,
              8, 16,
              12, 28
            ],
            "circle-color": [
              "match",
              ["get", "confidence"],
              "high", "#ef4444",
              "medium", "#f97316",
              "low", "#eab308",
              "#ef4444"
            ],
            "circle-opacity": 0.5,
            "circle-blur": 0.8
          }
        });

        map.addLayer({
          id: "hotspots-core-layer",
          type: "circle",
          source: "hotspots-source",
          layout: { visibility: showHotspots ? "visible" : "none" },
          paint: {
            "circle-pitch-alignment": "map",
            "circle-pitch-scale": "map",
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4, 4,
              8, 7,
              12, 11
            ],
            "circle-color": [
              "match",
              ["get", "confidence"],
              "high", "#ff3333",
              "medium", "#f97316",
              "low", "#fbbf24",
              "#ff3333"
            ],
            "circle-stroke-width": 1.8,
            "circle-stroke-color": "#ffffff"
          }
        });

        const handleHotspotClick = (e: maplibregl.MapMouseEvent & { features?: maplibregl.MapGeoJSONFeature[] }) => {
          if (!e.features || e.features.length === 0) return;
          const feat = e.features[0];
          const props = feat.properties as any;
          const target = hotspotsRef.current.find((h) => String(h.id) === String(props.id));
          if (target) {
            onSelectHotspotRef.current(target);
          }
        };

        map.on("click", "hotspots-core-layer", handleHotspotClick);
        map.on("click", "hotspots-glow-layer", handleHotspotClick);
        map.on("mouseenter", "hotspots-core-layer", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseenter", "hotspots-glow-layer", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "hotspots-core-layer", () => { map.getCanvas().style.cursor = ""; });
        map.on("mouseleave", "hotspots-glow-layer", () => { map.getCanvas().style.cursor = ""; });
      } catch (err) {
        console.error("Gagal inisialisasi layer hotspot 3D:", err);
      }

      // 3. Animasi Rambatan Api Layers (SECOND)
      try {
        map.addSource("rambatan-source", {
          type: "geojson",
          data: rambatanGeoJsonRef.current
        });
        map.addSource("rambatan-front-source", {
          type: "geojson",
          data: rambatanFrontsGeoJsonRef.current
        });

        // Glowing outer pulse line
        map.addLayer({
          id: "rambatan-glow-layer",
          type: "line",
          source: "rambatan-source",
          layout: {
            visibility: showRambatan && showHotspots ? "visible" : "none",
            "line-join": "round",
            "line-cap": "round"
          },
          paint: {
            "line-color": "#ef4444",
            "line-width": 6.5,
            "line-opacity": 0.55,
            "line-blur": 2.5
          }
        });

        // Core directed animated dashed vector line
        map.addLayer({
          id: "rambatan-core-layer",
          type: "line",
          source: "rambatan-source",
          layout: {
            visibility: showRambatan && showHotspots ? "visible" : "none",
            "line-join": "round",
            "line-cap": "round"
          },
          paint: {
            "line-color": "#fbbf24",
            "line-width": 2.8,
            "line-opacity": 0.95,
            "line-dasharray": [3, 2]
          }
        });

        // Active front advancing pulse beacon
        map.addLayer({
          id: "rambatan-front-pulse",
          type: "circle",
          source: "rambatan-front-source",
          layout: {
            visibility: showRambatan && showHotspots ? "visible" : "none"
          },
          paint: {
            "circle-pitch-alignment": "map",
            "circle-pitch-scale": "map",
            "circle-radius": 14,
            "circle-color": "#ef4444",
            "circle-opacity": 0.45,
            "circle-blur": 0.8
          }
        });

        // Active front core head
        map.addLayer({
          id: "rambatan-front-head",
          type: "circle",
          source: "rambatan-front-source",
          layout: {
            visibility: showRambatan && showHotspots ? "visible" : "none"
          },
          paint: {
            "circle-pitch-alignment": "map",
            "circle-pitch-scale": "map",
            "circle-radius": 4.5,
            "circle-color": "#ffffff",
            "circle-stroke-width": 2,
            "circle-stroke-color": "#ef4444"
          }
        });

        // Click popup on propagation vector line
        map.on("click", "rambatan-core-layer", (e) => {
          if (!e.features || e.features.length === 0) return;
          const p = e.features[0].properties as any;
          if (popupRef.current) popupRef.current.remove();
          popupRef.current = new maplibregl.Popup({ closeButton: true, className: "custom-3d-popup" })
            .setLngLat(e.lngLat)
            .setHTML(`
              <div style="font-family: inherit; font-size: 0.8rem; padding: 4px; color: #f1f5f9;">
                <div style="font-weight: 700; color: #f59e0b; margin-bottom: 2px;">⚡ Vektor Rambatan Api Terhitung</div>
                <div>Arah: <b>${p.cardinalDir} (${p.bearingDeg}°)</b></div>
                <div>Jarak: <b>${p.distanceKm} km</b></div>
                <div>Laju: <b>~${p.speedKmH} km/jam</b></div>
                <div>Rentang Waktu: <b>${p.durationHours} jam</b></div>
              </div>
            `)
            .addTo(map);
        });

        map.on("mouseenter", "rambatan-core-layer", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "rambatan-core-layer", () => { map.getCanvas().style.cursor = ""; });
      } catch (err) {
        console.error("Gagal inisialisasi layer rambatan api 3D:", err);
      }

      // 4. KPS Layers (THIRD, optimized geojson-vt tiling)
      try {
        map.addSource("kps-source", {
          type: "geojson",
          data: kpsGeoJsonRef.current,
          tolerance: 0.8,
          buffer: 0,
          maxzoom: 10,
          generateId: true
        });

        map.addLayer({
          id: "kps-fill-layer",
          type: "fill",
          source: "kps-source",
          layout: { visibility: showKps ? "visible" : "none" },
          paint: {
            "fill-color": ["coalesce", ["get", "layerColor"], "#10b981"],
            "fill-opacity": 0.28
          }
        });

        map.addLayer({
          id: "kps-selected-fill-layer",
          type: "fill",
          source: "kps-source",
          layout: { visibility: "none" },
          paint: {
            "fill-color": "#f59e0b",
            "fill-opacity": 0.4
          }
        });

        map.addLayer({
          id: "kps-line-layer",
          type: "line",
          source: "kps-source",
          layout: { 
            visibility: showKps ? "visible" : "none",
            "line-join": "round",
            "line-cap": "round"
          },
          paint: {
            "line-color": ["coalesce", ["get", "layerColor"], "#34d399"],
            "line-width": 2.4,
            "line-opacity": 0.9
          }
        });

        map.addLayer({
          id: "kps-selected-highlight-layer",
          type: "line",
          source: "kps-source",
          layout: { 
            visibility: "none",
            "line-join": "round",
            "line-cap": "round"
          },
          paint: {
            "line-color": "#fbbf24",
            "line-width": 4.0,
            "line-opacity": 1.0
          }
        });

        map.on("click", "kps-fill-layer", (e) => {
          if (!e.features || e.features.length === 0) return;
          const hotspotHit = map.queryRenderedFeatures(e.point, {
            layers: ["hotspots-core-layer", "hotspots-glow-layer"]
          });
          if (hotspotHit.length > 0) return;

          const f = e.features[0];
          const p = f.properties || {};
          if (popupRef.current) popupRef.current.remove();

          popupRef.current = new maplibregl.Popup({ closeButton: true, className: "custom-3d-popup" })
            .setLngLat(e.lngLat)
            .setHTML(`
              <div style="font-family: inherit; font-size: 0.8rem; padding: 4px; color: #f1f5f9;">
                <div style="font-weight: 700; color: #34d399; margin-bottom: 2px;">🛡️ Kawasan Perhutanan Sosial</div>
                <div style="font-size: 0.85rem; font-weight: 600; color: #ffffff;">${p.LEMBAGA || p.NAMA_MHA || p.layerName || "Areal KPS"}</div>
                <div style="font-size: 0.75rem; color: #94a3b8; margin-top: 2px;">
                  ${p.NAMA_KAB || p.KABUPATEN || ""}, ${p.NAMA_PROV || p.PROVINSI || ""}
                </div>
                ${p.SKEMA ? `<div style="margin-top: 4px; display: inline-block; padding: 2px 6px; border-radius: 4px; background: rgba(52,211,153,0.15); color: #34d399; font-size: 0.7rem; font-weight: 600;">Skema: ${p.SKEMA}</div>` : ""}
              </div>
            `)
            .addTo(map);
        });

        map.on("mouseenter", "kps-fill-layer", () => { map.getCanvas().style.cursor = "pointer"; });
        map.on("mouseleave", "kps-fill-layer", () => { map.getCanvas().style.cursor = ""; });
      } catch (err) {
        console.error("Gagal inisialisasi layer KPS 3D:", err);
      }

      // 5. Wind Vectors Layer (FOURTH)
      try {
        map.addSource("wind-lines-source", {
          type: "geojson",
          data: windLinesGeoJsonRef.current
        });

        map.addLayer({
          id: "wind-lines-layer",
          type: "line",
          source: "wind-lines-source",
          layout: { 
            visibility: showWind ? "visible" : "none",
            "line-join": "round",
            "line-cap": "round"
          },
          paint: {
            "line-color": [
              "interpolate",
              ["linear"],
              ["get", "speedKmh"],
              0, "#38bdf8",
              15, "#fbbf24",
              30, "#f97316",
              50, "#ef4444"
            ],
            "line-width": 2.2,
            "line-opacity": 0.85
          }
        });
      } catch (err) {
        console.error("Gagal inisialisasi layer angin 3D:", err);
      }

      setMapReady(true);
      map.resize();
    });

    map.on("rotate", () => {
      setCurrentBearing(Math.round(map.getBearing()));
      setCurrentPitch(Math.round(map.getPitch()));
    });
    map.on("pitch", () => {
      setCurrentPitch(Math.round(map.getPitch()));
    });
    map.on("zoom", () => {
      setCurrentZoom(Math.round(map.getZoom() * 10) / 10);
    });

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ResizeObserver on container to prevent zero-size canvas in flex containers
  useEffect(() => {
    if (!mapContainerRef.current) return;
    const observer = new ResizeObserver(() => {
      if (mapRef.current) {
        mapRef.current.resize();
      }
    });
    observer.observe(mapContainerRef.current);

    const t1 = setTimeout(() => mapRef.current?.resize(), 150);
    const t2 = setTimeout(() => mapRef.current?.resize(), 600);

    return () => {
      observer.disconnect();
      clearTimeout(t1);
      clearTimeout(t2);
    };
  }, []);

  // Update Basemap Source
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const tiles = BASEMAP_TILES[basemap] || BASEMAP_TILES.satellite;
    try {
      const layers = map.getStyle().layers || [];
      const index = layers.findIndex(l => l.id === "basemap-layer");
      if (map.getLayer("basemap-layer")) map.removeLayer("basemap-layer");
      if (map.getSource("basemap-tiles")) map.removeSource("basemap-tiles");

      map.addSource("basemap-tiles", {
        type: "raster",
        tiles,
        tileSize: 256
      });
      map.addLayer(
        {
          id: "basemap-layer",
          type: "raster",
          source: "basemap-tiles",
          paint: { "raster-opacity": 1.0 }
        },
        index >= 0 ? layers[index + 1]?.id : undefined
      );
    } catch (err) {
      console.warn("Gagal mengubah basemap:", err);
    }
  }, [basemap, mapReady]);

  // Update Terrain
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    try {
      if (showTerrain) {
        map.setTerrain({ source: "terrain-dem", exaggeration: terrainExaggeration });
        if (map.getLayer("hillshade-layer")) {
          map.setLayoutProperty("hillshade-layer", "visibility", "visible");
        }
      } else {
        map.setTerrain(null);
        if (map.getLayer("hillshade-layer")) {
          map.setLayoutProperty("hillshade-layer", "visibility", "none");
        }
      }
    } catch {
      // Non-fatal
    }
  }, [showTerrain, terrainExaggeration, mapReady]);

  // Update Hotspots Data Source
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    try {
      const source = map.getSource("hotspots-source") as maplibregl.GeoJSONSource | undefined;
      if (source) {
        source.setData(hotspotsGeoJson as any);
      }
    } catch (err) {
      console.warn("Gagal update data hotspots-source:", err);
    }
  }, [hotspotsGeoJson, mapReady]);

  // Update Rambatan Data Source
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    try {
      const lineSource = map.getSource("rambatan-source") as maplibregl.GeoJSONSource | undefined;
      if (lineSource) {
        lineSource.setData(rambatanGeoJson as any);
      }
      const frontSource = map.getSource("rambatan-front-source") as maplibregl.GeoJSONSource | undefined;
      if (frontSource) {
        frontSource.setData(rambatanFrontsGeoJson as any);
      }
    } catch (err) {
      console.warn("Gagal update data rambatan-source:", err);
    }
  }, [rambatanGeoJson, rambatanFrontsGeoJson, mapReady]);

  // Update KPS Polygons Data Source
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    try {
      const source = map.getSource("kps-source") as maplibregl.GeoJSONSource | undefined;
      if (source) {
        source.setData(kpsGeoJson as any);
      }
    } catch (err) {
      console.warn("Gagal update data kps-source:", err);
    }
  }, [kpsGeoJson, mapReady]);

  // Update Wind Data Source
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    try {
      const source = map.getSource("wind-lines-source") as maplibregl.GeoJSONSource | undefined;
      if (source) {
        source.setData(windLinesGeoJson as any);
      }
    } catch (err) {
      console.warn("Gagal update data wind-lines-source:", err);
    }
  }, [windLinesGeoJson, mapReady]);

  // Highlight Selected Hotspot's KPS Polygon
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const agency = selectedHotspot?.agencyName?.trim();
    if (
      agency &&
      !agency.toLowerCase().startsWith("luar kawasan") &&
      !agency.toLowerCase().startsWith("luar areal") &&
      agency !== "-" &&
      agency !== "Tidak tersedia"
    ) {
      const lowerAgency = agency.toLowerCase();
      const filterExpr: any = [
        "any",
        ["==", ["downcase", ["to-string", ["coalesce", ["get", "LEMBAGA"], ""]]], lowerAgency],
        ["==", ["downcase", ["to-string", ["coalesce", ["get", "NAMA_MHA"], ""]]], lowerAgency],
        ["==", ["downcase", ["to-string", ["coalesce", ["get", "nama_kps"], ""]]], lowerAgency],
        ["==", ["downcase", ["to-string", ["coalesce", ["get", "layerLabel"], ""]]], lowerAgency],
        ["==", ["downcase", ["to-string", ["coalesce", ["get", "layerName"], ""]]], lowerAgency]
      ];

      if (map.getLayer("kps-selected-fill-layer")) {
        map.setFilter("kps-selected-fill-layer", filterExpr);
        map.setLayoutProperty("kps-selected-fill-layer", "visibility", "visible");
      }
      if (map.getLayer("kps-selected-highlight-layer")) {
        map.setFilter("kps-selected-highlight-layer", filterExpr);
        map.setLayoutProperty("kps-selected-highlight-layer", "visibility", "visible");
      }
    } else {
      if (map.getLayer("kps-selected-fill-layer")) {
        map.setLayoutProperty("kps-selected-fill-layer", "visibility", "none");
      }
      if (map.getLayer("kps-selected-highlight-layer")) {
        map.setLayoutProperty("kps-selected-highlight-layer", "visibility", "none");
      }
    }
  }, [selectedHotspot, mapReady]);

  // Fire Ember Pulsing & Rambatan Animation Effect
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !showHotspots) return;

    let animId: number;
    let lastDashUpdate = 0;
    let dashPhase = 0;
    const startTime = performance.now();

    const animateLoop = (time: number) => {
      if (!mapRef.current) return;
      const elapsed = (time - startTime) / 1000;
      
      // 1. Hotspot glow pulse (oscillation ~2.2 Hz)
      const pulseOpacity = 0.35 + 0.5 * Math.abs(Math.sin(elapsed * 2.2));
      const pulseBlur = 0.6 + 0.35 * Math.abs(Math.sin(elapsed * 2.2));

      // 2. Rambatan active front pulse
      const frontRadius = 9 + 10 * Math.abs(Math.sin(elapsed * 2.5));
      const frontOpacity = 0.3 + 0.5 * Math.abs(Math.cos(elapsed * 2.5));

      // 3. Rambatan glow line breathing
      const lineGlowOpacity = 0.4 + 0.35 * Math.abs(Math.sin(elapsed * 1.8));

      try {
        if (map.getLayer("hotspots-glow-layer")) {
          map.setPaintProperty("hotspots-glow-layer", "circle-opacity", pulseOpacity);
          map.setPaintProperty("hotspots-glow-layer", "circle-blur", pulseBlur);
        }
        if (map.getLayer("rambatan-front-pulse")) {
          map.setPaintProperty("rambatan-front-pulse", "circle-radius", frontRadius);
          map.setPaintProperty("rambatan-front-pulse", "circle-opacity", frontOpacity);
        }
        if (map.getLayer("rambatan-glow-layer")) {
          map.setPaintProperty("rambatan-glow-layer", "line-opacity", lineGlowOpacity);
        }

        // Animate rambatan line dashes every ~80ms to create forward marching flow
        if (time - lastDashUpdate > 80 && map.getLayer("rambatan-core-layer")) {
          lastDashUpdate = time;
          dashPhase = (dashPhase + 1) % 4;
          const dashArrays: [number, number][] = [
            [3, 2],
            [2, 3],
            [1, 4],
            [4, 1]
          ];
          map.setPaintProperty("rambatan-core-layer", "line-dasharray", dashArrays[dashPhase]);
        }
      } catch {
        // Style might be reloading or layer unavailable
      }

      animId = requestAnimationFrame(animateLoop);
    };

    animId = requestAnimationFrame(animateLoop);
    return () => {
      cancelAnimationFrame(animId);
    };
  }, [mapReady, showHotspots, showRambatan]);

  // Update Layer Visibility Toggles
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const vis = showHotspots ? "visible" : "none";
    if (map.getLayer("hotspots-glow-layer")) map.setLayoutProperty("hotspots-glow-layer", "visibility", vis);
    if (map.getLayer("hotspots-core-layer")) map.setLayoutProperty("hotspots-core-layer", "visibility", vis);
  }, [showHotspots, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const vis = showRambatan && showHotspots ? "visible" : "none";
    if (map.getLayer("rambatan-glow-layer")) map.setLayoutProperty("rambatan-glow-layer", "visibility", vis);
    if (map.getLayer("rambatan-core-layer")) map.setLayoutProperty("rambatan-core-layer", "visibility", vis);
    if (map.getLayer("rambatan-front-pulse")) map.setLayoutProperty("rambatan-front-pulse", "visibility", vis);
    if (map.getLayer("rambatan-front-head")) map.setLayoutProperty("rambatan-front-head", "visibility", vis);
  }, [showRambatan, showHotspots, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const vis = showKps ? "visible" : "none";
    if (map.getLayer("kps-fill-layer")) map.setLayoutProperty("kps-fill-layer", "visibility", vis);
    if (map.getLayer("kps-line-layer")) map.setLayoutProperty("kps-line-layer", "visibility", vis);
  }, [showKps, mapReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const vis = showWind ? "visible" : "none";
    if (map.getLayer("wind-lines-layer")) map.setLayoutProperty("wind-lines-layer", "visibility", vis);
  }, [showWind, mapReady]);

  // Selected Hotspot Flying & Popup
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !selectedHotspot) {
      if (popupRef.current) {
        popupRef.current.remove();
        popupRef.current = null;
      }
      return;
    }

    const { longitude, latitude } = selectedHotspot;

    map.flyTo({
      center: [longitude, latitude],
      zoom: Math.max(map.getZoom(), 10.5),
      pitch: 65,
      bearing: map.getBearing(),
      speed: 1.2,
      curve: 1.4,
      essential: true
    });

    const conf = (selectedHotspot.confidence || "").toUpperCase();
    const confColor = conf === "H" ? "#ef4444" : conf === "M" ? "#f97316" : "#eab308";
    const confLabel = conf === "H" ? "Tinggi (High)" : conf === "M" ? "Sedang (Medium)" : "Rendah (Low)";

    const popupHtml = `
      <div class="wildfire-popup-card">
        <div class="wildfire-popup-header">
          <div class="wildfire-popup-tag" style="background: ${confColor}22; color: ${confColor}; border-color: ${confColor}55;">
            🔥 ${confLabel}
          </div>
          <div class="wildfire-popup-sat">${selectedHotspot.satellite} · ${selectedHotspot.source}</div>
        </div>
        <div class="wildfire-popup-agency">${selectedHotspot.agencyName || "Luar Areal KPS"}</div>
        <div class="wildfire-popup-loc">${selectedHotspot.provinceName || "Indonesia"} · ${selectedHotspot.latitude.toFixed(4)}, ${selectedHotspot.longitude.toFixed(4)}</div>
        
        <div class="wildfire-popup-stats">
          <div class="popup-stat-item">
            <span class="stat-label">FRP</span>
            <span class="stat-val">${selectedHotspot.frp ? `${selectedHotspot.frp} MW` : "-"}</span>
          </div>
          <div class="popup-stat-item">
            <span class="stat-label">Brightness</span>
            <span class="stat-val">${selectedHotspot.brightness ? `${selectedHotspot.brightness} K` : "-"}</span>
          </div>
          <div class="popup-stat-item">
            <span class="stat-label">Kawasan</span>
            <span class="stat-val">${selectedHotspot.fungsiKawasan || "-"}</span>
          </div>
        </div>

        <div class="wildfire-popup-time">
          🕒 Waktu Deteksi: <b>${formatDateTimeWIB(selectedHotspot.detectedAt)}</b>
        </div>

        <div class="wildfire-popup-weather">
          <div class="weather-title">🌦️ Cuaca Spot Open-Meteo</div>
          ${
            spotWeatherLoading
              ? '<div class="weather-loading">Memuat prakiraan cuaca & angin...</div>'
              : spotWeatherError
              ? `<div class="weather-error">${spotWeatherError}</div>`
              : spotWeather
              ? `
                <div class="weather-grid">
                  <div class="w-item">🌡️ <b>${spotWeather.temperature ?? "-"}°C</b> Suhu</div>
                  <div class="w-item">💧 <b>${spotWeather.relative_humidity ?? "-"}%</b> Kelembaban</div>
                  <div class="w-item">🌧️ <b>${spotWeather.precipitation ?? "0"} mm</b> Hujan</div>
                  <div class="w-item">💨 <b>${spotWeather.wind_speed ?? "-"} km/h</b> Angin (${spotWeather.wind_direction ?? "-"}°)</div>
                  ${spotWeather.air_quality?.pm2_5 !== undefined ? `<div class="w-item full">🌫️ PM2.5: <b>${spotWeather.air_quality.pm2_5} µg/m³</b></div>` : ""}
                </div>
              `
              : '<div class="weather-loading">Pilih titik untuk info cuaca</div>'
          }
        </div>
      </div>
    `;

    if (popupRef.current) popupRef.current.remove();

    popupRef.current = new maplibregl.Popup({
      closeButton: true,
      closeOnClick: false,
      maxWidth: "340px",
      className: "custom-3d-popup"
    })
      .setLngLat([longitude, latitude])
      .setHTML(popupHtml)
      .addTo(map);

    popupRef.current.on("close", () => {
      onSelectHotspot(null);
    });
  }, [selectedHotspot, spotWeather, spotWeatherLoading, spotWeatherError]);

  // Camera Actions
  const handleZoomIn = () => mapRef.current?.zoomIn();
  const handleZoomOut = () => mapRef.current?.zoomOut();
  const handleResetNorth = () => {
    mapRef.current?.easeTo({ bearing: 0, pitch: 0 });
  };
  const handleCyclePitch = () => {
    const map = mapRef.current;
    if (!map) return;
    const nextPitch = currentPitch === 0 ? 45 : currentPitch === 45 ? 65 : 0;
    map.easeTo({ pitch: nextPitch });
  };
  const handleJumpToBookmark = (b: typeof REGION_BOOKMARKS[0]) => {
    setActiveBookmark(b.name);
    mapRef.current?.flyTo({
      center: b.center,
      zoom: b.zoom,
      pitch: b.pitch,
      bearing: b.bearing,
      speed: 1.0,
      curve: 1.3
    });
  };

  return (
    <div className="wildfire-3d-map-wrapper">
      {/* WebGL Map Container */}
      <div ref={mapContainerRef} className="wildfire-3d-canvas" />

      {/* Floating 3D Navigation Controls (Top Right) */}
      <div className="wildfire-3d-nav-stack">
        <button
          type="button"
          onClick={handleZoomIn}
          className="map-nav-btn"
          title="Perbesar Peta"
          aria-label="Perbesar"
        >
          <Plus size={16} />
        </button>
        <button
          type="button"
          onClick={handleZoomOut}
          className="map-nav-btn"
          title="Perkecil Peta"
          aria-label="Perkecil"
        >
          <Minus size={16} />
        </button>
        <button
          type="button"
          onClick={handleCyclePitch}
          className={`map-nav-btn ${currentPitch > 10 ? "active" : ""}`}
          title={`Kemiringan 3D: ${currentPitch}° (Klik untuk rotasi sudut)`}
          aria-label="Rotasi Kemiringan 3D"
        >
          <span className="pitch-indicator">{currentPitch}°</span>
        </button>
        <button
          type="button"
          onClick={handleResetNorth}
          className="map-nav-btn"
          title="Reset Orientasi ke Utara"
          aria-label="Reset Orientasi"
          style={{ transform: `rotate(${-currentBearing}deg)`, transition: "transform 0.2s" }}
        >
          <Compass size={17} color={currentBearing === 0 ? "#94a3b8" : "#f97316"} />
        </button>
      </div>

      {/* Quick Jump Regional Bookmarks Bar (Top Center) with Rambatan Status Pill */}
      <div className="wildfire-3d-bookmarks-bar">
        {rambatanCount > 0 && showRambatan && (
          <div className="rambatan-status-pill active" title={`${rambatanCount} vektor rambatan aktif terhitung secara kronologis`}>
            <Zap size={12} className="text-amber-400" />
            <span>Rambatan: {rambatanCount} Vektor</span>
          </div>
        )}
        <span className="bookmarks-label">
          <Navigation size={13} className="mr-1 text-amber-400" /> Wilayah:
        </span>
        <div className="bookmarks-list">
          {REGION_BOOKMARKS.map((b) => (
            <button
              key={b.name}
              type="button"
              onClick={() => handleJumpToBookmark(b)}
              className={`bookmark-pill ${activeBookmark === b.name ? "active" : ""}`}
            >
              {b.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};
