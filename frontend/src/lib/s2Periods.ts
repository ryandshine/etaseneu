// Warna & label lapisan "Estimasi Sentinel-2" per periode (bulan).
//
// Backend memecah poligon yang terbakar di >1 bulan jadi potongan
// tak-tumpang-tindih per "bulan pertama terdeteksi" (lihat
// `_s2_period_pieces` di postgres_store/_s2_burned_area.py). Tiap potongan
// diwarnai sesuai bulan pertama terdeteksinya; potongan yang terdeteksi LAGI
// di bulan berikutnya (`redetected_in` tidak kosong) diberi garis tepi warna
// bulan berikutnya itu + isian lebih pekat -- supaya kelihatan "ini bekas
// bulan X yang masih terlihat di bulan Y", bukan dua poligon bertumpuk.
// Dipakai bersama Live Map (HotspotMap.tsx) dan peta Detail KPS.

export const S2_MONTH_NAMES = [
  "Januari",
  "Februari",
  "Maret",
  "April",
  "Mei",
  "Juni",
  "Juli",
  "Agustus",
  "September",
  "Oktober",
  "November",
  "Desember"
];

// Bulan berurutan dapat warna berurutan (kuning -> oranye -> merah -> ...),
// kontras di basemap satelit gelap maupun peta jalan. Warna TETAP per bulan
// kalender (bukan per urutan periode yang kebetulan tampil) -- supaya
// "September" berwarna sama di Live Map (semua periode nasional) dan di
// Detail KPS (cuma periode KPS itu). Agustus 2026 = kuning.
const PERIOD_PALETTE = ["#facc15", "#f97316", "#ef4444", "#d946ef", "#22d3ee", "#84cc16"];
const PALETTE_OFFSET = 5; // (2026*12 + 7 + 5) % 6 === 0 -> Agustus 2026 = kuning

export type S2PieceProps = {
  year: number;
  month: number;
  redetected_in?: string[];
};

export function periodKey(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

export function periodLabel(key: string): string {
  const [y, m] = key.split("-").map(Number);
  return `${S2_MONTH_NAMES[m - 1] ?? key} ${y}`;
}

/** Warna tetap satu periode "YYYY-MM". */
export function s2PeriodColor(key: string): string {
  const [y, m] = key.split("-").map(Number);
  if (!Number.isFinite(y) || !Number.isFinite(m)) return PERIOD_PALETTE[0];
  const idx = (y * 12 + (m - 1) + PALETTE_OFFSET) % PERIOD_PALETTE.length;
  return PERIOD_PALETTE[idx];
}

/** Daftar periode dari fitur-fitur (kalau meta.periods tidak tersedia). */
export function periodsFromPieces(pieces: S2PieceProps[]): string[] {
  const keys = new Set<string>();
  for (const p of pieces) {
    keys.add(periodKey(p.year, p.month));
    for (const r of p.redetected_in ?? []) keys.add(r);
  }
  return [...keys].sort();
}

export function s2PieceStyle(props: S2PieceProps) {
  const own = s2PeriodColor(periodKey(props.year, props.month));
  const redetected = props.redetected_in ?? [];
  if (redetected.length > 0) {
    return {
      color: s2PeriodColor(redetected[redetected.length - 1]),
      weight: 2.2,
      dashArray: undefined as string | undefined,
      fillColor: own,
      fillOpacity: 0.6
    };
  }
  return { color: own, weight: 1.4, dashArray: "5 3" as string | undefined, fillColor: own, fillOpacity: 0.35 };
}
