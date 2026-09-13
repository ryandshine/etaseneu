import type { DashboardHotspot, GeoJsonStatusResponse } from "../types/api";
import { getConfidenceCategory, getFrpCategory } from "./hotspotDisplay";
import { getTodayWIB } from "./date";

export type ChartItem = {
  label: string;
  value: number;
  color: string;
  tone?: string;
  subtitle?: string;
};

export type SeriesPoint = {
  label: string;
  value: number;
};

export type MultiSeries = {
  label: string;
  color: string;
  values: number[];
};

export const FRP_CATEGORIES: Array<{
  label: string;
  tone: string;
  color: string;
  border: string;
  desc: string;
}> = [
  { label: "Tinggi", tone: "high", color: "rgba(220, 38, 38, 0.74)", border: "#ef4444", desc: "> 30 MW" },
  { label: "Sedang", tone: "nominal", color: "rgba(234, 88, 12, 0.64)", border: "#f59e0b", desc: "10 - 30 MW" },
  { label: "Rendah", tone: "low", color: "rgba(34, 197, 94, 0.5)", border: "#22c55e", desc: "< 10 MW" }
];

export const CONFIDENCE_CATEGORIES: Array<{
  label: string;
  tone: string;
  color: string;
  border: string;
  desc: string;
}> = [
  { label: "Tinggi", tone: "high", color: "rgba(220, 38, 38, 0.74)", border: "#ef4444", desc: "> 80% (MODIS) / H (VIIRS)" },
  { label: "Sedang", tone: "nominal", color: "rgba(245, 158, 11, 0.64)", border: "#f59e0b", desc: "30-80% (MODIS) / N (VIIRS)" },
  { label: "Rendah", tone: "low", color: "rgba(59, 130, 246, 0.5)", border: "#3b82f6", desc: "< 30% (MODIS) / L (VIIRS)" }
];

export function buildConfidenceDistribution(hotspots: DashboardHotspot[]): ChartItem[] {
  return CONFIDENCE_CATEGORIES.map((bin) => ({
    ...bin,
    value: hotspots.filter((hotspot) => getConfidenceCategory(hotspot) === bin.label).length,
  }));
}

export const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function parseDateTime(value: string) {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function getWibDateParts(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return { year: 0, month: 0, date: 0, dateStr: "", yearMonthStr: "" };
  }
  const wibTime = new Date(parsed.getTime() + 7 * 60 * 60 * 1000);
  const year = wibTime.getUTCFullYear();
  const month = wibTime.getUTCMonth(); // 0-indexed
  const date = wibTime.getUTCDate();
  const monthStr = String(month + 1).padStart(2, '0');
  const dayStr = String(date).padStart(2, '0');
  return {
    year,
    month,
    date,
    dateStr: `${year}-${monthStr}-${dayStr}`,
    yearMonthStr: `${year}-${monthStr}`
  };
}

export function formatDateLabel(value: string) {
  const parsed = parseDateTime(value);
  if (!parsed) {
    return "-";
  }

  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    day: "2-digit",
    month: "short"
  }).format(parsed);
}

export function formatJakartaTimestamp(value?: string | null) {
  if (!value) {
    return "Tidak Pernah";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "Tidak Pernah";
  }

  const formatter = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Jakarta",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit"
  });
  const parts = formatter.formatToParts(parsed);
  const day = parts.find((part) => part.type === "day")?.value ?? "--";
  const month = parts.find((part) => part.type === "month")?.value ?? "---";
  const hour = parts.find((part) => part.type === "hour")?.value ?? "--";
  const minute = parts.find((part) => part.type === "minute")?.value ?? "--";
  return `${day} ${month} ${hour}:${minute} WIB`;
}

export function getLatestRegistrySync(status: GeoJsonStatusResponse | null): string {
  if (!status?.files.length) {
    return "Tidak Pernah";
  }

  const timestamps = status.files
    .map((file) => file.last_synced_at)
    .filter((value): value is string => Boolean(value));

  if (!timestamps.length) {
    return "Tidak Pernah";
  }

  timestamps.sort();
  return formatJakartaTimestamp(timestamps[timestamps.length - 1]);
}

