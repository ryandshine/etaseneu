import { useEffect, useRef, useState } from "react";
import { WindLayer } from "./WindLayer";
import { WeatherOverlay } from "./WeatherOverlay";
import {
  CircleMarker,
  GeoJSON,
  MapContainer,
  Popup,
  Marker,
  TileLayer,
  useMap,
  ZoomControl
} from "react-leaflet";
import { canvas, latLngBounds, divIcon } from "leaflet";

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
  weatherOverlay?: "temperature" | "humidity" | "precipitation" | "soil_moisture" | "fwi" | null;
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

const rainIcon = divIcon({
  html: `
    <style>
      @keyframes pulse-rain {
        0% {
          transform: scale(0.9);
          box-shadow: 0 0 0 0 rgba(56, 189, 248, 0.7);
        }
        70% {
          transform: scale(1.05);
          box-shadow: 0 0 0 10px rgba(56, 189, 248, 0);
        }
        100% {
          transform: scale(0.9);
          box-shadow: 0 0 0 0 rgba(56, 189, 248, 0);
        }
      }
    </style>
    <div class="rain-glowing-icon" style="
      display: flex;
      align-items: center;
      justify-content: center;
      background: rgba(56, 189, 248, 0.25);
      border: 2px solid rgb(56, 189, 248);
      border-radius: 50%;
      width: 32px;
      height: 32px;
      box-shadow: 0 0 12px rgb(56, 189, 248), inset 0 0 8px rgb(56, 189, 248);
      color: #fff;
      animation: pulse-rain 2s infinite;
    ">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-cloud-rain"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M16 14v6"/><path d="M8 14v6"/><path d="M12 16v6"/></svg>
    </div>
  `,
  className: '',
  iconSize: [32, 32],
  iconAnchor: [16, 16]
});

type SpotWeather = {
  current: {
    temperature: number;
    humidity: number;
    precipitation: number;
    wind_speed: number;
    wind_direction: number;
    wind_gusts: number;
    soil_moisture: number;
    soil_moisture_status: string;
    soil_moisture_color: string;
    weather_code: number;
    fire_danger: {
      value: number;
      level: string;
      color: string;
    };
  };
  air_quality: {
    pm2_5: number;
    pm10: number;
    carbon_monoxide: number;
    aqi: number;
  };
};

