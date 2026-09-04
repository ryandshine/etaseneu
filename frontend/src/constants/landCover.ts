export type LandCoverClassKey = "hutan" | "kebun" | "semak" | "pertanian" | "terbuka" | "air";

export const LAND_COVER_CLASSES: ReadonlyArray<{
  key: LandCoverClassKey;
  label: string;
  color: string;
}> = [
  { key: "hutan", label: "Hutan", color: "#1B7A3D" },
  { key: "kebun", label: "Kebun Sawit", color: "#6B8E23" },
  { key: "semak", label: "Semak/Belukar", color: "#9CC55B" },
  { key: "pertanian", label: "Pertanian/Kebun", color: "#E8B84B" },
  { key: "terbuka", label: "Lahan Terbuka", color: "#C97B4A" },
  { key: "air", label: "Badan Air", color: "#2E7BBF" },
] as const;

export const LAND_COVER_YEARS: readonly number[] = [2021, 2022, 2023, 2024, 2025];

// Versi formula analisis yang dipakai server SEKARANG -- WAJIB sama dengan
// `FORMULA_VERSION` di backend/app/services/land_cover_service.py. Cuma
// dipakai daftar Tutupan Lahan (endpoint /polygons tidak membawa versi
// terkini); LandCoverPanel memakai `current_formula_version` dari /status.
export const LAND_COVER_FORMULA_VERSION = 3;
