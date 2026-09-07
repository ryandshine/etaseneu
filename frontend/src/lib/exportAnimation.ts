import { GIFEncoder, quantize, applyPalette } from "gifenc";

export interface OverlayInfo {
  title: string;
  subtitle?: string;
  dateRangeLabel?: string;
  timeLabel: string;
  activeCount: number;
  insideCount?: number;
  outsideCount?: number;
  bufferKm?: number;
  frameIndex: number;
  totalFrames: number;
}

export interface AnimationExportOptions {
  mapContainer: HTMLElement;
  totalFrames: number;
  stepToFrame: (frameIndex: number) => Promise<void>;
  getOverlayInfo: (frameIndex: number) => OverlayInfo;
  delayMs?: number;
  format?: "gif" | "webm";
  onProgress?: (current: number, total: number, statusText: string) => void;
  signal?: AbortSignal;
}

/** Bulatkan ke bawah ke bilangan genap. Dimensi ganjil membuat encoder H.264
 *  (dipakai WhatsApp saat mengonversi GIF/video ke MP4) menghasilkan berkas
 *  rusak / diam -- ini penyebab umum "GIF tidak jalan di WhatsApp". */
function evenFloor(n: number): number {
  return Math.max(2, Math.floor(n)) & ~1;
}

/** Urutan mimeType video: MP4/H.264 lebih dulu karena itu yang diputar mulus
 *  di WhatsApp & semua ponsel; WebM sebagai cadangan untuk browser yang belum
 *  bisa merekam MP4 (mis. Chrome Linux lama). */
const VIDEO_MIME_CANDIDATES = [
  "video/mp4;codecs=avc1.42E01E",
  "video/mp4;codecs=avc1",
  "video/mp4",
  "video/webm;codecs=vp9",
  "video/webm;codecs=vp8",
  "video/webm",
];

function pickVideoMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "video/webm";
  for (const mime of VIDEO_MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime;
  }
  return "video/webm";
}

/** Ekstensi berkas dari tipe blob hasil ekspor. */
export function extensionForExportBlob(blob: Blob): "gif" | "mp4" | "webm" {
  if (blob.type.includes("gif")) return "gif";
  if (blob.type.includes("mp4")) return "mp4";
  return "webm";
}

/**
 * Menggambar snapshot elemen Leaflet (tiles dan canvas) beserta
 * overlay kop judul resmi, stempel waktu, dan counter hotspot ke kanvas komposit.
 */
