import { describe, expect, it, vi } from "vitest";
import { captureMapFrame, type OverlayInfo } from "../lib/exportAnimation";

describe("captureMapFrame", () => {
  it("renders KPS title, location subtitle, and dateRangeLabel onto canvas context", () => {
    const dummyContainer = document.createElement("div");
    Object.defineProperty(dummyContainer, "getBoundingClientRect", {
      value: () => ({ width: 800, height: 600, top: 0, left: 0 })
    });

    const overlay: OverlayInfo = {
      title: "LPHD Tumbang Runen",
      subtitle: "Parupuk, Kamipang, Katingan • Luas: 4,556 Ha",
      dateRangeLabel: "01 Sep 2026 s/d 07 Sep 2026 (WIB)",
      timeLabel: "06 Sep 2026, 20:00 WIB",
      activeCount: 14,
      insideCount: 10,
      outsideCount: 4,
      bufferKm: 5,
      frameIndex: 5,
      totalFrames: 10
    };

    const targetCanvas = document.createElement("canvas");
    const fillTextCalls: string[] = [];
    const mockCtx = {
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 1,
      font: "",
      fillRect: vi.fn(),
      beginPath: vi.fn(),
      roundRect: vi.fn(),
      fill: vi.fn(),
      stroke: vi.fn(),
      arc: vi.fn(),
      save: vi.fn(),
      restore: vi.fn(),
      drawImage: vi.fn(),
      measureText: vi.fn().mockReturnValue({ width: 100 }),
      fillText: vi.fn((text: string) => {
        fillTextCalls.push(text);
      })
    };

    vi.spyOn(targetCanvas, "getContext").mockReturnValue(mockCtx as unknown as CanvasRenderingContext2D);

    const result = captureMapFrame(dummyContainer, overlay, targetCanvas);
    expect(result).toBe(targetCanvas);
    expect(mockCtx.fillRect).toHaveBeenCalledWith(0, 0, 800, 600);

    // Verifikasi bahwa nama KPS, tag, dan rentang waktu digambar ke kanvas
    expect(fillTextCalls).toContain("KPS / PERHUTANAN SOSIAL");
    expect(fillTextCalls.some((t) => t.includes("LPHD Tumbang Runen"))).toBe(true);
    expect(fillTextCalls.some((t) => t.includes("01 Sep 2026 s/d 07 Sep 2026 (WIB)"))).toBe(true);
    expect(fillTextCalls.some((t) => t.includes("14 Titik"))).toBe(true);
  });
});