export function buildFrpDistribution(hotspots: DashboardHotspot[]): ChartItem[] {
  return FRP_CATEGORIES.map((bin) => ({
    ...bin,
    value: hotspots.filter((hotspot) => getFrpCategory(hotspot) === bin.label).length,
  }));
}

// Jumlah titik panas per fungsi kawasan hutan (atribusi Fase 4: tiap hotspot
// membawa `kawasanHutan`). Diurutkan terbanyak dulu; titik di luar semua
// kawasan hutan dikumpulkan di label sendiri supaya total = jumlah hotspot.
export const KAWASAN_LUAR_LABEL = "Di luar kawasan";
export const KAWASAN_BAR_COLOR = "#2f855a";

export function shortKawasanLabel(fungsi: string): string {
  return fungsi
    .replace(/Hutan Produksi yang dapat Dikonversi/i, "HP Konversi")
    .replace(/Hutan Produksi Terbatas/i, "HP Terbatas")
    .replace(/Hutan Produksi Tetap/i, "HP Tetap")
    .replace(/Kawasan Konservasi Laut/i, "Konservasi Laut")
    .replace(/Kawasan Konservasi.*/i, "Konservasi")
    .replace(/Areal Penggunaan Lain/i, "APL");
}

export function buildKawasanDistribution(hotspots: DashboardHotspot[]): ChartItem[] {
  const counts = new Map<string, number>();
  for (const hotspot of hotspots) {
    const label = (hotspot.fungsiKawasan || "").trim() || KAWASAN_LUAR_LABEL;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, value]) => ({
      label: label === KAWASAN_LUAR_LABEL ? label : shortKawasanLabel(label),
      value,
      color: label === KAWASAN_LUAR_LABEL ? "#4b5563" : KAWASAN_BAR_COLOR,
    }))
    .sort((a, b) => b.value - a.value);
}

export const SKEMA_FALLBACK = "Tanpa Skema";
export const MATRIX_PREVIEW_ROW_LIMIT = 10;

// Sebagian polygon di sumber belum mengisi SKEMA; titiknya tetap dihitung lewat
// label SKEMA_FALLBACK supaya total tabel silang sama dengan jumlah rekaman
// yang tampil di buku besar. Label ini sengaja sama dengan yang dipakai ekspor
// XLSX/PDF (backend: polygon_fields.skema_name).
export function getSkema(hotspot: DashboardHotspot) {
  return (hotspot.polygonMetadata.SKEMA || "").trim() || SKEMA_FALLBACK;
}

export function getProvinsi(hotspot: DashboardHotspot) {
  return (hotspot.provinceName || hotspot.polygonMetadata.NAMA_PROV || "").trim() || "Tanpa Provinsi";
}

export type SkemaProvinsiRow = {
  provinsi: string;
  counts: number[];
  total: number;
};

export type SkemaProvinsiMatrix = {
  skema: string[];
  rows: SkemaProvinsiRow[];
  totals: number[];
  grandTotal: number;
  maxCell: number;
};

export function buildSkemaProvinsiMatrix(hotspots: DashboardHotspot[]): SkemaProvinsiMatrix {
  const pairCounts = new Map<string, number>();
  const skemaTotals = new Map<string, number>();
  const provinsiTotals = new Map<string, number>();

  hotspots.forEach((hotspot) => {
    const skema = getSkema(hotspot);
    const provinsi = getProvinsi(hotspot);
    const pairKey = `${provinsi} ${skema}`;
    pairCounts.set(pairKey, (pairCounts.get(pairKey) ?? 0) + 1);
    skemaTotals.set(skema, (skemaTotals.get(skema) ?? 0) + 1);
    provinsiTotals.set(provinsi, (provinsiTotals.get(provinsi) ?? 0) + 1);
  });

  // Kolom & baris diurutkan dari yang terbanyak: tabelnya bisa selebar delapan
  // kolom dan pembaca hampir selalu berhenti di beberapa kolom pertama.
  const byCountDesc = (a: [string, number], b: [string, number]) =>
    b[1] - a[1] || a[0].localeCompare(b[0]);

  const skema = Array.from(skemaTotals.entries()).sort(byCountDesc).map(([label]) => label);
  const rows = Array.from(provinsiTotals.entries())
    .sort(byCountDesc)
    .map(([provinsi, total]) => ({
      provinsi,
      counts: skema.map((label) => pairCounts.get(`${provinsi} ${label}`) ?? 0),
      total,
    }));
  const totals = skema.map((label) => skemaTotals.get(label) ?? 0);

  return {
    skema,
    rows,
    totals,
    grandTotal: hotspots.length,
    maxCell: Math.max(0, ...Array.from(pairCounts.values())),
  };
}

