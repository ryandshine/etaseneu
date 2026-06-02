import type { LayerBounds } from "../types/api";

type LayerItem = {
  id: string;
  name: string;
  label: string;
  active: boolean;
  color: string;
  bounds: LayerBounds;
  geojson: Record<string, unknown>;
  feature_count: number;
};

type LayerListProps = {
  layers: LayerItem[];
  onToggleLayer: (id: string) => void;
};

export function LayerList({ layers, onToggleLayer }: LayerListProps) {
  if (layers.length === 0) {
    return <p className="muted-copy">Belum ada lapisan spasial yang dimuat.</p>;
  }

  return (
    <div aria-label="Spatial layers" className="layer-list">
      {layers.map((layer) => (
        <label key={layer.id} className="layer-row">
          <input
            type="checkbox"
            aria-label={layer.label || layer.name}
            checked={layer.active}
            onChange={() => onToggleLayer(layer.id)}
          />
          <span className="layer-swatch" style={{ backgroundColor: layer.color }} />
          <span className="layer-meta">
            <span className="layer-name">{layer.label || layer.name}</span>
            <span className="layer-count">{layer.feature_count.toLocaleString()} fitur</span>
          </span>
        </label>
      ))}
    </div>
  );
}
