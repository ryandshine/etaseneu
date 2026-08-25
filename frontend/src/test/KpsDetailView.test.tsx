import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// KpsDetailView me-render peta Leaflet (CircleMarker canvas-based) yang tidak
// bisa jalan di jsdom (Canvas.getContext tidak diimplementasikan) -- dimock
// persis pola yang sudah dipakai HotspotMap.test.tsx, bukan dites di sini
// (peta sudah ditest lewat HotspotMap.test.tsx / App.test.tsx).
vi.mock("react-leaflet", () => ({
  CircleMarker: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  GeoJSON: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  LayerGroup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="leaflet-map">{children}</div>,
  Pane: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  useMap: () => ({ fitBounds: vi.fn(), invalidateSize: vi.fn(), getContainer: () => document.createElement("div") })
}));

import { KpsDetailView } from "../components/KpsDetailView";
import type { DashboardHotspot } from "../hooks/useDashboardData";

// KpsDetailView fetch beberapa endpoint saat mount (detail polygon, riwayat
// KLHK) lepas dari filter waktu kustom yang ditest di sini -- semuanya perlu
// dimock supaya tidak coba jaringan sungguhan di jsdom.
const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const polygonDetail = {
  id: 292425,
  layer_key: "psagustus2026",
  feature_key: "292425",
  lembaga: "LD LINGAT",
  nama_prov: "Riau",
  nama_kab: null,
  nama_kec: null,
  nama_desa: null,
  skema: null,
  no_sk: null,
  tgl_sk: null,
  status: null,
  wilker_bps: null,
  ps_id: null,
  luas_final: null,
  jml_kk: null,
  geometry: { type: "Polygon", coordinates: [] }
};

beforeEach(() => {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    if (url.startsWith("/api/polygons/")) {
      return jsonResponse(polygonDetail);
    }
    if (url.startsWith("/api/burned-area/summary")) {
      return jsonResponse({ rows: [], unique_ha: null });
    }
    if (url.startsWith("/api/burned-area/geometry")) {
      return jsonResponse({ type: "FeatureCollection", features: [] });
    }
    if (url.startsWith("/api/hotspots")) {
      return jsonResponse({
        count: 1,
        hotspots: [
          {
            id: "custom-1",
            source: "NASA FIRMS",
            satellite: "MODIS",
            latitude: -1.1,
            longitude: 113.1,
            brightness: 330,
            frp: 15,
            confidence: "high",
            daynight: "D",
            detected_at: "2026-04-10T02:00:00Z",
            layer_name: "LD LINGAT",
            agency_name: "LD LINGAT",
            province_name: "Riau",
            polygon_metadata: { LEMBAGA: "LD LINGAT", polygon_metadata_id: "292425" }
          }
        ],
        stats: { total: 1, by_source: {}, by_layer: {} }
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function buildHotspot(overrides: Partial<DashboardHotspot> = {}): DashboardHotspot {
  return {
    id: "dashboard-1",
    latitude: -1.234,
    longitude: 113.456,
    source: "NASA FIRMS",
    satellite: "MODIS",
    layerName: "LD LINGAT",
    agencyName: "LD LINGAT",
    provinceName: "Riau",
    brightness: 321.45,
    frp: 12.4,
    confidence: "high",
    daynight: "D",
    detectedAt: "2026-05-28T00:10:59Z",
    polygonMetadata: { LEMBAGA: "LD LINGAT", polygon_metadata_id: "292425" },
    ...overrides
  };
}

describe("KpsDetailView", () => {
  it("defaults to the dashboard's hotspots with no custom filter applied", async () => {
    render(
      <KpsDetailView
        agency="LD LINGAT"
        hotspots={[buildHotspot()]}
        onClose={() => undefined}
        onExportPdf={() => undefined}
        isExportingPdf={false}
      />
    );

    expect(screen.getByText("Mengikuti rentang waktu dashboard saat ini.")).toBeInTheDocument();
    expect(screen.getByText("1 titik")).toBeInTheDocument();
    // Fetch kustom belum boleh terpanggil selama kedua tanggal belum diisi.
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith("/api/hotspots"))).toBe(false);
  });

  it("switches to a custom-fetched hotspot set once both dates are filled, and resets on demand", async () => {
    render(
      <KpsDetailView
        agency="LD LINGAT"
        hotspots={[buildHotspot(), buildHotspot({ id: "dashboard-2" })]}
        onClose={() => undefined}
        onExportPdf={() => undefined}
        isExportingPdf={false}
      />
    );

    // Total awal (mode default) datang dari 2 hotspot yang dilewatkan via prop.
    expect(await screen.findByText("2 titik")).toBeInTheDocument();

    const dateInputs = document.querySelectorAll('input[type="date"]');
    expect(dateInputs.length).toBe(2);

    fireEvent.change(dateInputs[0], { target: { value: "2026-04-01" } });
    fireEvent.change(dateInputs[1], { target: { value: "2026-04-30" } });

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => String(input).startsWith("/api/hotspots"))).toBe(true)
    );

    // Fetch custom mengembalikan cuma 1 hotspot ("custom-1") -- daftar & total
    // harus mengikuti hasil itu, bukan lagi 2 dari prop `hotspots` semula.
    await waitFor(() => expect(screen.getByText("1 titik")).toBeInTheDocument());
    expect(
      screen.getByText("Menampilkan titik hotspot & riwayat bekas terbakar untuk rentang kustom ini saja.")
    ).toBeInTheDocument();

    const resetButton = screen.getByText("Kembali ke rentang dashboard");
    fireEvent.click(resetButton);

    await waitFor(() => expect(screen.getByText("2 titik")).toBeInTheDocument());
    expect(screen.getByText("Mengikuti rentang waktu dashboard saat ini.")).toBeInTheDocument();
  });
});
