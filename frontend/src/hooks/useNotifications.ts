import { useCallback, useEffect, useRef, useState } from "react";
import { createApiClient } from "../lib/api";
import { playHotspotAlertSound } from "../lib/audioAlert";
import {
  getNotificationPermission,
  isBrowserNotificationSupported,
  requestBrowserNotificationPermission,
  showBrowserHotspotNotification,
} from "../lib/browserNotification";
import type { HotspotNotification } from "../types/api";

const api = createApiClient();

const STORAGE_READ_IDS_KEY = "etaseneu.notifications.read_ids.v1";
const STORAGE_SOUND_KEY = "etaseneu.notifications.sound_enabled";
const STORAGE_DESKTOP_KEY = "etaseneu.notifications.desktop_enabled";

function getStoredReadIds(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = localStorage.getItem(STORAGE_READ_IDS_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function saveStoredReadIds(ids: Set<string>): void {
  if (typeof window === "undefined") return;
  try {
    const arr = Array.from(ids).slice(-200);
    localStorage.setItem(STORAGE_READ_IDS_KEY, JSON.stringify(arr));
  } catch {}
}

export function useNotifications(onNavigateToMap?: () => void, ready: boolean = true) {
  const [notifications, setNotifications] = useState<HotspotNotification[]>([]);
  const [readIds, setReadIds] = useState<Set<string>>(getStoredReadIds);
  const [toastNotification, setToastNotification] = useState<HotspotNotification | null>(null);
  const [soundEnabled, setSoundEnabled] = useState<boolean>(() => {
    if (typeof window === "undefined") return true;
    const stored = localStorage.getItem(STORAGE_SOUND_KEY);
    return stored === null ? true : stored === "true";
  });
  const [desktopEnabled, setDesktopEnabled] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(STORAGE_DESKTOP_KEY) === "true";
  });
  const [desktopPermission, setDesktopPermission] = useState<NotificationPermission>(getNotificationPermission);

  const prevIdsRef = useRef<Set<string>>(new Set());
  const isInitialLoadRef = useRef(true);
  const toastTimerRef = useRef<number | null>(null);

  const fetchNotifications = useCallback(async () => {
    try {
      const response = await api.getNotifications(50);
      const items = response.notifications || [];
      setNotifications(items);

      const currentIds = new Set(items.map((n) => n.id));

      if (isInitialLoadRef.current) {
        isInitialLoadRef.current = false;
        prevIdsRef.current = currentIds;
        return;
      }

      // Cari notifikasi baru yang belum ada di polling sebelumnya
      const newItems = items.filter((n) => !prevIdsRef.current.has(n.id));
      prevIdsRef.current = currentIds;

      if (newItems.length > 0) {
        const latestNew = newItems[0];
        // Bunyikan alert suara jika diaktifkan
        if (soundEnabled) {
          playHotspotAlertSound();
        }

        // Tampilkan desktop push notification jika diaktifkan
        if (desktopEnabled && desktopPermission === "granted") {
          showBrowserHotspotNotification(latestNew.title, {
            body: latestNew.message,
            tag: latestNew.id,
            onClick: onNavigateToMap,
          });
        }

        // Tampilkan in-app toast
        setToastNotification(latestNew);
        if (toastTimerRef.current) {
          window.clearTimeout(toastTimerRef.current);
        }
        toastTimerRef.current = window.setTimeout(() => {
          setToastNotification(null);
        }, 9000);
      }
    } catch (err) {
      console.debug("Gagal memuat notifikasi:", err);
    }
  }, [desktopEnabled, desktopPermission, onNavigateToMap, soundEnabled]);

  useEffect(() => {
    if (!ready) {
      isInitialLoadRef.current = true;
      return;
    }

    void fetchNotifications();
    const interval = window.setInterval(() => {
      void fetchNotifications();
    }, 30_000);

    return () => {
      window.clearInterval(interval);
      if (toastTimerRef.current) {
        window.clearTimeout(toastTimerRef.current);
      }
    };
  }, [fetchNotifications, ready]);

  const markAsRead = useCallback((id: string) => {
    setReadIds((prev) => {
      const next = new Set(prev);
      next.add(id);
      saveStoredReadIds(next);
      return next;
    });
  }, []);

  const markAllAsRead = useCallback(() => {
    const allIds = new Set(notifications.map((n) => n.id));
    setReadIds(allIds);
    saveStoredReadIds(allIds);
  }, [notifications]);

  const toggleSound = useCallback(() => {
    setSoundEnabled((prev) => {
      const next = !prev;
      if (typeof window !== "undefined") {
        localStorage.setItem(STORAGE_SOUND_KEY, String(next));
      }
      if (next) {
        playHotspotAlertSound();
      }
      return next;
    });
  }, []);

  const enableDesktopNotification = useCallback(async () => {
    if (!isBrowserNotificationSupported()) {
      return false;
    }
    const perm = await requestBrowserNotificationPermission();
    setDesktopPermission(perm);
    if (perm === "granted") {
      setDesktopEnabled(true);
      if (typeof window !== "undefined") {
        localStorage.setItem(STORAGE_DESKTOP_KEY, "true");
      }
      showBrowserHotspotNotification("Notifikasi ETASENEU Diaktifkan", {
        body: "Anda akan menerima notifikasi desktop bila ada titik panas baru di areal Perhutanan Sosial.",
      });
      return true;
    }
    setDesktopEnabled(false);
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_DESKTOP_KEY, "false");
    }
    return false;
  }, []);

  const toggleDesktopNotification = useCallback(() => {
    if (desktopEnabled) {
      setDesktopEnabled(false);
      if (typeof window !== "undefined") {
        localStorage.setItem(STORAGE_DESKTOP_KEY, "false");
      }
    } else {
      void enableDesktopNotification();
    }
  }, [desktopEnabled, enableDesktopNotification]);

  const dismissToast = useCallback(() => {
    setToastNotification(null);
    if (toastTimerRef.current) {
      window.clearTimeout(toastTimerRef.current);
    }
  }, []);

  const unreadCount = notifications.filter((n) => !readIds.has(n.id)).length;

  return {
    notifications,
    unreadCount,
    readIds,
    toastNotification,
    soundEnabled,
    desktopEnabled,
    desktopPermission,
    markAsRead,
    markAllAsRead,
    toggleSound,
    toggleDesktopNotification,
    enableDesktopNotification,
    dismissToast,
    refreshNotifications: fetchNotifications,
  };
}
