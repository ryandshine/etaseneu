import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Peta Leaflet + chart recharts tidak jalan mulus di jsdom (Canvas /
// ResizeObserver). Dimock persis pola KpsDetailView.test.tsx -- panel ini
// diuji untuk perilaku fetch/polling/state, bukan render peta.
vi.mock("react-leaflet", () => ({
  GeoJSON: ({ children }: { children?: ReactNode }) => <div data-testid="lc-geojson">{children}</div>,
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="lc-map">{children}</div>,
  TileLayer: () => <div data-testid="lc-tile" />,
  useMap: () => ({
    invalidateSize: () => undefined,
    fitBounds: () => undefined,
  }),
}));

vi.mock("recharts", () => ({
  Bar: () => <div />,
  BarChart: ({ children }: { children?: ReactNode }) => <div data-testid="lc-chart">{children}</div>,
  ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tooltip: () => <div />,
  XAxis: () => <div />,
  YAxis: () => <div />,
}));

import { LandCoverPanel } from "../components/LandCoverPanel";

const YEARS = (start = 2021) => Array.from({ length: 5 }, (_, i) => start + i);

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response;
}

const RESULT = {
  meta: {
    model_trees: 150,
    n_training: 7200,
    oob_accuracy: 0.81,
    duration_s: 131,
    computed_at: "2026-08-30T07:20:00+07:00",
    source: "s",
    label_source: "Google Dynamic World v1",
  },
  years: YEARS(),
  classes: ["hutan", "semak", "pertanian", "terbuka", "air"],
  table: Object.fromEntries(
    YEARS().map((y) => [
      String(y),
      {
        hutan: { area_ha: 100, pct: 60 },
        semak: { area_ha: 30, pct: 18 },
        pertanian: { area_ha: 20, pct: 12 },
        terbuka: { area_ha: 10, pct: 6 },
        air: { area_ha: 6, pct: 4 },
      },
    ]),
  ),
  net_change: { hutan: -50, semak: 20, pertanian: 20, terbuka: 8, air: 2 },
  summary_text: "Tutupan Hutan turun 50 ha (-9.1%) dari 2021 ke 2025.",
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mockFetch(handler: (url: string, init?: RequestInit) => Response) {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(
    async (url: string, init?: RequestInit) => handler(String(url), init),
  );
}

describe("LandCoverPanel", () => {
  it("idle: shows the run button", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({ state: "idle", step: null, error: null, computed_at: null });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    expect(
      await screen.findByRole("button", { name: /jalankan analisis/i }),
    ).toBeInTheDocument();
  });

  it("clicking the button posts analyze and switches to running text", async () => {
    const calls: string[] = [];
    mockFetch((url) => {
      calls.push(url);
      if (url.includes("/land-cover/analyze")) {
        return jsonResponse({ started: true, polygon_id: 1 }, 202);
      }
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: calls.some((c) => c.includes("/analyze")) ? "running" : "idle",
          step: "2023 (4/6) — klasifikasi",
          error: null,
          computed_at: null,
        });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    fireEvent.click(await screen.findByRole("button", { name: /jalankan analisis/i }));
    await waitFor(() => expect(calls.some((c) => c.includes("/land-cover/analyze"))).toBe(true));
    expect(await screen.findByText(/Menghitung/i)).toBeInTheDocument();
  });

  it("done: renders the 5-class legend and the summary", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: "done",
          step: null,
          error: null,
          computed_at: RESULT.meta.computed_at,
        });
      }
      if (url.includes("/land-cover/result")) return jsonResponse(RESULT);
      if (url.includes("/land-cover/overlay")) {
        return jsonResponse({ type: "FeatureCollection", features: [] });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    const legend = await screen.findByRole("list", {
      name: /legenda kelas tutupan lahan/i,
    });
    expect(within(legend).getByText("Hutan")).toBeInTheDocument();
    expect(within(legend).getByText("Semak/Belukar")).toBeInTheDocument();
    expect(within(legend).getByText("Pertanian/Kebun")).toBeInTheDocument();
    expect(within(legend).getByText("Lahan Terbuka")).toBeInTheDocument();
    expect(within(legend).getByText("Badan Air")).toBeInTheDocument();
    expect(await screen.findByText(/Tutupan Hutan turun 50 ha/i)).toBeInTheDocument();
  });

  it("done: changing the year slider refetches overlay with the new year", async () => {
    const overlayYears: string[] = [];
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: "done",
          step: null,
          error: null,
          computed_at: RESULT.meta.computed_at,
        });
      }
      if (url.includes("/land-cover/result")) return jsonResponse(RESULT);
      if (url.includes("/land-cover/overlay")) {
        overlayYears.push(new URL(url, "http://x").searchParams.get("year") ?? "");
        return jsonResponse({ type: "FeatureCollection", features: [] });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    await screen.findByText("Hutan");
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "2024" } });
    await waitFor(() => expect(overlayYears).toContain("2024"));
  });
});
