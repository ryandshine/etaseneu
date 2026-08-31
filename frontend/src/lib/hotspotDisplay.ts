// Helper pemformatan & perhitungan yang dipakai bareng oleh HotspotMatrix
// (tabel Buku Besar) dan KpsDetailView (halaman detail KPS) -- dipisah ke
// sini supaya kedua tempat itu tidak punya salinan logika yang bisa mencar.

import type { HotspotRecord } from "../types/api";

export function normalizeLembagaName(name: string): string {
  if (!name) return name;
  if (name.toLowerCase() === "lphd nyuai peningun") return "Areal Perhutanan Sosial";
  return name;
}

// Bentuk hasil transformasi ini sengaja tidak diimpor dari useDashboardData.ts
// (akan bikin import siklik) -- KpsDetailView & useDashboardData sama-sama
// punya `DashboardHotspot` yang cocok dengan tipe balik fungsi ini secara
// struktural.
export type MappedDashboardHotspot = {
  id: string;
  latitude: number;
  longitude: number;
  source: string;
  satellite: string;
  layerName: string;
  agencyName: string;
  provinceName: string;
  brightness: number | null;
  frp: number | null;
  confidence: string;
  daynight: string;
  detectedAt: string;
  polygonMetadata: Record<string, string>;
  fungsiKawasan: string;
  namaKawasan: string;
  kelompokKawasan: string;
};

export function mapHotspotRecordToDashboardHotspot(
  hotspot: HotspotRecord,
  index: number
): MappedDashboardHotspot {
  return {
    id: String(hotspot.id ?? `${hotspot.latitude}-${hotspot.longitude}-${index}`),
    latitude: Number(hotspot.latitude ?? 0),
    longitude: Number(hotspot.longitude ?? 0),
    source: String(hotspot.source ?? "Unknown"),
    satellite: String(hotspot.satellite ?? "Unknown"),
    layerName: normalizeLembagaName(String(hotspot.layer_name ?? "Unassigned")),
    agencyName: normalizeLembagaName(String(hotspot.agency_name ?? hotspot.layer_name ?? "Unassigned")),
    provinceName: String(hotspot.province_name ?? ""),
    polygonMetadata: Object.entries(hotspot.polygon_metadata ?? {}).reduce<Record<string, string>>(
      (accumulator, [key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          accumulator[key] = key === "LEMBAGA" ? normalizeLembagaName(String(value)) : String(value);
        }
        return accumulator;
      },
      {}
    ),
    brightness:
      hotspot.brightness === null || hotspot.brightness === undefined ? null : Number(hotspot.brightness),
    frp: hotspot.frp === null || hotspot.frp === undefined ? null : Number(hotspot.frp),
    confidence: String(hotspot.confidence ?? "Unknown"),
    daynight: String(hotspot.daynight ?? ""),
    detectedAt: String(hotspot.detected_at ?? ""),
    // view=map memberi field datar (fungsi_kawasan/kelompok); view=full memberi
    // objek kawasan_hutan. Ambil dari mana pun yang terisi.
    fungsiKawasan: String(hotspot.fungsi_kawasan ?? hotspot.kawasan_hutan?.fungsi ?? ""),
    namaKawasan: String(hotspot.kawasan_hutan?.nama_kawasan ?? ""),
    kelompokKawasan: String(hotspot.kelompok ?? hotspot.kawasan_hutan?.kelompok ?? "")
  };
}

export type HotspotLike = {
  source: string;
  satellite: string;
  daynight: string;
  brightness: number | null;
  frp: number | null;
  detectedAt: string;
  latitude: number;
  longitude: number;
  agencyName: string;
  polygonMetadata: Record<string, string>;
};

function parseDateTime(value: string): Date | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatTimestamp(value: string): string {
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
    const year = parts.find((p) => p.type === "year")?.value ?? "";
    const month = parts.find((p) => p.type === "month")?.value ?? "";
    const day = parts.find((p) => p.type === "day")?.value ?? "";
    const hour = parts.find((p) => p.type === "hour")?.value ?? "";
    const minute = parts.find((p) => p.type === "minute")?.value ?? "";
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  } catch {
    const wibTime = new Date(parsed.getTime() + 7 * 60 * 60 * 1000);
    const day = String(wibTime.getUTCDate()).padStart(2, "0");
    const month = String(wibTime.getUTCMonth() + 1).padStart(2, "0");
    const year = wibTime.getUTCFullYear();
    const hour = String(wibTime.getUTCHours()).padStart(2, "0");
    const minute = String(wibTime.getUTCMinutes()).padStart(2, "0");
    return `${day}-${month}-${year} ${hour}:${minute} WIB`;
  }
}

export function formatNumber(value: number | null, digits = 2): string {
  if (value === null || Number.isNaN(value)) {
    return "Tidak Tersedia";
  }
  return value.toFixed(digits);
}

const INTEGER_GROUPED = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 });

/**
 * Bilangan bulat dengan pemisah ribuan gaya Indonesia (10.056), untuk angka
 * besar yang harus terbaca sekilas -- mis. total luas bekas terbakar di
 * overlay peta. `formatNumber` (toFixed) tetap dipakai di tempat lain yang
 * butuh desimal tetap.
 */
export function formatHectares(value: number | null): string {
  if (value === null || Number.isNaN(value)) {
    return "–";
  }
  return INTEGER_GROUPED.format(Math.round(value));
}

export function formatMetadataValue(value?: string): string {
  return value && value.trim() ? value : "-";
}

export function getFrpCategory(hotspot: HotspotLike): "Tinggi" | "Sedang" | "Rendah" {
  const frp = hotspot.frp ?? 0;
  if (frp > 30) return "Tinggi";
  if (frp >= 10) return "Sedang";
  return "Rendah";
}

export function normalizeFrpCategoryLabel(hotspot: HotspotLike): string {
  return getFrpCategory(hotspot);
}

export function getStatusLabel(hotspot: HotspotLike): string {
  const metadata = hotspot.polygonMetadata ?? {};
  return formatMetadataValue(metadata.Status) !== "-"
    ? formatMetadataValue(metadata.Status)
    : getFrpCategory(hotspot);
}

export function getStatusTone(statusLabel: string): "accent" | "soft" | "warm" {
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

export type ComparisonRow = { label: string; value: number; color: string };

// Membandingkan satu deteksi terpilih terhadap populasi hotspot yang sedang
// dimuat (rata-rata & maksimum), bukan cuma terhadap KPS-nya sendiri --
// jadi angka "Maksimum Global" tetap bermakna walau KPS ini titiknya sedikit.
export function buildComparison(
  hotspots: HotspotLike[],
  selectedHotspot: HotspotLike | null
): { frp: ComparisonRow[]; brightness: ComparisonRow[] } {
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
