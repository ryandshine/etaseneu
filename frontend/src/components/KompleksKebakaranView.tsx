import { useEffect, useMemo, useState } from "react";
import { Check, Copy } from "lucide-react";
import {
  Circle,
  CircleMarker,
  GeoJSON,
  MapContainer,
  Pane,
  Popup,
  ScaleControl,
  TileLayer,
  useMap,
  ZoomControl
} from "react-leaflet";
import { createApiClient } from "../lib/api";
import { SMOOTH_ZOOM_MAP_PROPS } from "../constants/map";
import type { ClusterCollectionResponse, ClusterPoint, ClusterRecord, ClusterSensitivity } from "../types/api";
import type { DashboardLayer } from "../hooks/useDashboardData";

const api = createApiClient();

type TimeRangeOption = { label: string; days: number };

const TIME_RANGE_OPTIONS: TimeRangeOption[] = [
  { label: "7 Hari Terakhir", days: 7 },
  { label: "30 Hari Terakhir", days: 30 },
  { label: "24 Jam", days: 1 }
];

const SENSITIVITY_OPTIONS: {
  value: ClusterSensitivity;
  label: string;
  hint: string;
  epsKm: number;
  epsHours: number;
  minSamples: number;
}[] = [
  { value: "ketat", label: "Ketat", hint: "radius 1 km, jeda antar-deteksi 12 jam", epsKm: 1, epsHours: 12, minSamples: 4 },
  { value: "sedang", label: "Sedang (disarankan)", hint: "radius 2 km, jeda antar-deteksi 48 jam", epsKm: 2, epsHours: 48, minSamples: 4 },
  { value: "longgar", label: "Longgar", hint: "radius 5 km, jeda antar-deteksi 72 jam", epsKm: 5, epsHours: 72, minSamples: 3 }
];

const BESAR_THRESHOLD = 400;
const SEDANG_THRESHOLD = 150;
const AKTIF_THRESHOLD_HOURS = 24;
const WIB_TIME_ZONE = "Asia/Jakarta";

type Severity = { key: "besar" | "sedang" | "kecil"; label: string; color: string };

function severityOf(count: number): Severity {
  if (count >= BESAR_THRESHOLD) return { key: "besar", label: "Besar", color: "#ef4444" };
  if (count >= SEDANG_THRESHOLD) return { key: "sedang", label: "Sedang", color: "#f59e0b" };
  return { key: "kecil", label: "Kecil", color: "#9ca3af" };
}

function hoursSince(isoDate: string): number {
  return (Date.now() - new Date(isoDate).getTime()) / (1000 * 60 * 60);
}

function formatActivity(lastDetectedAt: string): { text: string; live: boolean } {
  const hours = hoursSince(lastDetectedAt);
  if (hours < AKTIF_THRESHOLD_HOURS) {
    return { text: `Aktif · ${hours.toFixed(1)} jam lalu`, live: true };
  }
  const days = Math.round(hours / 24);
  return { text: `Terakhir ${days} hari lalu`, live: false };
}

function formatSpanDays(firstDetectedAt: string, lastDetectedAt: string): number {
  const spanMs = new Date(lastDetectedAt).getTime() - new Date(firstDetectedAt).getTime();
  return Math.round((spanMs / (1000 * 60 * 60 * 24)) * 10) / 10;
}

function formatWibDateTime(isoDate: string): string {
  return `${new Intl.DateTimeFormat("id-ID", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: WIB_TIME_ZONE
  }).format(new Date(isoDate))} WIB`;
}

type AgencySummary = {
  name: string;
  clusterCount: number;
  hotspotCount: number;
  activeCount: number;
  largestClusterCount: number;
  lastDetectedAt: string;
  centroidLat: number;
  centroidLon: number;
};

