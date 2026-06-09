import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";

import { FilterPanel } from "./components/FilterPanel";
import { SidebarNav } from "./components/SidebarNav";
import { useDashboardData } from "./hooks/useDashboardData";
import { getTodayWIB, formatDateTimeWIB } from "./lib/date";

const HotspotMap = lazy(async () => {
  const module = await import("./components/HotspotMap");
  return { default: module.HotspotMap };
});

const HotspotMatrix = lazy(async () => {
  const module = await import("./components/HotspotMatrix");
  return { default: module.HotspotMatrix };
});

const MonitoringPanel = lazy(async () => {
  const module = await import("./components/MonitoringPanel");
  return { default: module.MonitoringPanel };
});

const SettingsPanel = lazy(async () => {
  const module = await import("./components/SettingsPanel");
  return { default: module.SettingsPanel };
});

function isSchedulerFailureStatus(status?: string | null): boolean {
  return status === "failure" || status === "failed";
}

function deriveMonitoringSignal(
  metrics: {
    last_sync_status?: string;
    consecutive_failures?: number;
    new_hotspot_over_threshold?: boolean;
    has_new_hotspot?: boolean;
  } | null,
): "normal" | "incident" | "critical" {
  if (!metrics) {
    return "normal";
  }

  if ((metrics.consecutive_failures ?? 0) > 1) {
    return "critical";
  }

  if (metrics.new_hotspot_over_threshold) {
    return "critical";
  }

  if (isSchedulerFailureStatus(metrics.last_sync_status) || (metrics.consecutive_failures ?? 0) === 1) {
    return "incident";
  }

  if (metrics.has_new_hotspot) {
    return "incident";
  }

  return "normal";
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
  const [showWind, setShowWind] = useState(false);
  const [activeView, setActiveView] = useState<"map" | "matrix" | "monitoring" | "settings">("map");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [mobileFilterOpen, setMobileFilterOpen] = useState(false);
  const handleViewChange = (view: "map" | "matrix" | "monitoring" | "settings") => {
    if (view === "settings") {
      const password = prompt("Masukkan password untuk mengakses Pengaturan:");
      if (password !== "admin@5150") {
        alert("Password salah!");
        return;
      }
    }
    setActiveView(view);
  };
  const [signalChangeNotice, setSignalChangeNotice] = useState<string | null>(null);
  const [audioMuted, setAudioMuted] = useState(false);
  const [alertVolume, setAlertVolume] = useState<"normal" | "low">("normal");
  const [showPanels, setShowPanels] = useState(true);
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
    toggleLayer,
    toggleSatellite,
    updateDate,
    initialLoading,
    retryInitialLoad
  } = useDashboardData(activeView);

  const provinceOptions = useMemo(() => {
    const provinces = hotspots
      .map((h) => h.provinceName)
      .filter((p): p is string => Boolean(p && p.trim() !== ""));
    return Array.from(new Set(provinces)).sort();
  }, [hotspots]);

  useEffect(() => {
    if (selectedProvince && !provinceOptions.includes(selectedProvince)) {
      setSelectedProvince("");
    }
  }, [provinceOptions, selectedProvince]);

  const monitoringSignal = useMemo(
    () => deriveMonitoringSignal(schedulerMetrics),
    [schedulerMetrics],
  );
  const previousSignalRef = useRef<"normal" | "incident" | "critical">("normal");
  const soundSignalRef = useRef<"normal" | "incident" | "critical">("normal");
  const historyYear = timeRange.endAt.getUTCFullYear() || parseInt(getTodayWIB().slice(0, 4), 10);
  const syncLabel = storageStatus?.database_enabled ? "database online" : "fallback file";
  const syncStatusLabel = storageStatus?.last_hotspot_sync_at ? "success" : "waiting";

  useEffect(() => {
    const previousSignal = previousSignalRef.current;
    previousSignalRef.current = monitoringSignal;

    if (monitoringSignal === previousSignal || monitoringSignal === "normal") {
      return;
    }

    const escalationMap = {
      incident: "Status berubah: Sinyal insiden baru",
      critical: "Status berubah: Peringatan kritis"
    } as const;

    setSignalChangeNotice(escalationMap[monitoringSignal]);
    const timer = window.setTimeout(() => {
      setSignalChangeNotice(null);
    }, 8000);

    return () => window.clearTimeout(timer);
  }, [monitoringSignal]);

  useEffect(() => {
    const previousSignal = soundSignalRef.current;
    soundSignalRef.current = monitoringSignal;

    if (activeView !== "monitoring" || audioMuted) {
      return;
    }

    if (monitoringSignal === previousSignal || monitoringSignal === "normal") {
      return;
    }

    const AudioContextCtor = window.AudioContext;
    if (!AudioContextCtor) {
      return;
    }

    const audioContext = new AudioContextCtor();
    const oscillator = audioContext.createOscillator();
    const gainNode = audioContext.createGain();
    const toneFrequency = monitoringSignal === "critical" ? 880 : 640;
    const peakGain = alertVolume === "low" ? 0.035 : 0.08;

    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(toneFrequency, audioContext.currentTime);
    gainNode.gain.setValueAtTime(0.0001, audioContext.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(peakGain, audioContext.currentTime + 0.01);
    gainNode.gain.exponentialRampToValueAtTime(0.0001, audioContext.currentTime + 0.24);

    oscillator.connect(gainNode);
    gainNode.connect(audioContext.destination);
    oscillator.start(audioContext.currentTime);
    oscillator.stop(audioContext.currentTime + 0.25);
    void audioContext.close();
  }, [activeView, alertVolume, audioMuted, monitoringSignal]);

  const dynamicConfidenceStats = useMemo(() => {
    const stats: Record<string, { tinggi: number, sedang: number, rendah: number, total: number }> = {};

    hotspots.forEach((h) => {
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
  }, [hotspots]);

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

  let healthStatus: "normal" | "warning" | "error" = "normal";
  let healthLabel = "Sinkronisasi Normal";

  if (!schedulerMetrics || !schedulerMetrics.scheduler_enabled) {
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
    if (!schedulerMetrics || !schedulerMetrics.scheduler_enabled) {
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

  return (
    <div className="app-frame grid-lines">
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
        syncLabel={syncLabel}
        syncStatusLabel={syncStatusLabel}
        lastSyncLabel={lastHotspotSyncLabel}
        manualSyncBusy={isTriggeringManualSync}
        prewarmBusy={isPrewarming}
        monitoringSignal={monitoringSignal}
        healthStatus={healthStatus}
        healthLabel={healthLabel}
        schedulerStatusLabel={schedulerStatusInfo.label}
        schedulerStatusColor={schedulerStatusInfo.color}
        schedulerStatusBg={schedulerStatusInfo.bg}
        syncTodayRatio={syncTodayRatio}
        syncInterval={schedulerMetrics?.interval_hours ? `${schedulerMetrics.interval_hours} Jam` : '3 Jam'}
        nextScheduledSyncLabel={formatDateTimeWIB(schedulerMetrics?.next_scheduled_sync_at) || 'Belum Dijadwalkan'}
        latestHotspotTimeLabel={latestHotspotTimeLabel}
        dataAgeLabel={dataAgeLabel}
        hasLatestHotspot={!!latestHotspot}
        mobileOpen={mobileMenuOpen}
      />

      <main className="workspace">
        {activeView === "map" ? (
          <section aria-label="Dashboard workspace" className="workspace-stage workspace-stage--map">
            <Suspense fallback={<ViewLoader label="Memuat tampilan peta..." />}>
              <HotspotMap
                hotspots={hotspots}
                layers={layers}
                selectedProvince={selectedProvince}
                showWind={showWind}
              />
            </Suspense>

            {showPanels && (
              <>
                {/* Mobile Filter Toggle Button */}
                <button
                  className="mobile-filter-btn"
                  onClick={() => setMobileFilterOpen(!mobileFilterOpen)}
                  aria-label="Toggle filter panel"
                >
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
                </button>

                <aside className={`control-overlay control-overlay--top-left${mobileFilterOpen ? ' mobile-open' : ''}`}>
                              <FilterPanel
                                layers={layers}
                                selectedSatellites={selectedSatellites}
                                timePreset={timePreset}
                                onToggleLayer={toggleLayer}
                                onToggleSatellite={toggleSatellite}
                                onTimePresetChange={setTimePreset}
                                onDateChange={updateDate}
                                startDate={startDate}
                                endDate={endDate}
                                hotspotCount={stats.hotspotCount}
                                selectedProvince={selectedProvince}
                                onProvinceChange={setSelectedProvince}
                                provinceOptions={provinceOptions}
                                showWind={showWind}
                                onToggleWind={() => setShowWind(w => !w)}
                              />
                            </aside>
                
                            <aside className="control-overlay control-overlay--top-right panel panel--stats" style={{ maxHeight: '100%', overflowY: 'auto', overflowX: 'hidden' }}>
                  <article className="metric-card" style={{ padding: '0.65rem 0.75rem' }}>
                    <p className="metric-label" style={{ textTransform: 'uppercase', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.3rem', fontSize: '0.72rem' }}>
                      Titik Panas (FRP)
                      <span title="Kategori Intensitas Panas (FRP)&#10;&#10;Tinggi: > 30 MW&#10;Sedang: 10–30 MW&#10;Rendah: < 10 MW&#10;&#10;FRP (Fire Radiative Power) menunjukkan tingkat energi panas yang dipancarkan oleh hotspot yang terdeteksi satelit." style={{ cursor: 'help', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '13px', height: '13px', borderRadius: '50%', border: '1px solid currentColor', fontSize: '9px', flexShrink: 0 }}>i</span>
                    </p>

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
              </>
            )}
            
            <button 
              onClick={() => setShowPanels(p => !p)} 
              title={showPanels ? "Sembunyikan Panel" : "Tampilkan Panel"}
              style={{
                position: 'absolute',
                bottom: '30px',
                left: '50%',
                transform: 'translateX(-50%)',
                zIndex: 1000,
                background: 'rgba(15, 23, 42, 0.7)',
                backdropFilter: 'blur(8px)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                color: '#fff',
                padding: '8px 16px',
                borderRadius: '9999px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                cursor: 'pointer',
                boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
                transition: 'all 0.2s',
                fontSize: '0.875rem',
                fontWeight: '500'
              }}
            >
              {showPanels ? <Minimize size={16} /> : <Maximize size={16} />}
              {showPanels ? "Sembunyikan UI" : "Tampilkan UI"}
            </button>

            {loadError ? <p className="toast-error">{loadError}</p> : null}
            {exportError ? <p className="toast-error toast-error--bottom">{exportError}</p> : null}
            {syncError ? <p className="toast-error toast-error--bottom">{syncError}</p> : null}
          </section>
        ) : activeView === "matrix" ? (
          <section aria-label="Matrix workspace" className="workspace-stage workspace-stage--matrix">
            <Suspense fallback={<ViewLoader label="Memuat matriks data..." />}>
              <HotspotMatrix
                hotspots={hotspots.map((hotspot) => ({
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
                  daynight: hotspot.daynight
                }))}
                geojsonStatus={geojsonStatus}
                onExport={(filters) => void exportDashboard(filters)}
                isExporting={isExporting}
                onExportPdf={(filters) => void exportPdf(filters)}
                isExportingPdf={isExportingPdf}
                onDateChange={updateDate}
                startDate={startDate}
                endDate={endDate}
                dateRangeLabel={timeRange.label}
              />
            </Suspense>
          </section>
        ) : activeView === "settings" ? (
          <section aria-label="Settings workspace" className="workspace-stage">
            <Suspense fallback={<ViewLoader label="Memuat pengaturan..." />}>
              <SettingsPanel onRefreshLayers={() => void retryInitialLoad()} />
            </Suspense>
          </section>
        ) : (
          <Suspense fallback={<ViewLoader label="Memuat pemantauan..." />}>
            <MonitoringPanel
              metrics={schedulerMetrics}
              hotspots={hotspots}
              layers={layers}
              onManualSync={() => void manualSync()}
              onPrewarmHistory={() => void prewarmHistory()}
              manualSyncBusy={isTriggeringManualSync}
              prewarmBusy={isPrewarming}
              autoRefreshActive
              refreshing={isRefreshingScheduler}
              signalChangeNotice={signalChangeNotice}
              audioMuted={audioMuted}
              onToggleAudioMuted={() => setAudioMuted((current) => !current)}
              alertVolume={alertVolume}
              onToggleAlertVolume={() =>
                setAlertVolume((current) => (current === "normal" ? "low" : "normal"))
              }
              onDismissSignalChangeNotice={() => setSignalChangeNotice(null)}
            />
          </Suspense>
        )}
      </main>

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
