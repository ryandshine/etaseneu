import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  bucketLabelWIB,
  computeBuckets,
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

/**
 * State + loop pemutar waktu hotspot. Murni client-side atas `hotspots`
 * yang sudah dimuat. Loop pakai `setInterval` (bukan rAF): opacity di-snap
 * per bucket per tick, jadi interval cukup dan bisa diuji dengan fake timer.
 * Loop hanya hidup saat `enabled && isPlaying`.
 */
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

  // Re-init (jeda di ujung = semua titik tampil) tiap set bucket berganti
  // identitas: data baru / jendela waktu baru. Skip render pertama supaya
  // tidak ada setState ganda saat mount.
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
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

  // Berhenti otomatis begitu playhead menyentuh ujung (tick terakhir sudah
  // menaikkan ke lastIndex; tick berikutnya yang mematikan -- di sini kita
  // matikan lebih awal supaya tombol langsung berubah jadi "Putar").
  useEffect(() => {
    if (isPlaying && playheadIndex >= lastIndex && lastIndex > 0) {
      setIsPlaying(false);
    }
  }, [isPlaying, playheadIndex, lastIndex]);

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
  const label = currentBucket ? bucketLabelWIB(currentBucket.start, bucketMs) : "";

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
