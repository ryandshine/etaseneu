import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotificationCenter } from "../components/NotificationCenter";
import { ToastNotification } from "../components/ToastNotification";
import type { HotspotNotification } from "../types/api";

const mockNotifications: HotspotNotification[] = [
  {
    id: "notif-1",
    type: "hotspot_new",
    title: "🔥 3 Titik Panas Baru Terdeteksi",
    message: "Terdeteksi 3 titik panas baru di areal Perhutanan Sosial (Riau).",
    hotspot_count: 3,
    severity: "danger",
    metadata: {
      provinces: ["Riau"],
      agencies: ["KTH Tella Serasan"],
      satellites: ["NOAA-20"],
      max_frp: 35.5,
      hotspots: [
        {
          latitude: 0.5123,
          longitude: 101.4421,
          frp: 35.5,
          confidence: "Tinggi",
          agency_name: "KTH Tella Serasan",
          province_name: "Riau",
          google_maps_url: "https://www.google.com/maps?q=0.51230,101.44210",
        },
      ],
    },
    created_at: "2026-09-18T10:00:00Z",
  },
  {
    id: "notif-2",
    type: "system_status",
    title: "Sistem Siaga Pemantauan Aktif",
    message: "Sistem memantau secara berkala.",
    hotspot_count: 0,
    severity: "info",
    created_at: "2026-09-18T08:00:00Z",
  },
];

describe("NotificationCenter Component", () => {
  it("renders trigger button with unread badge and opens popover on click", () => {
    const onMarkAsRead = vi.fn();
    const onMarkAllAsRead = vi.fn();
    const onToggleSound = vi.fn();
    const onToggleDesktop = vi.fn();
    const onNavigateToMap = vi.fn();

    render(
      <NotificationCenter
        notifications={mockNotifications}
        unreadCount={1}
        readIds={new Set(["notif-2"])}
        soundEnabled={true}
        desktopEnabled={false}
        onMarkAsRead={onMarkAsRead}
        onMarkAllAsRead={onMarkAllAsRead}
        onToggleSound={onToggleSound}
        onToggleDesktop={onToggleDesktop}
        onNavigateToMap={onNavigateToMap}
      />
    );

    // Trigger button shows unread count badge
    expect(screen.getByLabelText(/Notifikasi Hotspot \(1 belum dibaca\)/i)).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    // Click to open popover
    fireEvent.click(screen.getByLabelText(/Notifikasi Hotspot/i));

    // Popover is displayed
    expect(screen.getByRole("dialog", { name: /Pusat Notifikasi Titik Panas/i })).toBeInTheDocument();
    expect(screen.getByText("🔥 3 Titik Panas Baru Terdeteksi")).toBeInTheDocument();
    expect(screen.getByText("+3 Titik Baru")).toBeInTheDocument();

    // Verify FRP and Google Maps link inside notification center
    expect(screen.getByText("Maps")).toBeInTheDocument();
    const mapsLink = screen.getByTitle(/Buka titik koordinat di Google Maps/i);
    expect(mapsLink).toHaveAttribute("href", "https://www.google.com/maps?q=0.51230,101.44210");
    expect(screen.getByText("35.5 MW")).toBeInTheDocument();

    // Click "Lihat di Peta"
    const viewMapButtons = screen.getAllByText("Lihat di Peta");
    expect(viewMapButtons.length).toBeGreaterThan(0);
    fireEvent.click(viewMapButtons[0]);
    expect(onNavigateToMap).toHaveBeenCalledTimes(1);
    expect(onMarkAsRead).toHaveBeenCalledWith("notif-1");
  });

  it("handles mark all as read and sound toggle buttons", () => {
    const onMarkAllAsRead = vi.fn();
    const onToggleSound = vi.fn();
    const onToggleDesktop = vi.fn();

    render(
      <NotificationCenter
        notifications={mockNotifications}
        unreadCount={2}
        readIds={new Set()}
        soundEnabled={true}
        desktopEnabled={false}
        onMarkAsRead={vi.fn()}
        onMarkAllAsRead={onMarkAllAsRead}
        onToggleSound={onToggleSound}
        onToggleDesktop={onToggleDesktop}
        onNavigateToMap={vi.fn()}
      />
    );

    fireEvent.click(screen.getByLabelText(/Notifikasi Hotspot/i));

    // Mark all as read button
    const markAllBtn = screen.getByTitle(/Tandai semua telah dibaca/i);
    fireEvent.click(markAllBtn);
    expect(onMarkAllAsRead).toHaveBeenCalledTimes(1);

    // Sound toggle
    const soundBtn = screen.getByTitle(/Bunyi alarm aktif/i);
    fireEvent.click(soundBtn);
    expect(onToggleSound).toHaveBeenCalledTimes(1);
  });
});

describe("ToastNotification Component", () => {
  it("renders toast alert, FRP badge, Google Maps link, and handles view map", () => {
    const onClose = vi.fn();
    const onViewMap = vi.fn();

    render(
      <ToastNotification
        notification={mockNotifications[0]}
        onClose={onClose}
        onViewMap={onViewMap}
      />
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("🔥 3 Titik Panas Baru Terdeteksi")).toBeInTheDocument();
    expect(
      screen.getByText(/Terdeteksi 3 titik panas baru di areal Perhutanan Sosial/i)
    ).toBeInTheDocument();
    expect(screen.getByText("FRP: 35.5 MW")).toBeInTheDocument();

    // Google Maps link in toast
    const gmapsLink = screen.getByText("Google Maps").closest("a");
    expect(gmapsLink).toHaveAttribute("href", "https://www.google.com/maps?q=0.51230,101.44210");

    // Click View Map
    const btn = screen.getByText("Lihat di Peta");
    fireEvent.click(btn);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onViewMap).toHaveBeenCalledTimes(1);
  });
});
