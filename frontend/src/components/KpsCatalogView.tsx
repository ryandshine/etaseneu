import React, { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Download,
  ExternalLink,
  FileText,
  Flame,
  Layers,
  MapPin,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  TreePine,
  Users,
  X,
} from "lucide-react";
import { authFetch } from "../lib/api";
import type { KpsCatalogItem, KpsCatalogMeta, KpsCatalogResponse } from "../types/api";

type KpsCatalogViewProps = {
  onOpenKpsDetail: (agency: string, polygonId?: number) => void;
  onOpenMap?: (item: KpsCatalogItem) => void;
};

// Skema color styling helper
function getSkemaBadge(skema: string) {
  const s = (skema || "").toUpperCase();
  if (s.includes("HD") || s.includes("DESA")) {
    return { bg: "rgba(59, 130, 246, 0.18)", border: "rgba(59, 130, 246, 0.4)", text: "#93c5fd", label: "HD" };
  }
  if (s.includes("HKM")) {
    return { bg: "rgba(16, 185, 129, 0.18)", border: "rgba(16, 185, 129, 0.4)", text: "#6ee7b7", label: "HKm" };
  }
  if (s.includes("HTR")) {
    return { bg: "rgba(245, 158, 11, 0.18)", border: "rgba(245, 158, 11, 0.4)", text: "#fcd34d", label: "HTR" };
  }
  if (s.includes("ADAT")) {
    return { bg: "rgba(168, 85, 247, 0.18)", border: "rgba(168, 85, 247, 0.4)", text: "#d8b4fe", label: "Hutan Adat" };
  }
  if (s.includes("PKK") || s.includes("KEMITRAAN")) {
    return { bg: "rgba(236, 72, 153, 0.18)", border: "rgba(236, 72, 153, 0.4)", text: "#f472b6", label: "KK" };
  }
  return { bg: "rgba(156, 163, 175, 0.15)", border: "rgba(156, 163, 175, 0.3)", text: "#d1d5db", label: skema || "PS" };
}

