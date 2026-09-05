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
  Wind,
  Lock
} from "lucide-react";
import { authFetch, downloadWithAuth } from "../lib/api";
import type { AppSession } from "../types/api";

// Riwayat singkat kartu KPI Peringatan Dini (semua 2026-09-05, iteratif
// atas masukan user):
//  v1: 4 kartu + 5 tab -> v2: 5 kartu berbasis RENTANG WAKTU, tiap kartu
//      gabungan KPS ber-rekap & belum-rekap (buang sumbu "status rekap"
//      yang dulu jadi 3 dari 5 kartu -> pindah jadi badge kolom tabel).
//  v3 (sekarang): 5 kartu waktu terasa redundan -> 3 kartu berdasar STATUS
//      HOTSPOT PER HARI INI (bukan "api" -- 1 titik panas belum tentu
//      kebakaran), PARTISI PERSIS (today + receding + inactive = total):
//        today    = "Ada Hotspot Hari Ini"  (h_today > 0)
//        receding = "Hotspot Mereda"        (h_today=0 DAN (h_7d>0 ATAU h_bulan>0))
//        inactive = "Tidak Ada Hotspot"     (h_today=0 DAN h_7d=0 DAN h_bulan=0)
//      Tidak ada kartu/tautan "Total" di UI (dihapus 2026-09-05 -- redundan
//      dengan search+filter); `bucketCounts.total` tetap dihitung internal
//      untuk `receding = total - today - inactive`.
//  Pembeda "punya catatan luas terbakar resmi Kemenhut atau belum" TIDAK
//  lagi jadi kolom badge terpisah (redundan dengan kolom "Luas Terbakar
//  Tercatat" yang sudah ada -- dua-duanya dari total_burned_ha); kolom luas
//  itu sekarang menampilkan "Belum tercatat" (bukan "-") kalau 0. Di kartu
//  "Ada Hotspot Hari Ini" tetap ada rincian "N luasnya tercatat / N belum".
type TimeBucket = "today" | "receding" | "inactive" | "total";

// Tiap bucket = pasangan kategori backend (ber-rekap + belum-rekap) yang
// di-fetch lalu digabung + disaring di klien (lihat loadItems) supaya
// partisinya PERSIS: today (h_today>0) | receding (h_today=0 DAN (h_7d>0
// ATAU h_bulan>0)) | inactive (h_today=0 DAN h_7d=0 DAN h_bulan=0).
// `burned_clear_today` = semua KPS ber-rekap yang h_today=0 (superset untuk
// receding & inactive); `early_warning_all` = semua KPS belum-rekap dg
// hotspot tahun ini. Backend `burned_padam_total` sudah = h_today=0 DAN
// h_7d=0 DAN h_bulan=0 (sejajar hitungan summary).
const BUCKET_FETCH: Record<TimeBucket, Array<{ burned: string; earlyWarning: string }>> = {
  today: [{ burned: "burned_active_today", earlyWarning: "early_warning_today" }],
  receding: [{ burned: "burned_clear_today", earlyWarning: "early_warning_all" }],
  inactive: [{ burned: "burned_padam_total", earlyWarning: "early_warning_all" }],
  total: [{ burned: "all_burned", earlyWarning: "early_warning_all" }]
};