function summarizeByAgency(clusters: ClusterRecord[]): AgencySummary[] {
  const summaries = new Map<string, AgencySummary>();

  clusters.forEach((cluster) => {
    const name = cluster.dominant_agency ?? "Tanpa lembaga teridentifikasi";
    const current = summaries.get(name);
    const active = hoursSince(cluster.last_detected_at) < AKTIF_THRESHOLD_HOURS;
    if (current) {
      const previousHotspotCount = current.hotspotCount;
      const nextHotspotCount = previousHotspotCount + cluster.hotspot_count;
      current.clusterCount += 1;
      current.hotspotCount = nextHotspotCount;
      current.activeCount += active ? 1 : 0;
      current.largestClusterCount = Math.max(current.largestClusterCount, cluster.hotspot_count);
      current.centroidLat =
        (current.centroidLat * previousHotspotCount + cluster.centroid_lat * cluster.hotspot_count) /
        nextHotspotCount;
      current.centroidLon =
        (current.centroidLon * previousHotspotCount + cluster.centroid_lon * cluster.hotspot_count) /
        nextHotspotCount;
      if (new Date(cluster.last_detected_at).getTime() > new Date(current.lastDetectedAt).getTime()) {
        current.lastDetectedAt = cluster.last_detected_at;
      }
      return;
    }

    summaries.set(name, {
      name,
      clusterCount: 1,
      hotspotCount: cluster.hotspot_count,
      activeCount: active ? 1 : 0,
      largestClusterCount: cluster.hotspot_count,
      lastDetectedAt: cluster.last_detected_at,
      centroidLat: cluster.centroid_lat,
      centroidLon: cluster.centroid_lon
    });
  });

  return Array.from(summaries.values()).sort(
    (left, right) => right.hotspotCount - left.hotspotCount || right.clusterCount - left.clusterCount
  );
}

function buildGoogleMapsUrl(latitude: number, longitude: number): string {
  const query = `${latitude.toFixed(5)},${longitude.toFixed(5)}`;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

function buildWhatsAppReport(
  response: ClusterCollectionResponse,
  clusters: ClusterRecord[],
  timeRangeDays: number,
  sensitivity: ClusterSensitivity
): string {
  const timeRange = TIME_RANGE_OPTIONS.find((option) => option.days === timeRangeDays);
  const sensitivityOption = SENSITIVITY_OPTIONS.find((option) => option.value === sensitivity);
  const rangeLabel = timeRange?.label.replace(" Terakhir", "") ?? `${timeRangeDays} Hari`;
  const sensitivityLabel = sensitivityOption?.label.replace(" (disarankan)", "") ?? sensitivity;
  const activeCount = clusters.filter(
    (cluster) => hoursSince(cluster.last_detected_at) < AKTIF_THRESHOLD_HOURS
  ).length;
  const largeCount = clusters.filter((cluster) => cluster.hotspot_count >= BESAR_THRESHOLD).length;
  const agencySummaries = summarizeByAgency(clusters);
  const identifiedAgencyCount = agencySummaries.filter(
    (summary) => summary.name !== "Tanpa lembaga teridentifikasi"
  ).length;
  const unidentifiedClusterCount = clusters.filter((cluster) => !cluster.dominant_agency).length;
  const reportTime = formatWibDateTime(new Date().toISOString());

  const lines = [
    "*LAPORAN KOMPLEKS KEBAKARAN*",
    `Periode: *${rangeLabel}*`,
    `Kepekaan: *${sensitivityLabel}*`,
    `Data: ${formatWibDateTime(response.range_start)} s.d. ${formatWibDateTime(response.range_end)}`,
    `Dibuat: ${reportTime}`,
    "",
    "*RINGKASAN*",
    `• KPS/lembaga teridentifikasi: *${identifiedAgencyCount.toLocaleString("id-ID")}*`,
    `• Total kompleks: *${clusters.length.toLocaleString("id-ID")}*`,
    `• Total titik hotspot: *${response.stats.total_hotspots_in_range.toLocaleString("id-ID")}*`,
    `• Titik tergabung: ${response.stats.clustered_hotspots.toLocaleString("id-ID")}`,
    `• Titik tidak tergabung: ${response.stats.unclustered_hotspots.toLocaleString("id-ID")}`,
    `• Kompleks aktif <24 jam: *${activeCount.toLocaleString("id-ID")}*`,
    `• Kompleks besar (≥${BESAR_THRESHOLD} titik): ${largeCount.toLocaleString("id-ID")}`,
    ...(unidentifiedClusterCount > 0
      ? [`• Kompleks tanpa lembaga dominan: ${unidentifiedClusterCount.toLocaleString("id-ID")}`]
      : []),
    "",
    agencySummaries.length > 0
      ? "*REKAP LEMBAGA DOMINAN*"
      : "*REKAP LEMBAGA DOMINAN*\nTidak ada kompleks terdeteksi.",
  ];

  agencySummaries.forEach((summary, index) => {
    lines.push(
      `${index + 1}. *${summary.name}* _(lembaga dominan)_`,
      `   • Jumlah kompleks: ${summary.clusterCount.toLocaleString("id-ID")}`,
      `   • Jumlah titik: *${summary.hotspotCount.toLocaleString("id-ID")}*`,
      `   • Kompleks aktif <24 jam: ${summary.activeCount.toLocaleString("id-ID")}`,
      `   • Kompleks terbesar: ${summary.largestClusterCount.toLocaleString("id-ID")} titik`,
      `   • Deteksi terakhir: ${formatWibDateTime(summary.lastDetectedAt)}`,
      `   📍 Google Maps: ${buildGoogleMapsUrl(summary.centroidLat, summary.centroidLon)}`
    );
  });

  lines.push("", "Sumber: ETA SEUNEU");
  return lines.join("\n");
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("Clipboard tidak tersedia");
  }
}

