// Palet & label fungsi kawasan hutan KLHK (KWSHUTAN_AR_250K), disamakan dengan
// tampilan portal SIGAP: Konservasi hijau tua, Hutan Lindung hijau muda,
// Hutan Produksi kuning, HPK ungu, APL merah muda, tubuh air biru.

export type KawasanKelompok =
  | "Konservasi"
  | "Lindung"
  | "Produksi"
  | "Non-Kawasan Hutan"
  | "Kawasan Hutan"
  | "Lainnya";

type KawasanEntry = {
  singkatan: string;
  fungsi: string;
  kelompok: KawasanKelompok;
  color: string;
};

// Warna mengikuti portal SIGAP.
const C_KONSERVASI = "#38761D"; // hijau tua
const C_TN = "#274E13"; // hijau tua pekat (Taman Nasional)
const C_LINDUNG = "#93C47D"; // hijau muda
const C_HPT = "#FFD966"; // kuning
const C_HP = "#F1C232"; // kuning tua
const C_HPK = "#8E7CC3"; // ungu
const C_APL = "#C27BA0"; // merah muda
const C_AIR = "#A4C2F4"; // biru muda
const C_LUAR = "#E6E0D4"; // krem samar

// Kunci = kode FUNGSIKWS (numeric) sebagai string.
export const KAWASAN_HUTAN_BY_KODE: Readonly<Record<string, KawasanEntry>> = {
  "0": { singkatan: "-", fungsi: "Luar Kawasan Hutan", kelompok: "Non-Kawasan Hutan", color: C_LUAR },
  "100000": { singkatan: "KH", fungsi: "Kawasan Hutan (tanpa rincian)", kelompok: "Kawasan Hutan", color: C_LINDUNG },
  "100100": { singkatan: "KSA-KPA", fungsi: "Kawasan Suaka Alam & Pelestarian Alam", kelompok: "Konservasi", color: C_KONSERVASI },
  "100200": { singkatan: "KKP", fungsi: "Kawasan Konservasi Perairan", kelompok: "Konservasi", color: C_KONSERVASI },
  "100201": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100210": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100211": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100220": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100221": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100230": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100240": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100241": { singkatan: "TN", fungsi: "Taman Nasional", kelompok: "Konservasi", color: C_TN },
  "100250": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100251": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100260": { singkatan: "KSA-KPA", fungsi: "KSA-KPA", kelompok: "Konservasi", color: C_KONSERVASI },
  "100300": { singkatan: "HL", fungsi: "Hutan Lindung", kelompok: "Lindung", color: C_LINDUNG },
  "100400": { singkatan: "HPT", fungsi: "Hutan Produksi Terbatas", kelompok: "Produksi", color: C_HPT },
  "100500": { singkatan: "HP", fungsi: "Hutan Produksi Tetap", kelompok: "Produksi", color: C_HP },
  "100700": { singkatan: "HPK", fungsi: "Hutan Produksi yang dapat Dikonversi", kelompok: "Produksi", color: C_HPK },
  "500100": { singkatan: "TA", fungsi: "Tubuh Air", kelompok: "Non-Kawasan Hutan", color: C_AIR },
  "500300": { singkatan: "APL", fungsi: "Areal Penggunaan Lain", kelompok: "Non-Kawasan Hutan", color: C_APL },
};

const KELOMPOK_FALLBACK_COLOR: Record<KawasanKelompok, string> = {
  Konservasi: C_KONSERVASI,
  Lindung: C_LINDUNG,
  Produksi: C_HP,
  "Non-Kawasan Hutan": C_APL,
  "Kawasan Hutan": C_LINDUNG,
  Lainnya: "#9AA0A6",
};

// Fallback kelompok berbasis prefix kode -- sejalan dengan fungsi SQL
// fungsi_kawasan_kelompok() di backend.
export function kawasanKelompokFromKode(kode: number | string | null | undefined): KawasanKelompok {
  if (kode === null || kode === undefined || kode === "") return "Lainnya";
  const known = KAWASAN_HUTAN_BY_KODE[String(kode)];
  if (known) return known.kelompok;
  const s = String(kode);
  if (s.startsWith("1001") || s.startsWith("1002")) return "Konservasi";
  if (s.startsWith("1003")) return "Lindung";
  if (s.startsWith("1004") || s.startsWith("1005") || s.startsWith("1007")) return "Produksi";
  if (s.startsWith("5")) return "Non-Kawasan Hutan";
  if (s.startsWith("1")) return "Kawasan Hutan";
  return "Lainnya";
}

export function kawasanColorFromKode(kode: number | string | null | undefined): string {
  const known = KAWASAN_HUTAN_BY_KODE[String(kode)];
  if (known) return known.color;
  return KELOMPOK_FALLBACK_COLOR[kawasanKelompokFromKode(kode)];
}

// Legenda ringkas untuk ditempel di peta saat overlay menyala.
export const KAWASAN_HUTAN_LEGEND: ReadonlyArray<{ label: string; color: string }> = [
  { label: "Konservasi (KSA-KPA / TN)", color: C_KONSERVASI },
  { label: "Hutan Lindung", color: C_LINDUNG },
  { label: "HP Terbatas", color: C_HPT },
  { label: "HP Tetap", color: C_HP },
  { label: "HP Konversi", color: C_HPK },
  { label: "APL", color: C_APL },
];
