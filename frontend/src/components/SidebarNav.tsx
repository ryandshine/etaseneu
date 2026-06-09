type SidebarNavProps = {
  activeView: "map" | "matrix" | "monitoring" | "settings";
  onChangeView: (view: "map" | "matrix" | "monitoring" | "settings") => void;
  onManualSync: () => void;
  onPrewarmHistory: () => void;
  syncLabel: string;
  syncStatusLabel: string;
  lastSyncLabel: string;
  manualSyncBusy: boolean;
  prewarmBusy: boolean;
  monitoringSignal: "normal" | "incident" | "critical";
  healthStatus: "normal" | "warning" | "error";
  healthLabel: string;
  schedulerStatusLabel: string;
  schedulerStatusColor: string;
  schedulerStatusBg: string;
  syncTodayRatio: string;
  syncInterval: string;
  nextScheduledSyncLabel: string;
  latestHotspotTimeLabel: string;
  dataAgeLabel: string;
  hasLatestHotspot: boolean;
};

function NavButton({
  active,
  children,
  onClick
}: {
  active: boolean;
  children: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`side-nav-link${active ? " side-nav-link--active" : ""}`}
    >
      <span className="side-nav-mark" aria-hidden="true" />
      <span>{children}</span>
    </button>
  );
}

export function SidebarNav({
  activeView,
  onChangeView,
  onManualSync,
  onPrewarmHistory,
  syncLabel,
  syncStatusLabel,
  lastSyncLabel,
  manualSyncBusy,
  prewarmBusy,
  monitoringSignal,
  healthStatus,
  healthLabel,
  schedulerStatusLabel,
  schedulerStatusColor,
  schedulerStatusBg,
  syncTodayRatio,
  syncInterval,
  nextScheduledSyncLabel,
  latestHotspotTimeLabel,
  dataAgeLabel,
  hasLatestHotspot
}: SidebarNavProps) {
  return (
    <aside className="side-rail">
      <div className="side-brand">
        <div>
          <div className="side-brand-name">ETAseneu</div>
          <div className="side-brand-sub">KPS Hotspot Monitoring</div>
        </div>
      </div>

      <nav className="side-nav" aria-label="Utama">
        <p className="side-nav-label">Navigasi</p>
        <NavButton active={activeView === "map"} onClick={() => onChangeView("map")}>
          LIVE MAP
        </NavButton>
        <NavButton active={activeView === "matrix"} onClick={() => onChangeView("matrix")}>
          Matriks Data
        </NavButton>
        <button
          type="button"
          onClick={() => onChangeView("monitoring")}
          className={`side-nav-link${activeView === "monitoring" ? " side-nav-link--active" : ""}`}
        >
          <span className="side-nav-mark" aria-hidden="true" />
          <span>Pemantauan</span>
          {monitoringSignal !== "normal" ? (
            <span
              className={`side-nav-alert side-nav-alert--${
                monitoringSignal === "critical" ? "critical" : "incident"
              }`}
            >
              PERINGATAN
            </span>
          ) : null}
        </button>
        <button
          type="button"
          onClick={() => onChangeView("settings")}
          className={`side-nav-link${activeView === "settings" ? " side-nav-link--active" : ""}`}
        >
          <span className="side-nav-mark" aria-hidden="true" />
          <span>Pengaturan</span>
        </button>
      </nav>

      <div className="side-footer" style={{ padding: '0.75rem', fontSize: '0.75rem' }}>
        <div className="side-footer-block" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0.5rem', marginBottom: '0.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
            <span className="side-footer-label" style={{ fontWeight: '600', letterSpacing: '0.03em', textTransform: 'uppercase', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              Sinkronisasi NASA
              <span 
                title="Info Sinkronisasi NASA&#10;&#10;Tidak adanya hotspot baru tidak selalu berarti sinkronisasi gagal.&#10;&#10;Periksa:&#10;- Last Sync&#10;- Next Sync&#10;- Hotspot Terbaru&#10;- Status Scheduler" 
                style={{ cursor: 'help', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '12px', height: '12px', borderRadius: '50%', border: '1px solid currentColor', fontSize: '8px' }}
              >
                i
              </span>
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <span style={{ 
                width: '6px', 
                height: '6px', 
                borderRadius: '50%', 
                backgroundColor: healthStatus === 'normal' ? '#10b981' : healthStatus === 'warning' ? '#f59e0b' : '#ef4444',
                boxShadow: `0 0 6px ${healthStatus === 'normal' ? '#10b981' : healthStatus === 'warning' ? '#f59e0b' : '#ef4444'}`
              }} />
              <span style={{ fontSize: '0.65rem', fontWeight: 'bold', color: healthStatus === 'normal' ? '#10b981' : healthStatus === 'warning' ? '#f59e0b' : '#ef4444' }}>
                {healthStatus === 'normal' ? 'OK' : healthStatus === 'warning' ? 'LATE' : 'ERR'}
              </span>
            </div>
          </div>
          
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.3rem', color: '#9ca3af', fontSize: '0.7rem' }}>
            <div>
              <span>Scheduler: </span>
              <strong style={{ color: schedulerStatusColor, backgroundColor: schedulerStatusBg, padding: '0.05rem 0.25rem', borderRadius: '3px', fontSize: '0.65rem' }}>
                {schedulerStatusLabel}
              </strong>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span>Sync Hari Ini: </span>
              <strong style={{ color: '#fff' }}>{syncTodayRatio}</strong>
            </div>
            <div>
              <span>Interval: </span>
              <strong style={{ color: '#fff' }}>{syncInterval}</strong>
            </div>
            <div style={{ textAlign: 'right' }}>
              <span>Database: </span>
              <strong style={{ color: '#fff' }}>{syncLabel}</strong>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', fontSize: '0.68rem', color: '#9ca3af', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0.5rem', marginBottom: '0.5rem' }}>
          <div>
            <span>LAST SYNC: </span>
            <strong style={{ color: '#fff' }}>{lastSyncLabel}</strong>
          </div>
          <div>
            <span>NEXT SYNC: </span>
            <strong style={{ color: '#fff' }}>{nextScheduledSyncLabel}</strong>
          </div>
          <div style={{ borderTop: '1px dashed rgba(255,255,255,0.05)', paddingTop: '0.25rem', marginTop: '0.25rem' }}>
            <span>HOTSPOT TERBARU: </span>
            <strong style={{ color: '#fff', display: 'block' }}>{latestHotspotTimeLabel}</strong>
          </div>
          <div>
            <span>USIA DATA: </span>
            <strong style={{ color: hasLatestHotspot ? '#fff' : '#6b7280', fontSize: hasLatestHotspot ? '0.68rem' : '0.62rem' }}>
              {dataAgeLabel}
            </strong>
          </div>
        </div>
        <div className="side-sync-actions">
          <button
            type="button"
            className={`side-sync${manualSyncBusy ? " side-sync--busy" : ""}`}
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
            className={`side-sync side-sync--ghost${prewarmBusy ? " side-sync--busy" : ""}`}
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
      </div>
    </aside>
  );
}
