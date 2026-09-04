import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { FilterPanel } from "./components/FilterPanel";
import { LoginPage } from "./components/LoginPage";
import { PasswordGateModal } from "./components/PasswordGateModal";
import { SidebarNav } from "./components/SidebarNav";
import { useDashboardData } from "./hooks/useDashboardData";
import { useIsDesktopWide } from "./hooks/useIsDesktopWide";
import { setAuthToken, setUnauthorizedHandler } from "./lib/api";
import { clearDashboardCache } from "./lib/dashboardPersistence";
import { getTodayWIB, formatDateTimeWIB } from "./lib/date";
import type { AppSession } from "./types/api";

const HotspotMap = lazy(async () => {
  const module = await import("./components/HotspotMap");
  return { default: module.HotspotMap };
});

const HotspotMatrix = lazy(async () => {
  const module = await import("./components/HotspotMatrix");
  return { default: module.HotspotMatrix };
});

const KpsDetailView = lazy(async () => {
  const module = await import("./components/KpsDetailView");
  return { default: module.KpsDetailView };
});

const PointMatchView = lazy(async () => {
  const module = await import("./components/PointMatchView");
  return { default: module.PointMatchView };
});

const KompleksKebakaranView = lazy(async () => {
  const module = await import("./components/KompleksKebakaranView");
  return { default: module.KompleksKebakaranView };
});

const TutupanLahanView = lazy(async () => {
  const module = await import("./components/TutupanLahanView");
  return { default: module.TutupanLahanView };
});

const EarlyWarningView = lazy(async () => {
  const module = await import("./components/EarlyWarningView");
  return { default: module.EarlyWarningView };
});

const SettingsPanel = lazy(async () => {
  const module = await import("./components/SettingsPanel");
  return { default: module.SettingsPanel };
});

function isSchedulerFailureStatus(status?: string | null): boolean {
  return status === "failure" || status === "failed";
}

type AppView = "map" | "matrix" | "pointmatch" | "kompleks" | "landcover" | "earlywarning" | "settings" | "kps";

const PERSISTED_SESSION_KEY = "etaseneu.session.v1";

function readPersistedSession(): AppSession | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(PERSISTED_SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<AppSession>;
    if (
      typeof value.token !== "string" ||
      typeof value.username !== "string" ||
      (value.role !== "admin" && value.role !== "user" && value.role !== "bps")
    ) {
      window.localStorage.removeItem(PERSISTED_SESSION_KEY);
      return null;
    }
    return {
      token: value.token,
      username: value.username,
      role: value.role,
      wilker_bps: typeof value.wilker_bps === "string" ? value.wilker_bps : null,
      expiresAt: typeof value.expiresAt === "string" ? value.expiresAt : null
    };
  } catch {
    window.localStorage.removeItem(PERSISTED_SESSION_KEY);
    return null;
  }
}

function persistSession(session: AppSession | null): void {
  if (typeof window === "undefined") return;
  if (!session) {
    window.localStorage.removeItem(PERSISTED_SESSION_KEY);
    return;
  }
  window.localStorage.setItem(PERSISTED_SESSION_KEY, JSON.stringify(session));
}

// Preferensi sidebar ringkas (icon rail). Default expanded -- user lama tidak
// dikagetkan; sekali di-collapse manual, pilihannya diingat. Semua akses
// localStorage dibungkus try/catch (pola sama seperti lib/dashboardPersistence.ts:
// Chrome Android / mode privat bisa melempar saat storage dimatikan).
const SIDEBAR_COLLAPSED_KEY = "etaseneu.sidebar.collapsed.v1";

function readSidebarCollapsedPref(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function persistSidebarCollapsedPref(collapsed: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    /* storage dimatikan -- preferensi cuma berlaku untuk sesi ini */
  }
}

/**
 * View aktif disimpan di query string supaya refresh dan tombol back tidak
 * selalu melempar pengguna kembali ke Live Map, dan tautan ke Matriks Data
 * bisa dibagikan. "kps" (detail satu KPS dari Buku Besar) juga ikut
 * dipulihkan dari URL selama nama KPS-nya ada, jadi tautan ke satu KPS bisa
 * dibagikan juga.
 *
 * Identifier-nya nama KPS (LEMBAGA/agencyName), bukan polygon_metadata_id --
 * tidak semua KPS punya polygon yang sudah ke-link (spatial join bisa
 * tertinggal), tapi nama KPS selalu ada di setiap baris Buku Besar. Halaman
 * detailnya sendiri yang mencari polygon_metadata_id dari hotspot manapun
 * di grup itu yang sudah ke-link.
 *
 * "settings" sengaja TIDAK ikut dipulihkan dari URL. Gerbangnya berjalan di
 * sisi klien, jadi memulihkannya dari tautan sama saja menyediakan jalan
 * pintas melewati gerbang itu.
 */
function readViewFromUrl(): AppView {
  if (typeof window === "undefined") {
    return "map";
  }
  const params = new URLSearchParams(window.location.search);
  const view = params.get("view");
  if (view === "matrix") {
    return "matrix";
  }
  if (view === "pointmatch") {
    return "pointmatch";
  }
  if (view === "kompleks") {
    return "kompleks";
  }
  if (view === "landcover") {
    return "landcover";
  }
  if (view === "earlywarning") {
    return "earlywarning";
  }
  if (view === "kps" && params.get("kps")) {
    return "kps";
  }
  return "map";
}

function readKpsAgencyFromUrl(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  // URLSearchParams.get() sudah mendekode persen-encoding sendiri.
  return new URLSearchParams(window.location.search).get("kps");
}

