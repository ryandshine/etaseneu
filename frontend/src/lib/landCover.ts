import {
  LAND_COVER_CLASSES,
  LAND_COVER_YEARS,
  type LandCoverClassKey,
} from "../constants/landCover";

export type LandCoverTable = Record<
  string,
  Partial<Record<LandCoverClassKey, { area_ha: number; pct: number }>>
>;

const COLOR_BY_KEY = new Map(LAND_COVER_CLASSES.map((c) => [c.key, c.color]));

export function landCoverColor(key: string): string {
  return COLOR_BY_KEY.get(key as LandCoverClassKey) ?? "#999999";
}

export function buildChartData(
  table: LandCoverTable,
): Array<{ year: string } & Record<LandCoverClassKey, number>> {
  return LAND_COVER_YEARS.map((year) => {
    const cell = table[String(year)] ?? {};
    const row = { year: String(year) } as { year: string } & Record<LandCoverClassKey, number>;
    for (const { key } of LAND_COVER_CLASSES) {
      row[key] = cell[key]?.pct ?? 0;
    }
    return row;
  });
}

export function formatDelta(ha: number): string {
  const rounded = Math.round(ha);
  if (rounded === 0) return "0 ha";
  const sign = rounded > 0 ? "+" : "−";
  return `${sign}${Math.abs(rounded)} ha`;
}
