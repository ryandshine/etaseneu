type LegendItem = {
  color?: string;
  count: number;
  label: string;
};

type LegendProps = {
  sources: LegendItem[];
};

export function Legend({ sources }: LegendProps) {
  return (
    <section aria-label="Map legend" className="panel panel--legend glass-panel">
      <div className="panel-header">
        <div>
          <h3 style={{ margin: 0 }}>Legenda</h3>
        </div>
      </div>

      <div className="legend-grid">
        <div className="legend-section">
          <p className="legend-title">
            Hotspot per Satelit
          </p>
          <ul className="legend-list">
            {sources.map((source) => (
              <li key={source.label} className="legend-item">
                <span>{source.label}</span>
                <strong>{source.count}</strong>
              </li>
            ))}
          </ul>
        </div>

      </div>
    </section>
  );
}