// Preseleksi poligon di menu Tutupan Lahan (mis. tautan dari baris ringkas
// di Detail KPS). Opsional -- menu itu tetap bisa dibuka tanpa ini, listnya
// sendiri yang jadi titik masuk utama.
function readLandCoverPolygonIdFromUrl(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = new URLSearchParams(window.location.search).get("polygon");
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function ViewLoader({ label }: { label: string }) {
  return (
    <div className="view-loader" role="status" aria-live="polite">
      <span className="view-loader-dot" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
import { Maximize, Minimize, Menu, X } from "lucide-react";

export default function App() {
  const [selectedProvince, setSelectedProvince] = useState<string>("");
  const [selectedWilker, setSelectedWilker] = useState<string>("");
  const [showWind, setShowWind] = useState(false);
  const [weatherOverlay, setWeatherOverlay] = useState<"temperature" | "humidity" | "precipitation" | "soil_moisture" | "fwi" | null>(null);
  const [activeView, setActiveView] = useState<AppView>(readViewFromUrl);
  const [kpsAgency, setKpsAgency] = useState<string | null>(readKpsAgencyFromUrl);
  const [landCoverPolygonId, setLandCoverPolygonId] = useState<number | null>(readLandCoverPolygonIdFromUrl);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  // Preferensi user (persisted) vs kondisi efektif: collapse SENGAJA cuma
  // berlaku di desktop lebar (>=1024px). Di tablet/mobile lebar sidebar diatur
  // aturan lain yang sudah rapuh (lihat index.css sekitar .app-frame), jadi
  // preferensi ini diabaikan di sana -- bukan dipaksakan.
  const [sidebarCollapsedPref, setSidebarCollapsedPref] = useState<boolean>(readSidebarCollapsedPref);
  const isDesktopWide = useIsDesktopWide();
  const sidebarCollapsed = sidebarCollapsedPref && isDesktopWide;

  const toggleSidebarCollapsed = () => {
    setSidebarCollapsedPref((prev) => {
      const next = !prev;
      persistSidebarCollapsedPref(next);
      return next;
    });
  };
  const [passwordGateOpen, setPasswordGateOpen] = useState(false);
  const [passwordGateError, setPasswordGateError] = useState<string | null>(null);
  const [passwordGateVerifying, setPasswordGateVerifying] = useState(false);
  // Disimpan di memori (bukan localStorage) selama sesi tab ini saja --
  // dikirim sebagai header X-Admin-Key ke endpoint admin (upload geojson,
  // sync manual, prewarm). Backend yang beneran memvalidasi, bukan cuma
  // dicek string di JS seperti sebelumnya.
  const [adminKey, setAdminKey] = useState<string | null>(null);
  // Token sesi disimpan di localStorage supaya reload/reset web tidak
  // memaksa login ulang. Token tetap diverifikasi ke /api/auth/session saat
  // aplikasi dibuka; revoke dari admin akan membuat verifikasi itu 401.
  // session.role menentukan siapa yang lihat tab Manajemen User di
  // Pengaturan (lihat SettingsPanel) -- bukan pembatas fitur dashboard lain.
  const [session, setSession] = useState<AppSession | null>(readPersistedSession);
  const [restoringSession, setRestoringSession] = useState(() => Boolean(readPersistedSession()));

  // Kalau ada panggilan API balas 401 (mis. backend API_REQUIRE_AUTH menyala
  // dan token kadaluarsa), buang sesi -> kembali ke LoginPage.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAuthToken(null);
      persistSession(null);
      clearDashboardCache();
      setSession(null);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    const persisted = readPersistedSession();
    if (!persisted) {
      setRestoringSession(false);
      return;
    }

    setAuthToken(persisted.token);

    let cancelled = false;
    fetch("/api/auth/session", {
      headers: { Authorization: `Bearer ${persisted.token}` }
    })
      .then(async (response) => {
        if (cancelled) return;
        if (response.ok) {
          const data = await response.json();
          const refreshed: AppSession = {
            token: persisted.token,
            username: data.username ?? persisted.username,
            role: data.role ?? persisted.role,
            wilker_bps: data.wilker_bps ?? persisted.wilker_bps ?? null,
            expiresAt: data.expires_at ?? persisted.expiresAt ?? null
          };
          persistSession(refreshed);
          setSession(refreshed);
          setAuthToken(refreshed.token);
        } else if (response.status === 401) {
          setAuthToken(null);
          persistSession(null);
          setSession(null);
        }
      })
      .catch(() => {
        // Saat server sedang restart, pertahankan sesi lokal. Panggilan API
        // dashboard akan menampilkan error koneksi seperti biasa; sesi tetap
        // dibuang otomatis bila server mengembalikan 401.
      })
      .finally(() => {
        if (!cancelled) setRestoringSession(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const handleLoginSuccess = (nextSession: AppSession) => {
    setAuthToken(nextSession.token);
    persistSession(nextSession);
    setSession(nextSession);
  };

  const handleLogout = () => {
    const current = session;
    setAuthToken(null);
    persistSession(null);
    clearDashboardCache();
    setAdminKey(null);
    setSession(null);
    if (current?.token) {
      void fetch("/api/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${current.token}` }
      }).catch(() => undefined);
    }
  };

  const commitViewChange = (view: AppView) => {
    setActiveView(view);
    if (view !== "kps") {
      setKpsAgency(null);
    }
    if (view !== "landcover") {
      setLandCoverPolygonId(null);
    }

    // Pengaturan tidak ditulis ke URL supaya tautannya tidak bisa dipakai
    // melewati gerbang password di atas.
    const params = new URLSearchParams(window.location.search);
    params.delete("kps");
    params.delete("polygon");
    if (view === "matrix" || view === "pointmatch" || view === "kompleks" || view === "landcover") {
      params.set("view", view);
    } else {
      params.delete("view");
    }
    const query = params.toString();
    window.history.pushState({}, "", query ? `?${query}` : window.location.pathname);
  };

  const handleViewChange = (view: AppView) => {
    if (view === "settings") {
      // Info akun tersedia untuk semua role. Isi pengaturan sistem dan
      // manajemen sesi tetap diguard di SettingsPanel oleh role admin.
      commitViewChange("settings");
      return;
    }
    commitViewChange(view);
  };

  // Dipicu dari klik baris KPS di Buku Besar -- beda dari commitViewChange
  // karena butuh menulis nama KPS juga ke URL supaya tautan halaman detail
  // ini bisa dibagikan/di-bookmark.
  // `useCallback` supaya `HotspotMarkersLayer` (React.memo di HotspotMap)
  // tidak ikut re-render tiap state App lain berubah -- penting saat
  // timeline animasi jalan.
  const openKpsDetail = useCallback((agency: string) => {
    setKpsAgency(agency);
    setActiveView("kps");
    const params = new URLSearchParams(window.location.search);
    params.set("view", "kps");
    params.set("kps", agency);
    window.history.pushState({}, "", `?${params.toString()}`);
  }, []);

  // Dipicu dari baris ringkas "Tutupan Lahan" di Detail KPS -- beda dari
  // commitViewChange karena butuh menulis polygon_metadata_id juga ke URL
  // supaya tautan langsung ke satu poligon di menu Tutupan Lahan bisa
  // dibagikan/di-bookmark (pola sama seperti openKpsDetail di atas).
  const openTutupanLahan = (polygonId: number) => {
    setLandCoverPolygonId(polygonId);
    setActiveView("landcover");
    const params = new URLSearchParams(window.location.search);
    params.delete("kps");
    params.set("view", "landcover");
    params.set("polygon", String(polygonId));
    window.history.pushState({}, "", `?${params.toString()}`);
  };

  const handlePasswordGateSubmit = async (password: string) => {
    setPasswordGateError(null);
    setPasswordGateVerifying(true);
    try {
      const response = await fetch("/api/auth/verify", {
        method: "POST",
        headers: { "X-Admin-Key": password }
      });
      if (response.ok) {
        setAdminKey(password);
        setPasswordGateOpen(false);
        commitViewChange("settings");
        return;
      }
      setPasswordGateError(
        response.status === 503
          ? "Admin API belum dikonfigurasi di server."
          : "Password salah!"
      );
    } catch {
      setPasswordGateError("Gagal menghubungi server. Coba lagi.");
    } finally {
      setPasswordGateVerifying(false);
    }
  };

  const handlePasswordGateCancel = () => {
    setPasswordGateOpen(false);
    setPasswordGateError(null);
  };

  // Tombol back/forward browser mengubah URL tanpa memuat ulang halaman, jadi
  // state view harus ikut disesuaikan sendiri.
  useEffect(() => {
    const syncFromUrl = () => {
      setActiveView(readViewFromUrl());
      setKpsAgency(readKpsAgencyFromUrl());
    };
    window.addEventListener("popstate", syncFromUrl);
    return () => window.removeEventListener("popstate", syncFromUrl);
  }, []);
  const [showPanels, setShowPanels] = useState(true);
  // Di mobile panel statistik disajikan sebagai sheet yang dibuka lewat tombol
  // ringkas; di desktop state ini tidak berpengaruh (panelnya selalu tampil).
  const [statsOpen, setStatsOpen] = useState(false);
  // Terpisah dari statsOpen (yang hanya berarti di mobile): ini mengontrol
  // apakah panel statistik desktop ditutup lewat tombol × di headernya.
  const [statsPanelClosed, setStatsPanelClosed] = useState(false);
  const {
    endDate,
    exportDashboard,
    exportError,
    hotspots,
    geojsonStatus,
    isExporting,
    isExportingPdf,
    isPrewarming,
    isTriggeringManualSync,
    exportPdf,
    isRefreshingScheduler,
    layers,
    loadError,
    manualSync,
    prewarmHistory,
    schedulerMetrics,
    sourceBreakdown,
    selectedSatellites,
    startDate,
    stats,
    storageStatus,
    syncError,
    lastHotspotSyncLabel,
    timePreset,
    timeRange,
    setTimePreset,
    toggleSatellite,
    updateDate,
    initialLoading,
    usingCachedData,
    retryInitialLoad
  } = useDashboardData(activeView, adminKey, session?.token ?? null, Boolean(session) && !restoringSession);

  const provinceOptions = useMemo(() => {
    const provinces = hotspots
      .map((h) => h.provinceName)
      .filter((p): p is string => Boolean(p && p.trim() !== ""));
    return Array.from(new Set(provinces)).sort();
  }, [hotspots]);

  // Wilker (wilayah kerja Balai PS) hanya tersedia lewat polygon_metadata,
  // tidak ada kolom khususnya seperti provinceName.
  const wilkerOptions = useMemo(() => {
    const wilkers = hotspots
      .map((h) => h.polygonMetadata?.WILKER_BPS)
      .filter((w): w is string => Boolean(w && w.trim() !== ""));
    return Array.from(new Set(wilkers)).sort();
  }, [hotspots]);

  useEffect(() => {
    if (selectedProvince && !provinceOptions.includes(selectedProvince)) {
      setSelectedProvince("");
    }
  }, [provinceOptions, selectedProvince]);

  const userWilker = useMemo(() => {
    if (session?.role === "bps") {
      if (session.wilker_bps) return session.wilker_bps;
      const u = session.username?.toLowerCase() || "";
      if (u.includes("banjarbaru")) return "Balai PS Banjarbaru";
      if (u.includes("kampar")) return "Balai PS Kampar";
      if (u.includes("palembang")) return "Balai PS Palembang";
      if (u.includes("medan")) return "Balai PS Medan";
      if (u.includes("gowa")) return "Balai PS Gowa";
      if (u.includes("denpasar")) return "Balai PS Denpasar";
      if (u.includes("ambon")) return "Balai PS Ambon";
      if (u.includes("bogor")) return "Balai PS Bogor";
      if (u.includes("kupang")) return "Balai PS Kupang";
      if (u.includes("kutai") || u.includes("karta")) return "Balai PS Kutai Kartanegara";
      if (u.includes("manado")) return "Balai PS Manado";
      if (u.includes("manokwari")) return "Balai PS Manokwari";
      if (u.includes("yogyakarta") || u.includes("jogja")) return "Balai PS Yogyakarta";
    }
    return "";
  }, [session]);

  const effectiveWilker = session?.role === "bps" ? (userWilker || session.wilker_bps || selectedWilker) : selectedWilker;

  // Pilihan yang tidak lagi ada di data (mis. setelah rentang waktu diubah)
  // direset supaya peta tidak diam-diam menyaring habis semua titik.
  // Untuk role BPS, wilker selalu terkunci ke wilayah kerjanya.
  useEffect(() => {
    if (session?.role === "bps" && effectiveWilker) {
      setSelectedWilker(effectiveWilker);
      return;
    }
    if (selectedWilker && !wilkerOptions.includes(selectedWilker)) {
      setSelectedWilker("");
    }
  }, [wilkerOptions, selectedWilker, session?.role, effectiveWilker]);

  const visibleHotspots = useMemo(
    () =>
      effectiveWilker
        ? hotspots.filter((h) => {
            const w = h.polygonMetadata?.WILKER_BPS;
            if (!w) return false;
            const normW = w.toLowerCase().replace(/[^a-z0-9]/g, "");
            const normEff = effectiveWilker.toLowerCase().replace(/[^a-z0-9]/g, "");
            return normW.includes(normEff) || normEff.includes(normW);
          })
        : hotspots,
    [hotspots, effectiveWilker],
  );

  const historyYear = timeRange.endAt.getUTCFullYear() || parseInt(getTodayWIB().slice(0, 4), 10);
  // storageStatus & schedulerMetrics baru terisi setelah request awal selesai.
  // Selama masih null kita BELUM TAHU kondisinya. Menampilkan tebakan buruk
  // ("fallback file", "Nonaktif", "never") di fase ini bikin user mengira
  // sistem bermasalah padahal cuma belum selesai memuat -- jadi fase ini
  // harus punya tampilannya sendiri, bukan menumpang cabang else.
  const isStorageLoading = !storageStatus;
  const isSchedulerLoading = !schedulerMetrics;

  // Label barisnya sudah "Database", jadi kata itu tidak perlu diulang di
  // nilainya -- di kolom sempit teksnya malah terpotong jadi "database onl".
  const syncLabel = isStorageLoading
    ? "memuat..."
    : storageStatus.database_enabled
      ? "online"
      : "fallback file";
  const syncStatusLabel = isStorageLoading
    ? "memuat"
    : storageStatus.last_hotspot_sync_at
      ? "success"
      : "waiting";

  const dynamicConfidenceStats = useMemo(() => {
    const stats: Record<string, { tinggi: number, sedang: number, rendah: number, total: number }> = {};

    visibleHotspots.forEach((h) => {
      let satKey = (h.source || h.satellite || "Unknown").trim().toUpperCase();
      
      let formattedSat = satKey;
      if (satKey.includes("NOAA-20") || satKey.includes("NOAA20")) formattedSat = "NOAA-20";
      else if (satKey.includes("NOAA-21") || satKey.includes("NOAA21")) formattedSat = "NOAA-21";
      else if (satKey.includes("S-NPP") || satKey.includes("SNPP") || satKey.includes("SUOMI")) formattedSat = "S-NPP";
      else if (satKey.includes("MODIS")) formattedSat = "MODIS";
      else if (!satKey) formattedSat = "Unknown";
      
      if (!stats[formattedSat]) {
        stats[formattedSat] = { tinggi: 0, sedang: 0, rendah: 0, total: 0 };
      }

      const frp = h.frp ?? 0;
      let category = "rendah";
      if (frp > 30) category = "tinggi";
      else if (frp >= 10) category = "sedang";
      else category = "rendah";

      if (category === "tinggi") stats[formattedSat].tinggi++;
      else if (category === "sedang") stats[formattedSat].sedang++;
      else stats[formattedSat].rendah++;

      stats[formattedSat].total++;
    });

    return stats;
  }, [visibleHotspots]);

  const satelliteRows = useMemo(() => {
    return Object.entries(dynamicConfidenceStats).sort(([a], [b]) => a.localeCompare(b));
  }, [dynamicConfidenceStats]);

  const totalTinggi = useMemo(() => satelliteRows.reduce((acc, [_, row]) => acc + row.tinggi, 0), [satelliteRows]);
  const totalSedang = useMemo(() => satelliteRows.reduce((acc, [_, row]) => acc + row.sedang, 0), [satelliteRows]);
  const totalRendah = useMemo(() => satelliteRows.reduce((acc, [_, row]) => acc + row.rendah, 0), [satelliteRows]);
  const grandTotal = useMemo(() => satelliteRows.reduce((acc, [_, row]) => acc + row.total, 0), [satelliteRows]);

  const pct = (val: number) => grandTotal > 0 ? ((val / grandTotal) * 100).toFixed(1) + '%' : '0%';

  const { dominantSat, dominantConf } = useMemo(() => {
    let dSat = { name: '-', count: 0 };
    satelliteRows.forEach(([sat, row]) => {
      if (row.total > dSat.count) {
        dSat = { name: sat, count: row.total };
      }
    });

    let dConf = { name: '-', count: 0, pct: '0%' };
    if (totalTinggi >= totalSedang && totalTinggi >= totalRendah && totalTinggi > 0) dConf = { name: 'Tinggi', count: totalTinggi, pct: pct(totalTinggi) };
    else if (totalSedang >= totalTinggi && totalSedang >= totalRendah && totalSedang > 0) dConf = { name: 'Sedang', count: totalSedang, pct: pct(totalSedang) };
    else if (totalRendah >= totalTinggi && totalRendah >= totalSedang && totalRendah > 0) dConf = { name: 'Rendah', count: totalRendah, pct: pct(totalRendah) };
    
    return { dominantSat: dSat, dominantConf: dConf };
  }, [satelliteRows, totalTinggi, totalSedang, totalRendah, grandTotal]);

  const [clockSec, setClockSec] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => {
      setClockSec((prev) => prev + 1);
    }, 15000);
    return () => clearInterval(timer);
  }, []);

  const lastSyncTime = schedulerMetrics?.last_sync_at ? new Date(schedulerMetrics.last_sync_at).getTime() : null;
  const intervalMs = (schedulerMetrics?.interval_hours || 3) * 60 * 60 * 1000;
  const nowMs = new Date().getTime();

  let healthStatus: "loading" | "normal" | "warning" | "error" = "normal";
  let healthLabel = "Sinkronisasi Normal";

  if (isSchedulerLoading) {
    healthStatus = "loading";
    healthLabel = "Memuat status...";
  } else if (!schedulerMetrics.scheduler_enabled) {
    healthStatus = "warning";
    healthLabel = "Scheduler Nonaktif";
  } else if ((schedulerMetrics.consecutive_failures ?? 0) > 1) {
    healthStatus = "error";
    healthLabel = "Sinkronisasi Bermasalah";
  } else if (isSchedulerFailureStatus(schedulerMetrics.last_sync_status) || (schedulerMetrics.consecutive_failures ?? 0) === 1) {
    healthStatus = "warning";
    healthLabel = "Sinkronisasi Gagal Sekali";
  } else if (lastSyncTime) {
    const diffMs = nowMs - lastSyncTime;
    if (diffMs > 2 * intervalMs) {
      healthStatus = "error";
      healthLabel = "Sinkronisasi Bermasalah";
    } else if (diffMs > intervalMs) {
      healthStatus = "warning";
      healthLabel = "Data Mulai Terlambat";
    }
  } else {
    healthStatus = "warning";
    healthLabel = "Menunggu Sinkronisasi";
  }

  const syncTodayRatio = useMemo(() => {
    // Tanpa penjaga ini rasionya dihitung dari jadwal default dan tampil
    // sebagai angka meyakinkan (mis. "4 / 8") padahal belum ada datanya.
    if (!schedulerMetrics) {
      return "-";
    }
    const scheduleHours = schedulerMetrics?.schedule_hours || [0, 3, 6, 9, 12, 15, 18, 21];
    const totalSlots = scheduleHours.length;
    let currentWibHour = 0;
    let currentWibMinute = 0;
    try {
      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: "Asia/Jakarta",
        hour: "numeric",
        minute: "numeric",
        hour12: false
      });
      const parts = formatter.formatToParts(new Date());
      const hourStr = parts.find(p => p.type === "hour")?.value ?? "0";
      const minStr = parts.find(p => p.type === "minute")?.value ?? "0";
      currentWibHour = parseInt(hourStr, 10);
      currentWibMinute = parseInt(minStr, 10);
    } catch {
      const d = new Date();
      currentWibHour = d.getHours();
      currentWibMinute = d.getMinutes();
    }
    const passedSlots = scheduleHours.filter(h => {
      if (h < currentWibHour) return true;
      if (h === currentWibHour && currentWibMinute >= 5) return true;
      return false;
    }).length;
    const failures = schedulerMetrics?.consecutive_failures || 0;
    const successfulSyncs = Math.max(0, passedSlots - failures);
    return `${successfulSyncs} / ${totalSlots}`;
  }, [schedulerMetrics]);

  const schedulerStatusInfo = useMemo(() => {
    if (!schedulerMetrics) {
      return { label: "Memuat...", color: "#9ca3af", bg: "rgba(156, 163, 175, 0.15)" };
    }
    if (!schedulerMetrics.scheduler_enabled) {
      return { label: "Nonaktif", color: "#6b7280", bg: "rgba(107, 114, 128, 0.15)" };
    }
    if ((schedulerMetrics.consecutive_failures ?? 0) > 1) {
      return { label: "Error", color: "#ef4444", bg: "rgba(239, 68, 68, 0.15)" };
    }
    if (isSchedulerFailureStatus(schedulerMetrics.last_sync_status) || (schedulerMetrics.consecutive_failures ?? 0) === 1) {
      return { label: "Peringatan", color: "#f59e0b", bg: "rgba(245, 158, 11, 0.15)" };
    }
    return { label: "Aktif", color: "#10b981", bg: "rgba(16, 185, 129, 0.15)" };
  }, [schedulerMetrics]);

  const latestHotspot = useMemo(() => {
    if (!hotspots || hotspots.length === 0) return null;
    return hotspots.reduce((latest, current) => {
      const latestTime = new Date(latest.detectedAt).getTime();
      const currentTime = new Date(current.detectedAt).getTime();
      return currentTime > latestTime ? current : latest;
    }, hotspots[0]);
  }, [hotspots]);

  const latestHotspotTimeLabel = useMemo(() => {
    if (!latestHotspot) return "Tidak ada dalam filter";
    return formatDateTimeWIB(latestHotspot.detectedAt);
  }, [latestHotspot]);

  const dataAgeLabel = useMemo(() => {
    if (!latestHotspot) return "— (pilih filter 48J / 7H)";
    const diffMs = new Date().getTime() - new Date(latestHotspot.detectedAt).getTime();
    if (diffMs < 0) return "0 menit";
    const diffMinutes = Math.floor(diffMs / (60 * 1000));
    const hours = Math.floor(diffMinutes / 60);
    const mins = diffMinutes % 60;
    if (hours === 0) return `${mins} menit`;
    return `${hours} jam ${mins} menit`;
  }, [latestHotspot, clockSec]);

  if (restoringSession) {
    return <ViewLoader label="Memulihkan sesi akun..." />;
  }

  if (!session) {
    return <LoginPage onSuccess={handleLoginSuccess} />;
  }

  return (
    <div className={`app-frame grid-lines${sidebarCollapsed ? " app-frame--collapsed" : ""}`}>
      {/* Mobile Hamburger Button */}
      <button
        className="mobile-hamburger"
        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
        aria-label="Toggle navigation menu"
      >
        {mobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
      </button>

      {/* Mobile Overlay */}
      <div
        className={`mobile-overlay${mobileMenuOpen ? ' mobile-open' : ''}`}
        onClick={() => setMobileMenuOpen(false)}
      />

      {/* Sidebar */}
      <SidebarNav
        activeView={activeView}
        onChangeView={(view) => {
          handleViewChange(view);
          setMobileMenuOpen(false);
        }}
        onManualSync={() => void manualSync()}
        onPrewarmHistory={() => void prewarmHistory()}
        onLogout={handleLogout}
        syncLabel={syncLabel}
        syncStatusLabel={syncStatusLabel}
        lastSyncLabel={isStorageLoading ? "memuat..." : lastHotspotSyncLabel}
        manualSyncBusy={isTriggeringManualSync}
        prewarmBusy={isPrewarming}
        healthStatus={healthStatus}
        healthLabel={healthLabel}
        schedulerStatusLabel={schedulerStatusInfo.label}
        schedulerStatusColor={schedulerStatusInfo.color}
        schedulerStatusBg={schedulerStatusInfo.bg}
        syncTodayRatio={syncTodayRatio}
        syncInterval={isSchedulerLoading ? '-' : schedulerMetrics.interval_hours ? `${schedulerMetrics.interval_hours} Jam` : '3 Jam'}
        nextScheduledSyncLabel={isSchedulerLoading ? '-' : formatDateTimeWIB(schedulerMetrics.next_scheduled_sync_at) || 'Belum Dijadwalkan'}
        latestHotspotTimeLabel={latestHotspotTimeLabel}
        dataAgeLabel={dataAgeLabel}
        hasLatestHotspot={!!latestHotspot}
        isAdmin={session?.role === "admin"}
        mobileOpen={mobileMenuOpen}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={toggleSidebarCollapsed}
        filterSlot={activeView === "map" ? (
          <FilterPanel
            selectedSatellites={selectedSatellites}
            timePreset={timePreset}
            onToggleSatellite={toggleSatellite}
            onTimePresetChange={setTimePreset}
            onDateChange={updateDate}
            startDate={startDate}
            endDate={endDate}
            hotspotCount={selectedWilker ? visibleHotspots.length : stats.hotspotCount}
            selectedProvince={selectedProvince}
            onProvinceChange={setSelectedProvince}
            provinceOptions={provinceOptions}
            selectedWilker={selectedWilker}
            onWilkerChange={setSelectedWilker}
            wilkerOptions={wilkerOptions}
            isWilkerLocked={session?.role === "bps"}
            showWind={showWind}
            onToggleWind={() => setShowWind(w => !w)}
            weatherOverlay={weatherOverlay}
            onWeatherOverlayChange={setWeatherOverlay}
          />
        ) : null}
      />

      <main className="workspace">
      {usingCachedData && (
        <div className="cached-data-banner" role="status">
          <span className="cached-data-banner__dot" />
          Menampilkan data tersimpan — memperbarui&hellip;
        </div>
      )}
      <ErrorBoundary key={activeView} label={`tampilan ${activeView}`}>
        {activeView === "map" ? (
          <section aria-label="Dashboard workspace" className="workspace-stage workspace-stage--map">
            <Suspense fallback={<ViewLoader label="Memuat tampilan peta..." />}>
              <HotspotMap
                hotspots={visibleHotspots}
                layers={layers}
                selectedProvince={selectedProvince}
                selectedWilker={effectiveWilker || selectedWilker}
                showWind={showWind}
                weatherOverlay={weatherOverlay}
                onOpenKpsDetail={openKpsDetail}
              />
            </Suspense>

            <div
              className={`panels-toggle-layer${showPanels ? "" : " panels-toggle-layer--hidden"}`}
              aria-hidden={!showPanels}
            >
                
                <button
                  type="button"
                  className="stats-sheet-toggle"
                  onClick={() => setStatsOpen((open) => !open)}
                  aria-expanded={statsOpen}
                  aria-controls="panel-statistik-hotspot"
                >
                  {statsOpen ? "Tutup" : `${(selectedWilker ? visibleHotspots.length : stats.hotspotCount).toLocaleString()} hotspot`}
                </button>

                {!statsPanelClosed && (
                <aside
                  id="panel-statistik-hotspot"
                  className={`control-overlay control-overlay--top-right panel panel--stats${statsOpen ? " mobile-open" : ""}`}
                  style={{ maxHeight: '100%', overflowY: 'auto', overflowX: 'hidden' }}
                >
                  <article className="metric-card" style={{ padding: '0.65rem 0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.4rem', marginBottom: '0.3rem' }}>
                      <p className="metric-label" style={{ textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.4rem', margin: 0, fontSize: '0.72rem' }}>
                        Titik Panas (FRP)
                        <span title="Kategori Intensitas Panas (FRP)&#10;&#10;Tinggi: > 30 MW&#10;Sedang: 10–30 MW&#10;Rendah: < 10 MW&#10;&#10;FRP (Fire Radiative Power) menunjukkan tingkat energi panas yang dipancarkan oleh hotspot yang terdeteksi satelit." style={{ cursor: 'help', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '13px', height: '13px', borderRadius: '50%', border: '1px solid currentColor', fontSize: '9px', flexShrink: 0 }}>i</span>
                      </p>
                      <button
                        type="button"
                        className="stats-panel-close"
                        onClick={() => setStatsPanelClosed(true)}
                        aria-label="Tutup panel statistik"
                      >
                        ×
                      </button>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
                      <strong className="metric-value" style={{ lineHeight: 1, fontSize: '2rem' }}>{stats.hotspotCount.toLocaleString()}</strong>
                      <span style={{ fontSize: '0.75rem', color: '#9ca3af' }}>hotspot</span>
                    </div>

                    {stats.hotspotCount > 0 && (
                      <>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem', marginTop: '0.55rem', paddingBottom: '0.55rem', borderBottom: '1px solid rgba(255,255,255,0.08)', fontSize: '0.75rem', color: '#d1d5db' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span><span style={{ color: '#ef4444', marginRight: '0.3rem' }}>■</span>Tinggi</span>
                            <span><strong style={{ color: '#ffffff' }}>{totalTinggi.toLocaleString()}</strong> <span style={{ color: '#6b7280' }}>({pct(totalTinggi)})</span></span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span><span style={{ color: '#f59e0b', marginRight: '0.3rem' }}>■</span>Sedang</span>
                            <span><strong style={{ color: '#ffffff' }}>{totalSedang.toLocaleString()}</strong> <span style={{ color: '#6b7280' }}>({pct(totalSedang)})</span></span>
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                            <span><span style={{ color: '#3b82f6', marginRight: '0.3rem' }}>■</span>Rendah</span>
                            <span><strong style={{ color: '#ffffff' }}>{totalRendah.toLocaleString()}</strong> <span style={{ color: '#6b7280' }}>({pct(totalRendah)})</span></span>
                          </div>
                        </div>

                        <div style={{ marginTop: '0.55rem' }}>
                          <p style={{ fontSize: '0.65rem', color: '#6b7280', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Distribusi per Satelit</p>
                          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.7rem', color: '#ffffff', tableLayout: 'fixed' }}>
                            <thead>
                              <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', color: '#9ca3af' }}>
                                <th style={{ padding: '0.25rem 0', fontWeight: '500', width: '30%', textAlign: 'left', fontSize: '0.62rem' }}>Satelit</th>
                                <th style={{ padding: '0.25rem 0', fontWeight: '500', color: '#ef4444', width: '17.5%', textAlign: 'center', fontSize: '0.62rem' }}>T</th>
                                <th style={{ padding: '0.25rem 0', fontWeight: '500', color: '#f59e0b', width: '17.5%', textAlign: 'center', fontSize: '0.62rem' }}>S</th>
                                <th style={{ padding: '0.25rem 0', fontWeight: '500', color: '#3b82f6', width: '17.5%', textAlign: 'center', fontSize: '0.62rem' }}>R</th>
                                <th style={{ padding: '0.25rem 0', fontWeight: '500', width: '17.5%', textAlign: 'center', fontSize: '0.62rem' }}>∑</th>
                              </tr>
                            </thead>
                            <tbody>
                              {satelliteRows.map(([sat, rowStats]) => (
                                <tr key={sat} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                                  <td style={{ padding: '0.25rem 0', fontWeight: '600', wordBreak: 'break-all', textAlign: 'left', fontSize: '0.65rem' }}>{sat}</td>
                                  <td style={{ padding: '0.25rem 0', textAlign: 'center' }}>{rowStats.tinggi.toLocaleString()}</td>
                                  <td style={{ padding: '0.25rem 0', textAlign: 'center' }}>{rowStats.sedang.toLocaleString()}</td>
                                  <td style={{ padding: '0.25rem 0', textAlign: 'center' }}>{rowStats.rendah.toLocaleString()}</td>
                                  <td style={{ padding: '0.25rem 0', textAlign: 'center', fontWeight: '600' }}>{rowStats.total.toLocaleString()}</td>
                                </tr>
                              ))}
                            </tbody>
                            <tfoot>
                              <tr style={{ backgroundColor: 'rgba(255,255,255,0.06)', borderTop: '1px solid rgba(255,255,255,0.15)' }}>
                                <td style={{ padding: '0.3rem 0', fontWeight: '700', textAlign: 'left', fontSize: '0.65rem' }}>TOTAL</td>
                                <td style={{ padding: '0.3rem 0', textAlign: 'center', fontWeight: '600' }}>{totalTinggi.toLocaleString()}</td>
                                <td style={{ padding: '0.3rem 0', textAlign: 'center', fontWeight: '600' }}>{totalSedang.toLocaleString()}</td>
                                <td style={{ padding: '0.3rem 0', textAlign: 'center', fontWeight: '600' }}>{totalRendah.toLocaleString()}</td>
                                <td style={{ padding: '0.3rem 0', textAlign: 'center', fontWeight: '700' }}>{grandTotal.toLocaleString()}</td>
                              </tr>
                            </tfoot>
                          </table>
                        </div>

                        <div style={{ marginTop: '0.55rem', paddingTop: '0.55rem', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                          <p style={{ fontSize: '0.65rem', color: '#6b7280', marginBottom: '0.35rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Insight</p>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.35rem', fontSize: '0.72rem' }}>
                            <div style={{ backgroundColor: 'rgba(255,255,255,0.04)', padding: '0.45rem 0.5rem', borderRadius: '5px' }}>
                              <span style={{ color: '#6b7280', display: 'block', marginBottom: '0.15rem', fontSize: '0.6rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Satelit</span>
                              <strong style={{ color: '#ffffff', display: 'block', fontSize: '0.78rem', wordBreak: 'break-word' }}>{dominantSat.name}</strong>
                              <span style={{ color: '#6b7280', fontSize: '0.65rem' }}>{dominantSat.count.toLocaleString()}</span>
                            </div>
                            <div style={{ backgroundColor: 'rgba(255,255,255,0.04)', padding: '0.45rem 0.5rem', borderRadius: '5px' }}>
                              <span style={{ color: '#6b7280', display: 'block', marginBottom: '0.15rem', fontSize: '0.6rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Conf</span>
                              <strong style={{ color: '#ffffff', display: 'block', fontSize: '0.78rem' }}>{dominantConf.name}</strong>
                              <span style={{ color: '#6b7280', fontSize: '0.65rem' }}>{dominantConf.pct}</span>
                            </div>
                          </div>
                        </div>
                      </>
                    )}
                  </article>
                </aside>
                )}

                {statsPanelClosed && (
                  <button
                    type="button"
                    className="stats-panel-reopen"
                    onClick={() => setStatsPanelClosed(false)}
                    aria-label="Tampilkan panel statistik"
                  >
                    {(selectedWilker ? visibleHotspots.length : stats.hotspotCount).toLocaleString()} hotspot
                  </button>
                )}
            </div>

            <button
              type="button"
              className="ui-toggle-btn"
              onClick={() => setShowPanels(p => !p)}
              title={showPanels ? "Sembunyikan Panel" : "Tampilkan Panel"}
            >
              {showPanels ? <Minimize size={16} /> : <Maximize size={16} />}
              <span className="ui-toggle-btn-label">
                {showPanels ? "Sembunyikan UI" : "Tampilkan UI"}
              </span>
            </button>

            {loadError ? <p className="toast-error">{loadError}</p> : null}
            {exportError ? <p className="toast-error toast-error--bottom">{exportError}</p> : null}
            {syncError ? <p className="toast-error toast-error--bottom">{syncError}</p> : null}
          </section>
        ) : activeView === "matrix" ? (
          <section aria-label="Matrix workspace" className="workspace-stage workspace-stage--matrix">
            <Suspense fallback={<ViewLoader label="Memuat matriks data..." />}>
              <HotspotMatrix
                hotspots={(session?.role === "bps" ? visibleHotspots : hotspots).map((hotspot) => ({
                  id: hotspot.id,
                  detectedAt: hotspot.detectedAt,
                  latitude: hotspot.latitude,
                  longitude: hotspot.longitude,
                  layerName: hotspot.layerName,
                  agencyName: hotspot.agencyName,
                  provinceName: hotspot.provinceName,
                  polygonMetadata: hotspot.polygonMetadata,
                  source: hotspot.source,
                  satellite: hotspot.satellite,
                  brightness: hotspot.brightness,
                  frp: hotspot.frp,
                  confidence: hotspot.confidence,
                  daynight: hotspot.daynight,
                  fungsiKawasan: hotspot.fungsiKawasan,
                  kelompokKawasan: hotspot.kelompokKawasan
                }))}
                geojsonStatus={geojsonStatus}
                onExport={(filters) => void exportDashboard(filters)}
                isExporting={isExporting}
                onExportPdf={(filters) => void exportPdf(filters)}
                isExportingPdf={isExportingPdf}
                onDateChange={updateDate}
                startDate={startDate}
                endDate={endDate}
                timeRange={timeRange}
                dateRangeLabel={timeRange.label}
                timePreset={timePreset}
                onTimePresetChange={setTimePreset}
                initialWilker={effectiveWilker || selectedWilker}
                lockedWilker={session?.role === "bps" ? effectiveWilker : undefined}
                onOpenKpsDetail={openKpsDetail}
                isAdmin={session?.role === "admin"}
              />
            </Suspense>
          </section>
        ) : activeView === "pointmatch" ? (
          <section aria-label="Cek titik ke KPS workspace" className="workspace-stage workspace-stage--pointmatch">
            <Suspense fallback={<ViewLoader label="Memuat alat cek titik..." />}>
              <PointMatchView />
            </Suspense>
          </section>
        ) : activeView === "kompleks" ? (
          <section aria-label="Kompleks Kebakaran workspace" className="workspace-stage workspace-stage--kompleks">
            <Suspense fallback={<ViewLoader label="Memuat kompleks kebakaran..." />}>
              <KompleksKebakaranView onOpenKpsDetail={openKpsDetail} layers={layers} />
            </Suspense>
          </section>
        ) : activeView === "landcover" ? (
          <section aria-label="Tutupan Lahan workspace" className="workspace-stage workspace-stage--landcover">
            <Suspense fallback={<ViewLoader label="Memuat tutupan lahan..." />}>
              <TutupanLahanView
                initialPolygonId={landCoverPolygonId}
                onOpenKpsDetail={openKpsDetail}
                isAdmin={session?.role === "admin"}
              />
            </Suspense>
          </section>
        ) : activeView === "earlywarning" ? (
          <section aria-label="Peringatan Dini workspace" className="workspace-stage workspace-stage--earlywarning">
            <Suspense fallback={<ViewLoader label="Memuat peringatan dini..." />}>
              <EarlyWarningView
                onOpenKpsDetail={openKpsDetail}
                session={session}
                selectedWilker={session?.role === "bps" ? (session.wilker_bps || selectedWilker) : selectedWilker}
              />
            </Suspense>
          </section>
        ) : activeView === "kps" ? (
          <section aria-label="Detail KPS workspace" className="workspace-stage workspace-stage--kps">
            <Suspense fallback={<ViewLoader label="Memuat detail KPS..." />}>
              {kpsAgency !== null ? (
                <KpsDetailView
                  agency={kpsAgency}
                  hotspots={hotspots}
                  onClose={() => commitViewChange("matrix")}
                  onExportPdf={(filters) => void exportPdf(filters)}
                  isExportingPdf={isExportingPdf}
                  onOpenTutupanLahan={openTutupanLahan}
                />
              ) : null}
            </Suspense>
          </section>
        ) : (
          <section aria-label="Settings workspace" className="workspace-stage workspace-stage--settings">
            <Suspense fallback={<ViewLoader label="Memuat pengaturan..." />}>
              <SettingsPanel
                onRefreshLayers={() => void retryInitialLoad()}
                adminKey={adminKey}
                session={session}
                onLogout={handleLogout}
              />
            </Suspense>
          </section>
        )}
      </ErrorBoundary>
      </main>

      <PasswordGateModal
        open={passwordGateOpen}
        error={passwordGateError}
        verifying={passwordGateVerifying}
        onSubmit={(password) => void handlePasswordGateSubmit(password)}
        onCancel={handlePasswordGateCancel}
      />

      {initialLoading.error && (
        <div className="loading-screen-overlay">
          <div className="loading-card">
            <div className="loading-logo">ES</div>
            <h2 className="loading-error-title">{initialLoading.error}</h2>
            <p className="loading-subtitle">Gagal terhubung ke server. Periksa koneksi Anda.</p>
            <button
              type="button"
              className="loading-retry-button"
              onClick={retryInitialLoad}
            >
              Coba Lagi
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
