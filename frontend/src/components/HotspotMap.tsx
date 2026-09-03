import { useEffect, useMemo, useRef, useState } from "react";
import { authFetch } from "../lib/api";
import { formatHectares } from "../lib/hotspotDisplay";
import { SMOOTH_ZOOM_MAP_PROPS } from "../constants/map";
import { Flame, LocateFixed, Trees } from "lucide-react";
import { WindLayer } from "./WindLayer";
import { WeatherOverlay } from "./WeatherOverlay";
import {
  CoordinateActions,
  HIGH_FRP_THRESHOLD,
  HotspotPopupContent,
  HotspotWeatherPopup,
  formatNumber
} from "./HotspotPopupContent";
import {
  Circle,
  CircleMarker,
  GeoJSON,
  LayerGroup,
  MapContainer,
  Pane,
  Popup,
  Marker,
  TileLayer,
  useMap,
  ZoomControl
} from "react-leaflet";
import { canvas, circleMarker as buildLeafletCircleMarker, latLngBounds, divIcon } from "leaflet";
import type { LayerGroup as LLayerGroup } from "leaflet";

import { useBurnedAreaOverlay } from "../hooks/useBurnedAreaOverlay";
import type { BurnedAreaOverlayFeature } from "../hooks/useBurnedAreaOverlay";
import { useS2BurnedAreaOverlay } from "../hooks/useS2BurnedAreaOverlay";
import type { S2BurnedAreaFeature } from "../hooks/useS2BurnedAreaOverlay";
import { KawasanHutanLayer } from "./KawasanHutanLayer";
import { PolygonInfoLayer } from "./PolygonInfoLayer";
import { KAWASAN_HUTAN_LEGEND } from "../constants/kawasanHutan";
import type { LayerBounds } from "../types/api";

const MONTH_LABELS = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember"
];

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
  fungsiKawasan?: string;
  namaKawasan?: string;
  kelompokKawasan?: string;
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
  selectedWilker?: string;
  showWind?: boolean;
  weatherOverlay?: "temperature" | "humidity" | "precipitation" | "soil_moisture" | "fwi" | null;
  onOpenKpsDetail?: (agency: string) => void;
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


const highIntensityIconCache = new Map<string, ReturnType<typeof divIcon>>();

function getHighIntensityIcon(color: string) {
  const cached = highIntensityIconCache.get(color);
  if (cached) {
    return cached;
  }

  const icon = divIcon({
    html: `<span class="hotspot-pulse-marker" style="--hotspot-pulse-color: ${color};">
      <span class="hotspot-pulse-ring"></span>
      <span class="hotspot-pulse-core"></span>
    </span>`,
    className: "",
    iconSize: [16, 16],
    iconAnchor: [8, 8]
  });

  highIntensityIconCache.set(color, icon);
  return icon;
}

const userLocationIcon = divIcon({
  html: `<span class="user-location-marker">
    <span class="user-location-pulse"></span>
    <span class="user-location-core"></span>
  </span>`,
  className: "",
  iconSize: [18, 18],
  iconAnchor: [9, 9]
});

function geolocationErrorMessage(error: GeolocationPositionError): string {
  switch (error.code) {
    case error.PERMISSION_DENIED:
      return "Izin lokasi ditolak. Aktifkan izin lokasi untuk situs ini di pengaturan browser.";
    case error.POSITION_UNAVAILABLE:
      return "Lokasi tidak tersedia saat ini. Coba lagi di area dengan sinyal GPS lebih baik.";
    case error.TIMEOUT:
      return "Waktu permintaan lokasi habis. Coba lagi.";
    default:
      return "Gagal mengambil lokasi Anda.";
  }
}

type UserLocationFix = { lat: number; lon: number; accuracy: number };

