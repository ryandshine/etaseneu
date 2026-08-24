import { useState, useEffect, useRef } from "react";
import type { AppSession, GeoJsonStatusResponse } from "../types/api";
import { UserManagementPanel } from "./UserManagementPanel";

type SettingsPanelProps = {
  onRefreshLayers: () => void;
  adminKey: string | null;
  session: AppSession | null;
};

export function SettingsPanel({ onRefreshLayers, adminKey, session }: SettingsPanelProps) {
  const [registryStatus, setRegistryStatus] = useState<GeoJsonStatusResponse | null>(null);
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const [feedback, setFeedback] = useState<{ tone: "success" | "danger" | "warn"; title: string; body: string } | null>(null);
  // Default "add": sistem ini memuat lebih dari satu layer (Perhutanan Sosial,
  // Hutan Adat, dst). "replace" menghapus SEMUA layer lain, jadi itu tindakan
  // yang harus dipilih sadar, bukan yang kebetulan terjadi.
  const [uploadMode, setUploadMode] = useState<"add" | "replace">("add");
  const fileInputRef = useRef<HTMLInputElement>(null);
  type LayerAction = "delete" | "deactivate";
  const [pendingAction, setPendingAction] = useState<{ fileName: string; action: LayerAction } | null>(null);
  const [processingFile, setProcessingFile] = useState<string | null>(null);

  const fetchStatus = async () => {
    setLoadingStatus(true);
    try {
      const response = await fetch("/api/geojson/status");
      if (response.ok) {
        const data = await response.json();
        setRegistryStatus(data);
      }
    } catch (e) {
      console.error("Gagal memuat status registri:", e);
    } finally {
      setLoadingStatus(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      validateAndUpload(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      validateAndUpload(e.target.files[0]);
    }
  };

  const validateAndUpload = (file: File) => {
    setFeedback(null);
    if (!file.name.endsWith(".geojson")) {
      setFeedback({
        tone: "danger",
        title: "Ekstensi berkas tidak valid",
        body: "Hanya file dengan ekstensi berkas .geojson yang diperbolehkan untuk diunggah."
      });
      return;
    }

    const maxSize = 500 * 1024 * 1024; // 500MB limit
    if (file.size > maxSize) {
      setFeedback({
        tone: "danger",
        title: "Ukuran berkas terlalu besar",
        body: `Ukuran berkas (${(file.size / (1024 * 1024)).toFixed(1)}MB) melebihi batas maksimum yang diperbolehkan (500MB).`
      });
      return;
    }

    uploadFile(file);
  };

  const uploadFile = (file: File) => {
    setUploading(true);
    setUploadProgress(0);

    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file);
    formData.append("mode", uploadMode);

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        const percentComplete = Math.round((e.loaded / e.total) * 100);
        setUploadProgress(percentComplete);
      }
    });

    xhr.addEventListener("load", () => {
      setUploading(false);
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const res = JSON.parse(xhr.responseText);
          setFeedback({
            tone: "success",
            title: "Unggahan Berhasil",
            body: `File ${res.file_name} berhasil dimuat. ${res.summary?.features_upserted ?? 0} poligon baru ditambahkan/diperbarui dan di-intersect dengan data hotspot.`
          });
          fetchStatus();
          onRefreshLayers();
        } catch {
          setFeedback({
            tone: "success",
            title: "Unggahan Berhasil",
            body: `File ${file.name} berhasil disimpan dan disinkronkan ke sistem.`
          });
          fetchStatus();
          onRefreshLayers();
        }
      } else {
        let errorMsg = "Terjadi kesalahan saat memproses file GeoJSON di server.";
        try {
          const res = JSON.parse(xhr.responseText);
          if (res.detail) errorMsg = res.detail;
        } catch {}
        setFeedback({
          tone: "danger",
          title: "Proses Unggahan Gagal",
          body: errorMsg
        });
      }
    });

    xhr.addEventListener("error", () => {
      setUploading(false);
      setFeedback({
        tone: "danger",
        title: "Koneksi Terputus",
        body: "Terjadi kesalahan jaringan saat mengunggah file. Silakan coba lagi."
      });
    });

    xhr.open("POST", "/api/geojson/upload");
    if (adminKey) {
      xhr.setRequestHeader("X-Admin-Key", adminKey);
    }
    xhr.send(formData);
  };

  const ACTION_CONFIG: Record<
    LayerAction,
    { method: "DELETE" | "POST"; path: (f: string) => string; successTitle: string; successBody: (f: string) => string; failTitle: string }
  > = {
    delete: {
      method: "DELETE",
      path: (f) => `/api/geojson/${encodeURIComponent(f)}`,
      successTitle: "Berkas Dihapus",
      successBody: (f) => `${f} beserta poligon terkaitnya telah dihapus permanen dari sistem.`,
      failTitle: "Gagal Menghapus Berkas",
    },
    deactivate: {
      method: "POST",
      path: (f) => `/api/geojson/${encodeURIComponent(f)}/deactivate`,
      successTitle: "Layer Dinonaktifkan",
      successBody: (f) => `${f} dinonaktifkan. Riwayatnya tetap tersimpan dan masih terlihat di daftar sebagai NONAKTIF.`,
      failTitle: "Gagal Menonaktifkan Layer",
    },
  };

  const handleLayerAction = async (fileName: string, action: LayerAction) => {
    setProcessingFile(fileName);
    setFeedback(null);
    const config = ACTION_CONFIG[action];
    try {
      const response = await fetch(config.path(fileName), {
        method: config.method,
        headers: adminKey ? { "X-Admin-Key": adminKey } : {},
      });
      const body = await response.json().catch(() => null);
      if (response.ok) {
        setFeedback({ tone: "success", title: config.successTitle, body: config.successBody(fileName) });
        fetchStatus();
        onRefreshLayers();
      } else {
        setFeedback({
          tone: "danger",
          title: config.failTitle,
          body: body?.detail ?? "Terjadi kesalahan saat memproses berkas GeoJSON di server."
        });
      }
    } catch {
      setFeedback({
        tone: "danger",
        title: "Koneksi Terputus",
        body: "Terjadi kesalahan jaringan. Silakan coba lagi."
      });
    } finally {
      setProcessingFile(null);
      setPendingAction(null);
    }
  };

  return (
    <div className="view-content-scroll" style={{ padding: "2rem", maxWidth: "900px", margin: "0 auto" }}>
      <div className="monitoring-header" style={{ marginBottom: "2rem" }}>
        <h1>Pengaturan Sistem</h1>
        <p className="monitoring-header-subtitle">
          Kelola dataset wilayah perhutanan sosial (GeoJSON) dan koordinasi intersect data spasial.
        </p>
      </div>

      {feedback && (
        <div 
          className={`signal-banner signal-banner--${feedback.tone}`} 
          style={{ marginBottom: "1.5rem", borderRadius: "8px", animation: "slideIn 0.3s ease" }}
        >
          <div className="signal-banner-head">
            <span className={`signal-badge signal-badge--${feedback.tone === "danger" ? "critical" : feedback.tone === "warn" ? "incident" : "normal"}`}>
              {feedback.tone === "danger" ? "ERROR" : feedback.tone === "warn" ? "WARN" : "SUKSES"}
            </span>
            <strong className="signal-banner-title">{feedback.title}</strong>
          </div>
          <p className="signal-banner-body" style={{ marginTop: "0.5rem" }}>{feedback.body}</p>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: "2rem" }}>
        {/* Upload Card */}
        <div style={{ background: "rgba(17, 24, 39, 0.5)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: "12px", padding: "2rem" }}>
          <h2 style={{ fontSize: "1.25rem", color: "#fff", marginBottom: "0.5rem", fontWeight: "600" }}>Unggah Berkas GeoJSON Baru</h2>
          <p style={{ color: "#9ca3af", fontSize: "0.88rem", marginBottom: "1rem" }}>
            Unggah berkas GeoJSON batas wilayah. Setelah tersimpan, sistem otomatis menjalankan
            intersect ulang terhadap seluruh riwayat titik hotspot NASA FIRMS yang telah terekam.
          </p>

          <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem", marginBottom: "1.5rem" }}>
            {([
              {
                value: "add" as const,
                title: "Tambah layer baru",
                body: "Layer yang sudah ada tetap utuh. Berkas dengan nama sama akan diperbarui."
              },
              {
                value: "replace" as const,
                title: "Ganti semua layer",
                body: "Menghapus SELURUH layer yang ada, termasuk Perhutanan Sosial, lalu memuat berkas ini saja."
              }
            ]).map((option) => {
              const active = uploadMode === option.value;
              const danger = option.value === "replace";
              return (
                <label
                  key={option.value}
                  style={{
                    display: "flex",
                    gap: "0.65rem",
                    alignItems: "flex-start",
                    padding: "0.75rem 0.9rem",
                    borderRadius: "6px",
                    cursor: uploading ? "not-allowed" : "pointer",
                    border: `1px solid ${active ? (danger ? "rgba(239,68,68,0.5)" : "rgba(16,185,129,0.5)") : "rgba(255,255,255,0.1)"}`,
                    background: active ? (danger ? "rgba(239,68,68,0.07)" : "rgba(16,185,129,0.06)") : "rgba(255,255,255,0.02)"
                  }}
                >
                  <input
                    type="radio"
                    name="upload-mode"
                    value={option.value}
                    checked={active}
                    disabled={uploading}
                    onChange={() => setUploadMode(option.value)}
                    style={{ marginTop: "0.2rem" }}
                  />
                  <span>
                    <span style={{ display: "block", color: danger && active ? "#fca5a5" : "#fff", fontWeight: 600, fontSize: "0.85rem" }}>
                      {option.title}
                    </span>
                    <span style={{ display: "block", color: "#9ca3af", fontSize: "0.78rem", marginTop: "0.15rem" }}>
                      {option.body}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>

          <form
            onDragEnter={handleDrag}
            onDragOver={handleDrag}
            onDragLeave={handleDrag}
            onDrop={handleDrop}
            onClick={() => !uploading && fileInputRef.current?.click()}
            style={{
              border: `2px dashed ${dragActive ? "#10b981" : "rgba(255, 255, 255, 0.15)"}`,
              borderRadius: "8px",
              padding: "3rem 2rem",
              textAlign: "center",
              cursor: uploading ? "not-allowed" : "pointer",
              background: dragActive ? "rgba(16, 185, 129, 0.05)" : "rgba(255, 255, 255, 0.02)",
              transition: "all 0.2s ease",
            }}
          >
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileChange}
              style={{ display: "none" }}
              accept=".geojson"
              disabled={uploading}
            />

            {uploading ? (
              <div>
                <div style={{ display: "flex", justifyContent: "space-between", color: "#fff", fontSize: "0.85rem", marginBottom: "0.5rem", maxWidth: "300px", margin: "0 auto 0.5rem" }}>
                  <span>Mengunggah Berkas...</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div style={{ width: "100%", height: "8px", background: "rgba(255, 255, 255, 0.1)", borderRadius: "4px", overflow: "hidden", maxWidth: "300px", margin: "0 auto 1rem" }}>
                  <div style={{ width: `${uploadProgress}%`, height: "100%", background: "#10b981", borderRadius: "4px", transition: "width 0.1s ease" }} />
                </div>
                <p style={{ color: "#9ca3af", fontSize: "0.75rem" }}>Jangan menutup halaman ini hingga proses pemrosesan spasial di server selesai.</p>
              </div>
            ) : (
              <div>
                <svg
                  style={{ width: "48px", height: "48px", color: dragActive ? "#10b981" : "#6b7280", marginBottom: "1rem", transition: "color 0.2s ease" }}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                  />
                </svg>
                <p style={{ color: "#fff", fontWeight: "500", fontSize: "0.95rem", marginBottom: "0.25rem" }}>
                  Tarik & lepas file GeoJSON di sini, atau klik untuk memilih
                </p>
                <p style={{ color: "#6b7280", fontSize: "0.78rem" }}>Format yang diterima: .geojson (Max. 500MB)</p>
              </div>
            )}
          </form>
        </div>

        {/* Current State Card */}
        <div style={{ background: "rgba(17, 24, 39, 0.5)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: "12px", padding: "2rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h2 style={{ fontSize: "1.25rem", color: "#fff", fontWeight: "600", margin: 0 }}>Daftar Layer Terdaftar saat ini</h2>
            <button
              onClick={fetchStatus}
              disabled={loadingStatus}
              style={{
                background: "transparent",
                border: "1px solid rgba(255, 255, 255, 0.15)",
                color: "#fff",
                padding: "0.4rem 0.8rem",
                borderRadius: "6px",
                fontSize: "0.78rem",
                cursor: "pointer",
              }}
            >
              {loadingStatus ? "Memuat..." : "Refresh Status"}
            </button>
          </div>

          {registryStatus && registryStatus.files && registryStatus.files.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              {registryStatus.files.map((file: any) => {
                const confirmingAction =
                  pendingAction !== null && pendingAction.fileName === file.file_name ? pendingAction.action : null;
                const isProcessing = processingFile === file.file_name;
                return (
                <div
                  key={file.file_name}
                  style={{
                    background: "rgba(255, 255, 255, 0.02)",
                    border: `1px solid ${confirmingAction ? "rgba(239,68,68,0.4)" : "rgba(255, 255, 255, 0.05)"}`,
                    borderRadius: "8px",
                    padding: "1rem",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: "1rem",
                  }}
                >
                  <div>
                    <strong style={{ color: "#fff", fontSize: "0.95rem", display: "block" }}>{file.file_name}</strong>
                    <span style={{ color: "#9ca3af", fontSize: "0.75rem" }}>
                      Layer Key: <code>{file.layer_key}</code>
                    </span>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", justifyContent: "flex-end", marginBottom: "0.25rem" }}>
                        <span style={{
                          width: "6px",
                          height: "6px",
                          borderRadius: "50%",
                          backgroundColor: file.is_active ? "#10b981" : "#6b7280"
                        }} />
                        <span style={{ fontSize: "0.75rem", color: file.is_active ? "#10b981" : "#6b7280", fontWeight: "bold" }}>
                          {file.is_active ? "AKTIF" : "NONAKTIF"}
                        </span>
                      </div>
                      <span style={{ color: "#9ca3af", fontSize: "0.75rem" }}>
                        {file.feature_count} Poligon Wilayah
                      </span>
                    </div>
                    {confirmingAction ? (
                      <div style={{ display: "flex", gap: "0.4rem" }}>
                        <button
                          onClick={() => handleLayerAction(file.file_name, confirmingAction)}
                          disabled={isProcessing}
                          style={{
                            background: "#ef4444",
                            border: "1px solid #ef4444",
                            color: "#fff",
                            padding: "0.4rem 0.7rem",
                            borderRadius: "6px",
                            fontSize: "0.75rem",
                            fontWeight: 600,
                            cursor: isProcessing ? "not-allowed" : "pointer",
                            opacity: isProcessing ? 0.7 : 1,
                          }}
                        >
                          {isProcessing
                            ? confirmingAction === "delete" ? "Menghapus…" : "Menonaktifkan…"
                            : confirmingAction === "delete" ? "Yakin, Hapus" : "Yakin, Nonaktifkan"}
                        </button>
                        <button
                          onClick={() => setPendingAction(null)}
                          disabled={isProcessing}
                          style={{
                            background: "transparent",
                            border: "1px solid rgba(255,255,255,0.15)",
                            color: "#fff",
                            padding: "0.4rem 0.7rem",
                            borderRadius: "6px",
                            fontSize: "0.75rem",
                            cursor: isProcessing ? "not-allowed" : "pointer",
                          }}
                        >
                          Batal
                        </button>
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: "0.4rem" }}>
                        {file.is_active && (
                          <button
                            onClick={() => setPendingAction({ fileName: file.file_name, action: "deactivate" })}
                            title={`Nonaktifkan ${file.file_name}`}
                            style={{
                              background: "transparent",
                              border: "1px solid rgba(255,255,255,0.15)",
                              color: "#d1d5db",
                              padding: "0.4rem 0.7rem",
                              borderRadius: "6px",
                              fontSize: "0.75rem",
                              cursor: "pointer",
                            }}
                          >
                            Nonaktifkan
                          </button>
                        )}
                        <button
                          onClick={() => setPendingAction({ fileName: file.file_name, action: "delete" })}
                          title={`Hapus ${file.file_name}`}
                          style={{
                            background: "transparent",
                            border: "1px solid rgba(239,68,68,0.35)",
                            color: "#fca5a5",
                            padding: "0.4rem 0.7rem",
                            borderRadius: "6px",
                            fontSize: "0.75rem",
                            cursor: "pointer",
                          }}
                        >
                          Hapus
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );})}
            </div>
          ) : (
            <div style={{ textAlign: "center", padding: "2rem", color: "#6b7280", fontSize: "0.85rem" }}>
              Tidak ada file GeoJSON yang aktif terdaftar dalam sistem.
            </div>
          )}
        </div>

        {session?.role === "admin" ? (
          <UserManagementPanel token={session.token} currentUsername={session.username} />
        ) : null}
      </div>
    </div>
  );
}
