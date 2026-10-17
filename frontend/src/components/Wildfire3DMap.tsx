import React, { useEffect, useRef, useState, useCallback } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { DashboardHotspot, DashboardLayer } from "../types/api";
import type { SpotWeatherData, WindGeoJson } from "../hooks/useWildfire3DData";
import { formatDateTimeWIB } from "../lib/date";
import { 
  Compass, 
  Layers, 
  Maximize2, 
  Minus, 
  Plus, 
  RotateCw, 
  Wind, 
  Flame, 
  MapPin, 
  Thermometer, 
  Droplets, 
  Eye, 
  Navigation
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
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);

  const [currentPitch, setCurrentPitch] = useState(50);
  const [currentBearing, setCurrentBearing] = useState(-5);
  const [currentZoom, setCurrentZoom] = useState(4.6);
  const [activeBookmark, setActiveBookmark] = useState("Seluruh RI");

  // Format Hotspots to GeoJSON FeatureCollection
  const hotspotsGeoJson = React.useMemo(() => {
    return {
      type: "FeatureCollection" as const,
      features: hotspots.map((h) => ({
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
          confidence: (h.confidence || "").toLowerCase(),
          detectedAt: h.detectedAt,
          detectedAtWib: formatDateTimeWIB(h.detectedAt),
          fungsiKawasan: h.fungsiKawasan || "Luar Kawasan Hutan",
          isInside: h.is_inside ?? false
        }
      }))
    };
  }, [hotspots]);

  // Format KPS Polygons to GeoJSON FeatureCollection
  const kpsGeoJson = React.useMemo(() => {
    const features: any[] = [];
    layers.forEach((l) => {
      if (l.geojson && (l.geojson as any).features) {
        (l.geojson as any).features.forEach((f: any) => {
          features.push({
            ...f,
            properties: {
              ...f.properties,
              layerName: l.name,
              layerLabel: l.label,
              layerColor: l.color
            }
          });
        });
      }
    });
    return {
      type: "FeatureCollection" as const,
      features
    };
  }, [layers]);

  // Format Wind to line segments representing vectors
  const windLinesGeoJson = React.useMemo(() => {
    if (!windGeoJson) return { type: "FeatureCollection" as const, features: [] };

    // Create directed line segments
    const scale = 0.08; // visual magnitude in coordinate degrees
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
      // 3D Terrain setup
      if (showTerrain) {
        map.setTerrain({ source: "terrain-dem", exaggeration: terrainExaggeration });
      }

      // 1. KPS Layers
      map.addSource("kps-source", {
        type: "geojson",
        data: kpsGeoJson
      });

      map.addLayer({
        id: "kps-fill-layer",
        type: "fill",
        source: "kps-source",
        layout: { visibility: showKps ? "visible" : "none" },
        paint: {
          "fill-color": "#10b981",
          "fill-opacity": 0.12
        }
      });

      map.addLayer({
        id: "kps-line-layer",
        type: "line",
        source: "kps-source",
        layout: { visibility: showKps ? "visible" : "none" },
        paint: {
          "line-color": "#34d399",
          "line-width": 1.4,
          "line-opacity": 0.75
        }
      });

      // 2. Wind Vectors Layer
      map.addSource("wind-lines-source", {
        type: "geojson",
        data: windLinesGeoJson
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

      // 3. Hotspot Point Layers
      map.addSource("hotspots-source", {
        type: "geojson",
        data: hotspotsGeoJson
      });

      // Outer glow pulse
      map.addLayer({
        id: "hotspots-glow-layer",
        type: "circle",
        source: "hotspots-source",
        layout: { visibility: showHotspots ? "visible" : "none" },
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            4, 7,
            8, 14,
            12, 24
          ],
          "circle-color": [
            "match",
            ["get", "confidence"],
            "h", "#ef4444",
            "high", "#ef4444",
            "m", "#f97316",
            "medium", "#f97316",
            "nominal", "#f97316",
            "l", "#eab308",
            "low", "#eab308",
            "#ef4444"
          ],
          "circle-opacity": 0.35,
          "circle-blur": 0.8
        }
      });

      // Inner core marker
      map.addLayer({
        id: "hotspots-core-layer",
        type: "circle",
        source: "hotspots-source",
        layout: { visibility: showHotspots ? "visible" : "none" },
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["zoom"],
            4, 3.5,
            8, 6.5,
            12, 10
          ],
          "circle-color": [
            "match",
            ["get", "confidence"],
            "h", "#ef4444",
            "high", "#ef4444",
            "m", "#f97316",
            "medium", "#f97316",
            "nominal", "#f97316",
            "l", "#eab308",
            "low", "#eab308",
            "#ef4444"
          ],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#ffffff"
        }
      });

      // Hotspot click interaction
      map.on("click", "hotspots-core-layer", (e) => {
        if (!e.features || e.features.length === 0) return;
        const feat = e.features[0];
        const props = feat.properties as any;
        const coords = (feat.geometry as any).coordinates as [number, number];

        // Find matching hotspot in state
        const target = hotspots.find((h) => String(h.id) === String(props.id));
        if (target) {
          onSelectHotspot(target);
        }
      });

      map.on("mouseenter", "hotspots-core-layer", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "hotspots-core-layer", () => {
        map.getCanvas().style.cursor = "";
      });

      // KPS click interaction
      map.on("click", "kps-fill-layer", (e) => {
        if (!e.features || e.features.length === 0) return;
        const f = e.features[0];
        const p = f.properties || {};
        new maplibregl.Popup({ closeButton: true, className: "custom-3d-popup" })
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

      map.on("mouseenter", "kps-fill-layer", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "kps-fill-layer", () => {
        map.getCanvas().style.cursor = "";
      });
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

  // Update Basemap Source
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const tiles = BASEMAP_TILES[basemap] || BASEMAP_TILES.satellite;
    const source = map.getSource("basemap-tiles") as maplibregl.RasterTileSource | undefined;
    if (source && (source as any).tiles) {
      // Re-add basemap raster source
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
    }
  }, [basemap]);

  // Update Terrain
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

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
  }, [showTerrain, terrainExaggeration]);

  // Update Data Sources
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource("hotspots-source") as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(hotspotsGeoJson as any);
    }
  }, [hotspotsGeoJson]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource("kps-source") as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(kpsGeoJson as any);
    }
  }, [kpsGeoJson]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource("wind-lines-source") as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(windLinesGeoJson as any);
    }
  }, [windLinesGeoJson]);

  // Update Layer Visibility Toggles
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const vis = showHotspots ? "visible" : "none";
    if (map.getLayer("hotspots-glow-layer")) map.setLayoutProperty("hotspots-glow-layer", "visibility", vis);
    if (map.getLayer("hotspots-core-layer")) map.setLayoutProperty("hotspots-core-layer", "visibility", vis);
  }, [showHotspots]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const vis = showKps ? "visible" : "none";
    if (map.getLayer("kps-fill-layer")) map.setLayoutProperty("kps-fill-layer", "visibility", vis);
    if (map.getLayer("kps-line-layer")) map.setLayoutProperty("kps-line-layer", "visibility", vis);
  }, [showKps]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const vis = showWind ? "visible" : "none";
    if (map.getLayer("wind-lines-layer")) map.setLayoutProperty("wind-lines-layer", "visibility", vis);
  }, [showWind]);

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

    // Smooth 3D flyTo
    map.flyTo({
      center: [longitude, latitude],
      zoom: Math.max(map.getZoom(), 10.5),
      pitch: 65,
      bearing: map.getBearing(),
      speed: 1.2,
      curve: 1.4,
      essential: true
    });

    // Content for hotspot popup
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

      {/* Quick Jump Regional Bookmarks Bar (Top Center) */}
      <div className="wildfire-3d-bookmarks-bar">
        <span className="bookmarks-label">
          <Navigation size={13} className="mr-1 text-amber-400" /> Jelajah Wilayah:
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
