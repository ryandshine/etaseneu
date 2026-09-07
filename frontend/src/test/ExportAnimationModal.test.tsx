import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExportAnimationModal } from "../components/ExportAnimationModal";

afterEach(cleanup);

describe("ExportAnimationModal", () => {
  it("does not render when isOpen is false", () => {
    render(
      <ExportAnimationModal
        isOpen={false}
        onClose={vi.fn()}
        totalFrames={10}
        activeHotspotCount={5}
        kpsName="KPS Rawa Lestari"
        onStartExport={vi.fn()}
      />
    );
    expect(screen.queryByText(/Unduh Animasi Sebaran Hotspot/i)).not.toBeInTheDocument();
  });

  it("renders correctly with format options, date range label, and speed buttons when open", () => {
    render(
      <ExportAnimationModal
        isOpen={true}
        onClose={vi.fn()}
        totalFrames={12}
        activeHotspotCount={8}
        kpsName="KPS Rawa Lestari"
        dateRangeLabel="01 Sep 2026 s/d 07 Sep 2026 (WIB)"
        onStartExport={vi.fn()}
      />
    );

    expect(screen.getByText("Unduh Animasi Sebaran Hotspot")).toBeInTheDocument();
    expect(screen.getByText("KPS Rawa Lestari")).toBeInTheDocument();
    expect(screen.getByText("01 Sep 2026 s/d 07 Sep 2026 (WIB)")).toBeInTheDocument();
    expect(screen.getByText(/12 frame • 8 titik terpantau/i)).toBeInTheDocument();
    expect(screen.getByText(/GIF Animasi \(\.gif\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Video WebM \(\.webm\)/i)).toBeInTheDocument();
  });

  it("allows switching format and speed, then triggering onStartExport", async () => {
    const onStartExport = vi.fn().mockResolvedValue(undefined);
    render(
      <ExportAnimationModal
        isOpen={true}
        onClose={vi.fn()}
        totalFrames={15}
        activeHotspotCount={7}
        kpsName="KPS Danau Indah"
        onStartExport={onStartExport}
      />
    );

    // Switch format to WebM
    const webmCard = screen.getByText(/Video WebM \(\.webm\)/i);
    fireEvent.click(webmCard);

    // Switch speed to Perlahan (0.50s)
    const slowBtn = screen.getByRole("button", { name: /Perlahan \(0\.50s\)/i });
    fireEvent.click(slowBtn);

    // Click start export
    const submitBtn = screen.getByRole("button", { name: /Mulai Rekam & Unduh/i });
    fireEvent.click(submitBtn);

    expect(onStartExport).toHaveBeenCalledWith(
      "webm",
      500,
      expect.any(Function),
      expect.any(AbortSignal)
    );
  });
});
