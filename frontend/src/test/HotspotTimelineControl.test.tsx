import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HotspotTimelineControl } from "../components/HotspotTimelineControl";

afterEach(cleanup);

const buckets = [
  { index: 0, start: 0, end: 1, count: 5 },
  { index: 1, start: 1, end: 2, count: 2 },
  { index: 2, start: 2, end: 3, count: 8 },
];

function setup(overrides: Partial<Parameters<typeof HotspotTimelineControl>[0]> = {}) {
  const props = {
    buckets,
    playheadIndex: 1,
    isPlaying: false,
    speed: 1,
    label: "8 Agu 2026, 01:00 WIB",
    toggle: vi.fn(),
    seek: vi.fn(),
    cycleSpeed: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  render(<HotspotTimelineControl {...props} />);
  return props;
}

describe("HotspotTimelineControl", () => {
  it("renders one histogram bar per bucket", () => {
    setup();
    expect(screen.getAllByTestId("timeline-bar")).toHaveLength(3);
  });

  it("shows the running time label and bucket count", () => {
    setup();
    expect(screen.getByText("8 Agu 2026, 01:00 WIB")).toBeInTheDocument();
    expect(screen.getByText("2 titik")).toBeInTheDocument();
  });

  it("calls toggle when the play/pause button is clicked", () => {
    const p = setup();
    fireEvent.click(screen.getByRole("button", { name: /putar|jeda/i }));
    expect(p.toggle).toHaveBeenCalledTimes(1);
  });

  it("exposes an accessible slider bound to the bucket range", () => {
    setup({ playheadIndex: 2 });
    const slider = screen.getByRole("slider");
    expect(slider).toHaveAttribute("aria-valuemin", "0");
    expect(slider).toHaveAttribute("aria-valuemax", "2");
    expect(slider).toHaveAttribute("aria-valuenow", "2");
  });

  it("calls seek when the slider changes", () => {
    const p = setup();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "2" } });
    expect(p.seek).toHaveBeenCalledWith(2);
  });

  it("shows the speed and cycles it on click", () => {
    const p = setup({ speed: 2 });
    fireEvent.click(screen.getByRole("button", { name: /kecepatan 2 kali/i }));
    expect(p.cycleSpeed).toHaveBeenCalledTimes(1);
  });

  it("calls onClose", () => {
    const p = setup();
    fireEvent.click(screen.getByRole("button", { name: /tutup pemutar/i }));
    expect(p.onClose).toHaveBeenCalledTimes(1);
  });
});
