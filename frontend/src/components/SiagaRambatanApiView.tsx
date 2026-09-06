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
  ArrowRight
} from "lucide-react";
import { Circle, CircleMarker, GeoJSON, MapContainer, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import { authFetch, downloadWithAuth } from "../lib/api";

interface SummaryData {
  total_kps_threatened: number;
  total_external_hotspots: number;
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
  distance_m: number;
  distance_km: number;
  status_level: "bahaya" | "waspada" | "pantau";
  status_label: string;
  bearing_deg: number | null;
  bearing_compass: string;
  closest_kps_point: [number, number] | null;
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
  status_level: "bahaya" | "waspada" | "pantau";
  status_label: string;
  min_distance_m: number;
  min_distance_km: number;
  total_external_hotspots: number;
  hotspots: ThreatDetailHotspot[];
  closest_vector: {
    hotspot_coords: [number, number];
    kps_boundary_coords: [number, number];
    distance_m: number;
    bearing_compass: string;
  } | null;
  time_window_hours: number;
  max_distance_km: number;
}

function MapAutoFit({ geom, hotspots }: { geom: any; hotspots: ThreatDetailHotspot[] }) {
  const map = useMap();
  useEffect(() => {
    try {
      map.invalidateSize();
      const bounds = L.latLngBounds([]);
      if (geom) {
        const layer = L.geoJSON(geom);
        bounds.extend(layer.getBounds());
      }
      for (const h of hotspots) {
        bounds.extend([h.latitude, h.longitude]);
      }
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
      }
    } catch {
      // ignore
    }
  }, [geom, hotspots, map]);
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

      {/* KPI Summary Cards */}
      <div className="fs-kpi-grid">
        {/* Bahaya Kritis */}
        <div
          onClick={() => setSelectedLevel("bahaya")}
          className="fs-kpi-card"
          style={{
            backgroundColor: selectedLevel === "bahaya" ? "rgba(239, 68, 68, 0.22)" : "rgba(239, 68, 68, 0.08)",
            border: selectedLevel === "bahaya" ? "1.5px solid #ef4444" : "1px solid rgba(239, 68, 68, 0.25)"
          }}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#f87171" }}>
              Bahaya Kritis (&lt; 1 km)
            </span>
            <span style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#ef4444" }} />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">
              {summary?.bahaya_count ?? 0}
            </span>
            <span style={{ fontSize: "0.85rem", color: "#fca5a5" }}>KPS Terancam</span>
          </div>
          <p className="fs-kpi-card-desc" style={{ color: "#d1d5db" }}>
            Api sangat dekat batas luar, potensi tembus hitungan jam.
          </p>
        </div>

        {/* Waspada */}
        <div
          onClick={() => setSelectedLevel("waspada")}
          className="fs-kpi-card"
          style={{
            backgroundColor: selectedLevel === "waspada" ? "rgba(249, 115, 22, 0.22)" : "rgba(249, 115, 22, 0.08)",
            border: selectedLevel === "waspada" ? "1.5px solid #f97316" : "1px solid rgba(249, 115, 22, 0.25)"
          }}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#fb923c" }}>
              Waspada (1–3 km)
            </span>
            <span style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#f97316" }} />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">
              {summary?.waspada_count ?? 0}
            </span>
            <span style={{ fontSize: "0.85rem", color: "#fed7aa" }}>KPS Terancam</span>
          </div>
          <p className="fs-kpi-card-desc" style={{ color: "#d1d5db" }}>
            Api aktif di area tetangga, butuh sekat perimeter.
          </p>
        </div>

        {/* Pantau */}
        <div
          onClick={() => setSelectedLevel("pantau")}
          className="fs-kpi-card"
          style={{
            backgroundColor: selectedLevel === "pantau" ? "rgba(234, 179, 8, 0.22)" : "rgba(234, 179, 8, 0.08)",
            border: selectedLevel === "pantau" ? "1.5px solid #eab308" : "1px solid rgba(234, 179, 8, 0.25)"
          }}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#fde047" }}>
              Pantau (3–5 km)
            </span>
            <span style={{ width: "10px", height: "10px", borderRadius: "50%", backgroundColor: "#eab308" }} />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">
              {summary?.pantau_count ?? 0}
            </span>
            <span style={{ fontSize: "0.85rem", color: "#fef08a" }}>KPS Terancam</span>
          </div>
          <p className="fs-kpi-card-desc" style={{ color: "#d1d5db" }}>
            Klaster api lanskap sekitarnya, siaga dini patroli.
          </p>
        </div>

        {/* Total Hotspot Luar */}
        <div
          onClick={() => setSelectedLevel("all")}
          className="fs-kpi-card"
          style={{
            backgroundColor: selectedLevel === "all" ? "rgba(59, 130, 246, 0.22)" : "rgba(31, 41, 55, 0.5)",
            border: selectedLevel === "all" ? "1.5px solid #3b82f6" : "1px solid rgba(255,255,255,0.08)"
          }}
        >
          <div className="fs-kpi-card-header">
            <span className="fs-kpi-card-label" style={{ color: "#93c5fd" }}>
              Total Hotspot Luar (5 km)
            </span>
            <Flame size={16} color="#3b82f6" />
          </div>
          <div className="fs-kpi-card-count">
            <span className="fs-kpi-card-num">
              {summary?.total_external_hotspots?.toLocaleString() ?? 0}
            </span>
            <span style={{ fontSize: "0.85rem", color: "#9ca3af" }}>Titik Api</span>
          </div>
          <p className="fs-kpi-card-desc" style={{ color: "#9ca3af" }}>
            Menargetkan {summary?.total_kps_threatened ?? 0} KPS di seluruh Indonesia.
          </p>
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
              style={{ maxWidth: "180px" }}
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
              style={{ maxWidth: "180px" }}
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
                    onClick={() => setSelectedKpsId(item.polygon_id)}
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
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Layers size={17} color="#60a5fa" />
              <span style={{ fontSize: "0.88rem", fontWeight: "700", color: "#ffffff" }}>
                {threatDetail ? threatDetail.lembaga : "Peta Perimeter Ancaman"}
              </span>
            </div>
            {threatDetail && (
              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                <span style={{ fontSize: "0.76rem", color: "#9ca3af" }}>
                  {threatDetail.hotspots.length} titik api luar radius {threatDetail.max_distance_km} km
                </span>
                {onOpenKpsDetail && (
                  <button
                    type="button"
                    onClick={() => onOpenKpsDetail(threatDetail.lembaga)}
                    style={{
                      background: "rgba(59, 130, 246, 0.15)",
                      border: "1px solid rgba(59, 130, 246, 0.4)",
                      borderRadius: "4px",
                      color: "#93c5fd",
                      fontSize: "0.72rem",
                      cursor: "pointer",
                      padding: "0.2rem 0.5rem",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "0.25rem"
                    }}
                  >
                    Detail KPS <ArrowRight size={11} />
                  </button>
                )}
              </div>
            )}
          </div>

          <div className="fs-map-stage">
            {loadingDetail && (
              <div
                style={{
                  position: "absolute",
                  inset: 0,
                  backgroundColor: "rgba(17, 24, 39, 0.75)",
                  zIndex: 1000,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "0.5rem",
                  fontSize: "0.85rem",
                  color: "#e5e7eb"
                }}
              >
                <RefreshCw size={18} className="animate-spin" /> Memuat visualisasi poligon KPS &amp; perimeter buffer...
              </div>
            )}

            <MapContainer
              center={mapCenter}
              zoom={11}
              style={{ width: "100%", height: "100%", background: "#0b1120" }}
              attributionControl={false}
            >
              <TileLayer
                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                maxZoom={19}
              />

              {/* Auto Fit Bounds ke Poligon KPS + Seluruh Titik Api */}
              {threatDetail?.geometry && (
                <MapAutoFit geom={threatDetail.geometry} hotspots={threatDetail.hotspots} />
              )}

              {/* Render Poligon KPS */}
              {threatDetail?.geometry && (
                <GeoJSON
                  data={threatDetail.geometry}
                  style={{
                    color: "#10b981",
                    weight: 2.5,
                    fillColor: "#10b981",
                    fillOpacity: 0.15
                  }}
                >
                  <Popup>
                    <div style={{ color: "#111827", fontSize: "0.8rem" }}>
                      <strong>{threatDetail.lembaga}</strong>
                      <br />
                      Status Siaga: <strong>{threatDetail.status_label}</strong>
                      <br />
                      Luas: {threatDetail.luas_ha ? `${threatDetail.luas_ha.toLocaleString()} ha` : "-"}
                    </div>
                  </Popup>
                </GeoJSON>
              )}

              {/* Multi-Ring Buffers di sekeliling Centroid KPS (1 km, 3 km, 5 km) */}
              {threatDetail?.centroid && (
                <>
                  <Circle
                    center={[threatDetail.centroid[1], threatDetail.centroid[0]]}
                    radius={1000}
                    pathOptions={{ color: "#ef4444", weight: 1.5, dashArray: "4, 4", fill: false }}
                  />
                  <Circle
                    center={[threatDetail.centroid[1], threatDetail.centroid[0]]}
                    radius={3000}
                    pathOptions={{ color: "#f97316", weight: 1.5, dashArray: "4, 4", fill: false }}
                  />
                  <Circle
                    center={[threatDetail.centroid[1], threatDetail.centroid[0]]}
                    radius={5000}
                    pathOptions={{ color: "#eab308", weight: 1.5, dashArray: "4, 4", fill: false }}
                  />
                </>
              )}

              {/* Garis Panah Vektor Ancaman Terdekat */}
              {threatDetail?.closest_vector && (
                <Polyline
                  positions={[
                    [threatDetail.closest_vector.hotspot_coords[1], threatDetail.closest_vector.hotspot_coords[0]],
                    [threatDetail.closest_vector.kps_boundary_coords[1], threatDetail.closest_vector.kps_boundary_coords[0]]
                  ]}
                  pathOptions={{
                    color: "#ef4444",
                    weight: 3.5,
                    dashArray: "6, 6"
                  }}
                >
                  <Popup>
                    <div style={{ color: "#111827", fontSize: "0.78rem" }}>
                      <strong>Garis Vektor Rambatan Terdekat</strong>
                      <br />
                      Jarak: <strong>{threatDetail.closest_vector.distance_m} meter</strong>
                      <br />
                      Arah: <strong>{threatDetail.closest_vector.bearing_compass}</strong>
                    </div>
                  </Popup>
                </Polyline>
              )}

              {/* Titik-Titik Hotspot Luar */}
              {threatDetail?.hotspots.map((h) => {
                const isHbahaya = h.status_level === "bahaya";
                const isHwaspada = h.status_level === "waspada";
                const pColor = isHbahaya ? "#ef4444" : isHwaspada ? "#f97316" : "#eab308";

                return (
                  <CircleMarker
                    key={h.id}
                    center={[h.latitude, h.longitude]}
                    radius={isHbahaya ? 7 : 5.5}
                    pathOptions={{
                      color: "#ffffff",
                      weight: 1.5,
                      fillColor: pColor,
                      fillOpacity: 0.95
                    }}
                  >
                    <Popup>
                      <div style={{ color: "#111827", fontSize: "0.8rem", minWidth: "160px" }}>
                        <div style={{ fontWeight: "700", color: pColor, marginBottom: "0.2rem" }}>
                          🔥 Hotspot Luar ({h.status_label})
                        </div>
                        <div>Jarak ke KPS: <strong>{h.distance_m} m</strong> ({h.distance_km} km)</div>
                        <div>Arah dari KPS: <strong>{h.bearing_compass}</strong> ({h.bearing_deg}°)</div>
                        {h.frp > 0 && <div>FRP: <strong>{h.frp} MW</strong></div>}
                        <div>Satelit: {h.satellite || "-"} ({h.confidence || "-"})</div>
                        <div style={{ fontSize: "0.72rem", color: "#6b7280", marginTop: "0.2rem" }}>
                          {h.detected_at || "-"}
                        </div>
                      </div>
                    </Popup>
                  </CircleMarker>
                );
              })}
            </MapContainer>

            {/* Legenda Peta Overlay */}
            <div className="fs-map-legend">
              <div style={{ fontWeight: "700", marginBottom: "0.15rem", color: "#ffffff" }}>Legenda Peta:</div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "12px", height: "3px", backgroundColor: "#10b981" }} />
                <span>Batas Kawasan KPS</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "9px", height: "9px", borderRadius: "50%", backgroundColor: "#ef4444" }} />
                <span>Hotspot Luar &lt; 1 km (Kritis)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "9px", height: "9px", borderRadius: "50%", backgroundColor: "#f97316" }} />
                <span>Hotspot Luar 1–3 km (Waspada)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "9px", height: "9px", borderRadius: "50%", backgroundColor: "#eab308" }} />
                <span>Hotspot Luar 3–5 km (Pantau)</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
                <span style={{ width: "14px", height: "2px", borderTop: "2px dashed #ef4444" }} />
                <span>Garis Rambatan Api Terdekat</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
