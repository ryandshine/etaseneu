// Uji titik-dalam-poligon murni JS (ray casting), tanpa dependensi. Dipakai
// penangan klik peta untuk mengetahui poligon KPS/Hutan Adat apa yang ada di
// bawah kursor. Data GeoJSON layer sudah termuat di memori, jadi cukup cepat
// (bbox filter dulu, lalu uji ring).

type Pos = [number, number]; // [lng, lat]

function pointInRing(lng: number, lat: number, ring: Pos[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersect =
      yi > lat !== yj > lat &&
      lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

// coords Polygon: [outerRing, ...holes]
function pointInPolygon(lng: number, lat: number, coords: Pos[][]): boolean {
  if (!coords.length || !pointInRing(lng, lat, coords[0])) return false;
  for (let k = 1; k < coords.length; k++) {
    if (pointInRing(lng, lat, coords[k])) return false; // di dalam lubang
  }
  return true;
}

type Geometry =
  | { type: "Polygon"; coordinates: Pos[][] }
  | { type: "MultiPolygon"; coordinates: Pos[][][] }
  | { type: string; coordinates: unknown };

export function pointInGeometry(lng: number, lat: number, geometry: Geometry): boolean {
  if (!geometry || !geometry.coordinates) return false;
  if (geometry.type === "Polygon") {
    return pointInPolygon(lng, lat, geometry.coordinates as Pos[][]);
  }
  if (geometry.type === "MultiPolygon") {
    for (const poly of geometry.coordinates as Pos[][][]) {
      if (pointInPolygon(lng, lat, poly)) return true;
    }
  }
  return false;
}
