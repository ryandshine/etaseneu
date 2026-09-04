import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  Line: () => <div />,
  LineChart: ({ children }: { children?: ReactNode }) => <div data-testid="lc-chart">{children}</div>,
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
    render(<LandCoverPanel polygonId={1} isAdmin />);
    expect(
      await screen.findByRole("button", { name: /jalankan analisis/i }),
    ).toBeInTheDocument();
  });

  it("idle: disables the run button and shows a hint when another polygon is busy", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: "idle",
          step: null,
          error: null,
          computed_at: null,
          busy_elsewhere: true,
        });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} isAdmin />);
    const button = await screen.findByRole("button", { name: /jalankan analisis/i });
    expect(button).toBeDisabled();
    expect(screen.getByText(/analisis .* lain sedang berjalan/i)).toBeInTheDocument();
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
    render(<LandCoverPanel polygonId={1} isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: /jalankan analisis/i }));
    await waitFor(() => expect(calls.some((c) => c.includes("/land-cover/analyze"))).toBe(true));
    expect(await screen.findByText(/Menghitung/i)).toBeInTheDocument();
  });

  it("done: defaults to the Peta Spasial tab, showing the floating per-class area grid", async () => {
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
    render(<LandCoverPanel polygonId={1} isAdmin />);
    // year mulai dari LAST_YEAR (2025) saat panel baru masuk state "done".
    const classGrid = await screen.findByRole("list", { name: /luas per kelas tahun 2025/i });
    expect(within(classGrid).getByText("Hutan")).toBeInTheDocument();
    expect(within(classGrid).getByText("Semak/Belukar")).toBeInTheDocument();
    expect(within(classGrid).getByText("Pertanian/Kebun")).toBeInTheDocument();
    expect(within(classGrid).getByText("Lahan Terbuka")).toBeInTheDocument();
    expect(within(classGrid).getByText("Badan Air")).toBeInTheDocument();
    // Data RESULT.table punya hutan area_ha:100 pct:60 di tiap tahun.
    expect(within(classGrid).getByText("100 ha")).toBeInTheDocument();
    // Grafik/tabel/ringkasan ada di tab lain, belum tampil di tab default.
    expect(screen.queryByText(/Tutupan Hutan turun 50 ha/i)).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /peta spasial/i })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("done: switching to the Tren Historis tab reveals the chart, table, and summary", async () => {
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
    render(<LandCoverPanel polygonId={1} isAdmin />);
    await screen.findByRole("list", { name: /luas per kelas tahun 2025/i });
    fireEvent.click(screen.getByRole("tab", { name: /tren historis/i }));
    expect(await screen.findByTestId("lc-chart")).toBeInTheDocument();
    expect(await screen.findByText(/Tutupan Hutan turun 50 ha/i)).toBeInTheDocument();
    // Tabel bertingkat: ha & persen sebagai elemen terpisah, bukan satu baris
    // inline (RESULT punya hutan 100ha/60% identik tiap tahun -> muncul >1x).
    expect(screen.getAllByText("100 ha").length).toBeGreaterThan(0);
    expect(screen.getAllByText("60.0%").length).toBeGreaterThan(0);
  });

  it("done: hides a class row entirely when it has no meaningful area in any year", async () => {
    const zeroClassResult = {
      ...RESULT,
      table: Object.fromEntries(
        YEARS().map((y) => [
          String(y),
          {
            hutan: { area_ha: 100, pct: 76.9 },
            semak: { area_ha: 30, pct: 23.1 },
            // pertanian/terbuka/air tidak pernah ada di poligon ini.
          },
        ]),
      ),
      net_change: { hutan: -10, semak: 10, pertanian: 0, terbuka: 0, air: 0 },
    };
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: "done",
          step: null,
          error: null,
          computed_at: RESULT.meta.computed_at,
        });
      }
      if (url.includes("/land-cover/result")) return jsonResponse(zeroClassResult);
      if (url.includes("/land-cover/overlay")) {
        return jsonResponse({ type: "FeatureCollection", features: [] });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} isAdmin />);
    await screen.findByRole("list", { name: /luas per kelas tahun 2025/i });
    fireEvent.click(screen.getByRole("tab", { name: /tren historis/i }));
    await screen.findByText(/Tutupan Hutan/i);
    expect(screen.queryByText("Pertanian/Kebun")).not.toBeInTheDocument();
    expect(screen.queryByText("Lahan Terbuka")).not.toBeInTheDocument();
    expect(screen.queryByText("Badan Air")).not.toBeInTheDocument();
    expect(screen.getByText(/4 kelas lain tidak ditemukan di poligon ini/i)).toBeInTheDocument();
  });

  it("done: 'Hapus hasil' sends DELETE and returns the panel to idle", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let deleted = false;
    mockFetch((url, init) => {
      if (url.includes("/land-cover/result") && init?.method === "DELETE") {
        deleted = true;
        return jsonResponse({ deleted: true, polygon_id: 1 });
      }
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: deleted ? "idle" : "done",
          step: null,
          error: null,
          computed_at: deleted ? null : RESULT.meta.computed_at,
        });
      }
      if (url.includes("/land-cover/result")) return jsonResponse(RESULT);
      if (url.includes("/land-cover/overlay")) {
        return jsonResponse({ type: "FeatureCollection", features: [] });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} isAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: /hapus hasil/i }));
    await waitFor(() => expect(deleted).toBe(true));
    expect(
      await screen.findByRole("button", { name: /jalankan analisis/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /analisis ulang/i })).not.toBeInTheDocument();
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
    render(<LandCoverPanel polygonId={1} isAdmin />);
    await screen.findByText("Hutan");
    const slider = screen.getByRole("slider");
    fireEvent.change(slider, { target: { value: "2024" } });
    await waitFor(() => expect(overlayYears).toContain("2024"));
  });
});

