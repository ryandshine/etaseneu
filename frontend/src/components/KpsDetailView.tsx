import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Download } from "lucide-react";
import { CircleMarker, GeoJSON, MapContainer, Pane, Popup, TileLayer, useMap } from "react-leaflet";
import { geoJSON as buildLeafletGeoJSON } from "leaflet";

import type { DashboardHotspot } from "../hooks/useDashboardData";
import type { PolygonDetail } from "../types/api";
import { WeatherConditionCard } from "./WeatherConditionCard";
import {
  buildComparison,
  formatMetadataValue,
  formatNumber,
  formatTimestamp,
  getFrpCategory,
  getStatusLabel,
  normalizeFrpCategoryLabel
} from "../lib/hotspotDisplay";

const DETECTION_PAGE_SIZE = 10;

const MONTH_LABELS = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember"
];

type BurnedAreaRow = {
  polygon_metadata_id: number;
  layer_key: string;
  year: number;
  month: number;
  burned_area_ha: number;
  source: string;
};

type BurnedAreaFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: Record<string, unknown>;
    properties: { year: number; month: number; burned_area_ha: number };
  }>;
};

type KpsDetailViewProps = {
  agency: string;
  hotspots: DashboardHotspot[];
  onClose: () => void;
  onExportPdf: (filters: { agency?: string }) => void;
  isExportingPdf: boolean;
};

function sourceColor(source: string): string {
  if (source === "MODIS") {
    return "#ff8c42";
  }
  if (source.startsWith("VIIRS")) {
    return "#facc15";
  }
  return "#ffd7a8";
}

// Peta polygon detail dimulai dari view Indonesia lalu di-fit ke batas
// polygon setelah geometrinya datang -- fitBounds butuh instance peta, jadi
// harus jadi komponen anak MapContainer sendiri (pola yang sama dengan
// MapViewport di HotspotMap.tsx).
function FitToPolygon({ geometry }: { geometry: Record<string, unknown> }) {
  const map = useMap();

  useEffect(() => {
    try {
      const layer = buildLeafletGeoJSON(geometry as never);
      const bounds = layer.getBounds();
      if (bounds.isValid()) {
        // Ukuran disegarkan dulu: fitBounds menghitung zoom dari ukuran yang
        // Leaflet KIRA dimilikinya, jadi kalau kontainer sudah tumbuh tanpa
        // sepengetahuan Leaflet, hasil fit-nya ikut meleset.
        map.invalidateSize({ animate: false });
        map.fitBounds(bounds, { padding: [32, 32] });
      }
    } catch {
      // Geometry tidak valid -- peta tetap di posisi default, tidak fatal.
    }
  }, [geometry, map]);

  return null;
}

/**
 * Beritahu Leaflet setiap kali kontainernya berubah ukuran.
 *
 * Tinggi peta di halaman ini ditentukan oleh baris grid, yang tingginya
 * mengikuti sidebar kiri -- dan sidebar itu baru terisi setelah data detail
 * tiba dari server. Leaflet mengukur kontainernya sekali saat inisialisasi dan
 * tidak memantau perubahan ukuran, sehingga ia hanya menggambar ubin untuk
 * area lama: peta tampak terpotong dengan area hitam di bawahnya.
 *
 * Sengaja hanya invalidateSize, tanpa fitBounds ulang, supaya posisi dan zoom
 * yang sedang dilihat pengguna tidak tereset setiap kali ada perubahan tata
 * letak (mis. saat jendela diubah ukurannya).
 */
function KeepMapSized() {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    if (typeof ResizeObserver === "undefined") {
      return;
    }

    let frame = 0;
    const observer = new ResizeObserver(() => {
      // Ditunda ke frame berikutnya supaya pengukuran ulang terjadi setelah
      // browser selesai menata ulang, bukan di tengah-tengahnya.
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => map.invalidateSize({ animate: false }));
    });

    observer.observe(container);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [map]);

  return null;
}

