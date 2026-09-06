import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SiagaRambatanApiView } from "../components/SiagaRambatanApiView";
import * as apiModule from "../lib/api";

vi.mock("react-leaflet", () => ({
  CircleMarker: ({ children }: { children?: ReactNode }) => <div data-testid="circle-marker">{children}</div>,
  Circle: () => <div data-testid="circle-buffer" />,
  Polyline: () => <div data-testid="polyline-vector" />,
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="map-container">{children}</div>,
  GeoJSON: () => <div data-testid="geojson" />,
  Popup: ({ children }: { children?: ReactNode }) => <div data-testid="popup">{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  useMap: () => ({ fitBounds: vi.fn(), flyTo: vi.fn() })
}));

const mockSummary = {
  total_kps_threatened: 15,
  total_external_hotspots: 45,
  bahaya_count: 5,
  waspada_count: 6,
  pantau_count: 4,
  time_window_hours: 48,
  max_distance_km: 5.0,
};

const mockThreats = [
  {
    polygon_id: 101,
    lembaga: "KPS Rimba Lestari",
    nama_kps: "KPS Rimba Lestari",
    nama_desa: "Desa Rimba",
    nama_kec: "Kecamatan Hijau",
    nama_kab: "Lamandau",
    nama_prov: "Kalimantan Tengah",
    skema: "HD",
    no_sk: "SK.123",
    wilker_bps: "BPSKL Kalimantan",
    luas_ha: 1500.0,
    min_distance_m: 350,
    min_distance_km: 0.35,
    status_level: "bahaya",
    status_label: "Bahaya Kritis (< 1 km)",
    external_hotspots_count: 8,
    max_frp: 42.0,
    avg_frp: 21.5,
    bearing_deg: 315.0,
    bearing_compass: "Barat Laut (NW)",
    rekomendasi: "DARURAT: Api berjarak 350 m dari arah Barat Laut (NW)",
    nearest_hotspot: {
      coordinates: [111.5, -2.1],
      satellite: "N21",
      confidence: "h",
      detected_at: "2026-09-06 10:00:00 +07",
    },
    nearest_boundary_point: [111.502, -2.102],
  },
];

const mockDetail = {
  polygon_id: 101,
  lembaga: "KPS Rimba Lestari",
  nama_kps: "KPS Rimba Lestari",
  nama_desa: "Desa Rimba",
  nama_kec: "Kecamatan Hijau",
  nama_kab: "Lamandau",
  nama_prov: "Kalimantan Tengah",
  skema: "HD",
  no_sk: "SK.123",
  wilker_bps: "BPSKL Kalimantan",
  luas_ha: 1500.0,
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [111.5, -2.1],
        [111.55, -2.1],
        [111.55, -2.15],
        [111.5, -2.15],
        [111.5, -2.1],
      ],
    ],
  },
  centroid: [111.525, -2.125],
  status_level: "bahaya",
  status_label: "Bahaya Kritis (< 1 km)",
  min_distance_m: 350,
  min_distance_km: 0.35,
  total_external_hotspots: 1,
  total_internal_hotspots: 2,
  hotspots: [
    {
      id: 998,
      latitude: -2.12,
      longitude: 111.52,
      satellite: "N21",
      confidence: "h",
      brightness: 355.0,
      frp: 50.0,
      detected_at: "2026-09-06 10:15:00 +07",
      is_inside: true,
      distance_m: 0,
      distance_km: 0.0,
      status_level: "internal",
      status_label: "Di Dalam Kawasan",
      bearing_deg: null,
      bearing_compass: "Dalam Kawasan",
      closest_kps_point: null,
    },
    {
      id: 999,
      latitude: -2.1,
      longitude: 111.5,
      satellite: "N21",
      confidence: "h",
      brightness: 340.0,
      frp: 42.0,
      detected_at: "2026-09-06 10:00:00 +07",
      is_inside: false,
      distance_m: 350,
      distance_km: 0.35,
      status_level: "bahaya",
      status_label: "Bahaya Kritis (< 1 km)",
      bearing_deg: 315.0,
      bearing_compass: "Barat Laut (NW)",
      closest_kps_point: [111.502, -2.102],
    },
  ],
  neighbors: [
    {
      id: 202,
      lembaga: "KPS Rimba Sebelah",
      nama_desa: "Desa Tetangga",
      nama_kec: "Kecamatan Hijau",
      nama_kab: "Lamandau",
      skema: "HKm",
      luas_ha: 850.0,
      distance_m: 0,
      distance_km: 0.0,
      hotspot_count: 5,
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [111.45, -2.1],
            [111.5, -2.1],
            [111.5, -2.15],
            [111.45, -2.15],
            [111.45, -2.1],
          ],
        ],
      },
    },
  ],
  closest_vector: {
    hotspot_coords: [111.5, -2.1],
    kps_boundary_coords: [111.502, -2.102],
    distance_m: 350,
    bearing_compass: "Barat Laut (NW)",
  },
  time_window_hours: 48,
  max_distance_km: 5.0,
};

describe("SiagaRambatanApiView", () => {
  beforeEach(() => {
    vi.spyOn(apiModule, "authFetch").mockImplementation((url: string) => {
      if (url.includes("/api/fire-spread/summary")) {
        return Promise.resolve(new Response(JSON.stringify(mockSummary), { status: 200 }));
      }
      if (url.includes("/api/fire-spread/threats")) {
        return Promise.resolve(new Response(JSON.stringify({ items: mockThreats, total: 1 }), { status: 200 }));
      }
      if (url.includes("/api/fire-spread/detail")) {
        return Promise.resolve(new Response(JSON.stringify(mockDetail), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders summary cards and threat item correctly", async () => {
    render(<SiagaRambatanApiView />);

    await waitFor(() => {
      expect(screen.getByText("Siaga Rambatan Api (Deteksi Ancaman Luar KPS)")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByText("KPS Rimba Lestari")).toBeInTheDocument();
      expect(screen.getByText("350 m")).toBeInTheDocument();
      expect(screen.getByText("Barat Laut (NW)")).toBeInTheDocument();
    });

    // Cek tampilan indikator hotspot internal dan KPS tetangga
    await waitFor(() => {
      expect(screen.getByText(/2 hotspot di DALAM/)).toBeInTheDocument();
      expect(screen.getByText(/1 KPS sekitar/)).toBeInTheDocument();
    });
  });

  it("allows filtering by time window", async () => {
    render(<SiagaRambatanApiView />);

    await waitFor(() => {
      expect(screen.getByText("KPS Rimba Lestari")).toBeInTheDocument();
    });

    const timeSelect = screen.getByDisplayValue("48 Jam Terakhir");
    fireEvent.change(timeSelect, { target: { value: "24" } });

    await waitFor(() => {
      expect(apiModule.authFetch).toHaveBeenCalledWith(expect.stringContaining("time_window_hours=24"));
    });
  });
});
