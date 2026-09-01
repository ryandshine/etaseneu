import { useEffect, useState } from "react";
import { authFetch } from "../lib/api";
import { Check, ChevronDown, CloudSun, Copy, ExternalLink, FileText } from "lucide-react";

// Popup detail titik hotspot -- dipakai bareng oleh HotspotMap (peta utama)
// dan KpsDetailView (peta di halaman Detail KPS) supaya isi & gaya popup-nya
// identik di kedua tempat, bukan implementasi terpisah yang bisa mencar.

export const HIGH_FRP_THRESHOLD = 30;

export type PopupHotspot = {
  latitude: number;
  longitude: number;
  source: string;
  satellite: string;
  agencyName: string;
  provinceName: string;
  brightness: number | null;
  frp?: number | null;
  detectedAt: string;
  fungsiKawasan?: string;
  namaKawasan?: string;
  kelompokKawasan?: string;
};

type SpotWeather = {
  current: {
    temperature: number;
    humidity: number;
    precipitation: number;
    wind_speed: number;
    wind_direction: number;
    wind_gusts: number;
    soil_moisture: number;
    soil_moisture_status: string;
    soil_moisture_color: string;
    weather_code: number;
    fire_danger: {
      value: number;
      level: string;
      color: string;
    };
  };
  air_quality: {
    pm2_5: number;
    pm10: number;
    carbon_monoxide: number;
    aqi: number;
  };
};

function formatTimestamp(value: string): string {
  if (!value) {
    return "Timestamp tidak tersedia";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Timestamp tidak tersedia";
  }

  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Jakarta",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
    const parts = formatter.formatToParts(parsed);
    const year = parts.find((p) => p.type === "year")?.value ?? "";
    const month = parts.find((p) => p.type === "month")?.value ?? "";
    const day = parts.find((p) => p.type === "day")?.value ?? "";
    const hour = parts.find((p) => p.type === "hour")?.value ?? "";
    const minute = parts.find((p) => p.type === "minute")?.value ?? "";
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  } catch {
    const wibTime = new Date(parsed.getTime() + 7 * 60 * 60 * 1000);
    const day = String(wibTime.getUTCDate()).padStart(2, "0");
    const month = String(wibTime.getUTCMonth() + 1).padStart(2, "0");
    const year = wibTime.getUTCFullYear();
    const hour = String(wibTime.getUTCHours()).padStart(2, "0");
    const minute = String(wibTime.getUTCMinutes()).padStart(2, "0");
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  }
}

export function formatNumber(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "Tidak tersedia";
  }

  return value.toFixed(2);
}

function formatMetadataValue(value?: string): string {
  return value && value.trim() ? value : "Tidak tersedia";
}

// Dipakai di popup hotspot maupun popup lokasi user -- salin koordinat ke
// clipboard, atau buka titik yang sama di Google Maps (tautan biasa ke situs
// mereka, bukan hotlink tile, jadi tidak melanggar ToS Google Maps).
export function CoordinateActions({ lat, lon }: { lat: number; lon: number }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const text = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Beberapa browser/webview lama tidak dukung Clipboard API dan tidak
      // ada fallback yang bermakna selain minta user salin manual.
    }
  };

  return (
    <div className="coord-actions">
      <button type="button" className="coord-action-btn" onClick={() => void handleCopy()}>
        {copied ? <Check size={12} /> : <Copy size={12} />}
        {copied ? "Disalin!" : "Salin koordinat"}
      </button>
      <a
        href={`https://www.google.com/maps?q=${lat},${lon}`}
        target="_blank"
        rel="noopener noreferrer"
        className="coord-action-btn"
      >
        <ExternalLink size={12} />
        Google Maps
      </a>
    </div>
  );
}

