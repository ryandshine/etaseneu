import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";

const fitBoundsMock = vi.fn();
const mapContainerPropsMock = vi.fn();
const mapZoomMock = vi.fn(() => 5);

vi.mock("react-leaflet", () => ({
  CircleMarker: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  GeoJSON: ({ children }: { children?: ReactNode }) => (
    <div data-testid="geojson-layer">{children}</div>
  ),
  MapContainer: ({ children, ...props }: { children?: ReactNode }) => {
    mapContainerPropsMock(props);
    return <div data-testid="leaflet-map">{children}</div>;
  },
  Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tooltip: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  ZoomControl: () => <div data-testid="zoom-control" />,
  useMap: () => ({ fitBounds: fitBoundsMock, getZoom: mapZoomMock }),
  useMapEvents: () => ({})
}));

const layersResponse = {
  count: 1,
  layers: [
    {
      id: "sample_area",
      name: "Sample Area",
      label: "LPHD Nyuai Peningun",
      color: "#ff7a00",
      active: true,
      feature_count: 1,
      bounds: {
        min_lat: -7,
        min_lon: 107,
        max_lat: -6,
        max_lon: 108
      },
      geojson_mode: "full",
      geojson: {
        type: "FeatureCollection",
        features: []
      }
    }
  ]
};

const hotspotsResponse = {
  count: 2,
  hotspots: [
    {
      id: "hs-1",
      latitude: -6.5,
      longitude: 107.25,
      source: "MODIS",
      satellite: "Terra",
      layer_name: "Sample Area",
      agency_name: "LPHD Nyuai Peningun",
      brightness: 330.5,
      confidence: "high",
      detected_at: "2026-05-26T08:15:00"
    },
    {
      id: "hs-2",
      latitude: -6.3,
      longitude: 107.8,
      source: "VIIRS S-NPP",
      satellite: "NPP",
      layer_name: "Sample Area",
      agency_name: "LPHD Nyuai Peningun",
      brightness: 345.2,
      confidence: "nominal",
      detected_at: "2026-05-26T09:45:00"
    },
    {
      id: "hs-3",
      latitude: -6.2,
      longitude: 107.55,
      source: "VIIRS NOAA-20",
      satellite: "NOAA-20",
      layer_name: "Sample Area",
      agency_name: "LPHD Nyuai Peningun",
      brightness: 351.0,
      confidence: "high",
      detected_at: "2026-05-26T10:10:00"
    }
  ],
  stats: {
    total: 3,
    by_source: {
      MODIS: 1,
      "VIIRS S-NPP": 1,
      "VIIRS NOAA-20": 1
    },
    by_layer: {
      "Sample Area": 3
    }
  }
};

