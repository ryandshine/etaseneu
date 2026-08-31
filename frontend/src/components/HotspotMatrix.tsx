import { useEffect, useMemo, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, ResponsiveContainer, AreaChart, Area, Cell, LabelList } from "recharts";
import { Download } from "lucide-react";

import { BurnedAreaCard } from "./BurnedAreaCard";
import type {
  BurnFrequencyRecord,
  BurnedAreaKawasanResponse,
  GeoJsonStatusResponse,
  PolygonDetail,
} from "../types/api";
import { formatDateWIB, getTodayWIB } from "../lib/date";
import { authFetch, createApiClient } from "../lib/api";
import { TIME_PRESET_OPTIONS, type TimePreset } from "../constants/time-windows";
import type { TimeRange } from "../hooks/useDashboardData";
import {
  formatMetadataValue,
  formatNumber,
  formatTimestamp,
  getFrpCategory,
  normalizeFrpCategoryLabel
} from "../lib/hotspotDisplay";

const api = createApiClient();

const BULAN_PENDEK = [
  "", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"
];

function formatPeriodeSingkat(iso: string | null): string {
  if (!iso) return "-";
  const [year, month] = iso.split("-");
  const m = Number(month);
  return `${BULAN_PENDEK[m] ?? month} ${year}`;
}

type MatrixHotspot = {
  id: string;
  detectedAt: string;
  latitude: number;
  longitude: number;
  layerName: string;
  agencyName: string;
  provinceName: string;
  polygonMetadata: Record<string, string>;
  source: string;
  satellite: string;
  brightness: number | null;
  frp: number | null;
  confidence: string;
  daynight: string;
  fungsiKawasan?: string;
  kelompokKawasan?: string;
};

function hotspotToGeoJsonFeature(hotspot: MatrixHotspot) {
  return {
    type: "Feature" as const,
    geometry: {
      type: "Point" as const,
      coordinates: [hotspot.longitude, hotspot.latitude]
    },
    properties: {
      id: hotspot.id,
      detected_at: hotspot.detectedAt,
      layer_name: hotspot.layerName,
      agency_name: hotspot.agencyName,
      province_name: hotspot.provinceName,
      source: hotspot.source,
      satellite: hotspot.satellite,
      brightness: hotspot.brightness,
      frp: hotspot.frp,
      confidence: hotspot.confidence,
      daynight: hotspot.daynight,
      ...hotspot.polygonMetadata
    }
  };
}