const INFO_FIELDS: Array<[label: string, key: keyof PolygonDetail]> = [
  ["Balai PS", "wilker_bps"],
  ["Provinsi", "nama_prov"],
  ["Kabupaten", "nama_kab"],
  ["Kecamatan", "nama_kec"],
  ["Desa", "nama_desa"],
  ["Skema", "skema"],
  ["No. SK", "no_sk"],
  ["Tanggal SK", "tgl_sk"],
  ["Status", "status"],
  ["PS ID", "ps_id"],
  ["Luas Final (Ha)", "luas_final"],
  ["Jumlah KK", "jml_kk"]
];

export function KpsDetailView({ agency, hotspots, onClose, onExportPdf, isExportingPdf }: KpsDetailViewProps) {
  // Semua titik hotspot milik KPS ini sudah tersedia dari dataset yang sama
  // dipakai Buku Besar -- tidak perlu endpoint tambahan, tinggal disaring
  // pakai nama KPS (LEMBAGA/agencyName), yang selalu ada di tiap baris
  // (beda dari polygon_metadata_id yang bisa saja belum ke-link).
  const kpsHotspots = useMemo(
    () =>
      hotspots
        .filter((hotspot) => formatMetadataValue(hotspot.polygonMetadata.LEMBAGA || hotspot.agencyName) === agency)
        .sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime()),
    [hotspots, agency]
  );

  // Cari ID polygon dari hotspot MANAPUN di grup ini yang sudah ke-link --
  // bukan cuma yang terbaru, supaya satu-dua titik yang belum sempat
  // ke-spatial-join tidak bikin seluruh halaman kehilangan polygon-nya.
  const polygonId = useMemo(() => {
    for (const hotspot of kpsHotspots) {
      const raw = hotspot.polygonMetadata.polygon_metadata_id;
      const parsed = raw ? Number(raw) : NaN;
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
    return null;
  }, [kpsHotspots]);

  const [detail, setDetail] = useState<PolygonDetail | null>(null);
  const [loading, setLoading] = useState(polygonId !== null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (polygonId === null) {
      setDetail(null);
      setLoading(false);
      setError(null);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);
    setDetail(null);

    fetch(`/api/polygons/${polygonId}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 404
              ? "Polygon KPS ini tidak ditemukan."
              : "Gagal memuat data polygon."
          );
        }
        return response.json() as Promise<PolygonDetail>;
      })
      .then((payload) => {
        if (active) {
          setDetail(payload);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Gagal memuat data polygon.");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [polygonId]);

  // Luas kebakaran (MODIS MCD64A1) untuk polygon ini. Sengaja dibiarkan
  // gagal diam-diam: produknya terbit bulanan dengan lag rilis beberapa
  // bulan, jadi KPS yang datanya belum dihitung adalah kondisi normal --
  // bukan error yang perlu ditampilkan sebagai kegagalan halaman.
  const [burnedAreas, setBurnedAreas] = useState<BurnedAreaRow[]>([]);
  const [burnedGeometry, setBurnedGeometry] = useState<BurnedAreaFeatureCollection | null>(null);

  useEffect(() => {
    if (polygonId === null) {
      setBurnedAreas([]);
      setBurnedGeometry(null);
      return;
    }

    let active = true;
    // Difilter di server (polygon_ids), bukan unduh semua lalu saring di sini --
    // tabelnya bisa puluhan ribu baris kalau seluruh KPS sudah dihitung.
    fetch(`/api/burned-area/summary?polygon_ids=${polygonId}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { rows?: BurnedAreaRow[] } | null) => {
        if (active && payload?.rows) {
          setBurnedAreas(payload.rows);
        }
      })
      .catch(() => {
        /* diamkan -- lihat komentar di atas */
      });

    fetch(`/api/burned-area/geometry?polygon_ids=${polygonId}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: BurnedAreaFeatureCollection | null) => {
        if (active && payload?.features?.length) {
          setBurnedGeometry(payload);
        }
      })
      .catch(() => {
        /* diamkan -- lihat komentar di atas */
      });

    return () => {
      active = false;
    };
  }, [polygonId]);

  const burnedAreaStats = useMemo(() => {
    if (burnedAreas.length === 0) {
      return null;
    }
    const totalHa = burnedAreas.reduce((sum, row) => sum + (row.burned_area_ha ?? 0), 0);
    const sorted = [...burnedAreas].sort(
      (a, b) => b.year - a.year || b.month - a.month
    );
    return { totalHa, latest: sorted[0], months: sorted };
  }, [burnedAreas]);

  const stats = useMemo(() => {
    let tinggi = 0;
    let sedang = 0;
    let rendah = 0;
    const satellites = new Set<string>();

    kpsHotspots.forEach((hotspot) => {
      const frp = hotspot.frp ?? 0;
      if (frp > 30) {
        tinggi += 1;
      } else if (frp >= 10) {
        sedang += 1;
      } else {
        rendah += 1;
      }
      satellites.add(hotspot.source);
    });

    return { total: kpsHotspots.length, tinggi, sedang, rendah, satellites: Array.from(satellites) };
  }, [kpsHotspots]);

  // Deteksi yang sedang ditelaah di bawah -- default ke yang paling baru,
  // tapi user bisa ketuk baris lain di "Daftar Deteksi Hotspot".
  const [selectedDetectionId, setSelectedDetectionId] = useState<string | null>(null);
  const [detectionPage, setDetectionPage] = useState(1);
  const detectionTotalPages = Math.max(1, Math.ceil(kpsHotspots.length / DETECTION_PAGE_SIZE));
  const pagedKpsHotspots = kpsHotspots.slice(
    (detectionPage - 1) * DETECTION_PAGE_SIZE,
    detectionPage * DETECTION_PAGE_SIZE
  );
  const selectedDetection = useMemo(
    () => kpsHotspots.find((hotspot) => hotspot.id === selectedDetectionId) ?? kpsHotspots[0] ?? null,
    [kpsHotspots, selectedDetectionId]
  );

  const comparison = useMemo(
    () => buildComparison(hotspots, selectedDetection),
    [hotspots, selectedDetection]
  );

  return (
    <div className="kps-detail">
      <header className="kps-detail-header">
        <button type="button" className="kps-detail-back" onClick={onClose}>
          <ArrowLeft size={16} />
          Kembali ke Matriks Data
        </button>
        <div className="kps-detail-title-row">
          <h2 className="kps-detail-title">{detail?.lembaga || agency}</h2>
          <button
            type="button"
            className="matrix-btn matrix-btn--primary"
            onClick={() => onExportPdf({ agency })}
            disabled={isExportingPdf}
          >
            <Download size={14} />
            {isExportingPdf ? "Mengunduh PDF..." : "Unduh Laporan Lembaga (PDF)"}
          </button>
        </div>
      </header>

      {error ? <p className="toast-error toast-error--inline">{error}</p> : null}

      <div className="kps-detail-body">
        <aside className="kps-detail-info panel">
          {loading ? (
            <p className="help-copy">Memuat informasi KPS...</p>
          ) : detail ? (
            <dl className="kps-detail-fields">
              {INFO_FIELDS.map(([label, key]) => {
                const value = detail[key];
                if (!value) {
                  return null;
                }
                return (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>{String(value)}</dd>
                  </div>
                );
              })}
            </dl>
          ) : (
            <p className="help-copy">Polygon KPS ini belum terhubung ke data spasial.</p>
          )}

          <div className="kps-detail-stats">
            <div className="control-metric">
              <span>Total hotspot terpantau:</span>
              <strong>{stats.total}</strong>
            </div>
            {stats.total > 0 && (
              <div className="kps-detail-frp-breakdown">
                <div>
                  <span style={{ color: "#ef4444" }}>■</span> Tinggi <strong>{stats.tinggi}</strong>
                </div>
                <div>
                  <span style={{ color: "#f59e0b" }}>■</span> Sedang <strong>{stats.sedang}</strong>
                </div>
                <div>
                  <span style={{ color: "#3b82f6" }}>■</span> Rendah <strong>{stats.rendah}</strong>
                </div>
              </div>
            )}
            {stats.satellites.length > 0 && (
              <p className="help-copy">Satelit: {stats.satellites.join(", ")}</p>
            )}

            {burnedAreaStats && (
              <div style={{ marginTop: "1rem", paddingTop: "0.85rem", borderTop: "1px solid rgba(255,255,255,0.08)" }}>
                <div className="control-metric">
                  <span>Luas terbakar (total):</span>
                  <strong>{formatNumber(Math.round(burnedAreaStats.totalHa * 10) / 10)} Ha</strong>
                </div>
                <p className="help-copy" style={{ marginTop: "0.4rem" }}>
                  Terakhir dihitung: {MONTH_LABELS[burnedAreaStats.latest.month - 1]}{" "}
                  {burnedAreaStats.latest.year}
                </p>
                {burnedAreaStats.months.length > 1 && (
                  <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                    {burnedAreaStats.months.slice(0, 6).map((row) => (
                      <div
                        key={`${row.year}-${row.month}`}
                        style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", color: "#9ca3af" }}
                      >
                        <span>
                          {MONTH_LABELS[row.month - 1]} {row.year}
                        </span>
                        <span>{formatNumber(Math.round(row.burned_area_ha * 10) / 10)} Ha</span>
                      </div>
                    ))}
                  </div>
                )}
                {burnedGeometry && (
                  <p className="help-copy" style={{ marginTop: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span
                      style={{
                        display: "inline-block",
                        width: "12px",
                        height: "12px",
                        background: "rgba(220,38,38,0.45)",
                        border: "1px solid #dc2626",
                        flexShrink: 0
                      }}
                    />
                    Area merah di peta = jejak lahan terbakar.
                  </p>
                )}
                <p className="help-copy" style={{ marginTop: "0.5rem", fontSize: "0.72rem" }}>
                  Sumber: MODIS MCD64A1 (resolusi 500 m, terbit bulanan dengan jeda beberapa bulan).
                </p>
              </div>
            )}
          </div>
        </aside>

        <div className="kps-detail-map">
          <MapContainer center={[-2.5, 118]} zoom={5} preferCanvas style={{ height: "100%", width: "100%" }}>
            <KeepMapSized />
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />
            {detail ? (
              <>
                <FitToPolygon geometry={detail.geometry} />
                <GeoJSON
                  data={{ type: "Feature", properties: {}, geometry: detail.geometry } as never}
                  // Batas KPS tidak punya popup maupun penangan klik. Selama ia
                  // ikut diperhitungkan, Leaflet memilih lapisan tergambar
                  // paling akhir sebagai sasaran klik -- dan karena geometri
                  // baru tiba setelah titik hotspot terpasang, polygon inilah
                  // yang menang, lalu kliknya dibuang tanpa jejak. Titik jadi
                  // terlihat mati padahal penanganya ada.
                  style={{
                    color: "#ff8c42",
                    weight: 3,
                    fillColor: "#ff8c42",
                    fillOpacity: 0.14,
                    interactive: false
                  }}
                />
              </>
            ) : null}
            {/* Jejak area terbakar (MCD64A1). Di panel sendiri di antara batas
                KPS (overlayPane, 400) dan titik hotspot (450) supaya arsiran
                merahnya menimpa batas kawasan tapi tidak menutupi titik. */}
            {burnedGeometry && (
              <Pane name="area-terbakar" style={{ zIndex: 420 }}>
                <GeoJSON
                  key={`burned-${polygonId}`}
                  data={burnedGeometry as never}
                  style={{
                    color: "#dc2626",
                    weight: 1,
                    fillColor: "#dc2626",
                    fillOpacity: 0.45,
                    interactive: true
                  }}
                  onEachFeature={(feature, layer) => {
                    const props = feature.properties as {
                      year: number;
                      month: number;
                      burned_area_ha: number;
                    };
                    layer.bindPopup(
                      `<div style="font-size:12px;font-family:sans-serif">
                         <strong>Area terbakar</strong><br/>
                         ${MONTH_LABELS[props.month - 1]} ${props.year}<br/>
                         ${formatNumber(Math.round(props.burned_area_ha * 10) / 10)} Ha
                       </div>`
                    );
                  }}
                />
              </Pane>
            )}
            {/* Panel sendiri di atas overlayPane (z-index 400) supaya titik
                hotspot tidak tertutup arsiran polygon, apa pun urutan
                datangnya data. */}
            <Pane name="hotspot-titik" style={{ zIndex: 450 }}>
              {kpsHotspots.map((hotspot) => (
                <CircleMarker
                  key={hotspot.id}
                  center={[hotspot.latitude, hotspot.longitude]}
                  radius={6}
                  pathOptions={{
                    color: "#1b120d",
                    weight: 2,
                    fillColor: sourceColor(hotspot.source),
                    fillOpacity: 0.95
                  }}
                  eventHandlers={{ click: () => setSelectedDetectionId(hotspot.id) }}
                >
                  <Popup>
                    <div style={{ fontSize: "12px", fontFamily: "sans-serif" }}>
                      <strong>{hotspot.source}</strong> ({hotspot.satellite})
                      <div>FRP: {hotspot.frp?.toFixed(2) ?? "Tidak tersedia"}</div>
                      <div>{new Date(hotspot.detectedAt).toLocaleString("id-ID")}</div>
                    </div>
                  </Popup>
                </CircleMarker>
              ))}
            </Pane>
          </MapContainer>
        </div>
      </div>

      {/* Konten di bawah ini mengalir dalam scroll satu halaman (bukan
          panel geser terpisah dengan scroll sendiri) -- lihat catatan
          "Eliminasi Nested Scroll" di HotspotMatrix.tsx. */}
      {selectedDetection && (
        <div className="kps-detail-sections">
          <section className="matrix-detail-card">
            <div className="matrix-detail-card__head">
              <span>Segmen Lokasi</span>
              <strong>{getStatusLabel(selectedDetection)}</strong>
            </div>
            <div className="matrix-detail-grid matrix-detail-grid--two">
              <div className="matrix-detail-item">
                <span>Sumber</span>
                <strong>{formatMetadataValue(selectedDetection.source)}</strong>
              </div>
              <div className="matrix-detail-item">
                <span>Satelit</span>
                <strong>{formatMetadataValue(selectedDetection.satellite)}</strong>
              </div>
              <div className="matrix-detail-item">
                <span>Siang/Malam</span>
                <strong>{formatMetadataValue(selectedDetection.daynight)}</strong>
              </div>
              <div className="matrix-detail-item">
                <span>Terdeteksi</span>
                <strong>{formatTimestamp(selectedDetection.detectedAt)}</strong>
              </div>
            </div>
            <div className="matrix-code-block">
              <p className="matrix-code-block__label">Koordinat</p>
              <strong>
                {selectedDetection.latitude.toFixed(5)}, {selectedDetection.longitude.toFixed(5)}
              </strong>
            </div>
          </section>

          <WeatherConditionCard lat={selectedDetection.latitude} lon={selectedDetection.longitude} />

          <section className="matrix-detail-card">
            <div className="matrix-detail-card__head">
              <span>Grafik Data Intensitas</span>
              <strong>Terpilih vs populasi</strong>
            </div>
            <div className="matrix-comparison-block">
              <div className="matrix-comparison-head">
                <span>Perbandingan FRP (MW)</span>
                <strong>{formatNumber(selectedDetection.frp)}</strong>
              </div>
              <div className="matrix-comparison-list">
                {comparison.frp.map((item) => {
                  const max = Math.max(...comparison.frp.map((entry) => entry.value), 1);
                  const width = `${Math.max((item.value / max) * 100, item.value > 0 ? 12 : 0)}%`;
                  return (
                    <div key={item.label} className="matrix-comparison-row">
                      <span>{item.label}</span>
                      <div className="matrix-bar-track matrix-bar-track--mini">
                        <span className="matrix-bar-fill" style={{ width, background: item.color }} />
                      </div>
                      <strong>{item.value}</strong>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="matrix-comparison-block">
              <div className="matrix-comparison-head">
                <span>Perbandingan Kecerahan (K)</span>
                <strong>{formatNumber(selectedDetection.brightness)}</strong>
              </div>
              <div className="matrix-comparison-list">
                {comparison.brightness.map((item) => {
                  const max = Math.max(...comparison.brightness.map((entry) => entry.value), 1);
                  const width = `${Math.max((item.value / max) * 100, item.value > 0 ? 12 : 0)}%`;
                  return (
                    <div key={item.label} className="matrix-comparison-row">
                      <span>{item.label}</span>
                      <div className="matrix-bar-track matrix-bar-track--mini">
                        <span className="matrix-bar-fill" style={{ width, background: item.color }} />
                      </div>
                      <strong>{item.value}</strong>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          <section className="matrix-detail-card">
            <div className="matrix-detail-card__head">
              <span>Daftar Deteksi Hotspot ({kpsHotspots.length} titik)</span>
              <strong>Ketuk untuk detail</strong>
            </div>
            <div className="detect-list">
              <table className="detect-table">
                <thead>
                  <tr>
                    <th scope="col">Tanggal</th>
                    <th scope="col">Satelit</th>
                    <th scope="col">Kelas FRP</th>
                    <th scope="col">FRP</th>
                    <th scope="col">Lat/Lon</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedKpsHotspots.map((hotspot) => {
                    const isActive = selectedDetection.id === hotspot.id;
                    return (
                      <tr
                        key={hotspot.id}
                        className={isActive ? "detect-row detect-row--active" : "detect-row"}
                        onClick={() => setSelectedDetectionId(hotspot.id)}
                        role="button"
                        tabIndex={0}
                        aria-current={isActive || undefined}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setSelectedDetectionId(hotspot.id);
                          }
                        }}
                      >
                        <td className="dt-waktu">{formatTimestamp(hotspot.detectedAt)}</td>
                        <td className="dt-satelit">{hotspot.source}</td>
                        <td className="dt-kelas">
                          <span
                            className={`confidence-pill confidence-pill--${
                              getFrpCategory(hotspot) === "Tinggi" ? "high" : getFrpCategory(hotspot) === "Sedang" ? "nominal" : "low"
                            }`}
                          >
                            {normalizeFrpCategoryLabel(hotspot)}
                          </span>
                        </td>
                        <td className="dt-frp">{formatNumber(hotspot.frp)} MW</td>
                        <td className="dt-koord" title={`${hotspot.latitude.toFixed(4)}, ${hotspot.longitude.toFixed(4)}`}>
                          {hotspot.latitude.toFixed(3)}, {hotspot.longitude.toFixed(3)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="matrix-footer">
              <span className="matrix-footer__count">{kpsHotspots.length} titik</span>
              <div className="matrix-pagination">
                <button
                  type="button"
                  className="matrix-page-btn"
                  onClick={() => setDetectionPage((page) => Math.max(1, page - 1))}
                  disabled={detectionPage === 1}
                  aria-label="Halaman sebelumnya"
                >
                  ‹
                </button>
                <span className="matrix-page-info">
                  Halaman {detectionPage} / {detectionTotalPages}
                </span>
                <button
                  type="button"
                  className="matrix-page-btn"
                  onClick={() => setDetectionPage((page) => Math.min(detectionTotalPages, page + 1))}
                  disabled={detectionPage >= detectionTotalPages}
                  aria-label="Halaman berikutnya"
                >
                  ›
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
