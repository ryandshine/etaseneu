// Side-effect: mendaftarkan handler smoothWheelZoom ke L.Map sebelum peta
// mana pun dibuat.
import "../lib/leaflet-smooth-wheel-zoom";

/**
 * Opsi zoom Leaflet yang dipakai SAMA di semua peta (Live Map, Detail KPS,
 * Kompleks Kebakaran) supaya rasa zoom konsisten.
 *
 * - `scrollWheelZoom: false` + `smoothWheelZoom`: matikan zoom-per-langkah
 *   bawaan, ganti dengan zoom kontinu mengikuti kecepatan scroll/trackpad
 *   (lib/leaflet-smooth-wheel-zoom.ts).
 * - `zoomSnap 0.25` / `zoomDelta 0.5`: pinch, tombol +/-, dan fitBounds
 *   menempel di kelipatan seperempat level, bukan lompat penuh 1 level.
 */
export const SMOOTH_ZOOM_MAP_PROPS = {
  scrollWheelZoom: false,
  smoothWheelZoom: true,
  smoothSensitivity: 1,
  zoomSnap: 0.25,
  zoomDelta: 0.5,
} as const;
