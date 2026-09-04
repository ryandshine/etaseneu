import { describe, expect, it } from "vitest";
import {
  computeBuckets,
  opacityForBucket,
  bucketLabelWIB,
  MAX_FRAMES,
  OPACITY_FLOOR,
} from "../lib/hotspotTimeline";

const iso = (s: string) => ({ detectedAt: s });

describe("computeBuckets", () => {
  it("uses 1-hour buckets when span <= 48h and counts per bucket", () => {
    const { bucketMs, buckets } = computeBuckets([
      iso("2026-08-01T00:30:00Z"),
      iso("2026-08-01T10:15:00Z"),
      iso("2026-08-02T11:45:00Z"),
    ]);
    expect(bucketMs).toBe(3_600_000);
    expect(buckets.length).toBe(36);
    expect(buckets[0].count).toBe(1);
    expect(buckets[10].count).toBe(1);
    expect(buckets[35].count).toBe(1);
    expect(buckets.reduce((s, b) => s + b.count, 0)).toBe(3);
    expect(buckets[0].index).toBe(0);
    expect(buckets[1].start).toBe(buckets[0].end);
  });

  it("uses 3-hour buckets when span <= 7 days", () => {
    const { bucketMs, buckets } = computeBuckets([
      iso("2026-08-01T00:00:00Z"),
      iso("2026-08-05T23:59:00Z"),
    ]);
    expect(bucketMs).toBe(3 * 3_600_000);
    expect(buckets.length).toBe(40);
  });

  it("uses 1-day buckets when span > 7 days", () => {
    const { bucketMs, buckets } = computeBuckets([
      iso("2026-08-01T00:00:00Z"),
      iso("2026-08-20T23:59:00Z"),
    ]);
    expect(bucketMs).toBe(86_400_000);
    expect(buckets.length).toBe(20);
  });

  it("widens bucket size so frame count never exceeds MAX_FRAMES", () => {
    const { bucketMs, buckets } = computeBuckets([
      iso("2025-01-01T00:00:00Z"),
      iso("2026-02-05T00:00:00Z"),
    ]);
    expect(buckets.length).toBeLessThanOrEqual(MAX_FRAMES);
    expect(bucketMs).toBe(4 * 86_400_000);
  });

  it("ignores hotspots with an unparseable detectedAt", () => {
    const { buckets } = computeBuckets([
      iso("not-a-date"),
      iso("2026-08-01T00:00:00Z"),
    ]);
    expect(buckets.length).toBe(1);
    expect(buckets[0].count).toBe(1);
  });

  it("returns no buckets for empty input", () => {
    expect(computeBuckets([])).toEqual({ bucketMs: 0, buckets: [] });
  });
});

describe("opacityForBucket", () => {
  it("hides future buckets", () => {
    expect(opacityForBucket(10, 12)).toBe(0);
  });
  it("full opacity at the playhead bucket", () => {
    expect(opacityForBucket(10, 10)).toBe(1);
  });
  it("ramps down over FADE_BUCKETS then holds at the floor", () => {
    expect(opacityForBucket(10, 9)).toBe(0.85);
    expect(opacityForBucket(10, 8)).toBe(0.75);
    expect(opacityForBucket(10, 7)).toBe(0.65);
    expect(opacityForBucket(10, 6)).toBe(0.5);
    expect(opacityForBucket(10, 5)).toBe(0.4);
    expect(opacityForBucket(10, 4)).toBe(OPACITY_FLOOR);
    expect(opacityForBucket(10, 2)).toBe(OPACITY_FLOOR);
  });
});

describe("bucketLabelWIB", () => {
  it("includes the WIB clock time for sub-daily buckets", () => {
    // 2026-08-08T06:00:00Z === 13:00 WIB
    expect(bucketLabelWIB(Date.parse("2026-08-08T06:00:00Z"), 3_600_000)).toBe(
      "8 Agu 2026, 13:00 WIB",
    );
  });
  it("omits the clock time for daily buckets", () => {
    expect(bucketLabelWIB(Date.parse("2026-08-08T02:00:00Z"), 86_400_000)).toBe(
      "8 Agu 2026",
    );
  });
});
