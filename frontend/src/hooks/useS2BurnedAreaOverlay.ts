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
    // Mode gabungan: poligon yang terbakar di >1 bulan dipecah backend jadi
    // potongan tak-tumpang-tindih per BULAN PERTAMA TERDETEKSI (`year`/`month`
    // di atas = bulan itu). `redetected_in` = periode "YYYY-MM" belakangan yang
    // mendeteksi potongan ini lagi (kosong = cuma terdeteksi sekali) -- lebih
    // sering bekas lama yang belum "terserap" baseline bulan berikutnya
    // (`analyze_month` per bulan independen), bukan kebakaran baru.
    redetected_in: string[];
    // Luas potongan yang tampil (geometri). `area_ha` = luas raster GEE
    // seluruh bulan itu untuk poligon ini, bukan luas potongan.
    piece_ha: number;
    // Footprint poligon lintas semua periode, tanpa hitung ganda.
    footprint_ha: number;
    periods_breakdown: Array<{ year: number; month: number; area_ha: number }>;
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
    // Jumlah poligon KPS/Hutan Adat (bukan jumlah fitur/potongan).
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
