/**
 * Helper untuk Desktop / Web Browser Push Notification API.
 */

export function isBrowserNotificationSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function getNotificationPermission(): NotificationPermission {
  if (!isBrowserNotificationSupported()) {
    return "denied";
  }
  return Notification.permission;
}

export async function requestBrowserNotificationPermission(): Promise<NotificationPermission> {
  if (!isBrowserNotificationSupported()) {
    return "denied";
  }
  try {
    const perm = await Notification.requestPermission();
    return perm;
  } catch (err) {
    console.error("Gagal meminta izin notifikasi browser:", err);
    return Notification.permission;
  }
}

export function showBrowserHotspotNotification(
  title: string,
  options: {
    body: string;
    tag?: string;
    onClick?: () => void;
  }
): Notification | null {
  if (!isBrowserNotificationSupported() || Notification.permission !== "granted") {
    return null;
  }

  try {
    const notif = new Notification(title, {
      body: options.body,
      tag: options.tag || "etaseneu-hotspot",
      icon: "/favicon.ico",
      badge: "/favicon.ico",
      requireInteraction: false,
    });

    notif.onclick = () => {
      window.focus();
      options.onClick?.();
      notif.close();
    };

    return notif;
  } catch (err) {
    console.error("Gagal menampilkan notifikasi browser:", err);
    return null;
  }
}
