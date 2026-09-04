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
  luas_final: number | null;
  land_cover_status: LandCoverStatus;
  land_cover_computed_at: string | null;
};

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

  const filteredRows = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return rows.filter((r) => {
      if (provinceFilter && r.nama_prov !== provinceFilter) return false;
      if (kabupatenFilter && r.nama_kab !== kabupatenFilter) return false;
      if (query) {
        const haystack = `${r.lembaga ?? ""} ${r.nama_prov ?? ""} ${r.nama_kab ?? ""}`.toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    });
  }, [rows, provinceFilter, kabupatenFilter, searchQuery]);

  const analyzedCount = useMemo(
    () => rows.filter((r) => r.land_cover_status === "done").length,
    [rows],
  );

  const selectedRow = useMemo(
    () => rows.find((r) => r.polygon_metadata_id === selectedId) ?? null,
    [rows, selectedId],
  );

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

              <div className="tl-filters">
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
              </div>
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
                      <div className="tl-row-body">
                        <div className="tl-row-top">
                          <span className="tl-row-name">{row.lembaga || "(tanpa nama)"}</span>
                          <span className="tl-row-layer">{layerLabel(row.layer_key)}</span>
                        </div>
                        <div className="tl-row-meta">
                          {[row.nama_kab, row.nama_prov].filter(Boolean).join(", ") || "-"}
                        </div>
                      </div>
                      <span className={badge.className}>
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
