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
    <aside aria-label="Filters" className="panel panel--filters glass-panel">
      <div className="panel-header">
        <div>
          <p className="panel-eyebrow">Filter temporal</p>
          <h2>Filter temporal</h2>
        </div>
        <p className="panel-badge">AKTIF</p>
      </div>

      <section className="filter-group">
        <h3>Preset rentang waktu</h3>
        <div className="chip-list chip-list--tight">
          {TIME_PRESET_OPTIONS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              className={`chip chip--button${props.timePreset === preset.value ? " chip--active" : ""}`}
              onClick={() => props.onTimePresetChange(preset.value)}
            >
              <span>{preset.label}</span>
            </button>
          ))}
        </div>
        <div className="control-metric">
          <span>Hotspot beririsan</span>
          <strong>{props.hotspotCount}</strong>
        </div>
      </section>

      <section className="filter-group">
        <h3>Provinsi</h3>
        <select
          value={props.selectedProvince}
          onChange={(e) => props.onProvinceChange(e.target.value)}
          style={{
            width: "100%",
            padding: "0.5rem",
            background: "rgba(255, 255, 255, 0.05)",
            border: "1px solid rgba(255, 255, 255, 0.1)",
            borderRadius: "0.25rem",
            color: "#f3f4f6",
            fontSize: "0.85rem",
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
        <label className="chip" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={props.showWind}
            onChange={props.onToggleWind}
          />
          <span>Tampilkan Angin</span>
        </label>
      </section>

      <section className="filter-group">
        <h3>Rentang kustom</h3>
        <div className="field-grid">
          <label className="field">
            <span>Dari</span>
            <input
              type="date"
              value={props.startDate}
              disabled={props.timePreset !== "custom"}
              onChange={(event) =>
                props.onDateChange("startDate", event.currentTarget.value)
              }
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
