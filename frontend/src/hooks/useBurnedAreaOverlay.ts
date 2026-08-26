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

/**
 * Lapisan "kawasan terdampak kebakaran" untuk peta utama.
 *
 * Sengaja tidak ikut `hotspots`/filter waktu: hotspot itu deteksi titik api
 * near-real-time (tiap 3 jam), sedangkan burned area adalah rekap resmi KLHK
 * yang terbit tidak dengan jadwal tetap. Menyamakan rentang waktunya akan
 * bikin lapisan ini nyaris selalu kosong saat pengguna melihat rentang
 * beberapa hari terakhir. Default: sepanjang tahun berjalan.
 */
export function useBurnedAreaOverlay(enabled: boolean, year?: number) {
  const [data, setData] = useState<BurnedAreaOverlay | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    // Sekali diambil, disimpan -- mematikan lalu menyalakan lagi togglenya
    // tidak perlu memanggil ulang server.
    if (data) {
      return;
    }

    let active = true;
    setLoading(true);
    const query = year ? `?year=${year}` : "";
    authFetch(`/api/burned-area/map-overlay${query}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: BurnedAreaOverlay | null) => {
        if (active && payload?.features) {
          setData(payload);
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
  }, [enabled, year, data]);

  return { data, loading };
}
