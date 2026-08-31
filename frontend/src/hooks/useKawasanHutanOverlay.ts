import { useEffect, useState } from "react";

export type KawasanHutanFeature = {
  type: "Feature";
  geometry: Record<string, unknown>;
  properties: {
    // Kode FUNGSIKWS KLHK. Nama field mengikuti dump ogr2ogr (huruf kecil).
    fungsikws: number | null;
  };
};

export type KawasanHutanCollection = {
  type: "FeatureCollection";
  features: KawasanHutanFeature[];
};

/**
 * Overlay fungsi kawasan hutan KLHK (KWSHUTAN_AR_250K) -- versi ringan yang
 * SUDAH di-dissolve per fungsi & disederhanakan (~1 fitur per kode FUNGSIKWS),
 * disajikan sebagai berkas statis dari `public/` supaya tidak menyentuh
 * `LayerService` (yang memuat geojson penuh ke RAM). Lazy: berkas baru diambil
 * saat overlay pertama kali dinyalakan, lalu di-cache di memori komponen.
 */
export function useKawasanHutanOverlay(enabled: boolean) {
  const [data, setData] = useState<KawasanHutanCollection | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!enabled || data || loading) return;
    let active = true;
    setLoading(true);
    setError(false);
    fetch(`${import.meta.env.BASE_URL}kawasan_hutan.min.json`)
      .then((response) => (response.ok ? (response.json() as Promise<KawasanHutanCollection>) : null))
      .then((payload) => {
        if (!active) return;
        if (payload?.features) setData(payload);
        else setError(true);
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
  }, [enabled, data, loading]);

  return { data, loading, error };
}
