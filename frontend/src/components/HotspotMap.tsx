import { useEffect, useRef } from "react";
import { WindLayer } from "./WindLayer";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Popup,
  TileLayer,
  useMap,
  ZoomControl
} from "react-leaflet";
import { canvas, latLngBounds } from "leaflet";

import type { LayerBounds } from "../types/api";

type HotspotRecord = {
  id: string;
  latitude: number;
  longitude: number;
  source: string;
  satellite: string;
  layerName: string;
  agencyName: string;
  provinceName: string;
  polygonMetadata?: Record<string, string>;
  brightness: number | null;
  frp?: number | null;
  confidence: string;
  daynight?: string;
  detectedAt: string;
};

type LayerRecord = {
  id: string;
  name: string;
  label: string;
  active: boolean;
  color: string;
  bounds: LayerBounds;
  geojson: Record<string, unknown>;
  geojson_mode?: "preview" | "full";
};

type HotspotMapProps = {
  hotspots: HotspotRecord[];
  layers: LayerRecord[];
  selectedProvince?: string;
  showWind?: boolean;
};

function sourceColor(source: string) {
  if (source === "MODIS") {
    return "#ff8c42";
  }

  if (source.startsWith("VIIRS")) {
    return "#facc15";
  }

  return "#ffd7a8";
}

const PROVINCE_BOUNDS: Record<string, [[number, number], [number, number]]> = {
  "ACEH": [[2.0, 95.0], [6.1, 98.4]],
  "SUMATERA UTARA": [[0.2, 97.0], [4.3, 100.7]],
  "SUMATRA UTARA": [[0.2, 97.0], [4.3, 100.7]],
  "SUMATERA BARAT": [[-3.5, 98.5], [1.0, 102.0]],
  "SUMATRA BARAT": [[-3.5, 98.5], [1.0, 102.0]],
  "RIAU": [[-1.2, 100.0], [2.5, 104.0]],
  "KEPULAUAN RIAU": [[-1.0, 103.0], [4.8, 109.2]],
  "JAMBI": [[-2.8, 101.0], [-0.7, 104.5]],
  "SUMATERA SELATAN": [[-4.9, 102.0], [-1.6, 106.2]],
  "SUMATRA SELATAN": [[-4.9, 102.0], [-1.6, 106.2]],
  "BENGKULU": [[-5.6, 101.0], [-2.3, 104.0]],
  "LAMPUNG": [[-6.0, 103.5], [-3.7, 106.0]],
  "KEPULAUAN BANGKA BELITUNG": [[-3.5, 105.0], [-1.0, 109.0]],
  "DKI JAKARTA": [[-6.4, 106.6], [-5.9, 107.0]],
  "JAWA BARAT": [[-7.9, 106.3], [-5.9, 108.9]],
  "BANTEN": [[-7.1, 105.1], [-5.9, 106.8]],
  "JAWA TENGAH": [[-8.3, 108.5], [-6.3, 111.7]],
  "DI YOGYAKARTA": [[-8.3, 110.0], [-7.5, 110.9]],
  "JAWA TIMUR": [[-8.9, 111.0], [-6.7, 114.7]],
  "BALI": [[-8.9, 114.4], [-8.0, 115.8]],
  "NUSA TENGGARA BARAT": [[-9.1, 115.7], [-8.0, 119.4]],
  "NUSA TENGGARA TIMUR": [[-11.2, 118.8], [-8.0, 125.2]],
  "KALIMANTAN BARAT": [[-3.1, 108.8], [2.2, 114.4]],
  "KALIMANTAN TENGAH": [[-3.6, 110.7], [0.8, 115.9]],
  "KALIMANTAN SELATAN": [[-4.3, 114.1], [-1.1, 117.5]],
  "KALIMANTAN TIMUR": [[-2.5, 113.8], [2.7, 119.3]],
  "KALIMANTAN UTARA": [[1.1, 114.5], [4.5, 118.1]],
  "SULAWESI UTARA": [[0.2, 121.0], [4.8, 127.2]],
  "GORONTALO": [[0.3, 121.1], [1.1, 123.6]],
  "SULAWESI TENGAH": [[-2.4, 119.2], [1.4, 124.5]],
  "SULAWESI BARAT": [[-3.5, 118.7], [-0.9, 119.9]],
  "SULAWESI SELATAN": [[-7.0, 118.7], [-1.9, 121.8]],
  "SULAWESI TENGGARA": [[-6.3, 120.8], [-2.8, 124.7]],
  "MALUKU": [[-8.4, 124.0], [-2.7, 131.6]],
  "MALUKU UTARA": [[-2.5, 124.0], [3.2, 129.5]],
  "PAPUA BARAT": [[-4.3, 131.0], [-0.3, 135.5]],
  "PAPUA": [[-9.2, 134.0], [-1.3, 141.1]],
  "PAPUA BARAT DAYA": [[-2.0, 130.0], [0.8, 133.0]],
  "PAPUA SELATAN": [[-9.1, 137.5], [-5.0, 141.0]],
  "PAPUA TENGAH": [[-5.2, 134.5], [-2.8, 138.5]],
  "PAPUA PEGUNUNGAN": [[-5.1, 137.0], [-3.2, 141.0]]
};

