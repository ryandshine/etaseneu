import { describe, expect, it } from "vitest";
import { periodLabel, periodsFromPieces, s2PeriodColor, s2PieceStyle } from "../lib/s2Periods";

describe("s2Periods", () => {
  it("gives each calendar month a fixed color (Agustus 2026 = kuning, September = oranye)", () => {
    expect(s2PeriodColor("2026-08")).toBe("#facc15");
    expect(s2PeriodColor("2026-09")).toBe("#f97316");
    // stabil apa pun periode lain yang tampil -- Live Map & Detail KPS sama
    expect(s2PeriodColor("2026-09")).toBe(s2PeriodColor("2026-09"));
  });

  it("gives consecutive months different colors, also across a year boundary", () => {
    const keys = ["2026-10", "2026-11", "2026-12", "2027-01"];
    const colors = keys.map(s2PeriodColor);
    for (let i = 1; i < colors.length; i += 1) {
      expect(colors[i]).not.toBe(colors[i - 1]);
    }
  });

  it("labels periods in Indonesian", () => {
    expect(periodLabel("2026-08")).toBe("Agustus 2026");
  });

  it("gives a redetected piece the first month's fill and the later month's solid border", () => {
    const style = s2PieceStyle({ year: 2026, month: 8, redetected_in: ["2026-09"] });
    expect(style.fillColor).toBe("#facc15");
    expect(style.color).toBe("#f97316");
    expect(style.dashArray).toBeUndefined();
    expect(style.fillOpacity).toBeGreaterThan(s2PieceStyle({ year: 2026, month: 8 }).fillOpacity);
  });

  it("keeps a plain piece dashed in its own month color", () => {
    const style = s2PieceStyle({ year: 2026, month: 9, redetected_in: [] });
    expect(style.color).toBe("#f97316");
    expect(style.fillColor).toBe("#f97316");
    expect(style.dashArray).toBe("5 3");
  });

  it("derives periods from pieces including redetection months", () => {
    expect(periodsFromPieces([{ year: 2026, month: 8, redetected_in: ["2026-09"] }])).toEqual(["2026-08", "2026-09"]);
  });
});