export function captureMapFrame(
  mapContainer: HTMLElement,
  overlay: OverlayInfo,
  targetCanvas?: HTMLCanvasElement
): HTMLCanvasElement {
  const mapRect = mapContainer.getBoundingClientRect();
  const width = evenFloor(Math.max(320, mapRect.width));
  const height = evenFloor(Math.max(240, mapRect.height));

  const canvas = targetCanvas || document.createElement("canvas");
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return canvas;

  // 1. Background dasar gelap
  ctx.fillStyle = "#0f172a";
  ctx.fillRect(0, 0, width, height);

  // 2. Gambar Leaflet Tiles (jika ada)
  const tiles = mapContainer.querySelectorAll<HTMLImageElement>("img.leaflet-tile");
  tiles.forEach((tile) => {
    try {
      if (tile.complete && tile.naturalWidth > 0) {
        const rect = tile.getBoundingClientRect();
        const x = rect.left - mapRect.left;
        const y = rect.top - mapRect.top;
        ctx.drawImage(tile, x, y, rect.width, rect.height);
      }
    } catch {
      // Abaikan bila ada ubin yang terkena taint CORS
    }
  });

  // 3. Gambar Leaflet Overlay Canvases (poligon KPS, bekas terbakar, titik hotspot)
  const panes = mapContainer.querySelectorAll<HTMLCanvasElement>(".leaflet-pane canvas");
  panes.forEach((paneCanvas) => {
    try {
      const rect = paneCanvas.getBoundingClientRect();
      const x = rect.left - mapRect.left;
      const y = rect.top - mapRect.top;
      ctx.drawImage(paneCanvas, x, y, rect.width, rect.height);
    } catch {
      // Abaikan bila canvas tidak dapat diakses
    }
  });

  // 4. Render Overlay Kop Kartu Judul KPS (Top-Left)
  ctx.save();
  const pad = 12;
  const headerCardWidth = Math.min(width - pad * 2, 450);

  let headerCardHeight = 46;
  if (overlay.subtitle && overlay.dateRangeLabel) {
    headerCardHeight = 84;
  } else if (overlay.subtitle || overlay.dateRangeLabel) {
    headerCardHeight = 66;
  }

  // Background kartu kop dengan glassmorphism dark
  ctx.fillStyle = "rgba(15, 23, 42, 0.92)";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.16)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(pad, pad, headerCardWidth, headerCardHeight, 6);
  ctx.fill();
  ctx.stroke();

  let textY = pad + 16;

  // Baris 1: Tag/Pill "KPS / PERHUTANAN SOSIAL"
  ctx.fillStyle = "#f97316";
  ctx.beginPath();
  ctx.arc(pad + 12, textY - 3, 3.5, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = "#fb923c";
  ctx.font = "bold 9px system-ui, -apple-system, sans-serif";
  ctx.fillText("KPS / PERHUTANAN SOSIAL", pad + 20, textY);

  // Baris 2: Nama KPS Resmi
  textY += 16;
  ctx.fillStyle = "#f8fafc";
  ctx.font = "bold 13px system-ui, -apple-system, sans-serif";
  const displayTitle = overlay.title;
  const maxTitleChars = Math.floor((headerCardWidth - 24) / 7.8);
  const truncatedTitle =
    displayTitle.length > maxTitleChars ? `${displayTitle.slice(0, maxTitleChars)}...` : displayTitle;
  ctx.fillText(truncatedTitle, pad + 10, textY);

  // Baris 3: Lokasi Administratif & Luas Kawasan (jika ada)
  if (overlay.subtitle) {
    textY += 16;
    ctx.fillStyle = "#94a3b8";
    ctx.font = "11px system-ui, -apple-system, sans-serif";
    const maxSubChars = Math.floor((headerCardWidth - 24) / 6.5);
    const subText =
      overlay.subtitle.length > maxSubChars
        ? `${overlay.subtitle.slice(0, maxSubChars)}...`
        : overlay.subtitle;
    ctx.fillText(`📍 ${subText}`, pad + 10, textY);
  }

  // Baris 4: Rentang Waktu Analisis (jika ada)
  if (overlay.dateRangeLabel) {
    textY += 16;
    ctx.fillStyle = "#38bdf8";
    ctx.font = "bold 10.5px system-ui, -apple-system, sans-serif";
    const maxRangeChars = Math.floor((headerCardWidth - 24) / 6.5);
    const rangeText =
      overlay.dateRangeLabel.length > maxRangeChars
        ? `${overlay.dateRangeLabel.slice(0, maxRangeChars)}...`
        : overlay.dateRangeLabel;
    ctx.fillText(`📅 Rentang: ${rangeText}`, pad + 10, textY);
  }

  // 5. Badge Branding Kanan Atas (ETA SENEU)
  const brandWidth = 100;
  const brandHeight = 24;
  const brandX = width - pad - brandWidth;
  ctx.fillStyle = "rgba(15, 23, 42, 0.85)";
  ctx.strokeStyle = "rgba(249, 115, 22, 0.4)";
  ctx.beginPath();
  ctx.roundRect(brandX, pad, brandWidth, brandHeight, 4);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "#fb923c";
  ctx.font = "bold 10px system-ui, sans-serif";
  ctx.fillText("ETA SENEU", brandX + 8, pad + 16);
  ctx.fillStyle = "#cbd5e1";
  ctx.font = "9px system-ui, sans-serif";
  ctx.fillText("KPS", brandX + 75, pad + 16);

  // 6. Bottom Overlay Bar (Waktu Deteksi Berjalan & Counter Titik Panas)
  const bottomBarHeight = 36;
  const bottomBarY = height - pad - bottomBarHeight;

  ctx.fillStyle = "rgba(15, 23, 42, 0.92)";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.18)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(pad, bottomBarY, width - pad * 2, bottomBarHeight, 6);
  ctx.fill();
  ctx.stroke();

  // Ikon & Teks Stempel Waktu Deteksi Berjalan
  ctx.fillStyle = "#38bdf8";
  ctx.font = "bold 12px system-ui, sans-serif";
  const cleanTimeLabel = overlay.timeLabel.includes("WIB")
    ? overlay.timeLabel
    : `${overlay.timeLabel} WIB`;
  ctx.fillText(`🕒 Deteksi: ${cleanTimeLabel}`, pad + 10, bottomBarY + 22);

  // Counter Titik Hotspot & Frame Info
  let counterText = `🔥 ${overlay.activeCount} Titik Panas Aktif`;
  if (
    overlay.insideCount !== undefined &&
    overlay.outsideCount !== undefined &&
    overlay.outsideCount > 0
  ) {
    counterText = `🔥 ${overlay.activeCount} Titik (${overlay.insideCount} Dalam • ${overlay.outsideCount} Luar)`;
  }
  const frameText = `• Frame ${overlay.frameIndex + 1}/${overlay.totalFrames}`;
  const fullCounterText = `${counterText} ${frameText}`;

  ctx.fillStyle = overlay.activeCount > 0 ? "#f87171" : "#10b981";
  ctx.font = "bold 11px system-ui, sans-serif";
  const counterWidth = ctx.measureText(fullCounterText).width;
  if (width - pad * 2 - counterWidth - 220 > 0) {
    ctx.fillText(fullCounterText, width - pad - counterWidth - 12, bottomBarY + 22);
  } else {
    const smallCounterWidth = ctx.measureText(counterText).width;
    ctx.fillText(counterText, width - pad - smallCounterWidth - 12, bottomBarY + 22);
  }

  // 7. Scrubber garis progres animasi di batas paling bawah
  const progressRatio = Math.min(1, (overlay.frameIndex + 1) / Math.max(1, overlay.totalFrames));
  ctx.fillStyle = "rgba(255, 255, 255, 0.12)";
  ctx.fillRect(0, height - 3, width, 3);
  ctx.fillStyle = "#f97316";
  ctx.fillRect(0, height - 3, width * progressRatio, 3);

  ctx.restore();
  return canvas;
}

