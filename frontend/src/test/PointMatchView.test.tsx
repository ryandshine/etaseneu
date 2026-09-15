import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { PointMatchView } from "../components/PointMatchView";
import * as apiModule from "../lib/api";

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children?: React.ReactNode }) => <div data-testid="leaflet-map">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  GeoJSON: () => <div data-testid="leaflet-geojson" />,
  CircleMarker: ({ children }: { children?: React.ReactNode }) => <div data-testid="circle-marker">{children}</div>,
  Popup: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  useMap: () => ({ fitBounds: vi.fn() }),
}));

describe("PointMatchView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders upload dropzone with title and instructions", () => {
    render(<PointMatchView />);

    expect(screen.getByText("Cek Titik Api (Titik dan Poligon)")).toBeInTheDocument();
    expect(screen.getByText(/Tarik & lepas berkas titik atau poligon/i)).toBeInTheDocument();
  });

  it("handles polygon analysis results correctly", async () => {
    const mockPolygonResponse = {
      kind: "polygon",
      token: "poly-token-123",
      source_name: "areal_konsesi.geojson",
      source_format: "geojson",
      warnings: [],
      skipped_features: 0,
      polygon_info: {
        area_ha: 15420.5,
        bounds: [110.0, -1.0, 110.1, -1.1],
        overlaps_kps: true,
        kps_matches: [
          {
            id: 1,
            lembaga: "LPHD Bintang Jaya",
            skema: "HD",
            nama_kab: "Kapuas",
          },
        ],
      },
      summary: {
        total_hotspots: 5,
        confidence_high: 2,
        confidence_medium: 3,
        confidence_low: 0,
        density_per_1000ha: 0.32,
        by_month: [{ label: "Agustus", count: 5 }],
        by_satellite: [{ label: "VIIRS NOAA-20", count: 5 }],
        by_confidence: [
          { label: "Tinggi", count: 2 },
          { label: "Sedang", count: 3 },
          { label: "Rendah", count: 0 },
        ],
      },
      hotspots: [
        {
          id: 1,
          latitude: -1.05,
          longitude: 110.05,
          detected_at: "2026-08-15T10:00:00Z",
          detected_at_wib: "15 Agu 2026 17:00 WIB",
          satellite: "VIIRS NOAA-20",
          confidence: "h",
          confidence_level: "Tinggi",
          brightness: 340.5,
          frp: 21.0,
        },
      ],
      polygon_geojson: { type: "Polygon", coordinates: [] },
      preview_rows: [
        [1, "15 Agu 2026 17:00 WIB", "-1.05000", "110.05000", "VIIRS NOAA-20", "Tinggi", "340.5", "21.0"],
      ],
      preview_truncated: false,
    };

    vi.spyOn(apiModule, "authFetch").mockResolvedValueOnce({
      ok: true,
      json: async () => mockPolygonResponse,
    } as Response);

    const { container } = render(<PointMatchView />);

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['{"type": "FeatureCollection"}'], "areal_konsesi.geojson", { type: "application/geo+json" });

    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Mode Analisis Poligon Kawasan")).toBeInTheDocument();
    });

    expect(screen.getByText(/Kawasan Beririsan dengan Perhutanan Sosial/i)).toBeInTheDocument();
    expect(screen.getByText("Total Titik Panas (2026)")).toBeInTheDocument();
    expect(screen.getByTestId("leaflet-map")).toBeInTheDocument();
    expect(screen.getByText("Unduh Excel")).toBeInTheDocument();
    expect(screen.getByText("Unduh PDF")).toBeInTheDocument();
  });
});
