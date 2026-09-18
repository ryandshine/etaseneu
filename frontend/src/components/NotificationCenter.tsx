import React, { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  Bell,
  BellRing,
  Flame,
  Info,
  CheckCheck,
  Volume2,
  VolumeX,
  X,
  ExternalLink,
  ShieldCheck,
  MapPin,
  Eye,
  Zap,
} from "lucide-react";
import type { HotspotNotification } from "../types/api";
import { formatDateTimeWIB } from "../lib/date";

interface NotificationCenterProps {
  notifications: HotspotNotification[];
  unreadCount: number;
  readIds: Set<string>;
  soundEnabled: boolean;
  desktopEnabled: boolean;
  onMarkAsRead: (id: string) => void;
  onMarkAllAsRead: () => void;
  onToggleSound: () => void;
  onToggleDesktop: () => void;
  onNavigateToMap: () => void;
  onOpenKpsDetail?: (agency: string, polygonId?: number) => void;
}

export const NotificationCenter: React.FC<NotificationCenterProps> = ({
  notifications,
  unreadCount,
  readIds,
  soundEnabled,
  desktopEnabled,
  onMarkAsRead,
  onMarkAllAsRead,
  onToggleSound,
  onToggleDesktop,
  onNavigateToMap,
  onOpenKpsDetail,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const [panelStyle, setPanelStyle] = useState<React.CSSProperties>({
    position: "fixed",
    top: 60,
    left: 16,
    width: "min(92vw, 420px)",
    zIndex: 99999,
  });

  const updatePanelPosition = useCallback(() => {
    if (!buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const vw = typeof window !== "undefined" ? window.innerWidth : 1024;
    const vh = typeof window !== "undefined" ? window.innerHeight : 768;
    const panelWidth = Math.min(420, vw - 24);

    let top = rect.bottom + 8;
    if (top + 380 > vh) {
      top = Math.max(12, vh - 440);
    }

    if (vw < 540) {
      // Layar mobile kecil: rentangkan di tengah layar
      setPanelStyle({
        position: "fixed",
        top: Math.min(rect.bottom + 8, vh - 100),
        left: 12,
        right: 12,
        width: "auto",
        maxHeight: "calc(100vh - 80px)",
        zIndex: 99999,
      });
    } else if (rect.left < panelWidth) {
      // Tombol di dekat tepi kiri layar (misal: di sidebar brand)
      // Buka panel ke arah kanan agar TIDAK terpotong di tepi kiri layar
      const left = Math.max(12, Math.min(rect.left, vw - panelWidth - 12));
      setPanelStyle({
        position: "fixed",
        top,
        left,
        right: "auto",
        width: panelWidth,
        maxHeight: "calc(100vh - 80px)",
        zIndex: 99999,
      });
    } else {
      // Tombol di sisi kanan (misal: header navigasi)
      // Buka panel ke arah kiri tombol
      const right = Math.max(12, vw - rect.right);
      setPanelStyle({
        position: "fixed",
        top,
        left: "auto",
        right,
        width: panelWidth,
        maxHeight: "calc(100vh - 80px)",
        zIndex: 99999,
      });
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      updatePanelPosition();
      window.addEventListener("resize", updatePanelPosition);
      window.addEventListener("scroll", updatePanelPosition, true);
    }
    return () => {
      window.removeEventListener("resize", updatePanelPosition);
      window.removeEventListener("scroll", updatePanelPosition, true);
    };
  }, [isOpen, updatePanelPosition]);

  // Tutup panel bila klik di luar
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(event.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  // Tutup saat Escape ditekan
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      {/* Bell Trigger Button */}
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-label={`Notifikasi Hotspot (${unreadCount} belum dibaca)`}
        aria-expanded={isOpen}
        style={{
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: "36px",
          height: "36px",
          borderRadius: "8px",
          backgroundColor: isOpen ? "rgba(231, 230, 194, 0.15)" : "rgba(255, 255, 255, 0.05)",
          border: "1px solid rgba(255, 255, 255, 0.12)",
          color: unreadCount > 0 ? "#f59e0b" : "#E7E6C2",
          cursor: "pointer",
          transition: "all 0.15s ease",
        }}
      >
        {unreadCount > 0 ? (
          <BellRing size={19} className="animate-pulse" />
        ) : (
          <Bell size={19} />
        )}

        {/* Badge Unread Count */}
        {unreadCount > 0 && (
          <span
            style={{
              position: "absolute",
              top: "-4px",
              right: "-4px",
              backgroundColor: "#ef4444",
              color: "#ffffff",
              fontSize: "0.62rem",
              fontWeight: 800,
              minWidth: "18px",
              height: "18px",
              borderRadius: "999px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: "0 4px",
              boxShadow: "0 0 8px rgba(239, 68, 68, 0.8)",
              border: "1.5px solid #1c1917",
            }}
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {/* Popover Panel with Portal */}
      {isOpen &&
        (typeof document !== "undefined" && document.body
          ? createPortal(
              <div
                ref={panelRef}
                role="dialog"
                aria-label="Pusat Notifikasi Titik Panas"
                style={{
                  ...panelStyle,
                  backgroundColor: "#161412",
                  border: "1px solid rgba(255, 255, 255, 0.16)",
                  borderRadius: "12px",
                  boxShadow: "0 20px 40px -10px rgba(0, 0, 0, 0.9), 0 0 25px rgba(0, 0, 0, 0.7)",
                  display: "flex",
                  flexDirection: "column",
                  overflow: "hidden",
                  animation: "fadeIn 0.2s ease-out",
                }}
              >
          {/* Panel Header */}
          <div
            style={{
              padding: "0.85rem 1rem",
              borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
              backgroundColor: "rgba(255, 255, 255, 0.03)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span style={{ fontWeight: 700, fontSize: "0.9rem", color: "#E7E6C2" }}>
                Notifikasi Titik Panas
              </span>
              {unreadCount > 0 && (
                <span
                  style={{
                    backgroundColor: "rgba(239, 68, 68, 0.2)",
                    color: "#fca5a5",
                    fontSize: "0.68rem",
                    fontWeight: 700,
                    padding: "0.15rem 0.45rem",
                    borderRadius: "999px",
                    border: "1px solid rgba(239, 68, 68, 0.4)",
                  }}
                >
                  {unreadCount} Baru
                </span>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
              {/* Sound Toggle */}
              <button
                type="button"
                onClick={onToggleSound}
                title={soundEnabled ? "Bunyi alarm aktif (klik untuk matikan)" : "Bunyi alarm mati (klik untuk aktifkan)"}
                style={{
                  background: soundEnabled ? "rgba(16, 185, 129, 0.15)" : "rgba(255, 255, 255, 0.05)",
                  color: soundEnabled ? "#34d399" : "rgba(255, 255, 255, 0.4)",
                  border: "none",
                  borderRadius: "6px",
                  padding: "0.3rem",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                {soundEnabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
              </button>

              {/* Desktop Push Toggle */}
              <button
                type="button"
                onClick={onToggleDesktop}
                title={desktopEnabled ? "Notifikasi browser aktif" : "Aktifkan notifikasi desktop browser"}
                style={{
                  background: desktopEnabled ? "rgba(59, 130, 246, 0.15)" : "rgba(255, 255, 255, 0.05)",
                  color: desktopEnabled ? "#60a5fa" : "rgba(255, 255, 255, 0.4)",
                  border: "none",
                  borderRadius: "6px",
                  padding: "0.3rem",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Bell size={16} />
              </button>

              {/* Mark All as Read */}
              {unreadCount > 0 && (
                <button
                  type="button"
                  onClick={onMarkAllAsRead}
                  title="Tandai semua telah dibaca"
                  style={{
                    background: "transparent",
                    color: "rgba(255, 255, 255, 0.6)",
                    border: "none",
                    borderRadius: "6px",
                    padding: "0.3rem",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <CheckCheck size={16} />
                </button>
              )}

              {/* Close Button */}
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                title="Tutup"
                style={{
                  background: "transparent",
                  color: "rgba(255, 255, 255, 0.4)",
                  border: "none",
                  borderRadius: "6px",
                  padding: "0.3rem",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Notification List Scroll Area */}
          <div
            style={{
              padding: "0.6rem",
              overflowY: "auto",
              maxHeight: "360px",
              display: "flex",
              flexDirection: "column",
              gap: "0.5rem",
            }}
          >
            {notifications.length === 0 ? (
              <div
                style={{
                  padding: "2rem 1rem",
                  textAlign: "center",
                  color: "rgba(255, 255, 255, 0.5)",
                  fontSize: "0.82rem",
                }}
              >
                <ShieldCheck size={36} style={{ margin: "0 auto 0.6rem auto", color: "#10b981", opacity: 0.8 }} />
                <div style={{ fontWeight: 600, color: "#E7E6C2", marginBottom: "0.2rem" }}>
                  Aman, Belum Ada Hotspot Baru
                </div>
                <div>Sistem sedang memantau secara berkala.</div>
              </div>
            ) : (
              notifications.map((notif) => {
                const isRead = readIds.has(notif.id);
                const isDanger = notif.severity === "danger";

                return (
                  <div
                    key={notif.id}
                    onClick={() => onMarkAsRead(notif.id)}
                    style={{
                      padding: "0.75rem",
                      borderRadius: "8px",
                      backgroundColor: isRead ? "rgba(255, 255, 255, 0.02)" : "rgba(255, 255, 255, 0.06)",
                      border: `1px solid ${
                        isRead
                          ? "rgba(255, 255, 255, 0.05)"
                          : isDanger
                            ? "rgba(239, 68, 68, 0.3)"
                            : "rgba(245, 158, 11, 0.3)"
                      }`,
                      cursor: "pointer",
                      transition: "background-color 0.15s ease",
                      position: "relative",
                    }}
                  >
                    {!isRead && (
                      <span
                        style={{
                          position: "absolute",
                          top: "10px",
                          right: "10px",
                          width: "7px",
                          height: "7px",
                          borderRadius: "50%",
                          backgroundColor: isDanger ? "#ef4444" : "#f59e0b",
                        }}
                      />
                    )}

                    <div style={{ display: "flex", alignItems: "flex-start", gap: "0.6rem" }}>
                      <div
                        style={{
                          flexShrink: 0,
                          width: "28px",
                          height: "28px",
                          borderRadius: "50%",
                          backgroundColor:
                            notif.type === "system_status"
                              ? "rgba(59, 130, 246, 0.15)"
                              : isDanger
                                ? "rgba(239, 68, 68, 0.15)"
                                : "rgba(245, 158, 11, 0.15)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color:
                            notif.type === "system_status"
                              ? "#60a5fa"
                              : isDanger
                                ? "#ef4444"
                                : "#f59e0b",
                        }}
                      >
                        {notif.type === "system_status" ? (
                          <Info size={16} />
                        ) : (
                          <Flame size={16} />
                        )}
                      </div>

                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            fontWeight: isRead ? 500 : 700,
                            fontSize: "0.82rem",
                            color: isRead ? "#d1d5db" : "#ffffff",
                            marginBottom: "0.2rem",
                            paddingRight: "1rem",
                          }}
                        >
                          {notif.title}
                        </div>

                        <p
                          style={{
                            fontSize: "0.75rem",
                            color: "rgba(255, 255, 255, 0.7)",
                            margin: "0 0 0.4rem 0",
                            lineHeight: 1.35,
                          }}
                        >
                          {notif.message}
                        </p>

                        {/* Metadata Tags */}
                        {notif.metadata && (
                          <div
                            style={{
                              display: "flex",
                              flexWrap: "wrap",
                              gap: "0.3rem",
                              marginBottom: "0.4rem",
                            }}
                          >
                            {notif.hotspot_count > 0 && (
                              <span
                                style={{
                                  fontSize: "0.65rem",
                                  fontWeight: 700,
                                  backgroundColor: isDanger ? "rgba(239, 68, 68, 0.2)" : "rgba(245, 158, 11, 0.2)",
                                  color: isDanger ? "#fca5a5" : "#fcd34d",
                                  padding: "0.1rem 0.35rem",
                                  borderRadius: "4px",
                                }}
                              >
                                +{notif.hotspot_count} Titik Baru
                              </span>
                            )}
                            {notif.metadata.provinces?.slice(0, 3).map((p) => (
                              <span
                                key={p}
                                style={{
                                  fontSize: "0.65rem",
                                  backgroundColor: "rgba(255, 255, 255, 0.08)",
                                  color: "#E7E6C2",
                                  padding: "0.1rem 0.35rem",
                                  borderRadius: "4px",
                                }}
                              >
                                {p}
                              </span>
                            ))}
                            {notif.metadata.wilker_bps?.slice(0, 2).map((bps) => (
                              <span
                                key={bps}
                                style={{
                                  fontSize: "0.65rem",
                                  backgroundColor: "rgba(16, 185, 129, 0.15)",
                                  color: "#6ee7b7",
                                  border: "1px solid rgba(16, 185, 129, 0.3)",
                                  padding: "0.1rem 0.35rem",
                                  borderRadius: "4px",
                                }}
                              >
                                {bps}
                              </span>
                            ))}
                            {notif.metadata.max_frp ? (
                              <span
                                style={{
                                  fontSize: "0.65rem",
                                  backgroundColor: "rgba(255, 255, 255, 0.08)",
                                  color: "rgba(255, 255, 255, 0.65)",
                                  padding: "0.1rem 0.35rem",
                                  borderRadius: "4px",
                                }}
                              >
                                FRP: {notif.metadata.max_frp} MW
                              </span>
                            ) : null}
                          </div>
                        )}

                        {/* Rincian Hotspot Confidence Sedang & Tinggi (FRP & Google Maps) */}
                        {notif.metadata?.hotspots && notif.metadata.hotspots.length > 0 && (
                          <div
                            style={{
                              marginTop: "0.35rem",
                              marginBottom: "0.45rem",
                              backgroundColor: "rgba(0, 0, 0, 0.3)",
                              borderRadius: "6px",
                              border: "1px solid rgba(255, 255, 255, 0.08)",
                              padding: "0.4rem 0.5rem",
                              display: "flex",
                              flexDirection: "column",
                              gap: "0.35rem",
                            }}
                          >
                            <div
                              style={{
                                fontSize: "0.66rem",
                                fontWeight: 700,
                                color: "#E7E6C2",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "space-between",
                              }}
                            >
                              <span>Daftar Titik Panas ({notif.metadata.hotspots.length})</span>
                              <span style={{ fontSize: "0.6rem", color: "rgba(255, 255, 255, 0.45)", fontWeight: 400 }}>
                                Sedang / Tinggi
                              </span>
                            </div>

                            {notif.metadata.hotspots.slice(0, 5).map((h, hIdx) => {
                              const isHigh = h.confidence === "Tinggi";
                              return (
                                <div
                                  key={`${h.latitude}-${h.longitude}-${hIdx}`}
                                  style={{
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "space-between",
                                    fontSize: "0.68rem",
                                    padding: "0.35rem 0.5rem",
                                    borderRadius: "6px",
                                    backgroundColor: "rgba(255, 255, 255, 0.04)",
                                    border: "1px solid rgba(255, 255, 255, 0.07)",
                                    gap: "0.5rem",
                                  }}
                                >
                                  <div
                                    style={{
                                      flex: 1,
                                      minWidth: 0,
                                      cursor: onOpenKpsDetail ? "pointer" : "default",
                                    }}
                                    onClick={(e) => {
                                      if (onOpenKpsDetail && h.agency_name) {
                                        e.stopPropagation();
                                        setIsOpen(false);
                                        onMarkAsRead(notif.id);
                                        onOpenKpsDetail(h.agency_name);
                                      }
                                    }}
                                    title={onOpenKpsDetail ? `Buka Detail KPS: ${h.agency_name || "Areal KPS"}` : undefined}
                                  >
                                    <div
                                      style={{
                                        fontWeight: 700,
                                        color: "#f3f4f6",
                                        whiteSpace: "nowrap",
                                        overflow: "hidden",
                                        textOverflow: "ellipsis",
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "0.3rem",
                                      }}
                                    >
                                      <span>{h.agency_name || "Areal KPS"}</span>
                                      {onOpenKpsDetail && (
                                        <Eye size={11} style={{ opacity: 0.7, color: "#6ee7b7", flexShrink: 0 }} />
                                      )}
                                    </div>
                                    <div
                                      style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: "0.3rem",
                                        fontSize: "0.62rem",
                                        color: "rgba(255, 255, 255, 0.55)",
                                        flexWrap: "wrap",
                                        marginTop: "0.15rem",
                                      }}
                                    >
                                      <span
                                        style={{
                                          color: isHigh ? "#fca5a5" : "#fcd34d",
                                          fontWeight: 600,
                                        }}
                                      >
                                        {h.confidence}
                                      </span>
                                      <span>•</span>
                                      <span style={{ color: "#fbbf24", fontWeight: 600 }}>
                                        {h.frp !== null ? `${h.frp} MW` : "FRP —"}
                                      </span>
                                      {h.wilker_bps && (
                                        <>
                                          <span>•</span>
                                          <span style={{ color: "#6ee7b7", fontWeight: 600 }}>
                                            {h.wilker_bps}
                                          </span>
                                        </>
                                      )}
                                      {(h.kabupaten_name || h.province_name) && (
                                        <>
                                          <span>•</span>
                                          <span>
                                            {h.kabupaten_name
                                              ? `${h.kabupaten_name}, ${h.province_name}`
                                              : h.province_name}
                                          </span>
                                        </>
                                      )}
                                      <span>•</span>
                                      <span style={{ fontFamily: "monospace", color: "rgba(255, 255, 255, 0.45)" }}>
                                        {h.latitude.toFixed(5)}, {h.longitude.toFixed(5)}
                                      </span>
                                    </div>
                                  </div>

                                  <div style={{ display: "flex", alignItems: "center", gap: "0.35rem", flexShrink: 0 }}>
                                    {/* Tombol Shortcut Utama: Detail KPS */}
                                    <button
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        setIsOpen(false);
                                        onMarkAsRead(notif.id);
                                        if (onOpenKpsDetail && h.agency_name) {
                                          onOpenKpsDetail(h.agency_name);
                                        } else {
                                          onNavigateToMap();
                                        }
                                      }}
                                      title={`Buka Detail KPS: ${h.agency_name || "Areal KPS"}`}
                                      style={{
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: "0.25rem",
                                        fontSize: "0.66rem",
                                        fontWeight: 700,
                                        padding: "0.24rem 0.55rem",
                                        borderRadius: "5px",
                                        backgroundColor: "rgba(16, 185, 129, 0.22)",
                                        color: "#6ee7b7",
                                        border: "1px solid rgba(16, 185, 129, 0.45)",
                                        cursor: "pointer",
                                        transition: "all 0.15s ease",
                                      }}
                                    >
                                      <Eye size={11} />
                                      <span>Detail KPS</span>
                                    </button>

                                    {/* Tombol Shortcut Maps (Google Maps) */}
                                    {h.google_maps_url && (
                                      <a
                                        href={h.google_maps_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        onClick={(e) => e.stopPropagation()}
                                        title="Buka titik koordinat di Google Maps"
                                        style={{
                                          display: "inline-flex",
                                          alignItems: "center",
                                          gap: "0.2rem",
                                          fontSize: "0.64rem",
                                          fontWeight: 600,
                                          padding: "0.24rem 0.45rem",
                                          borderRadius: "5px",
                                          backgroundColor: "rgba(59, 130, 246, 0.18)",
                                          color: "#93c5fd",
                                          border: "1px solid rgba(59, 130, 246, 0.35)",
                                          textDecoration: "none",
                                          transition: "all 0.15s ease",
                                        }}
                                      >
                                        <MapPin size={11} />
                                        <span>Maps</span>
                                      </a>
                                    )}
                                  </div>
                                </div>
                              );
                            })}

                            {notif.metadata.hotspots.length > 5 && (
                              <div
                                style={{
                                  fontSize: "0.62rem",
                                  color: "rgba(255, 255, 255, 0.45)",
                                  textAlign: "center",
                                  fontStyle: "italic",
                                  paddingTop: "0.15rem",
                                }}
                              >
                                +{notif.metadata.hotspots.length - 5} titik lainnya dapat dilihat di peta
                              </div>
                            )}
                          </div>
                        )}

                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            fontSize: "0.68rem",
                            color: "rgba(255, 255, 255, 0.4)",
                          }}
                        >
                          <span>{formatDateTimeWIB(notif.created_at)}</span>

                          {notif.hotspot_count > 0 && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onMarkAsRead(notif.id);
                                setIsOpen(false);
                                onNavigateToMap();
                              }}
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                gap: "0.25rem",
                                background: "transparent",
                                border: "none",
                                color: "#E7E6C2",
                                fontWeight: 600,
                                cursor: "pointer",
                                padding: "2px 4px",
                              }}
                            >
                              <span>Lihat di Peta</span>
                              <ExternalLink size={11} />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>,
        document.body
      ) : null)}
    </div>
  );
};
