import { describe, expect, it } from "vitest";
import { buildTimeRange } from "../hooks/useDashboardData";

describe("buildTimeRange - Calendar Preset Filters & Custom Ranges in WIB", () => {
  it("should represent 24 Jam as the full calendar day when the selected date is already in the past", () => {
    const selectedDate = "2026-05-30";
    const now = new Date("2026-08-09T00:49:00.000Z");
    const range = buildTimeRange("24h", "2026-05-29", selectedDate, 0, now);

    // 2026-05-30 00:00:00 WIB -> 2026-05-29 17:00:00 UTC
    expect(range.startAt.toISOString()).toBe("2026-05-29T17:00:00.000Z");
    // 2026-05-31 00:00:00 WIB -> 2026-05-30 17:00:00 UTC
    expect(range.endAt.toISOString()).toBe("2026-05-30T17:00:00.000Z");
    expect(range.label).toBe("24 jam terakhir");
  });

  it("should roll 24 Jam back from the current hour when the selected date is today", () => {
    // 2026-08-09 00:49 WIB -> 2026-08-08 17:49 UTC. Hari kalender WIB baru
    // berjalan 49 menit, sehingga jendela "hari ini" yang lama akan kosong.
    const now = new Date("2026-08-08T17:49:00.000Z");
    const range = buildTimeRange("24h", "2026-08-08", "2026-08-09", 0, now);

    // Dibulatkan ke bawah ke jam penuh, lalu mundur 24 jam.
    expect(range.endAt.toISOString()).toBe("2026-08-08T17:00:00.000Z");
    expect(range.startAt.toISOString()).toBe("2026-08-07T17:00:00.000Z");
  });

  it("should keep the 24 Jam window stable across clock ticks within the same hour", () => {
    // Cache key backend memuat start_at/end_at persis; jendela yang bergeser
    // tiap menit akan membuat cache tidak pernah kena.
    const first = buildTimeRange("24h", "2026-08-08", "2026-08-09", 0, new Date("2026-08-08T17:05:00.000Z"));
    const second = buildTimeRange("24h", "2026-08-08", "2026-08-09", 1, new Date("2026-08-08T17:58:00.000Z"));

    expect(first.startAt.toISOString()).toBe(second.startAt.toISOString());
    expect(first.endAt.toISOString()).toBe(second.endAt.toISOString());
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

  it("should not throw and should fall back to a valid date when the custom range is incomplete or malformed", () => {
    expect(() => buildTimeRange("custom", "", "2026-05-15", 0)).not.toThrow();
    expect(() => buildTimeRange("custom", "2026-05-10", "", 0)).not.toThrow();
    expect(() => buildTimeRange("custom", "2026-13-40", "2026-05-15", 0)).not.toThrow();

    const range = buildTimeRange("custom", "", "2026-05-15", 0);
    expect(Number.isNaN(range.startAt.getTime())).toBe(false);
    expect(() => range.startAt.toISOString()).not.toThrow();
  });
});
