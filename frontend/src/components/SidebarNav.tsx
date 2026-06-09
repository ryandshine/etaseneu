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
  mobileOpen?: boolean;
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
  hasLatestHotspot,
  mobileOpen
}: SidebarNavProps) {
  return (
    <aside className={`side-rail${mobileOpen ? " mobile-open" : ""}`}>
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

      <div className="side-footer" style={{ padding: '0.75rem', fontSize: '0.75rem', overflowX: 'hidden' }}>
        <div className="side-footer-block" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0.5rem', marginBottom: '0.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.35rem' }}>
            <span className="side-footer-label" style={{ fontWeight: '600', letterSpacing: '0.03em', textTransform: 'uppercase', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              Sinkronisasi NASA
              <span
                title="Info Sinkronisasi NASA&#10;&#10;Tidak adanya hotspot baru tidak selalu berarti sinkronisasi gagal.&#10;&#10;Periksa:&#10;- Last Sync&#10;- Next Sync&#10;- Hotspot Terbaru&#10;- Status Scheduler"
                style={{ cursor: 'help', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '12px', height: '12px', borderRadius: '50%', border: '1px solid currentColor', fontSize: '8px', flexShrink: 0 }}
              >
                i
              </span>
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexShrink: 0 }}>
              <span style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                flexShrink: 0,
                backgroundColor: healthStatus === 'normal' ? '#10b981' : healthStatus === 'warning' ? '#f59e0b' : '#ef4444',
                boxShadow: `0 0 6px ${healthStatus === 'normal' ? '#10b981' : healthStatus === 'warning' ? '#f59e0b' : '#ef4444'}`
              }} />
              <span style={{ fontSize: '0.65rem', fontWeight: 'bold', color: healthStatus === 'normal' ? '#10b981' : healthStatus === 'warning' ? '#f59e0b' : '#ef4444' }}>
                {healthStatus === 'normal' ? 'OK' : healthStatus === 'warning' ? 'LATE' : 'ERR'}
              </span>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.22rem', color: '#9ca3af', fontSize: '0.68rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.4rem' }}>
              <span style={{ flexShrink: 0 }}>Scheduler</span>
              <strong style={{ color: schedulerStatusColor, backgroundColor: schedulerStatusBg, padding: '0.05rem 0.2rem', borderRadius: '3px', fontSize: '0.62rem', flexShrink: 0 }}>
                {schedulerStatusLabel}
              </strong>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.4rem' }}>
              <span style={{ flexShrink: 0 }}>Sync Hari Ini</span>
              <strong style={{ color: '#fff', flexShrink: 0 }}>{syncTodayRatio}</strong>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.4rem' }}>
              <span style={{ flexShrink: 0 }}>Interval</span>
              <strong style={{ color: '#fff', flexShrink: 0 }}>{syncInterval}</strong>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.4rem' }}>
              <span style={{ flexShrink: 0 }}>Database</span>
              <strong style={{ color: '#fff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '55%', textAlign: 'right' }}>{syncLabel}</strong>
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.35rem', fontSize: '0.65rem', color: '#9ca3af', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0.4rem', marginBottom: '0.4rem' }}>
          <div>
            <span style={{ fontSize: '0.6rem', color: '#6b7280' }}>LAST SYNC</span>
            <div style={{ color: '#fff', fontSize: '0.63rem', marginTop: '0.1rem', wordBreak: 'break-word', lineHeight: 1.3 }}>{lastSyncLabel}</div>
          </div>
          <div>
            <span style={{ fontSize: '0.6rem', color: '#6b7280' }}>NEXT SYNC</span>
            <div style={{ color: '#fff', fontSize: '0.63rem', marginTop: '0.1rem', wordBreak: 'break-word', lineHeight: 1.3 }}>{nextScheduledSyncLabel}</div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <span style={{ fontSize: '0.6rem', color: '#6b7280' }}>HOTSPOT TERBARU</span>
            <div style={{ color: '#fff', fontSize: '0.63rem', marginTop: '0.1rem', wordBreak: 'break-word', lineHeight: 1.3 }}>{latestHotspotTimeLabel}</div>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <span style={{ fontSize: '0.6rem', color: '#6b7280' }}>USIA DATA</span>
            <div style={{ color: hasLatestHotspot ? '#fff' : '#6b7280', fontSize: '0.63rem', marginTop: '0.1rem', wordBreak: 'break-word', lineHeight: 1.3 }}>{dataAgeLabel}</div>
          </div>
        </div>
        <div className="side-sync-actions" style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className={`side-sync${manualSyncBusy ? " side-sync--busy" : ""}`}
            onClick={onManualSync}
            disabled={manualSyncBusy}
            aria-busy={manualSyncBusy}
            style={{ flex: '1 1 48%', minHeight: '44px', fontSize: '0.75rem', padding: '0.5rem', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' }}
          >
            <span className="sync-button-label">
              {manualSyncBusy ? "Sync..." : "Sync Hotspot"}
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
            style={{ flex: '1 1 48%', minHeight: '44px', fontSize: '0.75rem', padding: '0.5rem', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column' }}
          >
            <span className="sync-button-label">
              {prewarmBusy ? "Prewarm..." : "Prewarm"}
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
