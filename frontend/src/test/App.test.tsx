import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import { loginThroughUI } from "./testHelpers";

// Overlay Fungsi Kawasan Hutan (default nyala sejak 2026-09-04, lihat
// HotspotMap.tsx) manipulasi L.Map asli (getPane/createPane/addLayer) lewat
// useMap() -- di luar jangkauan mock react-leaflet ringan di bawah. Diganti
// no-op supaya render map tetap bisa diuji tanpa mensimulasikan Leaflet penuh.
vi.mock("../components/KawasanHutanLayer", () => ({
  KawasanHutanLayer: () => null
}));

vi.mock("react-leaflet", () => ({
  CircleMarker: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  GeoJSON: ({ children }: { children?: ReactNode }) => (
    <div data-testid="geojson-layer">{children}</div>
  ),
  MapContainer: ({ children }: { children?: ReactNode }) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  // Ditambah bareng fitur pane z-index eksplisit di HotspotMap.tsx -- tanpa
  // ini HotspotMap crash saat mount ("No Pane export"), lihat komentar sama
  // di HotspotMap.test.tsx.
  Pane: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  // Titik hotspot dibungkus <LayerGroup> supaya bisa di-bringToFront() di
  // atas polygon bekas terbakar (satu Pane/renderer yang sama) -- lihat
  // catatan di HotspotMap.tsx & KpsDetailView.tsx.
  LayerGroup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Marker: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Circle: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tooltip: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  ZoomControl: () => <div data-testid="zoom-control" />,
  ScaleControl: () => <div data-testid="scale-control" />,
  useMap: () => ({ fitBounds: vi.fn(), getZoom: () => 5 }),
  useMapEvents: () => ({})
}));

