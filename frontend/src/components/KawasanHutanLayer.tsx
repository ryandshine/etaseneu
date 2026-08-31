import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import { KAWASAN_HUTAN_MAPSERVER } from "../constants/kawasanHutan";

// Layanan ArcGIS KWSHUTAN_AR_250K TIDAK punya cache tile (singleFusedMapCache
// false) dan tanpa WMSServer -- jadi tiap tile diminta lewat endpoint `export`
// dinamis. Pola bbox-per-tile ini persis yang dipakai L.TileLayer.WMS di dalam
// Leaflet: hitung bbox tiap tile di EPSG:3857 lalu minta gambar seukuran tile.
const ArcgisExportTileLayer = L.TileLayer.extend({
  getTileUrl(coords: L.Coords): string {
    const map = (this as unknown as { _map: L.Map })._map;
    const size = (this as unknown as { getTileSize: () => L.Point }).getTileSize();
    const nwPixel = L.point(coords.x * size.x, coords.y * size.y);
    const sePixel = L.point(nwPixel.x + size.x, nwPixel.y + size.y);
    const nw = map.unproject(nwPixel, coords.z);
    const se = map.unproject(sePixel, coords.z);
    const min = L.CRS.EPSG3857.project(L.latLng(se.lat, nw.lng));
    const max = L.CRS.EPSG3857.project(L.latLng(nw.lat, se.lng));
    const bbox = [min.x, min.y, max.x, max.y].join(",");
    const params = new URLSearchParams({
      bbox,
      bboxSR: "3857",
      imageSR: "3857",
      size: `${size.x},${size.y}`,
      dpi: "96",
      format: "png32",
      transparent: "true",
      f: "image",
    });
    return `${KAWASAN_HUTAN_MAPSERVER}/export?${params.toString()}`;
  },
});

/**
 * Overlay fungsi kawasan hutan (KWSHUTAN_AR_250K) diambil LIVE dari layanan
 * ArcGIS resmi Ditjen Planologi Kehutanan. Tidak ada berkas geojson yang
 * di-bundle; simbol & warna dirender oleh server itu. Dipasang di pane
 * `kawasan-hutan` (z360) supaya berada di bawah batas KPS.
 */
export function KawasanHutanLayer({ opacity = 0.6 }: { opacity?: number }) {
  const map = useMap();

  useEffect(() => {
    if (!map.getPane("kawasan-hutan")) {
      const pane = map.createPane("kawasan-hutan");
      pane.style.zIndex = "360";
    }
    const layer = new (ArcgisExportTileLayer as unknown as new (
      url: string,
      opts: L.TileLayerOptions,
    ) => L.TileLayer)("", {
      opacity,
      pane: "kawasan-hutan",
      // Layanan pemerintah bisa lambat -- jangan blokir render peta.
      updateWhenIdle: true,
      updateWhenZooming: false,
      keepBuffer: 1,
      maxNativeZoom: 15,
    });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, opacity]);

  return null;
}
