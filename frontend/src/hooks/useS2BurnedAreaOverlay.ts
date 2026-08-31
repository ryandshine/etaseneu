import { useCallback, useEffect, useState } from "react";
import { authFetch } from "../lib/api";

export type S2BurnedAreaFeature = {
  type: "Feature";
  geometry: Record<string, unknown>;
  properties: {
    polygon_metadata_id: number;
    lembaga: string | null;
    nama_prov: string | null;
    nama_kab: string | null;
    area_ha: number;
    dnbr_mean: number | null;
    hotspot_count_month: number;
    has_hotspot: boolean;
    computed_at: string | null;
    kawasan_dominan: string | null;
  };
};

export type S2BurnedAreaOverlay = {
  type: "FeatureCollection";
  features: S2BurnedAreaFeature[];
  meta: {
    year: number;
    month: number;
    polygons: number;
    total_ha: number;
    no_hotspot_but_burned: number;
  };
};

/**
 * Estimasi bekas terbakar dari analisis MANDIRI sistem (Sentinel-2 dNBR),
 * dihitung on-demand oleh admin lewat tombol di Pengaturan. Terpisah total
 * dari lapisan rekap resmi Kementerian Kehutanan (`useBurnedAreaOverlay`):
 * angka di sini ESTIMASI, belum terverifikasi. Default periode: bulan
 * berjalan.
 */
export function useS2BurnedAreaOverlay(enabled: boolean, year?: number, month?: number) {
  const [data, setData] = useState<S2BurnedAreaOverlay | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    if (!enabled) return;
    let active = true;
    setLoading(true);
    const params = new URLSearchParams();
    if (year) params.set("year", String(year));
    if (month) params.set("month", String(month));
    const query = params.toString() ? `?${params.toString()}` : "";
    authFetch(`/api/burned-area/s2-overlay${query}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: S2BurnedAreaOverlay | null) => {
        if (active && payload?.features) {
          setData(payload);
        }
      })
      .catch(() => {
        /* Lapisan pelengkap -- kegagalan tidak mengganggu peta hotspot. */
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [enabled, year, month]);

  useEffect(() => load(), [load]);

  return { data, loading, reload: load };
}
