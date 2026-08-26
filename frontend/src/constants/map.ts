/**
 * Opsi zoom Leaflet yang dipakai SAMA di semua peta (Live Map, Detail KPS,
 * Kompleks Kebakaran) supaya rasa zoom konsisten.
 *
 * Default Leaflet (`zoomSnap: 1`) mengunci tiap gerakan scroll/pinch ke level
 * zoom bulat dengan animasi penuh -- terasa nge-jump & berat. Setelan di bawah
 * membuat zoom menempel di kelipatan 0.25 level, tiap tik scroll setengah
 * level, dan butuh jarak scroll lebih panjang per level -> gerakannya halus
 * dan mudah dikontrol, di mouse maupun trackpad/touch.
 */
export const SMOOTH_ZOOM_MAP_PROPS = {
  scrollWheelZoom: true,
  zoomSnap: 0.25,
  zoomDelta: 0.5,
  wheelPxPerZoomLevel: 100,
  wheelDebounceTime: 15,
} as const;
