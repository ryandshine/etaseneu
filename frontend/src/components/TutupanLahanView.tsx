import { useEffect, useMemo, useState } from "react";

import { authFetch } from "../lib/api";
import { useIsMobile } from "../hooks/useIsMobile";
import { LandCoverPanel } from "./LandCoverPanel";

type LandCoverStatus = "pending" | "running" | "done" | "error" | null;

type LandCoverPolygonRow = {
  polygon_metadata_id: number;
  layer_key: string;
  lembaga: string | null;
  nama_prov: string | null;
  nama_kab: string | null;
  nama_kec: string | null;
  skema: string | null;
  wilker_bps: string | null;
  luas_final: number | null;
  land_cover_status: LandCoverStatus;
  land_cover_computed_at: string | null;
};

// Bucket status buat filter -- "idle" menampung null & "pending" sekaligus
// (keduanya artinya "belum ada hasil"), jadi user tidak perlu tahu bedanya.
type StatusFilterValue = "" | "idle" | "running" | "done" | "error";

const STATUS_FILTER_OPTIONS: ReadonlyArray<{ value: StatusFilterValue; label: string }> = [
  { value: "", label: "Semua" },
  { value: "idle", label: "Belum dianalisis" },
  { value: "running", label: "Sedang diproses" },
  { value: "done", label: "Sudah dianalisis" },
  { value: "error", label: "Gagal" },
];

function statusBucket(status: LandCoverStatus): Exclude<StatusFilterValue, ""> {
  if (status === "done") return "done";
  if (status === "running") return "running";
  if (status === "error") return "error";
  return "idle";
}

type TutupanLahanViewProps = {
  /** Preseleksi dari tautan `?view=landcover&polygon=<id>` (baris ringkas di
   *  Detail KPS). Cuma dipakai sebagai nilai awal -- komponen ini remount
   *  tiap kali activeView berpindah ke "landcover", jadi tidak perlu efek
   *  sinkronisasi tambahan. */
  initialPolygonId?: number | null;
  onOpenKpsDetail?: (agency: string) => void;
};

// Cuma 2 layer aktif saat ini (lihat CLAUDE.md, bagian "Model data poligon").
// Pemetaan manual di sini -- kalau nanti ada layer ketiga, tambahkan cabangnya.
function layerLabel(layerKey: string): string {
  return layerKey === "HUTAN_ADAT_APR26" ? "Hutan Adat" : "KPS";
}

function statusBadge(status: LandCoverStatus): { label: string; className: string } {
  switch (status) {
    case "done":
      return { label: "Sudah dianalisis", className: "tl-badge tl-badge--done" };
    case "running":
      return { label: "Sedang diproses", className: "tl-badge tl-badge--running" };
    case "error":
      return { label: "Gagal", className: "tl-badge tl-badge--error" };
    default:
      return { label: "Belum dianalisis", className: "tl-badge tl-badge--idle" };
  }
}

function formatComputedAt(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
}

