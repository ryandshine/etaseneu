import { useEffect, useMemo, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, ResponsiveContainer, AreaChart, Area, Cell, LabelList } from "recharts";
import { Flame } from "lucide-react";

import type { GeoJsonStatusResponse } from "../types/api";
import { getTodayWIB } from "../lib/date";

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
};

type HotspotMatrixProps = {
  hotspots: MatrixHotspot[];
  geojsonStatus: GeoJsonStatusResponse | null;
  onExport: (filters: { province?: string; wilker?: string; confidence?: string }) => void;
  isExporting: boolean;
  onExportPdf: (filters: { province?: string; wilker?: string; confidence?: string }) => void;
  isExportingPdf: boolean;
  startDate: string;
  endDate: string;
  dateRangeLabel: string;
  onDateChange: (field: "startDate" | "endDate", value: string) => void;
};

type QuerySection = {
  title: string;
  items: Array<[string, string]>;
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

function formatTimestamp(value: string) {
  const parsed = parseDateTime(value);
  if (!parsed) {
    return "Tidak Diketahui";
  }

  try {
    const formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Jakarta",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
    const parts = formatter.formatToParts(parsed);
    const year = parts.find(p => p.type === "year")?.value ?? "";
    const month = parts.find(p => p.type === "month")?.value ?? "";
    const day = parts.find(p => p.type === "day")?.value ?? "";
    const hour = parts.find(p => p.type === "hour")?.value ?? "";
    const minute = parts.find(p => p.type === "minute")?.value ?? "";
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  } catch (e) {
    const wibTime = new Date(parsed.getTime() + 7 * 60 * 60 * 1000);
    const day = String(wibTime.getUTCDate()).padStart(2, '0');
    const month = String(wibTime.getUTCMonth() + 1).padStart(2, '0');
    const year = wibTime.getUTCFullYear();
    const hour = String(wibTime.getUTCHours()).padStart(2, '0');
    const minute = String(wibTime.getUTCMinutes()).padStart(2, '0');
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  }
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

function formatNumber(value: number | null, digits = 2) {
  if (value === null || Number.isNaN(value)) {
    return "Tidak Tersedia";
  }

  return value.toFixed(digits);
}

function formatMetadataValue(value?: string) {
  return value && value.trim() ? value : "-";
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

function getFrpCategory(hotspot: MatrixHotspot) {
  const frp = hotspot.frp ?? 0;
  if (frp > 30) return "Tinggi";
  if (frp >= 10) return "Sedang";
  return "Rendah";
}

function normalizeFrpCategoryLabel(hotspot: MatrixHotspot) {
  return getFrpCategory(hotspot);
}

function getStatusLabel(hotspot: MatrixHotspot) {
  const metadata = hotspot.polygonMetadata ?? {};
  return formatMetadataValue(metadata.Status) || getFrpCategory(hotspot);
}

function getStatusTone(statusLabel: string) {
  const normalized = statusLabel.toLowerCase();

  if (
    normalized.includes("33") ||
    normalized.includes("active") ||
    normalized.includes("matched") ||
    normalized.includes("ready")
  ) {
    return "accent";
  }

  if (normalized.includes("low") || normalized.includes("inactive") || normalized.includes("missing")) {
    return "soft";
  }

  return "warm";
}

function buildQuerySections(hotspot: MatrixHotspot): QuerySection[] {
  const metadata = hotspot.polygonMetadata ?? {};
  return [
    {
      title: "Hotspot",
      items: [
        ["Sumber", formatMetadataValue(hotspot.source)],
        ["Satelit", formatMetadataValue(hotspot.satellite)],
        ["Siang/Malam", formatMetadataValue(hotspot.daynight)],
        ["Kecerahan", formatNumber(hotspot.brightness)],
        ["FRP", formatNumber(hotspot.frp)],
        ["Kategori FRP", getFrpCategory(hotspot)],
        ["Lintang", hotspot.latitude.toFixed(5)],
        ["Bujur", hotspot.longitude.toFixed(5)],
        ["Terdeteksi", formatTimestamp(hotspot.detectedAt)]
      ]
    },
    {
      title: "Lokasi",
      items: [
        ["NAMA_PROV", formatMetadataValue(hotspot.provinceName || metadata.NAMA_PROV)],
        ["NAMA_KAB", formatMetadataValue(metadata.NAMA_KAB)],
        ["NAMA_KEC", formatMetadataValue(metadata.NAMA_KEC)],
        ["NAMA_DESA", formatMetadataValue(metadata.NAMA_DESA)],
        ["WILKER_BPS", formatMetadataValue(metadata.WILKER_BPS)]
      ]
    },
    {
      title: "Poligon",
      items: [
        ["LEMBAGA", formatMetadataValue(metadata.LEMBAGA || hotspot.agencyName)],
        ["SKEMA", formatMetadataValue(metadata.SKEMA)],
        ["Status", formatMetadataValue(metadata.Status)],
        ["OBJECTID_1", formatMetadataValue(metadata.OBJECTID_1)],
        ["PS_ID", formatMetadataValue(metadata.PS_ID)],
        ["KODE_PROV", formatMetadataValue(metadata.KODE_PROV)],
        ["KODE_KAB", formatMetadataValue(metadata.KODE_KAB)],
        ["NO_SK", formatMetadataValue(metadata.NO_SK)],
        ["TGL_SK", formatMetadataValue(metadata.TGL_SK)],
        ["LuasFinal", formatMetadataValue(metadata.LuasFinal)],
        ["Jml_KK", formatMetadataValue(metadata.Jml_KK)]
      ]
    }
  ];
}

function buildFrpDistribution(hotspots: MatrixHotspot[]): ChartItem[] {
  return FRP_CATEGORIES.map((bin) => ({
    ...bin,
    value: hotspots.filter((hotspot) => getFrpCategory(hotspot) === bin.label).length,
  }));
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

function buildComparison(hotspots: MatrixHotspot[], selectedHotspot: MatrixHotspot | null) {
  const totalFrp = hotspots.reduce((sum, hotspot) => sum + (hotspot.frp ?? 0), 0);
  const totalBrightness = hotspots.reduce((sum, hotspot) => sum + (hotspot.brightness ?? 0), 0);
  const count = hotspots.length || 1;
  const maxFrp = hotspots.reduce((max, hotspot) => Math.max(max, hotspot.frp ?? 0), 0);
  const maxBrightness = hotspots.reduce((max, hotspot) => Math.max(max, hotspot.brightness ?? 0), 0);
  const selectedFrp = selectedHotspot?.frp ?? 0;
  const selectedBrightness = selectedHotspot?.brightness ?? 0;

  return {
    frp: [
      { label: "Rata-rata Global", value: Math.round((totalFrp / count) * 10) / 10, color: "rgba(255,255,255,0.15)" },
      { label: "Kebakaran Terpilih", value: Math.round(selectedFrp * 10) / 10, color: "rgba(245, 158, 11, 0.6)" },
      { label: "Maksimum Global", value: Math.round(maxFrp * 10) / 10, color: "rgba(239, 68, 68, 0.45)" }
    ],
    brightness: [
      { label: "Rata-rata Global", value: Math.round((totalBrightness / count) * 10) / 10, color: "rgba(255,255,255,0.15)" },
      { label: "Kebakaran Terpilih", value: Math.round(selectedBrightness * 10) / 10, color: "rgba(20, 184, 166, 0.6)" },
      { label: "Maksimum Global", value: Math.round(maxBrightness * 10) / 10, color: "rgba(239, 68, 68, 0.45)" }
    ]
  };
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


function renderCompactCard(title: string, data: any[], total: number, activeLabel: string | null = null, onClick: ((label: string | null) => void) | null = null) {
  const maxVal = Math.max(...data.map(d => d.value), 1);
  const domCategory = [...data].sort((a, b) => b.value - a.value)[0];
  
  return (
    <section className="matrix-chart-card glass-panel" style={{ display: 'flex', flexDirection: 'column', padding: '1.25rem', height: 'auto', minHeight: 'unset' }}>
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

      <div style={{ marginTop: '1.25rem', paddingTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.08)', fontSize: '0.75rem', color: '#9ca3af', lineHeight: 1.5 }}>
        Mayoritas hotspot memiliki {title.toLowerCase().includes('confidence') ? 'confidence' : 'intensitas FRP'} <strong style={{ color: '#fff' }}>{domCategory?.label || '-'}</strong> ({total > 0 ? Math.round(((domCategory?.value || 0) / total) * 100) : 0}%).
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
  dateRangeLabel
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

  const [wilkerFilter, setWilkerFilter] = useState("");
  const [provinceFilter, setProvinceFilter] = useState("");
  const [activeFrpCategory, setActiveFrpCategory] = useState<string | null>(null);
  const [selectedPeriod, setSelectedPeriod] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedHotspot, setSelectedHotspot] = useState<MatrixHotspot | null>(null);
  const [showAnalytics, setShowAnalytics] = useState(true);
  const [yoyMetric, setYoyMetric] = useState<"count" | "frp">("count");
  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 20;

  // Cascading filter: Province options only show provinces that have hotspots
  // matching the current wilkerFilter (and confidence). So picking a Wilker
  // narrows down which Provinces appear, and vice-versa.
  const provinceOptions = useMemo(
    () =>
      Array.from(
        new Set(
          hotspots
            .filter((h) => {
              const wilkerMatch = wilkerFilter ? h.polygonMetadata.WILKER_BPS === wilkerFilter : true;
              const frpMatch = activeFrpCategory ? getFrpCategory(h) === activeFrpCategory : true;
              return wilkerMatch && frpMatch;
            })
            .map((h) => h.provinceName)
            .filter((province): province is string => Boolean(province)),
        ),
      ).sort(),
    [hotspots, wilkerFilter, activeFrpCategory],
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
              return provinceMatch && frpMatch;
            })
            .map((h) => h.polygonMetadata.WILKER_BPS)
            .filter((value): value is string => Boolean(value && value.trim())),
        ),
      ).sort(),
    [hotspots, provinceFilter, activeFrpCategory],
  );

  const latestRegistrySync = useMemo(() => getLatestRegistrySync(geojsonStatus), [geojsonStatus]);

  const filteredHotspots = useMemo(
    () =>
      hotspots.filter((hotspot) => {
        const wilkerMatch = wilkerFilter
          ? hotspot.polygonMetadata.WILKER_BPS === wilkerFilter
          : true;
        const provinceMatch = provinceFilter ? hotspot.provinceName === provinceFilter : true;
        const frpMatch = activeFrpCategory ? getFrpCategory(hotspot) === activeFrpCategory : true;

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

        return wilkerMatch && provinceMatch && frpMatch && periodMatch && searchMatch;
      }),
    [activeFrpCategory, hotspots, wilkerFilter, provinceFilter, selectedPeriod, searchQuery],
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

  // Reset ke halaman 1 setiap kali filter berubah
  useEffect(() => {
    setCurrentPage(1);
  }, [wilkerFilter, provinceFilter, activeFrpCategory, groupedRows.length]);

  const selectedLembagaHotspots = useMemo(() => {
    if (!selectedHotspot) return [];
    const targetOwner = formatMetadataValue(selectedHotspot.polygonMetadata.LEMBAGA || selectedHotspot.agencyName);
    return filteredHotspots.filter(
      (h) => formatMetadataValue(h.polygonMetadata.LEMBAGA || h.agencyName) === targetOwner
    ).sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime());
  }, [selectedHotspot, filteredHotspots]);

    const confidenceDistribution = useMemo(() => buildConfidenceDistribution(filteredHotspots), [filteredHotspots]);
const frpDistribution = useMemo(() => buildFrpDistribution(filteredHotspots), [filteredHotspots]);
  const topWilker = useMemo(() => buildTopWilker(filteredHotspots), [filteredHotspots]);
  const frpChartHeight = Math.max(220, frpDistribution.length * 28 + 44);
  const topWilkerChartHeight = Math.max(240, topWilker.length * 34 + 56);
  const analyticsChartHeight = Math.max(frpChartHeight, topWilkerChartHeight);
  // Determine groupBy granularity based on selected date range
  const trendGroupBy = useMemo((): 'day' | 'month' => {
    if (!startDate || !endDate) return 'day';
    const s = new Date(startDate);
    const e = new Date(endDate);
    const monthsDiff = (e.getFullYear() - s.getFullYear()) * 12 + (e.getMonth() - s.getMonth());
    return monthsDiff >= 1 ? 'month' : 'day';
  }, [startDate, endDate]);

  const dailyTrend = useMemo(() => buildDailyTrend(filteredHotspots, trendGroupBy), [filteredHotspots, trendGroupBy]);
  const dailyFrpTrend = useMemo(() => buildDailyFrpTrend(filteredHotspots, trendGroupBy), [filteredHotspots, trendGroupBy]);
  const yoy = useMemo(() => buildYearOverYear(filteredHotspots), [filteredHotspots]);
  const comparison = useMemo(
    () => buildComparison(filteredHotspots, selectedHotspot),
    [filteredHotspots, selectedHotspot],
  );

  const selectedSummary = useMemo(() => {
    if (!selectedHotspot) {
      return null;
    }

    return {
      owner: formatMetadataValue(selectedHotspot.polygonMetadata.LEMBAGA || selectedHotspot.agencyName),
      province: formatMetadataValue(selectedHotspot.provinceName || selectedHotspot.polygonMetadata.NAMA_PROV),
      source: formatMetadataValue(selectedHotspot.source),
      satellite: formatMetadataValue(selectedHotspot.satellite),
      daynight: formatMetadataValue(selectedHotspot.daynight),
      detected: formatTimestamp(selectedHotspot.detectedAt),
      status: formatMetadataValue(getStatusLabel(selectedHotspot))
    };
  }, [selectedHotspot]);

  const selectedSections = useMemo(() => (selectedHotspot ? buildQuerySections(selectedHotspot) : []), [selectedHotspot]);

  const handleSelectFrpCategory = (label: string | null) => {
    setActiveFrpCategory((current) => (current === label ? null : label));
  };

  const detailRows = selectedHotspot
    ? [
        ["Pemilik", selectedSummary?.owner ?? "-"],
        ["Provinsi", selectedSummary?.province ?? "-"],
        ["Sumber", selectedSummary?.source ?? "-"],
        ["Satelit", selectedSummary?.satellite ?? "-"],
        ["Siang/Malam", selectedSummary?.daynight ?? "-"],
        ["Terdeteksi", selectedSummary?.detected ?? "-"]
      ]
    : [];

  return (
    <section className="panel panel--matrix matrix-shell">
      <div className="matrix-header-bar glass-panel">
        <div className="matrix-header-copy">
          <p className="panel-eyebrow">Log Riwayat Irisan Hotspot</p>
          <h2>Matriks Intersep</h2>
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
              confidence: activeFrpCategory || undefined
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
              confidence: activeFrpCategory || undefined
            })}
            disabled={isExportingPdf || filteredHotspots.length === 0}
          >
            {isExportingPdf ? "Mengekspor..." : "Ekspor PDF"}
          </button>
        </div>
      </div>

      <div className="matrix-toolbar glass-panel">
        <div className="matrix-filter-block matrix-filter-block--dates">
          <span className="matrix-filter-label">Rentang Tanggal</span>
          <div
            className="field-grid field-grid--matrix-dates"
            style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "0.45rem" }}
          >
            <label className="matrix-field">
              <span>Dari</span>
              <input
                type="date"
                value={startDate}
                onChange={(event) => onDateChange("startDate", event.currentTarget.value)}
              />
            </label>
            <label className="matrix-field">
              <span>Ke</span>
              <input
                type="date"
                value={endDate}
                onChange={(event) => onDateChange("endDate", event.currentTarget.value)}
              />
            </label>
          </div>
        </div>

        <label className="matrix-field">
          <span>Wilker Filter</span>
          <select
            value={wilkerFilter}
            onChange={(event) => setWilkerFilter(event.currentTarget.value)}
          >
            <option value="">Semua wilker</option>
            {wilkerOptions.map((wilker) => (
              <option key={wilker} value={wilker}>
                {wilker}
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
              <div style={{ width: '100%', height: 240, position: 'relative' }}>
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
                    <Bar dataKey="value" fill="#FF4E00" radius={[4, 4, 0, 0]} background={{ fill: 'rgba(255,255,255,0.03)', radius: 4 }} barSize={16} style={{ cursor: 'pointer' }}>
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
                <div style={{ width: '100%', height: 240, position: 'relative' }}>
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
                      <Area type="monotone" dataKey="value" stroke={selectedPeriod ? "#FF6B35" : "#f97316"} strokeWidth={selectedPeriod ? 3 : 2} fill="url(#dailyTrendGradient)" isAnimationActive={true} style={{ cursor: 'pointer' }}>
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
        <section className={`matrix-ledger glass-panel${selectedHotspot ? " matrix-ledger--split" : ""}`}>
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
            <div className="matrix-empty matrix-empty--card">Tidak ada hotspot ditemukan</div>
          ) : (
            <>
              <div style={{ padding: '1rem', marginBottom: '0.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', background: 'rgba(255, 255, 255, 0.05)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '0.5rem', padding: '0.75rem 1rem' }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ color: '#9ca3af', flexShrink: 0 }}>
                    <circle cx="11" cy="11" r="8" />
                    <path d="m21 21-4.35-4.35" />
                  </svg>
                  <input
                    type="text"
                    placeholder="Cari KPS, Balai PS, Provinsi, Kabupaten"
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setCurrentPage(1);
                    }}
                    style={{
                      flex: 1,
                      padding: 0,
                      fontSize: '0.95rem',
                      background: 'transparent',
                      border: 'none',
                      color: '#f3f4f6',
                      outline: 'none',
                      fontFamily: 'inherit'
                    }}
                  />
                  {searchQuery && (
                    <button
                      type="button"
                      onClick={() => {
                        setSearchQuery("");
                        setCurrentPage(1);
                      }}
                      style={{
                        fontSize: '1.2rem',
                        padding: '0.25rem 0.5rem',
                        cursor: 'pointer',
                        background: 'rgba(255,255,255,0.1)',
                        border: 'none',
                        color: '#fff',
                        borderRadius: '0.25rem',
                        flexShrink: 0
                      }}
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>
              <div className="matrix-table-wrap">
              <div className="matrix-scroll">
                <table className="matrix-table">
                  <thead>
                    <tr>
                      <th>KPS</th>
                      <th>Balai PS</th>
                      <th>Jumlah Hotspot</th>
                      <th>Most Recent Detected</th>
                      <th>Lat / Lon</th>
                      <th>Provinsi</th>
                      <th>FRP Conf %</th>
                      <th>Satelit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedRows.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE).map((group) => {
                      const hotspot = group.representativeHotspot;
                      const statusLabel = getStatusLabel(hotspot);
                      const statusTone = getStatusTone(statusLabel);
                      const isSelected = selectedHotspot && formatMetadataValue(selectedHotspot.polygonMetadata.LEMBAGA || selectedHotspot.agencyName) === group.key;

                      return (
                        <tr
                          key={group.key}
                          className={isSelected ? "matrix-row-selected" : undefined}
                          onClick={() => setSelectedHotspot(hotspot)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedHotspot(hotspot);
                            }
                          }}
                        >
                          <td>
                            <div className="matrix-satellite">
                              <strong>{group.key}</strong>
                              {group.key !== hotspot.layerName && (
                                <span style={{ opacity: 0.65 }}>{hotspot.layerName}</span>
                              )}
                            </div>
                          </td>
                          <td>
                            <span style={{ fontSize: '0.85rem', color: '#d1d5db' }}>
                              {group.wilker || '-'}
                            </span>
                          </td>
                          <td>
                            <span className="matrix-id-badge" style={{ backgroundColor: '#ff8c4224', color: '#ffb86b' }}>
                              {group.count} point{group.count > 1 ? "s" : ""}
                            </span>
                          </td>
                          <td>{formatTimestamp(hotspot.detectedAt)}</td>
                          <td>
                            {hotspot.latitude.toFixed(3)}, {hotspot.longitude.toFixed(3)}
                          </td>
                          <td>{formatMetadataValue(hotspot.provinceName || hotspot.polygonMetadata.NAMA_PROV)}</td>
                          <td>
                            <span className={`confidence-pill confidence-pill--${getFrpCategory(hotspot) === 'Tinggi' ? 'high' : getFrpCategory(hotspot) === 'Sedang' ? 'nominal' : 'low'}`}>
                              {normalizeFrpCategoryLabel(hotspot)}
                            </span>
                          </td>
                          <td>
                            <div className="matrix-satellite">
                              <strong>{hotspot.source}</strong>
                              <span>{hotspot.satellite}</span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="matrix-footer">
                <span>{groupedRows.length} lembaga ditemukan ({filteredHotspots.length} total titik hotspot)</span>
                <div className="matrix-pagination">
                  <button
                    className="matrix-page-btn"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                  >
                    ‹
                  </button>
                  <span className="matrix-page-info">
                    Halaman {currentPage} / {Math.max(1, Math.ceil(groupedRows.length / PAGE_SIZE))}
                  </span>
                  <button
                    className="matrix-page-btn"
                    onClick={() => setCurrentPage((p) => Math.min(Math.ceil(groupedRows.length / PAGE_SIZE), p + 1))}
                    disabled={currentPage >= Math.ceil(groupedRows.length / PAGE_SIZE)}
                  >
                    ›
                  </button>
                </div>
              </div>
            </div>
              </>
          )}
        </section>

        {selectedHotspot ? (
          <>
            <div
              className="matrix-drawer-shroud"
              onClick={() => setSelectedHotspot(null)}
            />
            <aside className="matrix-drawer glass-panel">
              <div className="matrix-drawer__header">
                <div>
                  <p className="panel-eyebrow">Laporan deteksi spesifik</p>
                  <h3>{selectedHotspot.agencyName || selectedHotspot.layerName}</h3>
                </div>
                <button type="button" className="matrix-inline-action" onClick={() => setSelectedHotspot(null)}>
                  Close
                </button>
              </div>

              <div className="matrix-drawer__body">
                <section className="matrix-detail-card">
                  <div className="matrix-detail-card__head">
                    <span>Segmen lokasi</span>
                    <strong>{selectedSummary?.status ?? "-"}</strong>
                  </div>
                  <div className="matrix-detail-grid">
                    {detailRows.map(([label, value]) => (
                      <div key={label} className="matrix-detail-item">
                        <span>{label}</span>
                        <strong>{value}</strong>
                      </div>
                    ))}
                  </div>
                  <div className="matrix-code-block">
                    <p className="matrix-code-block__label">Koordinat</p>
                    <strong>
                      {selectedHotspot.latitude.toFixed(5)}, {selectedHotspot.longitude.toFixed(5)}
                    </strong>
                  </div>
                </section>

                <section className="matrix-detail-card">
                  <div className="matrix-detail-card__head">
                    <span>Daftar Deteksi Hotspot ({selectedLembagaHotspots.length} titik)</span>
                    <strong>Klik baris untuk melihat info di bawah</strong>
                  </div>
                  <div className="matrix-table-wrap" style={{ marginTop: '8px' }}>
                    <div className="matrix-scroll" style={{ maxHeight: '180px', overflowY: 'auto' }}>
                      <table className="matrix-table" style={{ fontSize: '11.5px', width: '100%', tableLayout: 'fixed' }}>
                        <thead>
                          <tr>
                            <th style={{ padding: '6px 4px', width: '32%' }}>Tanggal</th>
                            <th style={{ padding: '6px 4px', width: '18%' }}>Satelit</th>
                            <th style={{ padding: '6px 4px', width: '18%' }}>Kepercayaan</th>
                            <th style={{ padding: '6px 4px', width: '14%' }}>FRP</th>
                            <th style={{ padding: '6px 4px', width: '18%' }}>Lat/Lon</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedLembagaHotspots.map((h) => {
                            const statusLabel = getStatusLabel(h);
                            const statusTone = getStatusTone(statusLabel);
                            const isHSelected = selectedHotspot.id === h.id;
                            const formattedDate = formatTimestamp(h.detectedAt).split(',')[0]; // simplify date
                            return (
                              <tr
                                key={h.id}
                                style={{ cursor: 'pointer', backgroundColor: isHSelected ? 'rgba(255,140,66,0.15)' : 'transparent' }}
                                onClick={() => setSelectedHotspot(h)}
                              >
                                <td style={{ padding: '6px 4px', color: isHSelected ? '#ff8c42' : 'inherit', fontWeight: isHSelected ? 'bold' : 'normal', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {formattedDate}
                                </td>
                                <td style={{ padding: '6px 4px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{h.source}</td>
                                <td style={{ padding: '6px 4px' }}>
                                  <span className={`confidence-pill confidence-pill--${getFrpCategory(h) === 'Tinggi' ? 'high' : getFrpCategory(h) === 'Sedang' ? 'nominal' : 'low'}`} style={{ padding: '2px 4px', fontSize: '9px', display: 'inline-block' }}>
                                    {normalizeFrpCategoryLabel(h)}
                                  </span>
                                </td>
                                <td style={{ padding: '6px 4px' }}>{formatNumber(h.frp)}</td>
                                <td style={{ padding: '6px 4px', fontSize: '10px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={`${h.latitude.toFixed(4)}, ${h.longitude.toFixed(4)}`}>
                                  {h.latitude.toFixed(2)}, {h.longitude.toFixed(2)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </section>

                <section className="matrix-detail-card">
                  <div className="matrix-detail-card__head">
                    <span>Sinyal akuisisi</span>
                    <strong>{normalizeFrpCategoryLabel(selectedHotspot)}</strong>
                  </div>
                  <div className="matrix-detail-grid matrix-detail-grid--two">
                    <div className="matrix-detail-item">
                      <span>Satelit</span>
                      <strong>{selectedHotspot.satellite}</strong>
                    </div>
                    <div className="matrix-detail-item">
                      <span>Sumber</span>
                      <strong>{selectedHotspot.source}</strong>
                    </div>
                    <div className="matrix-detail-item">
                      <span>Brightness</span>
                      <strong>{formatNumber(selectedHotspot.brightness)}</strong>
                    </div>
                    <div className="matrix-detail-item">
                      <span>FRP</span>
                      <strong>{formatNumber(selectedHotspot.frp)}</strong>
                    </div>
                    <div className="matrix-detail-item">
                      <span>Siang/Malam</span>
                      <strong>{formatMetadataValue(selectedHotspot.daynight)}</strong>
                    </div>
                    <div className="matrix-detail-item">
                      <span>Terdeteksi</span>
                      <strong>{formatTimestamp(selectedHotspot.detectedAt)}</strong>
                    </div>
                  </div>
                </section>

                <section className="matrix-detail-card">
                  <div className="matrix-detail-card__head">
                    <span>Grafik data intensitas</span>
                    <strong>Terpilih vs populasi</strong>
                  </div>
                  <div className="matrix-comparison-block">
                    <div className="matrix-comparison-head">
                      <span>Perbandingan FRP (MW)</span>
                      <strong>{formatNumber(selectedHotspot.frp)}</strong>
                    </div>
                    <div className="matrix-comparison-list">
                      {comparison.frp.map((item) => {
                        const max = Math.max(...comparison.frp.map((entry) => entry.value), 1);
                        const width = `${Math.max((item.value / max) * 100, item.value > 0 ? 12 : 0)}%`;
                        return (
                          <div key={item.label} className="matrix-comparison-row">
                            <span>{item.label}</span>
                            <div className="matrix-bar-track matrix-bar-track--mini">
                              <span className="matrix-bar-fill" style={{ width, background: item.color }} />
                            </div>
                            <strong>{item.value}</strong>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  <div className="matrix-comparison-block">
                    <div className="matrix-comparison-head">
                      <span>Perbandingan Kecerahan (K)</span>
                      <strong>{formatNumber(selectedHotspot.brightness)}</strong>
                    </div>
                    <div className="matrix-comparison-list">
                      {comparison.brightness.map((item) => {
                        const max = Math.max(...comparison.brightness.map((entry) => entry.value), 1);
                        const width = `${Math.max((item.value / max) * 100, item.value > 0 ? 12 : 0)}%`;
                        return (
                          <div key={item.label} className="matrix-comparison-row">
                            <span>{item.label}</span>
                            <div className="matrix-bar-track matrix-bar-track--mini">
                              <span className="matrix-bar-fill" style={{ width, background: item.color }} />
                            </div>
                            <strong>{item.value}</strong>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </section>

                {selectedSections.map((section) => (
                  <section key={section.title} className="matrix-detail-card">
                    <div className="matrix-detail-card__head">
                      <span>{section.title}</span>
                      <strong>{section.items.length} kolom</strong>
                    </div>
                    <div className="matrix-detail-grid matrix-detail-grid--compact">
                      {section.items.map(([label, value]) => (
                        <div key={label} className="matrix-detail-item">
                          <span>{label}</span>
                          <strong>{value}</strong>
                        </div>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </aside>
          </>
        ) : null}
      </div>

      <div className="matrix-footer">
        <span>STATUS: READY</span>
        <span>{filteredHotspots.length} RECORDS FOUND</span>
      </div>
    </section>
  );
}
