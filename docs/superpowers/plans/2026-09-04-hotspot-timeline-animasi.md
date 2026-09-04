# Timeline Animasi Hotspot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan pemutar (playback) waktu pada peta hotspot utama sehingga pengguna dapat memutar sebaran titik panas dari awal ke akhir jendela waktu terpilih (mode kumulatif dengan pudar berdasar umur).

**Architecture:** Murni client-side — memfilter/menata array `hotspots` yang sudah dimuat. Tiga unit baru: fungsi murni (`lib/hotspotTimeline.ts`), hook state+loop (`hooks/useHotspotTimeline.ts`), bar kontrol presentasional (`components/HotspotTimelineControl.tsx`). `HotspotMap.tsx` mengekstrak daftar marker ke child `React.memo` + daftar `ref` per marker; sebuah `useEffect` driver menata-ulang style marker secara imperatif tiap kali playhead maju, sehingga daftar marker TIDAK di-render ulang React selama animasi.

**Tech Stack:** React 18.3 + TypeScript 5.7, react-leaflet 4.2 / leaflet 1.9, Vitest 2.1 + @testing-library/react 16 (jsdom), lucide-react 1.16.

**Spec:** `docs/superpowers/specs/2026-09-04-hotspot-timeline-animasi-design.md`

## Global Constraints

- Semua berkas test berada di `frontend/src/test/**/*.test.ts(x)` (bukan co-located) — lihat `vitest.config`/`vite.config.ts` `test.include`.
- Verifikasi tiap task: `cd frontend && npm test` (vitest run) DAN `npm run build` (`tsc --noEmit && vite build`) harus hijau. Tidak ada ESLint di repo ini.
- Tidak ada perubahan backend. Tidak ada perubahan schema/API. Tidak ada test backend.
- Tidak menambah dependency npm baru.
- Register bahasa UI: Indonesia. Label waktu memakai zona `Asia/Jakarta` (WIB).
- Perilaku load-bearing `HotspotMap.tsx` yang TIDAK boleh berubah: `<Popup pane="popupPane">` di tiap popup hotspot; `fireCanvasRenderer` = SATU `canvas({ pane: "kps-interaktif", tolerance: 18 })` dibagi polygon bekas-terbakar + titik hotspot; `hotspotLayerGroupRef` + effect `bringToFront` pada `[hotspots, burnedArea.data]`; `PolygonInfoLayer` menerima prop `hotspots`.
- Konstanta timeline (nilai verbatim): `MAX_FRAMES = 120`, `FADE_BUCKETS = 6`, `OPACITY_FLOOR = 0.3`, `SPEED_STEPS = [1, 2, 4]`, `TICK_MS = 700`.
- Fitur hanya di peta utama (`HotspotMap.tsx`). TIDAK di `KpsDetailView.tsx`. State toggle tidak dipersist.

---

## Task 1: Fungsi murni `lib/hotspotTimeline.ts`

**Files:**
- Create: `frontend/src/lib/hotspotTimeline.ts`
- Test: `frontend/src/test/hotspotTimeline.test.ts`

**Interfaces:**
- Consumes: —
- Produces:
  - `type TimelineBucket = { index: number; start: number; end: number; count: number }`
  - `type TimelineBuckets = { bucketMs: number; buckets: TimelineBucket[] }`
  - `computeBuckets(hotspots: ReadonlyArray<{ detectedAt: string }>, filterWindow?: { start: number; end: number }): TimelineBuckets`
  - `opacityForBucket(playheadIndex: number, bucketIndex: number): number`
  - `bucketLabelWIB(ms: number, bucketMs: number): string`
  - `MAX_FRAMES`, `FADE_BUCKETS`, `OPACITY_FLOOR`, `TICK_MS: number`; `SPEED_STEPS: readonly [1, 2, 4]`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/hotspotTimeline.test.ts`:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/test/hotspotTimeline.test.ts`
Expected: FAIL — `Failed to resolve import "../lib/hotspotTimeline"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/lib/hotspotTimeline.ts`:

