import React, { useState, useEffect, useMemo } from "react";
import {
  Flame,
  AlertTriangle,
  ShieldCheck,
  Download,
  Search,
  RefreshCw,
  ChevronRight,
  TrendingUp,
  FileSpreadsheet,
  Info,
  Wind,
  ShieldAlert,
  Lock
} from "lucide-react";
import { authFetch, downloadWithAuth } from "../lib/api";
import type { AppSession } from "../types/api";

type CategoryType =
  | "burned_active_today"
  | "burned_clear_today"
  | "early_warning_today"
  | "early_warning_all"
  | "all_burned";

interface SummaryMetrics {
  burned_area_stats: {
    total_polygons: number;
    total_burned_ha: number;
    active_today: number;
    strict_reburn_kps_today: number;
    strict_reburn_hotspots_today: number;
    expanding_hotspots_today: number;
    clear_today: number;
    active_yesterday: number;
    active_7d: number;
    padam_total: number;
  };
  early_warning_stats: {
    total_kps: number;
    active_today: number;
    active_yesterday: number;
    active_7d: number;
    today_hotspots: number;
    month_hotspots: number;
    year_hotspots: number;
  };
  wilker_bps?: string | null;
  updated_at: string;
}

interface KpsItem {
  id: number;
  lembaga: string;
  nama_desa: string | null;
  nama_kec: string | null;
  nama_kab: string | null;
  nama_prov: string | null;
  wilker_bps: string | null;
  skema: string | null;
  luas_sk: number | null;
  no_sk: string | null;
  total_burned_ha: number;
  burn_frequency: number;
  latest_burned_month: string | null;
  hotspots_today: number;
  hotspots_today_strict_reburn: number;
  hotspots_today_expanding: number;
  min_distance_km: number | null;
  max_distance_km: number | null;
  avg_distance_km: number | null;
  fire_direction: string | null;
  fire_azimuth_deg: number | null;
  propagation_zone: string;
  zone_code: string;
  hotspots_yesterday: number;
  hotspots_7d: number;
  hotspots_7d_strict_reburn: number;
  hotspots_7d_expanding: number;
  hotspots_month: number;
  hotspots_year: number;
  latest_hotspot_at: string | null;
  ftri_score: number;
  status_label: string;
}

interface EarlyWarningViewProps {
  onOpenKpsDetail?: (agencyName: string) => void;
  session?: AppSession | null;
  selectedWilker?: string;
}