function FlyToCluster({ cluster }: { cluster: ClusterRecord | null }) {
  const map = useMap();
  useEffect(() => {
    if (cluster) {
      map.flyTo([cluster.centroid_lat, cluster.centroid_lon], Math.max(map.getZoom(), 8), {
        duration: 0.6
      });
    }
  }, [cluster, map]);
  return null;
}

type KompleksKebakaranViewProps = {
  onOpenKpsDetail?: (agency: string) => void;
  layers?: DashboardLayer[];
};

function featureLabel(feature: unknown): string {
  if (!feature || typeof feature !== "object") return "";
  const properties = (feature as { properties?: unknown }).properties;
  if (!properties || typeof properties !== "object") return "";
  const label = (properties as { label?: unknown }).label;
  return typeof label === "string" ? label.trim() : "";
}

function pointColor(cluster: ClusterRecord | undefined): string {
  return severityOf(cluster?.hotspot_count ?? 0).color;
}

function pointPathOptions(point: ClusterPoint, cluster: ClusterRecord | undefined, selectedId: number | null) {
  const selected = point.cluster_id === selectedId;
  const color = pointColor(cluster);
  return {
    color: point.is_core || selected ? "#ffffff" : color,
    weight: point.is_core ? 1.5 : selected ? 1.25 : 0.8,
    fillColor: color,
    fillOpacity: selected ? 0.92 : 0.58,
  };
}