```ts
export type TimelineBucket = {
  index: number;
  start: number;
  end: number;
  count: number;
};

export type TimelineBuckets = {
  bucketMs: number;
  buckets: TimelineBucket[];
};

export const MAX_FRAMES = 120;
export const FADE_BUCKETS = 6;
export const OPACITY_FLOOR = 0.3;
export const TICK_MS = 700;
export const SPEED_STEPS = [1, 2, 4] as const;

const HOUR = 3_600_000;
const DAY = 86_400_000;

function baseBucketMs(spanMs: number): number {
  if (spanMs <= 48 * HOUR) return HOUR;
  if (spanMs <= 7 * DAY) return 3 * HOUR;
  return DAY;
}

export function computeBuckets(
  hotspots: ReadonlyArray<{ detectedAt: string }>,
  filterWindow?: { start: number; end: number },
): TimelineBuckets {
  const times: number[] = [];
  for (const h of hotspots) {
    const t = Date.parse(h.detectedAt);
    if (!Number.isNaN(t)) times.push(t);
  }
  if (times.length === 0) return { bucketMs: 0, buckets: [] };

  const minT = filterWindow ? filterWindow.start : Math.min(...times);
  const maxT = filterWindow ? filterWindow.end : Math.max(...times);
  const span = Math.max(maxT - minT, 1);

  let bucketMs = baseBucketMs(span);
  while (Math.floor(span / bucketMs) + 1 > MAX_FRAMES) bucketMs *= 2;

  const start0 = Math.floor(minT / bucketMs) * bucketMs;
  const nBuckets = Math.floor((maxT - start0) / bucketMs) + 1;

  const buckets: TimelineBucket[] = Array.from({ length: nBuckets }, (_, i) => ({
    index: i,
    start: start0 + i * bucketMs,
    end: start0 + (i + 1) * bucketMs,
    count: 0,
  }));

  for (const t of times) {
    const i = Math.min(Math.floor((t - start0) / bucketMs), nBuckets - 1);
    if (i >= 0) buckets[i].count += 1;
  }

  return { bucketMs, buckets };
}

export function opacityForBucket(
  playheadIndex: number,
  bucketIndex: number,
): number {
  if (bucketIndex > playheadIndex) return 0;
  if (bucketIndex === playheadIndex) return 1;
  const age = playheadIndex - bucketIndex;
  if (age > FADE_BUCKETS) return OPACITY_FLOOR;
  const top = 0.85;
  const raw = top - ((age - 1) / (FADE_BUCKETS - 1)) * (top - OPACITY_FLOOR);
  return Math.round(raw / 0.05) * 0.05;
}

const ID_MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
  "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
];

export function bucketLabelWIB(ms: number, bucketMs: number): string {
  const f = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const parts = f.formatToParts(new Date(ms));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const day = String(Number(get("day")));
  const mon = ID_MONTHS[Number(get("month")) - 1];
  const year = get("year");
  if (bucketMs >= DAY) return `${day} ${mon} ${year}`;
  return `${day} ${mon} ${year}, ${get("hour")}:${get("minute")} WIB`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/test/hotspotTimeline.test.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Full verify**

Run: `cd frontend && npm test && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/hotspotTimeline.ts frontend/src/test/hotspotTimeline.test.ts
git commit -m "feat(timeline): fungsi murni bucketing + opacity + label WIB"
```

---

## Task 2: Hook `hooks/useHotspotTimeline.ts`

**Files:**
- Create: `frontend/src/hooks/useHotspotTimeline.ts`
- Test: `frontend/src/test/useHotspotTimeline.test.tsx`

**Interfaces:**
- Consumes (Task 1): `computeBuckets`, `opacityForBucket`, `bucketLabelWIB`, `TICK_MS`, `SPEED_STEPS`, `TimelineBucket`.
- Produces:
  - `type HotspotTimeline = {`
    - `buckets: TimelineBucket[]; bucketMs: number;`
    - `playheadIndex: number; isPlaying: boolean; speed: number;`
    - `currentBucket: TimelineBucket | null; label: string;`
    - `bucketIndexById: Map<string, number>;`
    - `play(): void; pause(): void; toggle(): void; seek(index: number): void; cycleSpeed(): void;`
  - `}`
  - `useHotspotTimeline(hotspots: ReadonlyArray<{ id: string; detectedAt: string }>, opts: { enabled: boolean; filterWindow?: { start: number; end: number } }): HotspotTimeline`

Loop uses `window.setInterval(tick, TICK_MS / speed)` (bukan `requestAnimationFrame`) — animasi ini men-snap opacity per bucket per tick, jadi interval sudah cukup dan bisa dites dengan fake timers. Loop hanya hidup saat `enabled && isPlaying`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/useHotspotTimeline.test.tsx`:

```tsx
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
    const { result } = renderHook(() =>
      useHotspotTimeline(hs, { enabled: true }),
    );
    expect(result.current.isPlaying).toBe(false);
    expect(result.current.playheadIndex).toBe(
      result.current.buckets.length - 1,
    );
    expect(result.current.bucketIndexById.get("h0")).toBe(0);
  });

  it("play() from the end restarts at 0 then advances one bucket per tick", () => {
    const hs = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() =>
      useHotspotTimeline(hs, { enabled: true }),
    );
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
    const { result } = renderHook(() =>
      useHotspotTimeline(hs, { enabled: true }),
    );
    act(() => result.current.cycleSpeed()); // 1 -> 2
    expect(result.current.speed).toBe(2);
    act(() => result.current.play());
    act(() => vi.advanceTimersByTime(700));
    expect(result.current.playheadIndex).toBe(2);
  });

  it("stops when it reaches the last bucket", () => {
    const hs = makeHotspots(4, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() =>
      useHotspotTimeline(hs, { enabled: true }),
    );
    act(() => result.current.play());
    act(() => vi.advanceTimersByTime(700 * 20));
    expect(result.current.playheadIndex).toBe(
      result.current.buckets.length - 1,
    );
    expect(result.current.isPlaying).toBe(false);
  });

  it("seek() clamps and pauses", () => {
    const hs = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() =>
      useHotspotTimeline(hs, { enabled: true }),
    );
    act(() => result.current.play());
    act(() => result.current.seek(999));
    expect(result.current.playheadIndex).toBe(
      result.current.buckets.length - 1,
    );
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
    expect(result.current.playheadIndex).toBe(
      result.current.buckets.length - 1,
    );
    expect(result.current.isPlaying).toBe(false);
  });

  it("does not advance when disabled", () => {
    const hs = makeHotspots(10, "2026-08-01T00:00:00Z", 3_600_000);
    const { result } = renderHook(() =>
      useHotspotTimeline(hs, { enabled: false }),
    );
    act(() => result.current.play());
    act(() => vi.advanceTimersByTime(700 * 5));
    expect(result.current.playheadIndex).toBe(
      result.current.buckets.length - 1,
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/test/useHotspotTimeline.test.tsx`
Expected: FAIL — cannot resolve `../hooks/useHotspotTimeline`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/hooks/useHotspotTimeline.ts`:

```ts
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  computeBuckets,
  bucketLabelWIB,
  SPEED_STEPS,
  TICK_MS,
  type TimelineBucket,
} from "../lib/hotspotTimeline";

