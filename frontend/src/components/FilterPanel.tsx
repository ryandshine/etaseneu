import { useState } from "react";

import type { LayerBounds } from "../types/api";
import { SATELLITE_OPTIONS } from "../constants/satellites";
import { TIME_PRESET_OPTIONS, type TimePreset } from "../constants/time-windows";
import { LayerList } from "./LayerList";

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

type FilterPanelProps = {
  layers: LayerItem[];
  selectedSatellites: string[];
  timePreset: TimePreset;
  startDate: string;
  endDate: string;
  onToggleLayer: (id: string) => void;
  onToggleSatellite: (value: string) => void;
  onTimePresetChange: (value: TimePreset) => void;
  onDateChange: (field: "startDate" | "endDate", value: string) => void;
  hotspotCount: number;
  selectedProvince: string;
  onProvinceChange: (province: string) => void;
  provinceOptions: string[];
  showWind: boolean;
  onToggleWind: () => void;
};

export function FilterPanel(props: FilterPanelProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  return (
    <aside aria-label="Filters" className="panel panel--filters glass-panel" style={{ overflowY: 'auto', maxHeight: 'calc(100vh - 2rem)' }}>
      <div className="filter-panel-header">
        <span className="filter-panel-title">Filter Waktu</span>
        <span className="filter-panel-badge">AKTIF</span>
      </div>

      <section className="filter-group">
        <p className="filter-group-label">Preset waktu</p>
        <div className="filter-preset-grid">
          {TIME_PRESET_OPTIONS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              className={`chip chip--button filter-preset-btn${props.timePreset === preset.value ? " chip--active" : ""}`}
              onClick={() => props.onTimePresetChange(preset.value)}
            >
              <span>{preset.label}</span>
            </button>
          ))}
        </div>
        <div className="control-metric">
          <span>Hotspot beririsan:</span>
          <strong>{props.hotspotCount}</strong>
        </div>
      </section>

      <section className="filter-group">
        <p className="filter-group-label">Provinsi</p>
        <select
          value={props.selectedProvince}
          onChange={(e) => props.onProvinceChange(e.target.value)}
          className="filter-select-input"
        >
          <option value="">Semua Provinsi</option>
          {props.provinceOptions.map((province) => (
            <option key={province} value={province}>
              {province}
            </option>
          ))}
        </select>
      </section>

      <section className="filter-group">
        <label className="filter-checkbox-label">
          <input
            type="checkbox"
            checked={props.showWind}
            onChange={props.onToggleWind}
          />
          <span>Tampilkan Angin</span>
        </label>
      </section>

      <section className="filter-group">
        <p className="filter-group-label">Rentang kustom</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem' }}>
          <label className="field">
            <span>Dari</span>
            <input
              type="date"
              value={props.startDate}
              disabled={props.timePreset !== "custom"}
              onChange={(event) =>
                props.onDateChange("startDate", event.currentTarget.value)
              }
              className="filter-date-input"
            />
          </label>
          <label className="field">
            <span>Ke</span>
            <input
              type="date"
              value={props.endDate}
              disabled={props.timePreset !== "custom"}
              onChange={(event) =>
                props.onDateChange("endDate", event.currentTarget.value)
              }
              className="filter-date-input"
            />
          </label>
        </div>
        {props.timePreset === "custom" && <p className="help-copy">Tanggal manual aktif.</p>}
      </section>

      <button
        type="button"
        className="advanced-toggle"
        onClick={() => setShowAdvanced((current) => !current)}
      >
        {showAdvanced ? "Sembunyikan filter lanjutan" : "Tampilkan satelit & lapisan"}
      </button>

      {showAdvanced ? (
        <>
          <section className="filter-group">
            <h3>Satelit</h3>
            <div className="chip-list">
              {SATELLITE_OPTIONS.map((satellite) => {
                const isActive = props.selectedSatellites.includes(satellite.value);
                return (
                  <label key={satellite.value} className={`chip${isActive ? " chip--active" : ""}`}>
                    <input
                      type="checkbox"
                      aria-label={satellite.label}
                      checked={isActive}
                      onChange={() => props.onToggleSatellite(satellite.value)}
                    />
                    <span>{satellite.label}</span>
                  </label>
                );
              })}
            </div>
          </section>
          <section className="filter-group">
            <h3>Lapisan</h3>
            <LayerList layers={props.layers} onToggleLayer={props.onToggleLayer} />
          </section>
        </>
      ) : null}
    </aside>
  );
}
