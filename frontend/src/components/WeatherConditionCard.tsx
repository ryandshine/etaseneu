import { useEffect, useState } from "react";
import { authFetch } from "../lib/api";

type SpotWeatherDetail = {
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

// Kartu cuaca & kualitas udara untuk satu titik koordinat -- dipakai di
// halaman detail KPS untuk deteksi yang sedang dipilih.
export function WeatherConditionCard({ lat, lon }: { lat: number; lon: number }) {
  const [data, setData] = useState<SpotWeatherDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(false);

    authFetch(`/api/weather/spot?lat=${lat}&lon=${lon}`)
      .then((res) => {
        if (!res.ok) throw new Error("Failed");
        return res.json() as Promise<SpotWeatherDetail>;
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
      <section className="matrix-detail-card">
        <div className="matrix-detail-card__head">
          <span>Kondisi Cuaca & Kualitas Udara</span>
          <strong>Memuat...</strong>
        </div>
        <div style={{ padding: "12px", color: "#94a3b8", fontSize: "11px" }}>
          ⚡ Memuat data cuaca dan kualitas udara Open-Meteo...
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="matrix-detail-card">
        <div className="matrix-detail-card__head">
          <span>Kondisi Cuaca & Kualitas Udara</span>
          <strong style={{ color: "#ef4444" }}>Error</strong>
        </div>
        <div style={{ padding: "12px", color: "#ef4444", fontSize: "11px" }}>
          ⚠️ Gagal mengambil data cuaca dari Open-Meteo.
        </div>
      </section>
    );
  }

  return (
    <section className="matrix-detail-card">
      <div className="matrix-detail-card__head">
        <span>Kondisi Cuaca & Kualitas Udara</span>
        <strong style={{ color: data.current.fire_danger.color }}>Bahaya Api (FDRS): {data.current.fire_danger.level}</strong>
      </div>
      <div className="matrix-detail-grid matrix-detail-grid--two">
        <div className="matrix-detail-item">
          <span>Suhu Udara</span>
          <strong>{data.current.temperature.toFixed(1)} °C</strong>
        </div>
        <div className="matrix-detail-item">
          <span>Kelembapan Udara</span>
          <strong>{data.current.humidity.toFixed(0)}% RH</strong>
        </div>
        <div className="matrix-detail-item">
          <span>Curah Hujan</span>
          <strong>{data.current.precipitation.toFixed(1)} mm</strong>
        </div>
        <div className="matrix-detail-item">
          <span>Kecepatan Angin</span>
          <strong>{data.current.wind_speed.toFixed(1)} m/s</strong>
        </div>
        <div className="matrix-detail-item">
          <span>Arah Angin</span>
          <strong>{data.current.wind_direction.toFixed(0)}°</strong>
        </div>
        <div className="matrix-detail-item">
          <span>Hembusan Angin</span>
          <strong>{data.current.wind_gusts.toFixed(1)} m/s</strong>
        </div>
        <div className="matrix-detail-item">
          <span>Kekeringan Gambut</span>
          <strong style={{ color: data.current.soil_moisture_color }}>
            {data.current.soil_moisture_status} ({(data.current.soil_moisture * 100).toFixed(1)}%)
          </strong>
        </div>
        <div className="matrix-detail-item">
          <span>Polusi Udara (AQI)</span>
          <strong style={{ color: data.air_quality.aqi > 100 ? "#ef4444" : data.air_quality.aqi > 50 ? "#eab308" : "#22c55e" }}>
            {data.air_quality.aqi} AQI (PM2.5: {data.air_quality.pm2_5.toFixed(1)})
          </strong>
        </div>
      </div>
    </section>
  );
}