/**
 * Menghasilkan berkas animasi GIF menggunakan gifenc
 */
export async function exportToGif(options: AnimationExportOptions): Promise<Blob> {
  const {
    mapContainer,
    totalFrames,
    stepToFrame,
    getOverlayInfo,
    delayMs = 300,
    onProgress,
    signal
  } = options;

  const gif = GIFEncoder();
  const workCanvas = document.createElement("canvas");

  for (let i = 0; i < totalFrames; i++) {
    if (signal?.aborted) {
      throw new DOMException("Proses dibatalkan oleh pengguna", "AbortError");
    }

    if (onProgress) {
      onProgress(i + 1, totalFrames, `Merender frame ${i + 1} dari ${totalFrames}...`);
    }

    // Ubah posisi waktu peta
    await stepToFrame(i);
    // Beri jeda kecil agar Leaflet menyelesaikan render canvas
    await new Promise((resolve) => setTimeout(resolve, 60));

    const overlay = getOverlayInfo(i);
    captureMapFrame(mapContainer, overlay, workCanvas);

    const ctx = workCanvas.getContext("2d");
    if (!ctx) continue;

    const imgData = ctx.getImageData(0, 0, workCanvas.width, workCanvas.height);
    // Kuantisasi warna ke palet 256 warna
    const palette = quantize(imgData.data, 256);
    const index = applyPalette(imgData.data, palette);

    gif.writeFrame(index, workCanvas.width, workCanvas.height, {
      palette,
      delay: delayMs
    });
  }

  if (onProgress) {
    onProgress(totalFrames, totalFrames, "Menyusun berkas GIF...");
  }

  gif.finish();
  const bytes = gif.bytes();
  return new Blob([bytes as unknown as BlobPart], { type: "image/gif" });
}

/**
 * Menghasilkan rekaman video menggunakan MediaRecorder kanvas.
 * Memilih MP4/H.264 bila browser mendukung (paling kompatibel dengan
 * WhatsApp & ponsel), jatuh ke WebM VP9/VP8 bila tidak. `blob.type`
 * mengikuti mimeType yang benar-benar dipakai -- pemanggil menentukan
 * ekstensi lewat `extensionForExportBlob()`.
 */
export async function exportToVideo(options: AnimationExportOptions): Promise<Blob> {
  const {
    mapContainer,
    totalFrames,
    stepToFrame,
    getOverlayInfo,
    delayMs = 300,
    onProgress,
    signal
  } = options;

  const mapRect = mapContainer.getBoundingClientRect();
  const width = evenFloor(Math.max(320, mapRect.width));
  const height = evenFloor(Math.max(240, mapRect.height));

  const streamCanvas = document.createElement("canvas");
  streamCanvas.width = width;
  streamCanvas.height = height;
  // Konteks perlu disentuh sekali supaya track kanvas punya frame awal.
  streamCanvas.getContext("2d");

  const fps = 30;
  const stream = streamCanvas.captureStream(fps);
  const track = stream.getVideoTracks()[0] as CanvasCaptureMediaStreamTrack | undefined;

  const mimeType = pickVideoMimeType();
  const isMp4 = mimeType.startsWith("video/mp4");

  const recordedChunks: Blob[] = [];
  const recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 6_000_000 });
  recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) {
      recordedChunks.push(e.data);
    }
  };

  recorder.start(200);

  try {
    for (let i = 0; i < totalFrames; i++) {
      if (signal?.aborted) {
        recorder.stop();
        throw new DOMException("Proses dibatalkan oleh pengguna", "AbortError");
      }

      if (onProgress) {
        onProgress(i + 1, totalFrames, `Merekam frame ${i + 1} dari ${totalFrames}...`);
      }

      await stepToFrame(i);
      await new Promise((resolve) => setTimeout(resolve, 60));

      const overlay = getOverlayInfo(i);
      captureMapFrame(mapContainer, overlay, streamCanvas);
      // Paksa track kanvas mengambil frame ini (kalau didukung) supaya
      // durasi video tidak bergantung pada timing auto-capture browser.
      track?.requestFrame?.();

      // Tahan frame selama durasi yang dipilih
      await new Promise((resolve) => setTimeout(resolve, Math.max(100, delayMs)));
    }
  } finally {
    if (recorder.state !== "inactive") {
      recorder.stop();
    }
  }

  if (onProgress) {
    onProgress(totalFrames, totalFrames, "Menyusun berkas video...");
  }

  await new Promise((resolve) => {
    recorder.onstop = () => resolve(null);
  });

  return new Blob(recordedChunks, { type: isMp4 ? "video/mp4" : "video/webm" });
}

/**
 * Memicu pengunduhan berkas Blob di browser pengguna
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
