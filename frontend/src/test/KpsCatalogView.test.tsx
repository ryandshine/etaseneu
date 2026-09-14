import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { KpsCatalogView } from "../components/KpsCatalogView";
import * as apiModule from "../lib/api";

const mockMeta = {
  summary: {
    total_kps: 8598,
    total_luas_ha: 6848359.0,
    total_provinsi: 38,
    total_balai: 14,
    kps_hotspot_30d: 83,
    kps_burned: 266,
  },
  filters: {
    skemas: ["PPHD", "PPHKm", "PPHTR"],
    wilkers: ["Balai PS Banjarbaru", "Balai PS Palembang"],
    provinces: ["Kalimantan Barat", "Riau"],
  },
};

const mockCatalogResponse = {
  pagination: {
    page: 1,
    page_size: 25,
    total_records: 1,
    total_pages: 1,
  },
  items: [
    {
      id: 287643,
      layer_key: "psagustus2026",
      feature_key: "abc12345",
      lembaga: "LPHD NYUAI PENINGUN",
      no_sk: "SK.687/MENLHK-PSKL/PKPS/PSL.0/2/2017",
      tgl_sk: "2017-02-23",
      skema: "PPHD",
      nama_prov: "Kalimantan Barat",
      nama_kab: "Kapuas Hulu",
      nama_kec: "Boyan Tanjung",
      nama_desa: "Nanga Jemah",
      wilker_bps: "Balai PS Banjarbaru",
      ps_id: "0",
      luas_final: 4160.0,
      luas_hl: 4160.0,
      luas_hp: 0.0,
      luas_hpt: 0.0,
      luas_hpk: 0.0,
      luas_hk: 0.0,
      jml_kk: 228,
      hotspot_count_30d: 2,
      last_hotspot_at: "2026-08-28T23:39:00Z",
      burned_area_ha: 0.0,
    },
  ],
};

describe("KpsCatalogView", () => {
  beforeEach(() => {
    vi.spyOn(apiModule, "authFetch").mockImplementation((url) => {
      const urlStr = String(url);
      if (urlStr.includes("/api/kps-catalog/meta")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockMeta),
        } as Response);
      }
      if (urlStr.includes("/api/kps-catalog")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockCatalogResponse),
        } as Response);
      }
      return Promise.reject(new Error(`Unhandled URL: ${urlStr}`));
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders header, KPI cards, and catalog table", async () => {
    const onOpenKpsDetail = vi.fn();
    const onOpenMap = vi.fn();

    render(<KpsCatalogView onOpenKpsDetail={onOpenKpsDetail} onOpenMap={onOpenMap} />);

    expect(screen.getByText("Data KPS Nasional")).toBeInTheDocument();

    // Tunggu KPI muncul
    await waitFor(() => {
      expect(screen.getByText("8.598")).toBeInTheDocument();
    });

    // Tunggu item KPS muncul di tabel
    await waitFor(() => {
      expect(screen.getByText("LPHD NYUAI PENINGUN")).toBeInTheDocument();
    });

    // Periksa badge skema dan tombol aksi Profile KPS
    expect(screen.getByText("Profile KPS")).toBeInTheDocument();
    expect(screen.getByText("Peta")).toBeInTheDocument();
  });

  it("triggers onOpenKpsDetail when Profile KPS button is clicked", async () => {
    const onOpenKpsDetail = vi.fn();
    const onOpenMap = vi.fn();

    render(<KpsCatalogView onOpenKpsDetail={onOpenKpsDetail} onOpenMap={onOpenMap} />);

    await waitFor(() => {
      expect(screen.getByText("LPHD NYUAI PENINGUN")).toBeInTheDocument();
    });

    const profileBtn = screen.getByRole("button", { name: /Profile KPS/i });
    fireEvent.click(profileBtn);

    expect(onOpenKpsDetail).toHaveBeenCalledWith("LPHD NYUAI PENINGUN", 287643);
  });

  it("triggers onOpenMap when Peta button is clicked", async () => {
    const onOpenKpsDetail = vi.fn();
    const onOpenMap = vi.fn();

    render(<KpsCatalogView onOpenKpsDetail={onOpenKpsDetail} onOpenMap={onOpenMap} />);

    await waitFor(() => {
      expect(screen.getByText("LPHD NYUAI PENINGUN")).toBeInTheDocument();
    });

    const mapBtn = screen.getByRole("button", { name: /Peta/i });
    fireEvent.click(mapBtn);

    expect(onOpenMap).toHaveBeenCalledWith(mockCatalogResponse.items[0]);
  });
});
