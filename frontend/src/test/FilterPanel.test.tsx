import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterPanel } from "../components/FilterPanel";

describe("FilterPanel", () => {
  it("renders time presets, province and wilker filters", () => {
    const onTimePresetChange = vi.fn();

    render(
      <FilterPanel
        selectedSatellites={["MODIS"]}
        timePreset="24h"
        onToggleSatellite={() => {}}
        onTimePresetChange={onTimePresetChange}
        onDateChange={() => {}}
        startDate="2026-01-01"
        endDate="2026-05-26"
        hotspotCount={5}
        selectedProvince=""
        onProvinceChange={() => {}}
        provinceOptions={[]}
        selectedWilker=""
        onWilkerChange={() => {}}
        wilkerOptions={["Balai PS Banjarbaru"]}
        showWind={false}
        onToggleWind={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /24 jam/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /custom/i }));
    expect(onTimePresetChange).toHaveBeenCalledWith("custom");
    // Filter satelit sekarang langsung terlihat, tanpa toggle "lanjutan".
    expect(screen.getByText("Satelit")).toBeInTheDocument();
    expect(screen.getByLabelText("Dari")).toBeDisabled();
    expect(screen.getByLabelText("Ke")).toBeDisabled();
    // Daftar lapisan spasial tidak lagi dirender FilterPanel (hanya ada satu
    // layer, PS_FEB_26), jadi yang diuji di sini kontrol yang benar-benar tampil.
    expect(screen.getByText("Wilker (Balai PS)")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Balai PS Banjarbaru" })).toBeInTheDocument();
  });
});
