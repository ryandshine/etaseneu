import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SidebarNav } from "../components/SidebarNav";

// Prop `collapsed` yang sampai ke SidebarNav SUDAH viewport-aware (App.tsx
// yang menggabungkannya dengan useIsDesktopWide), jadi di sini cukup dikirim
// langsung -- tidak perlu mock matchMedia.
function baseProps(overrides: Record<string, unknown> = {}) {
  return {
    activeView: "map" as const,
    onChangeView: vi.fn(),
    onManualSync: vi.fn(),
    onPrewarmHistory: vi.fn(),
    onLogout: vi.fn(),
    syncLabel: "online",
    syncStatusLabel: "OK",
    lastSyncLabel: "04 Sept 18:00 WIB",
    manualSyncBusy: false,
    prewarmBusy: false,
    healthStatus: "normal" as const,
    healthLabel: "Normal",
    schedulerStatusLabel: "Aktif",
    schedulerStatusColor: "#10b981",
    schedulerStatusBg: "rgba(16,185,129,0.15)",
    syncTodayRatio: "6 / 8",
    syncInterval: "3 Jam",
    nextScheduledSyncLabel: "05-09-2026 00:00 WIB",
    latestHotspotTimeLabel: "04-09-2026 13:14 WIB",
    dataAgeLabel: "7 jam",
    hasLatestHotspot: true,
    isAdmin: true,
    ...overrides
  };
}

describe("SidebarNav", () => {
  it("expanded: shows nav labels and the full sync status block", () => {
    render(<SidebarNav {...baseProps()} onToggleCollapsed={vi.fn()} />);

    expect(screen.getByText("Matriks Data")).toBeInTheDocument();
    expect(screen.getByText("Last Sync")).toBeInTheDocument();
    expect(screen.getByText("04 Sept 18:00 WIB")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /perkecil menu samping/i })).toBeInTheDocument();
  });

  it("collapsed: hides label text but keeps every menu reachable by accessible name", () => {
    render(<SidebarNav {...baseProps()} collapsed onToggleCollapsed={vi.fn()} />);

    // Teks visual hilang...
    expect(screen.queryByText("Matriks Data")).not.toBeInTheDocument();
    expect(screen.queryByText("Tutupan Lahan")).not.toBeInTheDocument();
    // ...tapi tombolnya tetap punya nama aksesibel (aria-label) & bisa diklik.
    expect(screen.getByRole("button", { name: "Matriks Data" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tutupan Lahan" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keluar" })).toBeInTheDocument();
    // Grid status detail diringkas jadi titik + aksi admin saja.
    expect(screen.queryByText("Last Sync")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sync hotspot manual/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /prewarm histori tahunan/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /perluas menu samping/i })).toBeInTheDocument();
  });

  it("collapsed: navigation still fires onChangeView", () => {
    const onChangeView = vi.fn();
    render(<SidebarNav {...baseProps({ onChangeView })} collapsed onToggleCollapsed={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Kompleks Kebakaran" }));
    expect(onChangeView).toHaveBeenCalledWith("kompleks");
  });

  it("collapsed: filter slot becomes an icon button that opens a flyout", () => {
    render(
      <SidebarNav
        {...baseProps()}
        collapsed
        onToggleCollapsed={vi.fn()}
        filterSlot={<div>Isi filter peta</div>}
      />
    );

    // Filter tidak langsung tampil -- harus dibuka lewat tombol ikon dulu.
    expect(screen.queryByText("Isi filter peta")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /filter peta/i }));
    expect(screen.getByText("Isi filter peta")).toBeInTheDocument();

    // Klik di luar (backdrop) menutup lagi.
    fireEvent.click(document.querySelector(".side-filter-backdrop") as HTMLElement);
    expect(screen.queryByText("Isi filter peta")).not.toBeInTheDocument();
  });

  it("expanded: filter slot is rendered inline, without a toggle button", () => {
    render(<SidebarNav {...baseProps()} filterSlot={<div>Isi filter peta</div>} />);

    expect(screen.getByText("Isi filter peta")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /filter peta/i })).not.toBeInTheDocument();
  });

  it("toggle button calls onToggleCollapsed", () => {
    const onToggleCollapsed = vi.fn();
    render(<SidebarNav {...baseProps()} onToggleCollapsed={onToggleCollapsed} />);

    fireEvent.click(screen.getByRole("button", { name: /perkecil menu samping/i }));
    expect(onToggleCollapsed).toHaveBeenCalledTimes(1);
  });
});
