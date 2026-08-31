// Overlay fungsi kawasan hutan diambil LIVE dari layanan resmi ArcGIS
// Ditjen Planologi Kehutanan (KWSHUTAN_AR_250K). Warna & simbol dirender oleh
// server itu sendiri -- di sini hanya URL layanan + salinan legenda untuk
// ditempel di peta.

export const KAWASAN_HUTAN_MAPSERVER =
  "https://geoportal.planologi.kehutanan.go.id/server/rest/services/Peta_Interaktif_2026/KWSHUTAN_AR_250K/MapServer";

// Warna disalin dari endpoint /legend layanan di atas (Juni 2026).
export const KAWASAN_HUTAN_LEGEND: ReadonlyArray<{ label: string; color: string }> = [
  { label: "Konservasi", color: "#AD3FFF" },
  { label: "Hutan Lindung", color: "#02AD00" },
  { label: "HP Terbatas", color: "#8AF200" },
  { label: "HP Tetap", color: "#FFFF00" },
  { label: "HP Konversi", color: "#FF5EFF" },
  { label: "APL", color: "#FFFFFF" },
  { label: "Tubuh Air", color: "#00C5FF" },
];
