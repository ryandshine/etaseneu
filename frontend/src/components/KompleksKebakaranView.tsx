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
  Tooltip,
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
  locationEpsKm: number;
}[] = [
  { value: "ketat", label: "Ketat", hint: "kompleks 1 km/12 jam, lokasi 0,5 km", epsKm: 1, epsHours: 12, minSamples: 4, locationEpsKm: 0.5 },
  { value: "sedang", label: "Sedang (disarankan)", hint: "kompleks 2 km/48 jam, lokasi 1 km", epsKm: 2, epsHours: 48, minSamples: 4, locationEpsKm: 1 },
  { value: "longgar", label: "Longgar", hint: "kompleks 5 km/72 jam, lokasi 2,5 km", epsKm: 5, epsHours: 72, minSamples: 3, locationEpsKm: 2.5 }
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

type RankedClusterLabel = { name: string; hotspot_count: number };

function formatClusterLabels(
  labels: RankedClusterLabel[] | undefined,
  fallback: string
): string {
  const names = (labels ?? []).map((label) => label.name).filter(Boolean);
  if (names.length === 0) return fallback;
  const visibleNames = names.slice(0, 2).join(", ");
  return names.length > 2 ? `${visibleNames} +${names.length - 2} lainnya` : visibleNames;
}

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
  const props = properties as Record<string, unknown>;
  const label =
    props.LEMBAGA ||
    props.label ||
    props.NAMA_KPS ||
    props.NAMA_LEMBAGA ||
    props.NAMALEMBAG ||
    props.nama_lembaga ||
    props.name ||
    props.NAME ||
    props.Name;
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
  const [showCoreRadii, setShowCoreRadii] = useState(false);
  const [showIndividualPoints, setShowIndividualPoints] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copying" | "copied" | "error">("idle");
  const [copiedCoord, setCopiedCoord] = useState<string | null>(null);

  const handleCopyCoord = async (lat: number, lon: number) => {
    const text = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedCoord(text);
      window.setTimeout(() => setCopiedCoord(null), 1500);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelectedId(null);
    setShowCoreRadii(false);

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
  const aktifCount = useMemo(() => {
    const activeAgencies = new Set<string>();
    let unnamedActive = 0;
    clusters.forEach((c) => {
      if (hoursSince(c.last_detected_at) < AKTIF_THRESHOLD_HOURS) {
        if (c.dominant_agency) {
          activeAgencies.add(c.dominant_agency);
        } else {
          unnamedActive += 1;
        }
      }
    });
    return activeAgencies.size + unnamedActive;
  }, [clusters]);
  const totalTergabung = data?.stats.clustered_hotspots ?? 0;
  const selectedAgencies = useMemo(
    () => new Set((selectedCluster?.affected_agencies ?? []).map((agency) => agency.name)),
    [selectedCluster]
  );
  const agencyClusterInfo = useMemo(() => {
    const counts = new Map<string, number>();
    const indices = new Map<number, { index: number; total: number }>();

    const agencyClusterList = new Map<string, number[]>();
    clusters.forEach((c) => {
      if (c.dominant_agency) {
        if (!agencyClusterList.has(c.dominant_agency)) {
          agencyClusterList.set(c.dominant_agency, []);
        }
        agencyClusterList.get(c.dominant_agency)!.push(c.cluster_id);
      }
    });

    agencyClusterList.forEach((clusterIds, agency) => {
      counts.set(agency, clusterIds.length);
      clusterIds.forEach((id, idx) => {
        indices.set(id, { index: idx + 1, total: clusterIds.length });
      });
    });

    return { counts, indices };
  }, [clusters]);
  const sensitivityParameters = SENSITIVITY_OPTIONS.find((option) => option.value === sensitivity) ?? SENSITIVITY_OPTIONS[1];
  const selectedCorePoints = useMemo(
    () => clusterPoints.filter((point) => point.cluster_id === selectedId && point.is_core),
    [clusterPoints, selectedId]
  );
  const selectedLocations = selectedCluster?.locations ?? [];

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
            <strong>{loading ? "–" : aktifCount}</strong> lembaga aktif &lt;24 jam
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
              <div className="kompleks-map-legend" aria-label="Legenda peta kompleks">
                <span className="kompleks-map-legend__title">Legenda Peta</span>
                <div className="kompleks-map-legend__grid">
                  <span className="kompleks-map-legend__item"><i className="kompleks-map-legend__dot" /> Titik anggota kompleks</span>
                  <span className="kompleks-map-legend__item"><i className="kompleks-map-legend__cluster" /> Ukuran = Banyak titik</span>
                  <span className="kompleks-map-legend__item"><i className="kompleks-map-legend__location" /> Lokasi terindikasi</span>
                  <span className="kompleks-map-legend__item" title="Gabungan radius ε semua titik inti"><i className="kompleks-map-legend__footprint" /> Selubung kompleks</span>
                  <span className="kompleks-map-legend__item"><i className="kompleks-map-legend__line" /> Polygon lembaga</span>
                  <span className="kompleks-map-legend__item" title="Mode audit radius ε per titik inti"><i className="kompleks-map-legend__radius" /> Ring radius ε</span>
                </div>
              </div>
              <div className="kompleks-map-audit" aria-live="polite">
                <button
                  type="button"
                  className="kompleks-map-audit__button"
                  aria-pressed={showIndividualPoints}
                  onClick={() => setShowIndividualPoints((visible) => !visible)}
                  title="Sembunyikan atau tampilkan seluruh titik satelit individu"
                >
                  {showIndividualPoints ? "Mode Sentroid Bersih" : "Tampilkan Semua Titik"}
                </button>
                <button
                  type="button"
                  className="kompleks-map-audit__button"
                  disabled={!selectedCluster || selectedCorePoints.length === 0}
                  aria-pressed={showCoreRadii}
                  onClick={() => setShowCoreRadii((visible) => !visible)}
                >
                  {showCoreRadii ? "Sembunyikan ring ε" : "Tampilkan semua ring ε"}
                </button>
                <span>
                  {selectedCluster
                    ? `${selectedCorePoints.length.toLocaleString("id-ID")} titik inti · ε ${sensitivityParameters.epsKm} km`
                    : "Pilih kompleks untuk melihat selubung & koordinat pusat"}
                </span>
              </div>
              <MapContainer
                center={[-2.5, 118]}
                zoom={5}
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
                <Pane name="kompleks-footprint" style={{ zIndex: 405, pointerEvents: "none" }}>
                  {selectedCluster?.footprint ? (
                    <GeoJSON
                      key={`footprint-${selectedCluster.cluster_id}`}
                      data={{
                        type: "Feature",
                        properties: {},
                        geometry: selectedCluster.footprint
                      } as never}
                      interactive={false}
                      style={{
                        color: "#fbbf24",
                        weight: 2.2,
                        opacity: 0.95,
                        fillColor: "#fbbf24",
                        fillOpacity: 0.14,
                        dashArray: "8 5"
                      }}
                    />
                  ) : null}
                </Pane>
                <Pane name="kompleks-radius" style={{ zIndex: 415, pointerEvents: "none" }}>
                  {showCoreRadii
                    ? selectedCorePoints.map((point) => (
                        <Circle
                          key={`radius-${selectedId}-${point.id}`}
                          center={[point.latitude, point.longitude]}
                          radius={sensitivityParameters.epsKm * 1000}
                          interactive={false}
                          pathOptions={{
                            color: "#fde68a",
                            weight: 1,
                            opacity: 0.65,
                            dashArray: "5 5",
                            fillColor: "#fbbf24",
                            fillOpacity: 0.025,
                            interactive: false
                          }}
                        />
                      ))
                    : null}
                </Pane>
                <Pane name="kompleks-boundaries" style={{ zIndex: 420 }}>
                  {layers.filter((layer) => layer.active).map((layer) => (
                    <GeoJSON
                      key={`boundaries-${layer.id}-${selectedCluster?.cluster_id ?? "none"}`}
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
                      onEachFeature={(feature, leafletLayer) => {
                        const props = ((feature as { properties?: unknown }).properties || {}) as Record<string, unknown>;
                        const label = featureLabel(feature) || (typeof props.OBJECTID_1 === "number" ? `Polygon #${props.OBJECTID_1}` : "Polygon KPS");
                        if (!label) return;

                        const skema = String(props.SKEMA || props.skema || "").trim();
                        const prov = String(props.NAMA_PROV || props.provinsi || "").trim();
                        const kab = String(props.NAMA_KAB || props.kabupaten || "").trim();
                        const wilker = String(props.WILKER_BPS || "").trim();

                        leafletLayer.bindTooltip(label, { sticky: true, className: "kompleks-polygon-tooltip" });

                        const matchingCluster = clusters.find((c) => c.dominant_agency === label);

                        const container = document.createElement("div");
                        container.style.fontSize = "12px";
                        container.style.fontFamily = "sans-serif";
                        container.style.minWidth = "200px";
                        container.style.lineHeight = "1.4";

                        const header = document.createElement("div");
                        header.style.color = "#ea580c";
                        header.style.fontWeight = "700";
                        header.style.fontSize = "11px";
                        header.style.textTransform = "uppercase";
                        header.style.letterSpacing = "0.05em";
                        header.textContent = "Polygon Lembaga";
                        container.appendChild(header);

                        const title = document.createElement("div");
                        title.style.marginTop = "3px";
                        title.style.fontWeight = "700";
                        title.style.fontSize = "13px";
                        title.style.color = "#111827";
                        title.textContent = label;
                        container.appendChild(title);

                        const parts = [skema, wilker, kab, prov].filter(Boolean);
                        if (parts.length > 0) {
                          const meta = document.createElement("div");
                          meta.style.marginTop = "3px";
                          meta.style.fontSize = "11px";
                          meta.style.color = "#6b7280";
                          meta.textContent = parts.join(" · ");
                          container.appendChild(meta);
                        }

                        const statusBox = document.createElement("div");
                        statusBox.style.marginTop = "8px";
                        statusBox.style.padding = "6px 8px";
                        statusBox.style.borderRadius = "4px";
                        statusBox.style.fontSize = "11px";

                        if (matchingCluster) {
                          statusBox.style.background = "rgba(239, 68, 68, 0.1)";
                          statusBox.style.border = "1px solid rgba(239, 68, 68, 0.25)";
                          statusBox.style.color = "#b91c1c";
                          statusBox.innerHTML = `🔥 Terdeteksi <strong>${matchingCluster.hotspot_count.toLocaleString("id-ID")} titik api</strong> aktif pada area ini.`;
                        } else {
                          statusBox.style.background = "rgba(16, 185, 129, 0.1)";
                          statusBox.style.border = "1px solid rgba(16, 185, 129, 0.25)";
                          statusBox.style.color = "#047857";
                          statusBox.textContent = "✅ Tidak ada titik api aktif dalam rentang waktu ini.";
                        }
                        container.appendChild(statusBox);

                        const btnGroup = document.createElement("div");
                        btnGroup.style.display = "flex";
                        btnGroup.style.gap = "8px";
                        btnGroup.style.marginTop = "8px";
                        btnGroup.style.alignItems = "center";

                        if (matchingCluster) {
                          const selectBtn = document.createElement("button");
                          selectBtn.type = "button";
                          selectBtn.textContent = "Fokus Kompleks";
                          selectBtn.style.padding = "4px 8px";
                          selectBtn.style.border = "1px solid #ea580c";
                          selectBtn.style.borderRadius = "4px";
                          selectBtn.style.background = "#ea580c";
                          selectBtn.style.color = "#ffffff";
                          selectBtn.style.fontWeight = "600";
                          selectBtn.style.fontSize = "11px";
                          selectBtn.style.cursor = "pointer";
                          selectBtn.onclick = (e) => {
                            e.stopPropagation();
                            setSelectedId(matchingCluster.cluster_id);
                          };
                          btnGroup.appendChild(selectBtn);
                        }

                        if (onOpenKpsDetail) {
                          const detailBtn = document.createElement("button");
                          detailBtn.type = "button";
                          detailBtn.textContent = "Lihat Detail KPS →";
                          detailBtn.style.padding = "4px 0";
                          detailBtn.style.border = "none";
                          detailBtn.style.background = "none";
                          detailBtn.style.color = "#ea580c";
                          detailBtn.style.fontWeight = "700";
                          detailBtn.style.fontSize = "11px";
                          detailBtn.style.cursor = "pointer";
                          detailBtn.onclick = (e) => {
                            e.stopPropagation();
                            onOpenKpsDetail(label);
                          };
                          btnGroup.appendChild(detailBtn);
                        }

                        container.appendChild(btnGroup);
                        leafletLayer.bindPopup(container);
                      }}
                    />
                  ))}
                </Pane>
                <Pane name="kompleks-locations" style={{ zIndex: 430 }}>
                  {selectedLocations.map((location) => (
                    <CircleMarker
                      key={`location-${location.location_id}`}
                      center={[location.centroid_lat, location.centroid_lon]}
                      radius={9}
                      pathOptions={{
                        color: "#fff7cc",
                        weight: 2,
                        fillColor: "#f97316",
                        fillOpacity: 0.92
                      }}
                    >
                      <Tooltip permanent direction="center" className="kompleks-location-label">
                        {location.location_id}
                      </Tooltip>
                      <Popup>
                        <strong>Lokasi terindikasi {location.location_id}</strong>
                        <br />
                        {location.hotspot_count.toLocaleString("id-ID")} deteksi
                        <br />
                        Dalam polygon: {location.polygon_hotspot_count.toLocaleString("id-ID")}
                        <br />
                        Di luar polygon: {location.outside_polygon_hotspot_count.toLocaleString("id-ID")}
                        <br />
                        {formatActivity(location.last_detected_at).text}
                      </Popup>
                    </CircleMarker>
                  ))}
                </Pane>
                <Pane name="kompleks-points" style={{ zIndex: 440 }}>
                  {(showIndividualPoints
                    ? clusterPoints
                    : selectedCluster
                    ? clusterPoints.filter((p) => p.cluster_id === selectedId)
                    : []
                  ).map((point) => (
                    <CircleMarker
                      key={`point-${point.id}`}
                      center={[point.latitude, point.longitude]}
                      radius={point.cluster_id === selectedId ? 4 : 2.6}
                      pathOptions={pointPathOptions(point, clusterById.get(point.cluster_id), selectedId)}
                    />
                  ))}
                  {selectedCluster &&
                  selectedCluster.epicenter_lat !== undefined &&
                  selectedCluster.epicenter_lon !== undefined ? (
                    <CircleMarker
                      key={`epicenter-marker-${selectedCluster.cluster_id}`}
                      center={[selectedCluster.epicenter_lat, selectedCluster.epicenter_lon]}
                      radius={8}
                      pathOptions={{
                        color: "#ffffff",
                        weight: 2.5,
                        fillColor: "#dc2626",
                        fillOpacity: 1
                      }}
                    >
                      <Tooltip permanent direction="top" className="kompleks-location-label">
                        🔥 Episentrum ({selectedCluster.max_frp ? `${selectedCluster.max_frp.toFixed(0)} MW` : "Peak"})
                      </Tooltip>
                    </CircleMarker>
                  ) : null}
                  {clusters.map((cluster) => {
                    const severity = severityOf(cluster.hotspot_count);
                    const isSelected = cluster.cluster_id === selectedId;
                    const coordString = `${cluster.centroid_lat.toFixed(5)}, ${cluster.centroid_lon.toFixed(5)}`;
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

                          <div
                            style={{
                              margin: "6px 0",
                              padding: "6px 8px",
                              background: "rgba(255, 255, 255, 0.08)",
                              borderRadius: "4px"
                            }}
                          >
                            <span className="kompleks-popup-agency-label">Koordinat Pusat (FRP-Weighted)</span>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                                marginTop: "3px",
                                gap: "6px"
                              }}
                            >
                              <strong style={{ fontSize: "11px", color: "#facc15" }}>{coordString}</strong>
                              <div style={{ display: "flex", gap: "4px" }}>
                                <button
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void handleCopyCoord(cluster.centroid_lat, cluster.centroid_lon);
                                  }}
                                  style={{
                                    fontSize: "10px",
                                    padding: "2px 6px",
                                    borderRadius: "3px",
                                    border: "1px solid rgba(255,255,255,0.2)",
                                    background: "rgba(255,255,255,0.12)",
                                    color: "#ffffff",
                                    cursor: "pointer"
                                  }}
                                >
                                  {copiedCoord === coordString ? "Disalin!" : "Salin"}
                                </button>
                                <a
                                  href={`https://www.google.com/maps?q=${cluster.centroid_lat},${cluster.centroid_lon}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{
                                    fontSize: "10px",
                                    padding: "2px 6px",
                                    borderRadius: "3px",
                                    border: "1px solid rgba(56,189,248,0.4)",
                                    background: "rgba(56,189,248,0.15)",
                                    color: "#38bdf8",
                                    textDecoration: "none"
                                  }}
                                >
                                  Maps ↗
                                </a>
                              </div>
                            </div>
                          </div>

                          {cluster.epicenter_lat !== undefined && cluster.epicenter_lon !== undefined ? (
                            <div
                              style={{
                                margin: "4px 0 6px 0",
                                padding: "6px 8px",
                                background: "rgba(239, 68, 68, 0.14)",
                                border: "1px solid rgba(239, 68, 68, 0.3)",
                                borderRadius: "4px"
                              }}
                            >
                              <span className="kompleks-popup-agency-label" style={{ color: "#f87171" }}>
                                🔥 Episentrum Api Terparah (Peak)
                              </span>
                              <div
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "space-between",
                                  marginTop: "3px",
                                  gap: "6px"
                                }}
                              >
                                <strong style={{ fontSize: "11px", color: "#fca5a5" }}>
                                  {cluster.epicenter_lat.toFixed(5)}, {cluster.epicenter_lon.toFixed(5)}
                                  {cluster.max_frp ? ` (${cluster.max_frp.toFixed(1)} MW)` : ""}
                                </strong>
                                <div style={{ display: "flex", gap: "4px" }}>
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void handleCopyCoord(cluster.epicenter_lat!, cluster.epicenter_lon!);
                                    }}
                                    style={{
                                      fontSize: "10px",
                                      padding: "2px 6px",
                                      borderRadius: "3px",
                                      border: "1px solid rgba(255,255,255,0.2)",
                                      background: "rgba(255,255,255,0.12)",
                                      color: "#ffffff",
                                      cursor: "pointer"
                                    }}
                                  >
                                    {copiedCoord === `${cluster.epicenter_lat.toFixed(5)}, ${cluster.epicenter_lon.toFixed(5)}`
                                      ? "Disalin!"
                                      : "Salin"}
                                  </button>
                                  <a
                                    href={`https://www.google.com/maps?q=${cluster.epicenter_lat},${cluster.epicenter_lon}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    style={{
                                      fontSize: "10px",
                                      padding: "2px 6px",
                                      borderRadius: "3px",
                                      border: "1px solid rgba(248,113,113,0.4)",
                                      background: "rgba(248,113,113,0.15)",
                                      color: "#fca5a5",
                                      textDecoration: "none"
                                    }}
                                  >
                                    Maps ↗
                                  </a>
                                </div>
                              </div>
                            </div>
                          ) : null}

                          Lokasi terindikasi: <strong>{cluster.location_count ?? "-"}</strong> · yang menyentuh polygon:{" "}
                          <strong>{cluster.locations_in_polygon ?? "-"}</strong>
                          <br />
                          Deteksi dalam polygon: <strong>{cluster.polygon_hotspot_count ?? "-"}</strong> · di luar:{" "}
                          <strong>{cluster.outside_polygon_hotspot_count ?? "-"}</strong>
                          <br />
                          <span className="kompleks-popup-agency-label">Cakupan administratif</span>
                          <br />
                          Balai/Wilker: {formatClusterLabels(cluster.affected_wilkers, "Belum teridentifikasi")}
                          <br />
                          Provinsi: {formatClusterLabels(cluster.affected_provinces, "Belum teridentifikasi")}
                          <br />
                          <span className="kompleks-popup-agency-label">Parameter analisis</span>
                          <br />
                          Selubung = union radius ε dari <strong>{cluster.core_point_count ?? "-"}</strong> titik inti · ε:{" "}
                          <strong>{sensitivityParameters.epsKm} km</strong> · jeda τ:{" "}
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
                const multiInfo = cluster.dominant_agency ? agencyClusterInfo.indices.get(cluster.cluster_id) : undefined;
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
                        {multiInfo && multiInfo.total > 1 ? (
                          <span className="kompleks-chip kompleks-chip--cluster">
                            Kluster {multiInfo.index}/{multiInfo.total}
                          </span>
                        ) : null}
                        <span className={`kompleks-chip kompleks-chip--${severity.key}`}>
                          {severity.label}
                        </span>
                        {activity.live ? (
                          <span className="kompleks-chip kompleks-chip--live">Aktif</span>
                        ) : null}
                      </span>
                      <span className="kompleks-row-context">
                        <span><b>Pusat Klaster (FRP):</b> {cluster.centroid_lat.toFixed(4)}, {cluster.centroid_lon.toFixed(4)}</span>
                        {cluster.epicenter_lat !== undefined && cluster.epicenter_lon !== undefined ? (
                          <span style={{ color: "#fca5a5" }}>
                            <b>Episentrum Terparah:</b> {cluster.epicenter_lat.toFixed(4)}, {cluster.epicenter_lon.toFixed(4)}
                            {cluster.max_frp ? ` (${cluster.max_frp.toFixed(1)} MW)` : ""}
                          </span>
                        ) : null}
                        <span><b>Balai/Wilker:</b> {cluster.dominant_wilker ?? "Belum teridentifikasi"}</span>
                        <span><b>Provinsi:</b> {cluster.dominant_province ?? "Belum teridentifikasi"}</span>
                        <span><b>Lokasi terindikasi:</b> {cluster.location_count ?? "-"} · <b>Dalam polygon:</b> {cluster.polygon_hotspot_count ?? "-"} titik</span>
                        {multiInfo && multiInfo.total > 1 ? (
                          <span style={{ color: "#93c5fd" }}>
                            <b>Info:</b> Kluster {multiInfo.index} dari {multiInfo.total} area terpisah di lembaga ini
                          </span>
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
        </div>
      </div>
    </section>
  );
}
