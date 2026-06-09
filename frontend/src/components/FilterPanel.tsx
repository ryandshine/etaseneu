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
        <div className="control-metric" style={{ fontSize: '0.68rem' }}>
          <span>Hotspot beririsan:</span>
          <strong style={{ marginLeft: '0.3rem' }}>{props.hotspotCount}</strong>
        </div>
      </section>

      <section className="filter-group">
        <p className="filter-group-label">Provinsi</p>
        <select
          value={props.selectedProvince}
          onChange={(e) => props.onProvinceChange(e.target.value)}
          className="filter-select-input"
          style={{
            width: "100%",
            fontSize: "0.75rem",
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "0.25rem",
            color: "#f3f4f6",
            outline: "none",
            cursor: "pointer"
          }}
        >
          <option value="" style={{ background: "#111317" }}>Semua Provinsi</option>
          {props.provinceOptions.map((province) => (
            <option key={province} value={province} style={{ background: "#111317" }}>
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
            style={{ cursor: 'pointer', width: '16px', height: '16px', flexShrink: 0 }}
          />
          <span>Tampilkan Angin</span>
        </label>
      </section>

      <section className="filter-group">
        <p className="filter-group-label">Rentang kustom</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem' }}>
          <label className="field" style={{ margin: 0 }}>
            <span style={{ fontSize: '0.68rem' }}>Dari</span>
            <input
              type="date"
              value={props.startDate}
              disabled={props.timePreset !== "custom"}
              onChange={(event) =>
                props.onDateChange("startDate", event.currentTarget.value)
              }
              className="filter-date-input"
              style={{ fontSize: '0.73rem' }}
            />
          </label>
          <label className="field" style={{ margin: 0 }}>
            <span style={{ fontSize: '0.68rem' }}>Ke</span>
            <input
              type="date"
              value={props.endDate}
              disabled={props.timePreset !== "custom"}
              onChange={(event) =>
                props.onDateChange("endDate", event.currentTarget.value)
              }
              className="filter-date-input"
              style={{ fontSize: '0.73rem' }}
            />
          </label>
        </div>
        {props.timePreset === "custom" && <p className="help-copy" style={{ fontSize: '0.64rem', marginTop: '0.2rem' }}>Tanggal manual aktif.</p>}
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
              {SATELLITE_OPTIONS.map((satellite) => (
                <label key={satellite.value} className="chip">
                  <input
                    type="checkbox"
                    aria-label={satellite.label}
                    checked={props.selectedSatellites.includes(satellite.value)}
                    onChange={() => props.onToggleSatellite(satellite.value)}
                  />
                  <span>{satellite.label}</span>
                </label>
              ))}
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
