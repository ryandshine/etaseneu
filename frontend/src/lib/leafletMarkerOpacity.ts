import type { CircleMarker as LCircleMarker, Marker as LMarker } from "leaflet";

export type HotspotMarkerLayer = LCircleMarker | LMarker;

/**
 * Terapkan opacity hasil `opacityForBucket` (lib/hotspotTimeline.ts) ke satu
 * marker Leaflet -- dipakai bareng HotspotMap.tsx (peta utama) dan
 * KpsDetailView.tsx (peta Detail KPS), jadi diekstrak ke sini supaya
 * keduanya tidak diam-diam menyimpang kalau salah satu diubah.
 *
 * `CircleMarker` (titik biasa) pakai `setStyle` fillOpacity/opacity;
 * `Marker` (ikon FRP tinggi, dipakai HotspotMap tapi tidak dipakai
 * KpsDetailView) pakai `setOpacity`. Titik "masa depan" (opacity 0) dibuat
 * non-interaktif supaya tidak menelan klik peta.
 */
export function applyMarkerOpacity(layer: HotspotMarkerLayer, o: number): void {
  const cm = layer as LCircleMarker;
  if (typeof cm.setStyle === "function") {
    cm.setStyle({ fillOpacity: o === 0 ? 0 : o * 0.98, opacity: o === 0 ? 0 : 1 });
    cm.options.interactive = o > 0;
    return;
  }
  const mk = layer as LMarker;
  if (typeof mk.setOpacity === "function") {
    mk.setOpacity(o === 0 ? 0 : 1);
    const el = mk.getElement?.();
    if (el) el.style.pointerEvents = o > 0 ? "" : "none";
  }
}
