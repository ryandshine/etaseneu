import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MapSheet } from "../components/MapSheet";
import { useSmokeLayers } from "../hooks/useSmokeLayers";

function Harness() {
  const smoke = useSmokeLayers();
  return (
    <MapSheet
      hotspots={[]}
      mapStyle="dark"
      onMapStyleChange={vi.fn()}
      showBurnedArea={false}
      onToggleBurnedArea={vi.fn()}
      burnedArea={{ data: null, loading: false }}
      showS2Burned={false}
      onToggleS2Burned={vi.fn()}
      s2Burned={{ data: null, loading: false }}
      showKawasan={false}
      onToggleKawasan={vi.fn()}
      smoke={smoke}
    />
  );
}

describe("MapSheet (mobile)", () => {
  it("lists the smoke layers, expanded and OFF by default", () => {
    render(<Harness />);
    // Sheet mulai "peek" (isi tersembunyi); pengguna menariknya naik dulu.
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByRole("button", { name: /citra satelit asap/i })).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: /prakiraan pm2\.5/i }));
    expect(screen.getByRole("button", { name: /prakiraan pm2\.5/i })).toHaveAttribute("aria-pressed", "true");
  });
});