describe("LandCoverPanel role & formula version", () => {
  it("non-admin: no run button in idle, only a hint", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({ state: "idle", step: null, error: null, computed_at: null });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    expect(await screen.findByText(/hanya bisa dilakukan admin/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /jalankan analisis/i })).not.toBeInTheDocument();
  });

  it("non-admin: no 'Hapus hasil' button when done", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: "done", step: null, error: null, computed_at: RESULT.meta.computed_at,
          formula_version: 2, current_formula_version: 2,
        });
      }
      if (url.includes("/land-cover/result")) return jsonResponse(RESULT);
      if (url.includes("/land-cover/overlay")) {
        return jsonResponse({ type: "FeatureCollection", features: [] });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} />);
    await screen.findByRole("list", { name: /luas per kelas tahun 2025/i });
    expect(screen.queryByRole("button", { name: /hapus hasil/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/metode lama/i)).not.toBeInTheDocument();
  });

  it("done: shows 'Metode lama' badge when stored formula_version < current", async () => {
    mockFetch((url) => {
      if (url.includes("/land-cover/status")) {
        return jsonResponse({
          state: "done", step: null, error: null, computed_at: RESULT.meta.computed_at,
          formula_version: 1, current_formula_version: 2,
        });
      }
      if (url.includes("/land-cover/result")) return jsonResponse(RESULT);
      if (url.includes("/land-cover/overlay")) {
        return jsonResponse({ type: "FeatureCollection", features: [] });
      }
      return jsonResponse({}, 404);
    });
    render(<LandCoverPanel polygonId={1} isAdmin />);
    expect(await screen.findByText(/metode lama \(v1\)/i)).toBeInTheDocument();
  });
});

describe("LandCoverPanel polling", () => {
  it("keeps polling while running even when the step text does not change", async () => {
    vi.useFakeTimers();
    try {
      let calls = 0;
      mockFetch((url) => {
        if (url.includes("/land-cover/status")) {
          calls += 1;
          return jsonResponse({
            state: "running",
            step: "mengunduh sampel latih",
            error: null,
            computed_at: null,
          });
        }
        return jsonResponse({}, 404);
      });
      render(<LandCoverPanel polygonId={1} isAdmin />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const first = calls;
      expect(first).toBeGreaterThanOrEqual(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000 * 3 + 50);
      });
      // Dulu: setTimeout dijadwal ulang lewat dep [state, step] -> berhenti
      // setelah 1 poll kalau step tidak berubah.
      expect(calls).toBeGreaterThanOrEqual(first + 3);
    } finally {
      vi.useRealTimers();
    }
  });
});
