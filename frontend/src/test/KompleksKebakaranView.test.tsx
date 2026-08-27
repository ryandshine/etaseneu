import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KompleksKebakaranView } from "../components/KompleksKebakaranView";

const flyToMock = vi.fn();

vi.mock("react-leaflet", () => ({
  CircleMarker: ({ children, eventHandlers }: { children?: ReactNode; eventHandlers?: { click?: () => void } }) => (
    <div data-testid="cluster-bubble" onClick={() => eventHandlers?.click?.()}>
      {children}
    </div>
  ),
  Circle: () => <div data-testid="audit-radius" />,
  MapContainer: ({ children }: { children?: ReactNode }) => <div data-testid="leaflet-map">{children}</div>,
  GeoJSON: () => <div data-testid="geojson-layer" />,
  Pane: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Popup: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  ScaleControl: () => <div data-testid="scale-control" />,
  TileLayer: () => <div data-testid="tile-layer" />,
  Tooltip: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  ZoomControl: () => <div data-testid="zoom-control" />,
  useMap: () => ({ flyTo: flyToMock, getZoom: () => 5 })
}));

// Mock CircleMarker/Popup di atas selalu merender children-nya (Leaflet asli
// cuma merender isi Popup saat dibuka) -- jadi nama lembaga muncul dua kali
// (popup peta + baris daftar). Query daftar harus di-scope ke panel daftar
// saja lewat helper ini, bukan screen.findByText global.
function getListPanel(): HTMLElement {
  return screen.getByText("Kompleks Terbesar").closest(".kompleks-list") as HTMLElement;
}

