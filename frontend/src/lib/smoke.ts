// Fungsi murni untuk lapisan asap (citra satelit GIBS + prakiraan PM2.5 CAMS).
// Sengaja tanpa Leaflet/React supaya bisa diuji langsung; komponennya ada di
// components/SmokeLayers.tsx dan components/SmokeControl.tsx.

// --- Kategori PM2.5 (ambang BMKG, µg/m³) ------------------------------------
// Sumber ambang: halaman "Konsentrasi Partikulat (PM2.5)" BMKG -- Baik 0-15,5;
// Sedang 15,6-55,4; Tidak Sehat 55,5-150,4; Sangat Tidak Sehat 150,5-250,4;
// Berbahaya >250,4.
export type Pm25Category = "baik" | "sedang" | "tidak_sehat" | "sangat_tidak_sehat" | "berbahaya";

export const PM25_LEGEND: ReadonlyArray<{
  key: Pm25Category;
  label: string;
  range: string;
  color: string;
}> = [
  { key: "baik", label: "Baik", range: "0-15,5", color: "#22c55e" },
  { key: "sedang", label: "Sedang", range: "15,6-55,4", color: "#facc15" },
  { key: "tidak_sehat", label: "Tidak sehat", range: "55,5-150,4", color: "#f97316" },
  { key: "sangat_tidak_sehat", label: "Sangat tidak sehat", range: "150,5-250,4", color: "#dc2626" },
  { key: "berbahaya", label: "Berbahaya", range: ">250,4", color: "#7e22ce" },
];

export function pm25Category(value: number): Pm25Category {
  if (value <= 15.5) return "baik";
  if (value <= 55.4) return "sedang";
  if (value <= 150.4) return "tidak_sehat";
  if (value <= 250.4) return "sangat_tidak_sehat";
  return "berbahaya";
}

// Peta warna kontinu (interpolasi antar titik henti) supaya gradasi halus, bukan
// blok per kategori. Alpha 0 untuk udara bersih: peta di bawahnya tetap terbaca.
const PM25_STOPS: ReadonlyArray<readonly [number, number, number, number, number]> = [
  [0, 34, 197, 94, 0],
  [15.5, 34, 197, 94, 0],
  [35, 250, 204, 21, 80],
  [55.5, 249, 115, 22, 120],
  [150.5, 220, 38, 38, 165],
  [250.5, 126, 34, 206, 200],
  [400, 88, 28, 135, 225],
];

export function pm25Rgba(value: number): [number, number, number, number] {
  const last = PM25_STOPS[PM25_STOPS.length - 1];
  if (!(value > 0)) return [PM25_STOPS[0][1], PM25_STOPS[0][2], PM25_STOPS[0][3], 0];
  if (value >= last[0]) return [last[1], last[2], last[3], last[4]];
  for (let i = 1; i < PM25_STOPS.length; i++) {
    const [v1, r1, g1, b1, a1] = PM25_STOPS[i];
    if (value <= v1) {
      const [v0, r0, g0, b0, a0] = PM25_STOPS[i - 1];
      const t = v1 === v0 ? 1 : (value - v0) / (v1 - v0);
      return [
        Math.round(r0 + (r1 - r0) * t),
        Math.round(g0 + (g1 - g0) * t),
        Math.round(b0 + (b1 - b0) * t),
        Math.round(a0 + (a1 - a0) * t),
      ];
    }
  }
  return [last[1], last[2], last[3], last[4]];
}

// --- Citra satelit (NASA GIBS lewat proxy backend) ---------------------------
export const DEFAULT_SMOKE_IMAGERY_LAYER = "VIIRS_SNPP_CorrectedReflectance_TrueColor";
export type SmokeImageryDay = "today" | "yesterday";

// Hari GIBS = hari UTC (bukan WIB), jadi tanggal diturunkan dari UTC.
export function smokeImageryDate(day: SmokeImageryDay, now: Date = new Date()): string {
  const shifted = new Date(now.getTime() - (day === "yesterday" ? 24 * 3600 * 1000 : 0));
  return shifted.toISOString().slice(0, 10);
}

