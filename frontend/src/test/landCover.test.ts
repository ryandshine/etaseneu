import { describe, expect, it } from "vitest";
import { LAND_COVER_CLASSES, LAND_COVER_YEARS } from "../constants/landCover";
import { buildChartData, formatDelta, landCoverColor } from "../lib/landCover";

describe("landCover constants", () => {
  it("has 6 classes in fixed order with hex colors", () => {
    expect(LAND_COVER_CLASSES.map((c) => c.key)).toEqual([
      "hutan", "pertanian", "semak", "basah", "permukiman", "terbuka",
    ]);
    for (const c of LAND_COVER_CLASSES) {
      expect(c.color).toMatch(/^#[0-9A-Fa-f]{6}$/);
    }
  });

  it("covers 2021..2025", () => {
    expect(LAND_COVER_YEARS).toEqual([2021, 2022, 2023, 2024, 2025]);
  });
});

describe("landCoverColor", () => {
  it("returns class color and grey fallback", () => {
    expect(landCoverColor("hutan")).toBe("#1B7A3D");
    expect(landCoverColor("nope")).toBe("#999999");
  });
});

describe("buildChartData", () => {
  it("emits one row per year with pct per class, zero-filled", () => {
    const rows = buildChartData({
      "2021": { hutan: { area_ha: 80, pct: 80 }, basah: { area_ha: 20, pct: 20 } },
      "2022": { hutan: { area_ha: 60, pct: 60 } },
    });
    expect(rows[0]).toMatchObject({ year: "2021", hutan: 80, basah: 20, semak: 0 });
    expect(rows[1]).toMatchObject({ year: "2022", hutan: 60, basah: 0 });
  });
});

describe("formatDelta", () => {
  it("formats sign and unit", () => {
    expect(formatDelta(430.2)).toBe("+430 ha");
    expect(formatDelta(-930.8)).toBe("−931 ha");
    expect(formatDelta(0)).toBe("0 ha");
  });
});
