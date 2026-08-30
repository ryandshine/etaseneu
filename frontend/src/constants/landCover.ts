export type LandCoverClassKey = "hutan" | "semak" | "pertanian" | "terbuka" | "air";

export const LAND_COVER_CLASSES: ReadonlyArray<{
  key: LandCoverClassKey;
  label: string;
  color: string;
}> = [
  { key: "hutan", label: "Hutan", color: "#1B7A3D" },
  { key: "semak", label: "Semak/Belukar", color: "#9CC55B" },
  { key: "pertanian", label: "Pertanian/Kebun", color: "#E8B84B" },
  { key: "terbuka", label: "Lahan Terbuka", color: "#C97B4A" },
  { key: "air", label: "Badan Air", color: "#2E7BBF" },
] as const;

export const LAND_COVER_YEARS: readonly number[] = [2020, 2021, 2022, 2023, 2024, 2025];
