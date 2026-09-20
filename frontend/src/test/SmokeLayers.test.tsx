import "@testing-library/jest-dom/vitest";
import { cleanup, render, waitFor } from "@testing-library/react";
import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SmokeMapLayers } from "../components/SmokeLayers";
import type { SmokeLayersState } from "../hooks/useSmokeLayers";
import { smokeImageryDate } from "../lib/smoke";

// Peta Leaflet ASLI (bukan mock): yang diuji justru integrasi dengan Leaflet --
// layer benar-benar terpasang di pane yang tepat dan terlepas saat dimatikan.
let realMap: L.Map;
vi.mock("react-leaflet", () => ({ useMap: () => realMap }));

const authFetchMock = vi.fn();
vi.mock("../lib/api", () => ({ authFetch: (...args: unknown[]) => authFetchMock(...args) }));

const grid = {
  header: { lo1: 100, la1: 2, dx: 1, dy: 1, nx: 2, ny: 2, valid_time: "2026-09-20T12:00", offset_hours: 0 },
  data: [300, 20, 10, 0],
};

function smokeState(overrides: Partial<SmokeLayersState> = {}): SmokeLayersState {
  return {
    imagery: false,
    imageryDay: "today",
    pm25: false,
    pm25Offset: 0,
    pm25Info: { status: "idle" },
    toggleImagery: vi.fn(),
    setImageryDay: vi.fn(),
    togglePm25: vi.fn(),
    setPm25Offset: vi.fn(),
    setPm25Info: vi.fn(),
    ...overrides,
  };
}

function layersOf(map: L.Map) {
  const found: L.Layer[] = [];
  map.eachLayer((layer) => found.push(layer));
  return found;
}

const tileUrls = (map: L.Map) =>
  layersOf(map)
    .map((l) => (l as unknown as { _url?: string })._url)
    .filter((u): u is string => typeof u === "string" && u.includes("/api/smoke/imagery/"));
const overlays = (map: L.Map) => layersOf(map).filter((l) => l instanceof L.ImageOverlay);

beforeEach(() => {
  realMap = L.map(document.createElement("div")).setView([-2, 110], 6);
  authFetchMock.mockReset();
  // jsdom tidak punya canvas 2D: sediakan yang minimal supaya jalur render jalan.
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    () =>
      ({
        createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
        putImageData: vi.fn(),
      }) as unknown as CanvasRenderingContext2D,
  );
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,AAAA");
});

afterEach(() => {
  cleanup();
  realMap.remove();
  vi.restoreAllMocks();
});

