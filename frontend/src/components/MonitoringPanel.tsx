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
  const signalBanner =
    (metrics?.consecutive_failures ?? 0) > 1
      ? {
          tone: "danger",
          title: "Scheduler memerlukan perhatian",
          body: metrics?.last_error || "Sync terakhir gagal beberapa kali dan perlu ditindaklanjuti."
        }
      : isSchedulerFailureStatus(metrics?.last_sync_status) || (metrics?.consecutive_failures ?? 0) === 1
        ? {
            tone: "warn",
            title: "Sync scheduler gagal sekali",
            body: metrics?.last_error || "Terjadi kesalahan pada sync terakhir. Scheduler akan mencoba lagi sesuai jadwal."
          }
        : metrics?.new_hotspot_over_threshold
          ? {
              tone: "danger",
              title: "Ambang batas terlampaui",
              body: "Jumlah hotspot baru pada sync terakhir melebihi ambang operasional."
            }
          : metrics?.has_new_hotspot
          ? {
              tone: "warn",
              title: "Sinyal insiden baru",
              body: "Scheduler mendeteksi hotspot baru sejak sync sukses sebelumnya."
            }
          : null;

  const refreshLabel = refreshing ? "Menyegarkan telemetri..." : "Auto-refresh aktif setiap 60 detik";

  return (
    <section aria-label="Monitoring workspace" className="workspace-stage workspace-stage--monitoring">
      <div className="monitor-shell">
        <section className={`panel glass-panel monitor-hero monitor-hero--${healthTone}`}>
          <div className="monitor-hero-copy">
            <p className="monitor-eyebrow">Pusat operasi kebakaran</p>
            <h1 className="monitor-title">Pemantauan Insiden</h1>
            <p className="monitor-description">
              Halaman ini hanya menampilkan sinyal operasional scheduler dan alert hotspot baru,
              tanpa mengulang peta atau tabel investigasi.
            </p>
          </div>

          <div className="monitor-hero-status">
            {autoRefreshActive ? (
              <div className={`monitor-refresh-chip${refreshing ? " monitor-refresh-chip--active" : ""}`}>
                <span className="monitor-refresh-dot" aria-hidden="true" />
                <span>{refreshLabel}</span>
              </div>
            ) : null}
            <div className={`monitor-pulse monitor-pulse--${healthTone}`}>
              <span className="monitor-pulse-dot" aria-hidden="true" />
              <span>Denyut Scheduler</span>
            </div>
            <strong className="monitor-status-value">{healthLabel}</strong>
            <span className="monitor-status-caption">
              {metrics?.scheduler_enabled ? "Scheduler aktif" : "Scheduler nonaktif"}
            </span>
            <div className="monitor-action-row">
              <button
                type="button"
                className={`monitor-sync${manualSyncBusy ? " monitor-sync--busy" : ""}`}
                onClick={onManualSync}
                disabled={manualSyncBusy}
                aria-busy={manualSyncBusy}
              >
                <span className="sync-button-label">
                  {manualSyncBusy ? "Sync Hotspot..." : "Sync Hotspot Manual"}
                </span>
                {manualSyncBusy ? (
                  <span className="sync-button-progress" aria-hidden="true">
                    <span className="sync-button-progress-bar" />
                  </span>
                ) : null}
              </button>
              <button
                type="button"
                className={`monitor-sync monitor-sync--ghost${prewarmBusy ? " monitor-sync--busy" : ""}`}
                onClick={onPrewarmHistory}
                disabled={prewarmBusy}
                aria-busy={prewarmBusy}
              >
                <span className="sync-button-label">
                  {prewarmBusy ? "Menyiapkan Histori..." : "Prewarm Histori"}
                </span>
                {prewarmBusy ? (
                  <span className="sync-button-progress" aria-hidden="true">
                    <span className="sync-button-progress-bar" />
                  </span>
                ) : null}
              </button>
            </div>
            <button type="button" className="monitor-audio-toggle" onClick={onToggleAudioMuted}>
              {audioMuted ? "Bunyikan Suara Peringatan" : "Bisukan Suara Peringatan"}
            </button>
            <button type="button" className="monitor-audio-toggle" onClick={onToggleAlertVolume}>
              {`Volume Peringatan ${alertVolume}`}
            </button>
          </div>
        </section>

        {signalBanner ? (
          <section className={`panel glass-panel monitor-banner monitor-banner--${signalBanner.tone}`}>
            <div>
              <p className="monitor-eyebrow">Peringatan visual</p>
              <strong className="monitor-banner-title">{signalBanner.title}</strong>
            </div>
            <p className="monitor-banner-body">{signalBanner.body}</p>
          </section>
        ) : null}

        {signalChangeNotice ? (
          <section className="panel glass-panel monitor-change-banner">
            <div className="monitor-change-banner-head">
              <div>
                <p className="monitor-eyebrow">Perubahan terdeteksi</p>
                <strong className="monitor-banner-title">{signalChangeNotice}</strong>
              </div>
              <button
                type="button"
                className="monitor-dismiss"
                onClick={onDismissSignalChangeNotice}
              >
                Dismiss Status Change
              </button>
            </div>
          </section>
        ) : null}

        <section className="monitor-grid" aria-label="Operational metrics">
          <article className="panel glass-panel monitor-card monitor-card--signal">
            <p className="monitor-card-label">Hotspot Baru</p>
            <strong className="monitor-card-value">
              {metrics?.last_new_hotspot_count ?? 0}
            </strong>
            <span className="monitor-card-meta">
              {metrics?.new_hotspot_over_threshold ? "Melewati threshold" : "Dalam batas pantau"}
            </span>
          </article>

          <article className="panel glass-panel monitor-card">
            <p className="monitor-card-label">Sinkronisasi Terakhir</p>
            <strong className="monitor-card-value monitor-card-value--small">
              {formatTimestamp(metrics?.last_sync_at ?? null)}
            </strong>
            <span className="monitor-card-meta">
              {formatDuration(metrics?.seconds_since_last_sync ?? null)} lalu
            </span>
          </article>

          <article className="panel glass-panel monitor-card">
            <p className="monitor-card-label">Sinkronisasi Berikutnya</p>
            <strong className="monitor-card-value monitor-card-value--small">
              {formatTimestamp(metrics?.next_scheduled_sync_at ?? null)}
            </strong>
            <span className="monitor-card-meta">
              Interval {metrics?.interval_hours ?? 0} jam
            </span>
          </article>

          <article className="panel glass-panel monitor-card">
            <p className="monitor-card-label">Kegagalan Beruntun</p>
            <strong className="monitor-card-value">{metrics?.consecutive_failures ?? 0}</strong>
            <span className="monitor-card-meta">
              {metrics?.last_error ? metrics.last_error : "Tidak ada error aktif"}
            </span>
          </article>
        </section>

        <section className="monitor-detail-grid">
          <article className="panel glass-panel monitor-detail-card">
            <p className="monitor-detail-label">Pantauan Ambang Batas</p>
            <div className="monitor-flag-stack">
              <div className={`monitor-flag${metrics?.has_new_hotspot ? " monitor-flag--warn" : ""}`}>
                <span>Ada hotspot baru</span>
                <strong>{metrics?.has_new_hotspot ? "YA" : "TIDAK"}</strong>
              </div>
              <div
                className={`monitor-flag${metrics?.new_hotspot_over_threshold ? " monitor-flag--danger" : ""}`}
              >
                <span>Melebihi ambang batas</span>
                <strong>{metrics?.new_hotspot_over_threshold ? "YA" : "TIDAK"}</strong>
              </div>
            </div>
          </article>

          <article className="panel glass-panel monitor-detail-card">
            <p className="monitor-detail-label">Catatan Operasional</p>
            <ul className="monitor-note-list">
              <li>
                Threshold aktif: <strong>{metrics?.new_hotspot_alert_threshold ?? 0}</strong> hotspot baru.
              </li>
              <li>
                Sync sukses terakhir:{" "}
                <strong>{formatDuration(metrics?.seconds_since_last_successful_sync ?? null)} lalu</strong>.
              </li>
              <li>
                Sampel sync terakhir memuat <strong>{metrics?.last_sync_hotspot_count ?? 0}</strong> hotspot.
              </li>
            </ul>
          </article>
        </section>

        <section className="panel glass-panel monitor-hotspots-card">
          <header className="monitor-hotspots-header">
            <h2 className="monitor-hotspots-title">
              <span className="monitor-hotspots-icon" aria-hidden="true">🔥</span>
              Alert Hotspot Aktif (24 Jam Terakhir)
            </h2>
            <span className="monitor-hotspots-count">
              {active24hHotspots.length} Hotspot
            </span>
          </header>
          
          <div className="monitor-hotspots-list">
            {active24hHotspots.length === 0 ? (
              <div className="hotspot-empty">
                Tidak ada hotspot aktif terdeteksi dalam 24 jam terakhir.
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
                          Radiasi (FRP): <strong>{h.frp} MW</strong>
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
