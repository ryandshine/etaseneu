import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SmokeControl } from "../components/SmokeControl";
import { useSmokeLayers } from "../hooks/useSmokeLayers";

afterEach(cleanup);

function Harness({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const smoke = useSmokeLayers();
  return <SmokeControl smoke={smoke} defaultOpen={defaultOpen} />;
}

describe("useSmokeLayers", () => {
  it("starts with every smoke layer OFF (opt-in, like the other heavy overlays)", () => {
    const { result } = renderHook(() => useSmokeLayers());
    expect(result.current.imagery).toBe(false);
    expect(result.current.pm25).toBe(false);
    expect(result.current.imageryDay).toBe("today");
    expect(result.current.pm25Offset).toBe(0);
  });

  it("toggles layers and remembers the chosen day / forecast hour", () => {
    const { result } = renderHook(() => useSmokeLayers());
    act(() => result.current.toggleImagery());
    act(() => result.current.setImageryDay("yesterday"));
    act(() => result.current.togglePm25());
    act(() => result.current.setPm25Offset(24));
    expect(result.current.imagery).toBe(true);
    expect(result.current.imageryDay).toBe("yesterday");
    expect(result.current.pm25).toBe(true);
    expect(result.current.pm25Offset).toBe(24);
  });
});

describe("SmokeControl", () => {
  it("is collapsed by default: only the header button is visible", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: /lapisan asap/i })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /citra satelit asap/i })).not.toBeInTheDocument();
  });

  it("opens to two OFF toggles", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: /lapisan asap/i }));
    expect(screen.getByRole("button", { name: /citra satelit asap/i })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: /prakiraan pm2\.5/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("can start expanded for the mobile sheet / left stack", () => {
    render(<Harness defaultOpen />);
    expect(screen.getByRole("button", { name: /citra satelit asap/i })).toBeInTheDocument();
  });

  it("shows the day switch only while the imagery layer is on", () => {
    render(<Harness defaultOpen />);
    expect(screen.queryByRole("button", { name: /kemarin/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /citra satelit asap/i }));
    const yesterday = screen.getByRole("button", { name: /kemarin/i });
    const today = screen.getByRole("button", { name: /hari ini/i });
    expect(today).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(yesterday);
    expect(yesterday).toHaveAttribute("aria-pressed", "true");
    expect(today).toHaveAttribute("aria-pressed", "false");
  });

  it("shows the forecast hour chips and the BMKG legend only while PM2.5 is on", () => {
    render(<Harness defaultOpen />);
    expect(screen.queryByText(/berbahaya/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /\+24 jam/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /prakiraan pm2\.5/i }));

    for (const label of ["Baik", "Sedang", "Tidak sehat", "Sangat tidak sehat", "Berbahaya"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: /sekarang/i })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /\+24 jam/i }));
    expect(screen.getByRole("button", { name: /\+24 jam/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /sekarang/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("is honest about resolution: says the forecast is a coarse regional model", () => {
    render(<Harness defaultOpen />);
    fireEvent.click(screen.getByRole("button", { name: /prakiraan pm2\.5/i }));
    expect(screen.getByText(/indikatif/i)).toBeInTheDocument();
  });

  it("reports loading, ready (with valid time) and error states of the forecast", () => {
    function StatusHarness() {
      const smoke = useSmokeLayers();
      return (
        <>
          <button onClick={() => smoke.setPm25Info({ status: "ready", validTime: "2026-09-20T12:00" })}>ready</button>
          <button onClick={() => smoke.setPm25Info({ status: "error" })}>fail</button>
          <SmokeControl smoke={smoke} defaultOpen />
        </>
      );
    }
    render(<StatusHarness />);
    fireEvent.click(screen.getByRole("button", { name: /prakiraan pm2\.5/i }));
    expect(screen.getByText(/memuat/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText("ready"));
    expect(screen.getByText(/Min, 20 Sep 12\.00 WIB/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("fail"));
    expect(screen.getByText(/gagal memuat/i)).toBeInTheDocument();
  });
});
