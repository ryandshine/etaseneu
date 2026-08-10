import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HotspotMatrix } from "../components/HotspotMatrix";

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
  it("renders geojson registry status and grouped query stack", () => {
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
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
      />
    );

    expect(screen.getByText("Matriks Intersep")).toBeInTheDocument();
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

  it("opens the dedicated KPS detail page instead of an inline drawer when a row is clicked", () => {
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
        dateRangeLabel="Hari ini"
        timePreset="24h"
        onTimePresetChange={() => undefined}
        onOpenKpsDetail={onOpenKpsDetail}
      />
    );

    fireEvent.click(screen.getByText("28-05-2026 07:10 WIB"));

    expect(onOpenKpsDetail).toHaveBeenCalledWith("LPHD Demo");
    // Panel geser lama tidak boleh ada lagi -- kontennya sudah pindah ke
    // halaman KpsDetailView tersendiri.
    expect(screen.queryByText("Laporan deteksi spesifik")).not.toBeInTheDocument();
  });
});
