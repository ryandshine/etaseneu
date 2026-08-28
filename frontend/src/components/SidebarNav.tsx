// "loading" dipisahkan dari "warning" dengan sengaja: selama data status
// belum tiba kita belum tahu kondisinya, dan menampilkannya sebagai
// peringatan bikin user mengira sistem bermasalah padahal cuma belum
// selesai memuat.
type HealthStatus = "loading" | "normal" | "warning" | "error";

const HEALTH_BADGE: Record<HealthStatus, { color: string; bg: string; label: string }> = {
  loading: { color: "#9ca3af", bg: "rgba(156,163,175,0.15)", label: "..." },
  normal: { color: "#10b981", bg: "rgba(16,185,129,0.15)", label: "OK" },
  warning: { color: "#f59e0b", bg: "rgba(245,158,11,0.15)", label: "LATE" },
  error: { color: "#ef4444", bg: "rgba(239,68,68,0.15)", label: "ERR" }
};

type SidebarNavProps = {
  // "kps" (detail satu KPS dibuka dari Buku Besar) bukan tujuan navigasi
  // sidebar, tapi activeView tetap perlu menerimanya supaya perbandingan
  // "active" di bawah tidak salah tipe saat halaman itu sedang tampil.
  activeView: "map" | "matrix" | "pointmatch" | "kompleks" | "earlywarning" | "settings" | "kps";
  onChangeView: (view: "map" | "matrix" | "pointmatch" | "kompleks" | "earlywarning" | "settings") => void;
  onManualSync: () => void;
  onPrewarmHistory: () => void;
  onLogout: () => void;
  syncLabel: string;
  syncStatusLabel: string;
  lastSyncLabel: string;
  manualSyncBusy: boolean;
  prewarmBusy: boolean;
  healthStatus: HealthStatus;
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
  /** Role admin: menampilkan tombol Sync/Prewarm. Menu Pengaturan berisi info
   *  akun untuk semua role, sedangkan panel sistemnya tetap admin-only. */
  isAdmin: boolean;
  mobileOpen?: boolean;
  /**
   * Panel filter peta. Dirender sebagai slot, bukan diimpor langsung, supaya
   * seluruh state filter tetap tinggal di App dan SidebarNav tidak ikut
   * bergantung pada tipe-tipe filter.
   */
  filterSlot?: React.ReactNode;
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
      <span>{typeof children === "string" ? children.trim() : children}</span>
    </button>
  );
}