export function buildTopWilker(hotspots: DashboardHotspot[]) {
  const counts = new Map<string, number>();
  hotspots.forEach((hotspot) => {
    const name = hotspot.polygonMetadata.WILKER_BPS || "Belum Ditugaskan";
    counts.set(name, (counts.get(name) ?? 0) + 1);
  });

  return Array.from(counts.entries())
    .map(([label, value]) => ({ label, value, color: "#14b8a6" }))
    .sort((a, b) => b.value - a.value);
}

export function buildDailyTrend(hotspots: DashboardHotspot[], groupBy: 'day' | 'month' = 'day') {
  const counts = new Map<string, number>();
  hotspots.forEach((hotspot) => {
    const parts = getWibDateParts(hotspot.detectedAt);
    const key = groupBy === 'month' ? parts.yearMonthStr : parts.dateStr;
    if (key) {
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  });

  return Array.from(counts.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function buildDailyFrpTrend(hotspots: DashboardHotspot[], groupBy: 'day' | 'month' = 'day') {
  const sums = new Map<string, number>();
  hotspots.forEach((hotspot) => {
    const parts = getWibDateParts(hotspot.detectedAt);
    const key = groupBy === 'month' ? parts.yearMonthStr : parts.dateStr;
    if (key) {
      const value = hotspot.frp ?? 0;
      sums.set(key, (sums.get(key) ?? 0) + value);
    }
  });

  return Array.from(sums.entries())
    .map(([label, value]) => ({ label, value: Math.round(value * 10) / 10 }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function buildYearOverYear(hotspots: DashboardHotspot[]) {
  const years = Array.from(
    new Set(
      hotspots
        .map((hotspot) => getWibDateParts(hotspot.detectedAt).year)
        .filter((value): value is number => Boolean(value)),
    ),
  ).sort((a, b) => a - b);

  const latestYear = years[years.length - 1] ?? parseInt(getTodayWIB().slice(0, 4), 10);
  const selectedYears = [latestYear - 2, latestYear - 1, latestYear];
  const yearIndexMap = new Map(selectedYears.map((y, idx) => [y, idx]));

  // 3 years x 12 months buckets
  const countBuckets = selectedYears.map(() => new Array(12).fill(0));
  const frpBuckets = selectedYears.map(() => new Array(12).fill(0));

  // Single-pass O(N) accumulation across all hotspots
  for (const hotspot of hotspots) {
    const parts = getWibDateParts(hotspot.detectedAt);
    const yIdx = yearIndexMap.get(parts.year);
    if (yIdx !== undefined && parts.month >= 0 && parts.month < 12) {
      countBuckets[yIdx][parts.month] += 1;
      frpBuckets[yIdx][parts.month] += (hotspot.frp ?? 0);
    }
  }

  const countSeries: MultiSeries[] = selectedYears.map((year, idx) => ({
    label: String(year),
    color: year === latestYear ? "#8A1A10" : year === latestYear - 1 ? "#14b8a6" : "#64748b",
    values: countBuckets[idx]
  }));

  const frpSeries: MultiSeries[] = selectedYears.map((year, idx) => ({
    label: String(year),
    color: year === latestYear ? "#8A1A10" : year === latestYear - 1 ? "#14b8a6" : "#64748b",
    values: frpBuckets[idx].map((val) => Math.round(val * 10) / 10)
  }));

  return { years: selectedYears, countSeries, frpSeries };
}
