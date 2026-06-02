import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

vi.mock("react-leaflet", () => ({
  CircleMarker: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  GeoJSON: ({ children }: { children?: ReactNode }) => (
    <div data-testid="geojson-layer">{children}</div>
  ),
  MapContainer: ({ children }: { children?: ReactNode }) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tooltip: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  ZoomControl: () => <div data-testid="zoom-control" />,
  useMap: () => ({ fitBounds: vi.fn(), getZoom: () => 5 }),
  useMapEvents: () => ({})
}));

describe("App", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const audioContextMock = vi.fn();
  let schedulerMetricsCallCount = 0;

  beforeEach(() => {
    schedulerMetricsCallCount = 0;
    const oscillator = {
      type: "sine",
      frequency: { setValueAtTime: vi.fn() },
      connect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn()
    };
    const gainNode = {
      gain: {
        setValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn()
      },
      connect: vi.fn()
    };

    audioContextMock.mockImplementation(() => ({
      currentTime: 0,
      destination: {},
      createOscillator: () => oscillator,
      createGain: () => gainNode,
      close: vi.fn()
    }));
    vi.stubGlobal("AudioContext", audioContextMock);
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);

      if (url === "/api/layers?view=preview") {
        return new Response(JSON.stringify({
          count: 1,
          layers: [
            {
              id: "sample_area",
              name: "Sample Area",
              label: "Sample Area",
              color: "#1d4ed8",
              active: true,
              feature_count: 1,
              bounds: {
                min_lat: -1,
                min_lon: 100,
                max_lat: 1,
                max_lon: 102
              },
              geojson: {
                type: "FeatureCollection",
                features: [
                  {
                    type: "Feature",
                    properties: {},
                    geometry: {
                      type: "Polygon",
                      coordinates: [[[100, -1], [102, -1], [102, 1], [100, 1], [100, -1]]]
                    }
                  }
                ]
              },
              geojson_mode: "preview",
              agencies: ["Sample Area"]
            }
          ]
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }

      if (url === "/api/layers/sample_area") {
        return new Response(JSON.stringify({
          id: "sample_area",
          name: "Sample Area",
          label: "Sample Area",
          color: "#1d4ed8",
          active: true,
          feature_count: 1,
          bounds: {
            min_lat: -1,
            min_lon: 100,
            max_lat: 1,
            max_lon: 102
          },
          geojson: {
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                properties: { label: "Sample Area" },
                geometry: {
                  type: "Polygon",
                  coordinates: [[[100, -1], [101, -1], [101, 0], [100, 0], [100, -1]]]
                }
              }
            ]
          },
          geojson_mode: "full",
          agencies: ["Sample Area"]
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }

      if (url.startsWith("/api/hotspots?")) {
        return new Response(
          JSON.stringify({
            count: 0,
            hotspots: [],
            stats: { total: 0, by_source: {}, by_layer: {} }
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          },
        );
      }

      if (url.startsWith("/api/cache/history/status?")) {
        return new Response(
          JSON.stringify({
            year: 2026,
            cached: false,
            satellites: ["MODIS", "VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21"],
            layers: []
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          },
        );
      }

      if (url === "/api/storage/status") {
        return new Response(
          JSON.stringify({
            database_enabled: true,
            database_url_present: true,
            last_hotspot_sync_at: "2026-05-28T00:10:59+07:00",
            last_hotspot_sync_count: 136,
            tables: {
              layers: 1,
              hotspot_history_archives: 1,
              api_cache_entries: 1,
              hotspot_observations: 1,
              hotspot_sync_state: 1
            }
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }
        );
      }

      if (url === "/api/scheduler/metrics") {
        schedulerMetricsCallCount += 1;
        const payload =
          schedulerMetricsCallCount === 1
            ? {
                scheduler_enabled: true,
                interval_hours: 3,
                nasa_api_configured: true,
                current_time_utc: "2026-05-28T08:30:00Z",
                last_sync_at: "2026-05-28T08:20:00Z",
                last_successful_sync_at: "2026-05-28T08:20:00Z",
                last_sync_status: "success",
                last_sync_hotspot_count: 12,
                last_new_hotspot_count: 0,
                has_new_hotspot: false,
                new_hotspot_over_threshold: false,
                new_hotspot_alert_threshold: 1,
                seconds_since_last_sync: 600,
                seconds_since_last_successful_sync: 600,
                consecutive_failures: 0,
                last_error: null,
                next_scheduled_sync_at: "2026-05-28T11:20:00Z"
              }
            : {
                scheduler_enabled: true,
                interval_hours: 3,
                nasa_api_configured: true,
                current_time_utc: "2026-05-28T08:31:00Z",
                last_sync_at: "2026-05-28T08:30:00Z",
                last_successful_sync_at: "2026-05-28T08:30:00Z",
                last_sync_status: "success",
                last_sync_hotspot_count: 12,
                last_new_hotspot_count: 2,
                has_new_hotspot: true,
                new_hotspot_over_threshold: true,
                new_hotspot_alert_threshold: 1,
                seconds_since_last_sync: 60,
                seconds_since_last_successful_sync: 60,
                consecutive_failures: 0,
                last_error: null,
                next_scheduled_sync_at: "2026-05-28T11:30:00Z"
              };

        return new Response(
          JSON.stringify(payload),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }
        );
      }

      if (url === "/api/scheduler/sync") {
        return new Response(
          JSON.stringify({
            triggered: true,
            message: "Sync hotspot dimulai di background."
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }
        );
      }

      if (url.startsWith("/api/cache/history/prewarm?")) {
        return new Response(
          JSON.stringify({
            year: 2026,
            cached: true,
            satellites: ["MODIS", "VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21"],
            layers: []
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }
        );
      }

      if (url === "/api/geojson/status") {
        return new Response(
          JSON.stringify({
            database_enabled: true,
            database_url_present: true,
            count: 1,
            active_count: 1,
            inactive_count: 0,
            files: [
              {
                file_name: "PS_FEB_26.geojson",
                file_path: "shp/PS_FEB_26.geojson",
                layer_key: "ps_feb_26",
                checksum: "demo",
                mtime: "2026-05-28T00:10:59+07:00",
                last_synced_at: "2026-05-28T00:10:59+07:00",
                last_sync_status: "synced",
                last_sync_message: "ok",
                feature_count: 7138,
                is_active: true
              }
            ]
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }
        );
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("renders the frontend shell heading", async () => {
    render(<App />);

    expect(screen.getAllByText("ETAseneu").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: /matriks data/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pemantauan/i })).toBeInTheDocument();
    expect(await screen.findByTestId("leaflet-map")).toBeInTheDocument();
    expect(await screen.findByText(/database online/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/tampilkan angin/i));
    expect(screen.queryByText(/angin:/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("Sinkronisasi NASA").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Aktif").length).toBeGreaterThanOrEqual(1);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/api/layers?view=preview"))
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input) === "/api/layers")
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input) === "/api/layers/sample_area")
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/api/hotspots?") && String(input).includes("view=map"))
    ).toBe(true);
  });

  it("switches to monitoring view without reusing map content", async () => {
    vi.useFakeTimers();
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /pemantauan/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(screen.getByText("Pemantauan Insiden")).toBeInTheDocument();
    expect(screen.getByText("Denyut Scheduler")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    await Promise.resolve();

    expect(screen.getByText("Hotspot Baru")).toBeInTheDocument();
    expect(screen.getByText("Auto-refresh aktif setiap 60 detik")).toBeInTheDocument();
    expect(screen.getByText("Ambang batas terlampaui")).toBeInTheDocument();
    expect(screen.queryByTestId("leaflet-map")).not.toBeInTheDocument();
    expect(screen.queryByText("Matriks Intersep")).not.toBeInTheDocument();

    vi.useRealTimers();
  });

  it("upgrades hotspot payload to full view when switching to matrix", async () => {
    render(<App />);

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    fireEvent.click(screen.getByRole("button", { name: /matriks data/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(
      fetchMock.mock.calls.some(
        ([input]) =>
          String(input).includes("/api/hotspots?")
          && !String(input).includes("view=map"),
      ),
    ).toBe(true);
  });

  it("polls scheduler metrics while monitoring view is active", async () => {
    vi.useFakeTimers();
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /pemantauan/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(screen.getByText("Pemantauan Insiden")).toBeInTheDocument();

    const schedulerCallsBefore = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/scheduler/metrics",
    ).length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    await Promise.resolve();

    const schedulerCallsAfter = fetchMock.mock.calls.filter(
      ([input]) => String(input) === "/api/scheduler/metrics",
    ).length;
    expect(schedulerCallsAfter).toBeGreaterThan(schedulerCallsBefore);

    vi.useRealTimers();
  });

  it("keeps the initial loading overlay hidden during background refresh", async () => {
    vi.useFakeTimers();
    const { container } = render(<App />);

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(screen.getByTestId("leaflet-map")).toBeInTheDocument();
    expect(container.querySelector(".loading-screen-overlay")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
      await vi.dynamicImportSettled();
    });
    await Promise.resolve();

    expect(screen.getByTestId("leaflet-map")).toBeInTheDocument();
    expect(container.querySelector(".loading-screen-overlay")).not.toBeInTheDocument();

    vi.useRealTimers();
  });

  it("keeps the initial loading overlay hidden while map data loads", () => {
    fetchMock.mockImplementation(
      () =>
        new Promise(() => {
          // Keep the request pending so the app stays in its initial loading phase.
        }),
    );
    const { container, unmount } = render(<App />);

    expect(container.querySelector(".loading-screen-overlay")).not.toBeInTheDocument();

    unmount();
  });

  it("shows sidebar alert badge and escalation notice after metrics change", async () => {
    vi.useFakeTimers();
    render(<App />);

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(screen.queryByText("PERINGATAN")).not.toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
      await vi.dynamicImportSettled();
    });
    await Promise.resolve();

    expect(screen.getAllByText("PERINGATAN").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /pemantauan/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(screen.getByText("Status berubah: Peringatan kritis")).toBeInTheDocument();

    vi.useRealTimers();
  });

  it("lets operator mute alert sound in monitoring view", async () => {
    vi.useFakeTimers();
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /pemantauan/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });

    fireEvent.click(screen.getByRole("button", { name: /bisukan suara peringatan/i }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    await Promise.resolve();

    expect(screen.getByRole("button", { name: /bunyikan suara peringatan/i })).toBeInTheDocument();
    expect(audioContextMock).not.toHaveBeenCalled();

    vi.useRealTimers();
  });

  it("lets operator dismiss status change notice and adjust alert volume", async () => {
    vi.useFakeTimers();
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /pemantauan/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    expect(screen.getByRole("button", { name: /volume peringatan normal/i })).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    await Promise.resolve();

    expect(screen.getByText("Status berubah: Peringatan kritis")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /dismiss status change/i }));
    expect(screen.queryByText("Status berubah: Peringatan kritis")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /volume peringatan normal/i }));
    expect(screen.getByRole("button", { name: /volume peringatan low/i })).toBeInTheDocument();

    vi.useRealTimers();
  });

  it("separates manual sync from prewarm history actions", async () => {
    render(<App />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /sync hotspot manual/i }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/api/scheduler/sync"))
    ).toBe(true);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /prewarm histori/i }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/api/cache/history/prewarm"))
    ).toBe(true);
  });
});