function HotspotWeatherPopup({ lat, lon }: { lat: number; lon: number }) {
  const [data, setData] = useState<SpotWeather | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);

    fetch(`/api/weather/spot?lat=${lat}&lon=${lon}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed");
        return res.json() as Promise<SpotWeather>;
      })
      .then((payload) => {
        if (active) {
          setData(payload);
        }
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [lat, lon]);

  if (loading) {
    return (
      <div className="weather-popup-loader" style={{ fontSize: '11px', color: '#94a3b8', padding: '4px 0' }}>
        <span>⚡ Memuat data cuaca & kualitas udara...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="weather-popup-error" style={{ fontSize: '11px', color: '#ef4444', padding: '4px 0' }}>
        ⚠️ Gagal memuat info cuaca Open-Meteo.
      </div>
    );
  }

  return (
    <div className="weather-popup-content" style={{ borderTop: '1px solid rgba(255,255,255,0.1)', marginTop: '8px', paddingTop: '8px' }}>
      <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#facc15', marginBottom: '6px' }}>Cuaca & Kualitas Udara Lokal</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 8px', fontSize: '11px' }}>
        <div>
          <span style={{ color: '#94a3b8' }}>Suhu: </span>
          <strong>{data.current.temperature.toFixed(1)} °C</strong>
        </div>
        <div>
          <span style={{ color: '#94a3b8' }}>RH: </span>
          <strong>{data.current.humidity.toFixed(0)}%</strong>
        </div>
        <div>
          <span style={{ color: '#94a3b8' }}>Hujan: </span>
          <strong>{data.current.precipitation.toFixed(1)} mm</strong>
        </div>
        <div>
          <span style={{ color: '#94a3b8' }}>Angin: </span>
          <strong>{data.current.wind_speed.toFixed(1)} m/s</strong>
        </div>
        <div style={{ gridColumn: 'span 2' }}>
          <span style={{ color: '#94a3b8' }}>Gambut: </span>
          <strong style={{ color: data.current.soil_moisture_color }}>
            {data.current.soil_moisture_status} ({(data.current.soil_moisture * 100).toFixed(1)}%)
          </strong>
        </div>
        <div style={{ gridColumn: 'span 2' }}>
          <span style={{ color: '#94a3b8' }}>Bahaya Api (CBI): </span>
          <strong style={{ color: data.current.fire_danger.color }}>
            {data.current.fire_danger.level} ({data.current.fire_danger.value})
          </strong>
        </div>
        <div style={{ gridColumn: 'span 2' }}>
          <span style={{ color: '#94a3b8' }}>Udara (AQI): </span>
          <strong style={{ color: data.air_quality.aqi > 100 ? '#ef4444' : data.air_quality.aqi > 50 ? '#eab308' : '#22c55e' }}>
            {data.air_quality.aqi} AQI (PM2.5: {data.air_quality.pm2_5.toFixed(1)})
          </strong>
        </div>
      </div>
    </div>
  );
}

export function HotspotMap({ hotspots, layers, selectedProvince, showWind, weatherOverlay }: HotspotMapProps) {
  const [rainyCoords, setRainyCoords] = useState<{ lat: number; lon: number; precipitation: number; label: string }[]>([]);

  useEffect(() => {
    const activeLayers = layers.filter(l => l.active);
    if (activeLayers.length === 0) {
      setRainyCoords([]);
      return;
    }

    const coordsParam = activeLayers
      .map(l => {
        const lat = (l.bounds.min_lat + l.bounds.max_lat) / 2;
        const lon = (l.bounds.min_lon + l.bounds.max_lon) / 2;
        return `${lat},${lon}`;
      })
      .join(";");

    if (!coordsParam) {
      setRainyCoords([]);
      return;
    }

    let active = true;
    const fetchRain = () => {
      fetch(`/api/weather/rain-check?coords=${encodeURIComponent(coordsParam)}`)
        .then(res => {
          if (!res.ok) throw new Error("Failed");
          return res.json();
        })
        .then((data: any[]) => {
          if (!active) return;
          const rainy = data
            .filter((item: any) => item.is_raining)
            .map((item: any, index: number) => {
              const matchLayer = activeLayers[index];
              return {
                lat: item.latitude,
                lon: item.longitude,
                precipitation: item.precipitation,
                label: matchLayer ? matchLayer.label : "Kawasan Hutan"
              };
            });
          setRainyCoords(rainy);
        })
        .catch(err => {
          console.error("Rain check failed", err);
        });
    };

    fetchRain();
    const interval = setInterval(fetchRain, 15 * 60 * 1000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [layers]);

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
        <WeatherOverlay parameter={weatherOverlay ?? null} />
        {rainyCoords.map((coord, idx) => (
          <Marker
            key={`rain-${idx}`}
            position={[coord.lat, coord.lon]}
            icon={rainIcon}
          >
            <Popup>
              <div style={{ fontSize: "12px", fontFamily: "sans-serif" }}>
                <strong style={{ color: "#0ea5e9" }}>🌧️ Sedang Terjadi Hujan</strong>
                <div style={{ marginTop: "4px" }}>
                  Wilayah: <strong>{coord.label}</strong>
                </div>
                <div>
                  Curah Hujan: <strong>{coord.precipitation.toFixed(1)} mm/jam</strong>
                </div>
              </div>
            </Popup>
          </Marker>
        ))}
        {layers
          .filter((layer) => layer.active)
          .map((layer) => (
            <GeoJSON
              key={layer.id}
              data={layer.geojson as never}
              interactive={false}
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
                <HotspotWeatherPopup lat={hotspot.latitude} lon={hotspot.longitude} />
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  );
}
