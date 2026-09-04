import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HotspotPopupContent } from "../components/HotspotPopupContent";

describe("HotspotPopupContent", () => {
  const mockHotspot = {
    latitude: -0.12345,
    longitude: 101.54321,
    source: "VIIRS",
    satellite: "NOAA-20",
    agencyName: "LPHD Nyuai Peningun",
    provinceName: "KALIMANTAN BARAT",
    brightness: 330.5,
    frp: 45.2,
    detectedAt: "2026-09-01T12:00:00Z",
    fungsiKawasan: "Hutan Lindung",
    namaKawasan: "Bukit Raya"
  };

  it("renders popup content with hotspot details and direct KPS detail action button", () => {
    const onOpenKpsDetail = vi.fn();
    render(<HotspotPopupContent hotspot={mockHotspot} onOpenKpsDetail={onOpenKpsDetail} />);

    expect(screen.getByText("VIIRS")).toBeInTheDocument();
    expect(screen.getAllByText("NOAA-20").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("KALIMANTAN BARAT")).toBeInTheDocument();
    expect(screen.getByText("VIIRS")).toBeInTheDocument();
    expect(screen.getAllByText("NOAA-20").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("KALIMANTAN BARAT")).toBeInTheDocument();
    expect(screen.getByText("Detail KPS")).toBeInTheDocument();

    const detailBtn = screen.getByRole("button", { name: /detail kps/i });
    fireEvent.click(detailBtn);

    expect(onOpenKpsDetail).toHaveBeenCalledTimes(1);
    expect(onOpenKpsDetail).toHaveBeenCalledWith("LPHD Nyuai Peningun");
  });

  it("toggles weather accordion on user click", () => {
    render(<HotspotPopupContent hotspot={mockHotspot} />);

    const weatherToggle = screen.getByRole("button", { name: /cuaca & kualitas udara/i });
    expect(weatherToggle).toBeInTheDocument();

    expect(screen.queryByText(/memuat data cuaca/i)).not.toBeInTheDocument();

    fireEvent.click(weatherToggle);

    expect(screen.getByText(/memuat data cuaca/i)).toBeInTheDocument();
  });

  it("also opens KPS detail when clicking the agency name link", () => {
    const onOpenKpsDetail = vi.fn();
    render(<HotspotPopupContent hotspot={mockHotspot} onOpenKpsDetail={onOpenKpsDetail} />);

    const agencyLink = screen.getByTitle("Buka detail KPS: LPHD Nyuai Peningun");
    fireEvent.click(agencyLink);

    expect(onOpenKpsDetail).toHaveBeenCalledTimes(1);
    expect(onOpenKpsDetail).toHaveBeenCalledWith("LPHD Nyuai Peningun");
  });

  it("does not render KPS detail button if agencyName is not available", () => {
    const onOpenKpsDetail = vi.fn();
    render(
      <HotspotPopupContent
        hotspot={{ ...mockHotspot, agencyName: "" }}
        onOpenKpsDetail={onOpenKpsDetail}
      />
    );

    expect(screen.queryByText("Detail KPS")).not.toBeInTheDocument();
  });

  it("shows a human label for the VIIRS letter confidence code", () => {
    render(<HotspotPopupContent hotspot={{ ...mockHotspot, confidence: "h" }} />);
    expect(screen.getByText("Keyakinan")).toBeInTheDocument();
    expect(screen.getByText("Tinggi")).toBeInTheDocument();
  });

  it("bands the MODIS numeric confidence", () => {
    render(<HotspotPopupContent hotspot={{ ...mockHotspot, confidence: "72" }} />);
    expect(screen.getByText("72% (sedang)")).toBeInTheDocument();
  });

  it("falls back gracefully when confidence is missing", () => {
    render(<HotspotPopupContent hotspot={mockHotspot} />);
    const dt = screen.getByText("Keyakinan");
    expect(dt.parentElement).toHaveTextContent("Tidak tersedia");
  });

  it("treats the literal string 'Unknown' as unavailable", () => {
    render(<HotspotPopupContent hotspot={{ ...mockHotspot, confidence: "Unknown" }} />);
    const dt = screen.getByText("Keyakinan");
    expect(dt.parentElement).toHaveTextContent("Tidak tersedia");
  });
});