// polygon_metadata_id bisa saja belum ke-link ke sebagian titik dalam satu
// grup KPS (spatial join belum lengkap) -- cari dari titik manapun yang
// sudah punya ID valid, bukan cuma yang pertama, biar boundary polygon tetap
// bisa disertakan selama ADA satu titik yang tertaut.
function findLinkedPolygonId(hotspots: MatrixHotspot[]): number | null {
  for (const hotspot of hotspots) {
    const raw = hotspot.polygonMetadata.polygon_metadata_id;
    const parsed = raw ? Number(raw) : NaN;
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function polygonDetailToGeoJsonFeature(detail: PolygonDetail) {
  return {
    type: "Feature" as const,
    geometry: detail.geometry,
    properties: {
      id: detail.id,
      layer_key: detail.layer_key,
      lembaga: detail.lembaga,
      nama_prov: detail.nama_prov,
      nama_kab: detail.nama_kab,
      nama_kec: detail.nama_kec,
      nama_desa: detail.nama_desa,
      skema: detail.skema,
      no_sk: detail.no_sk,
      tgl_sk: detail.tgl_sk,
      status: detail.status,
      wilker_bps: detail.wilker_bps,
      ps_id: detail.ps_id,
      luas_final: detail.luas_final,
      jml_kk: detail.jml_kk
    }
  };
}

function downloadGeoJson(featureCollection: object, filename: string) {
  const blob = new Blob([JSON.stringify(featureCollection, null, 2)], {
    type: "application/geo+json"
  });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 100);
}

function slugifyFilename(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

type HotspotMatrixProps = {
  hotspots: MatrixHotspot[];
  geojsonStatus: GeoJsonStatusResponse | null;
  onExport: (filters: { province?: string; wilker?: string; confidence?: string; skema?: string }) => void;
  isExporting: boolean;
  onExportPdf: (filters: { province?: string; wilker?: string; confidence?: string; skema?: string; agency?: string }) => void;
  isExportingPdf: boolean;
  startDate: string;
  endDate: string;
  // Sumber kebenaran rentang waktu yang benar-benar aktif -- startDate/endDate
  // di atas cuma berarti saat timePreset "custom"; untuk preset lain (mis.
  // "30 Hari") rentang sesungguhnya dihitung terpisah lewat buildTimeRange
  // dan tidak pernah disinkronkan balik ke startDate/endDate. Apa pun yang
  // butuh tanggal aktual filter (bukan cuma teks label-nya) harus pakai ini.
  timeRange: TimeRange;
  dateRangeLabel: string;
  onDateChange: (field: "startDate" | "endDate", value: string) => void;
  timePreset: TimePreset;
  onTimePresetChange: (value: TimePreset) => void;
  /**
   * Buka halaman detail KPS (polygon SHP + laporan deteksi lengkap) --
   * dulu ini panel geser sempit di sisi kanan, sekarang halaman tersendiri
   * supaya tidak ada scroll bertingkat. Opsional supaya HotspotMatrix tetap
   * bisa dites/dipakai tanpa fitur navigasi App.
   */
  initialWilker?: string;
  lockedWilker?: string;
  onOpenKpsDetail?: (agency: string) => void;
};

type ChartItem = {
  label: string;
  value: number;
  color: string;
  tone?: string;
  subtitle?: string;
};

type SeriesPoint = {
  label: string;
  value: number;
};

type MultiSeries = {
  label: string;
  color: string;
  values: number[];
};

const FRP_CATEGORIES: Array<{
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

const CONFIDENCE_CATEGORIES: Array<{
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

function getConfidenceCategory(hotspot: MatrixHotspot) {
  const conf = (hotspot.confidence || "").trim().toLowerCase();
  if (conf === "h" || conf === "high") return "Tinggi";
  if (conf === "n" || conf === "nominal" || conf === "medium") return "Sedang";
  if (conf === "l" || conf === "low") return "Rendah";

  const val = Number.parseInt(conf, 10);
  if (!Number.isNaN(val)) {
    if (val > 80) return "Tinggi";
    if (val >= 30) return "Sedang";
    return "Rendah";
  }
  return "Rendah";
}

function buildConfidenceDistribution(hotspots: MatrixHotspot[]): ChartItem[] {
  return CONFIDENCE_CATEGORIES.map((bin) => ({
    ...bin,
    value: hotspots.filter((hotspot) => getConfidenceCategory(hotspot) === bin.label).length,
  }));
}


const MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function parseDateTime(value: string) {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function getWibDateParts(value: string) {
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

function formatDateLabel(value: string) {
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

function formatJakartaTimestamp(value?: string | null) {
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

function getLatestRegistrySync(status: GeoJsonStatusResponse | null): string {
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

function buildFrpDistribution(hotspots: MatrixHotspot[]): ChartItem[] {
  return FRP_CATEGORIES.map((bin) => ({
    ...bin,
    value: hotspots.filter((hotspot) => getFrpCategory(hotspot) === bin.label).length,
  }));
}

// Jumlah titik panas per fungsi kawasan hutan (atribusi Fase 4: tiap hotspot
// membawa `kawasanHutan`). Diurutkan terbanyak dulu; titik di luar semua
// kawasan hutan dikumpulkan di label sendiri supaya total = jumlah hotspot.
const KAWASAN_LUAR_LABEL = "Di luar kawasan";
const KAWASAN_BAR_COLOR = "#2f855a";

function shortKawasanLabel(fungsi: string): string {
  return fungsi
    .replace(/Hutan Produksi yang dapat Dikonversi/i, "HP Konversi")
    .replace(/Hutan Produksi Terbatas/i, "HP Terbatas")
    .replace(/Hutan Produksi Tetap/i, "HP Tetap")
    .replace(/Kawasan Konservasi Laut/i, "Konservasi Laut")
    .replace(/Kawasan Konservasi.*/i, "Konservasi")
    .replace(/Areal Penggunaan Lain/i, "APL");
}

function buildKawasanDistribution(hotspots: MatrixHotspot[]): ChartItem[] {
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

const SKEMA_FALLBACK = "Tanpa Skema";
const MATRIX_PREVIEW_ROW_LIMIT = 10;

// Sebagian polygon di sumber belum mengisi SKEMA; titiknya tetap dihitung lewat
// label SKEMA_FALLBACK supaya total tabel silang sama dengan jumlah rekaman
// yang tampil di buku besar. Label ini sengaja sama dengan yang dipakai ekspor
// XLSX/PDF (backend: polygon_fields.skema_name).
function getSkema(hotspot: MatrixHotspot) {
  return (hotspot.polygonMetadata.SKEMA || "").trim() || SKEMA_FALLBACK;
}

function getProvinsi(hotspot: MatrixHotspot) {
  return (hotspot.provinceName || hotspot.polygonMetadata.NAMA_PROV || "").trim() || "Tanpa Provinsi";
}

type SkemaProvinsiRow = {
  provinsi: string;
  counts: number[];
  total: number;
};

type SkemaProvinsiMatrix = {
  skema: string[];
  rows: SkemaProvinsiRow[];
  totals: number[];
  grandTotal: number;
  maxCell: number;
};

function buildSkemaProvinsiMatrix(hotspots: MatrixHotspot[]): SkemaProvinsiMatrix {
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

function buildTopWilker(hotspots: MatrixHotspot[]) {
  const counts = new Map<string, number>();
  hotspots.forEach((hotspot) => {
    const name = hotspot.polygonMetadata.WILKER_BPS || "Belum Ditugaskan";
    counts.set(name, (counts.get(name) ?? 0) + 1);
  });

  return Array.from(counts.entries())
    .map(([label, value]) => ({ label, value, color: "#14b8a6" }))
    .sort((a, b) => b.value - a.value);
}

function buildDailyTrend(hotspots: MatrixHotspot[], groupBy: 'day' | 'month' = 'day') {
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

function buildDailyFrpTrend(hotspots: MatrixHotspot[], groupBy: 'day' | 'month' = 'day') {
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

function buildYearOverYear(hotspots: MatrixHotspot[]) {
  const years = Array.from(
    new Set(
      hotspots
        .map((hotspot) => getWibDateParts(hotspot.detectedAt).year)
        .filter((value): value is number => Boolean(value)),
    ),
  ).sort((a, b) => a - b);

  const latestYear = years[years.length - 1] ?? parseInt(getTodayWIB().slice(0, 4), 10);
  const selectedYears = [latestYear - 2, latestYear - 1, latestYear];

  const countSeries: MultiSeries[] = selectedYears.map((year) => ({
    label: String(year),
    color: year === latestYear ? "#ff4e00" : year === latestYear - 1 ? "#14b8a6" : "#64748b",
    values: MONTH_LABELS.map((_, monthIndex) =>
      hotspots.filter((hotspot) => {
        const parts = getWibDateParts(hotspot.detectedAt);
        return parts.year === year && parts.month === monthIndex;
      }).length,
    )
  }));

  const frpSeries: MultiSeries[] = selectedYears.map((year) => ({
    label: String(year),
    color: year === latestYear ? "#ff4e00" : year === latestYear - 1 ? "#14b8a6" : "#64748b",
    values: MONTH_LABELS.map((_, monthIndex) =>
      Math.round(
        hotspots
          .filter((hotspot) => {
            const parts = getWibDateParts(hotspot.detectedAt);
            return parts.year === year && parts.month === monthIndex;
          })
          .reduce((sum, hotspot) => sum + (hotspot.frp ?? 0), 0) * 10,
      ) / 10,
    )
  }));

  return { years: selectedYears, countSeries, frpSeries };
}

function MatrixField({
  label,
  value
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="matrix-key-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function BarTrackList({
  items,
  activeLabel,
  onSelect,
  selectable,
  emptyLabel
}: {
  items: ChartItem[];
  activeLabel?: string | null;
  onSelect?: (label: string) => void;
  selectable?: boolean;
  emptyLabel: string;
}) {
  const maxValue = Math.max(...items.map((item) => item.value), 1);

  if (!items.length) {
    return <div className="matrix-empty matrix-empty--inline">{emptyLabel}</div>;
  }

  return (
    <div className="matrix-bar-list">
      {items.map((item) => {
        const width = `${Math.max((item.value / maxValue) * 100, item.value > 0 ? 12 : 0)}%`;
        const isActive = Boolean(activeLabel && activeLabel === item.label);

        return (
          <button
            key={item.label}
            type="button"
            className={`matrix-bar-row${selectable ? " matrix-bar-row--selectable" : ""}${isActive ? " matrix-bar-row--active" : ""}`}
            onClick={() => onSelect?.(item.label)}
            disabled={!selectable}
          >
            <div className="matrix-bar-row__head">
              <span className="matrix-bar-row__label">{item.label}</span>
              <strong>{item.value}</strong>
            </div>
            <div className="matrix-bar-track">
              <span
                className="matrix-bar-fill"
                style={{
                  width,
                  background: item.color,
                  boxShadow: isActive ? `0 0 18px ${item.color}` : undefined
                }}
              />
            </div>
            {item.subtitle ? <small>{item.subtitle}</small> : null}
          </button>
        );
      })}
    </div>
  );
}

function AreaSparkChart({
  data,
  color,
  emptyLabel,
  labelFormatter
}: {
  data: SeriesPoint[];
  color: string;
  emptyLabel: string;
  labelFormatter?: (value: string) => string;
}) {
  if (!data.length) {
    return <div className="matrix-empty matrix-empty--inline">{emptyLabel}</div>;
  }

  const width = 720;
  const height = 180;
  const padding = 18;
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const max = Math.max(...data.map((item) => item.value), 1);
  const step = data.length > 1 ? plotWidth / (data.length - 1) : 0;
  const points = data.map((item, index) => {
    const x = padding + step * index;
    const y = height - padding - (item.value / max) * plotHeight;
    return { ...item, x, y };
  });
  const linePath = points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
  const areaPath = `${linePath} L ${points[points.length - 1].x} ${height - padding} L ${points[0].x} ${height - padding} Z`;

  return (
    <svg className="matrix-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Trend chart">
      <defs>
        <linearGradient id={`trend-fill-${color.replace(/[^a-z0-9]/gi, "")}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.26" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#trend-fill-${color.replace(/[^a-z0-9]/gi, "")})`} />
      <path d={linePath} fill="none" stroke={color} strokeWidth="2.5" />
      {points.map((point) => (
        <g key={point.label}>
          <circle cx={point.x} cy={point.y} r="3.2" fill={color} />
          <text x={point.x} y={height - 4} textAnchor="middle" className="matrix-spark__label">
            {labelFormatter ? labelFormatter(point.label) : point.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function MultiLineChart({
  months,
  series,
  emptyLabel
}: {
  months: string[];
  series: MultiSeries[];
  emptyLabel: string;
}) {
  if (!series.length) {
    return <div className="matrix-empty matrix-empty--inline">{emptyLabel}</div>;
  }

  const width = 720;
  const height = 220;
  const padding = 20;
  const plotWidth = width - padding * 2;
  const plotHeight = height - padding * 2;
  const max = Math.max(1, ...series.flatMap((entry) => entry.values));
  const step = months.length > 1 ? plotWidth / (months.length - 1) : 0;

  const buildPath = (values: number[]) => {
    return values
      .map((value, index) => {
        const x = padding + step * index;
        const y = height - padding - (value / max) * plotHeight;
        return `${index === 0 ? "M" : "L"} ${x} ${y}`;
      })
      .join(" ");
  };

  return (
    <svg className="matrix-spark matrix-spark--line" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Year over year chart">
      {months.map((month, index) => {
        const x = padding + step * index;
        return (
          <text key={month} x={x} y={height - 4} textAnchor="middle" className="matrix-spark__label">
            {month}
          </text>
        );
      })}
      {series.map((entry) => {
        const path = buildPath(entry.values);
        return <path key={entry.label} d={path} fill="none" stroke={entry.color} strokeWidth="2.5" />;
      })}
      {series.map((entry) =>
        entry.values.map((value, index) => {
          const x = padding + step * index;
          const y = height - padding - (value / max) * plotHeight;
          return <circle key={`${entry.label}-${index}`} cx={x} cy={y} r="2.8" fill={entry.color} />;
        }),
      )}
    </svg>
  );
}


function SkemaProvinsiCard({
  matrix,
  activeSkema,
  activeProvince,
  onSelectSkema,
  onSelectProvince
}: {
  matrix: SkemaProvinsiMatrix;
  activeSkema: string;
  activeProvince: string;
  onSelectSkema: (label: string) => void;
  onSelectProvince: (label: string) => void;
}) {
  const dominant = matrix.skema[0];
  const dominantShare = matrix.grandTotal ? Math.round((matrix.totals[0] / matrix.grandTotal) * 100) : 0;
  const [showAllRows, setShowAllRows] = useState(false);

  useEffect(() => {
    if (matrix.rows.length <= MATRIX_PREVIEW_ROW_LIMIT) {
      setShowAllRows(false);
    }
  }, [matrix.rows.length]);

  const visibleRows = showAllRows
    ? matrix.rows
    : matrix.rows.slice(0, MATRIX_PREVIEW_ROW_LIMIT);

  return (
    <section className="matrix-chart-card matrix-chart-card--wide glass-panel">
      <div className="matrix-chart-card__header">
        <div>
          <p className="panel-eyebrow">Tabel Silang</p>
          <h3>Hotspot per Skema per Provinsi</h3>
        </div>
        <p className="skema-matrix__meta">
          {matrix.skema.length} skema · {matrix.rows.length} provinsi · {matrix.grandTotal} titik
        </p>
      </div>

      {matrix.skema.length === 0 ? (
        <div className="matrix-empty matrix-empty--card">Data hotspot tidak tersedia</div>
      ) : (
        <>
          <p className="skema-matrix__lead">
            Konsentrasi terbesar pada skema <strong>{dominant}</strong> ({matrix.totals[0]} titik ·{" "}
            {dominantShare}%). Klik nama skema atau provinsi untuk menyaring seluruh matriks.
          </p>
          <div className="skema-matrix__scroll">
            <table className="skema-matrix">
              <thead>
                <tr>
                  <th scope="col">Provinsi</th>
                  {matrix.skema.map((label) => (
                    <th key={label} scope="col">
                      <button
                        type="button"
                        className={`skema-matrix__head-btn${activeSkema === label ? " is-active" : ""}`}
                        onClick={() => onSelectSkema(label)}
                        title={`Saring skema ${label}`}
                      >
                        {label}
                      </button>
                    </th>
                  ))}
                  <th className="skema-matrix__total-col" scope="col">Total</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr key={row.provinsi} className={activeProvince === row.provinsi ? "is-active" : ""}>
                    <th scope="row">
                      <button
                        type="button"
                        className={`skema-matrix__head-btn${activeProvince === row.provinsi ? " is-active" : ""}`}
                        onClick={() => onSelectProvince(row.provinsi)}
                        title={`Saring provinsi ${row.provinsi}`}
                      >
                        {row.provinsi}
                      </button>
                    </th>
                    {row.counts.map((count, index) => (
                      <td
                        key={matrix.skema[index]}
                        // Sel diberi gradasi menurut nilai terbesar di seluruh
                        // tabel supaya konsentrasi terbaca sekilas tanpa harus
                        // membandingkan angka satu per satu.
                        style={
                          count
                            ? {
                                background: `rgba(255, 78, 0, ${Math.max(
                                  0.08,
                                  (count / (matrix.maxCell || 1)) * 0.62,
                                ).toFixed(3)})`
                              }
                            : undefined
                        }
                      >
                        {count || <span className="skema-matrix__zero">–</span>}
                      </td>
                    ))}
                    <td className="skema-matrix__total-col">{row.total}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Total</th>
                  {matrix.totals.map((total, index) => (
                    <td key={matrix.skema[index]}>{total}</td>
                  ))}
                  <td className="skema-matrix__total-col">{matrix.grandTotal}</td>
                </tr>
              </tfoot>
            </table>
          </div>
          {matrix.rows.length > MATRIX_PREVIEW_ROW_LIMIT ? (
            <div className="skema-matrix__more">
              <span>
                Menampilkan {showAllRows ? matrix.rows.length : MATRIX_PREVIEW_ROW_LIMIT} dari {matrix.rows.length} provinsi
              </span>
              <button
                type="button"
                className="skema-matrix__more-btn"
                onClick={() => setShowAllRows((current) => !current)}
                aria-expanded={showAllRows}
              >
                {showAllRows ? "Tampilkan 10 saja" : `Lihat semua (${matrix.rows.length})`}
              </button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function renderCompactCard(title: string, data: any[], total: number, activeLabel: string | null = null, onClick: ((label: string | null) => void) | null = null) {
  const maxVal = Math.max(...data.map(d => d.value), 1);
  const domCategory = [...data].sort((a, b) => b.value - a.value)[0];
  
  return (
    <section className="matrix-chart-card glass-panel" style={{ display: 'flex', flexDirection: 'column', height: 'auto', minHeight: 'unset' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
        <div>
          <h3 style={{ fontSize: '1rem', fontWeight: '600', color: '#fff', marginBottom: '0.25rem' }}>{title}</h3>
          <p style={{ fontSize: '0.8rem', color: '#9ca3af' }}>Total Hotspot: <strong style={{ color: '#fff' }}>{total}</strong></p>
        </div>
        {activeLabel && onClick && (
          <button type="button" className="matrix-inline-action" onClick={() => onClick(null)}>
            Bersihkan
          </button>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
        {data.map(item => {
          const pct = total > 0 ? Math.round((item.value / total) * 100) : 0;
          const barWidth = Math.max((item.value / maxVal) * 100, 2);
          const isSelected = activeLabel === item.label;
          const opacity = activeLabel && !isSelected ? 0.3 : 1;
          const fill = isSelected ? '#FF4E00' : (item.color || '#374151');
          
          return (
            <div 
              key={item.label} 
              style={{ display: 'flex', alignItems: 'center', opacity, cursor: onClick ? 'pointer' : 'default', fontSize: '0.85rem' }}
              onClick={() => onClick && onClick(item.label)}
            >
              <div style={{ width: '60px', color: '#d1d5db', fontWeight: '500' }}>{item.label}</div>
              <div style={{ flex: 1, height: '12px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '2px', overflow: 'hidden', margin: '0 12px', display: 'flex' }}>
                {item.value > 0 && (
                  <div style={{ width: `${barWidth}%`, backgroundColor: fill, height: '100%', transition: 'width 0.3s ease' }} />
                )}
              </div>
              <div style={{ width: '70px', textAlign: 'right', color: '#fff' }}>
                {item.value} <span style={{ color: '#9ca3af', fontSize: '0.75rem' }}>({pct}%)</span>
              </div>
            </div>
          )
        })}
      </div>

      {(title.toLowerCase().includes('confidence') || title.toLowerCase().includes('frp')) && (
        <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '0.75rem', color: '#9ca3af', lineHeight: 1.5 }}>
          Mayoritas hotspot memiliki {title.toLowerCase().includes('confidence') ? 'confidence' : 'intensitas FRP'} <strong style={{ color: '#fff' }}>{domCategory?.label || '-'}</strong> ({total > 0 ? Math.round(((domCategory?.value || 0) / total) * 100) : 0}%).
        </div>
      )}
    </section>
  );
}

// Luas terbakar resmi Kementerian Kehutanan per fungsi kawasan hutan. Sumbernya
// beda total dari titik hotspot (satuan hektar vs jumlah titik, kesegaran data
// bulanan vs 3 jam) -- ditegaskan di catatan kaki kartu.
function formatHa(value: number): string {
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 }).format(value);
}

function renderKawasanBurnedCard(data: BurnedAreaKawasanResponse | null) {
  const rows = data?.rows ?? [];
  const totalHa = data?.total_ha ?? 0;
  const maxVal = Math.max(...rows.map((row) => row.luas_ha), 1);
  const dominant = [...rows].sort((a, b) => b.luas_ha - a.luas_ha)[0];

  return (
    <section className="matrix-chart-card glass-panel" style={{ display: 'flex', flexDirection: 'column', height: 'auto', minHeight: 'unset' }}>
      <div style={{ marginBottom: '1.25rem' }}>
        <h3 style={{ fontSize: '1rem', fontWeight: '600', color: '#fff', marginBottom: '0.25rem' }}>Luas Kebakaran per Kawasan Hutan</h3>
        <p style={{ fontSize: '0.8rem', color: '#9ca3af' }}>
          Total: <strong style={{ color: '#fff' }}>{formatHa(totalHa)} Ha</strong>
        </p>
      </div>

      {rows.length === 0 ? (
        <p style={{ fontSize: '0.85rem', color: '#9ca3af' }}>Belum ada data luas terbakar untuk pilihan ini.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {rows.map((row) => {
            const pct = totalHa > 0 ? Math.round((row.luas_ha / totalHa) * 100) : 0;
            const barWidth = Math.max((row.luas_ha / maxVal) * 100, 2);
            return (
              <div key={row.fungsi} style={{ display: 'flex', alignItems: 'center', fontSize: '0.85rem' }}>
                <div style={{ width: '92px', color: '#d1d5db', fontWeight: '500' }}>{shortKawasanLabel(row.fungsi)}</div>
                <div style={{ flex: 1, height: '12px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '2px', overflow: 'hidden', margin: '0 12px' }}>
                  <div style={{ width: `${barWidth}%`, backgroundColor: '#9B2C2C', height: '100%', transition: 'width 0.3s ease' }} />
                </div>
                <div style={{ width: '104px', textAlign: 'right', color: '#fff' }}>
                  {formatHa(row.luas_ha)} <span style={{ color: '#9ca3af', fontSize: '0.75rem' }}>({pct}%)</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '0.75rem', color: '#9ca3af', lineHeight: 1.5 }}>
        {dominant ? (
          <>Terbanyak di <strong style={{ color: '#fff' }}>{shortKawasanLabel(dominant.fungsi)}</strong>. </>
        ) : null}
        Sumber: {data?.source ?? "Kementerian Kehutanan"} · {data?.period ?? "Januari–Juli 2026"}. Satuan hektar, tidak sebanding langsung dengan jumlah titik panas.
      </div>
    </section>
  );
}

export function HotspotMatrix({
  hotspots,
  geojsonStatus,
  onExport,
  isExporting,
  onExportPdf,
  isExportingPdf,
  onDateChange,
  startDate,
  endDate,
  timeRange,
  dateRangeLabel,
  timePreset,
  onTimePresetChange,
  initialWilker,
  lockedWilker,
  onOpenKpsDetail
}: HotspotMatrixProps) {
  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div style={{ backgroundColor: '#13151A', border: '1px solid #1A1D21', padding: '12px', borderRadius: '2px', boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)', fontFamily: 'Plus Jakarta Sans, sans-serif', fontSize: '10px', textTransform: 'uppercase', color: 'white', zIndex: 50 }}>
          <p style={{ fontWeight: 'bold', color: '#FF4E00', borderBottom: '1px solid #1A1D21', paddingBottom: '4px', marginBottom: '4px' }}>{data.label}</p>
          <p><span style={{ color: '#9ca3af', marginRight: '4px' }}>COUNT:</span> <span style={{ fontWeight: 'bold' }}>{data.value} FIRES</span></p>
        </div>
      );
    }
    return null;
  };

  const DailyTrendTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div style={{ backgroundColor: '#13151A', border: '1px solid #1A1D21', padding: '12px', borderRadius: '2px', boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)', fontFamily: 'Plus Jakarta Sans, sans-serif', fontSize: '10px', textTransform: 'uppercase', color: 'white', zIndex: 50 }}>
          <p style={{ fontWeight: 'bold', color: '#f97316', borderBottom: '1px solid #1A1D21', paddingBottom: '4px', marginBottom: '4px' }}>{data.label}</p>
          <p style={{ fontWeight: 'bold' }}><span style={{ color: '#9ca3af', marginRight: '4px' }}>INCIDENTS:</span> {data.value} FIRES</p>
        </div>
      );
    }
    return null;
  };

  const DailyFrpTrendTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div style={{ backgroundColor: '#13151A', border: '1px solid #1A1D21', padding: '12px', borderRadius: '2px', boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)', fontFamily: 'Plus Jakarta Sans, sans-serif', fontSize: '10px', textTransform: 'uppercase', color: 'white', zIndex: 50 }}>
          <p style={{ fontWeight: 'bold', color: '#f59e0b', borderBottom: '1px solid #1A1D21', paddingBottom: '4px', marginBottom: '4px' }}>{data.label}</p>
          <p style={{ fontWeight: 'bold' }}><span style={{ color: '#9ca3af', marginRight: '4px' }}>TOTAL FRP:</span> {data.value.toLocaleString()} MW</p>
        </div>
      );
    }
    return null;
  };

  const [wilkerFilter, setWilkerFilter] = useState(lockedWilker || initialWilker || "");

  useEffect(() => {
    if (lockedWilker) {
      setWilkerFilter(lockedWilker);
    }
  }, [lockedWilker]);
  const [provinceFilter, setProvinceFilter] = useState("");
  const [skemaFilter, setSkemaFilter] = useState("");
  const [activeFrpCategory, setActiveFrpCategory] = useState<string | null>(null);
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [showAnalytics, setShowAnalytics] = useState(true);
  const [yoyMetric, setYoyMetric] = useState<"count" | "frp">("count");
  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 20;
  const [downloadingKpsKey, setDownloadingKpsKey] = useState<string | null>(null);
  const [kpsDownloadError, setKpsDownloadError] = useState<string | null>(null);

  // Frekuensi Kebakaran (data KLHK burned_area_summary) -- sumbernya beda
  // total dari `hotspots` (NASA FIRMS) yang dipakai groupedRows di bawah,
  // dan tidak terikat filter waktu/satelit dashboard, jadi di-fetch sendiri
  // sekali saat mount (bukan lewat useDashboardData).
  const [burnFrequency, setBurnFrequency] = useState<BurnFrequencyRecord[]>([]);
  useEffect(() => {
    let cancelled = false;
    api
      .getBurnFrequency()
      .then((response) => {
        if (!cancelled) {
          setBurnFrequency(response.rows);
        }
      })
      .catch(() => {
        /* diamkan -- kolom Frekuensi cukup tampil "-" kalau gagal, bukan
           kegagalan yang layak menghentikan seluruh Buku Besar */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Luas terbakar resmi Kementerian Kehutanan per FUNGSI kawasan hutan
  // (Jan-Jul 2026). Ikut filter provinsi Buku Besar -- di-fetch ulang tiap
  // filter provinsi berubah.
  const [burnedKawasan, setBurnedKawasan] = useState<BurnedAreaKawasanResponse | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .getBurnedAreaByKawasan(provinceFilter || undefined)
      .then((response) => {
        if (!cancelled) setBurnedKawasan(response);
      })
      .catch(() => {
        if (!cancelled) setBurnedKawasan(null);
      });
    return () => {
      cancelled = true;
    };
  }, [provinceFilter]);

  // Nama lembaga di data KLHK kadang punya whitespace tersisa (mis. "\r\n"
  // di akhir) -- di-trim di kedua sisi supaya tetap cocok dengan key dari
  // groupedRows (yang sumbernya beda tabel/pipeline sama sekali).
  const burnFrequencyByLembaga = useMemo(() => {
    const map = new Map<string, BurnFrequencyRecord>();
    burnFrequency.forEach((row) => {
      map.set(row.lembaga.trim(), row);
    });
    return map;
  }, [burnFrequency]);

function normalizeWilker(val?: string | null): string {
  if (!val) return "";
  const clean = val.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (clean.includes("kutai") || clean.includes("kurtanegara")) return "kutaikartanegara";
  return clean;
}

function matchWilker(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return false;
  return normalizeWilker(a) === normalizeWilker(b);
}

  // Cascading filter: Province options only show provinces that have hotspots
  // matching the current wilkerFilter (and confidence). So picking a Wilker
  // narrows down which Provinces appear, and vice-versa.
  const provinceOptions = useMemo(
    () =>
      Array.from(
        new Set(
          hotspots
            .filter((h) => {
              const wilkerMatch = wilkerFilter ? matchWilker(h.polygonMetadata.WILKER_BPS, wilkerFilter) : true;
              const frpMatch = activeFrpCategory ? getFrpCategory(h) === activeFrpCategory : true;
              const skemaMatch = skemaFilter ? getSkema(h) === skemaFilter : true;
              return wilkerMatch && frpMatch && skemaMatch;
            })
            .map((h) => h.provinceName)
            .filter((province): province is string => Boolean(province)),
        ),
      ).sort(),
    [hotspots, wilkerFilter, activeFrpCategory, skemaFilter],
  );

  // Cascading filter: Wilker options only show wilkers that have hotspots
  // matching the current provinceFilter (and confidence).
  const wilkerOptions = useMemo(
    () =>
      Array.from(
        new Set(
          hotspots
            .filter((h) => {
              const provinceMatch = provinceFilter ? h.provinceName === provinceFilter : true;
              const frpMatch = activeFrpCategory ? getFrpCategory(h) === activeFrpCategory : true;
              const skemaMatch = skemaFilter ? getSkema(h) === skemaFilter : true;
              return provinceMatch && frpMatch && skemaMatch;
            })
            .map((h) => h.polygonMetadata.WILKER_BPS)
            .filter((value): value is string => Boolean(value && value.trim())),
        ),
      ).sort(),
    [hotspots, provinceFilter, activeFrpCategory, skemaFilter],
  );

  // Opsi skema mengikuti pilihan wilker/provinsi/FRP yang sedang aktif, sama
  // seperti dua filter bertingkat di atasnya.
  const skemaOptions = useMemo(
    () =>
      Array.from(
        new Set(
          hotspots
            .filter((h) => {
              const wilkerMatch = wilkerFilter ? matchWilker(h.polygonMetadata.WILKER_BPS, wilkerFilter) : true;
              const provinceMatch = provinceFilter ? h.provinceName === provinceFilter : true;
              const frpMatch = activeFrpCategory ? getFrpCategory(h) === activeFrpCategory : true;
              return wilkerMatch && provinceMatch && frpMatch;
            })
            .map((h) => getSkema(h))
            .filter((value): value is string => Boolean(value && value.trim())),
        ),
      ).sort(),
    [hotspots, wilkerFilter, provinceFilter, activeFrpCategory],
  );

  const latestRegistrySync = useMemo(() => getLatestRegistrySync(geojsonStatus), [geojsonStatus]);

  // Determine groupBy granularity based on selected date range.
  // Dideklarasikan sebelum `filteredHotspots` karena filter periode di bawah
  // memakainya -- sebelumnya trendGroupBy dideklarasikan lebih ke bawah, jadi
  // begin diakses di sini kena Temporal Dead Zone dan React error persis saat
  // pengguna klik titik periode (baru saat itu `selectedPeriod` terisi dan
  // baris yang membaca trendGroupBy benar-benar dieksekusi).
  const trendGroupBy = useMemo((): 'day' | 'month' => {
    const s = timeRange?.startAt ?? (startDate ? new Date(startDate) : new Date());
    const e = timeRange?.endAt ?? (endDate ? new Date(endDate) : new Date());
    const monthsDiff = (e.getFullYear() - s.getFullYear()) * 12 + (e.getMonth() - s.getMonth());
    const daysDiff = (e.getTime() - s.getTime()) / (1000 * 60 * 60 * 24);
    return monthsDiff >= 1 || daysDiff > 35 ? 'month' : 'day';
  }, [timeRange, startDate, endDate]);

  const filteredHotspots = useMemo(
    () =>
      hotspots.filter((hotspot) => {
        const wilkerMatch = wilkerFilter
          ? matchWilker(hotspot.polygonMetadata.WILKER_BPS, wilkerFilter)
          : true;
        const provinceMatch = provinceFilter ? hotspot.provinceName === provinceFilter : true;
        const frpMatch = activeFrpCategory ? getFrpCategory(hotspot) === activeFrpCategory : true;
        const skemaMatch = skemaFilter ? getSkema(hotspot) === skemaFilter : true;

        let periodMatch = true;
        if (selectedPeriod) {
          const parts = getWibDateParts(hotspot.detectedAt);
          const periodKey = trendGroupBy === 'month' ? parts.yearMonthStr : parts.dateStr;
          periodMatch = periodKey === selectedPeriod;
        }

        let searchMatch = true;
        if (searchQuery) {
          const query = searchQuery.toLowerCase();
          const kpsValue = (hotspot.polygonMetadata.LEMBAGA || hotspot.agencyName).toLowerCase();
          const balaiPsValue = (hotspot.polygonMetadata.WILKER_BPS || "").toLowerCase();
          const provinsiValue = (hotspot.provinceName || hotspot.polygonMetadata.NAMA_PROV || "").toLowerCase();
          const kabupatenValue = (hotspot.polygonMetadata.NAMA_KAB || "").toLowerCase();

          searchMatch = kpsValue.includes(query) || balaiPsValue.includes(query) || provinsiValue.includes(query) || kabupatenValue.includes(query);
        }

        return wilkerMatch && provinceMatch && frpMatch && skemaMatch && periodMatch && searchMatch;
      }),
    [activeFrpCategory, hotspots, wilkerFilter, provinceFilter, skemaFilter, selectedPeriod, searchQuery, trendGroupBy],
  );

  const groupedRows = useMemo(() => {
    const groups: Record<string, typeof filteredHotspots> = {};
    filteredHotspots.forEach((hotspot) => {
      const ownerLabel = formatMetadataValue(hotspot.polygonMetadata.LEMBAGA || hotspot.agencyName);
      if (!groups[ownerLabel]) {
        groups[ownerLabel] = [];
      }
      groups[ownerLabel].push(hotspot);
    });

    return Object.entries(groups).map(([lembagaName, list]) => {
      const sortedList = [...list].sort(
        (a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime()
      );
      const representativeHotspot = sortedList[0];
      const count = list.length;
      const wilker = formatMetadataValue(representativeHotspot.polygonMetadata.WILKER_BPS);
      return {
        key: lembagaName,
        wilker,
        representativeHotspot,
        count,
        hotspots: sortedList
      };
    }).sort((a, b) => new Date(b.representativeHotspot.detectedAt).getTime() - new Date(a.representativeHotspot.detectedAt).getTime());
  }, [filteredHotspots]);

  // Reset filter bertingkat jika pilihan tidak lagi ada di opsi data baru
  useEffect(() => {
    if (provinceFilter && !provinceOptions.includes(provinceFilter)) {
      setProvinceFilter("");
    }
  }, [provinceOptions, provinceFilter]);

  useEffect(() => {
    if (wilkerFilter && !wilkerOptions.includes(wilkerFilter)) {
      setWilkerFilter("");
    }
  }, [wilkerOptions, wilkerFilter]);

  useEffect(() => {
    if (skemaFilter && !skemaOptions.includes(skemaFilter)) {
      setSkemaFilter("");
    }
  }, [skemaOptions, skemaFilter]);

  // Reset filter periode klik grafik jika rentang waktu atau filter utama berubah
  useEffect(() => {
    setSelectedPeriod(null);
  }, [timePreset, startDate, endDate, wilkerFilter, provinceFilter, skemaFilter, activeFrpCategory]);

  // Reset ke halaman 1 setiap kali filter berubah
  useEffect(() => {
    setCurrentPage(1);
  }, [wilkerFilter, provinceFilter, skemaFilter, activeFrpCategory, groupedRows.length]);

  const confidenceDistribution = useMemo(() => buildConfidenceDistribution(filteredHotspots), [filteredHotspots]);
  const frpDistribution = useMemo(() => buildFrpDistribution(filteredHotspots), [filteredHotspots]);
  const kawasanDistribution = useMemo(() => buildKawasanDistribution(filteredHotspots), [filteredHotspots]);
  const topWilker = useMemo(() => buildTopWilker(filteredHotspots), [filteredHotspots]);
  const skemaProvinsiMatrix = useMemo(
    () => buildSkemaProvinsiMatrix(filteredHotspots),
    [filteredHotspots],
  );
  const frpChartHeight = Math.max(220, frpDistribution.length * 28 + 44);
  const topWilkerChartHeight = Math.max(240, topWilker.length * 34 + 56);
  const analyticsChartHeight = Math.max(frpChartHeight, topWilkerChartHeight);

  const dailyTrend = useMemo(() => buildDailyTrend(filteredHotspots, trendGroupBy), [filteredHotspots, trendGroupBy]);
  const dailyFrpTrend = useMemo(() => buildDailyFrpTrend(filteredHotspots, trendGroupBy), [filteredHotspots, trendGroupBy]);
  const yoy = useMemo(() => buildYearOverYear(filteredHotspots), [filteredHotspots]);

  const handleSelectFrpCategory = (label: string | null) => {
    setActiveFrpCategory((current) => (current === label ? null : label));
  };

  // Filter waktu (dan filter toolbar lain) sudah diterapkan di client lewat
  // filteredHotspots -- itu persis apa yang ditampilkan di tabel, jadi
  // GeoJSON-nya dibangun langsung dari situ tanpa perlu bolak-balik ke server.
  const handleDownloadFilterGeojson = () => {
    if (filteredHotspots.length === 0) return;
    const featureCollection = {
      type: "FeatureCollection" as const,
      features: filteredHotspots.map(hotspotToGeoJsonFeature)
    };
    const rangeLabel = `${formatDateWIB(timeRange.startAt)}_${formatDateWIB(timeRange.endAt)}`;
    downloadGeoJson(featureCollection, `eta-seuneu-hotspots-${rangeLabel}.geojson`);
  };

  const handleDownloadKpsGeojson = async (group: (typeof groupedRows)[number]) => {
    setKpsDownloadError(null);
    setDownloadingKpsKey(group.key);
    try {
      const features: object[] = group.hotspots.map(hotspotToGeoJsonFeature);
      const polygonId = findLinkedPolygonId(group.hotspots);

      if (polygonId !== null) {
        const response = await authFetch(`/api/polygons/${polygonId}`);
        if (response.ok) {
          const detail = (await response.json()) as PolygonDetail;
          features.unshift(polygonDetailToGeoJsonFeature(detail));
        }
      }

      downloadGeoJson(
        { type: "FeatureCollection" as const, features },
        `eta-seuneu-kps-${slugifyFilename(group.key)}.geojson`
      );
    } catch {
      setKpsDownloadError(`Gagal mengunduh GeoJSON untuk ${group.key}.`);
    } finally {
      setDownloadingKpsKey(null);
    }
  };

  return (
    <section className="panel--matrix matrix-shell">
      <div className="matrix-header-bar glass-panel">
        <div className="matrix-header-copy">
          <p className="panel-eyebrow">Log Sebaran Hotspot Areal KPS</p>
          <h2>Matriks &amp; Rekapitulasi Data</h2>
          <p className="muted-copy">
            {dateRangeLabel} · {filteredHotspots.length} rekaman · {latestRegistrySync}
          </p>
        </div>

        <div className="matrix-header-actions">
          <button
            type="button"
            className="matrix-header-action"
            onClick={() => setShowAnalytics((current) => !current)}
          >
            {showAnalytics ? "Sembunyikan Grafik" : "Tampilkan Grafik"}
          </button>
          <button
            type="button"
            className="matrix-header-action matrix-header-action--ghost"
            onClick={() => onExport({
              province: provinceFilter || undefined,
              wilker: wilkerFilter || undefined,
              confidence: activeFrpCategory || undefined,
              skema: skemaFilter || undefined
            })}
            disabled={isExporting || filteredHotspots.length === 0}
          >
            {isExporting ? "Mengekspor..." : "Ekspor XLSX"}
          </button>
          <button
            type="button"
            className="matrix-header-action matrix-header-action--ghost"
            onClick={() => onExportPdf({
              province: provinceFilter || undefined,
              wilker: wilkerFilter || undefined,
              confidence: activeFrpCategory || undefined,
              skema: skemaFilter || undefined
            })}
            disabled={isExportingPdf || filteredHotspots.length === 0}
          >
            {isExportingPdf ? "Mengekspor..." : "Ekspor PDF"}
          </button>
          <button
            type="button"
            className="matrix-header-action matrix-header-action--ghost"
            onClick={handleDownloadFilterGeojson}
            disabled={filteredHotspots.length === 0}
            title="Unduh seluruh titik yang cocok dengan filter waktu & toolbar saat ini"
          >
            <Download size={14} />
            Unduh GeoJSON
          </button>
        </div>
      </div>
      {kpsDownloadError && <p className="matrix-download-error">{kpsDownloadError}</p>}

      <div className="matrix-toolbar glass-panel">
        <label className="matrix-field">
          <span>Filter Waktu</span>
          <select
            value={timePreset}
            onChange={(event) => onTimePresetChange(event.currentTarget.value as TimePreset)}
          >
            {TIME_PRESET_OPTIONS.map((preset) => (
              <option key={preset.value} value={preset.value}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>

        <label className="matrix-field">
          <span>Dari</span>
          <input
            type="date"
            value={startDate}
            disabled={timePreset !== "custom"}
            onChange={(event) => onDateChange("startDate", event.currentTarget.value)}
          />
        </label>

        <label className="matrix-field">
          <span>Ke</span>
          <input
            type="date"
            value={endDate}
            disabled={timePreset !== "custom"}
            onChange={(event) => onDateChange("endDate", event.currentTarget.value)}
          />
        </label>

        <label className="matrix-field">
          <span>Wilker Filter</span>
          <select
            value={wilkerFilter}
            disabled={Boolean(lockedWilker)}
            onChange={(event) => setWilkerFilter(event.currentTarget.value)}
          >
            {lockedWilker ? (
              <option value={lockedWilker}>{lockedWilker}</option>
            ) : (
              <>
                <option value="">Semua wilker</option>
                {wilkerOptions.map((wilker) => (
                  <option key={wilker} value={wilker}>
                    {wilker}
                  </option>
                ))}
              </>
            )}
          </select>
        </label>

        <label className="matrix-field">
          <span>Skema Filter</span>
          <select
            value={skemaFilter}
            onChange={(event) => setSkemaFilter(event.currentTarget.value)}
          >
            <option value="">Semua skema</option>
            {skemaOptions.map((skema) => (
              <option key={skema} value={skema}>
                {skema}
              </option>
            ))}
          </select>
        </label>

        <label className="matrix-field">
          <span>Provinsi Filter</span>
          <select
            value={provinceFilter}
            onChange={(event) => setProvinceFilter(event.currentTarget.value)}
          >
            <option value="">Semua provinsi</option>
            {provinceOptions.map((province) => (
              <option key={province} value={province}>
                {province}
              </option>
            ))}
          </select>
        </label>
      </div>

      {showAnalytics ? (
        <div className="matrix-analytics-grid">
          
          {renderCompactCard("Confidence", confidenceDistribution, filteredHotspots.length)}
          {renderCompactCard("FRP", frpDistribution, filteredHotspots.length, activeFrpCategory, handleSelectFrpCategory)}
          {renderCompactCard("Titik per Kawasan Hutan", kawasanDistribution, filteredHotspots.length)}
          {renderKawasanBurnedCard(burnedKawasan)}

          <SkemaProvinsiCard
            matrix={skemaProvinsiMatrix}
            activeSkema={skemaFilter}
            activeProvince={provinceFilter}
            onSelectSkema={(label) => setSkemaFilter((current) => (current === label ? "" : label))}
            onSelectProvince={(label) => setProvinceFilter((current) => (current === label ? "" : label))}
          />

          <BurnedAreaCard
            provinceFilter={provinceFilter}
            skemaFilter={skemaFilter}
            wilkerFilter={wilkerFilter}
            onSelectSkema={(label) => setSkemaFilter((current) => (current === label ? "" : label))}
          />

          <section className="matrix-chart-card matrix-chart-card--wide glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="matrix-chart-card__header">
              <div>
                <p className="panel-eyebrow">Peringkat WILKER</p>
                <h3>Hotspot per WILKER</h3>
              </div>
            </div>

            {topWilker.length === 0 ? (
              <div className="matrix-empty matrix-empty--card" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>Data hotspot tidak tersedia</div>
            ) : (
              <div style={{ width: '100%', height: 'clamp(240px, 50vw, 400px)', position: 'relative' }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={topWilker} layout="horizontal" margin={{ top: 24, right: 20, left: 20, bottom: 8 }} onClick={(state) => {
                    if (state && state.activeLabel) {
                      const label = String(state.activeLabel);
                      setWilkerFilter(label === wilkerFilter ? "" : label);
                      setCurrentPage(1);
                    }
                  }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.02)" vertical={false} />
                    <XAxis dataKey="label" stroke="rgba(255,255,255,0.2)" tick={{ fill: "rgba(255,255,255,0.5)", fontSize: 8, fontFamily: 'Plus Jakarta Sans, sans-serif' }} axisLine={false} tickLine={false} />
                    <YAxis hide />
                    <ChartTooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.01)' }} />
                    <Bar dataKey="value" fill="#FF4E00" radius={[4, 4, 0, 0]} background={{ fill: 'rgba(255,255,255,0.03)', radius: 4 }} barSize={16} isAnimationActive={false} style={{ cursor: 'pointer' }}>
                      <LabelList dataKey="value" position="top" fill="rgba(255,255,255,0.7)" fontSize={10} fontFamily="Plus Jakarta Sans, sans-serif" offset={8} />
                      {topWilker.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={wilkerFilter === entry.label ? '#FF6B35' : (entry.color || '#FF4E00')} opacity={wilkerFilter === entry.label ? 1 : 0.85} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section className="matrix-chart-card matrix-chart-card--wide glass-panel" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="matrix-chart-card__header">
              <div>
                <p className="panel-eyebrow">Analitik Tren</p>
                <h3>{trendGroupBy === 'month' ? 'Tren Volume Bulanan' : 'Tren Volume Harian'}</h3>
              </div>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              <p className="matrix-spark-title" style={{ flexShrink: 0, marginBottom: '12px' }}>
                {trendGroupBy === 'month' ? 'Volume Insiden Bulanan' : 'Volume Insiden Harian'}
              </p>
              {dailyTrend.length === 0 ? (
                <div className="matrix-empty matrix-empty--card" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '240px', color: '#9ca3af' }}>
                  Belum tersedia data untuk rentang waktu yang dipilih.
                </div>
              ) : (
                <div style={{ width: '100%', height: 'clamp(200px, 45vw, 350px)', position: 'relative' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={dailyTrend} margin={{ top: 20, right: 30, left: 10, bottom: 8 }} onClick={(state) => {
                      if (state && state.activeLabel) {
                        const label = String(state.activeLabel);
                        setSelectedPeriod(label === selectedPeriod ? null : label);
                        setCurrentPage(1);
                      }
                    }}>
                      <defs>
                        <linearGradient id="dailyTrendGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={selectedPeriod ? "rgba(249, 115, 22, 0.2)" : "rgba(249, 115, 22, 0.4)"}/>
                          <stop offset="95%" stopColor="#f97316" stopOpacity={0.0}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.02)" vertical={false} />
                      <XAxis dataKey="label" stroke="rgba(255,255,255,0.2)" tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 8, fontFamily: 'Plus Jakarta Sans, sans-serif' }} axisLine={false} tickLine={false} tickFormatter={(val) => { if (typeof val !== 'string') return ''; return trendGroupBy === 'month' ? val.slice(0, 7) : val.slice(8, 10); }} />
                      <YAxis stroke="rgba(255,255,255,0.2)" tick={{ fill: "rgba(255,255,255,0.4)", fontSize: 8, fontFamily: 'Plus Jakarta Sans, sans-serif' }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <ChartTooltip content={<DailyTrendTooltip />} />
                      <Area type="monotone" dataKey="value" stroke={selectedPeriod ? "#FF6B35" : "#f97316"} strokeWidth={selectedPeriod ? 3 : 2} fill="url(#dailyTrendGradient)" isAnimationActive={false} style={{ cursor: 'pointer' }}>
                        <LabelList dataKey="value" position="top" fill="rgba(255,255,255,0.7)" fontSize={10} fontFamily="Plus Jakarta Sans, sans-serif" offset={8} />
                      </Area>
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </section>
        </div>
      ) : null}

      <div className="matrix-workbench">
        <section className="matrix-ledger glass-panel">
          <div className="matrix-ledger-head">
            <div>
              <p className="panel-eyebrow">Buku Besar</p>
              <h3>Baris Hotspot</h3>
            </div>
            <div className="matrix-ledger-summary">
              <span>{filteredHotspots.length} terlihat</span>
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                {wilkerFilter && (
                  <>
                    <span style={{ backgroundColor: 'rgba(255, 107, 53, 0.2)', color: '#FF6B35', padding: '0.25rem 0.5rem', borderRadius: '0.25rem', fontSize: '0.8rem', fontWeight: '500' }}>
                      WILKER: {wilkerFilter}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setWilkerFilter("");
                        setCurrentPage(1);
                      }}
                      style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem', cursor: 'pointer', background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', borderRadius: '0.2rem' }}
                    >
                      ✕
                    </button>
                  </>
                )}
                {skemaFilter && (
                  <>
                    <span style={{ backgroundColor: 'rgba(20, 184, 166, 0.2)', color: '#2dd4bf', padding: '0.25rem 0.5rem', borderRadius: '0.25rem', fontSize: '0.8rem', fontWeight: '500' }}>
                      SKEMA: {skemaFilter}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setSkemaFilter("");
                        setCurrentPage(1);
                      }}
                      style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem', cursor: 'pointer', background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', borderRadius: '0.2rem' }}
                    >
                      ✕
                    </button>
                  </>
                )}
                {selectedPeriod && (
                  <>
                    <span style={{ backgroundColor: 'rgba(249, 115, 22, 0.2)', color: '#FF8C00', padding: '0.25rem 0.5rem', borderRadius: '0.25rem', fontSize: '0.8rem', fontWeight: '500' }}>
                      PERIODE: {trendGroupBy === 'month' ? selectedPeriod.slice(0, 7) : selectedPeriod.slice(8, 10)} {trendGroupBy === 'day' && selectedPeriod.slice(0, 7)}
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedPeriod(null);
                        setCurrentPage(1);
                      }}
                      style={{ fontSize: '0.75rem', padding: '0.2rem 0.4rem', cursor: 'pointer', background: 'rgba(255,255,255,0.1)', border: 'none', color: '#fff', borderRadius: '0.2rem' }}
                    >
                      ✕
                    </button>
                  </>
                )}
                <span>{activeFrpCategory ? `FRP: ${activeFrpCategory}` : "Tidak ada saringan FRP"}</span>
              </div>
            </div>
          </div>

          {filteredHotspots.length === 0 ? (
            <div style={{ padding: '2rem 1rem', textAlign: 'center' }}>
              <div className="matrix-empty matrix-empty--card" style={{ marginBottom: searchQuery ? '1.5rem' : 0 }}>
                Tidak ada hotspot ditemukan
              </div>
              {searchQuery && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '1rem', flexDirection: 'column' }}>
                  <p style={{ fontSize: '0.9rem', color: '#9ca3af', margin: 0 }}>
                    Tidak ada hasil untuk "<strong style={{ color: '#f3f4f6' }}>{searchQuery}</strong>"
                  </p>
                  <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                    <button
                      type="button"
                      onClick={() => {
                        setSearchQuery("");
                        setCurrentPage(1);
                      }}
                      style={{
                        minHeight: '44px',
                        minWidth: '44px',
                        padding: '0.5rem 1rem',
                        fontSize: '0.85rem',
                        background: 'rgba(255, 107, 53, 0.2)',
                        border: '1px solid rgba(255, 107, 53, 0.5)',
                        color: '#FF6B35',
                        borderRadius: '0.25rem',
                        cursor: 'pointer',
                        fontWeight: '500',
                        fontFamily: 'inherit',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center'
                      }}
                    >
                      Clear Search
                    </button>
                    <span style={{ fontSize: '0.8rem', color: '#6b7280' }}>atau tekan Escape</span>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <>
              {/* Style dipindah ke CSS (.ledger-search*): sebelumnya inline,
                  sehingga media query mobile tidak bisa memadatkannya tanpa
                  !important dan bar ini memakan 170px tinggi di layar kecil. */}
              <div className="ledger-search">
                <svg className="ledger-search__icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.35-4.35" />
                </svg>
                <input
                  type="text"
                  className="ledger-search__input"
                  aria-label="Cari hotspot"
                  placeholder="Cari KPS, Balai PS…"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      setSearchQuery(searchInput);
                      setCurrentPage(1);
                    } else if (e.key === 'Escape') {
                      setSearchInput("");
                      setSearchQuery("");
                      setCurrentPage(1);
                    }
                  }}
                />
                {searchInput && (
                  <button
                    type="button"
                    className="ledger-search__clear"
                    onClick={() => {
                      setSearchInput("");
                      setSearchQuery("");
                      setCurrentPage(1);
                    }}
                    aria-label="Bersihkan pencarian"
                    title="Bersihkan pencarian"
                  >
                    ✕
                  </button>
                )}
                <button
                  type="button"
                  className="ledger-search__submit"
                  onClick={() => {
                    setSearchQuery(searchInput);
                    setCurrentPage(1);
                  }}
                >
                  Cari
                </button>
              </div>
              <div className="matrix-table-wrap">
              <div className="matrix-scroll">
                <table className="matrix-table">
                  <thead>
                    <tr>
                      <th className="th-no" scope="col">No.</th>
                      <th scope="col">KPS</th>
                      <th scope="col">Balai PS</th>
                      <th scope="col">Jumlah</th>
                      <th scope="col">Terdeteksi</th>
                      <th scope="col">Lat / Lon</th>
                      <th scope="col">Provinsi</th>
                      <th scope="col">FRP</th>
                      <th scope="col">Satelit</th>
                      <th scope="col">Frekuensi</th>
                      <th scope="col">Periode</th>
                      <th className="th-aksi" scope="col">Aksi</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedRows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE).map((group, index) => {
                      const hotspot = group.representativeHotspot;
                      const freq = burnFrequencyByLembaga.get(group.key.trim());
                      const rowNumber = (currentPage - 1) * PAGE_SIZE + index + 1;

                      return (
                        <tr
                          key={group.key}
                          onClick={() => onOpenKpsDetail?.(group.key)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              onOpenKpsDetail?.(group.key);
                            }
                          }}
                        >
                          <td className="td-no" data-label="No.">
                            {rowNumber}
                          </td>
                          <td className="td-kps" data-label="KPS">
                            <div className="matrix-satellite">
                              <strong>{group.key}</strong>
                              {group.key !== hotspot.layerName && (
                                <span className="td-kps__sub">{hotspot.layerName}</span>
                              )}
                            </div>
                          </td>
                          <td className="td-balai" data-label="Balai PS">
                            {group.wilker || '-'}
                          </td>
                          <td className="td-jumlah" data-label="Jumlah">
                            <span className="matrix-id-badge matrix-id-badge--count">
                              {group.count} titik
                            </span>
                          </td>
                          <td className="td-waktu" data-label="Terdeteksi">{formatTimestamp(hotspot.detectedAt)}</td>
                          <td className="td-koord" data-label="Lat/Lon">
                            {hotspot.latitude.toFixed(3)}, {hotspot.longitude.toFixed(3)}
                          </td>
                          <td className="td-prov" data-label="Provinsi">{formatMetadataValue(hotspot.provinceName || hotspot.polygonMetadata.NAMA_PROV)}</td>
                          <td className="td-frp" data-label="FRP">
                            <span className={`confidence-pill confidence-pill--${getFrpCategory(hotspot) === 'Tinggi' ? 'high' : getFrpCategory(hotspot) === 'Sedang' ? 'nominal' : 'low'}`}>
                              {normalizeFrpCategoryLabel(hotspot)}
                            </span>
                          </td>
                          {/* source dan satellite sebelumnya dua elemen tanpa pemisah;
                              di mode kartu keduanya menyatu jadi "VIIRS NOAA-21N21". */}
                          <td className="td-satelit" data-label="Satelit">
                            <div className="matrix-satellite">
                              <strong>{hotspot.source}</strong>
                              {hotspot.satellite && hotspot.satellite !== hotspot.source && (
                                <span className="td-satelit__sub">{hotspot.satellite}</span>
                              )}
                            </div>
                          </td>
                          <td className="td-frekuensi" data-label="Frekuensi">
                            {freq ? (
                              <span
                                className={`confidence-pill confidence-pill--freq-${
                                  freq.periode_terbakar >= 4
                                    ? "tinggi"
                                    : freq.periode_terbakar >= 2
                                      ? "sedang"
                                      : "rendah"
                                }`}
                              >
                                {freq.periode_terbakar}&times;
                              </span>
                            ) : (
                              <span className="muted-copy">-</span>
                            )}
                          </td>
                          <td className="td-periode" data-label="Periode">
                            {freq ? (
                              <span className="td-periode__range">
                                {formatPeriodeSingkat(freq.pertama)}
                                {freq.pertama !== freq.terakhir && (
                                  <> &ndash; {formatPeriodeSingkat(freq.terakhir)}</>
                                )}
                              </span>
                            ) : (
                              <span className="muted-copy">-</span>
                            )}
                          </td>
                          <td className="td-aksi" data-label="Aksi">
                            <button
                              type="button"
                              className="matrix-row-download"
                              onClick={(event) => {
                                event.stopPropagation();
                                void handleDownloadKpsGeojson(group);
                              }}
                              disabled={downloadingKpsKey === group.key}
                              title={`Unduh GeoJSON untuk ${group.key}`}
                            >
                              <Download size={14} />
                              {downloadingKpsKey === group.key && (
                                <span className="matrix-row-download__label">Mengunduh...</span>
                              )}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="matrix-footer">
                <span className="matrix-footer__count">
                  {groupedRows.length} lembaga ({filteredHotspots.length} titik)
                </span>
                <div className="matrix-pagination">
                  <button
                    type="button"
                    className="matrix-page-btn"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    aria-label="Halaman sebelumnya"
                  >
                    ‹
                  </button>
                  <span className="matrix-page-info">
                    Halaman {currentPage} / {Math.max(1, Math.ceil(groupedRows.length / PAGE_SIZE))}
                  </span>
                  <button
                    type="button"
                    className="matrix-page-btn"
                    onClick={() => setCurrentPage((p) => Math.min(Math.ceil(groupedRows.length / PAGE_SIZE), p + 1))}
                    disabled={currentPage >= Math.ceil(groupedRows.length / PAGE_SIZE)}
                    aria-label="Halaman berikutnya"
                  >
                    ›
                  </button>
                </div>
              </div>
            </div>
              </>
          )}
        </section>

        {/* Panel "Laporan Deteksi Spesifik" sekarang jadi bagian dari halaman
            detail KPS (lihat KpsDetailView.tsx) -- dulu di sini sebagai
            drawer sempit dengan scroll bertingkat (drawer di dalam halaman
            yang sudah scroll sendiri). */}
      </div>

      <div className="matrix-footer">
        <span>STATUS: READY</span>
        <span>{filteredHotspots.length} RECORDS FOUND</span>
      </div>
    </section>
  );
}