export function SidebarNav({
  activeView,
  onChangeView,
  onManualSync,
  onPrewarmHistory,
  onLogout,
  syncLabel,
  syncStatusLabel,
  lastSyncLabel,
  manualSyncBusy,
  prewarmBusy,
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
  isAdmin,
  mobileOpen,
  filterSlot
}: SidebarNavProps) {
  return (
    <aside className={`side-rail${mobileOpen ? " mobile-open" : ""}`}>
      <div className="side-brand">
        <div>
          <div className="side-brand-name">ETAseneu</div>
          <div className="side-brand-sub">KPS Hotspot Monitoring</div>
        </div>
      </div>

      {/* Navigasi dan filter berbagi satu area yang bisa digulir, sementara
          brand di atas dan status sinkronisasi di bawah tetap diam. Tanpa ini
          filter yang panjang akan mendorong blok status keluar layar. */}
      <div className="side-scroll">
        <nav className="side-nav" aria-label="Utama">
          <NavButton active={activeView === "map"} onClick={() => onChangeView("map")}>
            LIVE MAP
          </NavButton>
          <NavButton active={activeView === "matrix"} onClick={() => onChangeView("matrix")}>
            Matriks Data
          </NavButton>
          <NavButton active={activeView === "pointmatch"} onClick={() => onChangeView("pointmatch")}>
            Cek Titik ke KPS
          </NavButton>
          <NavButton active={activeView === "kompleks"} onClick={() => onChangeView("kompleks")}>
            Kompleks Kebakaran
          </NavButton>
          <NavButton active={activeView === "earlywarning"} onClick={() => onChangeView("earlywarning")}>
            Peringatan Dini
          </NavButton>
          <NavButton active={activeView === "settings"} onClick={() => onChangeView("settings")}>
            Pengaturan
          </NavButton>
        </nav>

        <button type="button" className="side-logout-btn" onClick={onLogout}>
          Keluar
        </button>

        {filterSlot ? <div className="side-filter">{filterSlot}</div> : null}
      </div>

      <div className="side-footer" style={{ padding: '0.75rem', fontSize: '0.75rem', overflowX: 'hidden' }}>
        <div className="side-footer-block" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '0.6rem', marginBottom: '0.6rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.6rem' }}>
            <span className="side-footer-label" style={{ fontWeight: '700', letterSpacing: '0.03em', textTransform: 'uppercase', fontSize: '0.68rem', color: '#f5efe6', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
              Sinkronisasi NASA
              <span
                title="Info Sinkronisasi NASA&#10;&#10;Tidak adanya hotspot baru tidak selalu berarti sinkronisasi gagal.&#10;&#10;Periksa:&#10;- Last Sync&#10;- Next Sync&#10;- Hotspot Terbaru&#10;- Status Scheduler"
                style={{ cursor: 'help', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '12px', height: '12px', borderRadius: '50%', border: '1px solid currentColor', fontSize: '8px', flexShrink: 0 }}
              >
                i
              </span>
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', flexShrink: 0, padding: '0.15rem 0.5rem', borderRadius: '999px', backgroundColor: HEALTH_BADGE[healthStatus].bg }}>
              <span style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                flexShrink: 0,
                backgroundColor: HEALTH_BADGE[healthStatus].color,
                boxShadow: `0 0 6px ${HEALTH_BADGE[healthStatus].color}`
              }} />
              <span style={{ fontSize: '0.65rem', fontWeight: 'bold', color: HEALTH_BADGE[healthStatus].color }}>
                {HEALTH_BADGE[healthStatus].label}
              </span>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem', marginBottom: '0.6rem' }}>
            <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '0.5rem 0.6rem' }}>
              <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.2rem' }}>Last Sync</div>
              <div style={{ color: '#f5efe6', fontSize: '0.72rem', fontWeight: 600, wordBreak: 'break-word', lineHeight: 1.3 }}>{lastSyncLabel}</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '0.5rem 0.6rem' }}>
              <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.2rem' }}>Next Sync</div>
              <div style={{ color: '#f5efe6', fontSize: '0.72rem', fontWeight: 600, wordBreak: 'break-word', lineHeight: 1.3 }}>{nextScheduledSyncLabel}</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '0.5rem 0.6rem' }}>
              <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.2rem' }}>Hotspot Terbaru</div>
              <div style={{ color: '#f5efe6', fontSize: '0.72rem', fontWeight: 600, wordBreak: 'break-word', lineHeight: 1.3 }}>{latestHotspotTimeLabel}</div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.04)', borderRadius: '6px', padding: '0.5rem 0.6rem' }}>
              <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.5)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.2rem' }}>Usia Data</div>
              <div style={{ color: hasLatestHotspot ? '#f5efe6' : 'rgba(255,255,255,0.4)', fontSize: '0.72rem', fontWeight: 600, wordBreak: 'break-word', lineHeight: 1.3 }}>{dataAgeLabel}</div>
            </div>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', rowGap: '0.25rem', columnGap: '0.7rem', fontSize: '0.68rem', color: 'rgba(255,255,255,0.5)' }}>
            <span>Scheduler: <strong style={{ color: schedulerStatusColor, backgroundColor: schedulerStatusBg, padding: '0.05rem 0.3rem', borderRadius: '3px' }}>{schedulerStatusLabel}</strong></span>
            <span>Sync hari ini: <strong style={{ color: '#f5efe6' }}>{syncTodayRatio}</strong></span>
            <span>Interval: <strong style={{ color: '#f5efe6' }}>{syncInterval}</strong></span>
            <span>Database: <strong style={{ color: '#f5efe6' }}>{syncLabel}</strong></span>
          </div>
        </div>

        {isAdmin ? (
        <div className="side-sync-actions" style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className={`side-sync${manualSyncBusy ? " side-sync--busy" : ""}`}
            onClick={onManualSync}
            disabled={manualSyncBusy}
            aria-busy={manualSyncBusy}
            aria-label="Sync hotspot manual"
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
            aria-label="Prewarm histori tahunan"
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
        ) : null}
      </div>
    </aside>
  );
}