describe("Hotspot map integration", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const createObjectUrlMock = vi.fn(() => "blob:hotspots");
  const revokeObjectUrlMock = vi.fn();
  const clickMock = vi.fn();

  beforeEach(() => {
    fitBoundsMock.mockReset();
    mapContainerPropsMock.mockReset();
    mapZoomMock.mockReset();
    mapZoomMock.mockReturnValue(5);
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);

      if (url.startsWith("/api/layers")) {
        return new Response(JSON.stringify(layersResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }

      if (url.startsWith("/api/hotspots?")) {
        return new Response(JSON.stringify(hotspotsResponse), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }

      if (url.startsWith("/api/cache/history/status?")) {
        return new Response(JSON.stringify({
          year: 2026,
          cached: false,
          satellites: ["MODIS", "VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21"],
          layers: [
            {
              layer_id: "sample_area",
              cached: false,
              satellites: [],
              coverage_start: null,
              coverage_end: null,
              hotspot_count: 0
            }
          ]
        }), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }

      if (url === "/api/storage/status") {
        return new Response(
          JSON.stringify({
            database_enabled: true,
            database_url_present: true,
            last_hotspot_sync_at: "2026-05-30T07:00:00Z",
            last_hotspot_sync_count: 53,
            tables: {
              layers: 1,
              hotspot_history_archives: 1,
              api_cache_entries: 1,
              hotspot_observations: 1
            }
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }
        );
      }

      if (url === "/api/scheduler/metrics") {
        return new Response(
          JSON.stringify({
            scheduler_enabled: true,
            interval_hours: 3,
            nasa_api_configured: true,
            current_time_utc: "2026-05-30T18:00:00Z",
            last_sync_at: "2026-05-30T18:00:00Z",
            last_successful_sync_at: "2026-05-30T18:00:00Z",
            last_sync_status: "success",
            last_sync_hotspot_count: 53,
            last_new_hotspot_count: 0,
            has_new_hotspot: false,
            new_hotspot_over_threshold: false,
            new_hotspot_alert_threshold: 1,
            seconds_since_last_sync: 600,
            seconds_since_last_successful_sync: 600,
            consecutive_failures: 0,
            last_error: null,
            next_scheduled_sync_at: "2026-05-30T21:00:00Z",
            schedule_hours: [0, 3, 6, 9, 12, 15, 18, 21],
            schedule_label: "00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 WIB",
            schedule_timezone: "Asia/Jakarta"
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
            count: 1,
            active_count: 1,
            inactive_count: 0,
            files: []
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" }
          }
        );
      }

      if (url.startsWith("/api/export.xlsx?")) {
        return new Response(new Blob(["xlsx-bytes"]), {
          status: 200,
          headers: {
            "Content-Type":
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          }
        });
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", {
      createObjectURL: createObjectUrlMock,
      revokeObjectURL: revokeObjectUrlMock
    });
    vi.spyOn(document, "createElement").mockImplementation((tagName: string) => {
      const element = document.createElementNS("http://www.w3.org/1999/xhtml", tagName);

      if (tagName === "a") {
        Object.defineProperty(element, "click", {
          configurable: true,
          value: clickMock
        });
      }

      return element;
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("renders hotspot map content and downloads the export file", async () => {
    render(<App />);

    // Wait for dashboard content to appear (rendered only after isInitLoaded)
    expect(await screen.findByTestId("leaflet-map", {}, { timeout: 5000 })).toBeInTheDocument();
    expect((await screen.findAllByText("Filter temporal", {}, { timeout: 5000 })).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Hotspot beririsan")).toBeInTheDocument();
    expect(screen.getAllByText("Areal Perhutanan Sosial").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Kecerahan").length).toBeGreaterThanOrEqual(3);
    expect(screen.getAllByText("Satelit").length).toBeGreaterThanOrEqual(3);

    fireEvent.click(screen.getByRole("button", { name: /matriks data/i }));
    const exportBtn = await screen.findByRole("button", { name: /ekspor xlsx/i });
    fireEvent.click(exportBtn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/export.xlsx?"),
        expect.objectContaining({
          headers: expect.objectContaining({
            Accept:
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          })
        })
      );
    });

    const exportCall = fetchMock.mock.calls.find(([url]) =>
      String(url).startsWith("/api/export.xlsx?")
    );

    expect(exportCall).toBeDefined();
    expect(String(exportCall?.[0])).toContain("start_at=");
    expect(String(exportCall?.[0])).toContain("end_at=");
    expect(String(exportCall?.[0])).toContain("start_date=");
    expect(String(exportCall?.[0])).toContain("end_date=");
    expect(String(exportCall?.[0])).toContain("satellites=MODIS");
    expect(String(exportCall?.[0])).toContain("satellites=VIIRS_SNPP");
    expect(String(exportCall?.[0])).toContain("satellites=VIIRS_NOAA20");
    expect(String(exportCall?.[0])).toContain("satellites=VIIRS_NOAA21");
    expect(String(exportCall?.[0])).toContain("active_layers=sample_area");
    expect(createObjectUrlMock).toHaveBeenCalledTimes(1);
    expect(clickMock).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(revokeObjectUrlMock).toHaveBeenCalledWith("blob:hotspots");
    });

    expect(mapContainerPropsMock).toHaveBeenCalled();
    expect(mapContainerPropsMock.mock.calls[0]?.[0]).toMatchObject({ preferCanvas: true });
    expect(
      fetchMock.mock.calls.some(([input]) => String(input) === "/api/layers")
    ).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("/api/layers?view=preview"))
    ).toBe(false);
  });

  it("loads full geojson layers on initial map render", async () => {
    render(<App />);

    expect(await screen.findByTestId("leaflet-map", {}, { timeout: 5000 })).toBeInTheDocument();

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([input]) => String(input) === "/api/layers")
      ).toBe(true);
    });

    const layerCalls = fetchMock.mock.calls.filter(([input]) => String(input).startsWith("/api/layers"));
    expect(layerCalls).toHaveLength(1);
  });
});
