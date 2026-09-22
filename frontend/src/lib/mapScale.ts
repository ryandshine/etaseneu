/**
 * Kalkulasi skala rasio kartografi ("1:250.000") dari resolusi peta Web
 * Mercator, dipisah dari MapScaleRatio.tsx (komponen) supaya bisa diuji
 * tanpa Leaflet -- lihat komentar lengkap di komponen itu.
 */

const EARTH_CIRCUMFERENCE_M = 40075016.686; // WGS84, dasar tile Web Mercator
const OGC_PIXEL_SIZE_M = 0.00028; // 0,28 mm -- "standardized rendering pixel size" OGC
const NICE_STEPS = [1, 2, 2.5, 5, 10];

export function metersPerPixel(zoom: number, latDeg: number): number {
  return (
    (EARTH_CIRCUMFERENCE_M * Math.cos((latDeg * Math.PI) / 180)) / Math.pow(2, zoom + 8)
  );
}

/** Bulatkan ke deret "rapi" 1-2-2,5-5-10 x 10^n, gaya skala peta cetak. */
export function niceScaleDenominator(raw: number): number {
  if (!Number.isFinite(raw) || raw <= 0) return 0;
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalized = raw / magnitude;
  let best = NICE_STEPS[0];
  let bestDiff = Infinity;
  for (const step of NICE_STEPS) {
    const diff = Math.abs(normalized - step);
    if (diff < bestDiff) {
      bestDiff = diff;
      best = step;
    }
  }
  return Math.round(best * magnitude);
}

export function computeScaleDenominator(zoom: number, latDeg: number): number {
  return niceScaleDenominator(metersPerPixel(zoom, latDeg) / OGC_PIXEL_SIZE_M);
}

export function formatScaleLabel(denominator: number): string {
  if (denominator <= 0) return "1:—";
  return `1:${denominator.toLocaleString("id-ID")}`;
}
