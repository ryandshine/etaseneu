import React, { useState } from "react";
import { 
  useWildfire3DData 
} from "../hooks/useWildfire3DData";
import { Wildfire3DMap } from "./Wildfire3DMap";
import { TIME_PRESET_OPTIONS, type TimePreset } from "../constants/time-windows";
import { 
  Flame, 
  Wind, 
  Layers, 
  Compass, 
  Play, 
  Pause, 
  RotateCcw, 
  Sliders, 
  ChevronLeft, 
  ChevronRight, 
  Activity, 
  ShieldCheck, 
  Mountain, 
  CloudSun, 
  Map as MapIcon, 
  Eye, 
  EyeOff, 
  RefreshCw, 
  Info,
  Maximize2
} from "lucide-react";

import type { DashboardHotspot, DashboardLayer } from "../types/api";

export interface Wildfire3DExplorerProps {
  onBackToLiveMap: () => void;
  initialLayers?: DashboardLayer[];
  initialHotspots?: DashboardHotspot[];
}

export const Wildfire3DExplorer: React.FC<Wildfire3DExplorerProps> = ({
  onBackToLiveMap,
  initialLayers,
  initialHotspots,
}) => {
  const {
    timePreset,
    setTimePreset,
    customStartDate,
    setCustomStartDate,
    customEndDate,
    setCustomEndDate,
    filteredHotspots,
    layers,
    windGeoJson,
    windSummary,
    loading,
    error,
    lastUpdated,
    syncMetrics,
    loadHotspotData,
    // Toggles
    showHotspots,
    setShowHotspots,
    showHighConf,
    setShowHighConf,
    showMedConf,
    setShowMedConf,
    showLowConf,
    setShowLowConf,
    showKps,
    setShowKps,
    showTerrain,
    setShowTerrain,
    terrainExaggeration,
    setTerrainExaggeration,
    showWind,
    setShowWind,
    basemap,
    setBasemap,
    // Selection & Weather
    selectedHotspot,
    setSelectedHotspot,
    spotWeather,
    spotWeatherLoading,
    spotWeatherError,
    // Timeline
    isPlaying,
    setIsPlaying,
    playbackSpeed,
    setPlaybackSpeed,
    timelineProgress,
    setTimelineProgress,
    currentCutoffTimeFormatted,
    // Analytics
    analytics
  } = useWildfire3DData(true, initialLayers, initialHotspots);

  const [leftHudOpen, setLeftHudOpen] = useState(true);
  const [rightHudOpen, setRightHudOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<"summary" | "distribution" | "weather">("summary");

  return (
    <div className="wildfire-3d-explorer-container">
      {/* 1. Header Bar */}
      <header className="wildfire-3d-header">
        <div className="header-left">
          <button
            type="button"
            onClick={onBackToLiveMap}
            className="header-back-btn"
            title="Kembali ke Live Map 2D"
          >
            <ChevronLeft size={18} />
            <span>Live Map</span>
          </button>

          <div className="header-brand-divider" />

          <div className="header-title-group">
            <div className="header-main-title">
              <span className="title-fire-icon">🔥</span>
              <span>Wildfire 3D Explorer</span>
              <span className="badge-3d">3D WebGL</span>
            </div>
            <div className="header-sub-title">
              Eksplorasi Spasial 3D Hotspot, Poligon KPS, & Medan Geografis
            </div>
          </div>
        </div>

        <div className="header-right">
          <div className="telemetry-item">
            <span className="telemetry-label">Terakhir Sinkron:</span>
            <span className="telemetry-val">{lastUpdated || "Memuat..."}</span>
          </div>

          <div className="telemetry-badges">
            <div className="status-pill online" title="Koneksi data NASA FIRMS aktif">
              <span className="dot" /> NASA FIRMS
            </div>
            <div className="status-pill online" title="Koneksi data prakiraan Open-Meteo aktif">
              <span className="dot" /> Open-Meteo
            </div>
            <div className="status-pill online" title="Elevasi AWS Terrarium Terrain aktif">
              <span className="dot" /> 3D Terrain
            </div>
          </div>

          <button
            type="button"
            onClick={() => void loadHotspotData()}
            className="refresh-data-btn"
            title="Segarkan Data Hotspot"
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </header>

      {/* 2. Main Stage with 3D Map */}
      <main className="wildfire-3d-stage">
        <Wildfire3DMap
          hotspots={filteredHotspots}
          layers={layers}
          windGeoJson={windGeoJson}
          showHotspots={showHotspots}
          showKps={showKps}
          showTerrain={showTerrain}
          terrainExaggeration={terrainExaggeration}
          showWind={showWind}
          basemap={basemap}
          onSelectHotspot={setSelectedHotspot}
          selectedHotspot={selectedHotspot}
          spotWeather={spotWeather}
          spotWeatherLoading={spotWeatherLoading}
          spotWeatherError={spotWeatherError}
        />

        {/* 3. Floating Left HUD: Situasi & Analitik Aktual */}
        <aside className={`wildfire-hud-panel left ${leftHudOpen ? "open" : "collapsed"}`}>
          <div className="hud-header">
            <div className="hud-title">
              <Activity size={16} className="text-amber-400" />
              <span>Situasi Karhutla 3D</span>
            </div>
            <button
              type="button"
              onClick={() => setLeftHudOpen(!leftHudOpen)}
              className="hud-toggle-btn"
              title={leftHudOpen ? "Kecilkan Panel" : "Buka Panel"}
            >
              {leftHudOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
            </button>
          </div>

          {leftHudOpen && (
            <div className="hud-body">
              {/* Tab Selector */}
              <div className="hud-tabs">
                <button
                  type="button"
                  onClick={() => setActiveTab("summary")}
                  className={`hud-tab-item ${activeTab === "summary" ? "active" : ""}`}
                >
                  Ringkasan
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("distribution")}
                  className={`hud-tab-item ${activeTab === "distribution" ? "active" : ""}`}
                >
                  Distribusi KPS
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("weather")}
                  className={`hud-tab-item ${activeTab === "weather" ? "active" : ""}`}
                >
                  Cuaca & Angin
                </button>
              </div>

              {/* Tab Content: Summary */}
              {activeTab === "summary" && (
                <div className="hud-tab-pane">
                  <div className="kpi-hero-card">
                    <div className="kpi-hero-number">{analytics.total}</div>
                    <div className="kpi-hero-sub">Titik Panas pada Filter Aktif</div>
                  </div>

                  <div className="confidence-breakdown-row">
                    <div className="conf-pill high">
                      <span className="dot" />
                      <span className="count">{analytics.high}</span>
                      <span className="lbl">Tinggi</span>
                    </div>
                    <div className="conf-pill med">
                      <span className="dot" />
                      <span className="count">{analytics.med}</span>
                      <span className="lbl">Sedang</span>
                    </div>
                    <div className="conf-pill low">
                      <span className="dot" />
                      <span className="count">{analytics.low}</span>
                      <span className="lbl">Rendah</span>
                    </div>
                  </div>

                  <div className="metric-grid-2">
                    <div className="metric-box">
                      <div className="m-label">FRP Maksimum</div>
                      <div className="m-val highlight">{analytics.maxFrp} <span className="unit">MW</span></div>
                    </div>
                    <div className="metric-box">
                      <div className="m-label">FRP Rata-rata</div>
                      <div className="m-val">{analytics.avgFrp} <span className="unit">MW</span></div>
                    </div>
                  </div>

                  <div className="info-meta-item">
                    <span className="label">Waktu Deteksi Terbaru:</span>
                    <span className="val">{analytics.latestTime || "Belum ada titik"}</span>
                  </div>

                  <div className="info-meta-item">
                    <span className="label">Areal KPS Terpantau:</span>
                    <span className="val">{layers.reduce((acc, l) => acc + (l.feature_count || 0), 0)} unit</span>
                  </div>
                </div>
              )}

              {/* Tab Content: Distribution */}
              {activeTab === "distribution" && (
                <div className="hud-tab-pane">
                  <div className="section-mini-title flex items-center justify-between">
                    <span>KPS Terdampak</span>
                    {analytics.topKps.length > 0 && (
                      <span className="text-[0.65rem] text-emerald-400 font-mono">
                        {analytics.topKps.length} Unit
                      </span>
                    )}
                  </div>
                  {analytics.topKps.length === 0 ? (
                    <div className="empty-hint">Tidak ada hotspot di KPS</div>
                  ) : (
                    <div className="leaderboard-list">
                      {analytics.topKps.map((k, i) => (
                        <div key={k.name} className="leaderboard-item">
                          <span className="rank-num">#{i + 1}</span>
                          <div className="item-text">
                            <div className="main-name" title={k.name}>{k.name}</div>
                            <div className="sub-loc">{k.province}</div>
                          </div>
                          <span className="badge-count">{k.count} HS</span>
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="section-mini-title mt-3 flex items-center justify-between">
                    <span>Distribusi Provinsi</span>
                    {analytics.topProvinces.length > 0 && (
                      <span className="text-[0.65rem] text-sky-400 font-mono">
                        {analytics.topProvinces.length} Prov
                      </span>
                    )}
                  </div>
                  <div className="leaderboard-list">
                    {analytics.topProvinces.map((p, i) => (
                      <div key={p.name} className="leaderboard-item">
                        <span className="rank-num">#{i + 1}</span>
                        <div className="item-text">
                          <div className="main-name" title={p.name}>{p.name}</div>
                        </div>
                        <span className="badge-count prov">{p.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tab Content: Weather */}
              {activeTab === "weather" && (
                <div className="hud-tab-pane">
                  <div className="weather-overview-card">
                    <div className="weather-card-title">
                      <Wind size={15} className="text-cyan-400" />
                      <span>Grid Vektor Angin (Open-Meteo)</span>
                    </div>

                    <div className="weather-stats-row">
                      <div className="stat-col">
                        <span className="col-label">Kecepatan Rerata</span>
                        <span className="col-val">{windSummary?.avgSpeedKmh ?? "-"} <small>km/h</small></span>
                      </div>
                      <div className="stat-col">
                        <span className="col-label">Arah Dominan</span>
                        <span className="col-val">{windSummary?.dominantDirectionText ?? "-"} <small>({windSummary?.dominantDirectionDeg ?? "-"}°)</small></span>
                      </div>
                    </div>
                  </div>

                  {selectedHotspot && (
                    <div className="selected-spot-section">
                      <div className="spot-title">
                        <Flame size={14} className="text-red-400" />
                        <span>Cuaca Titik Terpilih: {selectedHotspot.agencyName}</span>
                      </div>
                      {spotWeatherLoading ? (
                        <div className="spot-loading">Memuat cuaca spot...</div>
                      ) : spotWeather ? (
                        <div className="spot-metrics-grid">
                          <div className="spot-metric">
                            <span className="sm-label">Suhu</span>
                            <span className="sm-val">{spotWeather.temperature ?? "-"}°C</span>
                          </div>
                          <div className="spot-metric">
                            <span className="sm-label">Kelembaban</span>
                            <span className="sm-val">{spotWeather.relative_humidity ?? "-"}%</span>
                          </div>
                          <div className="spot-metric">
                            <span className="sm-label">Curah Hujan</span>
                            <span className="sm-val">{spotWeather.precipitation ?? "0"} mm</span>
                          </div>
                          <div className="spot-metric">
                            <span className="sm-label">Angin</span>
                            <span className="sm-val">{spotWeather.wind_speed ?? "-"} km/h</span>
                          </div>
                        </div>
                      ) : (
                        <div className="spot-empty">Data tidak tersedia</div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </aside>

        {/* 4. Floating Right HUD: Layer Control & Legenda */}
        <aside className={`wildfire-hud-panel right ${rightHudOpen ? "open" : "collapsed"}`}>
          <div className="hud-header">
            <div className="hud-title">
              <Layers size={16} className="text-amber-400" />
              <span>Kontrol Layer & Visual</span>
            </div>
            <button
              type="button"
              onClick={() => setRightHudOpen(!rightHudOpen)}
              className="hud-toggle-btn"
              title={rightHudOpen ? "Kecilkan Panel" : "Buka Panel"}
            >
              {rightHudOpen ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
            </button>
          </div>

          {rightHudOpen && (
            <div className="hud-body">
              {/* Basemap Switcher */}
              <div className="control-group">
                <div className="control-group-title">
                  <MapIcon size={14} /> Peta Dasar
                </div>
                <div className="basemap-button-grid">
                  <button
                    type="button"
                    onClick={() => setBasemap("satellite")}
                    className={`basemap-btn ${basemap === "satellite" ? "active" : ""}`}
                  >
                    Satelit Hybrid
                  </button>
                  <button
                    type="button"
                    onClick={() => setBasemap("dark")}
                    className={`basemap-btn ${basemap === "dark" ? "active" : ""}`}
                  >
                    Dark Intel
                  </button>
                  <button
                    type="button"
                    onClick={() => setBasemap("topo")}
                    className={`basemap-btn ${basemap === "topo" ? "active" : ""}`}
                  >
                    Topografi
                  </button>
                </div>
              </div>

              {/* Layer Toggles */}
              <div className="control-group">
                <div className="control-group-title">
                  <Sliders size={14} /> Lapisan Spasial
                </div>

                {/* Hotspot Toggle */}
                <div className="layer-toggle-item">
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={showHotspots}
                      onChange={(e) => setShowHotspots(e.target.checked)}
                    />
                    <span className="toggle-name">Titik Panas (Hotspot)</span>
                  </label>
                </div>

                {/* Sub-confidence filters */}
                {showHotspots && (
                  <div className="sub-confidence-options">
                    <label className="sub-toggle">
                      <input
                        type="checkbox"
                        checked={showHighConf}
                        onChange={(e) => setShowHighConf(e.target.checked)}
                      />
                      <span className="dot high" /> Tinggi (High)
                    </label>
                    <label className="sub-toggle">
                      <input
                        type="checkbox"
                        checked={showMedConf}
                        onChange={(e) => setShowMedConf(e.target.checked)}
                      />
                      <span className="dot med" /> Sedang (Medium)
                    </label>
                    <label className="sub-toggle">
                      <input
                        type="checkbox"
                        checked={showLowConf}
                        onChange={(e) => setShowLowConf(e.target.checked)}
                      />
                      <span className="dot low" /> Rendah (Low)
                    </label>
                  </div>
                )}

                {/* KPS Boundaries Toggle */}
                <div className="layer-toggle-item">
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={showKps}
                      onChange={(e) => setShowKps(e.target.checked)}
                    />
                    <span className="toggle-name">Batas Kawasan KPS</span>
                  </label>
                </div>

                {/* 3D Terrain Toggle & Exaggeration */}
                <div className="layer-toggle-item">
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={showTerrain}
                      onChange={(e) => setShowTerrain(e.target.checked)}
                    />
                    <span className="toggle-name">Medan 3D (DEM Terrarium)</span>
                  </label>
                </div>

                {showTerrain && (
                  <div className="terrain-slider-box">
                    <div className="slider-header">
                      <span>Elevasi Medan:</span>
                      <b>{terrainExaggeration}x</b>
                    </div>
                    <input
                      type="range"
                      min="0.5"
                      max="3.0"
                      step="0.1"
                      value={terrainExaggeration}
                      onChange={(e) => setTerrainExaggeration(parseFloat(e.target.value))}
                      className="terrain-range"
                    />
                  </div>
                )}

                {/* Wind Vectors Overlay */}
                <div className="layer-toggle-item">
                  <label className="toggle-label">
                    <input
                      type="checkbox"
                      checked={showWind}
                      onChange={(e) => setShowWind(e.target.checked)}
                    />
                    <span className="toggle-name">Overlay Vektor Angin</span>
                  </label>
                </div>
              </div>

              {/* Visual Legend */}
              <div className="control-group legend">
                <div className="control-group-title">
                  <Info size={14} /> Legenda Simbologi
                </div>
                <div className="legend-items">
                  <div className="legend-row">
                    <span className="legend-circle high" />
                    <span>Hotspot Confidence Tinggi</span>
                  </div>
                  <div className="legend-row">
                    <span className="legend-circle med" />
                    <span>Hotspot Confidence Sedang</span>
                  </div>
                  <div className="legend-row">
                    <span className="legend-circle low" />
                    <span>Hotspot Confidence Rendah</span>
                  </div>
                  <div className="legend-row">
                    <span className="legend-box kps" />
                    <span>Poligon Perhutanan Sosial (KPS)</span>
                  </div>
                  <div className="legend-row">
                    <span className="legend-line wind" />
                    <span>Arah & Kecepatan Angin (m/s)</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </aside>

        {/* 5. Bottom Interactive Timeline Bar */}
        <section className="wildfire-3d-timeline-bar" aria-label="Timeline Hotspot">
          <div className="timeline-left-controls">
            {/* Play/Pause Button */}
            <button
              type="button"
              onClick={() => {
                if (!isPlaying && timelineProgress >= 100) {
                  setTimelineProgress(0);
                }
                setIsPlaying(!isPlaying);
              }}
              className={`timeline-play-btn ${isPlaying ? "playing" : ""}`}
              title={isPlaying ? "Jeda Playback" : "Mulai Animasi Waktu"}
              aria-label={isPlaying ? "Jeda" : "Putar"}
            >
              {isPlaying ? <Pause size={17} /> : <Play size={17} />}
            </button>

            {/* Speed Toggle */}
            <button
              type="button"
              onClick={() => {
                const next = playbackSpeed === 1 ? 2 : playbackSpeed === 2 ? 4 : 1;
                setPlaybackSpeed(next);
              }}
              className="timeline-speed-btn"
              title="Kecepatan Animasi"
            >
              {playbackSpeed}x
            </button>

            {/* Time Preset Buttons */}
            <div className="timeline-presets">
              {TIME_PRESET_OPTIONS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setTimePreset(p.value)}
                  className={`preset-chip ${timePreset === p.value ? "active" : ""}`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Timeline Center Scrubber */}
          <div className="timeline-center-scrubber">
            <div className="scrubber-header">
              <span className="scrubber-label">Waktu Pengamatan Aktif:</span>
              <span className="scrubber-time-badge">
                📅 {currentCutoffTimeFormatted}
              </span>
            </div>

            <div className="scrubber-track-wrap">
              <input
                type="range"
                min="0"
                max="100"
                step="0.5"
                value={timelineProgress}
                onChange={(e) => {
                  setTimelineProgress(parseFloat(e.target.value));
                  if (isPlaying) setIsPlaying(false);
                }}
                className="timeline-slider"
                aria-label="Penggeser Waktu"
              />
              <div 
                className="scrubber-fill" 
                style={{ width: `${timelineProgress}%` }} 
              />
            </div>
          </div>

          {/* Timeline Right Reset */}
          <div className="timeline-right-actions">
            <button
              type="button"
              onClick={() => {
                setIsPlaying(false);
                setTimelineProgress(100);
              }}
              className="timeline-reset-btn"
              title="Reset ke Waktu Sekarang"
            >
              <RotateCcw size={14} className="mr-1" /> Terkini
            </button>
          </div>
        </section>
      </main>
    </div>
  );
};
