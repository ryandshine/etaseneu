import { describe, expect, it } from "vitest";

import {
  DEFAULT_SMOKE_IMAGERY_LAYER,
  PM25_LEGEND,
  PM25_OFFSETS,
  formatSmokeValidTime,
  pm25Category,
  pm25Rgba,
  rasterizePm25,
  smokeImageryDate,
  smokeImageryUrlTemplate,
} from "../lib/smoke";

describe("pm25Category (ambang BMKG, µg/m³)", () => {
  it.each([
    [0, "baik"],
    [15.5, "baik"],
    [15.6, "sedang"],
    [55.4, "sedang"],
    [55.5, "tidak_sehat"],
    [150.4, "tidak_sehat"],
    [150.5, "sangat_tidak_sehat"],
    [250.4, "sangat_tidak_sehat"],
    [250.5, "berbahaya"],
    [948, "berbahaya"],
  ])("%s -> %s", (value, expected) => {
    expect(pm25Category(value)).toBe(expected);
  });

  it("legend covers all five categories, in ascending order, with a colour each", () => {
    expect(PM25_LEGEND.map((item) => item.key)).toEqual([
      "baik",
      "sedang",
      "tidak_sehat",
      "sangat_tidak_sehat",
      "berbahaya",
    ]);
    expect(new Set(PM25_LEGEND.map((item) => item.color)).size).toBe(5);
  });
});

describe("pm25Rgba", () => {
  it("is fully transparent for clean air so the map underneath stays readable", () => {
    expect(pm25Rgba(5)[3]).toBe(0);
    expect(pm25Rgba(0)[3]).toBe(0);
  });

  it("gets more opaque as the concentration rises", () => {
    const alphas = [20, 60, 160, 300, 500].map((v) => pm25Rgba(v)[3]);
    for (let i = 1; i < alphas.length; i++) {
      expect(alphas[i]).toBeGreaterThan(alphas[i - 1]);
    }
  });

  it("saturates instead of extrapolating beyond the last colour stop", () => {
    expect(pm25Rgba(5000)).toEqual(pm25Rgba(1000));
  });
});

describe("imagery helpers", () => {
  it("uses the UTC date, because GIBS days are UTC days", () => {
    // 00.30 WIB tanggal 21 = 17.30 UTC tanggal 20
    const now = new Date("2026-09-20T17:30:00Z");
    expect(smokeImageryDate("today", now)).toBe("2026-09-20");
    expect(smokeImageryDate("yesterday", now)).toBe("2026-09-19");
  });

  it("builds a Leaflet tile template that goes through our own proxy", () => {
    const tpl = smokeImageryUrlTemplate("2026-09-19");
    expect(tpl).toBe(`/api/smoke/imagery/${DEFAULT_SMOKE_IMAGERY_LAYER}/2026-09-19/{z}/{x}/{y}`);
    expect(tpl.startsWith("http")).toBe(false); // tidak boleh menembak NASA langsung dari browser
  });

  it("offers now / +12 / +24 / +48 hours for the PM2.5 forecast", () => {
    expect(PM25_OFFSETS).toEqual([0, 12, 24, 48]);
  });

  it("formats the forecast valid time in WIB, Indonesian", () => {
    expect(formatSmokeValidTime("2026-09-20T12:00")).toBe("Min, 20 Sep 12.00 WIB");
  });
});

describe("rasterizePm25", () => {
  const header = { lo1: 100, la1: 2, dx: 1, dy: 1, nx: 2, ny: 2 };

  it("returns an RGBA image sized from the grid and the map bounds", () => {
    const img = rasterizePm25({ header, data: [400, 0, 0, 0] }, { pxPerCell: 4 });
    expect(img.width).toBe(4);
    expect(img.height).toBeGreaterThan(0);
    expect(img.data.length).toBe(img.width * img.height * 4);
    expect(img.bounds).toEqual([
      [1, 100],
      [2, 101],
    ]); // [[selatan, barat], [utara, timur]]
  });

  it("puts the north-west cell at the top-left pixel (row 0 = north)", () => {
    const img = rasterizePm25({ header, data: [400, 0, 0, 0] }, { pxPerCell: 4 });
    const topLeftAlpha = img.data[3];
    const bottomRightAlpha = img.data[((img.height - 1) * img.width + (img.width - 1)) * 4 + 3];
    expect(topLeftAlpha).toBeGreaterThan(150); // berbahaya -> pekat
    expect(bottomRightAlpha).toBe(0); // udara bersih -> transparan
  });

  it("interpolates smoothly between cells instead of drawing blocks", () => {
    const img = rasterizePm25({ header: { ...header, nx: 2, ny: 2 }, data: [300, 300, 0, 0] }, { pxPerCell: 8 });
    const alphaAtRow = (row: number) => img.data[(row * img.width + 3) * 4 + 3];
    const top = alphaAtRow(0);
    const middle = alphaAtRow(Math.floor(img.height / 2));
    const bottom = alphaAtRow(img.height - 1);
    expect(top).toBeGreaterThan(middle);
    expect(middle).toBeGreaterThan(bottom);
  });

  it("treats missing values as clean air rather than crashing", () => {
    const img = rasterizePm25(
      { header, data: [Number.NaN, 0, 0, undefined as unknown as number] },
      { pxPerCell: 4 },
    );
    expect(img.data[3]).toBe(0);
  });
});