export function EarlyWarningView({ onOpenKpsDetail, session, selectedWilker }: EarlyWarningViewProps) {
  const [category, setCategory] = useState<CategoryType>("burned_active_today");
  const [summary, setSummary] = useState<SummaryMetrics | null>(null);
  const [items, setItems] = useState<KpsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingItems, setLoadingItems] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // Active wilker for BPS role
  const activeWilkerBps = useMemo(() => {
    if (session?.role === "bps" && session.wilker_bps) {
      return session.wilker_bps;
    }
    return selectedWilker || "";
  }, [session, selectedWilker]);

  // Filters
  const [search, setSearch] = useState("");
  const [selectedProvince, setSelectedProvince] = useState("");
  const [selectedSkema, setSelectedSkema] = useState("");
  const [selectedZone, setSelectedZone] = useState("");
  const [sortBy, setSortBy] = useState<"ftri" | "hs_today" | "distance" | "hs_strict" | "burned_ha" | "hs_7d">("ftri");

  // Fetch summary
  const loadSummary = async () => {
    try {
      setLoading(true);
      const query = new URLSearchParams();
      if (activeWilkerBps) query.append("wilker_bps", activeWilkerBps);

      const res = await authFetch(`/api/early-warning/summary?${query.toString()}`);
      if (!res.ok) throw new Error("Gagal memuat ringkasan data");
      const data: SummaryMetrics = await res.json();
      setSummary(data);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  // Fetch list items
  const loadItems = async () => {
    try {
      setLoadingItems(true);
      const query = new URLSearchParams({
        category,
        limit: "1500"
      });
      if (activeWilkerBps) query.append("wilker_bps", activeWilkerBps);
      if (selectedProvince) query.append("province", selectedProvince);
      if (selectedSkema) query.append("skema", selectedSkema);
      if (search) query.append("search", search);

      const res = await authFetch(`/api/early-warning/list?${query.toString()}`);
      if (!res.ok) throw new Error("Gagal memuat daftar KPS");
      const data = await res.json();
      setItems(data.items || []);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoadingItems(false);
    }
  };

  useEffect(() => {
    loadSummary();
  }, [activeWilkerBps]);

  useEffect(() => {
    loadItems();
  }, [category, activeWilkerBps, selectedProvince, selectedSkema]);

  // Unique options for filters
  const provinces = useMemo(() => {
    const set = new Set<string>();
    items.forEach((i) => {
      if (i.nama_prov) set.add(i.nama_prov);
    });
    return Array.from(set).sort();
  }, [items]);

  const skemas = useMemo(() => {
    const set = new Set<string>();
    items.forEach((i) => {
      if (i.skema) set.add(i.skema);
    });
    return Array.from(set).sort();
  }, [items]);

  // Filtered & sorted items
  const displayItems = useMemo(() => {
    let result = [...items];
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (i) =>
          i.lembaga.toLowerCase().includes(q) ||
          (i.nama_kab && i.nama_kab.toLowerCase().includes(q)) ||
          (i.nama_prov && i.nama_prov.toLowerCase().includes(q)) ||
          (i.nama_desa && i.nama_desa.toLowerCase().includes(q))
      );
    }

    if (selectedZone) {
      result = result.filter((i) => i.zone_code === selectedZone);
    }

    result.sort((a, b) => {
      if (sortBy === "ftri") return b.ftri_score - a.ftri_score;
      if (sortBy === "hs_today") return b.hotspots_today - a.hotspots_today;
      if (sortBy === "distance") return (b.max_distance_km || 0) - (a.max_distance_km || 0);
      if (sortBy === "hs_strict") return b.hotspots_today_strict_reburn - a.hotspots_today_strict_reburn;
      if (sortBy === "hs_7d") return b.hotspots_7d - a.hotspots_7d;
      if (sortBy === "burned_ha") return b.total_burned_ha - a.total_burned_ha;
      return 0;
    });

    return result;
  }, [items, search, selectedZone, sortBy]);

  const handleDownloadExcel = async () => {
    try {
      setDownloading(true);
      const wilkerQuery = activeWilkerBps ? `&wilker_bps=${encodeURIComponent(activeWilkerBps)}` : "";
      const wilkerFile = activeWilkerBps ? `-${activeWilkerBps.replace(/\s+/g, "_")}` : "";
      const filename = `rekap-analisis-kps-${category}${wilkerFile}-${new Date().toISOString().slice(0, 10)}.xlsx`;
      await downloadWithAuth(`/api/early-warning/export.xlsx?category=${category}${wilkerQuery}`, filename);
    } catch (err: any) {
      alert("Gagal mengunduh Excel: " + err.message);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div style={{ padding: "1.5rem", color: "#f3f4f6", height: "100%", overflowY: "auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.25rem", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
            <h1 style={{ fontSize: "1.5rem", fontWeight: "700", display: "flex", alignItems: "center", gap: "0.6rem", margin: 0, color: "#ffffff" }}>
              <Flame style={{ color: "#ef4444" }} size={28} />
              Peringatan Dini & Rekapitulasi Kebakaran KPS
            </h1>
            {session?.role === "bps" && activeWilkerBps ? (
              <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem", backgroundColor: "rgba(37, 99, 235, 0.2)", border: "1px solid #3b82f6", color: "#93c5fd", padding: "0.2rem 0.6rem", borderRadius: "999px", fontSize: "0.75rem", fontWeight: "600" }}>
                <Lock size={12} /> {activeWilkerBps}
              </span>
            ) : null}
          </div>
          <p style={{ fontSize: "0.85rem", color: "#9ca3af", marginTop: "0.3rem", margin: 0 }}>
            {session?.role === "bps"
              ? `Menampilkan data spasial & titik api khusus wilayah kerja ${activeWilkerBps}`
              : "Deteksi Spasial: Titik Tepat di Bekas Terbakar (Strict Re-burn), Jarak (KM), dan Arah Kompas Perambatan"}
          </p>
        </div>

        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          <button
            type="button"
            onClick={handleDownloadExcel}
            disabled={downloading}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.45rem",
              backgroundColor: "#15803d",
              color: "#ffffff",
              border: "none",
              borderRadius: "6px",
              padding: "0.55rem 0.95rem",
              fontSize: "0.82rem",
              fontWeight: "600",
              cursor: downloading ? "not-allowed" : "pointer",
              boxShadow: "0 2px 4px rgba(0,0,0,0.2)"
            }}
          >
            <Download size={15} />
            {downloading ? "Mengunduh..." : "Download Excel"}
          </button>

          <button
            type="button"
            onClick={() => {
              loadSummary();
              loadItems();
            }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
              backgroundColor: "rgba(255,255,255,0.08)",
              color: "#e5e7eb",
              border: "1px solid rgba(255,255,255,0.15)",
              borderRadius: "6px",
              padding: "0.55rem 0.85rem",
              fontSize: "0.82rem",
              cursor: "pointer"
            }}
          >
            <RefreshCw size={14} className={loading || loadingItems ? "animate-spin" : ""} />
            Segarkan
          </button>
        </div>
      </div>

      {/* Scientific Guide Banner */}
      <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", backgroundColor: "rgba(30, 41, 59, 0.6)", border: "1px solid rgba(255,255,255,0.08)", padding: "0.6rem 0.85rem", borderRadius: "6px", marginBottom: "1.2rem", fontSize: "0.75rem", color: "#cbd5e1", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <Wind size={15} color="#38bdf8" />
          <strong>Pedoman Zona & Arah Perambatan:</strong>
        </div>
        <span>
          <span style={{ color: "#ef4444", fontWeight: "600" }}>🔴 Zona 1 (&le;1.0 km)</span> = Merambat Langsung | <span style={{ color: "#f97316", fontWeight: "600" }}>🟠 Zona 2 (1.0 - 3.0 km)</span> = Loncatan Bara | <span style={{ color: "#eab308", fontWeight: "600" }}>🟡 Zona 3 (&gt;3.0 km)</span> = Titik Bakar Mandiri.
        </span>
      </div>

      {/* KPI Cards */}
      {summary && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.85rem", marginBottom: "1.5rem" }}>
          {/* Card 1: Re-burn active today with strict breakdown */}
          <div
            onClick={() => setCategory("burned_active_today")}
            style={{
              backgroundColor: category === "burned_active_today" ? "rgba(239, 68, 68, 0.18)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${category === "burned_active_today" ? "#ef4444" : "rgba(255,255,255,0.08)"}`,
              borderRadius: "8px",
              padding: "1rem",
              cursor: "pointer",
              transition: "all 0.2s ease"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
              <span style={{ fontSize: "0.75rem", fontWeight: "600", color: "#ef4444", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                🔴 Terbakar Hari Ini
              </span>
              <AlertTriangle size={16} color="#ef4444" />
            </div>
            <div style={{ fontSize: "1.85rem", fontWeight: "800", color: "#ffffff", lineHeight: 1 }}>
              {summary.burned_area_stats.active_today} <span style={{ fontSize: "0.85rem", fontWeight: "normal", color: "#9ca3af" }}>KPS</span>
            </div>
            <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.6rem", flexWrap: "wrap", fontSize: "0.7rem" }}>
              <span style={{ backgroundColor: "rgba(239,68,68,0.25)", color: "#fca5a5", padding: "0.15rem 0.4rem", borderRadius: "4px" }}>
                🔥 {summary.burned_area_stats.strict_reburn_hotspots_today} di Bekas Terbakar
              </span>
              <span style={{ backgroundColor: "rgba(249,115,22,0.2)", color: "#fdba74", padding: "0.15rem 0.4rem", borderRadius: "4px" }}>
                ⚡ {summary.burned_area_stats.expanding_hotspots_today} di Blok Baru
              </span>
            </div>
          </div>

          {/* Card 2: Burned clear today (padam) */}
          <div
            onClick={() => setCategory("burned_clear_today")}
            style={{
              backgroundColor: category === "burned_clear_today" ? "rgba(34, 197, 94, 0.18)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${category === "burned_clear_today" ? "#22c55e" : "rgba(255,255,255,0.08)"}`,
              borderRadius: "8px",
              padding: "1rem",
              cursor: "pointer",
              transition: "all 0.2s ease"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
              <span style={{ fontSize: "0.75rem", fontWeight: "600", color: "#22c55e", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                🟢 Padam Hari Ini
              </span>
              <ShieldCheck size={16} color="#22c55e" />
            </div>
            <div style={{ fontSize: "1.85rem", fontWeight: "800", color: "#ffffff", lineHeight: 1 }}>
              {summary.burned_area_stats.clear_today} <span style={{ fontSize: "0.85rem", fontWeight: "normal", color: "#9ca3af" }}>KPS</span>
            </div>
            <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginTop: "0.5rem" }}>
              KPS ber-luas terbakar dengan 0 titik api hari ini
            </div>
          </div>

          {/* Card 3: Early Warning today */}
          <div
            onClick={() => setCategory("early_warning_today")}
            style={{
              backgroundColor: category === "early_warning_today" ? "rgba(249, 115, 22, 0.18)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${category === "early_warning_today" ? "#f97316" : "rgba(255,255,255,0.08)"}`,
              borderRadius: "8px",
              padding: "1rem",
              cursor: "pointer",
              transition: "all 0.2s ease"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
              <span style={{ fontSize: "0.75rem", fontWeight: "600", color: "#f97316", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                ⚡ EW: Titik Baru Hari Ini
              </span>
              <TrendingUp size={16} color="#f97316" />
            </div>
            <div style={{ fontSize: "1.85rem", fontWeight: "800", color: "#ffffff", lineHeight: 1 }}>
              {summary.early_warning_stats.active_today} <span style={{ fontSize: "0.85rem", fontWeight: "normal", color: "#9ca3af" }}>KPS</span>
            </div>
            <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginTop: "0.5rem" }}>
              KPS titik api baru (belum masuk rekap luas terbakar)
            </div>
          </div>

          {/* Card 4: Total Early Warning 2026 */}
          <div
            onClick={() => setCategory("early_warning_all")}
            style={{
              backgroundColor: category === "early_warning_all" ? "rgba(59, 130, 246, 0.18)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${category === "early_warning_all" ? "#3b82f6" : "rgba(255,255,255,0.08)"}`,
              borderRadius: "8px",
              padding: "1rem",
              cursor: "pointer",
              transition: "all 0.2s ease"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
              <span style={{ fontSize: "0.75rem", fontWeight: "600", color: "#60a5fa", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                📋 Total Early Warning 2026
              </span>
              <FileSpreadsheet size={16} color="#60a5fa" />
            </div>
            <div style={{ fontSize: "1.85rem", fontWeight: "800", color: "#ffffff", lineHeight: 1 }}>
              {summary.early_warning_stats.total_kps} <span style={{ fontSize: "0.85rem", fontWeight: "normal", color: "#9ca3af" }}>KPS</span>
            </div>
            <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginTop: "0.5rem" }}>
              Total KPS terdeteksi hotspot di 2026 tanpa rekap luasan
            </div>
          </div>
        </div>
      )}

      {/* Tabs Navigation */}
      <div style={{ display: "flex", gap: "0.4rem", borderBottom: "1px solid rgba(255,255,255,0.1)", paddingBottom: "0.6rem", marginBottom: "1rem", overflowX: "auto" }}>
        {[
          { id: "burned_active_today", label: `🔴 Terbakar Hari Ini (${summary?.burned_area_stats.active_today ?? 0})` },
          { id: "burned_clear_today", label: `🟢 Padam Hari Ini (${summary?.burned_area_stats.clear_today ?? 0})` },
          { id: "early_warning_today", label: `⚡ Early Warning Hari Ini (${summary?.early_warning_stats.active_today ?? 0})` },
          { id: "early_warning_all", label: `📋 Semua Early Warning (${summary?.early_warning_stats.total_kps ?? 0})` },
          { id: "all_burned", label: `📊 Seluruh KPS Terbakar (${summary?.burned_area_stats.total_polygons ?? 0})` }
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setCategory(t.id as CategoryType)}
            style={{
              padding: "0.55rem 0.95rem",
              borderRadius: "6px",
              border: "none",
              fontSize: "0.82rem",
              fontWeight: category === t.id ? "700" : "500",
              backgroundColor: category === t.id ? "#2563eb" : "rgba(255,255,255,0.05)",
              color: category === t.id ? "#ffffff" : "#9ca3af",
              cursor: "pointer",
              whiteSpace: "nowrap",
              transition: "all 0.15s ease"
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Search & Filter Bar */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap", alignItems: "center" }}>
        {/* Search */}
        <div style={{ position: "relative", flex: "1 1 220px" }}>
          <Search size={15} style={{ position: "absolute", left: "0.75rem", top: "50%", transform: "translateY(-50%)", color: "#6b7280" }} />
          <input
            type="text"
            placeholder="Cari KPS, desa, kecamatan, kabupaten..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: "100%",
              padding: "0.5rem 0.75rem 0.5rem 2.2rem",
              backgroundColor: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: "6px",
              color: "#ffffff",
              fontSize: "0.82rem"
            }}
          />
        </div>

        {/* Province Filter */}
        <select
          value={selectedProvince}
          onChange={(e) => setSelectedProvince(e.target.value)}
          style={{
            padding: "0.5rem 0.75rem",
            backgroundColor: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "6px",
            color: "#ffffff",
            fontSize: "0.82rem",
            minWidth: "150px"
          }}
        >
          <option value="">Semua Provinsi</option>
          {provinces.map((p) => (
            <option key={p} value={p} style={{ backgroundColor: "#1e293b" }}>
              {p}
            </option>
          ))}
        </select>

        {/* Skema Filter */}
        <select
          value={selectedSkema}
          onChange={(e) => setSelectedSkema(e.target.value)}
          style={{
            padding: "0.5rem 0.75rem",
            backgroundColor: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "6px",
            color: "#ffffff",
            fontSize: "0.82rem",
            minWidth: "130px"
          }}
        >
          <option value="">Semua Skema</option>
          {skemas.map((s) => (
            <option key={s} value={s} style={{ backgroundColor: "#1e293b" }}>
              {s}
            </option>
          ))}
        </select>

        {/* Zona Perambatan Filter */}
        {category === "burned_active_today" && (
          <select
            value={selectedZone}
            onChange={(e) => setSelectedZone(e.target.value)}
            style={{
              padding: "0.5rem 0.75rem",
              backgroundColor: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.12)",
              borderRadius: "6px",
              color: "#ffffff",
              fontSize: "0.82rem",
              minWidth: "160px"
            }}
          >
            <option value="">Semua Zona Perambatan</option>
            <option value="zone1" style={{ backgroundColor: "#1e293b" }}>🔴 Zona 1: Merambat Langsung (≤1 km)</option>
            <option value="zone2" style={{ backgroundColor: "#1e293b" }}>🟠 Zona 2: Loncatan Bara (1-3 km)</option>
            <option value="zone3" style={{ backgroundColor: "#1e293b" }}>🟡 Zona 3: Titik Bakar Mandiri (&gt;3 km)</option>
            <option value="combo" style={{ backgroundColor: "#1e293b" }}>🔴 Kombinasi Bara & Merambat</option>
            <option value="strict" style={{ backgroundColor: "#1e293b" }}>🔥 Strict Re-burn (Bara Bekas)</option>
          </select>
        )}

        {/* Sort */}
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as any)}
          style={{
            padding: "0.5rem 0.75rem",
            backgroundColor: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "6px",
            color: "#ffffff",
            fontSize: "0.82rem"
          }}
        >
          <option value="ftri" style={{ backgroundColor: "#1e293b" }}>Urut: Skor FTRI Tertinggi</option>
          <option value="hs_today" style={{ backgroundColor: "#1e293b" }}>Urut: Hotspot Hari Ini (Total)</option>
          <option value="distance" style={{ backgroundColor: "#1e293b" }}>Urut: Jarak Perambatan Terjauh (KM)</option>
          <option value="hs_strict" style={{ backgroundColor: "#1e293b" }}>Urut: Strict Re-burn (Bekas Terbakar)</option>
          <option value="hs_7d" style={{ backgroundColor: "#1e293b" }}>Urut: Hotspot 7 Hari</option>
          <option value="burned_ha" style={{ backgroundColor: "#1e293b" }}>Urut: Luas Terbakar (ha)</option>
        </select>

        <div style={{ fontSize: "0.78rem", color: "#9ca3af", marginLeft: "auto" }}>
          Menampilkan <strong>{displayItems.length}</strong> KPS
        </div>
      </div>

      {/* Table */}
      <div style={{ backgroundColor: "rgba(255,255,255,0.03)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.08)", overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem", textAlign: "left" }}>
          <thead>
            <tr style={{ backgroundColor: "rgba(255,255,255,0.06)", borderBottom: "1px solid rgba(255,255,255,0.12)", color: "#9ca3af" }}>
              <th style={{ padding: "0.75rem 0.8rem", width: "45px", textAlign: "center" }}>No</th>
              <th style={{ padding: "0.75rem 0.8rem" }}>Nama KPS / Lembaga</th>
              <th style={{ padding: "0.75rem 0.8rem", width: "70px", textAlign: "center" }}>Skema</th>
              <th style={{ padding: "0.75rem 0.8rem" }}>Wilayah (Kab, Prov)</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "right" }}>Luas Terbakar (Kemenhut)</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center", minWidth: "180px" }}>
                Hotspot Hari Ini, Jarak & Arah
                <div style={{ fontSize: "0.68rem", fontWeight: "normal", color: "#6b7280" }}>[Total / Bekas / Jarak (km) & Arah]</div>
              </th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>HS Kemarin</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>HS 7 Hari</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>HS Agt</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "right" }}>Skor FTRI</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>Status & Zona Perambatan</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loadingItems ? (
              <tr>
                <td colSpan={12} style={{ padding: "2.5rem", textAlign: "center", color: "#9ca3af" }}>
                  <RefreshCw size={20} className="animate-spin" style={{ margin: "0 auto 0.5rem auto" }} />
                  Memuat data analisis...
                </td>
              </tr>
            ) : displayItems.length === 0 ? (
              <tr>
                <td colSpan={12} style={{ padding: "2.5rem", textAlign: "center", color: "#6b7280" }}>
                  Tidak ada data KPS yang sesuai dengan filter{activeWilkerBps ? ` untuk ${activeWilkerBps}` : ""}.
                </td>
              </tr>
            ) : (
              displayItems.map((item, idx) => {
                const hasDist = item.min_distance_km !== null;
                const distLabel = hasDist
                  ? item.min_distance_km === item.max_distance_km
                    ? `${item.min_distance_km} km`
                    : `${item.min_distance_km} - ${item.max_distance_km} km`
                  : null;

                const dirShort = item.fire_direction ? item.fire_direction.split(" ")[0] : null;

                return (
                  <tr
                    key={item.id}
                    style={{
                      borderBottom: "1px solid rgba(255,255,255,0.04)",
                      backgroundColor: item.hotspots_today > 0 ? "rgba(239, 68, 68, 0.05)" : "transparent"
                    }}
                  >
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center", color: "#6b7280" }}>{idx + 1}</td>
                    <td style={{ padding: "0.65rem 0.8rem" }}>
                      <div style={{ fontWeight: "600", color: "#ffffff" }}>{item.lembaga}</div>
                      <div style={{ fontSize: "0.7rem", color: "#6b7280" }}>
                        Desa: {item.nama_desa || "-"} | Kec: {item.nama_kec || "-"}
                      </div>
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center" }}>
                      <span style={{ padding: "0.15rem 0.45rem", borderRadius: "4px", backgroundColor: "rgba(255,255,255,0.08)", fontSize: "0.72rem", color: "#d1d5db" }}>
                        {item.skema || "-"}
                      </span>
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem" }}>
                      <div style={{ color: "#e5e7eb" }}>{item.nama_kab}</div>
                      <div style={{ fontSize: "0.7rem", color: "#9ca3af" }}>{item.nama_prov}</div>
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "right", fontWeight: "600", color: item.total_burned_ha > 0 ? "#fca5a5" : "#9ca3af" }}>
                      {item.total_burned_ha > 0 ? `${item.total_burned_ha.toLocaleString("id-ID", { minimumFractionDigits: 2 })} ha` : "-"}
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center" }}>
                      {item.hotspots_today > 0 ? (
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.25rem" }}>
                          <span
                            style={{
                              padding: "0.15rem 0.55rem",
                              borderRadius: "999px",
                              fontWeight: "800",
                              fontSize: "0.78rem",
                              backgroundColor: "#ef4444",
                              color: "#ffffff"
                            }}
                          >
                            {item.hotspots_today} Hotspot
                          </span>
                          <div style={{ display: "flex", gap: "0.25rem", fontSize: "0.68rem", flexWrap: "wrap", justifyContent: "center" }}>
                            {item.hotspots_today_strict_reburn > 0 ? (
                              <span
                                title={`${item.hotspots_today_strict_reburn} titik jatuh tepat di atas koordinat bekas luka bakar Kementerian Kehutanan sebelumnya`}
                                style={{ backgroundColor: "rgba(239,68,68,0.25)", color: "#fca5a5", padding: "0.1rem 0.35rem", borderRadius: "3px", fontWeight: "600" }}
                              >
                                🔥 {item.hotspots_today_strict_reburn} Bekas
                              </span>
                            ) : null}
                            {item.hotspots_today_expanding > 0 ? (
                              <span
                                title={`${item.hotspots_today_expanding} titik berada di blok baru dengan jarak ${distLabel || ''} arah ${item.fire_direction || '-'}`}
                                style={{
                                  backgroundColor: item.zone_code === "zone1" ? "rgba(239,68,68,0.25)" : item.zone_code === "zone2" ? "rgba(249,115,22,0.2)" : "rgba(234,179,8,0.2)",
                                  color: item.zone_code === "zone1" ? "#fca5a5" : item.zone_code === "zone2" ? "#fdba74" : "#fef08a",
                                  padding: "0.1rem 0.35rem",
                                  borderRadius: "3px",
                                  fontWeight: "600",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  gap: "0.2rem"
                                }}
                              >
                                ⚡ {item.hotspots_today_expanding} Baru {distLabel ? `(${distLabel}${dirShort ? ` ke ${dirShort}` : ''})` : ""}
                              </span>
                            ) : null}
                          </div>
                        </div>
                      ) : (
                        <span style={{ color: "#6b7280", fontSize: "0.75rem" }}>0</span>
                      )}
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center", color: item.hotspots_yesterday > 0 ? "#f97316" : "#6b7280" }}>
                      {item.hotspots_yesterday}
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center", color: item.hotspots_7d > 0 ? "#fbbf24" : "#6b7280" }}>
                      {item.hotspots_7d}
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center", color: item.hotspots_month > 0 ? "#e5e7eb" : "#6b7280" }}>
                      {item.hotspots_month}
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "right", fontWeight: "700", color: item.ftri_score >= 60 ? "#ef4444" : item.ftri_score >= 40 ? "#f97316" : "#22c55e" }}>
                      {item.ftri_score.toFixed(1)}
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center" }}>
                      <span
                        style={{
                          padding: "0.2rem 0.55rem",
                          borderRadius: "4px",
                          fontSize: "0.7rem",
                          fontWeight: "600",
                          backgroundColor: item.zone_code === "zone1" || item.zone_code === "strict" || item.zone_code === "combo"
                            ? "rgba(239,68,68,0.15)"
                            : item.zone_code === "zone2" || item.status_label.includes("⚠️") || item.status_label.includes("🟠")
                            ? "rgba(249,115,22,0.15)"
                            : item.zone_code === "zone3" || item.status_label.includes("🟡")
                            ? "rgba(234,179,8,0.15)"
                            : "rgba(34,197,94,0.15)",
                          color: item.zone_code === "zone1" || item.zone_code === "strict" || item.zone_code === "combo"
                            ? "#ef4444"
                            : item.zone_code === "zone2" || item.status_label.includes("⚠️") || item.status_label.includes("🟠")
                            ? "#f97316"
                            : item.zone_code === "zone3" || item.status_label.includes("🟡")
                            ? "#eab308"
                            : "#22c55e"
                        }}
                      >
                        {item.status_label}
                      </span>
                    </td>
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center" }}>
                      {onOpenKpsDetail ? (
                        <button
                          type="button"
                          onClick={() => onOpenKpsDetail(item.lembaga)}
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "0.2rem",
                            backgroundColor: "rgba(255,255,255,0.08)",
                            color: "#60a5fa",
                            border: "none",
                            borderRadius: "4px",
                            padding: "0.3rem 0.55rem",
                            fontSize: "0.72rem",
                            cursor: "pointer"
                          }}
                        >
                          Detail <ChevronRight size={12} />
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
