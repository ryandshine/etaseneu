import { describe, expect, it } from "vitest";
import { buildTimeRange } from "../hooks/useDashboardData";

describe("buildTimeRange - Calendar Preset Filters & Custom Ranges in WIB", () => {
  it("should represent Hari Ini (1 full calendar day) of the selected date in WIB", () => {
    const selectedDate = "2026-05-30";
    const range = buildTimeRange("24h", "2026-05-29", selectedDate, 0);

    // 2026-05-30 00:00:00 WIB -> 2026-05-29 17:00:00 UTC
    expect(range.startAt.toISOString()).toBe("2026-05-29T17:00:00.000Z");
    // 2026-05-31 00:00:00 WIB -> 2026-05-30 17:00:00 UTC
    expect(range.endAt.toISOString()).toBe("2026-05-30T17:00:00.000Z");
    expect(range.label).toBe("Hari ini");
  });

  it("should represent 48 Jam (2 full calendar days ending on selected date) in WIB", () => {
    const selectedDate = "2026-05-30";
    const range = buildTimeRange("48h", "2026-05-29", selectedDate, 0);

    // 2026-05-29 00:00:00 WIB -> 2026-05-28 17:00:00 UTC
    expect(range.startAt.toISOString()).toBe("2026-05-28T17:00:00.000Z");
    // 2026-05-31 00:00:00 WIB -> 2026-05-30 17:00:00 UTC
    expect(range.endAt.toISOString()).toBe("2026-05-30T17:00:00.000Z");
    expect(range.label).toBe("48 jam terakhir");
  });

  it("should represent 3 Hari (3 full calendar days ending on selected date) in WIB", () => {
    const selectedDate = "2026-05-30";
    const range = buildTimeRange("3d", "2026-05-29", selectedDate, 0);

    // 2026-05-28 00:00:00 WIB -> 2026-05-27 17:00:00 UTC
    expect(range.startAt.toISOString()).toBe("2026-05-27T17:00:00.000Z");
    // 2026-05-31 00:00:00 WIB -> 2026-05-30 17:00:00 UTC
    expect(range.endAt.toISOString()).toBe("2026-05-30T17:00:00.000Z");
    expect(range.label).toBe("3 hari terakhir");
  });

  it("should represent 7 Hari (7 full calendar days ending on selected date) in WIB", () => {
    const selectedDate = "2026-05-30";
    const range = buildTimeRange("7d", "2026-05-29", selectedDate, 0);

    // 2026-05-24 00:00:00 WIB -> 2026-05-23 17:00:00 UTC
    expect(range.startAt.toISOString()).toBe("2026-05-23T17:00:00.000Z");
    // 2026-05-31 00:00:00 WIB -> 2026-05-30 17:00:00 UTC
    expect(range.endAt.toISOString()).toBe("2026-05-30T17:00:00.000Z");
    expect(range.label).toBe("7 hari terakhir");
  });

  it("should represent 30 Hari (30 full calendar days ending on selected date) in WIB", () => {
    const selectedDate = "2026-05-30";
    const range = buildTimeRange("30d", "2026-05-29", selectedDate, 0);

    // 2026-05-01 00:00:00 WIB -> 2026-04-30 17:00:00 UTC
    expect(range.startAt.toISOString()).toBe("2026-04-30T17:00:00.000Z");
    // 2026-05-31 00:00:00 WIB -> 2026-05-30 17:00:00 UTC
    expect(range.endAt.toISOString()).toBe("2026-05-30T17:00:00.000Z");
    expect(range.label).toBe("30 hari terakhir");
  });

  it("should represent Custom Date Range (inclusive start to exclusive end + 1 day) in WIB", () => {
    const startDate = "2026-05-10";
    const endDate = "2026-05-15";
    const range = buildTimeRange("custom", startDate, endDate, 0);

    // 2026-05-10 00:00:00 WIB -> 2026-05-09 17:00:00 UTC
    expect(range.startAt.toISOString()).toBe("2026-05-09T17:00:00.000Z");
    // 2026-05-16 00:00:00 WIB (which is next_day(end_date)) -> 2026-05-15 17:00:00 UTC
    expect(range.endAt.toISOString()).toBe("2026-05-15T17:00:00.000Z");
    expect(range.label).toBe("2026-05-10 to 2026-05-15");
  });
});
