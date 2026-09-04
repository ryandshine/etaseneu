import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// LandCoverPanel (dirender di panel detail) pakai react-leaflet + recharts --
// dimock persis pola LandCoverPanel.test.tsx, komponen ini tidak dites lewat
// peta/grafik sungguhan.
vi.mock("react-leaflet", () => ({
  GeoJSON: ({ children }: { children?: ReactNode }) => <div data-testid="lc-geojson">{children}</div>,
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="lc-map">{children}</div>,
  TileLayer: () => <div data-testid="lc-tile" />,
  useMap: () => ({ invalidateSize: () => undefined, fitBounds: () => undefined }),
}));

vi.mock("recharts", () => ({
  Line: () => <div />,
  LineChart: ({ children }: { children?: ReactNode }) => <div data-testid="lc-chart">{children}</div>,
  ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tooltip: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
}));

import { TutupanLahanView } from "../components/TutupanLahanView";

const ROWS = [
  {
    polygon_metadata_id: 1,
    layer_key: "psagustus2026",
    lembaga: "GAPOKTAN MEKAR JAYA",
    nama_prov: "Riau",
    nama_kab: "Kampar",
    nama_kec: null,
    skema: "HD",
    wilker_bps: "Balai PS Kampar",
    luas_final: 120.5,
    land_cover_status: "done",
    land_cover_computed_at: "2026-08-30T00:00:00",
  },
  {
    polygon_metadata_id: 2,
    layer_key: "HUTAN_ADAT_APR26",
    lembaga: "MHA BATU BATU",
    nama_prov: "Sumatera Selatan",
    nama_kab: "OKI",
    nama_kec: null,
    skema: null,
    wilker_bps: "Balai PS Palembang",
    luas_final: 50.0,
    land_cover_status: null,
    land_cover_computed_at: null,
  },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    if (url.startsWith("/api/land-cover/polygons")) {
      return jsonResponse(ROWS);
    }
    if (url.startsWith("/api/land-cover/status")) {
      return jsonResponse({ state: "idle", step: null, error: null, computed_at: null });
    }
    if (url.startsWith("/api/polygons/")) {
      return jsonResponse({ type: "FeatureCollection", features: [] });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("TutupanLahanView", () => {
  it("lists all fetched polygons with their status badge", async () => {
    render(<TutupanLahanView />);

    expect(await screen.findByText("GAPOKTAN MEKAR JAYA")).toBeInTheDocument();
    expect(screen.getByText("MHA BATU BATU")).toBeInTheDocument();
    const list = within(document.querySelector(".tl-list-scroll") as HTMLElement);
    expect(list.getByText(/Sudah dianalisis/)).toBeInTheDocument();
    expect(list.getByText("Belum dianalisis")).toBeInTheDocument();
    const summary = await waitFor(() => {
      const el = document.querySelector(".tl-summary");
      if (!el || el.textContent === "Memuat…") throw new Error("not ready");
      return el;
    });
    expect(summary.textContent).toBe("1 dari 2 poligon telah dianalisis");
  });

  it("filters the list by search text", async () => {
    render(<TutupanLahanView />);
    await screen.findByText("GAPOKTAN MEKAR JAYA");

    fireEvent.change(screen.getByPlaceholderText("Cari nama KPS/Hutan Adat…"), {
      target: { value: "batu batu" },
    });
    fireEvent.click(screen.getByText("Cari"));

    expect(screen.queryByText("GAPOKTAN MEKAR JAYA")).not.toBeInTheDocument();
    expect(screen.getByText("MHA BATU BATU")).toBeInTheDocument();
  });

  it("opens the reused LandCoverPanel detail when a row is clicked", async () => {
    render(<TutupanLahanView isAdmin />);
    const row = await screen.findByText("GAPOKTAN MEKAR JAYA");
    fireEvent.click(row.closest('[role="button"]') as HTMLElement);

    expect(
      await screen.findByRole("button", { name: /jalankan analisis/i }),
    ).toBeInTheDocument();
  });

  it("filters via the Filter popover, shows a removable pill, and clearing it restores the list", async () => {
    render(<TutupanLahanView />);
    await screen.findByText("GAPOKTAN MEKAR JAYA");

    fireEvent.click(screen.getByRole("button", { name: /^filter$/i }));
    const provinceSelect = screen.getByLabelText("Provinsi") as HTMLSelectElement;
    fireEvent.change(provinceSelect, { target: { value: "Sumatera Selatan" } });

    expect(screen.queryByText("GAPOKTAN MEKAR JAYA")).not.toBeInTheDocument();
    expect(screen.getByText("MHA BATU BATU")).toBeInTheDocument();

    const pill = screen.getByRole("button", { name: /hapus filter sumatera selatan/i });
    expect(pill).toBeInTheDocument();

    fireEvent.click(pill);
    expect(await screen.findByText("GAPOKTAN MEKAR JAYA")).toBeInTheDocument();
  });

  it("preselects a polygon from initialPolygonId", async () => {
    render(<TutupanLahanView initialPolygonId={2} isAdmin />);

    expect(
      await screen.findByRole("button", { name: /jalankan analisis/i }),
    ).toBeInTheDocument();
  });
});
