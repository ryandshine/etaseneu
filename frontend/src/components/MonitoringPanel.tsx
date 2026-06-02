import type { SchedulerMetricsResponse } from "../types/api";

type MonitoringPanelProps = {
  metrics: SchedulerMetricsResponse | null;
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

  if (isSchedulerFailureStatus(metrics.last_sync_status) || metrics.consecutive_failures > 0) {
    return "danger";
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

  if (isSchedulerFailureStatus(metrics.last_sync_status)) {
    return "Gagal";
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
  const healthTone = getHealthTone(metrics);
  const healthLabel = getHealthLabel(metrics);
  const signalBanner =
    isSchedulerFailureStatus(metrics?.last_sync_status)
      ? {
          tone: "danger",
          title: "Scheduler memerlukan perhatian",
          body: metrics?.last_error || "Sync terakhir gagal dan perlu ditindaklanjuti."
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
      </div>
    </section>
  );
}
