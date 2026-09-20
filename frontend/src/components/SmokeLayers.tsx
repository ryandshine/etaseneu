import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";

import type { Pm25Info, SmokeLayersState } from "../hooks/useSmokeLayers";
import { authFetch } from "../lib/api";
import {
  type Pm25Grid,
  type Pm25Offset,
  type SmokeImageryDay,
  rasterizePm25,
  smokeImageryDate,
  smokeImageryUrlTemplate,
} from "../lib/smoke";

// Pane sendiri, DI BAWAH batas KPS (400) & fungsi kawasan hutan (360) tapi di
// atas basemap (tilePane 200): asap tampil sebagai latar, poligon KPS dan titik
// hotspot tetap di atasnya dan tetap bisa diklik. pointer-events:none supaya
// klik menembus ke peta/poligon di bawah-atasnya.
const IMAGERY_PANE = "smoke-imagery";
const PM25_PANE = "smoke-pm25";

function ensurePane(map: L.Map, name: string, zIndex: number): string {
  const pane = map.getPane(name) ?? map.createPane(name);
  pane.style.zIndex = String(zIndex);
  pane.style.pointerEvents = "none";
  return name;
}

/**
 * Citra satelit asap: true color VIIRS dari NASA GIBS. Diambil lewat proxy
 * backend (`/api/smoke/imagery/...`) yang meng-cache ubin -- semua pengguna
 * berbagi cache dan browser tidak pernah menembak server NASA langsung.
 *
 * "Hari ini" ditumpuk DI ATAS citra kemarin. Citra harian GIBS baru terisi
 * seiring satelit lewat: siang hari WIB, Indonesia sering belum terekam hari
 * itu (yang sudah hanya sebuah jalur sempit). Backend mengubah piksel tanpa
 * data jadi transparan, sehingga celahnya menampilkan citra kemarin alih-alih
 * peta kosong. Memilih "Kemarin" secara eksplisit hanya menampilkan kemarin.
 */
function SmokeImageryLayer({ day }: { day: SmokeImageryDay }) {
  const map = useMap();

  useEffect(() => {
    const pane = ensurePane(map, IMAGERY_PANE, 250);
    const days: SmokeImageryDay[] = day === "today" ? ["yesterday", "today"] : ["yesterday"];
    const layers = days.map((d, index) =>
      L.tileLayer(smokeImageryUrlTemplate(smokeImageryDate(d)), {
        pane,
        zIndex: index + 1, // yang lebih baru di atas
        opacity: 0.85,
        maxNativeZoom: 9, // batas TileMatrixSet GIBS Level9; di atasnya diperbesar
        maxZoom: 20,
        attribution: "Citra &copy; NASA GIBS / VIIRS",
        // Citra bisa belum ada untuk hari ini: jangan blokir render peta.
        updateWhenIdle: true,
        updateWhenZooming: false,
        keepBuffer: 1,
      }),
    );
    layers.forEach((layer) => layer.addTo(map));
    return () => {
      layers.forEach((layer) => map.removeLayer(layer));
    };
  }, [map, day]);

  return null;
}

/**
 * Prakiraan PM2.5 (CAMS via backend): grid jarang -> gambar halus (interpolasi
 * bilinear di ruang Mercator) yang ditimpakan sebagai `L.imageOverlay`.
 */
function Pm25Overlay({ offset, onInfo }: { offset: Pm25Offset; onInfo: (info: Pm25Info) => void }) {
  const map = useMap();

  useEffect(() => {
    let active = true;
    let overlay: L.ImageOverlay | null = null;
    onInfo({ status: "loading" });

    authFetch(`/api/smoke/pm25?offset_hours=${offset}`)
      .then((res) => {
        if (!res.ok) throw new Error(`PM2.5 ${res.status}`);
        return res.json() as Promise<Pm25Grid>;
      })
      .then((grid) => {
        if (!active) return;
        const image = rasterizePm25(grid, { pxPerCell: 6 });
        const canvas = document.createElement("canvas");
        canvas.width = image.width;
        canvas.height = image.height;
        const ctx = canvas.getContext("2d");
        if (!ctx) throw new Error("Canvas 2D tidak tersedia");
        const imageData = ctx.createImageData(image.width, image.height);
        imageData.data.set(image.data);
        ctx.putImageData(imageData, 0, 0);

        const pane = ensurePane(map, PM25_PANE, 260);
        overlay = L.imageOverlay(canvas.toDataURL("image/png"), image.bounds, {
          pane,
          interactive: false,
          opacity: 1,
        }).addTo(map);
        onInfo({ status: "ready", validTime: grid.header.valid_time });
      })
      .catch(() => {
        if (active) onInfo({ status: "error" });
      });

    return () => {
      active = false;
      if (overlay) map.removeLayer(overlay);
    };
  }, [map, offset, onInfo]);

  return null;
}

/**
 * Lapisan sisi-peta untuk satu peta: taruh DI DALAM <MapContainer>, berpasangan
 * dengan <SmokeControl> di luarnya. Lapisan yang mati tidak dirender sama
 * sekali -- tidak ada beban jaringan/CPU sebelum pengguna menyalakannya.
 */
export function SmokeMapLayers({ smoke }: { smoke: SmokeLayersState }) {
  return (
    <>
      {smoke.imagery ? <SmokeImageryLayer day={smoke.imageryDay} /> : null}
      {smoke.pm25 ? <Pm25Overlay offset={smoke.pm25Offset} onInfo={smoke.setPm25Info} /> : null}
    </>
  );
}
