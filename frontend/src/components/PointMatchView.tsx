import { useCallback, useEffect, useRef, useState } from "react";
import { authFetch, downloadWithAuth } from "../lib/api";
import {
  Download,
  FileSpreadsheet,
  FileText,
  Flame,
  Layers,
  MapPin,
  ShieldAlert,
  ShieldCheck,
  UploadCloud,
  X
} from "lucide-react";
import { CircleMarker, GeoJSON as LeafletGeoJson, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";

type SummaryItem = { label: string; count: number };

type PointMatchSummary = {
  total_points: number;
  inside_count: number;
  outside_count: number;
  distinct_kps: number;
  by_kps: SummaryItem[];
  by_wilker: SummaryItem[];
  by_province: SummaryItem[];
};

export type PointMatchResult = {
  kind?: "points";
  token: string;
  source_name: string;
  source_format: string;
  warnings: string[];
  skipped_features: number;
  summary: PointMatchSummary;
  property_columns: string[];
  preview_rows: (string | number)[][];
  preview_truncated: boolean;
};

export type PolygonInfo = {
  area_ha: number;
  bounds: [number, number, number, number];
  overlaps_kps: boolean;
  kps_matches: Array<{
    id: number;
    lembaga?: string;
    skema?: string;
    nama_kab?: string;
    nama_prov?: string;
    no_sk?: string;
  }>;
};

export type PolygonMatchSummary = {
  total_hotspots: number;
  confidence_high: number;
  confidence_medium: number;
  confidence_low: number;
  density_per_1000ha: number;
  by_month: SummaryItem[];
  by_satellite: SummaryItem[];
  by_confidence: SummaryItem[];
};

export type HotspotItem = {
  id: number;
  latitude: number;
  longitude: number;
  detected_at: string;
  detected_at_wib: string;
  satellite: string;
  confidence: string;
  confidence_level: string;
  brightness: number | string;
  frp: number | string;
};

export type PolygonMatchResult = {
  kind: "polygon";
  token: string;
  source_name: string;
  source_format: string;
  warnings: string[];
  skipped_features: number;
  polygon_info: PolygonInfo;
  summary: PolygonMatchSummary;
  hotspots: HotspotItem[];
  polygon_geojson: any;
  preview_rows: (string | number)[][];
  preview_truncated: boolean;
};

export type SpatialResult = PointMatchResult | PolygonMatchResult;

const BASE_HEADERS = [
  "No",
  "Latitude",
  "Longitude",
  "Status",
  "KPS (Lembaga)",
  "Balai PS",
  "Provinsi",
  "Kabupaten",
  "Kecamatan",
  "Desa",
  "Skema",
  "No. SK",
  "Tgl SK"
];

const POLYGON_HEADERS = [
  "No",
  "Waktu Deteksi (WIB)",
  "Lintang",
  "Bujur",
  "Satelit / Sensor",
  "Keyakinan",
  "Kecerahan",
  "FRP (MW)"
];

const STATUS_COLUMN = BASE_HEADERS.indexOf("Status");
const ACCEPTED = ".geojson,.json,.kml,.zip";

function formatNumber(value: number): string {
  return value.toLocaleString("id-ID");
}

function SummaryCard({
  label,
  value,
  tone,
  suffix
}: {
  label: string;
  value: number | string;
  tone?: "alert" | "normal";
  suffix?: string;
}) {
  const isNumeric = typeof value === "number";
  const displayVal = isNumeric ? formatNumber(value) : value;
  const isAlert = tone === "alert" && (isNumeric ? value > 0 : true);

  return (
    <div className={`pm-card${isAlert ? " pm-card--alert" : ""}`}>
      <span className="pm-card__label">{label}</span>
      <strong className="pm-card__value">
        {displayVal}
        {suffix && <span style={{ fontSize: "0.85rem", fontWeight: 500, marginLeft: "0.25rem" }}>{suffix}</span>}
      </strong>
    </div>
  );
}

function RankTable({ title, items, total }: { title: string; items: SummaryItem[]; total: number }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="pm-rank">
      <h3>{title}</h3>
      <table className="pm-rank__table">
        <tbody>
          {items.slice(0, 10).map((item) => {
            const share = total > 0 ? (item.count / total) * 100 : 0;
            return (
              <tr key={item.label}>
                <td className="pm-rank__label">{item.label}</td>
                <td className="pm-rank__bar">
                  <span style={{ width: `${Math.max(share, 2)}%` }} />
                </td>
                <td className="pm-rank__count">{formatNumber(item.count)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {items.length > 10 && (
        <p className="pm-note">... dan {formatNumber(items.length - 10)} lainnya, lengkapnya ada di berkas unduhan.</p>
      )}
    </div>
  );
}

function MapFitter({ bounds }: { bounds: [number, number, number, number] }) {
  const map = useMap();
  useEffect(() => {
    if (!bounds || bounds[0] === undefined) return;
    const [minLon, minLat, maxLon, maxLat] = bounds;
    map.fitBounds(
      [
        [minLat, minLon],
        [maxLat, maxLon]
      ],
      { padding: [24, 24], maxZoom: 15 }
    );
  }, [map, bounds]);
  return null;
}

export function PointMatchView() {
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SpatialResult | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const upload = useCallback(async (file: File) => {
    setIsUploading(true);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await authFetch("/api/point-match/analyze", {
        method: "POST",
        body: formData
      });

      if (!response.ok) {
        let message = `Gagal memproses berkas (kode ${response.status}).`;
        try {
          const body = await response.json();
          if (body?.detail) {
            message = String(body.detail);
          }
        } catch {
          // biarkan pesan bawaan
        }
        throw new Error(message);
      }

      setResult((await response.json()) as SpatialResult);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Gagal memproses berkas.");
    } finally {
      setIsUploading(false);
    }
  }, []);

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (file) {
      void upload(file);
    }
  };

  const isPolygon = result?.kind === "polygon";
  const pointResult = result && result.kind !== "polygon" ? (result as PointMatchResult) : null;
  const polyResult = result && result.kind === "polygon" ? (result as PolygonMatchResult) : null;

  const pointHeaders = pointResult ? [...BASE_HEADERS, ...pointResult.property_columns] : BASE_HEADERS;

  return (
    <section className="panel--matrix matrix-shell">
      <div className="matrix-header-bar glass-panel">
        <div className="matrix-header-copy">
          <p className="panel-eyebrow">Uji Tumpang Tindih Spasial</p>
          <h2>Cek Titik Api (Titik dan Poligon)</h2>
          <p className="muted-copy">
            Unggah berkas titik atau poligon (KML, GeoJSON, atau SHP dalam ZIP). Sistem otomatis mendeteksi: berkas
            titik dicocokkan ke perizinan KPS, atau berkas poligon dicek sebaran titik panas NASA sepanjang tahun ini (di
            dalam maupun di luar kawasan).
          </p>
        </div>
        {result && (
          <div className="matrix-header-actions">
            <button
              type="button"
              className="matrix-header-action matrix-header-action--ghost"
              onClick={() =>
                void downloadWithAuth(
                  `/api/point-match/${result.token}/export.xlsx`,
                  isPolygon ? `titik-panas-poligon-${result.source_name}.xlsx` : `cek-titik-ke-kps.xlsx`
                )
              }
            >
              <FileSpreadsheet size={14} />
              Unduh Excel
            </button>
            <button
              type="button"
              className="matrix-header-action matrix-header-action--ghost"
              onClick={() =>
                void downloadWithAuth(
                  `/api/point-match/${result.token}/export.pdf`,
                  isPolygon ? `titik-panas-poligon-${result.source_name}.pdf` : `cek-titik-ke-kps.pdf`
                )
              }
            >
              <FileText size={14} />
              Unduh PDF
            </button>
          </div>
        )}
      </div>

      <div
        className={`pm-drop glass-panel${isDragging ? " pm-drop--active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          hidden
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <UploadCloud size={30} />
        <p className="pm-drop__title">
          {isUploading
            ? "Menganalisis berkas spasial dan mencocokkan titik api..."
            : "Tarik & lepas berkas titik atau poligon di sini, atau klik untuk memilih"}
        </p>
        <p className="pm-drop__hint">
          Format: .geojson, .json, .kml, atau .zip berisi shapefile (.shp + .shx + .dbf).
          Mendukung Titik (cek perizinan KPS) dan Poligon (cek riwayat titik panas NASA 2026).
        </p>
      </div>

      {error && (
        <div className="pm-alert pm-alert--error" role="alert">
          <X size={15} />
          <span>{error}</span>
        </div>
      )}

      {/* HASIL MODE POLIGON */}
      {polyResult && (
        <>
          <div className="pm-mode-pill">
            <Layers size={13} />
            <span>Mode Analisis Poligon Kawasan</span>
          </div>

          {polyResult.warnings.map((warning) => (
            <div className="pm-alert pm-alert--warn" key={warning}>
              <span>{warning}</span>
            </div>
          ))}

          {/* Status Kawasan */}
          {polyResult.polygon_info.overlaps_kps ? (
            <div className="pm-overlap pm-overlap--yes">
              <ShieldCheck size={20} style={{ flexShrink: 0, marginTop: "2px" }} />
              <div>
                <strong>
                  Kawasan Beririsan dengan Perhutanan Sosial ({polyResult.polygon_info.kps_matches.length} unit
                  terdeteksi)
                </strong>
                <p className="pm-overlap__desc">
                  Unit terkait:{" "}
                  {polyResult.polygon_info.kps_matches
                    .map((m) => `${m.lembaga || "KPS"} (${m.skema || "-"}, ${m.nama_kab || "-"})`)
                    .join(" • ")}
                </p>
              </div>
            </div>
          ) : (
            <div className="pm-overlap pm-overlap--no">
              <ShieldAlert size={20} style={{ flexShrink: 0, marginTop: "2px" }} />
              <div>
                <strong>Kawasan di Luar Perhutanan Sosial (Non-KPS)</strong>
                <p className="pm-overlap__desc">
                  Poligon berada di luar areal izin Perhutanan Sosial (Areal Konsesi / Hutan Bebas / Lainnya). Titik
                  panas diverifikasi langsung terhadap riwayat satelit NASA FIRMS sepanjang tahun 2026.
                </p>
              </div>
            </div>
          )}

          {/* Kartu Ringkasan Poligon */}
          <div className="pm-cards pm-cards--5">
            <SummaryCard
              label="Total Titik Panas (2026)"
              value={polyResult.summary.total_hotspots}
              tone={polyResult.summary.total_hotspots > 0 ? "alert" : "normal"}
            />
            <SummaryCard
              label="Luas Areal"
              value={polyResult.polygon_info.area_ha ? polyResult.polygon_info.area_ha.toLocaleString("id-ID", { maximumFractionDigits: 1 }) : 0}
              suffix="Ha"
            />
            <SummaryCard
              label="Kerapatan Hotspot"
              value={polyResult.summary.density_per_1000ha.toFixed(2)}
              suffix="/ 1k Ha"
            />
            <SummaryCard
              label="Keyakinan Tinggi (High)"
              value={polyResult.summary.confidence_high}
              tone={polyResult.summary.confidence_high > 0 ? "alert" : "normal"}
            />
            <SummaryCard
              label="Keyakinan Sedang"
              value={polyResult.summary.confidence_medium}
            />
          </div>

          {/* Grid Peta & Rangkuman */}
          <div className="pm-poly-preview">
            <div className="pm-map-container glass-panel">
              <MapContainer
                center={[-2.5, 118]}
                zoom={5}
                preferCanvas
                style={{ height: "100%", width: "100%" }}
              >
                <TileLayer
                  attribution="Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
                  url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
                  maxZoom={16}
                />
                {polyResult.polygon_info.bounds && <MapFitter bounds={polyResult.polygon_info.bounds} />}
                {polyResult.polygon_geojson && (
                  <LeafletGeoJson
                    data={polyResult.polygon_geojson}
                    style={{
                      color: "#f59e0b",
                      weight: 2,
                      fillColor: "#f59e0b",
                      fillOpacity: 0.12
                    }}
                  />
                )}
                {polyResult.hotspots.map((hs) => {
                  const conf = hs.confidence_level;
                  const color = conf === "Tinggi" ? "#ef4444" : conf === "Sedang" ? "#f59e0b" : "#eab308";
                  return (
                    <CircleMarker
                      key={hs.id || `${hs.latitude}-${hs.longitude}-${hs.detected_at}`}
                      center={[hs.latitude, hs.longitude]}
                      radius={5}
                      pathOptions={{
                        color: color,
                        fillColor: color,
                        fillOpacity: 0.85,
                        weight: 1.5
                      }}
                    >
                      <Popup>
                        <div style={{ fontSize: "0.8rem", lineHeight: 1.5, color: "#111827" }}>
                          <strong style={{ display: "block", marginBottom: "3px" }}>
                            <Flame size={12} style={{ display: "inline", verticalAlign: "middle", marginRight: "4px" }} />
                            Titik Panas NASA
                          </strong>
                          <div>Waktu: {hs.detected_at_wib}</div>
                          <div>Satelit: {hs.satellite}</div>
                          <div>Keyakinan: {conf} ({hs.confidence})</div>
                          <div>Kecerahan: {hs.brightness} K</div>
                          <div>FRP: {hs.frp} MW</div>
                          <div>Koordinat: {hs.latitude.toFixed(5)}, {hs.longitude.toFixed(5)}</div>
                        </div>
                      </Popup>
                    </CircleMarker>
                  );
                })}
              </MapContainer>
            </div>

            <div className="pm-ranks glass-panel" style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <RankTable
                title="Sebaran Titik Panas per Bulan (2026)"
                items={polyResult.summary.by_month}
                total={polyResult.summary.total_hotspots}
              />
              <RankTable
                title="Sebaran per Satelit / Sensor"
                items={polyResult.summary.by_satellite}
                total={polyResult.summary.total_hotspots}
              />
            </div>
          </div>

          {/* Tabel Titik Panas */}
          <div className="matrix-ledger glass-panel">
            <div className="matrix-ledger-head">
              <div>
                <p className="panel-eyebrow">Data Titik Panas</p>
                <h3>{polyResult.source_name}</h3>
              </div>
              <span className="muted-copy">
                {polyResult.preview_truncated
                  ? `Menampilkan ${formatNumber(polyResult.preview_rows.length)} dari ${formatNumber(polyResult.summary.total_hotspots)} titik panas`
                  : `${formatNumber(polyResult.summary.total_hotspots)} titik panas terdeteksi sepanjang 2026`}
              </span>
            </div>

            <div className="matrix-table-wrap">
              <div className="matrix-scroll">
                <table className="matrix-table">
                  <thead>
                    <tr>
                      {POLYGON_HEADERS.map((header) => (
                        <th key={header} scope="col">
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {polyResult.preview_rows.map((row, index) => (
                      <tr key={index}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex} data-label={POLYGON_HEADERS[cellIndex]}>
                            {cellIndex === 5 ? (
                              <span
                                className={`pm-badge ${
                                  cell === "Tinggi"
                                    ? "pm-badge--high"
                                    : cell === "Sedang"
                                      ? "pm-badge--med"
                                      : "pm-badge--low"
                                }`}
                              >
                                {String(cell ?? "")}
                              </span>
                            ) : (
                              String(cell ?? "")
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                    {polyResult.preview_rows.length === 0 && (
                      <tr>
                        <td colSpan={POLYGON_HEADERS.length} style={{ textAlign: "center", padding: "2rem", color: "#9ca3af" }}>
                          Tidak ada titik panas NASA yang terdeteksi di dalam poligon ini sepanjang tahun 2026.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {polyResult.preview_truncated && (
              <p className="pm-note">
                <Download size={13} /> Data lengkap seluruh {formatNumber(polyResult.summary.total_hotspots)} titik
                tersedia di berkas Excel dan PDF.
              </p>
            )}
          </div>
        </>
      )}

      {/* HASIL MODE TITIK (LEGACY / TITIK KE KPS) */}
      {pointResult && (
        <>
          <div className="pm-mode-pill">
            <MapPin size={13} />
            <span>Mode Pencocokan Titik ke KPS</span>
          </div>

          {pointResult.warnings.map((warning) => (
            <div className="pm-alert pm-alert--warn" key={warning}>
              <span>{warning}</span>
            </div>
          ))}
          {pointResult.skipped_features > 0 && (
            <div className="pm-alert pm-alert--warn">
              <span>
                {formatNumber(pointResult.skipped_features)} fitur dilewati karena bukan titik atau koordinatnya tidak
                valid.
              </span>
            </div>
          )}

          <div className="pm-cards">
            <SummaryCard label="Total Titik" value={pointResult.summary.total_points} />
            <SummaryCard label="Masuk KPS" value={pointResult.summary.inside_count} />
            <SummaryCard label="Di Luar KPS" value={pointResult.summary.outside_count} tone="alert" />
            <SummaryCard label="KPS Terdampak" value={pointResult.summary.distinct_kps} />
          </div>

          <div className="pm-ranks glass-panel">
            <RankTable title="Titik per KPS" items={pointResult.summary.by_kps} total={pointResult.summary.total_points} />
            <RankTable
              title="Titik per Balai PS"
              items={pointResult.summary.by_wilker}
              total={pointResult.summary.total_points}
            />
            <RankTable
              title="Titik per Provinsi"
              items={pointResult.summary.by_province}
              total={pointResult.summary.total_points}
            />
          </div>

          <div className="matrix-ledger glass-panel">
            <div className="matrix-ledger-head">
              <div>
                <p className="panel-eyebrow">Hasil Pencocokan</p>
                <h3>{pointResult.source_name}</h3>
              </div>
              <span className="muted-copy">
                {pointResult.preview_truncated
                  ? `Menampilkan ${formatNumber(pointResult.preview_rows.length)} dari ${formatNumber(pointResult.summary.total_points)} titik`
                  : `${formatNumber(pointResult.summary.total_points)} titik`}
              </span>
            </div>

            <div className="matrix-table-wrap">
              <div className="matrix-scroll">
                <table className="matrix-table">
                  <thead>
                    <tr>
                      {pointHeaders.map((header) => (
                        <th key={header} scope="col">
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pointResult.preview_rows.map((row, index) => (
                      <tr key={index}>
                        {row.map((cell, cellIndex) => (
                          <td
                            key={cellIndex}
                            data-label={pointHeaders[cellIndex]}
                            className={
                              cellIndex === STATUS_COLUMN && cell === "Di luar KPS"
                                ? "pm-status pm-status--outside"
                                : cellIndex === STATUS_COLUMN
                                  ? "pm-status"
                                  : undefined
                            }
                          >
                            {String(cell ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {pointResult.preview_truncated && (
              <p className="pm-note">
                <Download size={13} /> Data lengkap seluruh {formatNumber(pointResult.summary.total_points)} titik
                tersedia di berkas Excel dan PDF.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