// Selalu lewat proxy backend kita (cache bersama semua pengguna), tidak pernah
// langsung ke server NASA dari browser -- pola sama dengan KawasanHutanLayer.
export function smokeImageryUrlTemplate(date: string, layer: string = DEFAULT_SMOKE_IMAGERY_LAYER): string {
  return `/api/smoke/imagery/${layer}/${date}/{z}/{x}/{y}`;
}

// --- Prakiraan PM2.5 ---------------------------------------------------------
export const PM25_OFFSETS = [0, 12, 24, 48] as const;
export type Pm25Offset = (typeof PM25_OFFSETS)[number];

export type Pm25Header = {
  lo1: number;
  la1: number;
  dx: number;
  dy: number;
  nx: number;
  ny: number;
  valid_time?: string;
  offset_hours?: number;
  source?: string;
};

export type Pm25Grid = { header: Pm25Header; data: number[] };

const DAY_NAMES = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"];
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];

// "2026-09-20T12:00" (sudah WIB dari backend) -> "Min, 20 Sep 12.00 WIB".
export function formatSmokeValidTime(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return iso;
  const [, y, m, d, hh, mm] = match;
  const weekday = DAY_NAMES[new Date(Date.UTC(Number(y), Number(m) - 1, Number(d))).getUTCDay()];
  return `${weekday}, ${Number(d)} ${MONTH_NAMES[Number(m) - 1]} ${hh}.${mm} WIB`;
}

export type RasterizedPm25 = {
  width: number;
  height: number;
  data: Uint8ClampedArray;
  // [[selatan, barat], [utara, timur]] -- format `bounds` L.imageOverlay.
  bounds: [[number, number], [number, number]];
};

const toRad = (deg: number) => (deg * Math.PI) / 180;
const mercatorY = (latDeg: number) => Math.log(Math.tan(Math.PI / 4 + toRad(latDeg) / 2));

/**
 * Ubah grid PM2.5 (titik sampel jarang) jadi gambar RGBA yang halus lewat
 * interpolasi bilinear. Baris gambar dihitung di ruang Mercator (bukan linear
 * di lintang) supaya pas menimpa peta Web Mercator Leaflet. Nilai kosong /
 * NaN dianggap udara bersih (transparan).
 */
export function rasterizePm25(grid: Pm25Grid, options: { pxPerCell?: number } = {}): RasterizedPm25 {
  const { lo1, la1, dx, dy, nx, ny } = grid.header;
  const pxPerCell = options.pxPerCell ?? 6;

  const west = lo1;
  const east = lo1 + (nx - 1) * dx;
  const north = la1;
  const south = la1 - (ny - 1) * dy;

  const width = Math.max(1, (nx - 1) * pxPerCell);
  const mercSpan = mercatorY(north) - mercatorY(south);
  const lonSpan = toRad(east - west);
  const height = Math.max(1, Math.round((width * mercSpan) / lonSpan));

  const value = (row: number, col: number): number => {
    const v = grid.data[row * nx + col];
    return Number.isFinite(v) ? v : 0;
  };

  const out = new Uint8ClampedArray(width * height * 4);
  const yNorth = mercatorY(north);

  for (let j = 0; j < height; j++) {
    const lat = ((2 * Math.atan(Math.exp(yNorth - ((j + 0.5) / height) * mercSpan)) - Math.PI / 2) * 180) / Math.PI;
    const rowF = Math.min(Math.max((la1 - lat) / dy, 0), ny - 1);
    const r0 = Math.floor(rowF);
    const r1 = Math.min(r0 + 1, ny - 1);
    const tr = rowF - r0;

    for (let i = 0; i < width; i++) {
      const colF = Math.min(Math.max(((i + 0.5) / width) * (nx - 1), 0), nx - 1);
      const c0 = Math.floor(colF);
      const c1 = Math.min(c0 + 1, nx - 1);
      const tc = colF - c0;

      const top = value(r0, c0) * (1 - tc) + value(r0, c1) * tc;
      const bottom = value(r1, c0) * (1 - tc) + value(r1, c1) * tc;
      const [r, g, b, a] = pm25Rgba(top * (1 - tr) + bottom * tr);

      const p = (j * width + i) * 4;
      out[p] = r;
      out[p + 1] = g;
      out[p + 2] = b;
      out[p + 3] = a;
    }
  }

  return {
    width,
    height,
    data: out,
    bounds: [
      [south, west],
      [north, east],
    ],
  };
}
