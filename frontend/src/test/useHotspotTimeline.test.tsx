import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useHotspotTimeline } from "../hooks/useHotspotTimeline";

function makeHotspots(n: number, startIso: string, stepMs: number) {
  const t0 = Date.parse(startIso);
  return Array.from({ length: n }, (_, i) => ({
    id: `h${i}`,
    detectedAt: new Date(t0 + i * stepMs).toISOString(),
  }));
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useHotspotTimeline", () => {
  it("starts paused at the last bucket (everything visible)", () => {
    const hs = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() => useHotspotTimeline(hs, { enabled: true }));
    expect(result.current.isPlaying).toBe(false);
    expect(result.current.playheadIndex).toBe(result.current.buckets.length - 1);
    expect(result.current.bucketIndexById.get("h0")).toBe(0);
  });

  it("play() from the end restarts at 0 then advances one bucket per tick", () => {
    const hs = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() => useHotspotTimeline(hs, { enabled: true }));
    act(() => result.current.play());
    expect(result.current.playheadIndex).toBe(0);
    expect(result.current.isPlaying).toBe(true);
    act(() => vi.advanceTimersByTime(700));
    expect(result.current.playheadIndex).toBe(1);
    act(() => vi.advanceTimersByTime(700 * 3));
    expect(result.current.playheadIndex).toBe(4);
  });

  it("2x speed advances twice as fast", () => {
    const hs = makeHotspots(20, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() => useHotspotTimeline(hs, { enabled: true }));
    act(() => result.current.cycleSpeed()); // 1 -> 2
    expect(result.current.speed).toBe(2);
    act(() => result.current.play());
    act(() => vi.advanceTimersByTime(700));
    expect(result.current.playheadIndex).toBe(2);
  });

  it("stops when it reaches the last bucket", () => {
    const hs = makeHotspots(4, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() => useHotspotTimeline(hs, { enabled: true }));
    act(() => result.current.play());
    act(() => vi.advanceTimersByTime(700 * 20));
    expect(result.current.playheadIndex).toBe(result.current.buckets.length - 1);
    expect(result.current.isPlaying).toBe(false);
  });

  it("seek() clamps and pauses", () => {
    const hs = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() => useHotspotTimeline(hs, { enabled: true }));
    act(() => result.current.play());
    act(() => result.current.seek(999));
    expect(result.current.playheadIndex).toBe(result.current.buckets.length - 1);
    expect(result.current.isPlaying).toBe(false);
  });

  it("re-inits to the end (paused) when hotspots change", () => {
    const a = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const b = makeHotspots(4, "2026-08-01T00:00:00Z", 3_600_000);
    const { result, rerender } = renderHook(
      ({ hs }) => useHotspotTimeline(hs, { enabled: true }),
      { initialProps: { hs: a } },
    );
    act(() => result.current.play());
    rerender({ hs: b });
    expect(result.current.playheadIndex).toBe(result.current.buckets.length - 1);
    expect(result.current.isPlaying).toBe(false);
  });

  it("does not advance when disabled", () => {
    const hs = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() => useHotspotTimeline(hs, { enabled: false }));
    act(() => result.current.play());
    act(() => vi.advanceTimersByTime(700 * 5));
    expect(result.current.playheadIndex).toBe(0);
  });
});
