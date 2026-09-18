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
      provinces: ["Sumatera Selatan"],
      agencies: ["KTH TELLA SERASAN"],
      wilker_bps: ["Balai PS Palembang"],
      satellites: ["NOAA-20"],
      max_frp: 35.5,
      hotspots: [
        {
          latitude: -3.095974,
          longitude: 104.376196,
          frp: 35.5,
          confidence: "Tinggi",
          agency_name: "KTH TELLA SERASAN",
          province_name: "Sumatera Selatan",
          kabupaten_name: "Muara Enim",
          wilker_bps: "Balai PS Palembang",
          google_maps_url: "https://www.google.com/maps?q=-3.095974,104.376196",
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

    // Verify Detail KPS button and Google Maps link inside notification center
    expect(screen.getByText("Detail KPS")).toBeInTheDocument();
    expect(screen.getByText("Maps")).toBeInTheDocument();
    const mapsLink = screen.getByTitle(/Buka titik koordinat di Google Maps/i);
    expect(mapsLink).toHaveAttribute("href", "https://www.google.com/maps?q=-3.095974,104.376196");
    expect(screen.getByText("35.5 MW")).toBeInTheDocument();
    expect(screen.getAllByText("Balai PS Palembang").length).toBeGreaterThan(0);

    // Click "Lihat di Peta"
    const viewMapButtons = screen.getAllByText("Lihat di Peta");
    expect(viewMapButtons.length).toBeGreaterThan(0);
    fireEvent.click(viewMapButtons[0]);
    expect(onNavigateToMap).toHaveBeenCalledTimes(1);
    expect(onMarkAsRead).toHaveBeenCalledWith("notif-1");
  });

  it("triggers onOpenKpsDetail when Detail KPS button or agency name is clicked", () => {
    const onOpenKpsDetail = vi.fn();
    const onMarkAsRead = vi.fn();

    render(
      <NotificationCenter
        notifications={mockNotifications}
        unreadCount={1}
        readIds={new Set()}
        soundEnabled={true}
        desktopEnabled={false}
        onMarkAsRead={onMarkAsRead}
        onMarkAllAsRead={vi.fn()}
        onToggleSound={vi.fn()}
        onToggleDesktop={vi.fn()}
        onNavigateToMap={vi.fn()}
        onOpenKpsDetail={onOpenKpsDetail}
      />
    );

    fireEvent.click(screen.getByLabelText(/Notifikasi Hotspot/i));

    const detailKpsBtn = screen.getByText("Detail KPS");
    fireEvent.click(detailKpsBtn);

    expect(onOpenKpsDetail).toHaveBeenCalledWith("KTH TELLA SERASAN");
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
  it("renders toast alert, FRP badge, Google Maps link, and handles view map and detail kps", () => {
    const onClose = vi.fn();
    const onViewMap = vi.fn();
    const onOpenKpsDetail = vi.fn();

    render(
      <ToastNotification
        notification={mockNotifications[0]}
        onClose={onClose}
        onViewMap={onViewMap}
        onOpenKpsDetail={onOpenKpsDetail}
      />
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("🔥 3 Titik Panas Baru Terdeteksi")).toBeInTheDocument();
    expect(
      screen.getByText(/Terdeteksi 3 titik panas baru di areal Perhutanan Sosial/i)
    ).toBeInTheDocument();
    expect(screen.getByText("FRP: 35.5 MW")).toBeInTheDocument();
    expect(screen.getByText("Balai PS Palembang")).toBeInTheDocument();

    // Google Maps link in toast
    const gmapsLink = screen.getByText("Google Maps").closest("a");
    expect(gmapsLink).toHaveAttribute("href", "https://www.google.com/maps?q=-3.095974,104.376196");

    // Click Detail KPS
    const detailBtn = screen.getByText("Detail KPS");
    fireEvent.click(detailBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onOpenKpsDetail).toHaveBeenCalledWith("KTH TELLA SERASAN");

    // Click View Map
    const btn = screen.getByText("Lihat di Peta");
    fireEvent.click(btn);
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(onViewMap).toHaveBeenCalledTimes(1);
  });
});
