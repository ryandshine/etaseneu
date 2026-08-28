import { useEffect, useState } from "react";
import { authFetch } from "../lib/api";

export type BurnedAreaOverlayFeature = {
  type: "Feature";
  geometry: Record<string, unknown>;
  properties: {
    polygon_metadata_id: number;
    lembaga: string | null;
    skema: string | null;
    nama_prov: string | null;
    wilker_bps: string | null;
    burned_area_ha: number;
    burned_months: number;
    latest_period: string | null;
    // true = KPS punya luas terbakar tapi tidak ada bentuk piksel yang bisa
    // divektorisasi (luasnya di bawah resolusi piksel MODIS 500 m), jadi
    // server mengirim centroid kawasan sebagai penanda perkiraan.
    is_estimated: boolean;
  };
};

export type BurnedAreaOverlay = {
  type: "FeatureCollection";
  features: BurnedAreaOverlayFeature[];
  total_ha: number;
  kps_count: number;
};

function normalizeWilker(val?: string | null): string {
  if (!val) return "";
  const clean = val.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (clean.includes("kutai") || clean.includes("kurtanegara")) return "kutaikartanegara";
  return clean;
}

function matchWilker(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return false;
  return normalizeWilker(a) === normalizeWilker(b);
}

/**
 * Lapisan "kawasan terdampak kebakaran" untuk peta utama.
 *
 * Sengaja tidak ikut `hotspots`/filter waktu: hotspot itu deteksi titik api
 * near-real-time (tiap 3 jam), sedangkan burned area adalah rekap resmi KLHK
 * yang terbit tidak dengan jadwal tetap. Menyamakan rentang waktunya akan
 * bikin lapisan ini nyaris selalu kosong saat pengguna melihat rentang
 * beberapa hari terakhir. Default: sepanjang tahun berjalan.
 */
export function useBurnedAreaOverlay(enabled: boolean, year?: number, wilkerFilter?: string) {
  const [data, setData] = useState<BurnedAreaOverlay | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let active = true;
    setLoading(true);
    const query = year ? `?year=${year}` : "";
    authFetch(`/api/burned-area/map-overlay${query}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: BurnedAreaOverlay | null) => {
        if (active && payload?.features) {
          const features = wilkerFilter
            ? payload.features.filter((f) => matchWilker(f.properties.wilker_bps, wilkerFilter))
            : payload.features;
          const total_ha = features.reduce((sum, f) => sum + (f.properties.burned_area_ha || 0), 0);
          setData({
            type: "FeatureCollection",
            features,
            total_ha,
            kps_count: features.length,
          });
        }
      })
      .catch(() => {
        /* Lapisan pelengkap -- kalau gagal, peta hotspot tetap berfungsi. */
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [enabled, year, wilkerFilter]);

  return { data, loading };
}
