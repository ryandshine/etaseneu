import type { DashboardHotspot } from "../types/api";

export function hotspotToGeoJsonFeature(hotspot: DashboardHotspot) {
  return {
    type: "Feature" as const,
    geometry: {
      type: "Point" as const,
      coordinates: [hotspot.longitude, hotspot.latitude]
    },
    properties: {
      id: hotspot.id,
      detected_at: hotspot.detectedAt,
      layer_name: hotspot.layerName,
      agency_name: hotspot.agencyName,
      province_name: hotspot.provinceName,
      source: hotspot.source,
      satellite: hotspot.satellite,
      brightness: hotspot.brightness,
      frp: hotspot.frp,
      confidence: hotspot.confidence,
      daynight: hotspot.daynight,
      ...hotspot.polygonMetadata
    }
  };
}

// polygon_metadata_id bisa saja belum ke-link ke sebagian titik dalam satu
// grup KPS (spatial join belum lengkap) -- cari dari titik manapun yang
// sudah punya ID valid, bukan cuma yang pertama, biar boundary polygon tetap
// bisa disertakan selama ADA satu titik yang tertaut.
export function findLinkedPolygonId(hotspots: DashboardHotspot[]): number | null {
  for (const hotspot of hotspots) {
    const raw = hotspot.polygonMetadata.polygon_metadata_id;
    const parsed = raw ? Number(raw) : NaN;
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

export function downloadGeoJson(featureCollection: object, filename: string) {
  const blob = new Blob([JSON.stringify(featureCollection, null, 2)], {
    type: "application/geo+json"
  });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 100);
}

export function slugifyFilename(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}