// Keterangan per baris untuk KPS yang TIDAK ada hotspot hari ini (kartu
// "Hotspot Mereda" & "Tidak Ada Hotspot").
// Menjelaskan KENAPA KPS itu masuk kartu tsb: berapa lama sejak titik panas
// terakhir. Untuk baris yang ADA hotspot hari ini, kolom tetap pakai
// status_label backend (info Zona Perambatan) -- lihat render tabel.
function describeLastDetection(latestIso: string | null): { text: string; color: string } {
  if (!latestIso) return { text: "Belum ada catatan hotspot 2026", color: "#6b7280" };
  const days = Math.floor((Date.now() - new Date(latestIso).getTime()) / 86_400_000);
  if (days <= 0) return { text: "Hotspot terakhir: hari ini", color: "#f97316" };
  if (days === 1) return { text: "🟠 Mereda — hotspot terakhir kemarin", color: "#f97316" };
  if (days <= 7) return { text: `🟠 Mereda — hotspot terakhir ${days} hari lalu`, color: "#eab308" };
  if (days <= 45) return { text: `⚪ Tidak aktif — hotspot terakhir ${days} hari lalu`, color: "#9ca3af" };
  const d = new Date(latestIso).toLocaleString("id-ID", { month: "short", year: "numeric", timeZone: "Asia/Jakarta" });
  return { text: `⚪ Tidak aktif — hotspot terakhir ${d}`, color: "#9ca3af" };
}

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
    truly_inactive: number;
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
  frp_max_7d: number | null;
  detected_days_7d: number;
  satellites_7d: number;
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
  const [bucket, setBucket] = useState<TimeBucket>("today");
  const [summary, setSummary] = useState<SummaryMetrics | null>(null);
  const [items, setItems] = useState<KpsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingItems, setLoadingItems] = useState(false);
  const [downloading, setDownloading] = useState(false);
  // Info sinkronisasi NASA FIRMS untuk banner sumber data (menegaskan ini
  // data resmi near-real-time, bukan tebakan model).
  const [syncInfo, setSyncInfo] = useState<{ lastSuccessAt: string | null; hotspotCount: number } | null>(null);

  // Active wilker for BPS role
  const activeWilkerBps = useMemo(() => {
    if (session?.role === "bps" && session.wilker_bps) {
      return session.wilker_bps;
    }
    return selectedWilker || "";
  }, [session, selectedWilker]);

  // Nama bulan berjalan (WIB), untuk label kolom "HS <bulan>" -- ikut
  // DATE_TRUNC('month', NOW()) di backend, otomatis ganti tiap ganti bulan.
  const namaBulanIni = useMemo(
    () => new Date().toLocaleString("id-ID", { month: "long", timeZone: "Asia/Jakarta" }),
    []
  );

  // Cap "status per <kapan>" di atas 3 kartu -- menegaskan angka kartu itu
  // POTRET hari ini, bukan akumulasi historis. Pakai waktu klien (WIB) =
  // saat user melihat; data list di-refetch tiap ganti bucket/filter.
  const snapshotLabel = useMemo(
    () =>
      new Date().toLocaleString("id-ID", {
        weekday: "long", day: "numeric", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta"
      }) + " WIB",
    []
  );

  // Filters
  const [search, setSearch] = useState("");
  const [selectedProvince, setSelectedProvince] = useState("");
  const [selectedSkema, setSelectedSkema] = useState("");
  const [selectedBps, setSelectedBps] = useState("");
  const [selectedZone, setSelectedZone] = useState("");
  const [sortBy, setSortBy] = useState<"ftri" | "hs_today" | "distance" | "hs_strict" | "burned_ha" | "hs_7d" | "frp">("ftri");

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

  // Status sinkronisasi NASA FIRMS -- best-effort, kegagalan tidak menghalangi
  // apa pun (banner-nya sekadar menyembunyikan bagian "sinkron terakhir").
  const loadSyncInfo = async () => {
    try {
      const res = await authFetch(`/api/scheduler/metrics`);
      if (!res.ok) return;
      const m = await res.json();
      setSyncInfo({
        lastSuccessAt: m.last_successful_sync_at ?? m.last_sync_at ?? null,
        hotspotCount: m.last_sync_hotspot_count ?? 0
      });
    } catch {
      /* diamkan -- banner sumber data tetap tampil tanpa timestamp */
    }
  };

  // Fetch list items -- tiap bucket = 1 atau 2 pasang kategori backend
  // (ber-rekap + belum-rekap), semua di-fetch paralel lalu digabung jadi
  // satu daftar. Selalu menampilkan KEDUA kelompok KPS bersama (keluhan awal
  // soal "peringatan dini melulu yang pernah punya luas kebakaran").
  const currentCategories = useMemo(
    () => BUCKET_FETCH[bucket].flatMap((p) => [p.burned, p.earlyWarning]),
    [bucket]
  );

  const buildListQuery = (cat: string) => {
    const query = new URLSearchParams({ category: cat, limit: "1500" });
    if (activeWilkerBps) query.append("wilker_bps", activeWilkerBps);
    if (selectedProvince) query.append("province", selectedProvince);
    if (selectedSkema) query.append("skema", selectedSkema);
    if (search) query.append("search", search);
    return query.toString();
  };

  const fetchCategory = async (cat: string): Promise<KpsItem[]> => {
    const res = await authFetch(`/api/early-warning/list?${buildListQuery(cat)}`);
    if (!res.ok) throw new Error("Gagal memuat daftar KPS");
    const data = await res.json();
    return data.items || [];
  };

  const loadItems = async () => {
    try {
      setLoadingItems(true);
      const results = await Promise.all(currentCategories.map(fetchCategory));
      let merged = results.flat();

      // Saring ke partisi PERSIS (lihat komentar BUCKET_FETCH). `burned_*`
      // sudah tersaring server-side; `early_warning_all` datang penuh jadi
      // filter ini yang mempersempit. Aman diterapkan ke semua baris.
      if (bucket === "inactive") {
        merged = merged.filter(
          (i) => i.hotspots_today === 0 && i.hotspots_7d === 0 && i.hotspots_month === 0
        );
      } else if (bucket === "receding") {
        merged = merged.filter(
          (i) => i.hotspots_today === 0 && (i.hotspots_7d > 0 || i.hotspots_month > 0)
        );
      }

      // Dedup by id (aman kalau nanti ada kategori yang tumpang tindih).
      const seen = new Set<number>();
      setItems(merged.filter((i) => (seen.has(i.id) ? false : (seen.add(i.id), true))));
    } catch (err: any) {
      console.error(err);
    } finally {
      setLoadingItems(false);
    }
  };

  useEffect(() => {
    loadSummary();
    loadSyncInfo();
  }, [activeWilkerBps]);

  useEffect(() => {
    loadItems();
  }, [bucket, activeWilkerBps, selectedProvince, selectedSkema]);

  // Jumlah gabungan (ber-rekap + belum-rekap) per bucket, dihitung dari
  // `summary` -- PARTISI PERSIS: today + receding + inactive = total.
  //  today    = h_today>0
  //  inactive = h_today=0 DAN h_7d=0 DAN h_bulan=0
  //             = burned.padam_total (sudah kondisi lengkap) + ew.truly_inactive
  //  receding = sisanya (h_today=0, tapi ada di 7 hari ATAU bulan berjalan)
  //             = (burned.clear_today - burned.padam_total)
  //               + (ew.total_kps - ew.active_today - ew.truly_inactive)
  const bucketCounts = useMemo(() => {
    if (!summary) return null;
    const ew = summary.early_warning_stats;
    const burned = summary.burned_area_stats;
    const today = burned.active_today + ew.active_today;
    const inactive = burned.padam_total + ew.truly_inactive;
    const total = burned.total_polygons + ew.total_kps;
    const yesterday = burned.active_yesterday + ew.active_yesterday; // "baru reda kemarin" -- sub-teks
    return {
      today,
      yesterday,
      receding: Math.max(0, total - today - inactive),
      inactive,
      total
    };
  }, [summary]);

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

  const wilkers = useMemo(() => {
    const set = new Set<string>();
    items.forEach((i) => {
      if (i.wilker_bps) set.add(i.wilker_bps);
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

    if (selectedBps) {
      result = result.filter((i) => i.wilker_bps === selectedBps);
    }

    result.sort((a, b) => {
      if (sortBy === "ftri") return b.ftri_score - a.ftri_score;
      if (sortBy === "hs_today") return b.hotspots_today - a.hotspots_today;
      if (sortBy === "distance") return (b.max_distance_km || 0) - (a.max_distance_km || 0);
      if (sortBy === "hs_strict") return b.hotspots_today_strict_reburn - a.hotspots_today_strict_reburn;
      if (sortBy === "hs_7d") return b.hotspots_7d - a.hotspots_7d;
      if (sortBy === "frp") return (b.frp_max_7d || 0) - (a.frp_max_7d || 0);
      if (sortBy === "burned_ha") return b.total_burned_ha - a.total_burned_ha;
      return 0;
    });

    return result;
  }, [items, search, selectedZone, selectedBps, sortBy]);

  // Endpoint ekspor backend cuma terima SATU kategori sekaligus -- bucket
  // aksi bisa memetakan ke 2 kategori (ber-rekap + belum-rekap) atau 4
  // (bucket "receding" = kemarin + 7 hari), jadi unduh satu file per
  // kategori berurutan supaya semua kelompok tetap lengkap.
  const handleDownloadExcel = async () => {
    try {
      setDownloading(true);
      const wilkerQuery = activeWilkerBps ? `&wilker_bps=${encodeURIComponent(activeWilkerBps)}` : "";
      const wilkerFile = activeWilkerBps ? `-${activeWilkerBps.replace(/\s+/g, "_")}` : "";
      const dateSuffix = new Date().toISOString().slice(0, 10);

      for (const cat of currentCategories) {
        await downloadWithAuth(
          `/api/early-warning/export.xlsx?category=${cat}${wilkerQuery}`,
          `rekap-analisis-kps-${cat}${wilkerFile}-${dateSuffix}.xlsx`
        );
      }
    } catch (err: any) {
      alert("Gagal mengunduh Excel: " + err.message);
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div style={{ padding: "1.25rem", color: "#f3f4f6", height: "100%", overflowY: "auto" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem", flexWrap: "wrap", gap: "1rem" }}>
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
            {downloading ? "Mengunduh..." : `Download Excel (${currentCategories.length} file)`}
          </button>

          <button
            type="button"
            onClick={() => {
              loadSummary();
              loadItems();
              loadSyncInfo();
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
      <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", backgroundColor: "rgba(30, 41, 59, 0.6)", border: "1px solid rgba(255,255,255,0.08)", padding: "0.5rem 0.8rem", borderRadius: "6px", marginBottom: "0.9rem", fontSize: "0.75rem", color: "#cbd5e1", flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <Wind size={15} color="#38bdf8" />
          <strong>Pedoman Zona & Arah Perambatan:</strong>
        </div>
        <span>
          <span style={{ color: "#ef4444", fontWeight: "600" }}>🔴 Zona 1 (&le;1.0 km)</span> = Merambat Langsung | <span style={{ color: "#f97316", fontWeight: "600" }}>🟠 Zona 2 (1.0 - 3.0 km)</span> = Loncatan Bara | <span style={{ color: "#eab308", fontWeight: "600" }}>🟡 Zona 3 (&gt;3.0 km)</span> = Titik Bakar Mandiri.
        </span>
      </div>

      {/* KPI Cards -- 2026-09-05: 3 kartu berbasis STATUS HOTSPOT PER HARI INI
          (Ada Hotspot Hari Ini / Hotspot Mereda / Tidak Ada Hotspot). Ketiganya
          POTRET per tanggal sekarang -- tiap KPS masuk TEPAT SATU kartu
          (189+498+1188 = 1875 total), berdasarkan kapan titik panas terakhir
          terdeteksi di dalamnya. */}
      {summary && bucketCounts && (
        <>
          <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginBottom: "0.5rem", lineHeight: 1.5 }}>
            📅 Status per <strong>{snapshotLabel}</strong>
            {syncInfo?.lastSuccessAt ? (
              <>
                {" · data NASA FIRMS sinkron terakhir "}
                <strong>
                  {new Date(syncInfo.lastSuccessAt).toLocaleString("id-ID", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta" })} WIB
                </strong>
              </>
            ) : null}
            <br />
            Tiap KPS masuk <strong>tepat satu</strong> kategori di bawah, berdasarkan kapan titik panas terakhir terdeteksi.
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "0.75rem", marginBottom: "0.55rem" }}>
            {/* REAKSI CEPAT */}
            <div
              onClick={() => setBucket("today")}
              style={{
                backgroundColor: bucket === "today" ? "rgba(239, 68, 68, 0.2)" : "rgba(239, 68, 68, 0.06)",
                border: `1px solid ${bucket === "today" ? "#ef4444" : "rgba(239,68,68,0.35)"}`,
                borderRadius: "8px", padding: "0.85rem", cursor: "pointer", transition: "all 0.2s ease",
                display: "flex", flexDirection: "column", height: "100%"
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.15rem" }}>
                <span style={{ fontSize: "0.8rem", fontWeight: "800", color: "#ef4444", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  🔴 Ada Hotspot Hari Ini
                </span>
                <AlertTriangle size={16} color="#ef4444" />
              </div>
              <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginBottom: "0.4rem" }}>Titik panas terdeteksi hari ini — perlu verifikasi lapangan & regu siaga</div>
              <div style={{ fontSize: "1.7rem", fontWeight: "800", color: "#ffffff", lineHeight: 1 }}>
                {bucketCounts.today} <span style={{ fontSize: "0.85rem", fontWeight: "normal", color: "#9ca3af" }}>KPS</span>
              </div>
              <div style={{ display: "flex", gap: "0.4rem", marginTop: "auto", paddingTop: "0.6rem", flexWrap: "wrap", fontSize: "0.7rem" }}>
                <span style={{ backgroundColor: "rgba(34,197,94,0.2)", color: "#4ade80", padding: "0.15rem 0.4rem", borderRadius: "4px" }}>
                  🟢 {summary.burned_area_stats.active_today} luasnya sudah tercatat
                </span>
                <span style={{ backgroundColor: "rgba(249,115,22,0.2)", color: "#fdba74", padding: "0.15rem 0.4rem", borderRadius: "4px" }}>
                  🟠 {summary.early_warning_stats.active_today} belum tercatat
                </span>
              </div>
            </div>

            {/* PANTAU KETAT */}
            <div
              onClick={() => setBucket("receding")}
              style={{
                backgroundColor: bucket === "receding" ? "rgba(234, 179, 8, 0.18)" : "rgba(255,255,255,0.04)",
                border: `1px solid ${bucket === "receding" ? "#eab308" : "rgba(255,255,255,0.08)"}`,
                borderRadius: "8px", padding: "0.85rem", cursor: "pointer", transition: "all 0.2s ease",
                display: "flex", flexDirection: "column", height: "100%"
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.15rem" }}>
                <span style={{ fontSize: "0.8rem", fontWeight: "800", color: "#eab308", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  🟡 Hotspot Mereda
                </span>
                <TrendingUp size={16} color="#eab308" />
              </div>
              <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginBottom: "0.4rem" }}>Tidak ada titik hari ini, tapi ada dalam 7 hari terakhir atau bulan {namaBulanIni} — bisa muncul lagi</div>
              <div style={{ fontSize: "1.7rem", fontWeight: "800", color: "#ffffff", lineHeight: 1 }}>
                {bucketCounts.receding} <span style={{ fontSize: "0.85rem", fontWeight: "normal", color: "#9ca3af" }}>KPS</span>
              </div>
              <div style={{ fontSize: "0.7rem", color: "#9ca3af", marginTop: "auto", paddingTop: "0.6rem" }}>
                {bucketCounts.yesterday} baru reda kemarin · {Math.max(0, bucketCounts.receding - bucketCounts.yesterday)} lebih lama (≤7 hari / bulan ini)
              </div>
            </div>

            {/* PEMANTAUAN PASIF */}
            <div
              onClick={() => setBucket("inactive")}
              style={{
                backgroundColor: bucket === "inactive" ? "rgba(34, 197, 94, 0.18)" : "rgba(255,255,255,0.04)",
                border: `1px solid ${bucket === "inactive" ? "#22c55e" : "rgba(255,255,255,0.08)"}`,
                borderRadius: "8px", padding: "0.85rem", cursor: "pointer", transition: "all 0.2s ease",
                display: "flex", flexDirection: "column", height: "100%"
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.15rem" }}>
                <span style={{ fontSize: "0.8rem", fontWeight: "800", color: "#22c55e", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  🟢 Tidak Ada Hotspot
                </span>
                <ShieldCheck size={16} color="#22c55e" />
              </div>
              <div style={{ fontSize: "0.72rem", color: "#9ca3af", marginBottom: "0.4rem" }}>0 titik panas: hari ini, 7 hari terakhir, DAN sepanjang bulan {namaBulanIni}</div>
              <div style={{ fontSize: "1.7rem", fontWeight: "800", color: "#ffffff", lineHeight: 1 }}>
                {bucketCounts.inactive} <span style={{ fontSize: "0.85rem", fontWeight: "normal", color: "#9ca3af" }}>KPS</span>
              </div>
            </div>
          </div>
          <div style={{ marginBottom: "1rem" }} />
        </>
      )}

      {/* Search & Filter Bar */}
      <div style={{ display: "flex", gap: "0.6rem", marginBottom: "0.85rem", flexWrap: "wrap", alignItems: "center" }}>
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

        {/* Balai PS Filter -- disembunyikan untuk role "bps" (tampilannya
            sudah dikunci ke satu wilker via activeWilkerBps). */}
        {session?.role !== "bps" && (
          <select
            value={selectedBps}
            onChange={(e) => setSelectedBps(e.target.value)}
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
            <option value="">Semua Balai PS</option>
            {wilkers.map((w) => (
              <option key={w} value={w} style={{ backgroundColor: "#1e293b" }}>
                {w}
              </option>
            ))}
          </select>
        )}

        {/* Zona Perambatan Filter -- cuma relevan buat KPS ber-rekap yang
            aktif hari ini (zone_code KPS belum-rekap selalu "new_2026",
            tidak match opsi manapun di bawah). */}
        {bucket === "today" && (
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
          <option value="frp" style={{ backgroundColor: "#1e293b" }}>Urut: FRP Tertinggi (7 Hari)</option>
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
              <th style={{ padding: "0.75rem 0.8rem" }}>Wilayah & Balai PS</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "right", minWidth: "130px" }}>
                Luas Terbakar Tercatat
                <div style={{ fontSize: "0.68rem", fontWeight: "normal", color: "#6b7280" }}>[dari catatan resmi Kemenhut]</div>
              </th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center", minWidth: "180px" }}>
                Hotspot Hari Ini, Jarak & Arah
                <div style={{ fontSize: "0.68rem", fontWeight: "normal", color: "#6b7280" }}>[Total / Bekas / Jarak (km) & Arah]</div>
              </th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>HS Kemarin</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>HS 7 Hari</th>
              {/* Datanya DATE_TRUNC('month', NOW()) = bulan BERJALAN. Nama
                  bulannya di-derive dari tanggal sekarang (WIB) supaya
                  otomatis ganti tiap ganti bulan -- mis. "HS September" ->
                  "HS Oktober" tanpa ubah kode. */}
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>HS {namaBulanIni}</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "right" }}>Skor FTRI</th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center", minWidth: "150px" }}>
                Kekuatan Sinyal
                <div style={{ fontSize: "0.68rem", fontWeight: "normal", color: "#6b7280" }}>[FRP · hari/7 · satelit]</div>
              </th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center", minWidth: "170px" }}>
                Keterangan
                <div style={{ fontSize: "0.68rem", fontWeight: "normal", color: "#6b7280" }}>[zona perambatan / kapan titik terakhir]</div>
              </th>
              <th style={{ padding: "0.75rem 0.8rem", textAlign: "center" }}>Aksi</th>
            </tr>
          </thead>
          <tbody>
            {loadingItems ? (
              <tr>
                <td colSpan={13} style={{ padding: "2.5rem", textAlign: "center", color: "#9ca3af" }}>
                  <RefreshCw size={20} className="animate-spin" style={{ margin: "0 auto 0.5rem auto" }} />
                  Memuat data analisis...
                </td>
              </tr>
            ) : displayItems.length === 0 ? (
              <tr>
                <td colSpan={13} style={{ padding: "2.5rem", textAlign: "center", color: "#6b7280" }}>
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
                    {/* Balai PS (wilker_bps) disatukan di kolom wilayah --
                        sama-sama info administratif/lokasi, biar tidak nambah
                        kolom. */}
                    <td style={{ padding: "0.65rem 0.8rem" }}>
                      <div style={{ color: "#e5e7eb" }}>{item.nama_kab || "-"}</div>
                      <div style={{ fontSize: "0.7rem", color: "#9ca3af" }}>{item.nama_prov || "-"}</div>
                      <div style={{ fontSize: "0.68rem", color: "#60a5fa", marginTop: "0.15rem" }}>
                        🏛️ {item.wilker_bps || "Balai PS tidak tercatat"}
                      </div>
                    </td>
                    {/* Satu kolom ini menggantikan pasangan kolom lama
                        "Bekas Terbakar Kemenhut (Ada/Belum Ada)" + "Luas
                        Terbakar" yang isinya redundan (dua-duanya dari
                        total_burned_ha). "Belum tercatat" != belum terbakar --
                        bisa kejadian baru / rekap Kemenhut belum terbit. */}
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "right", fontWeight: "600", color: item.total_burned_ha > 0 ? "#fca5a5" : "#9ca3af" }}>
                      {item.total_burned_ha > 0
                        ? `${item.total_burned_ha.toLocaleString("id-ID", { minimumFractionDigits: 2 })} ha`
                        : <span style={{ fontWeight: "400", fontSize: "0.72rem", fontStyle: "italic" }}>Belum tercatat</span>}
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
                      {/* Kekuatan Sinyal: intensitas + konsistensi + cross-sensor.
                          Ambang FRP Tinggi/Sedang/Rendah (>30 / 10-30 / <10 MW)
                          SAMA dengan kartu statistik FRP di peta utama. */}
                      {item.frp_max_7d == null ? (
                        <span style={{ color: "#6b7280", fontSize: "0.75rem" }}>—</span>
                      ) : (
                        (() => {
                          const frp = item.frp_max_7d;
                          const lvl = frp > 30 ? "Tinggi" : frp >= 10 ? "Sedang" : "Rendah";
                          const col = frp > 30 ? "#ef4444" : frp >= 10 ? "#f97316" : "#eab308";
                          const days = Math.min(item.detected_days_7d, 7);
                          return (
                            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.15rem" }}>
                              <span style={{ fontWeight: "700", color: col, fontSize: "0.78rem" }}>
                                {frp.toLocaleString("id-ID", { maximumFractionDigits: 0 })} MW
                                <span style={{ fontSize: "0.66rem", fontWeight: "600", marginLeft: "0.25rem" }}>{lvl}</span>
                              </span>
                              <span style={{ fontSize: "0.68rem", color: "#9ca3af" }}>
                                {days}/7 hari · {item.satellites_7d} satelit
                              </span>
                            </div>
                          );
                        })()
                      )}
                    </td>
                    {/* Kolom "Keterangan": kalau ada hotspot HARI INI -> tampil
                        status_label backend (info Zona Perambatan). Kalau tidak
                        (kartu "Hotspot Mereda" / "Tidak Ada Hotspot") -> tampil
                        "kapan titik panas terakhir" -- itu yang menjelaskan
                        kenapa KPS masuk kartu yang diklik. */}
                    <td style={{ padding: "0.65rem 0.8rem", textAlign: "center" }}>
                      {item.hotspots_today > 0 ? (
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
                      ) : (
                        (() => {
                          const d = describeLastDetection(item.latest_hotspot_at);
                          return (
                            <span style={{ fontSize: "0.72rem", fontWeight: "600", color: d.color }}>{d.text}</span>
                          );
                        })()
                      )}
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
