type StatCardsProps = {
  stats: {
    layerCount: number;
    activeLayerCount: number;
    satelliteCount: number;
    dateRangeLabel: string;
  };
};

const cardConfig = [
  {
    key: "layerCount",
    label: "Lapisan Dimuat"
  },
  {
    key: "activeLayerCount",
    label: "Lapisan Aktif"
  },
  {
    key: "satelliteCount",
    label: "Satelit"
  }
] as const;

export function StatCards({ stats }: StatCardsProps) {
  return (
    <section aria-label="Dashboard stats" className="panel panel--stats">
      <div className="panel-header">
        <div>
          <p className="panel-eyebrow">Status saat ini</p>
          <h2>Ringkasan operasional</h2>
        </div>
        <p className="panel-badge">{stats.dateRangeLabel}</p>
      </div>
      <div className="metric-grid">
        {cardConfig.map((card) => (
          <article key={card.key} className="metric-card">
            <p className="metric-label">{card.label}</p>
            <strong className="metric-value">{stats[card.key]}</strong>
          </article>
        ))}
        <article className="metric-card metric-card--wide">
          <p className="metric-label">Rentang Tanggal</p>
          <strong className="metric-value metric-value--range">{stats.dateRangeLabel}</strong>
        </article>
      </div>
    </section>
  );
}
