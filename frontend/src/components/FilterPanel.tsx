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
      <div className="panel-header">
        <div>
          <p className="panel-eyebrow">Filter temporal</p>
          <h2>Filter temporal</h2>
        </div>
        <p className="panel-badge">AKTIF</p>
      </div>

      <section className="filter-group" style={{ paddingBottom: '0.75rem' }}>
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.4rem' }}>Preset waktu</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.35rem', marginBottom: '0.5rem' }}>
          {TIME_PRESET_OPTIONS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              className={`chip chip--button${props.timePreset === preset.value ? " chip--active" : ""}`}
              onClick={() => props.onTimePresetChange(preset.value)}
              style={{ fontSize: '0.75rem', padding: '0.4rem 0.35rem', minHeight: '44px', minWidth: '44px' }}
            >
              <span>{preset.label}</span>
            </button>
          ))}
        </div>
        <div className="control-metric" style={{ fontSize: '0.7rem' }}>
          <span>Hotspot beririsan:</span>
          <strong style={{ marginLeft: '0.3rem' }}>{props.hotspotCount}</strong>
        </div>
      </section>

      <section className="filter-group" style={{ paddingBottom: '0.5rem' }}>
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.4rem' }}>Provinsi</h3>
        <select
          value={props.selectedProvince}
          onChange={(e) => props.onProvinceChange(e.target.value)}
          style={{
            width: "100%",
            minHeight: "44px",
            padding: "0.5rem",
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

      <section className="filter-group" style={{ paddingBottom: '0.5rem' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', cursor: 'pointer', fontSize: '0.75rem', minHeight: '44px', padding: '0.5rem 0' }}>
          <input
            type="checkbox"
            checked={props.showWind}
            onChange={props.onToggleWind}
            style={{ cursor: 'pointer', width: '18px', height: '18px' }}
          />
          <span>Tampilkan Angin</span>
        </label>
      </section>

      <section className="filter-group" style={{ paddingBottom: '0.75rem' }}>
        <h3 style={{ fontSize: '0.85rem', marginBottom: '0.4rem' }}>Rentang kustom</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.4rem' }}>
          <label className="field" style={{ margin: 0 }}>
            <span style={{ fontSize: '0.7rem' }}>Dari</span>
            <input
              type="date"
              value={props.startDate}
              disabled={props.timePreset !== "custom"}
              onChange={(event) =>
                props.onDateChange("startDate", event.currentTarget.value)
              }
              style={{ minHeight: '44px', padding: '0.5rem', fontSize: '0.75rem' }}
            />
          </label>
          <label className="field" style={{ margin: 0 }}>
            <span style={{ fontSize: '0.7rem' }}>Ke</span>
            <input
              type="date"
              value={props.endDate}
              disabled={props.timePreset !== "custom"}
              onChange={(event) =>
                props.onDateChange("endDate", event.currentTarget.value)
              }
              style={{ minHeight: '44px', padding: '0.5rem', fontSize: '0.75rem' }}
            />
          </label>
        </div>
        {props.timePreset === "custom" && <p className="help-copy" style={{ fontSize: '0.65rem', marginTop: '0.25rem' }}>Tanggal manual aktif.</p>}
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
