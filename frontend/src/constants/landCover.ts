// Taksonomi 6 kelas mengikuti kategori penggunaan lahan IPCC (Forest/
// Cropland/Grassland/Wetland/Settlement/Other Land) sejak formula v4
// (2026-09-05) -- lihat docstring backend/app/services/land_cover_service.py.
// Sawit TIDAK jadi kelas sendiri, dilebur ke "pertanian" (Cropland).
export type LandCoverClassKey =
  | "hutan"
  | "pertanian"
  | "semak"
  | "basah"
  | "permukiman"
  | "terbuka";

export const LAND_COVER_CLASSES: ReadonlyArray<{
  key: LandCoverClassKey;
  label: string;
  color: string;
}> = [
  { key: "hutan", label: "Hutan", color: "#1B7A3D" },
  { key: "pertanian", label: "Pertanian/Perkebunan", color: "#E8B84B" },
  { key: "semak", label: "Semak/Belukar", color: "#9CC55B" },
  { key: "basah", label: "Lahan Basah/Perairan", color: "#2E7BBF" },
  { key: "permukiman", label: "Permukiman", color: "#B95E5E" },
  { key: "terbuka", label: "Lahan Terbuka", color: "#C97B4A" },
] as const;

export const LAND_COVER_YEARS: readonly number[] = [2021, 2022, 2023, 2024, 2025];

// Versi formula analisis yang dipakai server SEKARANG -- WAJIB sama dengan
// `FORMULA_VERSION` di backend/app/services/land_cover_service.py. Cuma
// dipakai daftar Tutupan Lahan (endpoint /polygons tidak membawa versi
// terkini); LandCoverPanel memakai `current_formula_version` dari /status.
export const LAND_COVER_FORMULA_VERSION = 4;