function useUserLocationWatch(active: boolean) {
  const [position, setPosition] = useState<UserLocationFix | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) {
      setPosition(null);
      setError(null);
      return;
    }

    if (!("geolocation" in navigator)) {
      setError("Geolocation tidak didukung oleh perangkat/browser ini.");
      return;
    }

    setError(null);
    const watchId = navigator.geolocation.watchPosition(
      (pos) => {
        setError(null);
        setPosition({
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          accuracy: pos.coords.accuracy
        });
      },
      (err) => {
        setError(geolocationErrorMessage(err));
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 }
    );

    return () => navigator.geolocation.clearWatch(watchId);
  }, [active]);

  return { position, error, loading: active && !position && !error };
}

const USER_WEATHER_REFETCH_METERS = 500;

function distanceMeters(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const earthRadiusMeters = 6371000;
  const dLat = ((b.lat - a.lat) * Math.PI) / 180;
  const dLon = ((b.lon - a.lon) * Math.PI) / 180;
  const lat1 = (a.lat * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusMeters * Math.asin(Math.sqrt(h));
}

// GPS watchPosition mengirim titik baru tiap beberapa detik meski user diam
// di tempat (jitter beberapa meter). Cuaca/AQI dianchor ke titik yang cuma
// bergeser kalau lokasinya benar-benar berpindah signifikan, supaya popup
// cuaca di marker lokasi user tidak memanggil /api/weather/spot berkali-kali
// untuk pergeseran yang tidak berarti.
function useThrottledWeatherAnchor(position: UserLocationFix | null) {
  const [anchor, setAnchor] = useState<{ lat: number; lon: number } | null>(null);

  useEffect(() => {
    if (!position) {
      setAnchor(null);
      return;
    }
    setAnchor((current) => {
      if (!current || distanceMeters(current, position) > USER_WEATHER_REFETCH_METERS) {
        return { lat: position.lat, lon: position.lon };
      }
      return current;
    });
  }, [position]);

  return anchor;
}

// Memusatkan peta ke lokasi user sekali saat titik GPS pertama datang, bukan
// setiap update posisi -- supaya user tetap bebas menggeser peta sementara
// penanda lokasinya terus bergerak mengikuti GPS di latar belakang.
function UserLocationRecenter({ lat, lon }: { lat: number; lon: number }) {
  const map = useMap();
  const hasCenteredRef = useRef(false);

  useEffect(() => {
    if (hasCenteredRef.current) {
      return;
    }
    hasCenteredRef.current = true;
    map.setView([lat, lon], Math.max(map.getZoom(), 13));
  }, [lat, lon, map]);

  return null;
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

export function HotspotMap({
  hotspots,
  layers,
  selectedProvince,
  selectedWilker,
  showWind,
  weatherOverlay,
  onOpenKpsDetail
}: HotspotMapProps) {
  const [rainyCoords, setRainyCoords] = useState<{ lat: number; lon: number; precipitation: number; label: string }[]>([]);
  const [showUserLocation, setShowUserLocation] = useState(false);
  const userLocation = useUserLocationWatch(showUserLocation);
  const userWeatherAnchor = useThrottledWeatherAnchor(userLocation.position);
  const [mapStyle, setMapStyle] = useState<"dark" | "satellite">("dark");
  // Default nyala: pengguna ingin langsung tahu KPS mana yang terdampak
  // bekas kebakaran begitu buka peta, tanpa perlu tahu dulu ada tombol
  // togglenya (ikon api di sudut kiri atas kurang gampang ditemukan sendiri).
  // Tombolnya tetap ada untuk yang mau menyembunyikannya.
  const [showBurnedArea, setShowBurnedArea] = useState(true);
  const burnedArea = useBurnedAreaOverlay(showBurnedArea, undefined, selectedWilker);

  // Lapisan estimasi MANDIRI (Sentinel-2 dNBR) -- terpisah dari rekap resmi
  // di atas. Mati secara default: cuma relevan setelah admin menjalankan
  // analisisnya, dan pengguna biasa tidak perlu melihat angka "belum
  // terverifikasi" tanpa sadar itu estimasi.
  const [showS2Burned, setShowS2Burned] = useState(false);
  const s2Burned = useS2BurnedAreaOverlay(showS2Burned);

  // Overlay fungsi kawasan hutan (KWSHUTAN_AR_250K) diambil LIVE dari layanan
  // ArcGIS resmi Ditjen Planologi Kehutanan (lihat KawasanHutanLayer). Mati
  // secara default: cakupan nasional, menutupi peta kalau selalu nyala.
  const [showKawasan, setShowKawasan] = useState(false);

  // Polygon bekas terbakar & titik hotspot BERBAGI satu Pane/renderer (lihat
  // JSX di bawah) supaya polygonnya bisa diklik sungguhan. Canvas renderer
  // Leaflet memasang listener klik langsung di elemen <canvas>-nya sendiri
  // (bukan di peta) -- kalau dipisah ke Pane berbeda seperti sebelumnya, Pane
  // dengan z-index lebih tinggi (titik hotspot, 450) menutupi Pane di
  // bawahnya (bekas terbakar, 420) secara utuh di DOM, sehingga SEMUA klik di
  // area itu tertelan oleh canvas teratas walau tidak ada bentuk tergambar di
  // titik itu -- polygon di Pane bawah jadi TIDAK PERNAH bisa diklik sama
  // sekali (popup `onEachFeature`-nya tidak pernah terpicu), bukan cuma
  // tertutup separuh. Menyatukan renderer membuat Leaflet memilih target klik
  // lewat uji geometri tiap bentuk, bukan lewat susunan DOM.
  //
  // Supaya urutan gambar (dan karenanya prioritas klik saat tumpang tindih)
  // tetap deterministik walau data bekas terbakar datang belakangan lewat
  // fetch async, titik hotspot selalu dipaksa `bringToFront()` ulang tiap
  // kali daftarnya atau data bekas terbakar berubah.
  // Renderer canvas TUNGGAL yang dibagi polygon bekas terbakar + titik hotspot
  // (semuanya di Pane `kps-interaktif` -- lihat komentar panjang di atas soal
  // kenapa harus satu canvas). `tolerance: 12` menaikkan radius uji-klik
  // titik 7px jadi ~19px: tanpa ini di HP tap yang meleset sedikit lolos ke
  // `PolygonInfoLayer` dan yang muncul popup "Poligon di titik ini", bukan
  // popup hotspot. `tolerance` dibaca saat klik, bukan saat gambar.
  const fireCanvasRenderer = useMemo(
    () => canvas({ pane: "kps-interaktif", tolerance: 12 }),
    [],
  );
  // react-leaflet <GeoJSON> tidak mengetik prop `renderer`, tapi meneruskannya
  // apa adanya ke L.geoJSON -> L.Polygon (yang menghormatinya). Spread lewat
  // objek any supaya polygon bekas terbakar ikut canvas yang sama dengan titik
  // hotspot (WAJIB satu canvas -- lihat komentar di atas).
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fireRendererProp: any = { renderer: fireCanvasRenderer };

  const hotspotLayerGroupRef = useRef<LLayerGroup | null>(null);
  useEffect(() => {
    const group = hotspotLayerGroupRef.current;
    if (!group) {
      return;
    }
    group.eachLayer((layer) => {
      if ("bringToFront" in layer && typeof layer.bringToFront === "function") {
        layer.bringToFront();
      }
    });
  }, [hotspots, burnedArea.data]);

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
      authFetch(`/api/weather/rain-check?coords=${encodeURIComponent(coordsParam)}`)
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
      <div className="map-legend">
        <span className="map-legend-title">Legenda</span>
        <div className="map-legend-row"><span className="map-legend-dot" style={{ background: "#ff8c42" }} />MODIS</div>
        <div className="map-legend-row"><span className="map-legend-dot" style={{ background: "#facc15" }} />VIIRS</div>
        <div className="map-legend-row"><span className="map-legend-dot map-legend-dot--pulse" />FRP tinggi (&gt;30MW)</div>
        {showBurnedArea && burnedArea.data ? (
          <>
            <div className="map-legend-divider" />
            <div className="map-legend-row">
              <span className="map-legend-swatch" style={{ background: "rgba(220,38,38,0.5)", borderColor: "#dc2626" }} />
              Bekas terbakar
            </div>
            {burnedArea.data.features.some((feature) => feature.properties.is_estimated) ? (
              <div className="map-legend-row">
                <span className="map-legend-swatch map-legend-swatch--estimated" />
                Perkiraan lokasi
              </div>
            ) : null}
          </>
        ) : null}
      </div>

      <button
        type="button"
        className={`locate-btn${showUserLocation ? " locate-btn--active" : ""}${userLocation.loading ? " locate-btn--loading" : ""}`}
        onClick={() => setShowUserLocation((current) => !current)}
        title={showUserLocation ? "Sembunyikan lokasi saya" : "Tampilkan lokasi saya"}
        aria-pressed={showUserLocation}
        aria-label="Lokasi saya"
      >
        <LocateFixed size={16} />
      </button>

      <div className="burned-control">
        <div className="overlay-group">
          <button
            type="button"
            className={`burned-toggle${showBurnedArea ? " burned-toggle--active" : ""}${
              burnedArea.loading ? " burned-toggle--loading" : ""
            }${showBurnedArea && burnedArea.data ? " burned-toggle--merged" : ""}`}
            onClick={() => setShowBurnedArea((current) => !current)}
            title={
              showBurnedArea
                ? "Sembunyikan kawasan bekas terbakar"
                : "Tampilkan kawasan bekas terbakar (sumber: Kementerian Kehutanan, akurasi H/M)"
            }
            aria-pressed={showBurnedArea}
          >
            <Flame size={15} />
            <span>Bekas Terbakar</span>
          </button>

          {showBurnedArea && burnedArea.data ? (
            <div className="burned-summary-chip">
              <p className="burned-summary-chip__figure">
                <span className="burned-summary-chip__value">
                  {formatHectares(burnedArea.data.total_ha)}
                </span>
                <span className="burned-summary-chip__unit">Ha</span>
              </p>
              <p className="burned-summary-chip__scope">
                {formatHectares(burnedArea.data.kps_count)} KPS terdampak
              </p>
              <p className="burned-summary-chip__source">Sumber Kementerian Kehutanan · akurasi H/M</p>
            </div>
          ) : null}
        </div>

        <div className="overlay-group">
          <button
            type="button"
            className={`burned-toggle burned-toggle--s2${showS2Burned ? " burned-toggle--active" : ""}${
              s2Burned.loading ? " burned-toggle--loading" : ""
            }${showS2Burned && s2Burned.data ? " burned-toggle--merged" : ""}`}
            onClick={() => setShowS2Burned((current) => !current)}
            title={
              showS2Burned
                ? "Sembunyikan estimasi mandiri Sentinel-2"
                : "Tampilkan estimasi bekas terbakar hasil analisis mandiri (Sentinel-2 dNBR, belum terverifikasi)"
            }
            aria-pressed={showS2Burned}
          >
            <Flame size={15} />
            <span>Estimasi Sentinel-2</span>
          </button>

          {showS2Burned && s2Burned.data ? (
            <div className="burned-summary-chip">
              <p className="burned-summary-chip__figure">
                <span className="burned-summary-chip__value">
                  {formatHectares(s2Burned.data.meta.total_ha)}
                </span>
                <span className="burned-summary-chip__unit">Ha</span>
              </p>
              <p className="burned-summary-chip__scope">
                {formatHectares(s2Burned.data.meta.polygons)} KPS · {s2Burned.data.meta.no_hotspot_but_burned} tanpa hotspot
              </p>
              <p className="burned-summary-chip__source">
                Analisis mandiri Sentinel-2 · estimasi, belum terverifikasi
              </p>
            </div>
          ) : null}
        </div>

        <div className="overlay-group">
          <button
            type="button"
            className={`burned-toggle burned-toggle--kawasan${showKawasan ? " burned-toggle--active" : ""}${
              showKawasan ? " burned-toggle--merged" : ""
            }`}
            onClick={() => setShowKawasan((current) => !current)}
            title={
              showKawasan
                ? "Sembunyikan fungsi kawasan hutan"
                : "Tampilkan fungsi kawasan hutan (layanan ArcGIS Ditjen Planologi Kehutanan, KWSHUTAN 1:250.000)"
            }
            aria-pressed={showKawasan}
          >
            <Trees size={15} />
            <span>Fungsi Kawasan Hutan</span>
          </button>

          {showKawasan ? (
            <div className="burned-summary-chip kawasan-legend">
              <ul className="kawasan-legend__list">
                {KAWASAN_HUTAN_LEGEND.map((item) => (
                  <li key={item.label} className="kawasan-legend__row">
                    <span className="kawasan-legend__swatch" style={{ background: item.color }} />
                    {item.label}
                  </li>
                ))}
              </ul>
              <p className="burned-summary-chip__source">Sumber: SIGAP Kehutanan · KWSHUTAN 1:250K</p>
            </div>
          ) : null}
        </div>
      </div>
      {userLocation.error ? <p className="locate-error-toast">{userLocation.error}</p> : null}

      <div className="basemap-switcher" role="group" aria-label="Gaya peta">
        <button
          type="button"
          className={mapStyle === "dark" ? "basemap-switcher-btn--active" : ""}
          onClick={() => setMapStyle("dark")}
          aria-pressed={mapStyle === "dark"}
        >
          Peta
        </button>
        <button
          type="button"
          className={mapStyle === "satellite" ? "basemap-switcher-btn--active" : ""}
          onClick={() => setMapStyle("satellite")}
          aria-pressed={mapStyle === "satellite"}
        >
          Satelit
        </button>
      </div>

      <MapContainer
        center={[-2.5, 118]}
        zoom={5}
        preferCanvas
        {...SMOOTH_ZOOM_MAP_PROPS}
        zoomControl={false}
        style={{ height: "100%", width: "100%" }}
      >
        {mapStyle === "satellite" ? (
          <>
            <TileLayer
              attribution="Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              maxZoom={19}
            />
            {/* Citra satelit polos tidak ada nama tempat/jalan; layer referensi
                Esri ini ditumpuk di atasnya supaya tetap terbaca, mirip mode
                satelit Google Maps. */}
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
              maxZoom={19}
            />
          </>
        ) : (
          <>
            <TileLayer
              attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
              maxZoom={16}
            />
            {/* Base gelap Esri tanpa label; layer referensi Esri ini menaruh
                nama tempat/batas di atasnya. Menggantikan basemap CARTO
                dark_all yang kini butuh API key. */}
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
              maxZoom={16}
            />
          </>
        )}
        <ZoomControl position="bottomleft" />
        <MapViewport hotspots={hotspots} layers={layers} selectedProvince={selectedProvince} />
        <PolygonInfoLayer layers={layers} showKawasan={showKawasan} />
        <WindLayer visible={showWind ?? false} />
        <WeatherOverlay parameter={weatherOverlay ?? null} />
        {showUserLocation && userLocation.position ? (
          <>
            <UserLocationRecenter lat={userLocation.position.lat} lon={userLocation.position.lon} />
            <Circle
              center={[userLocation.position.lat, userLocation.position.lon]}
              radius={userLocation.position.accuracy}
              interactive={false}
              pathOptions={{ color: "#38bdf8", weight: 1, fillColor: "#38bdf8", fillOpacity: 0.12 }}
            />
            <Marker
              position={[userLocation.position.lat, userLocation.position.lon]}
              icon={userLocationIcon}
              zIndexOffset={1000}
            >
              <Popup>
                <div style={{ fontSize: "12px", fontFamily: "sans-serif" }}>
                  <strong style={{ color: "#38bdf8" }}>Lokasi Anda</strong>
                  <div style={{ marginTop: "4px" }}>
                    {userLocation.position.lat.toFixed(5)}, {userLocation.position.lon.toFixed(5)}
                  </div>
                  <div style={{ marginTop: "2px" }}>
                    Akurasi: <strong>±{Math.round(userLocation.position.accuracy)} m</strong>
                  </div>
                </div>
                <CoordinateActions lat={userLocation.position.lat} lon={userLocation.position.lon} />
                {userWeatherAnchor ? (
                  <HotspotWeatherPopup lat={userWeatherAnchor.lat} lon={userWeatherAnchor.lon} />
                ) : null}
              </Popup>
            </Marker>
          </>
        ) : null}
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
        {showKawasan ? <KawasanHutanLayer opacity={0.9} /> : null}
        <Pane name="batas-kps" style={{ zIndex: 400 }}>
          {layers
            .filter((layer) => layer.active)
            .map((layer) => (
              <GeoJSON
                // Saat overlay ArcGIS kawasan hutan menyala, isian poligon KPS
                // dimatikan (cuma garis batas) supaya warna kawasan hutan di
                // bawahnya tidak tertutup tint hijau. Ganti key memaksa restyle.
                key={`${layer.id}-${showKawasan ? "line" : "fill"}`}
                data={layer.geojson as never}
                interactive={false}
                style={{
                  color: layer.color,
                  weight: 4,
                  opacity: 1,
                  fillColor: layer.color,
                  fillOpacity: showKawasan ? 0 : 0.18,
                  dashArray: "6 5",
                  lineCap: "round",
                  lineJoin: "round"
                }}
              />
            ))}
        </Pane>
        {/* Bekas terbakar & titik hotspot BERBAGI satu Pane (lihat catatan
            `hotspotLayerGroupRef` di atas) supaya polygon bekas terbakar bisa
            sungguhan diklik -- Pane terpisah membuat canvas dengan z-index
            lebih tinggi menelan semua klik di Pane bawahnya walau tidak ada
            bentuk tergambar di titik itu. Batas KPS tetap di Pane sendiri
            (400, di bawah) karena non-interactive, urutannya tidak
            berpengaruh ke klik. Urutan gambar di sini (polygon dulu, titik
            belakangan + dipaksa bringToFront tiap render) yang menjaga titik
            hotspot tetap terlihat di atas arsiran merah -- sebelumnya dijamin
            lewat z-index Pane terpisah (390 sempat dicoba, ketutup isian
            hijau KPS, makanya sekarang di atas batas KPS juga). */}
        <Pane name="kps-interaktif" style={{ zIndex: 420 }}>
          {showS2Burned && s2Burned.data ? (
            <GeoJSON
              key={`s2-burned-${s2Burned.data.meta.year}-${s2Burned.data.meta.month}-${s2Burned.data.meta.polygons}`}
              data={s2Burned.data as never}
              {...fireRendererProp}
              style={{
                color: "#f59e0b",
                weight: 1.5,
                dashArray: "5 3",
                fillColor: "#f59e0b",
                fillOpacity: 0.35
              }}
              onEachFeature={(feature, layer) => {
                const props = feature.properties as S2BurnedAreaFeature["properties"];
                const hotspotNote = props.has_hotspot
                  ? `<div>Hotspot bulan ini: <strong>${props.hotspot_count_month}</strong></div>`
                  : `<div style="color:#fca5a5">Tidak ada hotspot terdeteksi — terbakar tetap terekam citra.</div>`;
                const kawasanNote = props.kawasan_dominan
                  ? `<div>Fungsi kawasan (dominan): <strong>${props.kawasan_dominan}</strong></div>`
                  : "";
                layer.bindPopup(
                  `<div style="font-size:12px;font-family:sans-serif;min-width:200px">
                     <strong style="color:#b45309">Estimasi Bekas Terbakar</strong>
                     <div style="margin-top:6px;font-weight:600">${props.lembaga ?? "-"}</div>
                     <div style="color:#9ca3af;font-size:11px">${props.nama_kab ?? "-"} · ${props.nama_prov ?? "-"}</div>
                     <div style="margin-top:6px">Luas estimasi: <strong>${formatNumber(
                       Math.round(props.area_ha * 10) / 10
                     )} Ha</strong></div>
                     ${hotspotNote}
                     ${kawasanNote}
                     <div style="margin-top:6px;color:#fbbf24;font-size:11px">
                       Analisis mandiri Sentinel-2 dNBR — estimasi, belum terverifikasi Kementerian Kehutanan.
                     </div>
                   </div>`
                );
              }}
            />
          ) : null}
          {showBurnedArea && burnedArea.data ? (
            <GeoJSON
              key={`burned-overlay-${burnedArea.data.kps_count}`}
              data={burnedArea.data as never}
              {...fireRendererProp}
              style={{
                color: "#dc2626",
                weight: 1.5,
                fillColor: "#dc2626",
                fillOpacity: 0.42
              }}
              pointToLayer={(_feature, latlng) =>
                buildLeafletCircleMarker(latlng, {
                  radius: 8,
                  color: "#dc2626",
                  weight: 2,
                  dashArray: "4 3",
                  fillColor: "#dc2626",
                  fillOpacity: 0.22,
                  renderer: fireCanvasRenderer
                })
              }
              onEachFeature={(feature, layer) => {
                const props = feature.properties as BurnedAreaOverlayFeature["properties"];
                const periodLabel = props.latest_period
                  ? `${MONTH_LABELS[Number(props.latest_period.slice(5, 7)) - 1]} ${props.latest_period.slice(0, 4)}`
                  : "-";
                const estimatedNote = props.is_estimated
                  ? `<div style="margin-top:6px;color:#fca5a5;font-size:11px">Perkiraan lokasi — luas di bawah resolusi piksel citra.</div>`
                  : "";
                layer.bindPopup(
                  `<div style="font-size:12px;font-family:sans-serif;min-width:190px">
                     <strong style="color:#dc2626">Bekas Kebakaran</strong>
                     <div style="margin-top:6px;font-weight:600">${props.lembaga ?? "-"}</div>
                     <div style="color:#9ca3af;font-size:11px">${props.skema ?? "-"} · ${props.nama_prov ?? "-"}</div>
                     <div style="margin-top:6px">Luas terbakar: <strong>${formatNumber(
                       Math.round(props.burned_area_ha * 10) / 10
                     )} Ha</strong></div>
                     <div>Terdeteksi: <strong>${props.burned_months} bulan</strong> · terakhir ${periodLabel}</div>
                     ${estimatedNote}
                   </div>`
                );
              }}
            />
          ) : null}
          <LayerGroup ref={hotspotLayerGroupRef}>
            {hotspots.map((hotspot) =>
              (hotspot.frp ?? 0) > HIGH_FRP_THRESHOLD ? (
                <Marker
                  key={hotspot.id}
                  position={[hotspot.latitude, hotspot.longitude]}
                  icon={getHighIntensityIcon(sourceColor(hotspot.source))}
                >
                  <Popup pane="popupPane">
                    <HotspotPopupContent hotspot={hotspot} onOpenKpsDetail={onOpenKpsDetail} />
                  </Popup>
                </Marker>
              ) : (
                <CircleMarker
                  key={hotspot.id}
                  center={[hotspot.latitude, hotspot.longitude]}
                  radius={7}
                  renderer={fireCanvasRenderer}
                  pathOptions={{
                    color: "#1b120d",
                    weight: 2,
                    fillColor: sourceColor(hotspot.source),
                    fillOpacity: 0.98
                  }}
                >
                  <Popup pane="popupPane">
                    <HotspotPopupContent hotspot={hotspot} onOpenKpsDetail={onOpenKpsDetail} />
                  </Popup>
                </CircleMarker>
              )
            )}
          </LayerGroup>
        </Pane>
      </MapContainer>
    </div>
  );
}