export function TutupanLahanView({
  initialPolygonId = null,
  onOpenKpsDetail,
}: TutupanLahanViewProps): JSX.Element {
  const [rows, setRows] = useState<LandCoverPolygonRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [provinceFilter, setProvinceFilter] = useState("");
  const [kabupatenFilter, setKabupatenFilter] = useState("");
  const [wilkerFilter, setWilkerFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilterValue>("");
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(initialPolygonId);
  const isMobile = useIsMobile();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    authFetch("/api/land-cover/polygons")
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as LandCoverPolygonRow[];
      })
      .then((data) => {
        if (!cancelled) setRows(data);
      })
      .catch(() => {
        if (!cancelled) setError("Gagal memuat daftar poligon. Coba lagi.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const provinceOptions = useMemo(() => {
    const set = new Set(
      rows.map((r) => r.nama_prov).filter((v): v is string => Boolean(v && v.trim())),
    );
    return Array.from(set).sort();
  }, [rows]);

  const kabupatenOptions = useMemo(() => {
    const scoped = provinceFilter ? rows.filter((r) => r.nama_prov === provinceFilter) : rows;
    const set = new Set(
      scoped.map((r) => r.nama_kab).filter((v): v is string => Boolean(v && v.trim())),
    );
    return Array.from(set).sort();
  }, [rows, provinceFilter]);

  // Kabupaten terpilih bisa jadi tidak lagi cocok kalau provinsi diganti.
  useEffect(() => {
    if (kabupatenFilter && !kabupatenOptions.includes(kabupatenFilter)) {
      setKabupatenFilter("");
    }
  }, [kabupatenOptions, kabupatenFilter]);

  const wilkerOptions = useMemo(() => {
    const scoped = rows.filter(
      (r) =>
        (!provinceFilter || r.nama_prov === provinceFilter) &&
        (!kabupatenFilter || r.nama_kab === kabupatenFilter),
    );
    const set = new Set(
      scoped.map((r) => r.wilker_bps).filter((v): v is string => Boolean(v && v.trim())),
    );
    return Array.from(set).sort();
  }, [rows, provinceFilter, kabupatenFilter]);

  useEffect(() => {
    if (wilkerFilter && !wilkerOptions.includes(wilkerFilter)) {
      setWilkerFilter("");
    }
  }, [wilkerOptions, wilkerFilter]);

  const filteredRows = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return rows.filter((r) => {
      if (provinceFilter && r.nama_prov !== provinceFilter) return false;
      if (kabupatenFilter && r.nama_kab !== kabupatenFilter) return false;
      if (wilkerFilter && r.wilker_bps !== wilkerFilter) return false;
      if (statusFilter && statusBucket(r.land_cover_status) !== statusFilter) return false;
      if (query) {
        const haystack = `${r.lembaga ?? ""} ${r.nama_prov ?? ""} ${r.nama_kab ?? ""}`.toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }, [rows, provinceFilter, kabupatenFilter, wilkerFilter, statusFilter, searchQuery]);

  const analyzedCount = useMemo(
    () => rows.filter((r) => r.land_cover_status === "done").length,
    [rows],
  );

  const selectedRow = useMemo(
    () => rows.find((r) => r.polygon_metadata_id === selectedId) ?? null,
    [rows, selectedId],
  );

  // Filter aktif sebagai pill yang bisa dilepas satu-satu, tanpa perlu buka
  // popover -- popovernya sendiri cuma tempat MENGUBAH pilihan.
  const activePills = useMemo(() => {
    const pills: Array<{ key: string; label: string; clear: () => void }> = [];
    if (provinceFilter) pills.push({ key: "prov", label: provinceFilter, clear: () => setProvinceFilter("") });
    if (kabupatenFilter) pills.push({ key: "kab", label: kabupatenFilter, clear: () => setKabupatenFilter("") });
    if (wilkerFilter) pills.push({ key: "wilker", label: wilkerFilter, clear: () => setWilkerFilter("") });
    if (statusFilter) {
      const label = STATUS_FILTER_OPTIONS.find((o) => o.value === statusFilter)?.label ?? statusFilter;
      pills.push({ key: "status", label, clear: () => setStatusFilter("") });
    }
    return pills;
  }, [provinceFilter, kabupatenFilter, wilkerFilter, statusFilter]);

  // Mobile: daftar dan detail bergantian tampil (bukan ditumpuk) supaya
  // sekali pilih poligon tidak perlu menggulir lewat ratusan baris untuk
  // sampai ke panel tutupan lahan. Desktop selalu menampilkan keduanya.
  const showList = !isMobile || selectedId === null;
  const showDetail = !isMobile || selectedId !== null;

  return (
    <section className="tl-shell" aria-label="Tutupan Lahan">
      <header className="tl-topbar">
        <div className="tl-topbar-row">
          <h2>Tutupan Lahan</h2>
          <span className="tl-summary">
            {loading ? (
              "Memuat…"
            ) : (
              <>
                <strong>{analyzedCount}</strong> dari <strong>{rows.length}</strong> poligon telah
                dianalisis
              </>
            )}
          </span>
        </div>
        <p className="tl-lede">
          Klasifikasi Sentinel-2 + Random Forest per poligon KPS/Hutan Adat, 2021–2025. Analisis
          dijalankan manual satu per satu — pilih poligon di bawah untuk mulai atau melihat
          hasilnya.
        </p>
      </header>

      {error ? (
        <p className="tl-alert" role="alert">
          {error}
        </p>
      ) : null}

      <div className="tl-body">
        {showList && (
          <div className="tl-list">
            <div className="tl-list-head">
              <div className="ledger-search">
                <svg
                  className="ledger-search__icon"
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  aria-hidden="true"
                >
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.35-4.35" />
                </svg>
                <input
                  type="text"
                  className="ledger-search__input"
                  aria-label="Cari KPS/Hutan Adat"
                  placeholder="Cari nama KPS/Hutan Adat…"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      setSearchQuery(searchInput);
                    } else if (e.key === "Escape") {
                      setSearchInput("");
                      setSearchQuery("");
                    }
                  }}
                />
                {searchInput && (
                  <button
                    type="button"
                    className="ledger-search__clear"
                    onClick={() => {
                      setSearchInput("");
                      setSearchQuery("");
                    }}
                    aria-label="Bersihkan pencarian"
                    title="Bersihkan pencarian"
                  >
                    ✕
                  </button>
                )}
                <button
                  type="button"
                  className="ledger-search__submit"
                  onClick={() => setSearchQuery(searchInput)}
                >
                  Cari
                </button>
              </div>

              <div className="tl-filterbar">
                <button
                  type="button"
                  className="tl-filter-toggle"
                  aria-expanded={filterOpen}
                  onClick={() => setFilterOpen((o) => !o)}
                >
                  Filter
                  {activePills.length > 0 && (
                    <span className="tl-filter-badge">{activePills.length}</span>
                  )}
                </button>

                {activePills.length > 0 && (
                  <div className="tl-filter-pills">
                    {activePills.map((p) => (
                      <button
                        key={p.key}
                        type="button"
                        className="tl-filter-pill"
                        onClick={p.clear}
                        aria-label={`Hapus filter ${p.label}`}
                      >
                        {p.label} <span aria-hidden>✕</span>
                      </button>
                    ))}
                  </div>
                )}

                {filterOpen && (
                  <>
                    <div className="tl-filter-backdrop" onClick={() => setFilterOpen(false)} />
                    <div className="tl-filter-popover">
                      <label className="matrix-field">
                        <span>Provinsi</span>
                        <select
                          value={provinceFilter}
                          onChange={(e) => setProvinceFilter(e.currentTarget.value)}
                        >
                          <option value="">Semua</option>
                          {provinceOptions.map((p) => (
                            <option key={p} value={p}>
                              {p}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="matrix-field">
                        <span>Kabupaten</span>
                        <select
                          value={kabupatenFilter}
                          onChange={(e) => setKabupatenFilter(e.currentTarget.value)}
                        >
                          <option value="">Semua</option>
                          {kabupatenOptions.map((k) => (
                            <option key={k} value={k}>
                              {k}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="matrix-field">
                        <span>Wilker BPS</span>
                        <select
                          value={wilkerFilter}
                          onChange={(e) => setWilkerFilter(e.currentTarget.value)}
                        >
                          <option value="">Semua</option>
                          {wilkerOptions.map((w) => (
                            <option key={w} value={w}>
                              {w}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="matrix-field">
                        <span>Status</span>
                        <select
                          value={statusFilter}
                          onChange={(e) => setStatusFilter(e.currentTarget.value as StatusFilterValue)}
                        >
                          {STATUS_FILTER_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                  </>
                )}
              </div>
              {filteredRows.length !== rows.length && (
                <p className="tl-filter-count">
                  Menampilkan {filteredRows.length} dari {rows.length} poligon
                </p>
              )}
            </div>

            <div className="tl-list-scroll">
              {loading ? (
                <p className="tl-empty">Memuat daftar poligon…</p>
              ) : filteredRows.length === 0 ? (
                <p className="tl-empty">Tidak ada poligon yang cocok.</p>
              ) : (
                filteredRows.map((row) => {
                  const badge = statusBadge(row.land_cover_status);
                  const active = row.polygon_metadata_id === selectedId;
                  return (
                    <div
                      key={row.polygon_metadata_id}
                      role="button"
                      tabIndex={0}
                      className={`tl-row${active ? " tl-row--active" : ""}`}
                      onClick={() => setSelectedId(row.polygon_metadata_id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedId(row.polygon_metadata_id);
                        }
                      }}
                    >
                      <span className="tl-row-name">{row.lembaga || "(tanpa nama)"}</span>
                      <div className="tl-row-meta">
                        <span className="tl-row-layer">{layerLabel(row.layer_key)}</span>
                        <span>{[row.nama_kab, row.nama_prov].filter(Boolean).join(", ") || "-"}</span>
                      </div>
                      <span className={badge.className}>
                        <span className="tl-badge__dot" aria-hidden />
                        {badge.label}
                        {row.land_cover_status === "done" && row.land_cover_computed_at
                          ? ` · ${formatComputedAt(row.land_cover_computed_at)}`
                          : ""}
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {showDetail && (
          <div className="tl-detail">
            {selectedId === null ? (
              <p className="tl-empty tl-empty--detail">
                Pilih satu poligon di daftar untuk melihat atau menjalankan analisis tutupan
                lahannya.
              </p>
            ) : loading ? (
              <p className="tl-empty tl-empty--detail">Memuat…</p>
            ) : !selectedRow ? (
              <p className="tl-empty tl-empty--detail">
                Poligon tidak ditemukan atau sudah tidak aktif.
              </p>
            ) : (
              <>
                {isMobile && (
                  <button
                    type="button"
                    className="tl-back-btn"
                    onClick={() => setSelectedId(null)}
                  >
                    ← Kembali ke daftar
                  </button>
                )}
                <div className="tl-detail-head">
                  <div>
                    <h3>{selectedRow.lembaga || "(tanpa nama)"}</h3>
                    <p className="tl-detail-meta">
                      {layerLabel(selectedRow.layer_key)} ·{" "}
                      {[selectedRow.nama_kab, selectedRow.nama_prov].filter(Boolean).join(", ") ||
                        "-"}
                    </p>
                  </div>
                  {onOpenKpsDetail && selectedRow.lembaga ? (
                    <button
                      type="button"
                      className="tl-detail-link"
                      onClick={() => onOpenKpsDetail(selectedRow.lembaga as string)}
                    >
                      Lihat Detail KPS →
                    </button>
                  ) : null}
                </div>
                <LandCoverPanel polygonId={selectedRow.polygon_metadata_id} />
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
