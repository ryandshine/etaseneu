import { useRef } from "react";
import { useMapEvents } from "react-leaflet";
import L from "leaflet";
import { authFetch } from "../lib/api";
import { pointInGeometry } from "../lib/polygonHit";

type LayerLike = {
  id: string;
  name: string;
  label: string;
  active: boolean;
  geojson: Record<string, unknown>;
};

type Props = {
  layers: LayerLike[];
  showKawasan: boolean;
  // Titik hotspot di peta -- kalau tap jatuh dekat salah satunya, popup poligon
  // ini TIDAK ditampilkan (user sedang menyasar titiknya; marker canvas kecil
  // sering lolos di HP). Biar marker yang menangani.
  hotspots?: Array<{ latitude: number; longitude: number }>;
};

const HOTSPOT_GUARD_PX = 30;

type Hit = { layer: string; props: Record<string, unknown> };

function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string),
  );
}

function friendlyLayer(layer: LayerLike): string {
  const n = `${layer.name} ${layer.id}`.toLowerCase();
  if (n.includes("hutan_adat") || n.includes("hutan adat")) return "Hutan Adat";
  if (n.includes("psagustus") || n.startsWith("ps_") || n.includes("perhutanan")) {
    return "Perhutanan Sosial (KPS)";
  }
  return layer.label || layer.name || layer.id;
}

function firstOf(p: Record<string, unknown>, ...keys: string[]): string {
  for (const k of keys) {
    const v = p[k];
    if (v !== undefined && v !== null && String(v).trim() !== "") return String(v);
  }
  return "";
}

function renderPopup(hits: Hit[]): string {
  const blocks = hits
    .slice(0, 4)
    .map((h) => {
      const p = h.props;
      const nama = esc(firstOf(p, "LEMBAGA", "lembaga", "label") || "-");
      const rows: string[] = [];
      const skema = firstOf(p, "SKEMA", "skema");
      if (skema) rows.push(`Skema: <strong>${esc(skema)}</strong>`);
      const balai = firstOf(p, "WILKER_BPS");
      if (balai) rows.push(`Balai PS: <strong>${esc(balai)}</strong>`);
      const wil = [firstOf(p, "NAMA_KAB"), firstOf(p, "NAMA_PROV")]
        .filter(Boolean)
        .map(esc)
        .join(", ");
      if (wil) rows.push(`Wilayah: <strong>${wil}</strong>`);
      return `<div style="margin-top:8px">
        <div style="font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#6b7280">${esc(h.layer)}</div>
        <div style="font-weight:700;margin-top:2px">${nama}</div>
        ${rows.length ? `<div style="margin-top:3px;color:#374151;line-height:1.5">${rows.join("<br>")}</div>` : ""}
      </div>`;
    })
    .join("");
  return `<div style="font-size:12px;font-family:sans-serif;min-width:210px">
    <strong style="color:#1b3a2b">Poligon di titik ini</strong>${blocks}</div>`;
}

function kawasanBlock(k: {
  fungsi?: string;
  singkatan?: string;
  kelompok?: string;
  nama_kawasan?: string;
}): string {
  const judul = [k.fungsi, k.singkatan ? `(${k.singkatan})` : ""].filter(Boolean).map(esc).join(" ");
  const sub = [k.kelompok, k.nama_kawasan].filter(Boolean).map(esc).join(" · ");
  return `<div style="margin-top:8px;border-top:1px solid #e5e7eb;padding-top:6px">
    <div style="font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#6b7280">Fungsi Kawasan Hutan</div>
    <div style="font-weight:700;margin-top:2px">${judul || "-"}</div>
    ${sub ? `<div style="margin-top:2px;color:#374151">${sub}</div>` : ""}
  </div>`;
}

/**
 * Menangkap klik di area kosong peta (di luar titik hotspot / poligon bekas
 * terbakar yang sudah punya popup sendiri) lalu menampilkan popup berisi
 * poligon KPS/Hutan Adat di titik itu -- karena lapisan batas sengaja
 * non-interaktif (lihat catatan pane `batas-kps` di HotspotMap). Bila overlay
 * Fungsi Kawasan Hutan menyala, fungsi kawasan di titik itu ikut ditambahkan.
 */
export function PolygonInfoLayer({ layers, showKawasan, hotspots }: Props) {
  const popupRef = useRef<L.Popup | null>(null);

  const map = useMapEvents({
    click(e) {
      const { lat, lng } = e.latlng;

      // Tap dekat titik hotspot -> jangan tampilkan popup poligon. Uji-klik
      // canvas untuk titik 7px sering meleset di HP dan event-nya lolos ke sini;
      // menampilkan popup poligon di situ bikin user mengira klik titik "rusak".
      if (hotspots && hotspots.length > 0) {
        const clickPt = map.latLngToContainerPoint(e.latlng);
        const nearHotspot = hotspots.some(
          (h) =>
            clickPt.distanceTo(map.latLngToContainerPoint([h.latitude, h.longitude])) <=
            HOTSPOT_GUARD_PX,
        );
        if (nearHotspot) {
          popupRef.current?.close();
          popupRef.current = null;
          return;
        }
      }

      const hits: Hit[] = [];
      for (const layer of layers) {
        if (!layer.active) continue;
        const features = (layer.geojson as { features?: unknown[] })?.features;
        if (!Array.isArray(features)) continue;
        for (const f of features as { geometry?: never; properties?: Record<string, unknown> }[]) {
          if (f?.geometry && pointInGeometry(lng, lat, f.geometry)) {
            hits.push({ layer: friendlyLayer(layer), props: f.properties ?? {} });
            break; // satu poligon per layer sudah cukup untuk "layer apa"
          }
        }
      }

      if (hits.length === 0) {
        popupRef.current?.close();
        popupRef.current = null;
        return;
      }

      const baseHtml = renderPopup(hits);
      const popup = L.popup({ pane: "popupPane", maxWidth: 300, className: "poly-info-popup" })
        .setLatLng(e.latlng)
        .setContent(baseHtml)
        .openOn(map);
      popupRef.current = popup;

      if (showKawasan) {
        authFetch(`/api/burned-area/kawasan-at?lat=${lat}&lon=${lng}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((j) => {
            const k = j?.kawasan;
            if (k && popupRef.current === popup) {
              popup.setContent(baseHtml + kawasanBlock(k));
            }
          })
          .catch(() => {
            /* pelengkap -- diamkan */
          });
      }
    },
  });

  return null;
}
