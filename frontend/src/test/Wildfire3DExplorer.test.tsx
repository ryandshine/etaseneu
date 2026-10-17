import "@testing-library/jest-dom/vitest";
import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Wildfire3DExplorer } from "../components/Wildfire3DExplorer";
import { windDegToCompass } from "../hooks/useWildfire3DData";
import { SidebarNav } from "../components/SidebarNav";

// Mock MapLibre map component to avoid WebGL context requirement in jsdom
vi.mock("../components/Wildfire3DMap", () => ({
  Wildfire3DMap: ({ hotspots, selectedHotspot, onSelectHotspot }: any) => (
    <div data-testid="wildfire-3d-map">
      <div data-testid="map-hotspots-count">{hotspots.length}</div>
      {hotspots.map((h: any) => (
        <button
          key={h.id}
          data-testid={`hotspot-marker-${h.id}`}
          onClick={() => onSelectHotspot(h)}
        >
          {h.agencyName}
        </button>
      ))}
      {selectedHotspot && (
        <div data-testid="selected-hotspot-info">{selectedHotspot.agencyName}</div>
      )}
    </div>
  )
}));

describe("Wildfire3DExplorer & 3D Helpers", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("windDegToCompass correctly converts degrees to cardinal directions", () => {
    expect(windDegToCompass(0)).toBe("U");
    expect(windDegToCompass(90)).toBe("T");
    expect(windDegToCompass(180)).toBe("S");
    expect(windDegToCompass(270)).toBe("B");
    expect(windDegToCompass(45)).toBe("TL");
    expect(windDegToCompass(135)).toBe("Gr");
    expect(windDegToCompass(225)).toBe("BD");
    expect(windDegToCompass(315)).toBe("BL");
  });

  it("renders the 3D explorer header, title, badges, and telemetry", async () => {
    fetchMock.mockImplementation((url: any) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/hotspots")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              count: 2,
              hotspots: [
                {
                  id: "hs-1",
                  latitude: -1.2,
                  longitude: 110.5,
                  confidence: "h",
                  frp: 45.2,
                  brightness: 340.5,
                  source: "VIIRS",
                  satellite: "NOAA-20",
                  agency_name: "KPS Hutan Lestari",
                  province_name: "Kalimantan Barat",
                  detected_at: "2026-10-17T12:00:00Z"
                },
                {
                  id: "hs-2",
                  latitude: -2.5,
                  longitude: 112.3,
                  confidence: "m",
                  frp: 18.0,
                  brightness: 320.0,
                  source: "VIIRS",
                  satellite: "SNPP",
                  agency_name: "KPS Rimba Sejahtera",
                  province_name: "Kalimantan Tengah",
                  detected_at: "2026-10-17T14:30:00Z"
                }
              ]
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );
      }
      if (urlStr.includes("/api/scheduler/metrics")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              last_sync_time: "2026-10-17 14:00 WIB",
              next_scheduled_sync: "2026-10-17 17:00 WIB",
              scheduler_status: "OK",
              latest_hotspot_time: "2026-10-17 14:30 WIB"
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );
      }
      if (urlStr.includes("/api/layers")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              count: 1,
              layers: [
                {
                  id: "psagustus2026",
                  name: "Perhutanan Sosial",
                  label: "Perhutanan Sosial",
                  color: "#10b981",
                  active: true,
                  feature_count: 50,
                  bounds: { min_lat: -10, min_lon: 95, max_lat: 6, max_lon: 141 },
                  geojson: { type: "FeatureCollection", features: [] }
                }
              ]
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );
      }
      if (urlStr.includes("/api/wind")) {
        return Promise.resolve(
          new Response(
            JSON.stringify([
              {
                header: { parameterNumber: 2, lo1: 90, la1: 10, lo2: 146, la2: -14, dx: 1, dy: 1, nx: 57, ny: 25 },
                data: new Array(57 * 25).fill(2.5)
              },
              {
                header: { parameterNumber: 3, lo1: 90, la1: 10, lo2: 146, la2: -14, dx: 1, dy: 1, nx: 57, ny: 25 },
                data: new Array(57 * 25).fill(1.5)
              }
            ]),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    });

    const onBackMock = vi.fn();
    render(<Wildfire3DExplorer onBackToLiveMap={onBackMock} />);

    // Check header title & badges
    expect(screen.getByText("Wildfire 3D Explorer")).toBeInTheDocument();
    expect(screen.getByText("3D WebGL")).toBeInTheDocument();
    expect(screen.getByText("NASA FIRMS")).toBeInTheDocument();
    expect(screen.getByText("Open-Meteo")).toBeInTheDocument();
    expect(screen.getByText("3D Terrain")).toBeInTheDocument();

    // Check back button click
    const backBtn = screen.getByText("Live Map");
    fireEvent.click(backBtn);
    expect(onBackMock).toHaveBeenCalledTimes(1);

    // Wait for hotspots to populate KPI
    await waitFor(() => {
      const hero = document.querySelector(".kpi-hero-number");
      expect(hero).toHaveTextContent("2");
    });

    // Check confidence numbers
    expect(screen.getByText("Tinggi")).toBeInTheDocument();
    expect(screen.getByText("Sedang")).toBeInTheDocument();
    expect(screen.getByText("Rendah")).toBeInTheDocument();

    // Check max FRP
    expect(screen.getByText("45.2")).toBeInTheDocument();
  });

  it("switches tabs in the HUD and shows distribution and weather info", async () => {
    fetchMock.mockImplementation((url: any) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/hotspots")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              count: 1,
              hotspots: [
                {
                  id: "hs-101",
                  latitude: -1.23,
                  longitude: 110.45,
                  confidence: "h",
                  frp: 30.5,
                  source: "VIIRS",
                  satellite: "NOAA-20",
                  agency_name: "LPHD Kalibandung",
                  province_name: "Kalimantan Barat",
                  detected_at: "2026-10-17T10:00:00Z"
                }
              ]
            }),
            { status: 200 }
          )
        );
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    });

    render(<Wildfire3DExplorer onBackToLiveMap={() => {}} />);

    await waitFor(() => {
      const hero = document.querySelector(".kpi-hero-number");
      expect(hero).toHaveTextContent("1");
    });

    // Switch to Distribusi KPS tab
    const distTab = screen.getByRole("button", { name: "Distribusi KPS" });
    fireEvent.click(distTab);

    expect(screen.getByText("KPS Terdampak")).toBeInTheDocument();
    expect(screen.getByText("Distribusi Provinsi")).toBeInTheDocument();
    expect(screen.queryByText(/Top 5/)).not.toBeInTheDocument();

    await waitFor(() => {
      const list = document.querySelector(".leaderboard-list");
      expect(list).toHaveTextContent("LPHD Kalibandung");
      expect(list).toHaveTextContent("1 HS");
    });

    // Switch to Cuaca & Angin tab
    const weatherTab = screen.getByRole("button", { name: "Cuaca & Angin" });
    fireEvent.click(weatherTab);

    expect(screen.getByText(/Grid Vektor Angin \(Open-Meteo\)/)).toBeInTheDocument();
    expect(screen.queryByText(/Overlay angin adalah visualisasi kondisi meteorologis/)).not.toBeInTheDocument();
  });

  it("SidebarNav includes Wildfire 3D Explorer and calls onChangeView", () => {
    const onChangeViewMock = vi.fn();

    render(
      <SidebarNav
        activeView="map"
        onChangeView={onChangeViewMock}
        onManualSync={() => {}}
        onPrewarmHistory={() => {}}
        onLogout={() => {}}
        syncLabel="Manual Sync"
        syncStatusLabel="OK"
        lastSyncLabel="Baru saja"
        manualSyncBusy={false}
        prewarmBusy={false}
        healthStatus="normal"
        healthLabel="Sistem Normal"
        schedulerStatusLabel="OK"
        schedulerStatusColor="#10b981"
        schedulerStatusBg="rgba(16,185,129,0.15)"
        syncTodayRatio="100%"
        syncInterval="3 Jam"
        nextScheduledSyncLabel="3 Jam lagi"
        latestHotspotTimeLabel="1 jam lalu"
        dataAgeLabel="Segar"
        hasLatestHotspot={true}
        isAdmin={true}
      />
    );

    const wildfire3dBtn = screen.getByRole("button", { name: "Wildfire 3D Explorer" });
    expect(wildfire3dBtn).toBeInTheDocument();

    fireEvent.click(wildfire3dBtn);
    expect(onChangeViewMock).toHaveBeenCalledWith("wildfire3d");
  });
});
