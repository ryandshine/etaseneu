import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { createApiClient } from "../lib/api";
import { SMOOTH_ZOOM_MAP_PROPS } from "../constants/map";
import type { ClusterCollectionResponse, ClusterRecord, ClusterSensitivity } from "../types/api";

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
}[] = [
  { value: "ketat", label: "Ketat", hint: "radius 1 km, jeda antar-deteksi 12 jam" },
  { value: "sedang", label: "Sedang (disarankan)", hint: "radius 2 km, jeda antar-deteksi 48 jam" },
  { value: "longgar", label: "Longgar", hint: "radius 5 km, jeda antar-deteksi 72 jam" }
];

const BESAR_THRESHOLD = 400;
const SEDANG_THRESHOLD = 150;
const AKTIF_THRESHOLD_HOURS = 24;

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
};

export function KompleksKebakaranView({ onOpenKpsDetail }: KompleksKebakaranViewProps) {
  const [timeRangeDays, setTimeRangeDays] = useState(30);
  const [sensitivity, setSensitivity] = useState<ClusterSensitivity>("sedang");
  const [data, setData] = useState<ClusterCollectionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

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
  const selectedCluster = useMemo(
    () => clusters.find((c) => c.cluster_id === selectedId) ?? null,
    [clusters, selectedId]
  );

  const besarCount = clusters.filter((c) => c.hotspot_count >= BESAR_THRESHOLD).length;
  const aktifCount = clusters.filter((c) => hoursSince(c.last_detected_at) < AKTIF_THRESHOLD_HOURS).length;
  const totalTergabung = data?.stats.clustered_hotspots ?? 0;

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
            <MapContainer
              center={[-2.5, 118]}
              zoom={5}
              preferCanvas
              {...SMOOTH_ZOOM_MAP_PROPS}
              zoomControl={false}
              style={{ height: "100%", width: "100%" }}
            >
              <TileLayer
                attribution="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
                url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
                maxZoom={16}
              />
              <TileLayer
                url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
                maxZoom={16}
              />
              <FlyToCluster cluster={selectedCluster} />
              {clusters.map((cluster) => {
                const severity = severityOf(cluster.hotspot_count);
                const isSelected = cluster.cluster_id === selectedId;
                return (
                  <CircleMarker
                    key={cluster.cluster_id}
                    center={[cluster.centroid_lat, cluster.centroid_lon]}
                    radius={6 + Math.sqrt(cluster.hotspot_count) * 1.4}
                    pathOptions={{
                      color: isSelected ? "#ffffff" : severity.color,
                      weight: isSelected ? 2.5 : 1.4,
                      fillColor: severity.color,
                      fillOpacity: isSelected ? 0.85 : 0.55
                    }}
                    eventHandlers={{ click: () => setSelectedId(cluster.cluster_id) }}
                  >
                    <Popup>
                      <strong>{cluster.dominant_agency ?? "Kompleks tanpa nama lembaga"}</strong>
                      <br />
                      {cluster.hotspot_count.toLocaleString("id-ID")} titik &middot;{" "}
                      {formatSpanDays(cluster.first_detected_at, cluster.last_detected_at)} hari
                      <br />
                      {formatActivity(cluster.last_detected_at).text}
                      {cluster.dominant_agency && onOpenKpsDetail ? (
                        // Popup Leaflet pakai skin bawaan terang, bukan tema gelap
                        // aplikasi -- gaya inline di sini (bukan class global)
                        // supaya kontras tetap benar di atas latar terang itu,
                        // pola yang sama dipakai popup lain di HotspotMap.tsx.
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
            </MapContainer>
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
                        <span className="kompleks-row-name">
                          {cluster.dominant_agency ?? "Tanpa lembaga"}
                        </span>
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
            <b>Cara baca:</b> "Kompleks" = kumpulan titik hotspot yang saling berdekatan dan
            terdeteksi dalam rentang waktu berdekatan (sesuai Kepekaan Pengelompokan). Chip hijau{" "}
            <b style={{ color: "#6ee7b7" }}>Aktif</b> berarti titik terakhirnya terdeteksi &lt;24 jam
            lalu.
          </p>
        </div>
      </div>
    </section>
  );
}
