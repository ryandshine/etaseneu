import { useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { CircleMarker, GeoJSON, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { geoJSON as buildLeafletGeoJSON } from "leaflet";

import type { DashboardHotspot } from "../hooks/useDashboardData";
import type { PolygonDetail } from "../types/api";

type KpsDetailViewProps = {
  polygonId: number;
  hotspots: DashboardHotspot[];
  onClose: () => void;
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
        map.fitBounds(bounds, { padding: [32, 32] });
      }
    } catch {
      // Geometry tidak valid -- peta tetap di posisi default, tidak fatal.
    }
  }, [geometry, map]);

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

export function KpsDetailView({ polygonId, hotspots, onClose }: KpsDetailViewProps) {
  const [detail, setDetail] = useState<PolygonDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
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

  // Titik hotspot milik KPS ini sudah tersedia dari dataset yang sama dipakai
  // Buku Besar -- tidak perlu endpoint tambahan, tinggal disaring pakai ID
  // polygon yang sama.
  const kpsHotspots = useMemo(
    () => hotspots.filter((hotspot) => hotspot.polygonMetadata.polygon_metadata_id === String(polygonId)),
    [hotspots, polygonId]
  );

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

  return (
    <div className="kps-detail">
      <header className="kps-detail-header">
        <button type="button" className="kps-detail-back" onClick={onClose}>
          <ArrowLeft size={16} />
          Kembali ke Matriks Data
        </button>
        <h2 className="kps-detail-title">
          {detail?.lembaga || (loading ? "Memuat..." : "Detail KPS")}
        </h2>
      </header>

      {error ? <p className="toast-error toast-error--inline">{error}</p> : null}

      <div className="kps-detail-body">
        <aside className="kps-detail-info panel">
          {loading ? (
            <p className="help-copy">Memuat informasi KPS...</p>
          ) : detail ? (
            <>
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
              </div>
            </>
          ) : null}
        </aside>

        <div className="kps-detail-map">
          <MapContainer center={[-2.5, 118]} zoom={5} preferCanvas style={{ height: "100%", width: "100%" }}>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />
            {detail ? (
              <>
                <FitToPolygon geometry={detail.geometry} />
                <GeoJSON
                  data={{ type: "Feature", properties: {}, geometry: detail.geometry } as never}
                  style={{ color: "#ff8c42", weight: 3, fillColor: "#ff8c42", fillOpacity: 0.14 }}
                />
              </>
            ) : null}
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
          </MapContainer>
        </div>
      </div>
    </div>
  );
}
