import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EarlyWarningView } from "../components/EarlyWarningView";
import * as apiModule from "../lib/api";

const mockSummary = {
  burned_area_stats: {
    total_polygons: 10,
    active_today: 2,
    active_yesterday: 1,
    active_7d: 3,
    padam_total: 4,
    total_burned_ha: 150.0,
    strict_reburn_kps_today: 1,
    strict_reburn_hotspots_today: 1,
    expanding_hotspots_today: 1,
    clear_today: 8
  },
  early_warning_stats: {
    total_kps: 20,
    active_today: 1,
    active_yesterday: 0,
    active_7d: 2,
    truly_inactive: 17,
    today_hotspots: 1,
    month_hotspots: 5,
    year_hotspots: 10
  },
  wilker_bps: null,
  updated_at: "2026-09-06T10:00:00"
};

const mockItemsToday = [
  {
    id: 1,
    lembaga: "LPHD Bintang Jaya",
    nama_desa: "Desa Bintang",
    nama_kec: "Kec Bintang",
    nama_kab: "Kabupaten Kapuas",
    nama_prov: "Kalimantan Tengah",
    wilker_bps: "BPSKL Kalimantan",
    skema: "HD",
    luas_sk: 500,
    no_sk: "SK.1",
    total_burned_ha: 25.5,
    burn_frequency: 1,
    latest_burned_month: "Agustus 2026",
    hotspots_today: 2,
    hotspots_today_strict_reburn: 1,
    hotspots_today_expanding: 1,
    min_distance_km: 0.4,
    max_distance_km: 0.8,
    avg_distance_km: 0.6,
    fire_direction: "Utara (U)",
    fire_azimuth_deg: 0,
    propagation_zone: "Strict Re-burn",
    zone_code: "strict",
    hotspots_yesterday: 0,
    hotspots_7d: 3,
    hotspots_7d_strict_reburn: 1,
    hotspots_7d_expanding: 2,
    hotspots_month: 4,
    hotspots_year: 6,
    frp_max_7d: 18.2,
    detected_days_7d: 2,
    satellites_7d: 2,
    latest_hotspot_at: "2026-09-06T08:00:00Z",
    ftri_score: 82.5,
    status_label: "Strict Re-burn"
  },
  {
    id: 2,
    lembaga: "KT Hutan Asri",
    nama_desa: "Desa Asri",
    nama_kec: "Kec Asri",
    nama_kab: "Kabupaten Ketapang",
    nama_prov: "Kalimantan Barat",
    wilker_bps: "BPSKL Kalimantan",
    skema: "HKm",
    luas_sk: 300,
    no_sk: "SK.2",
    total_burned_ha: 0,
    burn_frequency: 0,
    latest_burned_month: null,
    hotspots_today: 1,
    hotspots_today_strict_reburn: 0,
    hotspots_today_expanding: 1,
    min_distance_km: null,
    max_distance_km: null,
    avg_distance_km: null,
    fire_direction: null,
    fire_azimuth_deg: null,
    propagation_zone: "Titik Baru 2026",
    zone_code: "new_2026",
    hotspots_yesterday: 0,
    hotspots_7d: 1,
    hotspots_7d_strict_reburn: 0,
    hotspots_7d_expanding: 1,
    hotspots_month: 1,
    hotspots_year: 2,
    frp_max_7d: 12.0,
    detected_days_7d: 1,
    satellites_7d: 1,
    latest_hotspot_at: "2026-09-06T07:30:00Z",
    ftri_score: 65.0,
    status_label: "P1: Titik Baru Hari Ini"
  }
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    if (url.startsWith("/api/early-warning/summary")) {
      return jsonResponse(mockSummary);
    }
    if (url.startsWith("/api/scheduler/metrics")) {
      return jsonResponse({ last_successful_sync_at: "2026-09-06T08:00:00Z", last_sync_hotspot_count: 10 });
    }
    if (url.startsWith("/api/early-warning/list")) {
      return jsonResponse({ items: mockItemsToday });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("EarlyWarningView", () => {
  it("renders table with items and displays correct download count", async () => {
    render(<EarlyWarningView />);

    expect(await screen.findByText("LPHD Bintang Jaya")).toBeInTheDocument();
    expect(screen.getByText("KT Hutan Asri")).toBeInTheDocument();

    const downloadBtn = screen.getByRole("button", { name: /Download Excel \(2 KPS\)/i });
    expect(downloadBtn).toBeInTheDocument();
  });

  it("filters items via search and updates the download button count", async () => {
    render(<EarlyWarningView />);

    await screen.findByText("LPHD Bintang Jaya");

    const searchInput = screen.getByPlaceholderText(/Cari KPS, desa, kecamatan, kabupaten/i);
    fireEvent.change(searchInput, { target: { value: "Bintang" } });

    expect(screen.getByText("LPHD Bintang Jaya")).toBeInTheDocument();
    expect(screen.queryByText("KT Hutan Asri")).not.toBeInTheDocument();

    expect(screen.getByRole("button", { name: /Download Excel \(1 KPS\)/i })).toBeInTheDocument();
  });

  it("calls downloadWithAuth with filtered items payload when download button is clicked", async () => {
    const downloadSpy = vi.spyOn(apiModule, "downloadWithAuth").mockResolvedValue();

    render(<EarlyWarningView />);
    await screen.findByText("LPHD Bintang Jaya");

    // Filter to 1 item
    const searchInput = screen.getByPlaceholderText(/Cari KPS, desa, kecamatan, kabupaten/i);
    fireEvent.change(searchInput, { target: { value: "Bintang" } });

    const downloadBtn = screen.getByRole("button", { name: /Download Excel \(1 KPS\)/i });
    fireEvent.click(downloadBtn);

    await waitFor(() => {
      expect(downloadSpy).toHaveBeenCalledTimes(1);
    });

    const [url, filename, init] = downloadSpy.mock.calls[0];
    expect(url).toBe("/api/early-warning/export.xlsx");
    expect(filename).toContain("rekap-peringatan-dini-ada-hotspot-hari-ini");
    expect(init?.method).toBe("POST");

    const payload = JSON.parse(init?.body as string);
    expect(payload.items).toHaveLength(1);
    expect(payload.items[0].lembaga).toBe("LPHD Bintang Jaya");
    expect(payload.subtitle).toContain('Pencarian: "Bintang"');
  });
});