describe("App", () => {
  const fetchMock = vi.fn<typeof fetch>();
  let schedulerMetricsCallCount = 0;

  beforeEach(() => {
    schedulerMetricsCallCount = 0;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);

      if (url === "/api/auth/login") {
        // Gerbang login (App.tsx) -- terpisah dari /api/auth/verify (gerbang
        // Pengaturan, cuma dipakai role non-admin sejak admin login otomatis
        // melewatinya -- lihat App.tsx::handleViewChange). Password tidak
        // dicek di sini; role ditentukan dari username yang dikirim supaya
        // test yang butuh sesi non-admin (mis. tes gerbang password) bisa
        // login lewat testHelpers.ts::loginThroughUI(username) dengan
        // username selain "admin".
        const body = init?.body ? JSON.parse(String(init.body)) : {};
        const isAdmin = body.username === "admin";
        return new Response(
          JSON.stringify({
            ok: true,
            token: "test-token",
            username: body.username ?? "admin",
            role: isAdmin ? "admin" : "user"
          }),
          { status: 200 }
        );
      }

      if (url === "/api/auth/session") {
        return new Response(
          JSON.stringify({ ok: true, username: "admin", role: "admin", expires_at: "2026-09-25T00:00:00+00:00" }),
          { status: 200 }
        );
      }

      if (url === "/api/auth/logout") {
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      }

      if (url === "/api/auth/verify") {
        const headers = new Headers(init?.headers);
        const key = headers.get("X-Admin-Key");
        return key === "correct-admin-key"
          ? new Response(JSON.stringify({ ok: true }), { status: 200 })
          : new Response(JSON.stringify({ detail: "Admin key tidak valid." }), { status: 401 });
      }

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

      if (url.startsWith("/api/land-cover/polygons")) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        });
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.history.replaceState({}, "", "/");
  });

  it("shows a loading state instead of a false 'fallback file' status while status data is in flight", async () => {
    // Fase "belum tiba" dulu ditampilkan memakai cabang else yang sama dengan
    // kondisi buruk, jadi panel sempat menyatakan database fallback dan
    // scheduler nonaktif padahal keduanya sehat -- cuma requestnya belum
    // selesai. Request status sengaja digantung di sini supaya fase itu bisa
    // diperiksa.
    const neverResolves = new Promise<Response>(() => {});
    const baseImplementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/storage/status" || url === "/api/scheduler/metrics") {
        return neverResolves;
      }
      return baseImplementation(input, init);
    });

    render(<App />);
    await loginThroughUI();

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(screen.getAllByText("memuat...").length).toBeGreaterThan(0);
    expect(screen.queryByText("fallback file")).not.toBeInTheDocument();
    expect(screen.queryByText("Nonaktif")).not.toBeInTheDocument();
    expect(screen.queryByText("never")).not.toBeInTheDocument();
  });

  it("tidak memuat data dashboard sebelum login", async () => {
    render(<App />);
    // LoginPage tampil, belum login.
    expect(await screen.findByLabelText("Username")).toBeInTheDocument();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    const dashboardCalls = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url !== "/api/auth/login");
    expect(dashboardCalls).toEqual([]);
  });

  it("kembali ke LoginPage saat panggilan API balas 401 (sesi kadaluarsa)", async () => {
    render(<App />);
    await loginThroughUI();
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    // Dashboard sudah termuat (semua fetch 200 dari mock default).
    expect(await screen.findByTestId("leaflet-map")).toBeInTheDocument();

    // Mulai sekarang, refetch hotspot balas 401.
    const baseImpl = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((input, init) => {
      const url = String(input);
      if (url.startsWith("/api/hotspots")) {
        return Promise.resolve(new Response("unauthorized", { status: 401 }));
      }
      return baseImpl(input, init);
    });

    // Ubah filter waktu -> memicu refetch hotspot -> 401 -> handler di App.tsx
    // -> setSession(null) -> LoginPage kembali.
    const presetButtons = screen.getAllByRole("button", { name: /hari|jam/i });
    fireEvent.click(presetButtons[presetButtons.length - 1]);

    expect(
      await screen.findByLabelText("Username", {}, { timeout: 3000 })
    ).toBeInTheDocument();
  });

  it("restores the matrix view from the URL on load", async () => {
    window.history.replaceState({}, "", "/?view=matrix");
    render(<App />);
    await loginThroughUI();

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(screen.getByText("Matriks & Rekapitulasi Data")).toBeInTheDocument();
  });

  it("does not restore the password-gated settings view from the URL", async () => {
    // Gerbangnya berjalan di sisi klien, jadi memulihkan view ini dari tautan
    // sama saja menyediakan jalan pintas melewatinya.
    window.history.replaceState({}, "", "/?view=settings");
    render(<App />);
    await loginThroughUI();

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(await screen.findByTestId("leaflet-map")).toBeInTheDocument();
  });

  it("writes the active view to the URL when navigating", async () => {
    render(<App />);
    await loginThroughUI();

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    fireEvent.click(screen.getByRole("button", { name: /matriks data/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(window.location.search).toBe("?view=matrix");

    fireEvent.click(screen.getByRole("button", { name: /live map/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(window.location.search).toBe("");
  });

  it("restores the landcover view from the URL on load", async () => {
    window.history.replaceState({}, "", "/?view=landcover");
    render(<App />);
    await loginThroughUI();

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(screen.getByRole("heading", { name: "Tutupan Lahan" })).toBeInTheDocument();
  });

  it("writes the landcover view to the URL when navigating there", async () => {
    render(<App />);
    await loginThroughUI();

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    fireEvent.click(screen.getByRole("button", { name: /tutupan lahan/i }));
    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(window.location.search).toBe("?view=landcover");
  });

  it("collapses the sidebar to an icon rail on desktop and remembers the choice on remount", async () => {
    // useIsDesktopWide dites terpisah lewat matchMedia sungguhan -- di sini
    // di-stub eksplisit supaya perilakunya deterministik terlepas dari
    // ukuran viewport default jsdom. jsdom TIDAK menyediakan window.matchMedia
    // sama sekali (hook lain di app sudah bergantung pada itu lewat guard
    // `typeof window.matchMedia !== "function"`) -- jadi nilai aslinya
    // ditangkap dan dikembalikan persis (bukan vi.unstubAllGlobals(), yang
    // ternyata tidak memulihkan window.matchMedia dengan benar di sini dan
    // membocorkan stub rusak ke test lain).
    const originalMatchMedia = window.matchMedia;
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: query.includes("1024px"),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined
      }))
    );

    // try/finally: kalau assertion di bawah gagal, matchMedia HARUS tetap
    // dipulihkan -- kalau tidak, stub vi.fn() ini ke-reset (bukan ke-hapus)
    // oleh vi.restoreAllMocks() di afterEach global file ini, lalu bocor jadi
    // "function yang manggil balik undefined" ke SEMUA test sesudahnya (beda
    // dari kondisi asli window.matchMedia yang memang tidak ada sama sekali).
    try {
      const { unmount } = render(<App />);
      await loginThroughUI();
      await act(async () => {
        await vi.dynamicImportSettled();
      });

      expect(screen.getByText("Matriks Data")).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /perkecil menu samping/i }));

      // Label teks hilang, tapi menu tetap bisa dijangkau lewat nama aksesibel.
      expect(screen.queryByText("Matriks Data")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Matriks Data" })).toBeInTheDocument();
      expect(window.localStorage.getItem("etaseneu.sidebar.collapsed.v1")).toBe("1");

      unmount();

      // Remount (mis. reload halaman) -- sesi SUDAH persisted (pola sama
      // seperti test "memulihkan sesi tersimpan...") jadi tidak login ulang,
      // langsung cek preferensi collapsed dipulihkan tanpa klik ulang.
      render(<App />);
      expect(await screen.findByRole("button", { name: /pengaturan/i })).toBeInTheDocument();
      expect(screen.queryByText("Matriks Data")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Matriks Data" })).toBeInTheDocument();
    } finally {
      vi.stubGlobal("matchMedia", originalMatchMedia);
    }
  });

  it("renders the frontend shell heading", async () => {
    render(<App />);
    await loginThroughUI();

    expect(screen.getAllByText("ETAseneu").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("button", { name: /matriks data/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pengaturan/i })).toBeInTheDocument();
    // Menu Pemantauan sudah dihapus -- pastikan tidak muncul lagi.
    expect(screen.queryByRole("button", { name: /pemantauan/i })).not.toBeInTheDocument();
    expect(await screen.findByTestId("leaflet-map")).toBeInTheDocument();
    // Nilainya kini cukup "online"; kata "database" sudah jadi labelnya.
    expect(await screen.findByText(/^online$/i)).toBeInTheDocument();
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

  it("upgrades hotspot payload to full view when switching to matrix", async () => {
    render(<App />);
    await loginThroughUI();

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

  it("keeps the initial loading overlay hidden during background refresh", async () => {
    const { container } = render(<App />);
    await loginThroughUI();

    await act(async () => {
      await vi.dynamicImportSettled();
    });

    expect(screen.getByTestId("leaflet-map")).toBeInTheDocument();
    expect(container.querySelector(".loading-screen-overlay")).not.toBeInTheDocument();

    // Fake timers baru diaktifkan di sini, bukan dari awal test -- login
    // (loginThroughUI) memakai waitForElementToBeRemoved yang butuh timer
    // asli untuk polling; diaktifkan lebih awal bikin login gantung selamanya
    // sampai test timeout.
    vi.useFakeTimers();
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

  it("separates manual sync from prewarm history actions", async () => {
    render(<App />);
    await loginThroughUI();

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

  it("menyembunyikan kontrol admin tetapi mempertahankan Pengaturan untuk role user", async () => {
    render(<App />);
    await loginThroughUI("regular-user");

    expect(screen.getByRole("button", { name: /pengaturan/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sync hotspot/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /prewarm/i })).not.toBeInTheDocument();
  });

  it("memulihkan sesi tersimpan setelah aplikasi di-reset", async () => {
    const firstRender = render(<App />);
    await loginThroughUI("admin");
    firstRender.unmount();

    render(<App />);

    expect(await screen.findByRole("button", { name: /pengaturan/i })).toBeInTheDocument();
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input) === "/api/auth/session")).toBe(true);
  });

  it("menampilkan menu Pengaturan + tombol Sync/Prewarm untuk role admin", async () => {
    render(<App />);
    await loginThroughUI("admin");

    expect(screen.getByRole("button", { name: /pengaturan/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sync hotspot/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /prewarm/i })).toBeInTheDocument();
  });
});
