import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HotspotMatrix } from "../components/HotspotMatrix";

// HotspotMatrix sekarang fetch sendiri /api/burned-area/frequency saat mount
// (Frekuensi Kebakaran, data KLHK -- terpisah dari `hotspots` yang datang
// lewat props). Tanpa mock ini, ketiga test di bawah akan gagal begitu
// komponennya coba fetch di jsdom (tidak ada network sungguhan).
const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockImplementation(async (input) => {
    if (String(input).includes("/api/burned-area/frequency")) {
      return new Response(JSON.stringify({ rows: [] }), { status: 200 });
    }
    throw new Error(`Unexpected fetch: ${String(input)}`);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const hotspot = {
  id: "hotspot-1",
  detectedAt: "2026-05-28T00:10:59Z",
  latitude: -1.234,
  longitude: 113.456,
  layerName: "LPHD Demo",
  agencyName: "LPHD Demo",
  provinceName: "Jawa Tengah",
  polygonMetadata: {
    LEMBAGA: "LPHD Demo",
    NAMA_PROV: "Jawa Tengah",
    NAMA_KAB: "Blora",
    NAMA_KEC: "Randublatung",
    NAMA_DESA: "Ngudi Jati",
    SKEMA: "PKK",
    Status: "PS 33",
    WILKER_BPS: "Balai PS Yogyakarta",
    PS_ID: "331623",
    KODE_PROV: "33",
    KODE_KAB: "3316",
    LuasFinal: "1960.23",
    Jml_KK: "13"
  },
  source: "NASA FIRMS",
  satellite: "MODIS",
  brightness: 321.45,
  frp: 12.4,
  confidence: "high",
  daynight: "D"
};

describe("HotspotMatrix", () => {
  it("renders geojson registry status and grouped query stack", async () => {
    render(
      <HotspotMatrix
        hotspots={[hotspot]}
        geojsonStatus={{
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
              checksum: "abc",
              mtime: "2026-05-28T00:10:59+07:00",
              last_synced_at: "2026-05-28T00:10:59+07:00",
              last_sync_status: "synced",
              last_sync_message: "ok",
              feature_count: 7138,
              is_active: true
            }
          ]
        }}
        onExport={() => undefined}
        isExporting={false}
        onExportPdf={() => undefined}
        isExportingPdf={false}
        onDateChange={() => undefined}
        startDate="2026-05-27"
        endDate="2026-05-28"
        timeRange={{
          startAt: new Date("2026-05-27T00:00:00Z"),
          endAt: new Date("2026-05-28T00:00:00Z"),
          label: "Hari ini"
        }}
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
      />
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByText("Matriks & Rekapitulasi Data")).toBeInTheDocument();
    // Rentang tanggal kini dua input berlabel "Dari"/"Ke", bukan satu label
    // tunggal "Rentang Tanggal".
    expect(screen.getByText("Filter Waktu")).toBeInTheDocument();
    expect(screen.getByText("Dari")).toBeInTheDocument();
    expect(screen.getByText("Ke")).toBeInTheDocument();
    expect(screen.getByText("Wilker Filter")).toBeInTheDocument();
    expect(screen.getByText("Provinsi Filter")).toBeInTheDocument();
    expect(screen.getByText("Confidence")).toBeInTheDocument();

    expect(screen.getByText("Baris Hotspot")).toBeInTheDocument();
    expect(screen.getByText("KPS")).toBeInTheDocument();
  });

  it("opens the dedicated KPS detail page instead of an inline drawer when a row is clicked", async () => {
    const onOpenKpsDetail = vi.fn();
    render(
      <HotspotMatrix
        hotspots={[hotspot]}
        geojsonStatus={null}
        onExport={() => undefined}
        isExporting={false}
        onExportPdf={() => undefined}
        isExportingPdf={false}
        onDateChange={() => undefined}
        startDate="2026-05-27"
        endDate="2026-05-28"
        timeRange={{
          startAt: new Date("2026-05-27T00:00:00Z"),
          endAt: new Date("2026-05-28T00:00:00Z"),
          label: "Hari ini"
        }}
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
        onOpenKpsDetail={onOpenKpsDetail}
      />
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fireEvent.click(screen.getByText("28-05-2026 07:10 WIB"));

    expect(onOpenKpsDetail).toHaveBeenCalledWith("LPHD Demo");
    // Panel geser lama tidak boleh ada lagi -- kontennya sudah pindah ke
    // halaman KpsDetailView tersendiri.
    expect(screen.queryByText("Laporan deteksi spesifik")).not.toBeInTheDocument();
  });

  it("renders the skema x provinsi crosstab and filters everything when a skema is picked", async () => {
    const onExport = vi.fn();
    const otherSkema = {
      ...hotspot,
      id: "hotspot-2",
      layerName: "LPHD Lain",
      agencyName: "LPHD Lain",
      provinceName: "Riau",
      polygonMetadata: { ...hotspot.polygonMetadata, LEMBAGA: "LPHD Lain", SKEMA: "PPHD" }
    };

    render(
      <HotspotMatrix
        hotspots={[hotspot, otherSkema]}
        geojsonStatus={null}
        onExport={onExport}
        isExporting={false}
        onExportPdf={() => undefined}
        isExportingPdf={false}
        onDateChange={() => undefined}
        startDate="2026-05-27"
        endDate="2026-05-28"
        timeRange={{
          startAt: new Date("2026-05-27T00:00:00Z"),
          endAt: new Date("2026-05-28T00:00:00Z"),
          label: "Hari ini"
        }}
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
      />
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByText("Hotspot per Skema per Provinsi")).toBeInTheDocument();
    expect(screen.getByText("Skema Filter")).toBeInTheDocument();
    expect(screen.getByText("2 skema · 2 provinsi · 2 titik")).toBeInTheDocument();

    // Klik judul kolom skema menyaring seluruh matriks, bukan cuma tabelnya.
    fireEvent.click(screen.getByTitle("Saring skema PKK"));

    expect(screen.getByText("SKEMA: PKK")).toBeInTheDocument();
    expect(screen.getByText("1 skema · 1 provinsi · 1 titik")).toBeInTheDocument();

    // Filter yang aktif ikut terbawa ke ekspor supaya isi file sama dengan
    // yang terlihat di layar. Tombol XLSX/PDF/GeoJSON kini di dalam dropdown
    // "Ekspor" (2026-09-05) -- buka dulu sebelum mengklik pilihannya.
    fireEvent.click(screen.getByRole("button", { name: /^Ekspor$/ }));
    fireEvent.click(screen.getByText("Ekspor XLSX"));
    expect(onExport).toHaveBeenCalledWith(expect.objectContaining({ skema: "PKK" }));
  });

  it("previews ten provinces and expands the rest on demand", async () => {
    const manyHotspots = Array.from({ length: 12 }, (_, index) => ({
      ...hotspot,
      id: `hotspot-${index + 1}`,
      provinceName: `Provinsi ${String(index + 1).padStart(2, "0")}`,
      polygonMetadata: {
        ...hotspot.polygonMetadata,
        NAMA_PROV: `Provinsi ${String(index + 1).padStart(2, "0")}`
      }
    }));

    render(
      <HotspotMatrix
        hotspots={manyHotspots}
        geojsonStatus={null}
        onExport={() => undefined}
        isExporting={false}
        onExportPdf={() => undefined}
        isExportingPdf={false}
        onDateChange={() => undefined}
        startDate="2026-05-27"
        endDate="2026-05-28"
        timeRange={{
          startAt: new Date("2026-05-27T00:00:00Z"),
          endAt: new Date("2026-05-28T00:00:00Z"),
          label: "Hari ini"
        }}
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
      />
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(document.querySelectorAll(".skema-matrix tbody tr")).toHaveLength(10);

    fireEvent.click(screen.getByRole("button", { name: "Lihat semua (12)" }));
    expect(document.querySelectorAll(".skema-matrix tbody tr")).toHaveLength(12);
    expect(screen.getByRole("button", { name: "Tampilkan 10 saja" })).toBeInTheDocument();
  });

  it("shows the Frekuensi Kebakaran chip once KLHK data loads, matched by trimmed lembaga name", async () => {
    // Nama lembaga dari data KLHK kadang punya whitespace tersisa -- baris
    // ini harus tetap cocok ke grup "LPHD Demo" dari `hotspots`.
    fetchMock.mockImplementation(async (input) => {
      if (String(input).includes("/api/burned-area/frequency")) {
        return new Response(
          JSON.stringify({
            rows: [
              { lembaga: "LPHD Demo\r\n", periode_terbakar: 4, pertama: "2026-04-01", terakhir: "2026-07-01", total_ha: 120.5 }
            ]
          }),
          { status: 200 }
        );
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    render(
      <HotspotMatrix
        hotspots={[hotspot]}
        geojsonStatus={null}
        onExport={() => undefined}
        isExporting={false}
        onExportPdf={() => undefined}
        isExportingPdf={false}
        onDateChange={() => undefined}
        startDate="2026-05-27"
        endDate="2026-05-28"
        timeRange={{
          startAt: new Date("2026-05-27T00:00:00Z"),
          endAt: new Date("2026-05-28T00:00:00Z"),
          label: "Hari ini"
        }}
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
      />
    );

    expect(await screen.findByText("4×")).toBeInTheDocument();
    expect(screen.getByText("Apr 2026 – Jul 2026")).toBeInTheDocument();
  });

  it("shows a dash in the Frekuensi column for KPS with no KLHK burned-area record", async () => {
    render(
      <HotspotMatrix
        hotspots={[hotspot]}
        geojsonStatus={null}
        onExport={() => undefined}
        isExporting={false}
        onExportPdf={() => undefined}
        isExportingPdf={false}
        onDateChange={() => undefined}
        startDate="2026-05-27"
        endDate="2026-05-28"
        timeRange={{
          startAt: new Date("2026-05-27T00:00:00Z"),
          endAt: new Date("2026-05-28T00:00:00Z"),
          label: "Hari ini"
        }}
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
      />
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const dashes = await screen.findAllByText("-");
    expect(dashes.length).toBeGreaterThan(0);
  });

  const baseProps = {
    hotspots: [hotspot],
    geojsonStatus: null,
    onExport: () => undefined,
    isExporting: false,
    onExportPdf: () => undefined,
    isExportingPdf: false,
    onDateChange: () => undefined,
    startDate: "2026-05-27",
    endDate: "2026-05-28",
    timeRange: {
      startAt: new Date("2026-05-27T00:00:00Z"),
      endAt: new Date("2026-05-28T00:00:00Z"),
      label: "Hari ini"
    },
    dateRangeLabel: "Hari ini",
    timePreset: "24h" as const,
    onTimePresetChange: () => undefined
  };

  it("hides the per-KPS GeoJSON download column for non-admin users", async () => {
    render(<HotspotMatrix {...baseProps} />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.queryByRole("columnheader", { name: "Aksi" })).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Unduh GeoJSON untuk/)).not.toBeInTheDocument();
  });

  it("shows the per-KPS GeoJSON download column for admin users", async () => {
    render(<HotspotMatrix {...baseProps} isAdmin />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(screen.getByRole("columnheader", { name: "Aksi" })).toBeInTheDocument();
    expect(screen.getByTitle(/Unduh GeoJSON untuk/)).toBeInTheDocument();
  });
});
