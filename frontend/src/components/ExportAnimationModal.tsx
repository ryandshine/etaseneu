import { useState, useRef } from "react";
import { X, Film, Download, Loader2, CheckCircle2, AlertCircle } from "lucide-react";

export interface ExportAnimationModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  dateRangeLabel?: string;
  totalFrames: number;
  activeHotspotCount?: number;
  kpsName?: string;
  onStartExport: (
    format: "gif" | "webm",
    speedMs: number,
    onProgress: (current: number, total: number, statusText: string) => void,
    signal: AbortSignal
  ) => Promise<void>;
}

export function ExportAnimationModal({
  isOpen,
  onClose,
  title,
  subtitle,
  dateRangeLabel,
  totalFrames,
  activeHotspotCount,
  kpsName,
  onStartExport
}: ExportAnimationModalProps) {
  const displayTitle = title || kpsName || "Kawasan KPS";
  const displaySubtitle =
    subtitle ||
    (activeHotspotCount !== undefined
      ? `${totalFrames} frame • ${activeHotspotCount} titik terpantau`
      : undefined);
  const [format, setFormat] = useState<"gif" | "webm">("gif");
  const [speedMs, setSpeedMs] = useState<number>(300);
  const [isExporting, setIsExporting] = useState(false);
  const [progress, setProgress] = useState<{ current: number; total: number; statusText: string }>({
    current: 0,
    total: totalFrames,
    statusText: ""
  });
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDone, setIsDone] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  if (!isOpen) return null;

  const handleStart = async () => {
    setIsExporting(true);
    setErrorMessage(null);
    setIsDone(false);
    setProgress({ current: 0, total: totalFrames, statusText: "Mempersiapkan perekaman..." });

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await onStartExport(
        format,
        speedMs,
        (current, total, statusText) => {
          setProgress({ current, total, statusText });
        },
        controller.signal
      );
      setIsDone(true);
      setTimeout(() => {
        if (!controller.signal.aborted) {
          onClose();
        }
      }, 1800);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setErrorMessage("Ekspor dibatalkan.");
      } else {
        setErrorMessage(
          err instanceof Error ? err.message : "Terjadi kesalahan saat memproses animasi."
        );
      }
    } finally {
      setIsExporting(false);
      abortControllerRef.current = null;
    }
  };

  const handleCancel = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    onClose();
  };

  const progressPercent =
    progress.total > 0 ? Math.round((progress.current / progress.total) * 100) : 0;

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="export-modal-title">
      <div className="modal-card export-modal">
        <div className="export-modal__header">
          <div className="export-modal__header-title">
            <Film size={18} className="export-modal__icon" />
            <h3 id="export-modal-title">Unduh Animasi Sebaran Hotspot</h3>
          </div>
          <button
            type="button"
            className="export-modal__close-btn"
            onClick={handleCancel}
            disabled={isExporting}
            aria-label="Tutup modal"
          >
            <X size={16} />
          </button>
        </div>

        <div className="export-modal__body">
          <div className="export-modal__target">
            <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", flexWrap: "wrap" }}>
                <span className="export-modal__target-label">KPS / Lembaga:</span>
                <strong className="export-modal__target-title">{displayTitle}</strong>
              </div>
              {dateRangeLabel && (
                <div style={{ display: "flex", alignItems: "baseline", gap: "0.45rem", flexWrap: "wrap", fontSize: "0.8rem" }}>
                  <span className="export-modal__target-label">Rentang Waktu:</span>
                  <span style={{ color: "#38bdf8", fontWeight: 600 }}>{dateRangeLabel}</span>
                </div>
              )}
              {displaySubtitle && <span className="export-modal__target-sub">{displaySubtitle}</span>}
            </div>
          </div>

          {!isExporting && !isDone && (
            <>
              <div className="export-modal__section">
                <label className="export-modal__label">Pilih Format Animasi:</label>
                <div className="export-modal__formats">
                  <button
                    type="button"
                    className={`export-format-card ${format === "gif" ? "export-format-card--active" : ""}`}
                    onClick={() => setFormat("gif")}
                  >
                    <div className="export-format-card__badge">GIF</div>
                    <div className="export-format-card__info">
                      <strong>GIF Animasi (.gif)</strong>
                      <span>Ideal untuk WhatsApp, PowerPoint (.pptx), dan Word</span>
                    </div>
                  </button>

                  <button
                    type="button"
                    className={`export-format-card ${format === "webm" ? "export-format-card--active" : ""}`}
                    onClick={() => setFormat("webm")}
                  >
                    <div className="export-format-card__badge">VIDEO</div>
                    <div className="export-format-card__info">
                      <strong>Video WebM (.webm)</strong>
                      <span>Resolusi tinggi, hemat memori, untuk presentasi digital</span>
                    </div>
                  </button>
                </div>
              </div>

              <div className="export-modal__section">
                <label className="export-modal__label">Kecepatan Frame per Langkah:</label>
                <div className="export-modal__speeds">
                  <button
                    type="button"
                    className={`chip chip--button ${speedMs === 150 ? "chip--active" : ""}`}
                    onClick={() => setSpeedMs(150)}
                  >
                    Cepat (0.15s)
                  </button>
                  <button
                    type="button"
                    className={`chip chip--button ${speedMs === 300 ? "chip--active" : ""}`}
                    onClick={() => setSpeedMs(300)}
                  >
                    Normal (0.30s)
                  </button>
                  <button
                    type="button"
                    className={`chip chip--button ${speedMs === 500 ? "chip--active" : ""}`}
                    onClick={() => setSpeedMs(500)}
                  >
                    Perlahan (0.50s)
                  </button>
                </div>
              </div>

              <div className="export-modal__info-box">
                <p>
                  Animasi ini merekam <strong>{totalFrames} frame waktu</strong> dengan overlay otomatis
                  berisi stempel waktu WIB, nama KPS resmi, dan jumlah titik aktif (dalam poligon maupun di zona penyangga luar).
                </p>
              </div>
            </>
          )}

          {isExporting && (
            <div className="export-modal__progress-box">
              <div className="export-modal__progress-top">
                <Loader2 size={20} className="animate-spin text-orange-500" />
                <span className="export-modal__progress-text">{progress.statusText}</span>
                <span className="export-modal__progress-pct">{progressPercent}%</span>
              </div>
              <div className="export-progress-bar">
                <div
                  className="export-progress-bar__fill"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
              <p className="export-modal__progress-hint">
                Mohon jangan menutup jendela browser selama proses rendering berlangsung.
              </p>
            </div>
          )}

          {isDone && (
            <div className="export-modal__done-box">
              <CheckCircle2 size={28} className="text-emerald-500" />
              <p>Animasi berhasil dibuat dan otomatis diunduh ke perangkat Anda!</p>
            </div>
          )}

          {errorMessage && (
            <div className="export-modal__error-box">
              <AlertCircle size={16} />
              <span>{errorMessage}</span>
            </div>
          )}
        </div>

        <div className="export-modal__footer">
          <button
            type="button"
            className="matrix-btn"
            onClick={handleCancel}
            disabled={isExporting}
          >
            {isDone ? "Selesai" : "Batal"}
          </button>
          {!isDone && (
            <button
              type="button"
              className="matrix-btn matrix-btn--primary"
              onClick={handleStart}
              disabled={isExporting || totalFrames === 0}
            >
              {isExporting ? (
                <>
                  <Loader2 size={14} className="animate-spin" />
                  <span>Memproses...</span>
                </>
              ) : (
                <>
                  <Download size={14} />
                  <span>Mulai Rekam &amp; Unduh</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
