import { describe, expect, it } from "vitest";
import { formatDateWIB } from "../lib/date";

describe("Timezone Edge Cases in WIB (Asia/Jakarta)", () => {
  it("should format 00:01 WIB as 2026-05-31", () => {
    // 31-05-2026 00:01 WIB is 30-05-2026 17:01 UTC
    const date = new Date("2026-05-30T17:01:00Z");
    expect(formatDateWIB(date)).toBe("2026-05-31");
  });

  it("should format 00:30 WIB as 2026-05-31", () => {
    // 31-05-2026 00:30 WIB is 30-05-2026 17:30 UTC
    const date = new Date("2026-05-30T17:30:00Z");
    expect(formatDateWIB(date)).toBe("2026-05-31");
  });

  it("should format 01:00 WIB as 2026-05-31", () => {
    // 31-05-2026 01:00 WIB is 30-05-2026 18:00 UTC
    const date = new Date("2026-05-30T18:00:00Z");
    expect(formatDateWIB(date)).toBe("2026-05-31");
  });

  it("should format 06:59 WIB as 2026-05-31", () => {
    // 31-05-2026 06:59 WIB is 30-05-2026 23:59 UTC
    const date = new Date("2026-05-30T23:59:00Z");
    expect(formatDateWIB(date)).toBe("2026-05-31");
  });

  it("should format 07:00 WIB as 2026-05-31", () => {
    // 31-05-2026 07:00 WIB is 31-05-2026 00:00 UTC
    const date = new Date("2026-05-31T00:00:00Z");
    expect(formatDateWIB(date)).toBe("2026-05-31");
  });

  it("should format 23:59 WIB as 2026-05-31", () => {
    // 31-05-2026 23:59 WIB is 31-05-2026 16:59 UTC
    const date = new Date("2026-05-31T16:59:59Z");
    expect(formatDateWIB(date)).toBe("2026-05-31");
  });
});