export type HotspotTimeline = {
  buckets: TimelineBucket[];
  bucketMs: number;
  playheadIndex: number;
  isPlaying: boolean;
  speed: number;
  currentBucket: TimelineBucket | null;
  label: string;
  bucketIndexById: Map<string, number>;
  play(): void;
  pause(): void;
  toggle(): void;
  seek(index: number): void;
  cycleSpeed(): void;
};

type Input = ReadonlyArray<{ id: string; detectedAt: string }>;

export function useHotspotTimeline(
  hotspots: Input,
  opts: { enabled: boolean; filterWindow?: { start: number; end: number } },
): HotspotTimeline {
  const { enabled, filterWindow } = opts;

  const { bucketMs, buckets } = useMemo(
    () => computeBuckets(hotspots, filterWindow),
    [hotspots, filterWindow],
  );

  const bucketIndexById = useMemo(() => {
    const map = new Map<string, number>();
    if (buckets.length === 0) return map;
    const start0 = buckets[0].start;
    for (const h of hotspots) {
      const t = Date.parse(h.detectedAt);
      if (Number.isNaN(t)) {
        map.set(h.id, 0);
        continue;
      }
      const i = Math.min(
        Math.max(Math.floor((t - start0) / bucketMs), 0),
        buckets.length - 1,
      );
      map.set(h.id, i);
    }
    return map;
  }, [hotspots, buckets, bucketMs]);

  const lastIndex = Math.max(buckets.length - 1, 0);
  const [playheadIndex, setPlayheadIndex] = useState(lastIndex);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(0);
  const speed = SPEED_STEPS[speedIdx];

  // Re-init whenever the bucket set identity changes (new data / new window).
  useEffect(() => {
    setPlayheadIndex(lastIndex);
    setIsPlaying(false);
  }, [buckets, lastIndex]);

  useEffect(() => {
    if (!enabled || !isPlaying) return;
    const id = window.setInterval(() => {
      setPlayheadIndex((cur) => {
        if (cur >= lastIndex) {
          setIsPlaying(false);
          return lastIndex;
        }
        return cur + 1;
      });
    }, TICK_MS / speed);
    return () => window.clearInterval(id);
  }, [enabled, isPlaying, speed, lastIndex]);

  const play = useCallback(() => {
    setPlayheadIndex((cur) => (cur >= lastIndex ? 0 : cur));
    setIsPlaying(true);
  }, [lastIndex]);
  const pause = useCallback(() => setIsPlaying(false), []);
  const toggle = useCallback(() => {
    setIsPlaying((p) => {
      if (!p) setPlayheadIndex((cur) => (cur >= lastIndex ? 0 : cur));
      return !p;
    });
  }, [lastIndex]);
  const seek = useCallback(
    (index: number) => {
      setIsPlaying(false);
      setPlayheadIndex(Math.min(Math.max(Math.round(index), 0), lastIndex));
    },
    [lastIndex],
  );
  const cycleSpeed = useCallback(
    () => setSpeedIdx((i) => (i + 1) % SPEED_STEPS.length),
    [],
  );

  const currentBucket = buckets[playheadIndex] ?? null;
  const label = currentBucket
    ? bucketLabelWIB(currentBucket.start, bucketMs)
    : "";

  return {
    buckets,
    bucketMs,
    playheadIndex,
    isPlaying,
    speed,
    currentBucket,
    label,
    bucketIndexById,
    play,
    pause,
    toggle,
    seek,
    cycleSpeed,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/test/useHotspotTimeline.test.tsx`
Expected: PASS.

Note: `toggle()` in the "2x speed" test path is not used; `play()` is. If the "stops when it reaches the last bucket" test flakes because a final `setIsPlaying(false)` lands in a later tick, add one extra `act(() => vi.advanceTimersByTime(700))` — the interval callback sets `isPlaying` false on the tick that hits `lastIndex`.

- [ ] **Step 5: Full verify**

Run: `cd frontend && npm test && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useHotspotTimeline.ts frontend/src/test/useHotspotTimeline.test.tsx
git commit -m "feat(timeline): hook state + loop pemutar (setInterval, re-init on data change)"
```

---

## Task 3: Bar kontrol `components/HotspotTimelineControl.tsx`

**Files:**
- Create: `frontend/src/components/HotspotTimelineControl.tsx`
- Modify: `frontend/src/index.css` (tambah blok `.timeline-control*` di akhir file)
- Test: `frontend/src/test/HotspotTimelineControl.test.tsx`

**Interfaces:**
- Consumes (Task 2): `HotspotTimeline` shape (`buckets`, `playheadIndex`, `isPlaying`, `speed`, `label`, `play`, `pause`, `toggle`, `seek`, `cycleSpeed`).
- Produces: `export function HotspotTimelineControl(props: HotspotTimelineControlProps)` where
  `type HotspotTimelineControlProps = Pick<HotspotTimeline, "buckets" | "playheadIndex" | "isPlaying" | "speed" | "label" | "toggle" | "seek" | "cycleSpeed"> & { onClose(): void }`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/test/HotspotTimelineControl.test.tsx`:

```tsx
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HotspotTimelineControl } from "../components/HotspotTimelineControl";

afterEach(cleanup);

const buckets = [
  { index: 0, start: 0, end: 1, count: 5 },
  { index: 1, start: 1, end: 2, count: 2 },
  { index: 2, start: 2, end: 3, count: 8 },
];

function setup(overrides: Partial<Parameters<typeof HotspotTimelineControl>[0]> = {}) {
  const props = {
    buckets,
    playheadIndex: 1,
    isPlaying: false,
    speed: 1,
    label: "8 Agu 2026, 01:00 WIB",
    toggle: vi.fn(),
    seek: vi.fn(),
    cycleSpeed: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<HotspotTimelineControl {...props} />);
  return props;
}

describe("HotspotTimelineControl", () => {
  it("renders one histogram bar per bucket", () => {
    setup();
    expect(screen.getAllByTestId("timeline-bar")).toHaveLength(3);
  });

  it("shows the running time label", () => {
    setup();
    expect(screen.getByText("8 Agu 2026, 01:00 WIB")).toBeInTheDocument();
  });

  it("calls toggle when the play/pause button is clicked", () => {
    const p = setup();
    fireEvent.click(screen.getByRole("button", { name: /putar|jeda/i }));
    expect(p.toggle).toHaveBeenCalledTimes(1);
  });

  it("exposes an accessible slider bound to the bucket range", () => {
    setup({ playheadIndex: 2 });
    const slider = screen.getByRole("slider");
    expect(slider).toHaveAttribute("aria-valuemin", "0");
    expect(slider).toHaveAttribute("aria-valuemax", "2");
    expect(slider).toHaveAttribute("aria-valuenow", "2");
  });

  it("calls seek when the slider changes", () => {
    const p = setup();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "2" } });
    expect(p.seek).toHaveBeenCalledWith(2);
  });

  it("shows the speed and cycles it on click", () => {
    const p = setup({ speed: 2 });
    fireEvent.click(screen.getByRole("button", { name: "2×" }));
    expect(p.cycleSpeed).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/test/HotspotTimelineControl.test.tsx`
Expected: FAIL — cannot resolve `../components/HotspotTimelineControl`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/HotspotTimelineControl.tsx`:

```tsx
import { Pause, Play } from "lucide-react";
import type { HotspotTimeline } from "../hooks/useHotspotTimeline";

export type HotspotTimelineControlProps = Pick<
  HotspotTimeline,
  | "buckets"
  | "playheadIndex"
  | "isPlaying"
  | "speed"
  | "label"
  | "toggle"
  | "seek"
  | "cycleSpeed"
> & { onClose(): void };

export function HotspotTimelineControl({
  buckets,
  playheadIndex,
  isPlaying,
  speed,
  label,
  toggle,
  seek,
  cycleSpeed,
  onClose,
}: HotspotTimelineControlProps) {
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));
  const lastIndex = Math.max(buckets.length - 1, 0);

  return (
    <div className="timeline-control" role="group" aria-label="Pemutar waktu hotspot">
      <button
        type="button"
        className="timeline-control__play"
        onClick={toggle}
        aria-label={isPlaying ? "Jeda animasi" : "Putar animasi"}
      >
        {isPlaying ? <Pause size={16} /> : <Play size={16} />}
      </button>

      <div className="timeline-control__scrub">
        <div className="timeline-control__hist" aria-hidden="true">
          {buckets.map((b) => (
            <span
              key={b.index}
              data-testid="timeline-bar"
              className={
                "timeline-control__bar" +
                (b.index <= playheadIndex ? " timeline-control__bar--past" : "")
              }
              style={{ height: `${Math.round((b.count / maxCount) * 100)}%` }}
            />
          ))}
        </div>
        <input
          type="range"
          className="timeline-control__range"
          min={0}
          max={lastIndex}
          step={1}
          value={playheadIndex}
          aria-label="Posisi waktu"
          aria-valuemin={0}
          aria-valuemax={lastIndex}
          aria-valuenow={playheadIndex}
          onChange={(e) => seek(Number(e.target.value))}
        />
      </div>

      <span className="timeline-control__label">{label}</span>

      <button
        type="button"
        className="timeline-control__speed"
        onClick={cycleSpeed}
        aria-label={`Kecepatan ${speed} kali`}
      >
        {speed}×
      </button>

      <button
        type="button"
        className="timeline-control__close"
        onClick={onClose}
        aria-label="Tutup pemutar waktu"
      >
        ×
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Add CSS**

Append to `frontend/src/index.css` (end of file). Mirror the existing floating-control look (`.map-legend`, `.burned-toggle`).

```css
/* ---- Pemutar waktu hotspot (timeline animasi) ---- */
.timeline-control {
  position: absolute;
  left: 50%;
  bottom: 1.25rem;
  transform: translateX(-50%);
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  width: min(680px, calc(100% - 2rem));
  padding: 0.5rem 0.7rem;
  border-radius: 0.6rem;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(19, 21, 26, 0.96);
  color: #f5efe6;
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.timeline-control__play,
.timeline-control__speed,
.timeline-control__close {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  min-width: 30px;
  padding: 0 0.5rem;
  border-radius: 0.45rem;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(12, 13, 17, 0.9);
  color: #f5efe6;
  font: inherit;
  font-size: 0.75rem;
  font-weight: 700;
  cursor: pointer;
}
.timeline-control__close {
  border: none;
  background: transparent;
  font-size: 1rem;
  color: rgba(245, 239, 230, 0.6);
}
.timeline-control__scrub {
  position: relative;
  flex: 1 1 auto;
  height: 34px;
}
.timeline-control__hist {
  position: absolute;
  inset: 0 0 6px 0;
  display: flex;
  align-items: flex-end;
  gap: 1px;
}
.timeline-control__bar {
  flex: 1 1 0;
  min-height: 2px;
  background: rgba(245, 239, 230, 0.18);
  border-radius: 1px 1px 0 0;
  transition: background 120ms ease;
}
.timeline-control__bar--past {
  background: #ff8c42;
}
.timeline-control__range {
  position: absolute;
  left: 0;
  right: 0;
  bottom: -2px;
  width: 100%;
  margin: 0;
  accent-color: #ff8c42;
  cursor: pointer;
}
.timeline-control__label {
  flex: none;
  min-width: 8.5rem;
  text-align: right;
  font-size: 0.72rem;
  font-variant-numeric: tabular-nums;
  color: rgba(245, 239, 230, 0.85);
}
@media (prefers-reduced-motion: reduce) {
  .timeline-control__bar {
    transition: none;
  }
}
@media (max-width: 640px) {
  .timeline-control {
    bottom: 5.5rem;
    gap: 0.4rem;
    flex-wrap: wrap;
  }
  .timeline-control__label {
    order: 5;
    width: 100%;
    text-align: center;
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/test/HotspotTimelineControl.test.tsx`
Expected: PASS.

- [ ] **Step 6: Full verify**

Run: `cd frontend && npm test && npm run build`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HotspotTimelineControl.tsx frontend/src/test/HotspotTimelineControl.test.tsx frontend/src/index.css
git commit -m "feat(timeline): bar kontrol melayang + histogram-scrubber"
```

---

## Task 4: Wiring ke `HotspotMap.tsx` (+ `App.tsx`, mock test)

**Files:**
- Modify: `frontend/src/components/HotspotMap.tsx`
- Modify: `frontend/src/App.tsx` (bungkus `openKpsDetail` dengan `useCallback`)
- Modify: `frontend/src/test/HotspotMap.test.tsx` (mock `CircleMarker`/`Marker` jadi `forwardRef`; assert tombol "Timeline")

**Interfaces:**
- Consumes (Task 2): `useHotspotTimeline`, `HotspotTimeline`.
- Consumes (Task 1): `opacityForBucket`.
- Consumes (Task 3): `HotspotTimelineControl`.
- Produces: —

### Perubahan `HotspotMap.tsx`

1. **Import.**

```tsx
import { forwardRef, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CircleMarker as LCircleMarker, Marker as LMarker } from "leaflet";
import { Clock } from "lucide-react";
import { useHotspotTimeline } from "../hooks/useHotspotTimeline";
import { opacityForBucket } from "../lib/hotspotTimeline";
import { HotspotTimelineControl } from "./HotspotTimelineControl";
```

2. **Ekstrak daftar marker ke child `React.memo`.** Cari blok JSX `<LayerGroup ref={hotspotLayerGroupRef}>{hotspots.map((hotspot) => …)}</LayerGroup>` (sekitar baris 917–948). Pindahkan `hotspots.map(...)` **apa adanya** ke komponen internal berikut, DI DALAM `HotspotMap.tsx` (di atas `export function HotspotMap`). JSX per-item (kondisi `frp > HIGH_FRP_THRESHOLD`, `<Marker>`, `<CircleMarker>`, `<Popup pane="popupPane">`, `HotspotPopupContent`, `getHighIntensityIcon`, `sourceColor`, `fireCanvasRenderer`, `radius={7}`, `pathOptions`) TIDAK berubah — hanya ditambah `ref`.

```tsx
type MarkersLayerProps = {
  hotspots: HotspotRecord[];
  renderer: ReturnType<typeof canvas>;
  onOpenKpsDetail?: (agency: string) => void;
  registerMarker: (id: string, layer: LCircleMarker | LMarker | null) => void;
};

const HotspotMarkersLayer = memo(function HotspotMarkersLayer({
  hotspots,
  renderer,
  onOpenKpsDetail,
  registerMarker,
}: MarkersLayerProps) {
  return (
    <>
      {hotspots.map((hotspot) =>
        (hotspot.frp ?? 0) > HIGH_FRP_THRESHOLD ? (
          <Marker
            key={hotspot.id}
            position={[hotspot.latitude, hotspot.longitude]}
            icon={getHighIntensityIcon(sourceColor(hotspot.source))}
            ref={(l) => registerMarker(hotspot.id, (l as unknown as LMarker) ?? null)}
          >
            <Popup pane="popupPane">
              <HotspotPopupContent hotspot={hotspot} onOpenKpsDetail={onOpenKpsDetail} />
            </Popup>
          </Marker>
        ) : (
          <CircleMarker
            key={hotspot.id}
            center={[hotspot.latitude, hotspot.longitude]}
            radius={7}
            renderer={renderer}
            ref={(l) => registerMarker(hotspot.id, (l as unknown as LCircleMarker) ?? null)}
            pathOptions={{
              color: "#1b120d",
              weight: 2,
              fillColor: sourceColor(hotspot.source),
              fillOpacity: 0.98,
            }}
          >
            <Popup pane="popupPane">
              <HotspotPopupContent hotspot={hotspot} onOpenKpsDetail={onOpenKpsDetail} />
            </Popup>
          </CircleMarker>
        ),
      )}
    </>
  );
});
```

Ganti isi `<LayerGroup ref={hotspotLayerGroupRef}>` menjadi:

```tsx
<LayerGroup ref={hotspotLayerGroupRef}>
  <HotspotMarkersLayer
    hotspots={hotspots}
    renderer={fireCanvasRenderer}
    onOpenKpsDetail={onOpenKpsDetail}
    registerMarker={registerMarker}
  />
</LayerGroup>
```

3. **Ref registry + timeline state** (di dalam `HotspotMap`, dekat `hotspotLayerGroupRef`):

```tsx
const markerRefs = useRef(new Map<string, LCircleMarker | LMarker>());
const registerMarker = useCallback(
  (id: string, layer: LCircleMarker | LMarker | null) => {
    if (layer) markerRefs.current.set(id, layer);
    else markerRefs.current.delete(id);
  },
  [],
);

const [timelineOn, setTimelineOn] = useState(false);
const timelineEnabled = timelineOn && hotspots.length > 0;
const timeline = useHotspotTimeline(hotspots, { enabled: timelineEnabled });
```

4. **Driver: restyle marker imperatif.** Full sweep tiap kali `playheadIndex` / `timelineOn` berubah. (Optimasi delta-range disebut di spec §8 sebagai lanjutan bila profiling menunjukkan jank — tidak diperlukan untuk ≤ 6.000 marker.)

```tsx
useEffect(() => {
  const map = markerRefs.current;
  if (!timelineOn) {
    // kembalikan ke tampilan penuh
    map.forEach((layer) => {
      if (typeof (layer as LCircleMarker).setStyle === "function") {
        (layer as LCircleMarker).setStyle({ fillOpacity: 0.98, opacity: 1 });
        (layer as LCircleMarker).options.interactive = true;
      } else if (typeof (layer as LMarker).setOpacity === "function") {
        (layer as LMarker).setOpacity(1);
      }
    });
    return;
  }
  map.forEach((layer, id) => {
    const b = timeline.bucketIndexById.get(id) ?? 0;
    const o = opacityForBucket(timeline.playheadIndex, b);
    if (typeof (layer as LCircleMarker).setStyle === "function") {
      (layer as LCircleMarker).setStyle({
        fillOpacity: o === 0 ? 0 : o * 0.98,
        opacity: o === 0 ? 0 : 1,
      });
      (layer as LCircleMarker).options.interactive = o > 0;
    } else if (typeof (layer as LMarker).setOpacity === "function") {
      (layer as LMarker).setOpacity(o === 0 ? 0 : 1);
    }
  });
}, [timelineOn, timeline.playheadIndex, timeline.bucketIndexById]);
```

5. **Tombol toggle "Timeline".** Di dalam `<div className="burned-control">` `overlay-group`, tambah tombol bergaya `burned-toggle` (deret yang sama dengan "Bekas Terbakar" / "Fungsi Kawasan Hutan"):

```tsx
<button
  type="button"
  className={`burned-toggle${timelineOn ? " burned-toggle--active" : ""}`}
  onClick={() => setTimelineOn((v) => !v)}
  disabled={hotspots.length === 0}
>
  <Clock size={15} />
  Timeline
</button>
```

6. **Render bar kontrol** (di dalam `<div className="map-frame">`, setelah `<MapContainer>` — bar bukan child peta):

```tsx
{timelineEnabled && timeline.buckets.length > 0 ? (
  <HotspotTimelineControl
    buckets={timeline.buckets}
    playheadIndex={timeline.playheadIndex}
    isPlaying={timeline.isPlaying}
    speed={timeline.speed}
    label={timeline.label}
    toggle={timeline.toggle}
    seek={timeline.seek}
    cycleSpeed={timeline.cycleSpeed}
    onClose={() => setTimelineOn(false)}
  />
) : null}
```

### Perubahan `App.tsx`

Bungkus `openKpsDetail` (sekitar baris 290) dengan `useCallback` agar `HotspotMarkersLayer` yang di-`memo` tidak ikut re-render saat state App lain berubah:

```tsx
const openKpsDetail = useCallback((agency: string) => {
  setKpsAgency(agency);
  setActiveView("kps");
  const params = new URLSearchParams(window.location.search);
  params.set("view", "kps");
  params.set("kps", agency);
  window.history.pushState({}, "", `?${params.toString()}`);
  // ...sisa isi fungsi TIDAK berubah...
}, []);
```

Pastikan `useCallback` sudah ter-import di `App.tsx` (kalau belum, tambah ke import `react`).

### Perubahan `frontend/src/test/HotspotMap.test.tsx`

Mock `react-leaflet` saat ini merender `CircleMarker`/`Marker` sebagai function component biasa. Karena kini menerima `ref`, ubah keduanya jadi `forwardRef` supaya React tidak memuntahkan warning dan `ref` di-abaikan dengan aman:

```tsx
import { forwardRef } from "react";
// di dalam vi.mock("react-leaflet", () => ({ ... }))
CircleMarker: forwardRef(({ children, ...props }: { children?: ReactNode }, _ref) => {
  circleMarkerPropsMock(props);
  return <div>{children}</div>;
}),
Marker: forwardRef(({ children }: { children?: ReactNode }, _ref) => <div>{children}</div>),
```

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/test/HotspotMap.test.tsx` (dalam `describe` yang sudah ada, gaya `loginThroughUI` seperti test lain di file itu):

```tsx
it("shows a Timeline toggle on the map", async () => {
  renderApp(); // helper yang sudah dipakai test lain di file ini
  await loginThroughUI();
  await screen.findByTestId("leaflet-map");
  expect(
    await screen.findByRole("button", { name: /timeline/i }),
  ).toBeInTheDocument();
});
```

(Jika file belum punya helper `renderApp`, pakai pola persis test terdekat di file yang sama — `render(<App />)` lalu `loginThroughUI()`.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/test/HotspotMap.test.tsx`
Expected: FAIL — tombol "Timeline" belum ada.

- [ ] **Step 3: Implement**

Terapkan semua perubahan `HotspotMap.tsx`, `App.tsx`, dan mock `HotspotMap.test.tsx` di atas.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/test/HotspotMap.test.tsx`
Expected: PASS (test baru + semua test lama di file — khususnya yang memakai `circleMarkerPropsMock`).

- [ ] **Step 5: Full verify**

Run: `cd frontend && npm test && npm run build`
Expected: PASS semua.

- [ ] **Step 6: Manual smoke test**

```
cd frontend && npm run dev
```
Di browser (login), pada peta utama:
1. Pilih preset "7 Hari", tunggu titik muncul. Klik tombol **Timeline** (deret kiri-atas). Bar muncul di bawah-tengah, playhead di ujung kanan, semua titik tampil, keadaan jeda.
2. Klik **Putar** → playhead lompat ke kiri, titik menumpuk dari sedikit ke banyak; titik lama meredup jadi "hantu", bucket aktif menyala. Animasi mulus (tak patah-patah).
3. Klik **2×** lalu **4×** → jelas lebih cepat. Berhenti sendiri di ujung kanan.
4. Tarik playhead di histogram → titik ikut, animasi jeda.
5. Saat memutar, klik sebuah titik → popup terbuka, tombol di dalamnya (Detail KPS) tetap berfungsi.
6. Ganti preset ke "30 Hari" → bar re-init (jeda di ujung), granularitas jadi harian.
7. Matikan **Timeline** → semua titik kembali penuh & bisa diklik seperti semula.
8. Uji di viewport HP (dev tools) → bar tetap terbaca (wrap), tidak menutupi zoom/legenda sepenuhnya.

Catat hasil tiap poin. Jika (2) patah-patah pada dataset besar (preset 30 hari, ribuan titik), terapkan optimasi delta-range: simpan `lastPlayheadRef`, dan di driver hanya sentuh marker dengan `bucketIndex` dalam `[min(last,cur) - FADE_BUCKETS, max(last,cur)]`.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HotspotMap.tsx frontend/src/App.tsx frontend/src/test/HotspotMap.test.tsx
git commit -m "feat(timeline): pasang pemutar waktu di HotspotMap (toggle + driver imperatif)"
```

---

## Task 5: Perbarui CLAUDE.md

**Files:**
- Modify: `frontend`-related bagian di `/home/ryandshinevps/etaseneu/CLAUDE.md`

**Interfaces:** Consumes: —  Produces: —

Repo ini punya aturan menjaga `CLAUDE.md` tetap mutakhir. Fitur ini menambah subsistem di `HotspotMap.tsx` yang perlu dicatat.

- [ ] **Step 1: Sunting CLAUDE.md**

Pada blok `components/ HotspotMap.tsx` (bagian Frontend), tambahkan kalimat:

> Pemutar waktu ("Timeline", toggle default mati): `useHotspotTimeline` (`hooks/`) + `lib/hotspotTimeline.ts` (fungsi murni: bucketing granularitas otomatis, `opacityForBucket`, label WIB) menggerakkan animasi kumulatif-berpudar. Daftar marker diekstrak ke `HotspotMarkersLayer` (`React.memo`); playback TIDAK me-render ulang list — sebuah `useEffect` driver menata style tiap marker lewat `markerRefs` (`Map<id, L.CircleMarker|L.Marker>`). Bar kontrol `HotspotTimelineControl` melayang di bawah-tengah peta (histogram-scrubber + play + kecepatan 1/2/4×). Murni client-side atas `hotspots` yang sudah dimuat; tak ada endpoint/persist. `openKpsDetail` di `App.tsx` di-`useCallback` demi `memo` ini.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE): catat subsistem timeline animasi hotspot"
```

---

## Self-Review

**1. Spec coverage:**
- Spec §1 mode kumulatif-berpudar → Task 1 `opacityForBucket` + Task 4 driver. Mode jendela-geser sengaja tidak ada (non-tujuan v1). ✓
- §3.1 berkas baru (`lib/`, `hooks/`, `components/`) → Task 1/2/3. ✓
- §3.2 ekstrak `HotspotMarkersLayer` memo + callback-ref + toggle + mount control + driver → Task 4. ✓
- §3.3 `computeBuckets`/`opacityForBucket`/`bucketLabelWIB` + konstanta → Task 1 (nilai `OPACITY_FLOOR` diselaraskan ke 0.3 agar kuantisasi 0.05 bersih; dicatat di Global Constraints & spec). ✓
- §3.4 hook (buckets memo, re-init on data change, setInterval loop, aksi, `bucketIndexById`) → Task 2. Spec menyebut `requestAnimationFrame`; plan memakai `setInterval` dengan alasan tertulis (snap per-bucket + testabilitas) — perubahan detail dalam pendekatan yang sama. ✓
- §3.5 bar kontrol (play/pause, histogram-scrubber, label WIB, tombol kecepatan, input range a11y, `prefers-reduced-motion`) → Task 3. ✓
- §4 alur data (memo dilewati saat animasi; `openKpsDetail` `useCallback`) → Task 4. ✓
- §5 kasus tepi: kosong→toggle disabled (Task 4 step 5); `detectedAt` invalid→bucket 0 (Task 1 test + Task 2 `bucketIndexById`); toggle off→restore sweep (Task 4 driver); data berubah saat play→re-init (Task 2 test); klik titik saat play→popup (Task 4 manual step 5); `<Marker>` FRP tinggi→opacity biner (Task 4 driver). ✓
- §6 pengujian → test di tiap task + Task 4 manual smoke. ✓
- §7 risiko (regresi load-bearing, memo tak efektif, kebocoran ref) → mitigasi di Task 4 (pindah JSX identik, `useCallback` handler & registrar, callback-ref hapus saat null). ✓

**2. Placeholder scan:** Tidak ada "TBD/TODO/handle edge cases" tanpa kode. Semua step kode berisi blok kode utuh. Task 4 step 1 menyebut "pola persis test terdekat" karena struktur helper file itu tak dikutip penuh — pelaksana membaca file itu; dapat diterima.

**3. Type consistency:**
- `computeBuckets` → `{ bucketMs, buckets }` dipakai konsisten di Task 2 (`const { bucketMs, buckets } = useMemo(...)`).
- `opacityForBucket(playheadIndex, bucketIndex)` urutan argumen sama di Task 1 (definisi + test) dan Task 4 (driver).
- `HotspotTimeline` field names (`playheadIndex`, `bucketIndexById`, `toggle`, `seek`, `cycleSpeed`, `label`, `isPlaying`, `speed`, `buckets`) identik di Task 2 (produce), Task 3 (`Pick<...>`), Task 4 (konsumsi).
- `registerMarker(id, layer|null)` signature sama di Task 4 (definisi `useCallback` + prop `MarkersLayerProps` + pemakaian `ref={(l) => registerMarker(...)}`).
- `HotspotTimelineControlProps` = `Pick<HotspotTimeline, ...> & { onClose }` — `onClose` diberikan di Task 4 render, dipakai di Task 3 tombol close & test.

Tidak ada ketidakcocokan ditemukan.
