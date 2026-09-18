import React from "react";
import { Flame, X, ExternalLink, MapPin } from "lucide-react";
import type { HotspotNotification } from "../types/api";

interface ToastNotificationProps {
  notification: HotspotNotification;
  onClose: () => void;
  onViewMap?: () => void;
}

export const ToastNotification: React.FC<ToastNotificationProps> = ({
  notification,
  onClose,
  onViewMap,
}) => {
  const isDanger = notification.severity === "danger";
  const firstHotspot = notification.metadata?.hotspots?.[0];
  const maxFrp = notification.metadata?.max_frp ?? firstHotspot?.frp;

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="hotspot-toast-card"
      style={{
        position: "fixed",
        top: "1.25rem",
        right: "1.25rem",
        zIndex: 9999,
        width: "min(92vw, 380px)",
        backgroundColor: "rgba(22, 20, 18, 0.96)",
        backdropFilter: "blur(12px)",
        border: `1px solid ${isDanger ? "#ef4444" : "#f59e0b"}`,
        boxShadow: `0 10px 25px -5px rgba(0, 0, 0, 0.6), 0 0 15px ${
          isDanger ? "rgba(239, 68, 68, 0.35)" : "rgba(245, 158, 11, 0.35)"
        }`,
        borderRadius: "10px",
        padding: "0.85rem 1rem",
        color: "#f3f4f6",
        animation: "toastSlideIn 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem" }}>
        <div
          style={{
            flexShrink: 0,
            width: "36px",
            height: "36px",
            borderRadius: "50%",
            backgroundColor: isDanger ? "rgba(239, 68, 68, 0.2)" : "rgba(245, 158, 11, 0.2)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: isDanger ? "#ef4444" : "#f59e0b",
          }}
        >
          <Flame size={20} className="animate-pulse" />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
            <span
              style={{
                fontSize: "0.85rem",
                fontWeight: 700,
                color: isDanger ? "#fca5a5" : "#fcd34d",
                letterSpacing: "0.01em",
              }}
            >
              {notification.title}
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Tutup notifikasi"
              style={{
                background: "transparent",
                border: "none",
                color: "rgba(255, 255, 255, 0.6)",
                cursor: "pointer",
                padding: "2px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <X size={16} />
            </button>
          </div>

          <p
            style={{
              fontSize: "0.78rem",
              color: "rgba(255, 255, 255, 0.85)",
              margin: "0.35rem 0 0.5rem 0",
              lineHeight: 1.35,
            }}
          >
            {notification.message}
          </p>

          {/* Badge FRP jika ada */}
          {maxFrp !== undefined && maxFrp !== null && (
            <div style={{ marginBottom: "0.55rem" }}>
              <span
                style={{
                  fontSize: "0.68rem",
                  fontWeight: 600,
                  backgroundColor: "rgba(245, 158, 11, 0.15)",
                  color: "#fcd34d",
                  border: "1px solid rgba(245, 158, 11, 0.3)",
                  padding: "0.15rem 0.4rem",
                  borderRadius: "4px",
                }}
              >
                FRP: {maxFrp} MW
              </span>
            </div>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", flexWrap: "wrap" }}>
            {onViewMap && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onViewMap();
                }}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.35rem",
                  fontSize: "0.74rem",
                  fontWeight: 600,
                  padding: "0.3rem 0.65rem",
                  borderRadius: "6px",
                  backgroundColor: isDanger ? "#dc2626" : "#d97706",
                  color: "#ffffff",
                  border: "none",
                  cursor: "pointer",
                  transition: "background-color 0.15s ease",
                }}
              >
                <span>Lihat di Peta</span>
                <ExternalLink size={12} />
              </button>
            )}

            {firstHotspot && (
              <a
                href={firstHotspot.google_maps_url}
                target="_blank"
                rel="noopener noreferrer"
                onClick={onClose}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "0.25rem",
                  fontSize: "0.74rem",
                  fontWeight: 600,
                  padding: "0.3rem 0.6rem",
                  borderRadius: "6px",
                  backgroundColor: "rgba(59, 130, 246, 0.2)",
                  color: "#93c5fd",
                  border: "1px solid rgba(59, 130, 246, 0.4)",
                  textDecoration: "none",
                  transition: "background-color 0.15s ease",
                }}
              >
                <MapPin size={12} />
                <span>Google Maps</span>
              </a>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