export function KompleksKebakaranView({ onOpenKpsDetail, layers = [] }: KompleksKebakaranViewProps) {
  const [timeRangeDays, setTimeRangeDays] = useState(30);
  const [sensitivity, setSensitivity] = useState<ClusterSensitivity>("sedang");
  const [mapStyle, setMapStyle] = useState<"dark" | "satellite">("dark");
  const [data, setData] = useState<ClusterCollectionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copying" | "copied" | "error">("idle");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelectedId(null);

    const endAt = new Date();
    const startAt = new Date(endAt.getTime() - timeRangeDays * 24 * 60 * 60 * 1000);

    api
      .getHotspotClusters({
        start_at: startAt.toISOString(),
        end_at: endAt.toISOString(),
        sensitivity
      })
      .then((response) => {
        if (!cancelled) {
          setData(response);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError("Gagal memuat data kompleks kebakaran. Coba lagi.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [timeRangeDays, sensitivity]);

  const clusters = data?.clusters ?? [];
  const clusterPoints = data?.points ?? [];
  const clusterById = useMemo(
    () => new Map(clusters.map((cluster) => [cluster.cluster_id, cluster])),
    [clusters]
  );
  const selectedCluster = useMemo(
    () => clusters.find((c) => c.cluster_id === selectedId) ?? null,
    [clusters, selectedId]
  );

  const besarCount = clusters.filter((c) => c.hotspot_count >= BESAR_THRESHOLD).length;
  const aktifCount = clusters.filter((c) => hoursSince(c.last_detected_at) < AKTIF_THRESHOLD_HOURS).length;
  const totalTergabung = data?.stats.clustered_hotspots ?? 0;
  const selectedAgencies = useMemo(
    () => new Set((selectedCluster?.affected_agencies ?? []).map((agency) => agency.name)),
    [selectedCluster]
  );
  const sensitivityParameters = SENSITIVITY_OPTIONS.find((option) => option.value === sensitivity) ?? SENSITIVITY_OPTIONS[1];
  const selectedCorePoints = useMemo(
    () => clusterPoints.filter((point) => point.cluster_id === selectedId && point.is_core),
    [clusterPoints, selectedId]
  );

  const handleCopyReport = async () => {
    if (!data || loading) return;
    setCopyState("copying");
    try {
      await copyToClipboard(buildWhatsAppReport(data, clusters, timeRangeDays, sensitivity));
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 2200);
    } catch {
      setCopyState("error");
      window.setTimeout(() => setCopyState("idle"), 3000);
    }
  };

  return (
    <section className="kompleks-shell" aria-label="Kompleks Kebakaran">
      <header className="kompleks-topbar">
        <div className="kompleks-topbar-row">
          <div className="kompleks-title">
            <h2>Kompleks Kebakaran</h2>
            <span
              className="info-dot"
              tabIndex={0}
              role="img"
              aria-label="Info"
              title="Titik-titik hotspot yang berdekatan waktu & lokasi digabung jadi satu kejadian, supaya jumlah yang dilihat mencerminkan kejadian nyata — bukan jumlah titik satelit."
            >
              i
            </span>
          </div>
          <div className="kompleks-controls">
            <label className="field field--inline">
              <span>Rentang</span>
              <select
                className="filter-select-input"
                value={timeRangeDays}
                onChange={(event) => setTimeRangeDays(Number(event.currentTarget.value))}
              >
                {TIME_RANGE_OPTIONS.map((opt) => (
                  <option key={opt.days} value={opt.days}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field field--inline">
              <span>
                Kepekaan
                <span
                  className="info-dot"
                  tabIndex={0}
                  role="img"
                  aria-label="Info kepekaan"
                  title={`${SENSITIVITY_OPTIONS.find((o) => o.value === sensitivity)?.hint}. Ambang penggabungan titik (jarak & jeda antar-deteksi) — bukan Rentang Waktu (jendela data).`}
                >
                  i
                </span>
              </span>
              <select
                className="filter-select-input"
                value={sensitivity}
                onChange={(event) => setSensitivity(event.currentTarget.value as ClusterSensitivity)}
              >
                {SENSITIVITY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="kompleks-copy-btn"
              onClick={handleCopyReport}
              disabled={!data || loading || copyState === "copying"}
              aria-live="polite"
            >
              {copyState === "copied" ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
              {copyState === "copied"
                ? "Tersalin"
                : copyState === "error"
                  ? "Gagal menyalin"
                  : copyState === "copying"
                    ? "Menyalin..."
                    : "Salin laporan WhatsApp"}
            </button>
          </div>
        </div>
        <div className="kompleks-summary">
          <span>
            <strong>{loading ? "–" : clusters.length}</strong> kompleks
          </span>
          <span className="crit">
            <strong>{loading ? "–" : besarCount}</strong> besar (&ge;{BESAR_THRESHOLD})
          </span>
          <span className="ok">
            <strong>{loading ? "–" : aktifCount}</strong> aktif &lt;24 jam
          </span>
          <span>
            <strong>{loading ? "–" : totalTergabung.toLocaleString("id-ID")}</strong> titik tergabung
          </span>
        </div>
      </header>

      {error ? (
        <p role="alert" className="kompleks-alert">
          {error}
        </p>
      ) : null}

      <div className="kompleks-body">
        <div className="kompleks-map">
          {loading ? (
            <div className="kompleks-map-loading">Memuat peta kompleks...</div>
          ) : (
            <>
              <div className="basemap-switcher kompleks-basemap-switcher" role="group" aria-label="Gaya peta kompleks">
                <button
                  type="button"
                  className={mapStyle === "dark" ? "basemap-switcher-btn--active" : ""}
                  onClick={() => setMapStyle("dark")}
                  aria-pressed={mapStyle === "dark"}
                >
                  Peta
                </button>
                <button
                  type="button"
                  className={mapStyle === "satellite" ? "basemap-switcher-btn--active" : ""}
                  onClick={() => setMapStyle("satellite")}
                  aria-pressed={mapStyle === "satellite"}
                >
                  Satelit
                </button>
              </div>
              <div className="kompleks-map-legend" aria-label="Keterangan lapisan peta">
                <span><i className="kompleks-map-legend__dot" /> Titik anggota kompleks</span>
                <span><i className="kompleks-map-legend__cluster" /> Ukuran simbol = jumlah titik</span>
                <span><i className="kompleks-map-legend__line" /> Polygon lembaga</span>
                <span>
                  <i className="kompleks-map-legend__radius" />{" "}
                  {selectedCluster
                    ? `Radius ε = ${sensitivityParameters.epsKm} km di setiap titik inti`
                    : "Pilih cluster untuk melihat radius ε"}
                </span>
              </div>
              <MapContainer
                center={[-2.5, 118]}
                zoom={5}
                preferCanvas
                {...SMOOTH_ZOOM_MAP_PROPS}
                zoomControl={false}
                style={{ height: "100%", width: "100%" }}
              >
                {mapStyle === "satellite" ? (
                  <>
                    <TileLayer
                      attribution="Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"
                      url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
                      maxZoom={19}
                    />
                    <TileLayer
                      url="https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}"
                      maxZoom={19}
                    />
                  </>
                ) : (
                  <>
                    <TileLayer
                      attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
                      url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
                      maxZoom={16}
                    />
                    <TileLayer
                      url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
                      maxZoom={16}
                    />
                  </>
                )}
                <ZoomControl position="bottomleft" />
                <ScaleControl position="bottomright" metric imperial={false} maxWidth={160} />
                <FlyToCluster cluster={selectedCluster} />
                <Pane name="kompleks-radius" style={{ zIndex: 415 }}>
                  {selectedCorePoints.map((point) => (
                    <Circle
                      key={`radius-${point.id}`}
                      center={[point.latitude, point.longitude]}
                      radius={sensitivityParameters.epsKm * 1000}
                      pathOptions={{
                        color: "#fbbf24",
                        weight: 1.5,
                        opacity: 0.72,
                        dashArray: "7 6",
                        fillColor: "#fbbf24",
                        fillOpacity: 0.018
                      }}
                    />
                  ))}
                </Pane>
                <Pane name="kompleks-boundaries" style={{ zIndex: 400 }}>
                  {layers.filter((layer) => layer.active).map((layer) => (
                    <GeoJSON
                      key={layer.id}
                      data={layer.geojson as never}
                      style={(feature) => {
                        const label = featureLabel(feature);
                        const highlighted = selectedAgencies.has(label);
                        return {
                          color: highlighted ? "#ff8c42" : layer.color,
                          weight: highlighted ? 2.4 : 1,
                          opacity: highlighted ? 1 : 0.55,
                          fillColor: highlighted ? "#ff8c42" : layer.color,
                          fillOpacity: highlighted ? 0.12 : 0.025,
                          dashArray: highlighted ? "6 4" : "3 5",
                        };
                      }}
                    />
                  ))}
                </Pane>
                <Pane name="kompleks-points" style={{ zIndex: 420 }}>
                  {clusterPoints.map((point) => (
                    <CircleMarker
                      key={`point-${point.id}`}
                      center={[point.latitude, point.longitude]}
                      radius={point.cluster_id === selectedId ? 4 : 2.6}
                      pathOptions={pointPathOptions(point, clusterById.get(point.cluster_id), selectedId)}
                    />
                  ))}
                  {clusters.map((cluster) => {
                    const severity = severityOf(cluster.hotspot_count);
                    const isSelected = cluster.cluster_id === selectedId;
                    return (
                      <CircleMarker
                        key={cluster.cluster_id}
                        center={[cluster.centroid_lat, cluster.centroid_lon]}
                        radius={Math.min(22, 6 + Math.sqrt(cluster.hotspot_count) * 0.9)}
                        pathOptions={{
                          color: isSelected ? "#ffffff" : severity.color,
                          weight: isSelected ? 2.5 : 1.4,
                          fillColor: severity.color,
                          fillOpacity: isSelected ? 0.85 : 0.55
                        }}
                        eventHandlers={{ click: () => setSelectedId(cluster.cluster_id) }}
                      >
                        <Popup>
                          {cluster.dominant_agency ? (
                            <>
                              <span className="kompleks-popup-agency-label">Lembaga dominan</span>
                              <br />
                              <strong>{cluster.dominant_agency}</strong>
                            </>
                          ) : (
                            <strong>Kompleks tanpa lembaga dominan</strong>
                          )}
                          <br />
                          {cluster.hotspot_count.toLocaleString("id-ID")} titik &middot;{" "}
                          {formatSpanDays(cluster.first_detected_at, cluster.last_detected_at)} hari
                          <br />
                          {formatActivity(cluster.last_detected_at).text}
                          <br />
                          <span className="kompleks-popup-agency-label">Parameter analisis</span>
                          <br />
                          Radius ε di setiap titik inti: <strong>{sensitivityParameters.epsKm} km</strong> ·{" "}
                          titik inti: <strong>{cluster.core_point_count ?? "-"}</strong> · jeda τ:{" "}
                          <strong>{sensitivityParameters.epsHours} jam</strong> · minimum{" "}
                          <strong>{sensitivityParameters.minSamples} titik</strong>
                          {cluster.affected_agencies && cluster.affected_agencies.length > 1 ? (
                            <>
                              <br />
                              <span className="kompleks-popup-agency-label">Lembaga terdampak dalam cluster</span>
                              <br />
                              {cluster.affected_agencies.map((agency) => `${agency.name} (${agency.hotspot_count})`).join(", ")}
                            </>
                          ) : null}
                          {cluster.dominant_agency && onOpenKpsDetail ? (
                            <button
                              type="button"
                              onClick={() => onOpenKpsDetail(cluster.dominant_agency as string)}
                              style={{
                                display: "block",
                                marginTop: "8px",
                                padding: 0,
                                border: "none",
                                background: "none",
                                color: "#ea580c",
                                fontWeight: 700,
                                fontSize: "12px",
                                textDecoration: "underline",
                                cursor: "pointer"
                              }}
                            >
                              Lihat Detail KPS &rarr;
                            </button>
                          ) : null}
                        </Popup>
                      </CircleMarker>
                    );
                  })}
                </Pane>
              </MapContainer>
            </>
          )}
        </div>

        <div className="kompleks-list">
          <div className="kompleks-list-head">
            <h3>Kompleks Terbesar</h3>
            <p className="muted-copy">Diurutkan dari jumlah titik terbanyak</p>
          </div>
          <div className="kompleks-list-scroll">
            {loading ? (
              <p className="muted-copy" style={{ padding: "0.75rem" }}>
                Memuat daftar kompleks...
              </p>
            ) : clusters.length === 0 ? (
              <p className="muted-copy" style={{ padding: "0.75rem" }}>
                Tidak ada kompleks terdeteksi pada rentang &amp; kepekaan ini.
              </p>
            ) : (
              clusters.map((cluster, index) => {
                const severity = severityOf(cluster.hotspot_count);
                const activity = formatActivity(cluster.last_detected_at);
                const isSelected = cluster.cluster_id === selectedId;
                return (
                  // div, bukan <button>, karena butuh tombol "Lihat Detail KPS"
                  // sungguhan di dalamnya -- <button> di dalam <button> tidak
                  // valid HTML. Aksesibilitas (fokus, Enter/Space) diisi manual,
                  // pola yang sama dipakai `.detect-row` di KpsDetailView.tsx.
                  <div
                    key={cluster.cluster_id}
                    className={`kompleks-row${isSelected ? " kompleks-row--active" : ""}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedId(cluster.cluster_id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        setSelectedId(cluster.cluster_id);
                      }
                    }}
                  >
                    <span className="kompleks-row-rank">{index + 1}</span>
                    <span className="kompleks-row-body">
                      <span className="kompleks-row-top">
                        {cluster.dominant_agency ? (
                          <>
                            <span className="kompleks-row-agency-label">Lembaga dominan:</span>
                            <span className="kompleks-row-name">{cluster.dominant_agency}</span>
                          </>
                        ) : (
                          <span className="kompleks-row-name">Tanpa lembaga dominan</span>
                        )}
                        <span className={`kompleks-chip kompleks-chip--${severity.key}`}>
                          {severity.label}
                        </span>
                        {activity.live ? (
                          <span className="kompleks-chip kompleks-chip--live">Aktif</span>
                        ) : null}
                      </span>
                      <span className="kompleks-row-meta">
                        <b>{cluster.hotspot_count.toLocaleString("id-ID")}</b> titik &middot;{" "}
                        <b>{formatSpanDays(cluster.first_detected_at, cluster.last_detected_at)}</b>{" "}
                        hari &middot; {activity.text}
                      </span>
                      {cluster.dominant_agency && onOpenKpsDetail ? (
                        <button
                          type="button"
                          className="kompleks-row-detail-btn"
                          onClick={(event) => {
                            event.stopPropagation();
                            onOpenKpsDetail(cluster.dominant_agency as string);
                          }}
                        >
                          Lihat Detail KPS &rarr;
                        </button>
                      ) : null}
                    </span>
                  </div>
                );
              })
            )}
          </div>
          <p className="kompleks-explain">
            <b>Cara baca</b>
            <br />
            <b>Rentang Waktu</b> = jendela data. <b>24 Jam</b> = titik panas hari ini (pantauan
            harian); <b>7 Hari</b> = minggu ini; <b>30 Hari</b> = rekap bulanan. Makin lebar
            jendelanya, kompleks makin sedikit tapi makin besar dan rentang harinya memanjang &mdash;
            itu area yang sama berulang menyala, bukan satu api menyala terus.
            <br />
            <b>Kompleks</b> = kumpulan titik hotspot yang berdekatan lokasi &amp; waktu (sesuai
            Kepekaan Pengelompokan). Contoh baris <i>&ldquo;344 titik &middot; 18.5 hari &middot;
            Aktif &middot; 7.7 jam lalu&rdquo;</i> = 344 deteksi; jarak deteksi pertama ke terakhir
            18.5 hari; terakhir terdeteksi 7.7 jam lalu.
            <br />
            Chip <b style={{ color: "#6ee7b7" }}>Aktif</b> = deteksi terakhirnya &lt;24 jam lalu
            (tidak ikut berubah oleh Rentang Waktu). Chip <b>Besar/Sedang/Kecil</b> hanya sebanding
            dalam jendela yang sama.
          </p>
        </div>
      </div>
    </section>
  );
}
