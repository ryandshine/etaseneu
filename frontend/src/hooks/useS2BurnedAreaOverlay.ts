import { useCallback, useEffect, useState } from "react";
import { authFetch } from "../lib/api";

export type S2BurnedAreaFeature = {
  type: "Feature";
  geometry: Record<string, unknown>;
  properties: {
    polygon_metadata_id: number;
    year: number;
    month: number;
    lembaga: string | null;
    nama_prov: string | null;
    nama_kab: string | null;
    area_ha: number;
    dnbr_mean: number | null;
    hotspot_count_month: number;
    has_hotspot: boolean;
    computed_at: string | null;
    kawasan_dominan: string | null;
    // Luas (ha) yang JUGA tercatat di periode lain milik poligon yang sama
    // (0 kalau tidak beririsan). Lihat `overlap_periods` untuk periode mana.
    // Ini bukan berarti "kebakaran baru dua kali" -- lebih sering bekas
    // periode sebelumnya yang belum "terserap" jadi baseline bulan berikutnya
    // (`analyze_month` per bulan independen, jendela pra-kebakaran tumpang
    // tindih). Cuma terisi di mode gabungan (tanpa year/month).
    overlap_ha: number;
    overlap_periods: string[];
  };
};

export type S2BurnedAreaOverlay = {
  type: "FeatureCollection";
  features: S2BurnedAreaFeature[];
  meta: {
    // null saat lapisan menggabung SEMUA periode (Live Map default) -- lihat
    // `periods` untuk daftar "YYYY-MM" yang benar-benar ada.
    year: number | null;
    month: number | null;
    periods: string[];
    polygons: number;
    // Footprint riil (union geometri, sudah dikoreksi dobel-hitung irisan
    // antar-periode) -- pakai ini untuk ringkasan/statistik, BUKAN
    // `total_ha_raw_sum`.
    total_ha: number;
    // Sum `area_ha` mentah per fitur TANPA koreksi overlap -- cuma untuk
    // perbandingan/debug, jangan ditampilkan sebagai "total" ke pengguna.
    total_ha_raw_sum: number;
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