export function HotspotWeatherPopup({ lat, lon }: { lat: number; lon: number }) {
  const [data, setData] = useState<SpotWeather | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);

    authFetch(`/api/weather/spot?lat=${lat}&lon=${lon}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed");
        return res.json() as Promise<SpotWeather>;
      })
      .then((payload) => {
        if (active) {
          setData(payload);
        }
      })
      .catch(() => {
        if (active) setError(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [lat, lon]);

  if (loading) {
    return (
      <div className="weather-popup-loader" style={{ fontSize: "11px", color: "#94a3b8", padding: "4px 0" }}>
        <span>⚡ Memuat data cuaca &amp; kualitas udara...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="weather-popup-error" style={{ fontSize: "11px", color: "#ef4444", padding: "4px 0" }}>
        ⚠️ Gagal memuat info cuaca Open-Meteo.
      </div>
    );
  }

  return (
    <div className="weather-popup-content" style={{ borderTop: "1px solid rgba(255,255,255,0.1)", marginTop: "8px", paddingTop: "8px" }}>
      <div style={{ fontSize: "12px", fontWeight: "bold", color: "#facc15", marginBottom: "6px" }}>Cuaca &amp; Kualitas Udara Lokal</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 8px", fontSize: "11px" }}>
        <div>
          <span style={{ color: "#94a3b8" }}>Suhu: </span>
          <strong>{data.current.temperature.toFixed(1)} °C</strong>
        </div>
        <div>
          <span style={{ color: "#94a3b8" }}>RH: </span>
          <strong>{data.current.humidity.toFixed(0)}%</strong>
        </div>
        <div>
          <span style={{ color: "#94a3b8" }}>Hujan: </span>
          <strong>{data.current.precipitation.toFixed(1)} mm</strong>
        </div>
        <div>
          <span style={{ color: "#94a3b8" }}>Angin: </span>
          <strong>{data.current.wind_speed.toFixed(1)} m/s</strong>
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <span style={{ color: "#94a3b8" }}>Gambut: </span>
          <strong style={{ color: data.current.soil_moisture_color }}>
            {data.current.soil_moisture_status} ({(data.current.soil_moisture * 100).toFixed(1)}%)
          </strong>
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <span style={{ color: "#94a3b8" }}>Bahaya Api (FDRS): </span>
          <strong style={{ color: data.current.fire_danger.color }}>
            {data.current.fire_danger.level} ({data.current.fire_danger.value})
          </strong>
        </div>
        <div style={{ gridColumn: "span 2" }}>
          <span style={{ color: "#94a3b8" }}>Udara (AQI): </span>
          <strong style={{ color: data.air_quality.aqi > 100 ? "#ef4444" : data.air_quality.aqi > 50 ? "#eab308" : "#22c55e" }}>
            {data.air_quality.aqi} AQI (PM2.5: {data.air_quality.pm2_5.toFixed(1)})
          </strong>
        </div>
      </div>
    </div>
  );
}

export function HotspotPopupContent({
  hotspot,
  onOpenKpsDetail
}: {
  hotspot: PopupHotspot;
  onOpenKpsDetail?: (agency: string) => void;
}) {
  const [showWeather, setShowWeather] = useState(false);
  const [copied, setCopied] = useState(false);

  const hasValidAgency = Boolean(
    hotspot.agencyName &&
    hotspot.agencyName.trim() &&
    hotspot.agencyName.trim() !== "Tidak tersedia" &&
    hotspot.agencyName.trim() !== "-"
  );

  const handleCopy = async () => {
    const text = `${hotspot.latitude.toFixed(5)}, ${hotspot.longitude.toFixed(5)}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore
    }
  };

  const frpVal = hotspot.frp ?? null;
  const frpLevel = frpVal
    ? frpVal > HIGH_FRP_THRESHOLD
      ? "Tinggi"
      : frpVal >= 10
      ? "Sedang"
      : "Rendah"
    : null;

  return (
    <div className="popup-card">
      <div className="popup-head">
        <div className="popup-head-main">
          <strong>{hotspot.source}</strong>
          <span>{hotspot.satellite}</span>
        </div>
        {frpVal !== null && (
          <span
            className={`popup-frp-badge popup-frp-badge--${
              frpVal > HIGH_FRP_THRESHOLD ? "high" : frpVal >= 10 ? "med" : "low"
            }`}
          >
            FRP {frpVal.toFixed(1)} MW
          </span>
        )}
      </div>

      <dl className="popup-grid popup-grid--tight">
        <div style={{ gridColumn: "span 2" }}>
          <dt>Lembaga / KPS</dt>
          <dd>
            {hasValidAgency && onOpenKpsDetail ? (
              <button
                type="button"
                className="popup-kps-link"
                onClick={() => onOpenKpsDetail(hotspot.agencyName.trim())}
                title={`Buka detail KPS: ${hotspot.agencyName}`}
              >
                {hotspot.agencyName}
              </button>
            ) : (
              formatMetadataValue(hotspot.agencyName)
            )}
          </dd>
        </div>
        <div>
          <dt>Satelit</dt>
          <dd>{hotspot.satellite}</dd>
        </div>
        <div>
          <dt>Provinsi</dt>
          <dd>{formatMetadataValue(hotspot.provinceName)}</dd>
        </div>
        <div>
          <dt>Koordinat</dt>
          <dd>
            {hotspot.latitude.toFixed(4)}, {hotspot.longitude.toFixed(4)}
          </dd>
        </div>
        <div>
          <dt>Terdeteksi</dt>
          <dd>{formatTimestamp(hotspot.detectedAt)}</dd>
        </div>
        <div>
          <dt>Kecerahan</dt>
          <dd>{hotspot.brightness ? `${formatNumber(hotspot.brightness)} K` : "Tidak tersedia"}</dd>
        </div>
        <div>
          <dt>FRP</dt>
          <dd>{frpVal !== null ? `${formatNumber(frpVal)} MW` : "Tidak tersedia"}</dd>
        </div>
        {(hotspot.fungsiKawasan || hotspot.kelompokKawasan) && (
          <div style={{ gridColumn: "span 2" }}>
            <dt>Fungsi Kawasan</dt>
            <dd>
              {formatMetadataValue(hotspot.fungsiKawasan)}
              {hotspot.kelompokKawasan ? ` (${hotspot.kelompokKawasan})` : ""}
              {hotspot.namaKawasan ? ` — ${hotspot.namaKawasan}` : ""}
            </dd>
          </div>
        )}
      </dl>

      <div className="popup-actions-row">
        {hasValidAgency && onOpenKpsDetail && (
          <button
            type="button"
            className="popup-action-btn popup-action-btn--primary"
            onClick={() => onOpenKpsDetail(hotspot.agencyName.trim())}
            title={`Buka Detail KPS: ${hotspot.agencyName}`}
          >
            <FileText size={12} />
            <span>Detail KPS</span>
          </button>
        )}
        <button
          type="button"
          className="popup-action-btn"
          onClick={() => void handleCopy()}
          title="Salin koordinat"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          <span>{copied ? "Disalin!" : "Salin"}</span>
        </button>
        <a
          href={`https://www.google.com/maps?q=${hotspot.latitude},${hotspot.longitude}`}
          target="_blank"
          rel="noopener noreferrer"
          className="popup-action-btn"
          title="Buka titik ini di Google Maps"
        >
          <ExternalLink size={12} />
          <span>G-Maps</span>
        </a>
      </div>

      <div className="popup-weather-toggle-section">
        <button
          type="button"
          className="popup-weather-toggle-btn"
          onClick={() => setShowWeather((open) => !open)}
          aria-expanded={showWeather}
        >
          <CloudSun size={12} />
          <span>{showWeather ? "Sembunyikan Cuaca" : "Cuaca & Kualitas Udara"}</span>
          <ChevronDown
            size={12}
            style={{
              marginLeft: "auto",
              transform: showWeather ? "rotate(180deg)" : "none",
              transition: "transform 150ms ease"
            }}
          />
        </button>
        {showWeather && (
          <HotspotWeatherPopup lat={hotspot.latitude} lon={hotspot.longitude} />
        )}
      </div>
    </div>
  );
}
