import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FilterPanel } from "../components/FilterPanel";

describe("FilterPanel", () => {
  it("calls layer toggle handler", () => {
    const onToggle = vi.fn();
    const onTimePresetChange = vi.fn();

    render(
      <FilterPanel
        layers={[
          {
            id: "sample_area",
            name: "sample_area",
            label: "LPHD Nyuai Peningun",
            active: true,
            color: "#1d4ed8",
            bounds: {
              min_lat: -7,
              min_lon: 107,
              max_lat: -6,
              max_lon: 108
            },
            geojson: {
              type: "FeatureCollection",
              features: []
            },
            feature_count: 1
          }
        ]}
        selectedSatellites={["MODIS"]}
        timePreset="24h"
        onToggleLayer={onToggle}
        onToggleSatellite={() => {}}
        onTimePresetChange={onTimePresetChange}
        onDateChange={() => {}}
        startDate="2026-01-01"
        endDate="2026-05-26"
        hotspotCount={5}
        selectedProvince=""
        onProvinceChange={() => {}}
        provinceOptions={[]}
        showWind={false}
        onToggleWind={() => {}}
      />,
    );

    expect(screen.getByRole("button", { name: /24 jam/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /custom/i }));
    expect(onTimePresetChange).toHaveBeenCalledWith("custom");
    fireEvent.click(screen.getByRole("button", { name: /tampilkan satelit/i }));
    expect(screen.getByLabelText("Dari")).toBeDisabled();
    expect(screen.getByLabelText("Ke")).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/nyuai peningun/i));
    expect(onToggle).toHaveBeenCalledWith("sample_area");
  });
});
