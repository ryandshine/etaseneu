import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearDashboardCache,
  loadDashboardCache,
  loadPersistedFilters,
  saveDashboardCache,
  savePersistedFilters,
} from "../lib/dashboardPersistence";

const FILTERS_KEY = "etaseneu.dashboard.filters.v1";
const CACHE_KEY = "etaseneu.dashboard.cache.v2";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("persisted filters", () => {
  it("round-trips a valid filter set", () => {
    savePersistedFilters({
      selectedSatellites: ["MODIS", "VIIRS_SNPP"],
      timePreset: "7d",
      startDate: "2026-08-01",
      endDate: "2026-08-08",
    });
    expect(loadPersistedFilters()).toEqual({
      selectedSatellites: ["MODIS", "VIIRS_SNPP"],
      timePreset: "7d",
      startDate: "2026-08-01",
      endDate: "2026-08-08",
    });
  });

  it("returns null when nothing stored", () => {
    expect(loadPersistedFilters()).toBeNull();
  });

  it("drops unknown satellites / presets / malformed dates", () => {
    window.localStorage.setItem(
      FILTERS_KEY,
      JSON.stringify({
        selectedSatellites: ["MODIS", "BOGUS_SAT"],
        timePreset: "9999h",
        startDate: "not-a-date",
        endDate: "2026-08-08",
      }),
    );
    expect(loadPersistedFilters()).toEqual({
      selectedSatellites: ["MODIS"],
      endDate: "2026-08-08",
    });
  });

  it("drops the satellite list entirely when none are valid", () => {
    window.localStorage.setItem(
      FILTERS_KEY,
      JSON.stringify({ selectedSatellites: ["NOPE"], timePreset: "24h" }),
    );
    expect(loadPersistedFilters()).toEqual({ timePreset: "24h" });
  });

  it("survives corrupt JSON", () => {
    window.localStorage.setItem(FILTERS_KEY, "{not json");
    expect(loadPersistedFilters()).toBeNull();
  });

  it("never throws when localStorage write fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() =>
      savePersistedFilters({
        selectedSatellites: ["MODIS"],
        timePreset: "24h",
        startDate: "2026-08-01",
        endDate: "2026-08-02",
      }),
    ).not.toThrow();
  });
});

describe("dashboard cache", () => {
  const payload = {
    layers: [
      { id: "l1", name: "KPS A", active: true, geojson: { type: "FeatureCollection", features: [] } },
    ],
    hotspots: [{ id: "h1", latitude: 1, longitude: 2 }],
    remoteStats: { total: 1, by_source: { MODIS: 1 }, by_layer: {} },
  } as unknown as Parameters<typeof saveDashboardCache>[0];

  it("round-trips layers, hotspots and stats", () => {
    saveDashboardCache(payload);
    const loaded = loadDashboardCache();
    expect(loaded?.hotspots).toHaveLength(1);
    expect(loaded?.layers).toHaveLength(1);
    expect(loaded?.remoteStats.total).toBe(1);
  });

  it("returns null past the 6h TTL", () => {
    saveDashboardCache(payload);
    const stored = JSON.parse(window.localStorage.getItem(CACHE_KEY) as string);
    stored.savedAt = Date.now() - 7 * 60 * 60 * 1000;
    window.localStorage.setItem(CACHE_KEY, JSON.stringify(stored));
    expect(loadDashboardCache()).toBeNull();
  });

  it("returns null on shape mismatch", () => {
    window.localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ savedAt: Date.now(), layers: "nope", hotspots: [] }),
    );
    expect(loadDashboardCache()).toBeNull();
  });

  it("drops layers (not stub geojson) when the first write hits quota", () => {
    const real = Storage.prototype.setItem;
    let calls = 0;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (
      this: Storage,
      key: string,
      value: string,
    ) {
      calls += 1;
      if (calls === 1) throw new Error("QuotaExceededError");
      real.call(this, key, value);
    });

    saveDashboardCache(payload);

    expect(calls).toBe(2);
    const loaded = loadDashboardCache();
    expect(loaded?.hotspots).toHaveLength(1);
    // Layer TIDAK di-cache dengan geojson kosong ({}) -- itu bikin <GeoJSON> crash.
    expect(loaded?.layers).toEqual([]);
  });

  it("discards all cached layers if any geojson is not renderable", () => {
    window.localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        savedAt: Date.now(),
        layers: [
          { id: "ok", geojson: { type: "FeatureCollection", features: [] } },
          { id: "bad", geojson: {} },
        ],
        hotspots: [{ id: "h1" }],
        remoteStats: { total: 0, by_source: {}, by_layer: {} },
      }),
    );
    const loaded = loadDashboardCache();
    expect(loaded?.layers).toEqual([]);
    expect(loaded?.hotspots).toHaveLength(1);
  });

  it("clearDashboardCache removes the entry", () => {
    saveDashboardCache(payload);
    clearDashboardCache();
    expect(loadDashboardCache()).toBeNull();
  });

  it("never throws when every write fails", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => saveDashboardCache(payload)).not.toThrow();
  });
});
