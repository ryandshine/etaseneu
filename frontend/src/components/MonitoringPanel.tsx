import { useMemo, useState, useEffect } from "react";
import type { SchedulerMetricsResponse } from "../types/api";
import type { DashboardHotspot } from "../hooks/useDashboardData";

type MonitoringPanelProps = {
  metrics: SchedulerMetricsResponse | null;
  hotspots: DashboardHotspot[];
  onManualSync: () => void;
  onPrewarmHistory: () => void;
  manualSyncBusy: boolean;
  prewarmBusy: boolean;
  autoRefreshActive: boolean;
  refreshing: boolean;
  signalChangeNotice: string | null;
  audioMuted: boolean;
  onToggleAudioMuted: () => void;
  alertVolume: "normal" | "low";
  onToggleAlertVolume: () => void;
  onDismissSignalChangeNotice: () => void;
};

function getHotspotAgeLabel(detectedAtStr: string): string {
  const detectedAt = new Date(detectedAtStr);
  if (Number.isNaN(detectedAt.getTime())) {
    return "Waktu tidak diketahui";
  }
  const diffMs = Date.now() - detectedAt.getTime();
  if (diffMs < 0) {
    return "Baru saja";
  }
  const diffMins = Math.floor(diffMs / (1000 * 60));
  if (diffMins < 60) {
    return `${diffMins} menit yang lalu`;
  }
  const diffHours = Math.floor(diffMins / 60);
  const remainderMins = diffMins % 60;
  if (diffHours < 24) {
    return remainderMins > 0
      ? `${diffHours} jam ${remainderMins} menit yang lalu`
      : `${diffHours} jam yang lalu`;
  }
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays} hari yang lalu`;
}

function getAgeLevel(detectedAtStr: string): "new" | "medium" | "old" {
  const detectedAt = new Date(detectedAtStr);
  if (Number.isNaN(detectedAt.getTime())) {
    return "old";
  }
  const diffMs = Date.now() - detectedAt.getTime();
  const diffHours = diffMs / (1000 * 60 * 60);
  if (diffHours < 3) {
    return "new";
  }
  if (diffHours < 12) {
    return "medium";
  }
  return "old";
}

function isSchedulerFailureStatus(status?: string | null): boolean {
  return status === "failure" || status === "failed";
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Belum ada data";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Belum ada data";
  }

  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Jakarta",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
    const parts = formatter.formatToParts(parsed);
    const year = parts.find(p => p.type === "year")?.value ?? "";
    const month = parts.find(p => p.type === "month")?.value ?? "";
    const day = parts.find(p => p.type === "day")?.value ?? "";
    const hour = parts.find(p => p.type === "hour")?.value ?? "";
    const minute = parts.find(p => p.type === "minute")?.value ?? "";
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  } catch (e) {
    const wibTime = new Date(parsed.getTime() + 7 * 60 * 60 * 1000);
    const day = String(wibTime.getUTCDate()).padStart(2, '0');
    const month = String(wibTime.getUTCMonth() + 1).padStart(2, '0');
    const year = wibTime.getUTCFullYear();
    const hour = String(wibTime.getUTCHours()).padStart(2, '0');
    const minute = String(wibTime.getUTCMinutes()).padStart(2, '0');
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  }
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || Number.isNaN(seconds)) {
    return "Belum tersedia";
  }

  if (seconds < 60) {
    return `${Math.round(seconds)} detik`;
  }

  const minutes = Math.round(seconds / 60);
  if (minutes < 60) {
    return `${minutes} menit`;
  }

  const hours = Math.floor(minutes / 60);
  const remainderMinutes = minutes % 60;
  return remainderMinutes === 0 ? `${hours} jam` : `${hours} jam ${remainderMinutes} menit`;
}

function getHealthTone(metrics: SchedulerMetricsResponse | null): "ok" | "warn" | "danger" {
  if (!metrics) {
    return "warn";
  }

  if (metrics.consecutive_failures > 1) {
    return "danger";
  }

  if (isSchedulerFailureStatus(metrics.last_sync_status) || metrics.consecutive_failures === 1) {
    return "warn";
  }

  if (metrics.new_hotspot_over_threshold || metrics.has_new_hotspot) {
    return "warn";
  }

  return "ok";
}

function getHealthLabel(metrics: SchedulerMetricsResponse | null): string {
  if (!metrics) {
    return "Tidak ada telemetri";
  }

  if (metrics.consecutive_failures > 1) {
    return "Gagal";
  }

  if (isSchedulerFailureStatus(metrics.last_sync_status) || metrics.consecutive_failures === 1) {
    return "Gagal Sekali";
  }

  if (metrics.new_hotspot_over_threshold) {
    return "Peringatan";
  }

  if (metrics.has_new_hotspot) {
    return "Insiden";
  }

  if (metrics.last_sync_status === "success") {
    return "Sehat";
  }

  return "Menunggu";
}

export function MonitoringPanel({
  metrics,
  hotspots,
  onManualSync,
  onPrewarmHistory,
  manualSyncBusy,
  prewarmBusy,
  autoRefreshActive,
  refreshing,
  signalChangeNotice,
  audioMuted,
  onToggleAudioMuted,
  alertVolume,
  onToggleAlertVolume,
  onDismissSignalChangeNotice
}: MonitoringPanelProps) {
  const [clockTick, setClockTick] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setClockTick((prev) => prev + 1);
    }, 30000);
    return () => clearInterval(timer);
  }, []);

  const active24hHotspots = useMemo(() => {
    const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000;
    return hotspots
      .filter((h) => {
        const time = new Date(h.detectedAt).getTime();
        return !Number.isNaN(time) && time >= oneDayAgo;
      })
      .sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime());
  }, [hotspots, clockTick]);

  const healthTone = getHealthTone(metrics);
  const healthLabel = getHealthLabel(metrics);
  const commanderStatus = useMemo(() => {
    if (healthTone === "danger") {
      return {
        label: "STATUS OPERASI: SIAGA I (BAHAYA)",
        desc: "Terdeteksi ancaman hotspot kritis atau gangguan sinkronisasi beruntun. Tindakan segera diperlukan!",
        colorClass: "commander-status--danger",
        icon: "🚨"
      };
    } else if (healthTone === "warn") {
      return {
        label: "STATUS OPERASI: SIAGA II (WASPADA)",
        desc: "Terjadi gangguan sinkronisasi sementara atau terdeteksi hotspot baru dalam batas normal.",
        colorClass: "commander-status--warn",
        icon: "⚠️"
      };
    } else {
      return {
        label: "STATUS OPERASI: NORMAL (AMAN)",
        desc: "Sistem aktif memantau. Seluruh wilayah terpantau aman tanpa titik api kritis baru.",
        colorClass: "commander-status--ok",
        icon: "🛡️"
      };
    }
  }, [healthTone]);

  const refreshLabel = refreshing ? "Menyegarkan data..." : "Patroli otomatis aktif setiap 60 detik";

  return (
    <section aria-label="Monitoring workspace" className="workspace-stage workspace-stage--monitoring">
      <div className="monitor-shell commander-shell">
        
        {/* ZONA 1: BANNER STATUS KOMANDO UTAMA */}
        <section className={`panel glass-panel commander-hero ${commanderStatus.colorClass}`}>
          <div className="commander-hero-radar">
            <span className="radar-circle circle-1" />
            <span className="radar-circle circle-2" />
            <span className="radar-circle circle-3" />
            <span className="radar-icon">{commanderStatus.icon}</span>
          </div>
          <div className="commander-hero-info">
            <span className="commander-hero-eyebrow">COMMANDER OPERATIONS CENTER</span>
            <h1 className="commander-hero-title">{commanderStatus.label}</h1>
            <p className="commander-hero-desc">{commanderStatus.desc}</p>
          </div>
          <div className="commander-hero-meta">
            {autoRefreshActive && (
              <div className={`commander-pulse-badge ${refreshing ? "commander-pulse-badge--active" : ""}`}>
                <span className="pulse-dot" />
                <span>{refreshLabel}</span>
              </div>
            )}
            <div className="system-time">
              <span>WAKTU LOKAL:</span>
              <strong>{new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })} WIB</strong>
            </div>
          </div>
        </section>

        {/* NOTIFIKASI PERUBAHAN STATUS */}
        {signalChangeNotice && (
          <section className="panel glass-panel commander-alert-banner">
            <div className="alert-banner-content">
              <span className="alert-banner-badge">PERUBAHAN DETEKSI</span>
              <strong className="alert-banner-text">{signalChangeNotice}</strong>
            </div>
            <button
              type="button"
              className="alert-banner-dismiss"
              onClick={onDismissSignalChangeNotice}
            >
              TUTUP NOTIFIKASI
            </button>
          </section>
        )}

        {/* ZONA 2: COMMANDER BOARD (KARTU STRATEGIS) */}
        <section className="commander-grid" aria-label="Operational metrics">
          
          <article className="panel glass-panel commander-card commander-card--hotspots">
            <div className="card-header">
              <span className="card-icon">🔥</span>
              <span className="card-label">Ancaman Kebakaran</span>
            </div>
            <div className="card-body">
              <strong className="card-value">{metrics?.last_new_hotspot_count ?? 0}</strong>
              <span className="card-unit">Hotspot Baru</span>
            </div>
            <div className="card-footer">
              <span className="card-meta">Ambang Batas: {metrics?.new_hotspot_alert_threshold ?? 0}</span>
              <span className={`card-badge ${metrics?.new_hotspot_over_threshold ? "card-badge--danger" : "card-badge--ok"}`}>
                {metrics?.new_hotspot_over_threshold ? "SIAGA ANCAMAN" : "AMAN"}
              </span>
            </div>
          </article>

          <article className="panel glass-panel commander-card commander-card--koneksi">
            <div className="card-header">
              <span className="card-icon">📡</span>
              <span className="card-label">Status Sinkronisasi</span>
            </div>
            <div className="card-body">
              <strong className="card-value">
                {metrics?.last_sync_status === "success" ? "SUKSES" : "GAGAL"}
              </strong>
              <span className="card-unit">Koneksi NASA</span>
            </div>
            <div className="card-footer">
              <span className="card-meta">Kegagalan Beruntun: {metrics?.consecutive_failures ?? 0}</span>
              <span className={`card-badge ${metrics?.consecutive_failures && metrics.consecutive_failures > 0 ? "card-badge--danger" : "card-badge--ok"}`}>
                {metrics?.consecutive_failures && metrics.consecutive_failures > 0 ? "GANGGUAN" : "ONLINE"}
              </span>
            </div>
          </article>

          <article className="panel glass-panel commander-card commander-card--terakhir">
            <div className="card-header">
              <span className="card-icon">⏱️</span>
              <span className="card-label">Pemeriksaan Terakhir</span>
            </div>
            <div className="card-body">
              <strong className="card-value card-value--small">
                {formatDuration(metrics?.seconds_since_last_sync ?? null)}
              </strong>
              <span className="card-unit">Yang lalu</span>
            </div>
            <div className="card-footer">
              <span className="card-meta" title={metrics?.last_sync_at ?? ""}>
                Waktu: {metrics?.last_sync_at ? formatTimestamp(metrics.last_sync_at).split(" ")[1] : "Belum ada"} WIB
              </span>
              <span className="card-badge card-badge--neutral">TERBARU</span>
            </div>
          </article>

          <article className="panel glass-panel commander-card commander-card--patroli">
            <div className="card-header">
              <span className="card-icon">📅</span>
              <span className="card-label">Patroli Otomatis</span>
            </div>
            <div className="card-body">
              <strong className="card-value card-value--small">
                {metrics?.next_scheduled_sync_at ? formatTimestamp(metrics.next_scheduled_sync_at).split(" ")[1] : "--:--"}
              </strong>
              <span className="card-unit">WIB</span>
            </div>
            <div className="card-footer">
              <span className="card-meta">Interval: {metrics?.interval_hours ?? 0} Jam</span>
              <span className="card-badge card-badge--neutral">TERJADWAL</span>
            </div>
          </article>

        </section>

        {/* ZONA 3 & ZONA 4: PANEL KENDALI & TIMELINE */}
        <section className="commander-sub-grid">
          
          {/* PANEL KENDALI COCKPIT */}
          <article className="panel glass-panel commander-cockpit">
            <div className="cockpit-header">
              <h3 className="cockpit-title">🎛️ PANEL KENDALI TAKTIS</h3>
              <span className={`cockpit-badge ${metrics?.scheduler_enabled ? "cockpit-badge--active" : ""}`}>
                {metrics?.scheduler_enabled ? "AUTO-PATROL AKTIF" : "AUTO-PATROL MATI"}
              </span>
            </div>
            
            <div className="cockpit-actions">
              <button
                type="button"
                className={`cockpit-btn cockpit-btn--primary ${manualSyncBusy ? "cockpit-btn--busy" : ""}`}
                onClick={onManualSync}
                disabled={manualSyncBusy}
              >
                {manualSyncBusy ? (
                  <>
                    <span className="spinner" />
                    <span>SINKRONISASI DATA...</span>
                  </>
                ) : (
                  <span>🔄 TARIK DATA NASA SEKARANG</span>
                )}
              </button>

              <button
                type="button"
                className={`cockpit-btn cockpit-btn--secondary ${prewarmBusy ? "cockpit-btn--busy" : ""}`}
                onClick={onPrewarmHistory}
                disabled={prewarmBusy}
              >
                {prewarmBusy ? (
                  <>
                    <span className="spinner" />
                    <span>MENYIAPKAN HISTORI...</span>
                  </>
                ) : (
                  <span>⚡ PREWARM HISTORI CEPAT</span>
                )}
              </button>
            </div>

            <div className="cockpit-settings">
              <div className="setting-control">
                <span>Sirene Suara:</span>
                <button type="button" className="setting-btn" onClick={onToggleAudioMuted}>
                  {audioMuted ? "🔇 BISU (MUTED)" : "🔊 AKTIF (UNMUTED)"}
                </button>
              </div>
              <div className="setting-control">
                <span>Volume Alarm:</span>
                <button type="button" className="setting-btn" onClick={onToggleAlertVolume}>
                  {alertVolume === "normal" ? "🔊 HIGH" : "🔉 LOW"}
                </button>
              </div>
            </div>
          </article>

          {/* KRONOLOGI AKTIVITAS SISTEM */}
          <article className="panel glass-panel commander-timeline-card">
            <h3 className="timeline-card-title">📝 KRONOLOGI AKTIVITAS SISTEM</h3>
            <div className="commander-timeline">
              
              <div className="timeline-item">
                <div className="timeline-badge timeline-badge--ok">STATUS</div>
                <div className="timeline-content">
                  <strong>Sistem Patroli Mandiri Aktif</strong>
                  <p>Mengecek data satelit NASA MODIS & VIIRS setiap {metrics?.interval_hours ?? 0} jam. Tingkat sensitivitas peringatan aktif adalah {metrics?.new_hotspot_alert_threshold ?? 0} hotspot baru.</p>
                </div>
              </div>

              <div className="timeline-item">
                <div className="timeline-badge timeline-badge--info">DATA</div>
                <div className="timeline-content">
                  <strong>Sinkronisasi Sukses Terakhir</strong>
                  <p>Dilakukan {formatDuration(metrics?.seconds_since_last_successful_sync ?? null)} lalu dengan memproses {metrics?.last_sync_hotspot_count ?? 0} titik hotspot terdaftar.</p>
                </div>
              </div>

              {metrics?.last_error && (
                <div className="timeline-item timeline-item--danger">
                  <div className="timeline-badge timeline-badge--danger">ERROR</div>
                  <div className="timeline-content">
                    <strong className="error-title">Kesalahan Sinkronisasi Terdeteksi</strong>
                    <p className="error-desc">{metrics.last_error}</p>
                  </div>
                </div>
              )}

            </div>
          </article>

        </section>

        {/* FEED 24 JAM HOTSPOT */}
        <section className="panel glass-panel commander-hotspots-section monitor-hotspots-card">
          <header className="monitor-hotspots-header">
            <h2 className="monitor-hotspots-title">
              <span className="monitor-hotspots-icon" aria-hidden="true">🔥</span>
              DAFTAR ANCAMAN HOTSPOT (24 JAM TERAKHIR)
            </h2>
            <span className="monitor-hotspots-count">
              {active24hHotspots.length} TITIK
            </span>
          </header>
          
          <div className="monitor-hotspots-list">
            {active24hHotspots.length === 0 ? (
              <div className="hotspot-empty">
                Tidak ada ancaman hotspot aktif yang terdeteksi dalam 24 jam terakhir.
              </div>
            ) : (
              active24hHotspots.map((h) => {
                const ageLevel = getAgeLevel(h.detectedAt);
                const ageLabel = getHotspotAgeLabel(h.detectedAt);
                
                return (
                  <article key={h.id} className="hotspot-item">
                    <div className="hotspot-meta-col">
                      <div className="hotspot-badge-container">
                        <span className={`hotspot-badge hotspot-badge--${ageLevel}`}>
                          {ageLevel === "new" ? "Sangat Baru" : ageLevel === "medium" ? "Sedang" : "Lama"}
                        </span>
                        <span className="hotspot-badge hotspot-badge--source">
                          {h.source}
                        </span>
                      </div>
                      <span className="hotspot-sensor">
                        🛰️ {h.satellite}
                      </span>
                      <span className="hotspot-conf">
                        Conf: {h.confidence || "Unknown"}
                      </span>
                    </div>
                    
                    <div className="hotspot-info-col">
                      <div className="hotspot-loc" title={h.agencyName || h.layerName || "Umum"}>
                        {h.agencyName || h.layerName || "Umum"}
                      </div>
                      <div className="hotspot-subloc" title={h.provinceName}>
                        Provinsi: {h.provinceName || "-"}
                      </div>
                      {h.frp !== null && (
                        <div className="hotspot-frp">
                          Kekuatan Radiasi (FRP): <strong>{h.frp} MW</strong>
                        </div>
                      )}
                    </div>
                    
                    <div className="hotspot-action-col">
                      <time className="hotspot-age" dateTime={h.detectedAt}>
                        {ageLabel}
                      </time>
                      <a
                        href={`https://www.google.com/maps/search/?api=1&query=${h.latitude},${h.longitude}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hotspot-link"
                        title="Buka lokasi di Google Maps"
                      >
                        📍 {h.latitude.toFixed(5)}, {h.longitude.toFixed(5)}
                      </a>
                    </div>
                  </article>
                );
              })
            )}
          </div>
        </section>

      </div>
    </section>
  );
}
