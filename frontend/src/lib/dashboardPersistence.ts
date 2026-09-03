// Persistensi ringan state dashboard di localStorage.
//
// Masalah yang dipecahkan: Chrome Android agresif men-discard tab latar. Saat
// user menutup browser / pindah aplikasi lalu kembali, SPA cold-boot dan semua
// state (yang cuma di memori React) hilang -> layar kosong + spinner + semua
// filter balik ke default. Lihat useDashboardData.ts.
//
// Dua hal disimpan TERPISAH:
//  - FILTERS (kecil): preset waktu, tanggal custom, satelit terpilih.
//  - CACHE DATA (besar): hotspot + layer + stats terakhir. Ini cuma placeholder
//    visual saat boot supaya tidak ada kedip layar kosong -- SELALU
//    di-revalidate ke API setelahnya.
//
// Semua akses localStorage dibungkus try/catch: private window, storage
// diblokir, atau kuota penuh tidak boleh sampai menjatuhkan aplikasi.

import { SATELLITE_OPTIONS } from "../constants/satellites";
import { TIME_PRESET_OPTIONS, type TimePreset } from "../constants/time-windows";
import type { DashboardHotspot, DashboardLayer } from "../hooks/useDashboardData";

const FILTERS_KEY = "etaseneu.dashboard.filters.v1";
const CACHE_KEY = "etaseneu.dashboard.cache.v1";

// Data hotspot lebih tua dari ini tidak lagi dipakai sebagai placeholder --
// menampilkan titik api 12 jam lalu seolah terkini bisa menyesatkan.
const CACHE_TTL_MS = 6 * 60 * 60 * 1000;
const CACHE_MAX_HOTSPOTS = 6000;
const CACHE_MIN_HOTSPOTS = 2000;

const KNOWN_SATELLITES = new Set<string>(SATELLITE_OPTIONS.map((option) => option.value));
const KNOWN_PRESETS = new Set<string>(TIME_PRESET_OPTIONS.map((option) => option.value));
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export type PersistedFilters = {
  selectedSatellites: string[];
  timePreset: TimePreset;
  startDate: string;
  endDate: string;
};

type RemoteStatsLike = {
  total: number;
  by_source: Record<string, number>;
  by_layer: Record<string, number>;
};

export type DashboardCachePayload = {
  layers: DashboardLayer[];
  hotspots: DashboardHotspot[];
  remoteStats: RemoteStatsLike;
};

const EMPTY_STATS: RemoteStatsLike = { total: 0, by_source: {}, by_layer: {} };

export function loadPersistedFilters(): Partial<PersistedFilters> | null {
  try {
    const raw = window.localStorage.getItem(FILTERS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedFilters>;
    const out: Partial<PersistedFilters> = {};

    if (Array.isArray(parsed.selectedSatellites)) {
      const sats = parsed.selectedSatellites.filter(
        (value): value is string => typeof value === "string" && KNOWN_SATELLITES.has(value),
      );
      if (sats.length > 0) out.selectedSatellites = sats;
    }
    if (typeof parsed.timePreset === "string" && KNOWN_PRESETS.has(parsed.timePreset)) {
      out.timePreset = parsed.timePreset as TimePreset;
    }
    if (typeof parsed.startDate === "string" && ISO_DATE_RE.test(parsed.startDate)) {
      out.startDate = parsed.startDate;
    }
    if (typeof parsed.endDate === "string" && ISO_DATE_RE.test(parsed.endDate)) {
      out.endDate = parsed.endDate;
    }
    return out;
  } catch {
    return null;
  }
}

export function savePersistedFilters(filters: PersistedFilters): void {
  try {
    window.localStorage.setItem(FILTERS_KEY, JSON.stringify(filters));
  } catch {
    /* localStorage penuh / diblokir -> abaikan, ini cuma kenyamanan */
  }
}

export function loadDashboardCache(): DashboardCachePayload | null {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as {
      savedAt?: unknown;
      layers?: unknown;
      hotspots?: unknown;
      remoteStats?: unknown;
    };
    if (typeof parsed.savedAt !== "number") return null;
    if (Date.now() - parsed.savedAt > CACHE_TTL_MS) return null;
    if (!Array.isArray(parsed.layers) || !Array.isArray(parsed.hotspots)) return null;

    const remoteStats =
      parsed.remoteStats && typeof parsed.remoteStats === "object"
        ? (parsed.remoteStats as RemoteStatsLike)
        : EMPTY_STATS;

    return {
      layers: parsed.layers as DashboardLayer[],
      hotspots: parsed.hotspots as DashboardHotspot[],
      remoteStats,
    };
  } catch {
    return null;
  }
}

export function saveDashboardCache(payload: DashboardCachePayload): void {
  const write = (layers: DashboardLayer[], hotspots: DashboardHotspot[]): boolean => {
    try {
      window.localStorage.setItem(
        CACHE_KEY,
        JSON.stringify({ savedAt: Date.now(), layers, hotspots, remoteStats: payload.remoteStats }),
      );
      return true;
    } catch {
      return false;
    }
  };

  const hotspots =
    payload.hotspots.length > CACHE_MAX_HOTSPOTS
      ? payload.hotspots.slice(0, CACHE_MAX_HOTSPOTS)
      : payload.hotspots;

  if (write(payload.layers, hotspots)) return;

  // Degradasi 1: kosongkan geojson layer (biasanya bagian terbesar dari payload).
  // Peta akan tampil tanpa poligon sampai revalidasi selesai -- trade-off yang
  // wajar demi tetap bisa menyimpan hotspot + stats.
  const slimLayers: DashboardLayer[] = payload.layers.map((layer) => ({ ...layer, geojson: {} }));
  if (write(slimLayers, hotspots)) return;

  // Degradasi 2: potong hotspot lebih agresif. Kalau masih gagal, menyerah diam-diam.
  write(slimLayers, hotspots.slice(0, CACHE_MIN_HOTSPOTS));
}

export function clearDashboardCache(): void {
  try {
    window.localStorage.removeItem(CACHE_KEY);
  } catch {
    /* abaikan */
  }
}