describe("SmokeMapLayers", () => {
  it("adds nothing to the map while every smoke layer is off", () => {
    const before = layersOf(realMap).length;
    render(<SmokeMapLayers smoke={smokeState()} />);
    expect(layersOf(realMap).length).toBe(before);
    expect(authFetchMock).not.toHaveBeenCalled(); // mati = tidak ada beban jaringan sama sekali
  });

  it("adds the satellite imagery tiles through OUR proxy, for the chosen UTC day", () => {
    const { rerender } = render(<SmokeMapLayers smoke={smokeState({ imagery: true, imageryDay: "yesterday" })} />);
    const yesterday = smokeImageryDate("yesterday");
    expect(tileUrls(realMap)).toEqual([expect.stringContaining(`/${yesterday}/{z}/{x}/{y}`)]);
    expect(tileUrls(realMap)[0].startsWith("/api/smoke/imagery/")).toBe(true);
    expect(tileUrls(realMap).every((u) => !u.startsWith("http"))).toBe(true); // tak pernah langsung ke NASA

    rerender(<SmokeMapLayers smoke={smokeState({ imagery: true, imageryDay: "today" })} />);
    expect(tileUrls(realMap).length).toBeGreaterThan(0);
  });

  it("stacks TODAY on top of yesterday, so gaps not yet recorded today show yesterday's imagery", () => {
    // Kasus nyata 2026-09-20 siang: citra hari ini belum merekam Indonesia. Tanpa
    // lapisan kemarin di bawahnya, Indonesia tampak kosong (hanya sebuah jalur
    // sempit di Pasifik yang sudah terekam).
    render(<SmokeMapLayers smoke={smokeState({ imagery: true, imageryDay: "today" })} />);
    const today = smokeImageryDate("today");
    const yesterday = smokeImageryDate("yesterday");

    const tiles = layersOf(realMap).filter(
      (l) => typeof (l as unknown as { _url?: string })._url === "string" && (l as unknown as { _url: string })._url.includes("/api/smoke/imagery/"),
    ) as unknown as Array<{ _url: string; options: { zIndex: number } }>;

    expect(tiles.map((t) => t._url.split("/")[5])).toEqual([yesterday, today]);
    const [under, over] = tiles;
    expect(over.options.zIndex).toBeGreaterThan(under.options.zIndex);
  });

  it("does not add a second layer when the user explicitly picks yesterday", () => {
    render(<SmokeMapLayers smoke={smokeState({ imagery: true, imageryDay: "yesterday" })} />);
    expect(tileUrls(realMap)).toHaveLength(1);
  });

  it("puts imagery in its own non-interactive pane so clicks still reach KPS polygons", () => {
    render(<SmokeMapLayers smoke={smokeState({ imagery: true })} />);
    const pane = realMap.getPane("smoke-imagery");
    expect(pane).toBeTruthy();
    expect(pane!.style.pointerEvents).toBe("none");
  });

  it("removes the imagery layer when switched off", () => {
    const { rerender } = render(<SmokeMapLayers smoke={smokeState({ imagery: true })} />);
    expect(tileUrls(realMap)).toHaveLength(2); // hari ini + kemarin (pengisi celah)
    rerender(<SmokeMapLayers smoke={smokeState({ imagery: false })} />);
    expect(tileUrls(realMap)).toHaveLength(0);
  });

  it("fetches the PM2.5 grid for the chosen forecast hour and draws it as an image overlay", async () => {
    authFetchMock.mockResolvedValue({ ok: true, json: async () => grid });
    const setPm25Info = vi.fn();
    render(<SmokeMapLayers smoke={smokeState({ pm25: true, pm25Offset: 24, setPm25Info })} />);

    await waitFor(() => expect(overlays(realMap)).toHaveLength(1));
    expect(authFetchMock).toHaveBeenCalledWith("/api/smoke/pm25?offset_hours=24");
    expect(setPm25Info).toHaveBeenCalledWith({ status: "loading" });
    expect(setPm25Info).toHaveBeenLastCalledWith({ status: "ready", validTime: "2026-09-20T12:00" });

    const bounds = (overlays(realMap)[0] as L.ImageOverlay).getBounds();
    expect(bounds.getSouth()).toBe(1);
    expect(bounds.getNorth()).toBe(2);
    expect(bounds.getWest()).toBe(100);
    expect(bounds.getEast()).toBe(101);
  });

  it("replaces (not stacks) the overlay when the forecast hour changes, and cleans up on unmount", async () => {
    authFetchMock.mockResolvedValue({ ok: true, json: async () => grid });
    const { rerender, unmount } = render(<SmokeMapLayers smoke={smokeState({ pm25: true, pm25Offset: 0 })} />);
    await waitFor(() => expect(overlays(realMap)).toHaveLength(1));

    rerender(<SmokeMapLayers smoke={smokeState({ pm25: true, pm25Offset: 12 })} />);
    await waitFor(() => expect(authFetchMock).toHaveBeenCalledWith("/api/smoke/pm25?offset_hours=12"));
    await waitFor(() => expect(overlays(realMap)).toHaveLength(1));

    unmount();
    expect(overlays(realMap)).toHaveLength(0);
  });

  it("reports an error instead of throwing when the forecast cannot be loaded", async () => {
    authFetchMock.mockResolvedValue({ ok: false, status: 502, json: async () => ({}) });
    const setPm25Info = vi.fn();
    render(<SmokeMapLayers smoke={smokeState({ pm25: true, setPm25Info })} />);
    await waitFor(() => expect(setPm25Info).toHaveBeenLastCalledWith({ status: "error" }));
    expect(overlays(realMap)).toHaveLength(0);
  });
});