function MapViewport({ layers, hotspots, selectedProvince }: HotspotMapProps) {
  const map = useMap();
  const lastViewportKeyRef = useRef<string | null>(null);

  useEffect(() => {
    if (selectedProvince) {
      const provinceKey = selectedProvince.toUpperCase().trim();
      const predefinedBounds = PROVINCE_BOUNDS[provinceKey];
      if (predefinedBounds) {
        const viewportKey = `province:${provinceKey}`;
        if (lastViewportKeyRef.current !== viewportKey) {
          lastViewportKeyRef.current = viewportKey;
          map.fitBounds(predefinedBounds, { padding: [16, 16] });
        }
        return;
      }

      // Fallback zoom to hotspot coordinates if province not defined in map
      const provinceHotspots = hotspots.filter(h => h.provinceName === selectedProvince);
      if (provinceHotspots.length > 0) {
        const bounds = latLngBounds(
          provinceHotspots.map((hotspot) => [hotspot.latitude, hotspot.longitude]),
        );
        if (bounds.isValid()) {
          const viewportKey = `province-hotspots:${selectedProvince}:${provinceHotspots.length}`;
          if (lastViewportKeyRef.current !== viewportKey) {
            lastViewportKeyRef.current = viewportKey;
            map.fitBounds(bounds, { padding: [40, 40] });
          }
          return;
        }
      }
    }

    const activeLayers = layers.filter((layer) => layer.active);

    if (activeLayers.length > 0) {
      const bounds = latLngBounds([]);

      activeLayers.forEach((layer) => {
        bounds.extend([layer.bounds.min_lat, layer.bounds.min_lon]);
        bounds.extend([layer.bounds.max_lat, layer.bounds.max_lon]);
      });

      if (bounds.isValid()) {
        const viewportKey = `layers:${activeLayers.map((layer) => layer.id).join(",")}`;
        if (lastViewportKeyRef.current !== viewportKey) {
          lastViewportKeyRef.current = viewportKey;
          map.fitBounds(bounds, { padding: [24, 24] });
        }
        return;
      }
    }

    if (hotspots.length > 0) {
      const bounds = latLngBounds(
        hotspots.map((hotspot) => [hotspot.latitude, hotspot.longitude]),
      );

      if (bounds.isValid()) {
        const viewportKey = `hotspots:${hotspots.length}`;
        if (lastViewportKeyRef.current !== viewportKey) {
          lastViewportKeyRef.current = viewportKey;
          map.fitBounds(bounds, { padding: [24, 24] });
        }
      }
    }
  }, [hotspots, layers, map, selectedProvince]);

  return null;
}

function formatTimestamp(value: string) {
  if (!value) {
    return "Timestamp tidak tersedia";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Timestamp tidak tersedia";
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

function formatNumber(value: number | null) {
  if (value === null || Number.isNaN(value)) {
    return "Tidak tersedia";
  }

  return value.toFixed(2);
}

function formatMetadataValue(value?: string) {
  return value && value.trim() ? value : "Tidak tersedia";
}

export function HotspotMap({ hotspots, layers, selectedProvince, showWind }: HotspotMapProps) {
  return (
    <div className="map-frame">
      <MapContainer
        center={[-2.5, 118]}
        zoom={5}
        preferCanvas
        scrollWheelZoom
        zoomControl={false}
        style={{ height: "100%", width: "100%" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
          url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        />
        <ZoomControl position="bottomleft" />
        <MapViewport hotspots={hotspots} layers={layers} selectedProvince={selectedProvince} />
        <WindLayer visible={showWind ?? false} />
        {layers
          .filter((layer) => layer.active)
          .map((layer) => (
            <GeoJSON
              key={layer.id}
              data={layer.geojson as never}
              style={{
                color: layer.color,
                weight: 4,
                opacity: 1,
                fillColor: layer.color,
                fillOpacity: 0.18,
                dashArray: "6 5",
                lineCap: "round",
                lineJoin: "round"
              }}
            />
          ))}
        {hotspots.map((hotspot) => (
          <CircleMarker
            key={hotspot.id}
            center={[hotspot.latitude, hotspot.longitude]}
            radius={7}
            renderer={canvas()}
            pathOptions={{
              color: "#1b120d",
              weight: 2,
              fillColor: sourceColor(hotspot.source),
              fillOpacity: 0.98
            }}
          >
            <Popup>
              <div className="popup-card">
                <div className="popup-head">
                  <strong>{hotspot.source}</strong>
                  <span>{hotspot.satellite}</span>
                </div>
                <dl className="popup-grid popup-grid--tight">
                  <div>
                    <dt>Lembaga</dt>
                    <dd>{formatMetadataValue(hotspot.agencyName)}</dd>
                  </div>
                  <div>
                    <dt>Satelit</dt>
                    <dd>{hotspot.satellite}</dd>
                  </div>
                  <div>
                    <dt>Provinsi</dt>
                    <dd>{formatMetadataValue(hotspot.provinceName)}</dd>
                  </div>
                  <div>
                    <dt>Lintang</dt>
                    <dd>{hotspot.latitude.toFixed(5)}</dd>
                  </div>
                  <div>
                    <dt>Bujur</dt>
                    <dd>{hotspot.longitude.toFixed(5)}</dd>
                  </div>
                  <div>
                    <dt>Kecerahan</dt>
                    <dd>{formatNumber(hotspot.brightness)}</dd>
                  </div>
                  <div>
                    <dt>FRP</dt>
                    <dd>{formatNumber(hotspot.frp ?? null)}</dd>
                  </div>
                  <div>
                    <dt>Intensitas FRP</dt>
                    <dd>{hotspot.frp ? (hotspot.frp > 30 ? 'Tinggi' : hotspot.frp >= 10 ? 'Sedang' : 'Rendah') : 'Rendah'}</dd>
                  </div>
                  <div>
                    <dt>Terdeteksi</dt>
                    <dd>{formatTimestamp(hotspot.detectedAt)}</dd>
                  </div>
                </dl>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