export function KpsCatalogView({ onOpenKpsDetail, onOpenMap }: KpsCatalogViewProps) {
  // State metadata KPI & opsi filter
  const [meta, setMeta] = useState<KpsCatalogMeta | null>(null);
  const [loadingMeta, setLoadingMeta] = useState(false);

  // State filter & pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedSkema, setSelectedSkema] = useState("");
  const [selectedWilker, setSelectedWilker] = useState("");
  const [selectedProvince, setSelectedProvince] = useState("");
  const [quickFilter, setQuickFilter] = useState<"all" | "hotspot" | "burned">("all");
  const [sortBy, setSortBy] = useState("lembaga");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // State data tabel
  const [data, setData] = useState<KpsCatalogResponse | null>(null);
  const [loadingData, setLoadingData] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Expanded rows
  const [expandedIds, setExpandedIds] = useState<Record<number, boolean>>({});

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearchQuery(searchInput.trim());
      setPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // Fetch meta (KPI & filter options)
  const fetchMeta = useCallback(async (refresh = false) => {
    setLoadingMeta(true);
    try {
      const res = await authFetch(`/api/kps-catalog/meta${refresh ? "?refresh=true" : ""}`);
      if (res.ok) {
        const json: KpsCatalogMeta = await res.json();
        setMeta(json);
      }
    } catch (err) {
      console.error("Gagal memuat metadata katalog KPS:", err);
    } finally {
      setLoadingMeta(false);
    }
  }, []);

  useEffect(() => {
    fetchMeta();
  }, [fetchMeta]);

  // Fetch paginated KPS catalog data
  const fetchData = useCallback(async () => {
    setLoadingData(true);
    setErrorMsg(null);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      if (searchQuery) params.set("search", searchQuery);
      if (selectedSkema) params.set("skema", selectedSkema);
      if (selectedWilker) params.set("wilker", selectedWilker);
      if (selectedProvince) params.set("province", selectedProvince);
      if (quickFilter === "hotspot") params.set("has_hotspot_30d", "true");
      if (quickFilter === "burned") params.set("has_burned_area", "true");
      params.set("sort_by", sortBy);
      params.set("sort_dir", sortDir);

      const res = await authFetch(`/api/kps-catalog?${params.toString()}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: Gagal memuat data katalog`);
      }
      const json: KpsCatalogResponse = await res.json();
      setData(json);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Terjadi kesalahan saat memuat data katalog KPS";
      setErrorMsg(msg);
    } finally {
      setLoadingData(false);
    }
  }, [page, pageSize, searchQuery, selectedSkema, selectedWilker, selectedProvince, quickFilter, sortBy, sortDir]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Reset pagination on filter changes
  const handleSkemaChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedSkema(e.target.value);
    setPage(1);
  };
  const handleWilkerChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedWilker(e.target.value);
    setPage(1);
  };
  const handleProvinceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedProvince(e.target.value);
    setPage(1);
  };
  const handleQuickFilter = (type: "all" | "hotspot" | "burned") => {
    setQuickFilter(type);
    setPage(1);
  };

  const toggleRowExpand = (id: number) => {
    setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Export CSV
  const handleExportCsv = () => {
    const params = new URLSearchParams();
    if (searchQuery) params.set("search", searchQuery);
    if (selectedSkema) params.set("skema", selectedSkema);
    if (selectedWilker) params.set("wilker", selectedWilker);
    if (selectedProvince) params.set("province", selectedProvince);
    if (quickFilter === "hotspot") params.set("has_hotspot_30d", "true");
    if (quickFilter === "burned") params.set("has_burned_area", "true");
    window.open(`/api/kps-catalog/export?${params.toString()}`, "_blank");
  };

  const pagination = data?.pagination;
  const items = data?.items || [];
  const startRow = pagination ? (pagination.page - 1) * pagination.page_size + 1 : 0;
  const endRow = pagination ? Math.min(pagination.page * pagination.page_size, pagination.total_records) : 0;

  return (
    <div className="kps-catalog-stage">
      {/* Header Utama */}
      <header className="kps-catalog-header">
        <div className="kps-catalog-title-wrap">
          <div className="kps-catalog-badge">
            <Layers size={14} /> DIREKTORI NASIONAL
          </div>
          <h1 className="kps-catalog-title">Data KPS Nasional</h1>
          <p className="kps-catalog-subtitle">
            Direktori lengkap seluruh unit persetujuan Perhutanan Sosial (7.000+ KPS) beserta status legalitas SK, fungsi kawasan hutan, dan pantauan hotspot.
          </p>
        </div>

        <div className="kps-catalog-header-actions">
          <button
            type="button"
            className="kps-catalog-btn kps-catalog-btn--outline"
            onClick={handleExportCsv}
            title="Unduh data KPS yang sedang difilter dalam format CSV"
          >
            <Download size={15} />
            <span>Ekspor CSV</span>
          </button>
          <button
            type="button"
            className="kps-catalog-btn kps-catalog-btn--ghost"
            onClick={() => {
              fetchMeta(true);
              fetchData();
            }}
            title="Muat ulang data"
          >
            <RefreshCw size={15} className={loadingData || loadingMeta ? "spin" : ""} />
            <span>Segarkan</span>
          </button>
        </div>
      </header>

      {/* KPI Cards Ringkasan */}
      <div className="kps-catalog-kpi-grid">
        <div className="kps-kpi-card">
          <div className="kps-kpi-icon" style={{ backgroundColor: "rgba(59, 130, 246, 0.15)", color: "#60a5fa" }}>
            <TreePine size={20} />
          </div>
          <div className="kps-kpi-body">
            <span className="kps-kpi-label">TOTAL KPS</span>
            <strong className="kps-kpi-val">
              {meta ? meta.summary.total_kps.toLocaleString("id-ID") : "..."}
            </strong>
            <span className="kps-kpi-sub">Unit Persetujuan Aktif</span>
          </div>
        </div>

        <div className="kps-kpi-card">
          <div className="kps-kpi-icon" style={{ backgroundColor: "rgba(16, 185, 129, 0.15)", color: "#34d399" }}>
            <Layers size={20} />
          </div>
          <div className="kps-kpi-body">
            <span className="kps-kpi-label">TOTAL LUAS SK</span>
            <strong className="kps-kpi-val">
              {meta ? `${Math.round(meta.summary.total_luas_ha).toLocaleString("id-ID")} Ha` : "..."}
            </strong>
            <span className="kps-kpi-sub">Definitif Seluruh Indonesia</span>
          </div>
        </div>

        <div className="kps-kpi-card">
          <div className="kps-kpi-icon" style={{ backgroundColor: "rgba(168, 85, 247, 0.15)", color: "#c084fc" }}>
            <MapPin size={20} />
          </div>
          <div className="kps-kpi-body">
            <span className="kps-kpi-label">SEBARAN WILAYAH</span>
            <strong className="kps-kpi-val">
              {meta ? `${meta.summary.total_balai} Balai PS` : "..."}
            </strong>
            <span className="kps-kpi-sub">
              {meta ? `${meta.summary.total_provinsi} Provinsi` : "Mencakup 38 Provinsi"}
            </span>
          </div>
        </div>

        <div className="kps-kpi-card">
          <div className="kps-kpi-icon" style={{ backgroundColor: "rgba(239, 68, 68, 0.15)", color: "#f87171" }}>
            <Flame size={20} />
          </div>
          <div className="kps-kpi-body">
            <span className="kps-kpi-label">TERDAMPAK HOTSPOT (30H)</span>
            <strong className="kps-kpi-val" style={{ color: "#f87171" }}>
              {meta ? `${meta.summary.kps_hotspot_30d.toLocaleString("id-ID")} KPS` : "..."}
            </strong>
            <span className="kps-kpi-sub">Terdeteksi NASA FIRMS</span>
          </div>
        </div>

        <div className="kps-kpi-card">
          <div className="kps-kpi-icon" style={{ backgroundColor: "rgba(245, 158, 11, 0.15)", color: "#fbbf24" }}>
            <ShieldAlert size={20} />
          </div>
          <div className="kps-kpi-body">
            <span className="kps-kpi-label">BEKAS TERBAKAR</span>
            <strong className="kps-kpi-val">
              {meta ? `${meta.summary.kps_burned.toLocaleString("id-ID")} KPS` : "..."}
            </strong>
            <span className="kps-kpi-sub">Histori Burned Area KLHK/S2</span>
          </div>
        </div>
      </div>

      {/* Toolbar Filter & Search */}
      <div className="kps-catalog-toolbar">
        <div className="kps-catalog-search-box">
          <Search size={16} className="kps-search-icon" />
          <input
            type="text"
            className="kps-search-input"
            placeholder="Cari nama lembaga/kelompok KPS, nomor SK, atau desa..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          {searchInput && (
            <button
              type="button"
              className="kps-search-clear"
              onClick={() => setSearchInput("")}
              title="Hapus pencarian"
            >
              <X size={14} />
            </button>
          )}
        </div>

        <div className="kps-catalog-filters">
          <select
            className="kps-select"
            value={selectedSkema}
            onChange={handleSkemaChange}
            aria-label="Filter Skema"
          >
            <option value="">Semua Skema</option>
            {meta?.filters.skemas.map((sk) => (
              <option key={sk} value={sk}>
                {sk}
              </option>
            ))}
          </select>

          <select
            className="kps-select"
            value={selectedWilker}
            onChange={handleWilkerChange}
            aria-label="Filter Balai PS"
          >
            <option value="">Semua Balai PS</option>
            {meta?.filters.wilkers.map((wk) => (
              <option key={wk} value={wk}>
                {wk}
              </option>
            ))}
          </select>

          <select
            className="kps-select"
            value={selectedProvince}
            onChange={handleProvinceChange}
            aria-label="Filter Provinsi"
          >
            <option value="">Semua Provinsi</option>
            {meta?.filters.provinces.map((prv) => (
              <option key={prv} value={prv}>
                {prv}
              </option>
            ))}
          </select>
        </div>

        <div className="kps-catalog-pills">
          <button
            type="button"
            className={`kps-pill${quickFilter === "all" ? " kps-pill--active" : ""}`}
            onClick={() => handleQuickFilter("all")}
          >
            Semua
          </button>
          <button
            type="button"
            className={`kps-pill${quickFilter === "hotspot" ? " kps-pill--active kps-pill--danger" : ""}`}
            onClick={() => handleQuickFilter("hotspot")}
          >
            <Flame size={12} />
            Ada Hotspot (30H)
          </button>
          <button
            type="button"
            className={`kps-pill${quickFilter === "burned" ? " kps-pill--active kps-pill--warning" : ""}`}
            onClick={() => handleQuickFilter("burned")}
          >
            <ShieldAlert size={12} />
            Pernah Terbakar
          </button>
        </div>
      </div>

      {/* Main Data Table */}
      <div className="kps-catalog-table-container">
        {errorMsg ? (
          <div className="kps-catalog-state kps-catalog-state--error">
            <ShieldAlert size={32} />
            <p>{errorMsg}</p>
            <button type="button" className="kps-catalog-btn" onClick={fetchData}>
              Coba Lagi
            </button>
          </div>
        ) : loadingData ? (
          <div className="kps-catalog-state kps-catalog-state--loading">
            <RefreshCw size={28} className="spin" />
            <p>Memuat direktori data KPS...</p>
          </div>
        ) : items.length === 0 ? (
          <div className="kps-catalog-state kps-catalog-state--empty">
            <Layers size={32} />
            <p>Tidak ada data KPS yang sesuai dengan filter pencarian.</p>
          </div>
        ) : (
          <table className="kps-table">
            <thead>
              <tr>
                <th style={{ width: "45px", textAlign: "center" }}>No</th>
                <th>Nama Lembaga / Kelompok KPS</th>
                <th style={{ width: "90px", textAlign: "center" }}>Skema</th>
                <th>Lokasi Administratif</th>
                <th>Balai PS</th>
                <th style={{ textAlign: "right" }}>Luas SK (Ha)</th>
                <th style={{ textAlign: "center", width: "130px" }}>Hotspot (30H)</th>
                <th style={{ textAlign: "center", width: "190px" }}>Aksi</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => {
                const rowNo = startRow + idx;
                const isExpanded = !!expandedIds[item.id];
                const badge = getSkemaBadge(item.skema);
                const hasHs = item.hotspot_count_30d > 0;

                return (
                  <React.Fragment key={item.id}>
                    <tr
                      className={`kps-table-row${isExpanded ? " kps-table-row--expanded" : ""}`}
                      onClick={() => toggleRowExpand(item.id)}
                    >
                      <td style={{ textAlign: "center", color: "#9ca3af" }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "4px" }}>
                          {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          <span>{rowNo}</span>
                        </div>
                      </td>
                      <td>
                        <div className="kps-col-lembaga">
                          <strong className="kps-lembaga-title">{item.lembaga}</strong>
                          <span className="kps-sk-sub">
                            SK: {item.no_sk || "—"} {item.tgl_sk ? `(${item.tgl_sk})` : ""}
                          </span>
                        </div>
                      </td>
                      <td style={{ textAlign: "center" }}>
                        <span
                          className="kps-skema-badge"
                          style={{
                            backgroundColor: badge.bg,
                            borderColor: badge.border,
                            color: badge.text,
                          }}
                        >
                          {badge.label}
                        </span>
                      </td>
                      <td>
                        <div className="kps-col-loc">
                          <span className="kps-loc-main">
                            {item.nama_desa ? `Desa ${item.nama_desa}` : "—"}
                            {item.nama_kec ? `, Kec. ${item.nama_kec}` : ""}
                          </span>
                          <span className="kps-loc-sub">
                            {item.nama_kab ? `Kab. ${item.nama_kab}` : ""}
                            {item.nama_prov ? `, ${item.nama_prov}` : ""}
                          </span>
                        </div>
                      </td>
                      <td>
                        <span className="kps-col-wilker">{item.wilker_bps || "—"}</span>
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <span className="kps-luas-val">
                          {item.luas_final.toLocaleString("id-ID", { minimumFractionDigits: 1, maximumFractionDigits: 2 })}
                        </span>
                      </td>
                      <td style={{ textAlign: "center" }}>
                        {hasHs ? (
                          <span className="kps-status-pill kps-status-pill--hotspot">
                            <Flame size={12} /> {item.hotspot_count_30d} Titik
                          </span>
                        ) : (
                          <span className="kps-status-pill kps-status-pill--safe">
                            <ShieldCheck size={12} /> Aman
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: "center" }} onClick={(e) => e.stopPropagation()}>
                        <div className="kps-actions-wrap">
                          <button
                            type="button"
                            className="kps-action-btn kps-action-btn--profile"
                            onClick={() => onOpenKpsDetail(item.lembaga, item.id)}
                            title="Buka Profile KPS lengkap (legalitas, peta, cuaca, grafik)"
                          >
                            <FileText size={13} />
                            <span>Profile KPS</span>
                          </button>
                          {onOpenMap && (
                            <button
                              type="button"
                              className="kps-action-btn kps-action-btn--map"
                              onClick={() => onOpenMap(item)}
                              title="Lihat KPS di Peta Live Map"
                            >
                              <MapPin size={13} />
                              <span>Peta</span>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Baris Rincian Terbuka (Expanded Row) */}
                    {isExpanded && (
                      <tr className="kps-table-detail-row">
                        <td colSpan={8}>
                          <div className="kps-expanded-box">
                            <div className="kps-expanded-section">
                              <span className="kps-exp-title">Fungsi Kawasan Hutan:</span>
                              <div className="kps-exp-chips">
                                <span className="kps-chip">
                                  Hutan Lindung (HL): <strong>{item.luas_hl.toLocaleString("id-ID")} Ha</strong>
                                </span>
                                <span className="kps-chip">
                                  Hutan Produksi (HP): <strong>{item.luas_hp.toLocaleString("id-ID")} Ha</strong>
                                </span>
                                <span className="kps-chip">
                                  Hutan Produksi Terbatas (HPT): <strong>{item.luas_hpt.toLocaleString("id-ID")} Ha</strong>
                                </span>
                                <span className="kps-chip">
                                  HPK: <strong>{item.luas_hpk.toLocaleString("id-ID")} Ha</strong>
                                </span>
                                <span className="kps-chip">
                                  Konservasi (HK): <strong>{item.luas_hk.toLocaleString("id-ID")} Ha</strong>
                                </span>
                              </div>
                            </div>

                            <div className="kps-expanded-section">
                              <span className="kps-exp-title">Data Sosial & Kebakaran:</span>
                              <div className="kps-exp-chips">
                                <span className="kps-chip">
                                  <Users size={13} /> Anggota: <strong>{item.jml_kk > 0 ? `${item.jml_kk} KK` : "—"}</strong>
                                </span>
                                <span className="kps-chip">
                                  <Flame size={13} /> Bekas Terbakar:{" "}
                                  <strong style={{ color: item.burned_area_ha > 0 ? "#f87171" : "inherit" }}>
                                    {item.burned_area_ha > 0 ? `${item.burned_area_ha} Ha` : "0 Ha"}
                                  </strong>
                                </span>
                                {item.last_hotspot_at && (
                                  <span className="kps-chip">
                                    Hotspot Terakhir: <strong>{item.last_hotspot_at.replace("T", " ").slice(0, 16)}</strong>
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination Bar */}
      {pagination && pagination.total_records > 0 && (
        <div className="kps-catalog-footer">
          <div className="kps-footer-info">
            Menampilkan <strong>{startRow.toLocaleString("id-ID")}</strong> – <strong>{endRow.toLocaleString("id-ID")}</strong> dari <strong>{pagination.total_records.toLocaleString("id-ID")}</strong> KPS
          </div>

          <div className="kps-footer-pagination">
            <button
              type="button"
              className="kps-page-btn"
              disabled={page <= 1 || loadingData}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              aria-label="Halaman Sebelumnya"
            >
              <ChevronLeft size={16} />
            </button>

            <span className="kps-page-indicator">
              Halaman <strong>{page}</strong> dari <strong>{pagination.total_pages}</strong>
            </span>

            <button
              type="button"
              className="kps-page-btn"
              disabled={page >= pagination.total_pages || loadingData}
              onClick={() => setPage((p) => Math.min(pagination.total_pages, p + 1))}
              aria-label="Halaman Berikutnya"
            >
              <ChevronRight size={16} />
            </button>
          </div>

          <div className="kps-footer-size">
            <span style={{ fontSize: "0.78rem", color: "#9ca3af" }}>Ukuran:</span>
            <select
              className="kps-select kps-select--sm"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              aria-label="Pilih ukuran halaman"
            >
              <option value={25}>25 per hal</option>
              <option value={50}>50 per hal</option>
              <option value={100}>100 per hal</option>
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
