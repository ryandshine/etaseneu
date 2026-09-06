import React, { useState, useEffect, useMemo } from "react";
import {
  Flame,
  AlertOctagon,
  AlertTriangle,
  Eye,
  Download,
  Search,
  RefreshCw,
  Compass,
  MapPin,
  ShieldAlert,
  Layers,
  ArrowRight,
  Crosshair,
  Copy,
  Check,
  X,
  ChevronLeft
} from "lucide-react";
import { CircleMarker, GeoJSON, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { authFetch, downloadWithAuth } from "../lib/api";

interface SummaryData {
  total_kps_threatened: number;
  total_external_hotspots: number;
  non_kps_hotspots?: number;
  neighbor_kps_hotspots?: number;
  bahaya_count: number;
  waspada_count: number;
  pantau_count: number;
  time_window_hours: number;
  max_distance_km: number;
}

interface ThreatItem {
  polygon_id: number;
  lembaga: string;
  nama_kps: string;
  nama_desa: string | null;
  nama_kec: string | null;
  nama_kab: string | null;
  nama_prov: string | null;
  skema: string | null;
  no_sk: string | null;
  wilker_bps: string | null;
  luas_ha: number | null;
  min_distance_m: number;
  min_distance_km: number;
  status_level: "bahaya" | "waspada" | "pantau";
  status_label: string;
  external_hotspots_count: number;
  non_kps_hotspots_count?: number;
  neighbor_kps_hotspots_count?: number;
  threat_origin?: "non_kps" | "neighbor_kps";
  threat_origin_label?: string;
  max_frp: number;
  avg_frp: number;
  bearing_deg: number | null;
  bearing_compass: string;
  rekomendasi: string;
  nearest_hotspot: {
    coordinates: [number, number] | null;
    satellite: string | null;
    confidence: string | null;
    detected_at: string | null;
    layer_key?: string | null;
    agency_name?: string | null;
  };
  nearest_boundary_point: [number, number] | null;
}

interface ThreatDetailHotspot {
  id: number;
  latitude: number;
  longitude: number;
  satellite: string | null;
  confidence: string | null;
  brightness: number | null;
  frp: number;
  detected_at: string | null;
  is_inside?: boolean;
  distance_m: number;
  distance_km: number;
  status_level: "bahaya" | "waspada" | "pantau" | "internal";
  status_label: string;
  threat_origin?: "internal" | "non_kps" | "neighbor_kps";
  threat_origin_label?: string;
  bearing_deg: number | null;
  bearing_compass: string;
  closest_kps_point: [number, number] | null;
}

interface ThreatNeighbor {
  id: number;
  lembaga: string;
  nama_desa: string | null;
  nama_kec: string | null;
  nama_kab: string | null;
  skema: string | null;
  luas_ha: number | null;
  distance_m: number;
  distance_km: number;
  hotspot_count: number;
  geometry: any;
}

interface ThreatDetail {
  polygon_id: number;
  lembaga: string;
  nama_kps: string;
  nama_desa: string | null;
  nama_kec: string | null;
  nama_kab: string | null;
  nama_prov: string | null;
  skema: string | null;
  no_sk: string | null;
  wilker_bps: string | null;
  luas_ha: number | null;
  geometry: any;
  centroid: [number, number] | null;
  status_level: "bahaya" | "waspada" | "pantau" | "internal";
  status_label: string;
  min_distance_m: number;
  min_distance_km: number;
  total_external_hotspots: number;
  total_internal_hotspots?: number;
  hotspots: ThreatDetailHotspot[];
  neighbors?: ThreatNeighbor[];
  closest_vector: {
    hotspot_coords: [number, number];
    kps_boundary_coords: [number, number];
    distance_m: number;
    bearing_compass: string;
  } | null;
  time_window_hours: number;
  max_distance_km: number;
}

const BASEMAP_CONFIGS = {
  hybrid: {
    key: "hybrid",
    name: "Satelit + Label",
    url: "https://mt{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    subdomains: ["0", "1", "2", "3"] as readonly string[],
    maxZoom: 20,
  },
  dark: {
    key: "dark",
    name: "Mode Gelap",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    subdomains: ["a", "b", "c"] as readonly string[],
    maxZoom: 16,
  },
  street: {
    key: "street",
    name: "Peta Jalan",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    subdomains: ["a", "b", "c"] as readonly string[],
    maxZoom: 19,
  },
} as const;

type BasemapKey = keyof typeof BASEMAP_CONFIGS;

/**
 * Pengontrol Viewport Peta: Otomatis Zoom & Fit ke Poligon KPS + Hotspot
 * Mendukung auto-panning ke kiri saat Sliding Right Panel dibuka
 */
function MapViewportController({
  polygonId,
  geometry,
  hotspots,
  focusTrigger,
  isDrawerOpen,
}: {
  polygonId: number | null;
  geometry: any;
  hotspots: ThreatDetailHotspot[];
  focusTrigger: number;
  isDrawerOpen: boolean;
}) {
  const map = useMap();

  useEffect(() => {
    if (!geometry) return;
    try {
      if (typeof map?.invalidateSize === "function") {
        map.invalidateSize({ animate: false });
      }
      const feat = { type: "Feature", properties: {}, geometry };
      const layer = L.geoJSON(feat as any);
      const bounds = layer.getBounds();
      if (!bounds || !bounds.isValid()) return;

      for (const h of hotspots) {
        bounds.extend([h.latitude, h.longitude]);
      }

      if (bounds.isValid()) {
        const containerWidth = typeof map?.getSize === "function" ? map.getSize().x : (typeof window !== "undefined" ? window.innerWidth : 1200);
        // Lebar sliding drawer panel adalah ~390px.
        // Dengan paddingBottomRight x = drawerOffset + 45, Leaflet secara otomatis
        // melakukan panning kanvas ke kiri sebesar drawerOffset / 2,
        // sehingga seluruh poligon KPS dan titik api berada tepat di tengah sisa area kanvas yang bebas.
        const drawerOffset = isDrawerOpen ? Math.min(410, Math.floor(containerWidth * 0.52)) : 0;

        const options: L.FitBoundsOptions = {
          paddingTopLeft: [45, 45],
          paddingBottomRight: [drawerOffset + 45, 45],
          maxZoom: 15,
          duration: 0.6,
        };

        if (typeof map?.flyToBounds === "function") {
          map.flyToBounds(bounds, options);
        } else if (typeof map?.fitBounds === "function") {
          map.fitBounds(bounds, options);
        }
      }
    } catch (err) {
      console.warn("Gagal fly ke poligon KPS:", err);
    }
  }, [polygonId, geometry, hotspots, focusTrigger, isDrawerOpen, map]);

  return null;
}

export function SiagaRambatanApiView({ onOpenKpsDetail }: { onOpenKpsDetail?: (kpsName: string) => void }) {
  const [timeWindow, setTimeWindow] = useState<number>(48);
  const [maxDistanceKm, setMaxDistanceKm] = useState<number>(5.0);
  const [selectedLevel, setSelectedLevel] = useState<"bahaya" | "waspada" | "pantau" | "all">("all");
  const [selectedProvince, setSelectedProvince] = useState<string>("");
  const [selectedRegency, setSelectedRegency] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState<string>("");

  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [threats, setThreats] = useState<ThreatItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [downloading, setDownloading] = useState<boolean>(false);

  const [selectedKpsId, setSelectedKpsId] = useState<number | null>(null);
  const [threatDetail, setThreatDetail] = useState<ThreatDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<boolean>(false);

  const [basemap, setBasemap] = useState<BasemapKey>("hybrid");
  const [focusTrigger, setFocusTrigger] = useState<number>(0);
  const [copiedCoords, setCopiedCoords] = useState<boolean>(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState<boolean>(true);

  // 1. Fetch summary & threats
  const fetchData = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        time_window_hours: String(timeWindow),
        max_distance_km: String(maxDistanceKm)
      });
      if (selectedProvince) params.append("province", selectedProvince);
      if (selectedRegency) params.append("regency", selectedRegency);

      const sumRes = await authFetch(`/api/fire-spread/summary?${params.toString()}`);
      if (sumRes.ok) {
        setSummary(await sumRes.json());
      }

      if (selectedLevel !== "all") params.append("level", selectedLevel);
      if (searchTerm.trim()) params.append("search", searchTerm.trim());
      params.append("limit", "150");

      const listRes = await authFetch(`/api/fire-spread/threats?${params.toString()}`);
      if (listRes.ok) {
        const listData = await listRes.json();
        const items: ThreatItem[] = listData.items || [];
        setThreats(items);
        if (items.length > 0 && !selectedKpsId) {
          setSelectedKpsId(items[0].polygon_id);
          setIsDrawerOpen(true);
        }
      }
    } catch (err) {
      console.error("Gagal memuat data siaga rambatan api:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [timeWindow, maxDistanceKm, selectedLevel, selectedProvince, selectedRegency]);

  // 2. Fetch Detail satu KPS jika dipilih
  useEffect(() => {
    if (!selectedKpsId) {
      setThreatDetail(null);
      return;
    }
    let cancelled = false;
    const fetchDetail = async () => {
      setLoadingDetail(true);
      try {
        const params = new URLSearchParams({
          polygon_id: String(selectedKpsId),
          time_window_hours: String(timeWindow),
          max_distance_km: String(maxDistanceKm)
        });
        const res = await authFetch(`/api/fire-spread/detail?${params.toString()}`);
        if (res.ok && !cancelled) {
          setThreatDetail(await res.json());
        }
      } catch (err) {
        console.error("Gagal memuat detail KPS terancam:", err);
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    };
    fetchDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedKpsId, timeWindow, maxDistanceKm]);

  // Handle Export Excel
  const handleExportExcel = async () => {
    setDownloading(true);
    try {
      const params = new URLSearchParams({
        time_window_hours: String(timeWindow),
        max_distance_km: String(maxDistanceKm)
      });
      if (selectedLevel !== "all") params.append("level", selectedLevel);
      if (selectedProvince) params.append("province", selectedProvince);
      if (selectedRegency) params.append("regency", selectedRegency);
      if (searchTerm.trim()) params.append("search", searchTerm.trim());

      await downloadWithAuth(
        `/api/fire-spread/export.xlsx?${params.toString()}`,
        `Laporan_Siaga_Rambatan_Api_${timeWindow}Jam.xlsx`
      );
    } catch (err) {
      console.error("Gagal mengekspor laporan siaga rambatan api:", err);
    } finally {
      setDownloading(false);
    }
  };

  // Opsi dropdown provinsi & kabupaten
  const provinceOptions = useMemo(() => {
    const s = new Set<string>();
    for (const t of threats) {
      if (t.nama_prov) s.add(t.nama_prov);
    }
    return Array.from(s).sort();
  }, [threats]);

  const regencyOptions = useMemo(() => {
    const s = new Set<string>();
    for (const t of threats) {
      if (!selectedProvince || t.nama_prov === selectedProvince) {
        if (t.nama_kab) s.add(t.nama_kab);
      }
    }
    return Array.from(s).sort();
  }, [threats, selectedProvince]);

  // Centroid koordinat peta
  const mapCenter: [number, number] = useMemo(() => {
    if (threatDetail?.centroid) {
      return [threatDetail.centroid[1], threatDetail.centroid[0]];
    }
    if (threatDetail?.hotspots && threatDetail.hotspots.length > 0) {
      return [threatDetail.hotspots[0].latitude, threatDetail.hotspots[0].longitude];
    }
    return [-2.5, 118.0]; // Pusat Indonesia
  }, [threatDetail]);

  const activeBasemap = BASEMAP_CONFIGS[basemap];

  return (
    <div className="fs-shell">
      {/* Header Halaman */}
      <header className="fs-header">
        <div>
          <div className="fs-title-box">
            <span className="fs-title-icon">
              <ShieldAlert size={24} />
            </span>
            <h1 className="fs-title">
              Siaga Rambatan Api (Deteksi Ancaman Luar KPS)
            </h1>
          </div>
          <p className="fs-subtitle">
            Peringatan dini deteksi titik api (hotspot) di luar batas kawasan KPS (radius buffer 1–5 km) yang berpotensi merambat masuk ke dalam wilayah kelola masyarakat.
          </p>
        </div>

        <div className="fs-header-actions">
          <button
            type="button"
            onClick={fetchData}
            disabled={loading}
            className="fs-btn-refresh"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            Segarkan
          </button>

          <button
            type="button"
            onClick={handleExportExcel}
            disabled={downloading || threats.length === 0}
            className="fs-btn-export"
          >
            <Download size={15} />
            {downloading ? "Mengunduh..." : "Ekspor Excel (.xlsx)"}
          </button>
        </div>
      </header>

      {/* KPI Summary Strip */}
      <div className="fs-kpi-grid">
        {/* Bahaya Kritis */}
        <div
          onClick={() => setSelectedLevel("bahaya")}
          className={`fs-kpi-card ${selectedLevel === "bahaya" ? "fs-kpi-card--active-bahaya" : ""}`}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#f87171" }}>
              Bahaya Kritis (&lt; 1 km)
            </span>
            <span className="fs-kpi-dot fs-kpi-dot--bahaya" />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">{summary?.bahaya_count ?? 0}</span>
            <span className="fs-kpi-card-unit" style={{ color: "#fca5a5" }}>KPS Terancam</span>
          </div>
        </div>

        {/* Waspada */}
        <div
          onClick={() => setSelectedLevel("waspada")}
          className={`fs-kpi-card ${selectedLevel === "waspada" ? "fs-kpi-card--active-waspada" : ""}`}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#fb923c" }}>
              Waspada (1–3 km)
            </span>
            <span className="fs-kpi-dot fs-kpi-dot--waspada" />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">{summary?.waspada_count ?? 0}</span>
            <span className="fs-kpi-card-unit" style={{ color: "#fed7aa" }}>KPS Terancam</span>
          </div>
        </div>

        {/* Pantau */}
        <div
          onClick={() => setSelectedLevel("pantau")}
          className={`fs-kpi-card ${selectedLevel === "pantau" ? "fs-kpi-card--active-pantau" : ""}`}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#fde047" }}>
              Pantau (3–5 km)
            </span>
            <span className="fs-kpi-dot fs-kpi-dot--pantau" />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">{summary?.pantau_count ?? 0}</span>
            <span className="fs-kpi-card-unit" style={{ color: "#fef08a" }}>KPS Terancam</span>
          </div>
        </div>

        {/* Total Hotspot Luar */}
        <div
          onClick={() => setSelectedLevel("all")}
          className={`fs-kpi-card ${selectedLevel === "all" ? "fs-kpi-card--active-all" : ""}`}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#93c5fd" }}>
              Total Hotspot Luar (5 km)
            </span>
            <Flame size={15} color="#3b82f6" />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">
              {summary?.total_external_hotspots?.toLocaleString() ?? 0}
            </span>
            <span className="fs-kpi-card-unit" style={{ color: "#9ca3af" }}>
              Titik Api ({summary?.total_kps_threatened ?? 0} KPS)
            </span>
          </div>
          <div style={{ fontSize: "0.68rem", color: "#94a3b8", marginTop: "0.2rem" }}>
            Luar KPS: <strong style={{ color: "#f87171" }}>{summary?.non_kps_hotspots ?? 0}</strong> · Tetangga: <strong style={{ color: "#818cf8" }}>{summary?.neighbor_kps_hotspots ?? 0}</strong>
          </div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="fs-toolbar">
        {/* Rentang Waktu */}
        <div className="fs-filter-group">
          <span className="fs-filter-label">Waktu:</span>
          <select
            value={timeWindow}
            onChange={(e) => setTimeWindow(Number(e.target.value))}
            className="fs-filter-select"
          >
            <option value={24}>24 Jam Terakhir</option>
            <option value={48}>48 Jam Terakhir</option>
            <option value={72}>3 Hari Terakhir</option>
            <option value={168}>7 Hari Terakhir</option>
          </select>
        </div>

        {/* Radius Maksimum */}
        <div className="fs-filter-group">
          <span className="fs-filter-label">Radius:</span>
          <select
            value={maxDistanceKm}
            onChange={(e) => setMaxDistanceKm(Number(e.target.value))}
            className="fs-filter-select"
          >
            <option value={1.0}>1 km (Zona Kritis)</option>
            <option value={3.0}>3 km (Zona Waspada)</option>
            <option value={5.0}>5 km (Zona Pantau Lengkap)</option>
          </select>
        </div>

        {/* Level Status Filter */}
        <div className="fs-filter-group">
          <span className="fs-filter-label">Status:</span>
          <select
            value={selectedLevel}
            onChange={(e) => setSelectedLevel(e.target.value as any)}
            className="fs-filter-select"
          >
            <option value="all">Semua Status</option>
            <option value="bahaya">Bahaya Kritis (&lt; 1 km)</option>
            <option value="waspada">Waspada (1–3 km)</option>
            <option value="pantau">Pantau (3–5 km)</option>
          </select>
        </div>

        {/* Dropdown Provinsi */}
        {provinceOptions.length > 0 && (
          <div className="fs-filter-group">
            <span className="fs-filter-label">Provinsi:</span>
            <select
              value={selectedProvince}
              onChange={(e) => {
                setSelectedProvince(e.target.value);
                setSelectedRegency("");
              }}
              className="fs-filter-select"
              style={{ maxWidth: "160px" }}
            >
              <option value="">Semua Provinsi</option>
              {provinceOptions.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Dropdown Kabupaten */}
        {regencyOptions.length > 0 && (
          <div className="fs-filter-group">
            <span className="fs-filter-label">Kabupaten:</span>
            <select
              value={selectedRegency}
              onChange={(e) => setSelectedRegency(e.target.value)}
              className="fs-filter-select"
              style={{ maxWidth: "160px" }}
            >
              <option value="">Semua Kabupaten</option>
              {regencyOptions.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Search Input */}
        <div className="fs-search-wrap">
          <Search size={14} className="fs-search-icon" />
          <input
            type="text"
            placeholder="Cari KPS / Desa / Kabupaten..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fetchData()}
            className="fs-search-input"
          />
          {searchTerm && (
            <button
              type="button"
              onClick={() => {
                setSearchTerm("");
                fetchData();
              }}
              style={{ background: "none", border: "none", color: "#9ca3af", cursor: "pointer", padding: "0 0.4rem" }}
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Main Layout: Left Column (Threat List) + Right Column (Sticky Interactive Map) */}
      <div className="fs-main-grid">
        {/* Left Column: Daftar KPS Terancam */}
        <div className="fs-list-column">
          <div className="fs-list-header">
            <div>
              <span style={{ fontSize: "0.88rem", fontWeight: "700", color: "#ffffff" }}>
                Prioritas KPS Terancam
              </span>
              <span style={{ marginLeft: "0.5rem", fontSize: "0.76rem", color: "#9ca3af" }}>
                ({threats.length} KPS terdekat dari titik api)
              </span>
            </div>
          </div>

          <div className="fs-list-body">
            {loading ? (
              <div style={{ padding: "3rem 1rem", textAlign: "center", color: "#9ca3af", fontSize: "0.88rem" }}>
                <RefreshCw size={24} className="animate-spin" style={{ margin: "0 auto 0.75rem" }} />
                Menganalisis jarak perimeter seluruh KPS ke titik api...
              </div>
            ) : threats.length === 0 ? (
              <div style={{ padding: "3rem 1rem", textAlign: "center", color: "#9ca3af", fontSize: "0.88rem" }}>
                <ShieldAlert size={32} style={{ margin: "0 auto 0.75rem", color: "#10b981" }} />
                Tidak ada titik api terdeteksi di perimeter luar poligon pada kriteria filter ini.
              </div>
            ) : (
              threats.map((item, idx) => {
                const isSelected = selectedKpsId === item.polygon_id;
                const isBahaya = item.status_level === "bahaya";
                const isWaspada = item.status_level === "waspada";
                const badgeBg = isBahaya ? "rgba(239, 68, 68, 0.18)" : isWaspada ? "rgba(249, 115, 22, 0.18)" : "rgba(234, 179, 8, 0.18)";
                const badgeColor = isBahaya ? "#f87171" : isWaspada ? "#fb923c" : "#fde047";
                const badgeBorder = isBahaya ? "#ef4444" : isWaspada ? "#f97316" : "#eab308";

                return (
                  <div
                    key={item.polygon_id}
                    onClick={() => {
                      setSelectedKpsId(item.polygon_id);
                      setIsDrawerOpen(true);
                    }}
                    className={`fs-card ${isSelected ? "fs-card--selected" : ""}`}
                  >
                    <div className="fs-card-head">
                      <div className="fs-card-info">
                        <div className="fs-card-badges">
                          <span style={{ fontSize: "0.72rem", fontWeight: "700", padding: "0.15rem 0.5rem", borderRadius: "4px", backgroundColor: badgeBg, color: badgeColor, border: `1px solid ${badgeBorder}` }}>
                            {item.status_label}
                          </span>
                          <span style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
                            #{idx + 1}
                          </span>
                          {item.skema && (
                            <span style={{ fontSize: "0.72rem", padding: "0.1rem 0.4rem", borderRadius: "4px", backgroundColor: "rgba(255,255,255,0.06)", color: "#d1d5db" }}>
                              {item.skema}
                            </span>
                          )}
                        </div>
                        <div className="fs-card-title">
                          {item.lembaga}
                        </div>
                        <div className="fs-card-location">
                          {[item.nama_desa, item.nama_kab, item.nama_prov].filter(Boolean).join(", ")}
                        </div>
                      </div>

                      <div className="fs-card-dist">
                        <div className="fs-card-dist-value" style={{ color: badgeColor }}>
                          {item.min_distance_m < 1000 ? `${item.min_distance_m} m` : `${item.min_distance_km} km`}
                        </div>
                        <div className="fs-card-dist-unit">
                          dari batas luar
                        </div>
                      </div>
                    </div>

                    {/* Detail Ancaman Bar */}
                    <div className="fs-card-metrics">
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                        <Compass size={13} color="#60a5fa" />
                        Arah: <strong>{item.bearing_compass}</strong>
                      </span>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
                        <Flame size={13} color="#f87171" />
                        <strong>{item.external_hotspots_count} titik api</strong> di luar
                      </span>
                      {item.threat_origin_label && (
                        <span
                          style={{
                            fontSize: "0.72rem",
                            padding: "0.1rem 0.4rem",
                            borderRadius: "4px",
                            backgroundColor: item.threat_origin === "non_kps" ? "rgba(239, 68, 68, 0.15)" : "rgba(99, 102, 241, 0.15)",
                            color: item.threat_origin === "non_kps" ? "#fca5a5" : "#c7d2fe",
                            border: `1px solid ${item.threat_origin === "non_kps" ? "rgba(239, 68, 68, 0.3)" : "rgba(99, 102, 241, 0.3)"}`
                          }}
                        >
                          Asal: {item.threat_origin_label}
                        </span>
                      )}
                      {item.max_frp > 0 && (
                        <span style={{ color: "#9ca3af" }}>
                          Max FRP: <strong>{item.max_frp} MW</strong>
                        </span>
                      )}
                      {onOpenKpsDetail && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenKpsDetail(item.lembaga);
                          }}
                          style={{
                            marginLeft: "auto",
                            background: "none",
                            border: "none",
                            color: "#60a5fa",
                            fontSize: "0.72rem",
                            cursor: "pointer",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.2rem",
                            padding: 0
                          }}
                        >
                          Buku Besar <ArrowRight size={12} />
                        </button>
                      )}
                    </div>

                    {/* Teks Rekomendasi Taktis */}
                    <div
                      className="fs-card-rekom"
                      style={{
                        color: isBahaya ? "#fca5a5" : "#d1d5db",
                        backgroundColor: isBahaya ? "rgba(239, 68, 68, 0.08)" : "rgba(0,0,0,0.2)"
                      }}
                    >
                      {item.rekomendasi}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Sticky Interactive Map */}
        <div className="fs-map-column">
          <div className="fs-map-header">
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", minWidth: 0 }}>
              <Layers size={16} color="#38bdf8" />
              <span style={{ fontSize: "0.88rem", fontWeight: "700", color: "#ffffff", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {threatDetail ? threatDetail.lembaga : "Peta Perimeter Ancaman KPS"}
              </span>
            </div>

            {/* Pilihan Basemap */}
            <div className="fs-basemap-group">
              <button
                type="button"
                className={`fs-basemap-btn ${basemap === "hybrid" ? "fs-basemap-btn--active" : ""}`}
                onClick={() => setBasemap("hybrid")}
              >
                Satelit
              </button>
              <button
                type="button"
                className={`fs-basemap-btn ${basemap === "dark" ? "fs-basemap-btn--active" : ""}`}
                onClick={() => setBasemap("dark")}
              >
                Gelap
              </button>
              <button
                type="button"
                className={`fs-basemap-btn ${basemap === "street" ? "fs-basemap-btn--active" : ""}`}
                onClick={() => setBasemap("street")}
              >
                Jalan
              </button>
            </div>
          </div>

          <div className="fs-map-stage">
            {loadingDetail && (
              <div className="fs-map-loading-overlay">
                <RefreshCw size={18} className="animate-spin" color="#38bdf8" />
                <span>Memuat batas poligon KPS &amp; sebaran hotspot...</span>
              </div>
            )}

            {/* Sliding Right Drawer Panel */}
            <aside
              className={`fs-drawer ${isDrawerOpen && threatDetail ? "fs-drawer--open" : ""}`}
              aria-label="Panel Detail KPS Terancam"
            >
              {threatDetail && (
                <div className="fs-drawer-content">
                  {/* Drawer Header */}
                  <div className="fs-drawer-header">
                    <div className="fs-drawer-header-top">
                      <div className="fs-drawer-badges">
                        <span
                          className="fs-drawer-status-badge"
                          style={{
                            backgroundColor:
                              threatDetail.status_level === "bahaya"
                                ? "rgba(239, 68, 68, 0.2)"
                                : threatDetail.status_level === "waspada"
                                ? "rgba(249, 115, 22, 0.2)"
                                : "rgba(234, 179, 8, 0.2)",
                            color:
                              threatDetail.status_level === "bahaya"
                                ? "#f87171"
                                : threatDetail.status_level === "waspada"
                                ? "#fb923c"
                                : "#fde047",
                            borderColor:
                              threatDetail.status_level === "bahaya"
                                ? "#ef4444"
                                : threatDetail.status_level === "waspada"
                                ? "#f97316"
                                : "#eab308",
                          }}
                        >
                          {threatDetail.status_label}
                        </span>
                        {threatDetail.skema && (
                          <span className="fs-drawer-skema-badge">{threatDetail.skema}</span>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => setIsDrawerOpen(false)}
                        className="fs-drawer-close-btn"
                        title="Tutup Panel Laci"
                        aria-label="Tutup panel"
                      >
                        <X size={18} />
                      </button>
                    </div>

                    <h3 className="fs-drawer-title">{threatDetail.lembaga}</h3>
                    <p className="fs-drawer-loc">
                      <MapPin size={13} style={{ flexShrink: 0, marginTop: "2px" }} />
                      <span>
                        {[threatDetail.nama_desa, threatDetail.nama_kab, threatDetail.nama_prov]
                          .filter(Boolean)
                          .join(", ")}
                      </span>
                    </p>
                  </div>

                  {/* Drawer Scrollable Body */}
                  <div className="fs-drawer-body">
                    {/* Hero Metric: Jarak ke Batas Luar */}
                    <div className="fs-drawer-hero-metric">
                      <div className="fs-drawer-hero-label">Jarak Terdekat dari Batas Luar</div>
                      <div
                        className="fs-drawer-hero-val"
                        style={{
                          color:
                            threatDetail.status_level === "bahaya"
                              ? "#f87171"
                              : threatDetail.status_level === "waspada"
                              ? "#fb923c"
                              : "#fde047",
                        }}
                      >
                        {threatDetail.min_distance_m < 1000
                          ? `${threatDetail.min_distance_m} m`
                          : `${threatDetail.min_distance_km} km`}
                      </div>
                      <div className="fs-drawer-hero-sub">
                        <Compass size={13} color="#38bdf8" />
                        <span>
                          Arah rambatan: <strong>{threatDetail.closest_vector?.bearing_compass || "-"}</strong>
                        </span>
                      </div>
                    </div>

                    {/* Alert: Hotspot di DALAM Kawasan jika ada */}
                    {(threatDetail.total_internal_hotspots ?? 0) > 0 && (
                      <div className="fs-drawer-alert-internal">
                        <div className="fs-drawer-alert-header">
                          <AlertOctagon size={16} color="#f43f5e" />
                          <span style={{ fontWeight: 700, color: "#fca5a5", fontSize: "0.82rem" }}>
                            🚨 {threatDetail.total_internal_hotspots} hotspot di DALAM kawasan
                          </span>
                        </div>
                        <p style={{ margin: "0.25rem 0 0", fontSize: "0.74rem", color: "#fecdd3", lineHeight: 1.35 }}>
                          Titik api aktif terdeteksi menembus masuk ke dalam poligon batas kelola masyarakat KPS. Prioritaskan aksi pemadaman darurat segera!
                        </p>
                      </div>
                    )}

                    {/* Grid Metrik Utama (2 Kolom) */}
                    <div className="fs-drawer-metrics-grid">
                      {/* Luas Kawasan */}
                      <div className="fs-drawer-metric-item">
                        <span className="fs-drawer-metric-label">Luas Kawasan</span>
                        <span className="fs-drawer-metric-val">
                          {threatDetail.luas_ha ? `${threatDetail.luas_ha.toLocaleString()} ha` : "-"}
                        </span>
                        <span className="fs-drawer-metric-sub">wilayah izin kelola</span>
                      </div>

                      {/* Titik Api Luar */}
                      <div className="fs-drawer-metric-item">
                        <span className="fs-drawer-metric-label">Hotspot Luar</span>
                        <span className="fs-drawer-metric-val" style={{ color: "#fb923c" }}>
                          🔥 {threatDetail.total_external_hotspots} titik
                        </span>
                        <span className="fs-drawer-metric-sub">radius {threatDetail.max_distance_km} km</span>
                      </div>

                      {/* KPS Sekitar */}
                      <div className="fs-drawer-metric-item">
                        <span className="fs-drawer-metric-label">KPS Sekitar</span>
                        <span className="fs-drawer-metric-val" style={{ color: "#a5b4fc" }}>
                          🏘️ {threatDetail.neighbors?.length ?? 0} KPS sekitar
                        </span>
                        <span className="fs-drawer-metric-sub">zona perbatasan</span>
                      </div>

                      {/* Max FRP */}
                      <div className="fs-drawer-metric-item">
                        <span className="fs-drawer-metric-label">Intensitas (Max FRP)</span>
                        <span className="fs-drawer-metric-val" style={{ color: "#f87171" }}>
                          {threatDetail.hotspots.length > 0
                            ? `${Math.max(...threatDetail.hotspots.map((h) => h.frp || 0)).toFixed(1)} MW`
                            : "-"}
                        </span>
                        <span className="fs-drawer-metric-sub">Fire Radiative Power</span>
                      </div>
                    </div>

                    {/* Rekomendasi Taktis */}
                    <div
                      className="fs-drawer-rekom-box"
                      style={{
                        backgroundColor:
                          threatDetail.status_level === "bahaya"
                            ? "rgba(239, 68, 68, 0.08)"
                            : "rgba(249, 115, 22, 0.08)",
                        borderColor:
                          threatDetail.status_level === "bahaya"
                            ? "rgba(239, 68, 68, 0.25)"
                            : "rgba(249, 115, 22, 0.25)",
                      }}
                    >
                      <div className="fs-drawer-rekom-header">
                        <ShieldAlert
                          size={14}
                          color={threatDetail.status_level === "bahaya" ? "#f87171" : "#fb923c"}
                        />
                        <span
                          style={{
                            fontWeight: 700,
                            fontSize: "0.76rem",
                            color: threatDetail.status_level === "bahaya" ? "#fca5a5" : "#fed7aa",
                            textTransform: "uppercase",
                            letterSpacing: "0.03em",
                          }}
                        >
                          Rekomendasi Respons Lapangan
                        </span>
                      </div>
                      <p className="fs-drawer-rekom-text">
                        {threatDetail.closest_vector
                          ? `DARURAT: Api berjarak ${
                              threatDetail.closest_vector.distance_m < 1000
                                ? `${threatDetail.closest_vector.distance_m} m`
                                : `${(threatDetail.closest_vector.distance_m / 1000).toFixed(2)} km`
                            } dari arah ${threatDetail.closest_vector.bearing_compass}. Segera terjunkan tim patroli batas & buat sekat bakar darurat!`
                          : "Pantau perkembangan titik api secara berkala melalui citra satelit dan siagakan MPA setempat."}
                      </p>
                    </div>

                    {/* Vektor Titik Masuk & Koordinat */}
                    {threatDetail.closest_vector && (
                      <div className="fs-drawer-vector-info">
                        <div className="fs-drawer-subheading">📍 Koordinat Vektor Batas Masuk</div>
                        <div className="fs-drawer-vector-row">
                          <span>Titik Batas KPS:</span>
                          <strong>
                            {threatDetail.closest_vector.kps_boundary_coords[1].toFixed(5)},{" "}
                            {threatDetail.closest_vector.kps_boundary_coords[0].toFixed(5)}
                          </strong>
                        </div>
                        <div className="fs-drawer-vector-row">
                          <span>Titik Api Terdekat:</span>
                          <strong>
                            {threatDetail.closest_vector.hotspot_coords[1].toFixed(5)},{" "}
                            {threatDetail.closest_vector.hotspot_coords[0].toFixed(5)}
                          </strong>
                        </div>
                      </div>
                    )}

                    {/* KPS Sekitar / Tetangga List */}
                    {threatDetail.neighbors && threatDetail.neighbors.length > 0 && (
                      <div className="fs-drawer-neighbors-wrap">
                        <div className="fs-drawer-subheading">
                          🏘️ KPS Bersebelahan / Sekitar ({threatDetail.neighbors.length})
                        </div>
                        <div className="fs-drawer-neighbors-list">
                          {threatDetail.neighbors.map((n) => (
                            <div key={`neighbor-${threatDetail.polygon_id}-${n.id}`} className="fs-drawer-neighbor-item">
                              <div className="fs-drawer-neighbor-header">
                                <span className="fs-drawer-neighbor-name">{n.lembaga}</span>
                                <span className="fs-drawer-neighbor-dist">
                                  {n.distance_m === 0 ? "0 m (Batas Langsung)" : `${n.distance_m} m`}
                                </span>
                              </div>
                              <div className="fs-drawer-neighbor-sub">
                                <span>{n.skema || "KPS"}</span>
                                <span>•</span>
                                <span style={{ color: n.hotspot_count > 0 ? "#f87171" : "#10b981", fontWeight: 600 }}>
                                  🔥 {n.hotspot_count} titik api
                                </span>
                              </div>
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedKpsId(n.id);
                                  setIsDrawerOpen(true);
                                }}
                                className="fs-drawer-neighbor-btn"
                              >
                                Pilih &amp; Pantau KPS Ini
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Drawer Footer Actions */}
                  <div className="fs-drawer-footer">
                    <button
                      type="button"
                      onClick={() => setFocusTrigger((t) => t + 1)}
                      className="fs-drawer-btn"
                      title="Fokuskan kembali peta ke poligon KPS dan titik api"
                    >
                      <Crosshair size={13} color="#38bdf8" />
                      Fokus Poligon
                    </button>

                    {threatDetail.hotspots.length > 0 && (
                      <button
                        type="button"
                        onClick={() => {
                          const h = threatDetail.hotspots[0];
                          navigator.clipboard.writeText(`${h.latitude.toFixed(6)}, ${h.longitude.toFixed(6)}`);
                          setCopiedCoords(true);
                          setTimeout(() => setCopiedCoords(false), 2000);
                        }}
                        className="fs-drawer-btn"
                        title="Salin koordinat hotspot terdekat"
                      >
                        {copiedCoords ? <Check size={13} color="#10b981" /> : <Copy size={13} />}
                        {copiedCoords ? "Tersalin!" : "Salin Titik Api"}
                      </button>
                    )}

                    {onOpenKpsDetail && (
                      <button
                        type="button"
                        onClick={() => onOpenKpsDetail(threatDetail.lembaga)}
                        className="fs-drawer-btn fs-drawer-btn--primary"
                        title="Buka Buku Besar KPS ini"
                      >
                        Buku Besar KPS
                        <ArrowRight size={13} />
                      </button>
                    )}
                  </div>
                </div>
              )}
            </aside>

            {/* Tombol Membuka Kembali Panel jika Ditutup */}
            {!isDrawerOpen && threatDetail && (
              <button
                type="button"
                onClick={() => setIsDrawerOpen(true)}
                className="fs-drawer-reopen-btn"
                title="Buka Panel Detail Metrik KPS"
              >
                <ChevronLeft size={16} />
                <span>Detail KPS</span>
                <span
                  className="fs-drawer-reopen-dot"
                  style={{
                    backgroundColor:
                      threatDetail.status_level === "bahaya"
                        ? "#ef4444"
                        : threatDetail.status_level === "waspada"
                        ? "#f97316"
                        : "#eab308",
                  }}
                />
              </button>
            )}

            <MapContainer
              center={mapCenter}
              zoom={11}
              style={{ width: "100%", height: "100%", background: "#0b1120" }}
              attributionControl={false}
            >
              <TileLayer
                key={activeBasemap.key}
                url={activeBasemap.url}
                subdomains={activeBasemap.subdomains as readonly string[] as string[]}
                maxZoom={activeBasemap.maxZoom}
              />

              {/* Viewport controller: Auto fly ke poligon KPS & hotspot */}
              <MapViewportController
                polygonId={threatDetail?.polygon_id ?? null}
                geometry={threatDetail?.geometry}
                hotspots={threatDetail?.hotspots ?? []}
                focusTrigger={focusTrigger}
                isDrawerOpen={isDrawerOpen}
              />

              {/* Visualisasi Poligon KPS Bersebelahan / Sekitar (Indigo Putus-putus) */}
              {threatDetail?.neighbors?.map((n) => (
                <GeoJSON
                  key={`threat-neighbor-${threatDetail.polygon_id}-${n.id}`}
                  data={{
                    type: "Feature",
                    properties: {
                      id: n.id,
                      lembaga: n.lembaga,
                      desa: n.nama_desa,
                      skema: n.skema,
                      distance_m: n.distance_m,
                      hotspot_count: n.hotspot_count,
                    },
                    geometry: n.geometry,
                  } as never}
                  style={{
                    color: "#818cf8",
                    weight: 2.2,
                    opacity: 0.9,
                    fillColor: "#6366f1",
                    fillOpacity: 0.12,
                    dashArray: "5 4",
                  }}
                >
                  <Popup>
                    <div style={{ color: "#111827", fontSize: "0.82rem", minWidth: "190px" }}>
                      <div style={{ display: "inline-block", fontSize: "0.7rem", fontWeight: "700", color: "#6366f1", backgroundColor: "rgba(99,102,241,0.12)", padding: "1px 6px", borderRadius: "4px", marginBottom: "0.25rem" }}>
                        KPS Bersebelahan / Sekitar
                      </div>
                      <div style={{ fontWeight: "700", fontSize: "0.92rem", color: "#1e1b4b", marginBottom: "0.2rem" }}>
                        {n.lembaga}
                      </div>
                      <div>Jarak ke KPS target: <strong>{n.distance_m === 0 ? "Berbatasan Langsung (0 m)" : `${n.distance_m} m`}</strong></div>
                      {n.skema && <div>Skema: <strong>{n.skema}</strong></div>}
                      <div>🔥 Hotspot di dalamnya: <strong style={{ color: n.hotspot_count > 0 ? "#dc2626" : "#059669" }}>{n.hotspot_count} titik api</strong></div>
                      <div style={{ marginTop: "0.25rem", fontSize: "0.74rem", color: "#4b5563" }}>
                        {[n.nama_desa, n.nama_kec, n.nama_kab].filter(Boolean).join(", ")}
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedKpsId(n.id);
                          setIsDrawerOpen(true);
                        }}
                        style={{
                          marginTop: "0.5rem",
                          width: "100%",
                          backgroundColor: "#4f46e5",
                          color: "#ffffff",
                          border: "none",
                          borderRadius: "4px",
                          padding: "5px 8px",
                          fontSize: "0.75rem",
                          fontWeight: "600",
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          gap: "0.3rem",
                        }}
                      >
                        Pilih &amp; Pantau KPS Ini
                      </button>
                    </div>
                  </Popup>
                </GeoJSON>
              ))}

              {/* Visualisasi Poligon KPS Utama Terpilih (High-Contrast Neon Cyan) */}
              {threatDetail?.geometry && (
                <GeoJSON
                  key={`threat-polygon-${threatDetail.polygon_id}`}
                  data={{
                    type: "Feature",
                    properties: {
                      lembaga: threatDetail.lembaga,
                      desa: threatDetail.nama_desa,
                      status_label: threatDetail.status_label,
                      luas_ha: threatDetail.luas_ha
                    },
                    geometry: threatDetail.geometry
                  } as never}
                  style={{
                    color: "#00e5ff",
                    weight: 3.5,
                    opacity: 1,
                    fillColor: "#0284c7",
                    fillOpacity: 0.22,
                    dashArray: "3 2"
                  }}
                >
                  <Popup>
                    <div style={{ color: "#111827", fontSize: "0.82rem", minWidth: "180px" }}>
                      <div style={{ fontWeight: "700", fontSize: "0.92rem", color: "#0284c7", marginBottom: "0.2rem" }}>
                        {threatDetail.lembaga}
                      </div>
                      <div>Status Ancaman: <strong>{threatDetail.status_label}</strong></div>
                      <div>Luas Kawasan: <strong>{threatDetail.luas_ha ? `${threatDetail.luas_ha.toLocaleString()} ha` : "-"}</strong></div>
                      <div style={{ marginTop: "0.3rem", fontSize: "0.74rem", color: "#4b5563" }}>
                        {[threatDetail.nama_desa, threatDetail.nama_kec, threatDetail.nama_kab, threatDetail.nama_prov].filter(Boolean).join(", ")}
                      </div>
                    </div>
                  </Popup>
                </GeoJSON>
              )}

              {/* Garis Panah Vektor Rambatan Terdekat & Titik Batas Masuk */}
              {threatDetail?.closest_vector && (
                <>
                  <Polyline
                    key={`vector-line-${threatDetail.polygon_id}`}
                    positions={[
                      [threatDetail.closest_vector.hotspot_coords[1], threatDetail.closest_vector.hotspot_coords[0]],
                      [threatDetail.closest_vector.kps_boundary_coords[1], threatDetail.closest_vector.kps_boundary_coords[0]]
                    ]}
                    pathOptions={{
                      color: "#ef4444",
                      weight: 3.5,
                      dashArray: "6, 6",
                      opacity: 0.95
                    }}
                  >
                    <Popup>
                      <div style={{ color: "#111827", fontSize: "0.8rem" }}>
                        <strong style={{ color: "#ef4444" }}>⚡ Vektor Rambatan Terdekat</strong>
                        <br />
                        Jarak ke batas: <strong>{threatDetail.closest_vector.distance_m < 1000 ? `${threatDetail.closest_vector.distance_m} m` : `${(threatDetail.closest_vector.distance_m / 1000).toFixed(2)} km`}</strong>
                        <br />
                        Arah rambatan: <strong>{threatDetail.closest_vector.bearing_compass}</strong>
                      </div>
                    </Popup>
                  </Polyline>

                  {/* Marker Titik Batas KPS Terdekat */}
                  <CircleMarker
                    key={`kps-entry-${threatDetail.polygon_id}`}
                    center={[threatDetail.closest_vector.kps_boundary_coords[1], threatDetail.closest_vector.kps_boundary_coords[0]]}
                    radius={7}
                    pathOptions={{
                      color: "#ffffff",
                      weight: 2,
                      fillColor: "#00e5ff",
                      fillOpacity: 1
                    }}
                  >
                    <Popup>
                      <div style={{ color: "#111827", fontSize: "0.8rem" }}>
                        <strong style={{ color: "#0284c7" }}>📍 Titik Batas KPS Terdekat</strong>
                        <br />
                        Jarak ke api luar: <strong>{threatDetail.closest_vector.distance_m} meter</strong>
                        <br />
                        Arah rambatan: <strong>{threatDetail.closest_vector.bearing_compass}</strong>
                      </div>
                    </Popup>
                  </CircleMarker>
                </>
              )}

              {/* Titik-Titik Hotspot: Di Dalam Kawasan & Perimeter Luar */}
              {threatDetail?.hotspots.map((h) => {
                const isInside = Boolean(h.is_inside || h.status_level === "internal");
                const isHbahaya = h.status_level === "bahaya";
                const isHwaspada = h.status_level === "waspada";
                const pColor = isInside
                  ? "#f43f5e"
                  : isHbahaya
                  ? "#ef4444"
                  : isHwaspada
                  ? "#f97316"
                  : "#eab308";

                return (
                  <CircleMarker
                    key={h.id}
                    center={[h.latitude, h.longitude]}
                    radius={isInside ? 8 : isHbahaya ? 7.5 : 6}
                    pathOptions={{
                      color: "#ffffff",
                      weight: isInside ? 2.5 : 2,
                      fillColor: pColor,
                      fillOpacity: isInside ? 1 : 0.95
                    }}
                  >
                    <Popup>
                      <div style={{ color: "#111827", fontSize: "0.8rem", minWidth: "180px" }}>
                        <div style={{ fontWeight: "700", color: pColor, marginBottom: "0.2rem" }}>
                          {isInside ? "🚨 Hotspot di DALAM Kawasan (Aktif)" : `🔥 Hotspot Luar (${h.status_label})`}
                        </div>
                        {isInside ? (
                          <div style={{ color: "#dc2626", fontWeight: "600", marginBottom: "0.2rem" }}>
                            Titik api aktif terdeteksi di dalam poligon KPS
                          </div>
                        ) : (
                          <>
                            <div>Jarak ke KPS: <strong>{h.distance_m} m</strong> ({h.distance_km} km)</div>
                            <div>Arah dari KPS: <strong>{h.bearing_compass}</strong> ({h.bearing_deg}°)</div>
                            {h.threat_origin_label && (
                              <div style={{ color: h.threat_origin === "non_kps" ? "#ef4444" : "#6366f1", marginTop: "0.15rem", fontWeight: "600" }}>
                                Asal: {h.threat_origin_label}
                              </div>
                            )}
                          </>
                        )}
                        {h.frp > 0 && <div>FRP: <strong>{h.frp} MW</strong></div>}
                        <div>Satelit: {h.satellite || "-"} ({h.confidence || "-"})</div>
                        <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: "0.25rem" }}>
                          {h.detected_at || "-"}
                        </div>
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}
            </MapContainer>

            {/* Legenda Peta Overlay Ringkas */}
            <div className="fs-map-legend">
              <div style={{ fontWeight: "700", marginBottom: "0.15rem", color: "#ffffff", fontSize: "0.74rem" }}>
                Legenda Peta:
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "14px", height: "3px", backgroundColor: "#00e5ff", border: "1px dashed #0284c7" }} />
                <span>Batas Kawasan KPS (Terpilih)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "14px", height: "3px", backgroundColor: "#818cf8", border: "1px dashed #6366f1" }} />
                <span>Batas KPS Bersebelahan / Sekitar</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#f43f5e", border: "2px solid #fff" }} />
                <span style={{ color: "#fda4af", fontWeight: "600" }}>Hotspot di DALAM Kawasan</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "9px", height: "9px", borderRadius: "50%", backgroundColor: "#ef4444", border: "1.5px solid #fff" }} />
                <span>Hotspot Luar &lt; 1 km (Kritis)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "9px", height: "9px", borderRadius: "50%", backgroundColor: "#f97316", border: "1.5px solid #fff" }} />
                <span>Hotspot Luar 1–3 km (Waspada)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "9px", height: "9px", borderRadius: "50%", backgroundColor: "#eab308", border: "1.5px solid #fff" }} />
                <span>Hotspot Luar 3–5 km (Pantau)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "14px", height: "2px", borderTop: "2px dashed #ef4444" }} />
                <span>Vektor Rambatan Terdekat</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: "#00f0ff", border: "1.5px solid #fff" }} />
                <span>Titik Masuk Batas Terdekat</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