describe("KompleksKebakaranView", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    flyToMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before data arrives", async () => {
    fetchMock.mockImplementation(() => new Promise(() => {}));

    render(<KompleksKebakaranView />);

    expect(screen.getByText("Memuat daftar kompleks...")).toBeInTheDocument();
  });

  it("renders cluster summary and list once data loads", async () => {
    const now = Date.now();
    const recentlyActive = new Date(now - 3 * 60 * 60 * 1000).toISOString();
    const longQuiet = new Date(now - 5 * 24 * 60 * 60 * 1000).toISOString();

    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          count: 2,
          clusters: [
            {
              cluster_id: 1,
              hotspot_count: 500,
              centroid_lat: -1.5,
              centroid_lon: 110.5,
              first_detected_at: "2026-08-01T00:00:00Z",
              last_detected_at: recentlyActive,
              dominant_agency: "LPHD Kalibandung"
            },
            {
              cluster_id: 2,
              hotspot_count: 20,
              centroid_lat: -2.0,
              centroid_lon: 111.0,
              first_detected_at: "2026-08-10T00:00:00Z",
              last_detected_at: longQuiet,
              dominant_agency: "KTH Contoh"
            }
          ],
          stats: {
            total_hotspots_in_range: 600,
            clustered_hotspots: 520,
            unclustered_hotspots: 80
          },
          sensitivity: "sedang",
          range_start: "2026-08-01T00:00:00Z",
          range_end: "2026-08-24T00:00:00Z"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    render(<KompleksKebakaranView />);

    await waitFor(() => expect(getListPanel()).toBeInTheDocument());
    const list = within(getListPanel());

    expect(list.getByText("LPHD Kalibandung")).toBeInTheDocument();
    expect(list.getByText("KTH Contoh")).toBeInTheDocument();

    // Kompleks besar (>=400 titik) + masih aktif <24 jam harus terhitung di
    // strip ringkasan atas.
    const norm = (el: Element | null) => el?.textContent?.replace(/\s+/g, " ").trim();
    await waitFor(() => {
      expect(norm(screen.getByText(/besar \(≥400\)/))).toBe("1 besar (≥400)");
    });
    expect(norm(screen.getByText(/aktif <24 jam/i))).toBe("1 aktif <24 jam");

    // "Aktif" juga muncul di teks penjelasan "Cara baca" di bawah daftar --
    // scope ke baris pertama (LPHD Kalibandung, kompleks terbesar & aktif)
    // supaya yang diuji betul-betul chip baris, bukan teks penjelasan.
    const firstRow = getListPanel().querySelector(".kompleks-row") as HTMLElement;
    expect(list.getByText("Besar")).toBeInTheDocument();
    expect(within(firstRow).getByText("Aktif")).toBeInTheDocument();
  });

  it("offers basemap and zoom controls for the member-point map", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          count: 1,
          clusters: [
            {
              cluster_id: 1,
              hotspot_count: 4,
              centroid_lat: -1.5,
              centroid_lon: 110.5,
              first_detected_at: "2026-08-01T00:00:00Z",
              last_detected_at: "2026-08-02T00:00:00Z",
              dominant_agency: "LPHD Peta",
              dominant_wilker: "Balai PS Peta",
              dominant_province: "Kalimantan Barat",
              affected_wilkers: [{ name: "Balai PS Peta", hotspot_count: 4 }],
              affected_provinces: [{ name: "Kalimantan Barat", hotspot_count: 4 }],
              core_point_count: 1,
              footprint: {
                type: "Polygon",
                coordinates: [[[110.49, -1.51], [110.51, -1.51], [110.51, -1.49], [110.49, -1.51]]]
              },
              affected_agencies: [{ name: "LPHD Peta", hotspot_count: 4 }]
            }
          ],
          points: [
            {
              id: 101,
              latitude: -1.5,
              longitude: 110.5,
              detected_at: "2026-08-01T00:00:00Z",
              agency_name: "LPHD Peta",
              cluster_id: 1,
              is_core: true
            }
          ],
          stats: { total_hotspots_in_range: 4, clustered_hotspots: 4, unclustered_hotspots: 0 },
          sensitivity: "sedang",
          range_start: "2026-08-01T00:00:00Z",
          range_end: "2026-08-24T00:00:00Z"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    render(
      <KompleksKebakaranView
        layers={[
          {
            id: "ps-demo",
            name: "Perhutanan Sosial",
            label: "Perhutanan Sosial",
            active: true,
            color: "#059669",
            bounds: { min_lat: -2, min_lon: 110, max_lat: -1, max_lon: 111 },
            geojson: { type: "FeatureCollection", features: [] },
            feature_count: 0,
            geojson_mode: "preview",
            agencies: ["LPHD Peta"]
          }
        ]}
      />
    );

    await waitFor(() => expect(screen.getByTestId("zoom-control")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Satelit" })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "Satelit" }));
    expect(screen.getByRole("button", { name: "Satelit" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Titik anggota kompleks")).toBeInTheDocument();
    expect(screen.getByText("Polygon lembaga")).toBeInTheDocument();
    expect(within(getListPanel()).getByText("Balai PS Peta")).toBeInTheDocument();
    expect(within(getListPanel()).getByText("Kalimantan Barat")).toBeInTheDocument();
    expect(screen.queryAllByTestId("audit-radius")).toHaveLength(0);
    const auditButton = screen.getByRole("button", { name: "Tampilkan semua ring ε" });
    expect(auditButton).toBeDisabled();
    fireEvent.click(within(getListPanel()).getByText("LPHD Peta"));
    await waitFor(() => expect(auditButton).not.toBeDisabled());
    fireEvent.click(auditButton);
    expect(screen.getAllByTestId("audit-radius")).toHaveLength(1);
  });

  it("copies a WhatsApp-ready report using the active 24-hour and medium filters", async () => {
    const response = (rangeStart: string, rangeEnd: string) =>
      new Response(
        JSON.stringify({
          count: 1,
          clusters: [
            {
              cluster_id: 1,
              hotspot_count: 155,
              centroid_lat: -1.234567,
              centroid_lon: 110.765432,
              first_detected_at: rangeStart,
              last_detected_at: rangeEnd,
              dominant_agency: "LPHD Uji"
            }
          ],
          stats: { total_hotspots_in_range: 155, clustered_hotspots: 155, unclustered_hotspots: 0 },
          sensitivity: "sedang",
          range_start: rangeStart,
          range_end: rangeEnd
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );

    fetchMock
      .mockResolvedValueOnce(response("2026-08-01T00:00:00Z", "2026-08-30T00:00:00Z"))
      .mockResolvedValueOnce(response("2026-08-30T00:00:00Z", "2026-08-31T00:00:00Z"));

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    render(<KompleksKebakaranView />);
    await waitFor(() => expect(getListPanel()).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Rentang"), { target: { value: "1" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "Salin laporan WhatsApp" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const report = writeText.mock.calls[0][0] as string;
    expect(report).toContain("*LAPORAN KOMPLEKS KEBAKARAN*");
    expect(report).toContain("Periode: *24 Jam*");
    expect(report).toContain("Kepekaan: *Sedang*");
    expect(report).toContain("KPS/lembaga teridentifikasi: *1*");
    expect(report).toContain("*LPHD Uji*");
    expect(report).toContain("• Jumlah kompleks: 1");
    expect(report).toContain("• Jumlah titik: *155*");
    expect(report).toContain(
      "📍 Google Maps: https://www.google.com/maps/search/?api=1&query=-1.23457%2C110.76543"
    );
    expect(report).not.toContain("Titik tengah:");
  });

  it("shows an error message when the request fails", async () => {
    fetchMock.mockRejectedValue(new Error("network down"));

    render(<KompleksKebakaranView />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Gagal memuat data kompleks kebakaran. Coba lagi."
    );
  });

  it("shows an empty state when no clusters are found", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          count: 0,
          clusters: [],
          stats: { total_hotspots_in_range: 0, clustered_hotspots: 0, unclustered_hotspots: 0 },
          sensitivity: "sedang",
          range_start: "2026-08-01T00:00:00Z",
          range_end: "2026-08-24T00:00:00Z"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    render(<KompleksKebakaranView />);

    expect(
      await screen.findByText("Tidak ada kompleks terdeteksi pada rentang & kepekaan ini.")
    ).toBeInTheDocument();
  });

  it("clicking a list row selects the corresponding cluster and pans the map", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          count: 1,
          clusters: [
            {
              cluster_id: 7,
              hotspot_count: 50,
              centroid_lat: -3.1,
              centroid_lon: 112.4,
              first_detected_at: "2026-08-01T00:00:00Z",
              last_detected_at: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
              dominant_agency: "LPHD Pantau"
            }
          ],
          stats: { total_hotspots_in_range: 50, clustered_hotspots: 50, unclustered_hotspots: 0 },
          sensitivity: "sedang",
          range_start: "2026-08-01T00:00:00Z",
          range_end: "2026-08-24T00:00:00Z"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    render(<KompleksKebakaranView />);

    await waitFor(() => expect(getListPanel()).toBeInTheDocument());
    const row = within(getListPanel()).getByText("LPHD Pantau");
    fireEvent.click(row.closest('[role="button"]') as HTMLElement);

    await waitFor(() => {
      expect(flyToMock).toHaveBeenCalledWith([-3.1, 112.4], 8, expect.objectContaining({ duration: 0.6 }));
    });
  });

  it("clicking 'Lihat Detail KPS' on a row opens the KPS detail without also selecting the row", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          count: 1,
          clusters: [
            {
              cluster_id: 9,
              hotspot_count: 30,
              centroid_lat: -1.1,
              centroid_lon: 113.2,
              first_detected_at: "2026-08-01T00:00:00Z",
              last_detected_at: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
              dominant_agency: "LD LINGAT"
            }
          ],
          stats: { total_hotspots_in_range: 30, clustered_hotspots: 30, unclustered_hotspots: 0 },
          sensitivity: "sedang",
          range_start: "2026-08-01T00:00:00Z",
          range_end: "2026-08-24T00:00:00Z"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    const onOpenKpsDetail = vi.fn();
    render(<KompleksKebakaranView onOpenKpsDetail={onOpenKpsDetail} />);

    await waitFor(() => expect(getListPanel()).toBeInTheDocument());
    const row = getListPanel().querySelector(".kompleks-row") as HTMLElement;
    const detailBtn = within(row).getByText("Lihat Detail KPS →");

    fireEvent.click(detailBtn);

    expect(onOpenKpsDetail).toHaveBeenCalledWith("LD LINGAT");
    // Klik tombol detail tidak boleh ikut memicu flyTo (seleksi baris) --
    // pengguna sedang berpindah halaman, bukan menjelajah peta.
    expect(flyToMock).not.toHaveBeenCalled();
  });

  it("hides 'Lihat Detail KPS' when a cluster has no dominant agency", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          count: 1,
          clusters: [
            {
              cluster_id: 10,
              hotspot_count: 12,
              centroid_lat: -1.1,
              centroid_lon: 113.2,
              first_detected_at: "2026-08-01T00:00:00Z",
              last_detected_at: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
              dominant_agency: null
            }
          ],
          stats: { total_hotspots_in_range: 12, clustered_hotspots: 12, unclustered_hotspots: 0 },
          sensitivity: "sedang",
          range_start: "2026-08-01T00:00:00Z",
          range_end: "2026-08-24T00:00:00Z"
        }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      )
    );

    render(<KompleksKebakaranView onOpenKpsDetail={vi.fn()} />);

    await waitFor(() => expect(getListPanel()).toBeInTheDocument());
    expect(screen.queryByText("Lihat Detail KPS →")).not.toBeInTheDocument();
  });
});
