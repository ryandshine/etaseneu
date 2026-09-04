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
  return Math.round(raw * 20) / 20;
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
