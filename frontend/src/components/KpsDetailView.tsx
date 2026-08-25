import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Download } from "lucide-react";
import { CircleMarker, GeoJSON, LayerGroup, MapContainer, Pane, Popup, TileLayer, useMap } from "react-leaflet";
import { circleMarker as buildLeafletCircleMarker, geoJSON as buildLeafletGeoJSON } from "leaflet";
import type { LayerGroup as LLayerGroup } from "leaflet";

import { SATELLITE_OPTIONS } from "../constants/satellites";
import { TIME_PRESET_OPTIONS } from "../constants/time-windows";
import type { DashboardHotspot } from "../hooks/useDashboardData";
import { createApiClient } from "../lib/api";
import { getTodayWIB } from "../lib/date";
import type { PolygonDetail } from "../types/api";
import { HotspotPopupContent } from "./HotspotPopupContent";
import { WeatherConditionCard } from "./WeatherConditionCard";
import {
  buildComparison,
  formatMetadataValue,
  formatNumber,
  formatTimestamp,
  getFrpCategory,
  getStatusLabel,
  mapHotspotRecordToDashboardHotspot,
  normalizeFrpCategoryLabel
} from "../lib/hotspotDisplay";

const api = createApiClient();

const DETECTION_PAGE_SIZE = 10;

const MONTH_LABELS = [
  "Januari", "Februari", "Maret", "April", "Mei", "Juni",
  "Juli", "Agustus", "September", "Oktober", "November", "Desember"
];

type BurnedAreaRow = {
  polygon_metadata_id: number;
  layer_key: string;
  year: number;
  month: number;
  burned_area_ha: number;
  source: string;
};

type BurnedAreaFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: Record<string, unknown>;
    properties: { year: number; month: number; burned_area_ha: number; is_estimated: boolean };
  }>;
};

type KpsDetailViewProps = {
  agency: string;
  hotspots: DashboardHotspot[];
  onClose: () => void;
  onExportPdf: (filters: { agency?: string }) => void;
  isExportingPdf: boolean;
};

function sourceColor(source: string): string {
  if (source === "MODIS") {
    return "#ff8c42";
  }
  if (source.startsWith("VIIRS")) {
    return "#facc15";
  }
  return "#ffd7a8";
}

// Batas hari kalender WIB (UTC+7) untuk tanggal "YYYY-MM-DD" dari <input
// type="date">. Dipakai cuma di sini karena inputnya selalu tanggal valid
// (bukan input mengetik-bebas seperti di FilterPanel), jadi tidak perlu
// penjagaan tanggal-tidak-valid seperti `getWibDate` di useDashboardData.ts.
function wibDateBoundaryIso(dateStr: string, endOfDay: boolean): string {
  return new Date(`${dateStr}T${endOfDay ? "23:59:59" : "00:00:00"}+07:00`).toISOString();
}

// Perbandingan "YYYYMM" supaya baris/riwayat KLHK bisa disaring ke rentang
// kustom halaman ini tanpa perlu ubah endpoint backend (datanya kecil per-KPS).
function isPeriodInRange(year: number, month: number, startDate: string, endDate: string): boolean {
  const period = year * 100 + month;
  const [startYear, startMonth] = startDate.split("-").map(Number);
  const [endYear, endMonth] = endDate.split("-").map(Number);
  return period >= startYear * 100 + startMonth && period <= endYear * 100 + endMonth;
}

// Titik tengah (bounding-box midpoint) dari geometry GeoJSON apa pun --
// Point, Polygon, atau MultiPolygon -- dipakai utk tombol "Salin
// koordinat"/"Google Maps" di popup area terbakar. Bukan centroid presisi
// (cukup utk "buka titik ini di peta lain", bukan perhitungan luas).
function geometryCenter(geometry: { type: string; coordinates: unknown }): { lat: number; lon: number } | null {
  const points: Array<[number, number]> = [];

  function collect(coords: unknown): void {
    if (!Array.isArray(coords)) {
      return;
    }
    if (typeof coords[0] === "number" && typeof coords[1] === "number") {
      points.push([coords[0], coords[1]]);
      return;
    }
    coords.forEach(collect);
  }

  collect(geometry?.coordinates);
  if (points.length === 0) {
    return null;
  }

  const lons = points.map((p) => p[0]);
  const lats = points.map((p) => p[1]);
  return {
    lat: (Math.min(...lats) + Math.max(...lats)) / 2,
    lon: (Math.min(...lons) + Math.max(...lons)) / 2
  };
}

// Preset "24 Jam/48 Jam/dst" dari dashboard (constants/time-windows.ts), tanpa
// "Custom" -- di halaman ini field Dari/Ke sendiri SUDAH jadi jalur custom-nya,
// jadi tidak perlu tombol "Custom" terpisah.
const HOTSPOT_DAY_PRESETS = TIME_PRESET_OPTIONS.filter((preset) => preset.value !== "custom");

// Tanggal "YYYY-MM-DD" mundur `days` hari kalender dari tanggal acuan --
// aritmetika tanggal murni (bukan waktu presisi jam), jadi aman dari isu
// DST/offset karena dikerjakan di "tanggal pura-pura UTC", bukan waktu asli.
function subtractDaysFromDateString(dateStr: string, days: number): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  const base = new Date(Date.UTC(year, month - 1, day));
  base.setUTCDate(base.getUTCDate() - days);
  return base.toISOString().slice(0, 10);
}

// Peta polygon detail dimulai dari view Indonesia lalu di-fit ke batas
// polygon setelah geometrinya datang -- fitBounds butuh instance peta, jadi
// harus jadi komponen anak MapContainer sendiri (pola yang sama dengan
// MapViewport di HotspotMap.tsx).
function FitToPolygon({ geometry }: { geometry: Record<string, unknown> }) {
  const map = useMap();

  useEffect(() => {
    try {
      const layer = buildLeafletGeoJSON(geometry as never);
      const bounds = layer.getBounds();
      if (bounds.isValid()) {
        // Ukuran disegarkan dulu: fitBounds menghitung zoom dari ukuran yang
        // Leaflet KIRA dimilikinya, jadi kalau kontainer sudah tumbuh tanpa
        // sepengetahuan Leaflet, hasil fit-nya ikut meleset.
        map.invalidateSize({ animate: false });
        map.fitBounds(bounds, { padding: [32, 32] });
      }
    } catch {
      // Geometry tidak valid -- peta tetap di posisi default, tidak fatal.
    }
  }, [geometry, map]);

  return null;
}

/**
 * Beritahu Leaflet setiap kali kontainernya berubah ukuran.
 *
 * Tinggi peta di halaman ini ditentukan oleh baris grid, yang tingginya
 * mengikuti sidebar kiri -- dan sidebar itu baru terisi setelah data detail
 * tiba dari server. Leaflet mengukur kontainernya sekali saat inisialisasi dan
 * tidak memantau perubahan ukuran, sehingga ia hanya menggambar ubin untuk
 * area lama: peta tampak terpotong dengan area hitam di bawahnya.
 *
 * Sengaja hanya invalidateSize, tanpa fitBounds ulang, supaya posisi dan zoom
 * yang sedang dilihat pengguna tidak tereset setiap kali ada perubahan tata
 * letak (mis. saat jendela diubah ukurannya).
 */
function KeepMapSized() {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    if (typeof ResizeObserver === "undefined") {
      return;
    }

    let frame = 0;
    const observer = new ResizeObserver(() => {
      // Ditunda ke frame berikutnya supaya pengukuran ulang terjadi setelah
      // browser selesai menata ulang, bukan di tengah-tengahnya.
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => map.invalidateSize({ animate: false }));
    });

    observer.observe(container);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [map]);

  return null;
}

const INFO_FIELDS: Array<[label: string, key: keyof PolygonDetail]> = [
  ["Balai PS", "wilker_bps"],
  ["Provinsi", "nama_prov"],
  ["Kabupaten", "nama_kab"],
  ["Kecamatan", "nama_kec"],
  ["Desa", "nama_desa"],
  ["Skema", "skema"],
  ["No. SK", "no_sk"],
  ["Tanggal SK", "tgl_sk"],
  ["Status", "status"],
  ["PS ID", "ps_id"],
  ["Luas Final (Ha)", "luas_final"],
  ["Jumlah KK", "jml_kk"]
];

export function KpsDetailView({ agency, hotspots, onClose, onExportPdf, isExportingPdf }: KpsDetailViewProps) {
  // Filter waktu independen, khusus halaman ini -- kosong (default) berarti
  // "ikuti apa pun rentang dashboard yang aktif" (perilaku lama, tidak
  // berubah). Begitu keduanya terisi, `customHotspots` menggantikan `hotspots`
  // sebagai sumber data (lihat `kpsHotspots` di bawah), dan riwayat KLHK ikut
  // disaring ke rentang yang sama di titik pemakaiannya.
  const [customStartDate, setCustomStartDate] = useState("");
  const [customEndDate, setCustomEndDate] = useState("");
  const [customHotspots, setCustomHotspots] = useState<DashboardHotspot[] | null>(null);
  const [customLoading, setCustomLoading] = useState(false);
  const [customError, setCustomError] = useState<string | null>(null);
  const isCustomRangeActive = Boolean(customStartDate && customEndDate);

  // Isi otomatis Dari/Ke dari preset waktu (24 Jam/48 Jam/dst), berpatokan ke
  // hari ini (WIB) -- klik ulang preset yang sama sesudah mengubah tanggal
  // manual mengembalikannya ke rentang preset itu lagi.
  const applyTimePreset = (hours: number) => {
    const days = Math.max(1, Math.round(hours / 24));
    const today = getTodayWIB();
    setCustomEndDate(today);
    setCustomStartDate(subtractDaysFromDateString(today, days - 1));
  };

  const isTimePresetActive = (hours: number): boolean => {
    if (!customStartDate || !customEndDate) {
      return false;
    }
    const days = Math.max(1, Math.round(hours / 24));
    const today = getTodayWIB();
    return customEndDate === today && customStartDate === subtractDaysFromDateString(today, days - 1);
  };

  // Semua titik hotspot milik KPS ini sudah tersedia dari dataset yang sama
  // dipakai Buku Besar -- tidak perlu endpoint tambahan, tinggal disaring
  // pakai nama KPS (LEMBAGA/agencyName), yang selalu ada di tiap baris
  // (beda dari polygon_metadata_id yang bisa saja belum ke-link).
  const kpsHotspots = useMemo(
    () =>
      (customHotspots ?? hotspots)
        .filter((hotspot) => formatMetadataValue(hotspot.polygonMetadata.LEMBAGA || hotspot.agencyName) === agency)
        .sort((a, b) => new Date(b.detectedAt).getTime() - new Date(a.detectedAt).getTime()),
    [hotspots, customHotspots, agency]
  );

  // Cari ID polygon dari hotspot MANAPUN di grup ini yang sudah ke-link --
  // bukan cuma yang terbaru, supaya satu-dua titik yang belum sempat
  // ke-spatial-join tidak bikin seluruh halaman kehilangan polygon-nya.
  //
  // Sengaja pakai `hotspots` (prop dashboard, tidak disaring rentang
  // kustom), BUKAN `kpsHotspots` -- polygon KPS adalah entitas tetap,
  // resolusinya tidak boleh hilang cuma karena rentang waktu kustom
  // kebetulan tidak berisi titik untuk KPS ini (yang bikin seluruh info
  // panel + riwayat KLHK ikut kosong padahal cuma titik hotspotnya yang nol).
  const polygonId = useMemo(() => {
    for (const hotspot of hotspots) {
      if (formatMetadataValue(hotspot.polygonMetadata.LEMBAGA || hotspot.agencyName) !== agency) {
        continue;
      }
      const raw = hotspot.polygonMetadata.polygon_metadata_id;
      const parsed = raw ? Number(raw) : NaN;
      if (Number.isFinite(parsed)) {
        return parsed;
      }
    }
    return null;
  }, [hotspots, agency]);

  const [detail, setDetail] = useState<PolygonDetail | null>(null);
  const [loading, setLoading] = useState(polygonId !== null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (polygonId === null) {
      setDetail(null);
      setLoading(false);
      setError(null);
      return;
    }

    let active = true;
    setLoading(true);
    setError(null);
    setDetail(null);

    fetch(`/api/polygons/${polygonId}`)
      .then((response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 404
              ? "Polygon KPS ini tidak ditemukan."
              : "Gagal memuat data polygon."
          );
        }
        return response.json() as Promise<PolygonDetail>;
      })
      .then((payload) => {
        if (active) {
          setDetail(payload);
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Gagal memuat data polygon.");
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [polygonId]);

  // Fetch khusus halaman ini untuk rentang kustom -- lepas dari filter waktu
  // dashboard. Discope ke layer dataset KPS ini (`detail.layer_key`, PS atau
  // Hutan Adat) lalu disaring per-agency di `kpsHotspots` di atas, sama
  // seperti cara `hotspots` dari dashboard sudah diperlakukan.
  useEffect(() => {
    if (!isCustomRangeActive || !detail?.layer_key) {
      setCustomHotspots(null);
      setCustomLoading(false);
      setCustomError(null);
      return;
    }

    let active = true;
    setCustomLoading(true);
    setCustomError(null);

    api
      .getHotspots({
        start_at: wibDateBoundaryIso(customStartDate, false),
        end_at: wibDateBoundaryIso(customEndDate, true),
        satellites: SATELLITE_OPTIONS.map((option) => option.value),
        active_layers: [detail.layer_key],
        view: "full"
      })
      .then((response) => {
        if (!active) return;
        setCustomHotspots(response.hotspots.map(mapHotspotRecordToDashboardHotspot));
      })
      .catch(() => {
        if (!active) return;
        setCustomHotspots([]);
        setCustomError("Gagal memuat data hotspot untuk rentang ini.");
      })
      .finally(() => {
        if (active) {
          setCustomLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [isCustomRangeActive, customStartDate, customEndDate, detail?.layer_key]);

  // Luas kebakaran (overlay resmi KLHK) untuk polygon ini. Sengaja dibiarkan
  // gagal diam-diam: rekapnya terbit tidak dengan jadwal tetap, jadi KPS
  // yang datanya belum dihitung adalah kondisi normal -- bukan error yang
  // perlu ditampilkan sebagai kegagalan halaman.
  const [burnedAreas, setBurnedAreas] = useState<BurnedAreaRow[]>([]);
  // Luas UNIK (ST_Union server-side) -- beda dari menjumlahkan burned_area_ha
  // per bulan, yang menghitung ganda lahan yang terbakar lebih dari sekali
  // dalam setahun. Pada satu KPS di Bengkalis selisihnya 536 ha (22%), dan
  // pada dua KPS lain penjumlahan bulanannya bahkan melebihi luas kawasan
  // itu sendiri -- mustahil secara fisik. null = belum ada geometry
  // tersimpan (jatuh kembali ke penjumlahan bulanan, dilabeli sebagai
  // akumulasi kejadian, bukan luas area).
  const [uniqueHa, setUniqueHa] = useState<number | null>(null);
  const [burnedGeometry, setBurnedGeometry] = useState<BurnedAreaFeatureCollection | null>(null);

  useEffect(() => {
    if (polygonId === null) {
      setBurnedAreas([]);
      setUniqueHa(null);
      setBurnedGeometry(null);
      return;
    }

    let active = true;
    // Difilter di server (polygon_ids), bukan unduh semua lalu saring di sini --
    // tabelnya bisa puluhan ribu baris kalau seluruh KPS sudah dihitung.
    fetch(`/api/burned-area/summary?polygon_ids=${polygonId}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { rows?: BurnedAreaRow[]; unique_ha?: number | null } | null) => {
        if (!active || !payload?.rows) {
          return;
        }
        setBurnedAreas(payload.rows);
        setUniqueHa(payload.unique_ha ?? null);
      })
      .catch(() => {
        /* diamkan -- lihat komentar di atas */
      });

    fetch(`/api/burned-area/geometry?polygon_ids=${polygonId}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: BurnedAreaFeatureCollection | null) => {
        if (active && payload?.features?.length) {
          setBurnedGeometry(payload);
        }
      })
      .catch(() => {
        /* diamkan -- lihat komentar di atas */
      });

    return () => {
      active = false;
    };
  }, [polygonId]);

  // Riwayat KLHK disaring ke rentang kustom (kalau aktif) di titik pemakaian
  // ini -- fetch-nya sendiri (di atas) tetap ambil SELURUH riwayat sekali
  // saja, datanya kecil per-KPS jadi tidak perlu bolak-balik ke server tiap
  // ganti tanggal.
  const effectiveBurnedAreas = useMemo(() => {
    if (!isCustomRangeActive) {
      return burnedAreas;
    }
    return burnedAreas.filter((row) => isPeriodInRange(row.year, row.month, customStartDate, customEndDate));
  }, [burnedAreas, isCustomRangeActive, customStartDate, customEndDate]);

  // Overlay peta (jejak area terbakar) mengikuti saringan rentang kustom yang
  // sama -- supaya arsiran merah di peta konsisten dengan daftar & badge di
  // sidebar, bukan selalu menampilkan seluruh riwayat.
  const effectiveBurnedGeometry = useMemo(() => {
    if (!burnedGeometry || !isCustomRangeActive) {
      return burnedGeometry;
    }
    return {
      ...burnedGeometry,
      features: burnedGeometry.features.filter((feature) =>
        isPeriodInRange(feature.properties.year, feature.properties.month, customStartDate, customEndDate)
      )
    };
  }, [burnedGeometry, isCustomRangeActive, customStartDate, customEndDate]);

  const burnedAreaStats = useMemo(() => {
    if (effectiveBurnedAreas.length === 0) {
      return null;
    }
    const accumulatedHa = effectiveBurnedAreas.reduce((sum, row) => sum + (row.burned_area_ha ?? 0), 0);
    const sorted = [...effectiveBurnedAreas].sort(
      (a, b) => b.year - a.year || b.month - a.month
    );
    // uniqueHa (dari ST_Union server) dihitung utk SELURUH riwayat polygon --
    // kalau rentang kustom aktif dan tidak mencakup semua periode, angka itu
    // jadi tidak representatif utk subset yang sedang ditampilkan, jadi ikut
    // jatuh ke akumulasi bulanan (subset) juga, sama seperti fallback KPS yang
    // belum punya geometry tersimpan.
    const coversFullHistory = !isCustomRangeActive || effectiveBurnedAreas.length === burnedAreas.length;
    const displayHa = uniqueHa !== null && coversFullHistory ? uniqueHa : accumulatedHa;
    const isAccumulated = !(uniqueHa !== null && coversFullHistory);
    // Periode (bulan) TERPISAH KPS ini tercatat terbakar -- beda dari
    // `burnedAreas.length`/`months.length` yang bisa lebih dari satu baris
    // untuk bulan yang sama (mis. beberapa bidang bekas terbakar sekaligus).
    const periodeTerbakar = new Set(effectiveBurnedAreas.map((row) => `${row.year}-${row.month}`)).size;
    return { displayHa, isAccumulated, latest: sorted[0], months: sorted, periodeTerbakar };
  }, [effectiveBurnedAreas, burnedAreas.length, uniqueHa, isCustomRangeActive]);

  // Dipakai cuma untuk pesan "tidak ada data di rentang ini" -- supaya rentang
  // kustom yang tidak overlap dengan bulan manapun di riwayat KLHK KPS ini
  // menampilkan penjelasan, bukan menghilangkan seluruh section "Luas
  // terbakar" tanpa keterangan (dulu terlihat seperti data hilang/bug).
  const fullBurnedHistoryRange = useMemo(() => {
    if (burnedAreas.length === 0) {
      return null;
    }
    const sorted = [...burnedAreas].sort((a, b) => a.year - b.year || a.month - b.month);
    return {
      earliest: sorted[0],
      latest: sorted[sorted.length - 1],
      periodeTerbakar: new Set(burnedAreas.map((row) => `${row.year}-${row.month}`)).size
    };
  }, [burnedAreas]);

  const stats = useMemo(() => {
    let tinggi = 0;
    let sedang = 0;
    let rendah = 0;
    const satellites = new Set<string>();

    kpsHotspots.forEach((hotspot) => {
      const frp = hotspot.frp ?? 0;
      if (frp > 30) {
        tinggi += 1;
      } else if (frp >= 10) {
        sedang += 1;
      } else {
        rendah += 1;
      }
      satellites.add(hotspot.source);
    });

    return { total: kpsHotspots.length, tinggi, sedang, rendah, satellites: Array.from(satellites) };
  }, [kpsHotspots]);

  // Deteksi yang sedang ditelaah di bawah -- default ke yang paling baru,
  // tapi user bisa ketuk baris lain di "Daftar Deteksi Hotspot".
  const [selectedDetectionId, setSelectedDetectionId] = useState<string | null>(null);
  const [detectionPage, setDetectionPage] = useState(1);
  const detectionTotalPages = Math.max(1, Math.ceil(kpsHotspots.length / DETECTION_PAGE_SIZE));
  const pagedKpsHotspots = kpsHotspots.slice(
    (detectionPage - 1) * DETECTION_PAGE_SIZE,
    detectionPage * DETECTION_PAGE_SIZE
  );
  const selectedDetection = useMemo(
    () => kpsHotspots.find((hotspot) => hotspot.id === selectedDetectionId) ?? kpsHotspots[0] ?? null,
    [kpsHotspots, selectedDetectionId]
  );

  const comparison = useMemo(
    () => buildComparison(hotspots, selectedDetection),
    [hotspots, selectedDetection]
  );

  // Titik hotspot & polygon bekas terbakar HARUS berbagi satu Pane/renderer
  // Leaflet yang sama. Canvas renderer memasang listener klik langsung di
  // elemen <canvas>-nya sendiri (bukan di peta) -- kalau keduanya dipisah ke
  // Pane berbeda (seperti sebelumnya), Pane dengan z-index lebih tinggi
  // menutupi Pane di bawahnya secara utuh di DOM, sehingga SEMUA klik di area
  // itu tertelan oleh canvas teratas walau tidak ada bentuk tergambar di titik
  // itu -- polygon bekas terbakar di Pane bawah jadi TIDAK PERNAH bisa diklik
  // sama sekali, bukan cuma tertutup separuh. Menyatukan renderer membuat
  // Leaflet memilih target klik lewat uji geometri tiap bentuk (lingkaran
  // kecil vs polygon besar), bukan lewat susunan DOM.
  //
  // Supaya urutan gambar (dan karenanya prioritas klik) tetap deterministik
  // walau data bekas terbakar datang belakangan lewat fetch async, titik
  // hotspot selalu dipaksa `bringToFront()` ulang tiap kali daftarnya atau
  // geometry bekas terbakar berubah -- tanpa ini, urutan menang bisa terbalik
  // tergantung siapa yang lebih dulu selesai fetch.
  const hotspotLayerGroupRef = useRef<LLayerGroup | null>(null);
  useEffect(() => {
    const group = hotspotLayerGroupRef.current;
    if (!group) {
      return;
    }
    group.eachLayer((layer) => {
      if ("bringToFront" in layer && typeof layer.bringToFront === "function") {
        layer.bringToFront();
      }
    });
  }, [kpsHotspots, effectiveBurnedGeometry]);

  return (
    <div className="kps-detail">
      <header className="kps-detail-header">
        <button type="button" className="kps-detail-back" onClick={onClose}>
          <ArrowLeft size={16} />
          Kembali ke Matriks Data
        </button>
        <div className="kps-detail-title-row">
          <h2 className="kps-detail-title">{detail?.lembaga || agency}</h2>
          <button
            type="button"
            className="matrix-btn matrix-btn--primary"
            onClick={() => onExportPdf({ agency })}
            disabled={isExportingPdf}
          >
            <Download size={14} />
            {isExportingPdf ? "Mengunduh PDF..." : "Unduh Laporan Lembaga (PDF)"}
          </button>
        </div>
      </header>

      <section className="panel kps-detail-info" style={{ marginBottom: "1rem" }}>
        <p className="filter-group-label">Filter Waktu Halaman Ini</p>
        <div className="filter-preset-grid" style={{ marginBottom: "0.65rem" }}>
          {HOTSPOT_DAY_PRESETS.map((preset) => (
            <button
              key={preset.value}
              type="button"
              className={`chip chip--button filter-preset-btn${
                isTimePresetActive(preset.hours) ? " chip--active" : ""
              }`}
              onClick={() => applyTimePreset(preset.hours)}
            >
              <span>{preset.label}</span>
            </button>
          ))}
        </div>
        <div className="filter-date-grid">
          <label className="field">
            <span>Dari</span>
            <input
              type="date"
              className="filter-date-input"
              value={customStartDate}
              onChange={(event) => setCustomStartDate(event.currentTarget.value)}
            />
          </label>
          <label className="field">
            <span>Ke</span>
            <input
              type="date"
              className="filter-date-input"
              value={customEndDate}
              onChange={(event) => setCustomEndDate(event.currentTarget.value)}
            />
          </label>
        </div>
        <p className="help-copy" style={{ marginTop: "0.5rem" }}>
          {customError
            ? customError
            : !isCustomRangeActive
              ? "Mengikuti rentang waktu dashboard saat ini."
              : customLoading
                ? "Memuat data untuk rentang ini..."
                : "Menampilkan titik hotspot & riwayat bekas terbakar untuk rentang kustom ini saja."}
        </p>
        {isCustomRangeActive && (
          <button
            type="button"
            className="kps-detail-back"
            style={{ marginTop: "0.6rem" }}
            onClick={() => {
              setCustomStartDate("");
              setCustomEndDate("");
            }}
          >
            Kembali ke rentang dashboard
          </button>
        )}
      </section>

      {error ? <p className="toast-error toast-error--inline">{error}</p> : null}

      <div className="kps-detail-body">
        <aside className="kps-detail-info panel">
          {loading ? (
            <p className="help-copy">Memuat informasi KPS...</p>
          ) : detail ? (
            <dl className="kps-detail-fields">
              {INFO_FIELDS.map(([label, key]) => {
                const value = detail[key];
                if (!value) {
                  return null;
                }
                return (
                  <div key={key}>
                    <dt>{label}</dt>
                    <dd>{String(value)}</dd>
                  </div>
                );
              })}
            </dl>
          ) : (
            <p className="help-copy">Polygon KPS ini belum terhubung ke data spasial.</p>
          )}

          <div className="kps-detail-stats">
            <div className="control-metric">
              <span>Total hotspot terpantau:</span>
              <strong>{stats.total}</strong>
            </div>
            {stats.total > 0 && (
              <div className="kps-detail-frp-breakdown">
                <div>
                  <span style={{ color: "#ef4444" }}>■</span> Tinggi <strong>{stats.tinggi}</strong>
                </div>
                <div>
                  <span style={{ color: "#f59e0b" }}>■</span> Sedang <strong>{stats.sedang}</strong>
                </div>
                <div>
                  <span style={{ color: "#3b82f6" }}>■</span> Rendah <strong>{stats.rendah}</strong>
                </div>
              </div>
            )}
            {stats.satellites.length > 0 && (
              <p className="help-copy">Satelit: {stats.satellites.join(", ")}</p>
            )}

            {!burnedAreaStats && isCustomRangeActive && fullBurnedHistoryRange && (
              <div style={{ marginTop: "1rem", paddingTop: "0.85rem", borderTop: "1px solid rgba(255,255,255,0.08)" }}>
                <p className="help-copy">
                  Tidak ada data luas terbakar (KLHK) pada rentang tanggal ini.
                </p>
                <p className="help-copy" style={{ marginTop: "0.3rem" }}>
                  Riwayat penuh KPS ini: {MONTH_LABELS[fullBurnedHistoryRange.earliest.month - 1]}{" "}
                  {fullBurnedHistoryRange.earliest.year} &ndash;{" "}
                  {MONTH_LABELS[fullBurnedHistoryRange.latest.month - 1]} {fullBurnedHistoryRange.latest.year}
                  {" "}({fullBurnedHistoryRange.periodeTerbakar}&times; periode). Ubah rentang tanggal di atas
                  supaya mencakup salah satu bulan itu untuk melihat datanya.
                </p>
              </div>
            )}

            {burnedAreaStats && (
              <div style={{ marginTop: "1rem", paddingTop: "0.85rem", borderTop: "1px solid rgba(255,255,255,0.08)" }}>
                <div className="control-metric">
                  <span>{burnedAreaStats.isAccumulated ? "Luas terbakar (akumulasi bulanan):" : "Luas terbakar (area unik):"}</span>
                  <strong>{formatNumber(Math.round(burnedAreaStats.displayHa * 10) / 10)} Ha</strong>
                </div>
                {burnedAreaStats.periodeTerbakar > 1 && (
                  <p className="help-copy" style={{ marginTop: "0.4rem" }}>
                    <span
                      className={`confidence-pill confidence-pill--freq-${
                        burnedAreaStats.periodeTerbakar >= 4 ? "tinggi" : "sedang"
                      }`}
                    >
                      Terbakar berulang &middot; {burnedAreaStats.periodeTerbakar}&times; periode
                    </span>
                  </p>
                )}
                {burnedAreaStats.isAccumulated && (
                  <p className="help-copy" style={{ marginTop: "0.3rem", color: "#f59e0b" }}>
                    Jumlah angka per bulan -- lahan yang terbakar lebih dari sekali
                    ikut terhitung berulang. Belum ada jejak area tersimpan untuk
                    menghitung luas unik yang sesungguhnya.
                  </p>
                )}
                <p className="help-copy" style={{ marginTop: "0.4rem" }}>
                  Terakhir dihitung: {MONTH_LABELS[burnedAreaStats.latest.month - 1]}{" "}
                  {burnedAreaStats.latest.year}
                </p>
                {burnedAreaStats.months.length > 1 && (
                  <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                    {burnedAreaStats.months.slice(0, 6).map((row) => (
                      <div
                        key={`${row.year}-${row.month}`}
                        style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", color: "#9ca3af" }}
                      >
                        <span>
                          {MONTH_LABELS[row.month - 1]} {row.year}
                        </span>
                        <span>{formatNumber(Math.round(row.burned_area_ha * 10) / 10)} Ha</span>
                      </div>
                    ))}
                  </div>
                )}
                {effectiveBurnedGeometry && effectiveBurnedGeometry.features.length > 0 && (
                  <p className="help-copy" style={{ marginTop: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span
                      style={{
                        display: "inline-block",
                        width: "12px",
                        height: "12px",
                        background: "rgba(220,38,38,0.45)",
                        border: "1px solid #dc2626",
                        flexShrink: 0
                      }}
                    />
                    Area merah di peta = jejak lahan terbakar.
                  </p>
                )}
                {effectiveBurnedGeometry?.features.some((feature) => feature.properties.is_estimated) && (
                  <p className="help-copy" style={{ marginTop: "0.3rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                    <span
                      style={{
                        display: "inline-block",
                        width: "12px",
                        height: "12px",
                        borderRadius: "50%",
                        background: "rgba(220,38,38,0.25)",
                        border: "2px dashed #dc2626",
                        flexShrink: 0
                      }}
                    />
                    Lingkaran putus-putus = perkiraan lokasi, luas di bawah resolusi piksel citra.
                  </p>
                )}
                <p className="help-copy" style={{ marginTop: "0.5rem", fontSize: "0.72rem" }}>
                  Sumber: KLHK — Areal Kebakaran Hutan dan Lahan (akurasi H/M, terverifikasi hotspot).
                </p>
              </div>
            )}
          </div>
        </aside>

        <div className="kps-detail-map">
          <MapContainer center={[-2.5, 118]} zoom={5} preferCanvas style={{ height: "100%", width: "100%" }}>
            <KeepMapSized />
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            />
            {detail ? (
              <>
                <FitToPolygon geometry={detail.geometry} />
                <GeoJSON
                  data={{ type: "Feature", properties: {}, geometry: detail.geometry } as never}
                  // Batas KPS tidak punya popup maupun penangan klik. Selama ia
                  // ikut diperhitungkan, Leaflet memilih lapisan tergambar
                  // paling akhir sebagai sasaran klik -- dan karena geometri
                  // baru tiba setelah titik hotspot terpasang, polygon inilah
                  // yang menang, lalu kliknya dibuang tanpa jejak. Titik jadi
                  // terlihat mati padahal penanganya ada.
                  style={{
                    color: "#ff8c42",
                    weight: 3,
                    fillColor: "#ff8c42",
                    fillOpacity: 0.14,
                    interactive: false
                  }}
                />
              </>
            ) : null}
            {/* Polygon bekas terbakar + titik hotspot BERBAGI satu Pane (lihat
                catatan `hotspotLayerGroupRef` di atas) supaya keduanya bisa
                sama-sama diklik -- Pane terpisah membuat canvas yang lebih
                tinggi z-index-nya menelan semua klik di Pane bawahnya,
                walaupun tidak ada bentuk tergambar di titik itu. Urutan
                gambar di sini (polygon dulu, titik belakangan + dipaksa
                bringToFront tiap render) yang menjaga titik hotspot tetap
                terlihat di atas arsiran merah, bukan lagi z-index Pane. */}
            <Pane name="kps-interaktif" style={{ zIndex: 420 }}>
              {effectiveBurnedGeometry && effectiveBurnedGeometry.features.length > 0 && (
                <GeoJSON
                  // Disertakan rentang kustom di key -- GeoJSON react-leaflet
                  // tidak mendiff ulang `data` di render berikutnya, jadi tanpa
                  // ini overlay tidak ikut menyempit saat filter diganti.
                  key={`burned-${polygonId}-${customStartDate}-${customEndDate}`}
                  data={effectiveBurnedGeometry as never}
                  style={{
                    color: "#dc2626",
                    weight: 1,
                    fillColor: "#dc2626",
                    fillOpacity: 0.45,
                    interactive: true
                  }}
                  // Baris tanpa geometry dikirim server sebagai titik centroid,
                  // is_estimated true -- digambar sebagai penanda putus-putus,
                  // bukan disamakan dengan bentuk presisi. Overlay KLHK (vektor
                  // ke vektor) selalu punya bentuk presisi, jadi jalur ini
                  // praktis tidak lagi terpakai -- dipertahankan untuk sumber
                  // data lama/masa depan yang mungkin tidak selalu bergeometri.
                  pointToLayer={(_feature, latlng) =>
                    buildLeafletCircleMarker(latlng, {
                      radius: 9,
                      color: "#dc2626",
                      weight: 2,
                      dashArray: "4 3",
                      fillColor: "#dc2626",
                      fillOpacity: 0.25
                    })
                  }
                  onEachFeature={(feature, layer) => {
                    const props = feature.properties as {
                      year: number;
                      month: number;
                      burned_area_ha: number;
                      is_estimated: boolean;
                    };

                    // Dibangun sebagai elemen DOM sungguhan (bukan string HTML
                    // + atribut onclick) supaya tombol "Salin koordinat" bisa
                    // pakai addEventListener asli -- lebih aman & tidak
                    // tergantung inline script diizinkan atau tidak.
                    const container = document.createElement("div");
                    container.className = "popup-card";
                    container.style.minWidth = "190px";
                    container.style.fontSize = "12px";
                    container.style.fontFamily = "sans-serif";

                    const title = document.createElement("strong");
                    title.style.color = "#dc2626";
                    title.textContent = "Area Terbakar";
                    container.appendChild(title);

                    const periodLine = document.createElement("div");
                    periodLine.style.marginTop = "6px";
                    periodLine.textContent = `${MONTH_LABELS[props.month - 1]} ${props.year}`;
                    container.appendChild(periodLine);

                    const haLabel = document.createElement("div");
                    haLabel.style.marginTop = "4px";
                    haLabel.append("Luas: ");
                    const haValue = document.createElement("strong");
                    haValue.textContent = `${formatNumber(Math.round(props.burned_area_ha * 10) / 10)} Ha`;
                    haLabel.appendChild(haValue);
                    container.appendChild(haLabel);

                    if (props.is_estimated) {
                      const note = document.createElement("div");
                      note.style.marginTop = "6px";
                      note.style.fontSize = "11px";
                      note.style.fontStyle = "italic";
                      note.textContent = "Perkiraan lokasi -- luas di bawah resolusi piksel citra satelit";
                      container.appendChild(note);
                    }

                    const center = geometryCenter(feature.geometry as { type: string; coordinates: unknown });
                    if (center) {
                      const actions = document.createElement("div");
                      actions.className = "coord-actions";

                      const copyBtn = document.createElement("button");
                      copyBtn.type = "button";
                      copyBtn.className = "coord-action-btn";
                      copyBtn.textContent = "Salin koordinat";
                      copyBtn.addEventListener("click", () => {
                        navigator.clipboard
                          .writeText(`${center.lat.toFixed(5)}, ${center.lon.toFixed(5)}`)
                          .then(() => {
                            copyBtn.textContent = "Disalin!";
                            window.setTimeout(() => {
                              copyBtn.textContent = "Salin koordinat";
                            }, 1500);
                          })
                          .catch(() => {
                            // Clipboard API tidak didukung di browser/webview ini --
                            // diamkan, tidak ada fallback yang bermakna.
                          });
                      });
                      actions.appendChild(copyBtn);

                      const mapsLink = document.createElement("a");
                      mapsLink.href = `https://www.google.com/maps?q=${center.lat},${center.lon}`;
                      mapsLink.target = "_blank";
                      mapsLink.rel = "noopener noreferrer";
                      mapsLink.className = "coord-action-btn";
                      mapsLink.textContent = "Google Maps";
                      actions.appendChild(mapsLink);

                      container.appendChild(actions);
                    }

                    layer.bindPopup(container);
                  }}
                />
              )}
              <LayerGroup ref={hotspotLayerGroupRef}>
                {kpsHotspots.map((hotspot) => (
                  <CircleMarker
                    key={hotspot.id}
                    center={[hotspot.latitude, hotspot.longitude]}
                    radius={6}
                    pathOptions={{
                      color: "#1b120d",
                      weight: 2,
                      fillColor: sourceColor(hotspot.source),
                      fillOpacity: 0.95
                    }}
                    eventHandlers={{ click: () => setSelectedDetectionId(hotspot.id) }}
                  >
                    <Popup>
                      <HotspotPopupContent hotspot={hotspot} />
                    </Popup>
                  </CircleMarker>
                ))}
              </LayerGroup>
            </Pane>
          </MapContainer>
        </div>
      </div>

      {/* Konten di bawah ini mengalir dalam scroll satu halaman (bukan
          panel geser terpisah dengan scroll sendiri) -- lihat catatan
          "Eliminasi Nested Scroll" di HotspotMatrix.tsx. */}
      {selectedDetection && (
        <div className="kps-detail-sections">
          <section className="matrix-detail-card">
            <div className="matrix-detail-card__head">
              <span>Segmen Lokasi</span>
              <strong>{getStatusLabel(selectedDetection)}</strong>
            </div>
            <div className="matrix-detail-grid matrix-detail-grid--two">
              <div className="matrix-detail-item">
                <span>Sumber</span>
                <strong>{formatMetadataValue(selectedDetection.source)}</strong>
              </div>
              <div className="matrix-detail-item">
                <span>Satelit</span>
                <strong>{formatMetadataValue(selectedDetection.satellite)}</strong>
              </div>
              <div className="matrix-detail-item">
                <span>Siang/Malam</span>
                <strong>{formatMetadataValue(selectedDetection.daynight)}</strong>
              </div>
              <div className="matrix-detail-item">
                <span>Terdeteksi</span>
                <strong>{formatTimestamp(selectedDetection.detectedAt)}</strong>
              </div>
            </div>
            <div className="matrix-code-block">
              <p className="matrix-code-block__label">Koordinat</p>
              <strong>
                {selectedDetection.latitude.toFixed(5)}, {selectedDetection.longitude.toFixed(5)}
              </strong>
            </div>
          </section>

          <WeatherConditionCard lat={selectedDetection.latitude} lon={selectedDetection.longitude} />

          <section className="matrix-detail-card">
            <div className="matrix-detail-card__head">
              <span>Grafik Data Intensitas</span>
              <strong>Terpilih vs populasi</strong>
            </div>
            <div className="matrix-comparison-block">
              <div className="matrix-comparison-head">
                <span>Perbandingan FRP (MW)</span>
                <strong>{formatNumber(selectedDetection.frp)}</strong>
              </div>
              <div className="matrix-comparison-list">
                {comparison.frp.map((item) => {
                  const max = Math.max(...comparison.frp.map((entry) => entry.value), 1);
                  const width = `${Math.max((item.value / max) * 100, item.value > 0 ? 12 : 0)}%`;
                  return (
                    <div key={item.label} className="matrix-comparison-row">
                      <span>{item.label}</span>
                      <div className="matrix-bar-track matrix-bar-track--mini">
                        <span className="matrix-bar-fill" style={{ width, background: item.color }} />
                      </div>
                      <strong>{item.value}</strong>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="matrix-comparison-block">
              <div className="matrix-comparison-head">
                <span>Perbandingan Kecerahan (K)</span>
                <strong>{formatNumber(selectedDetection.brightness)}</strong>
              </div>
              <div className="matrix-comparison-list">
                {comparison.brightness.map((item) => {
                  const max = Math.max(...comparison.brightness.map((entry) => entry.value), 1);
                  const width = `${Math.max((item.value / max) * 100, item.value > 0 ? 12 : 0)}%`;
                  return (
                    <div key={item.label} className="matrix-comparison-row">
                      <span>{item.label}</span>
                      <div className="matrix-bar-track matrix-bar-track--mini">
                        <span className="matrix-bar-fill" style={{ width, background: item.color }} />
                      </div>
                      <strong>{item.value}</strong>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>

          <section className="matrix-detail-card">
            <div className="matrix-detail-card__head">
              <span>Daftar Deteksi Hotspot ({kpsHotspots.length} titik)</span>
              <strong>Ketuk untuk detail</strong>
            </div>
            <div className="detect-list">
              <table className="detect-table">
                <thead>
                  <tr>
                    <th scope="col">Tanggal</th>
                    <th scope="col">Satelit</th>
                    <th scope="col">Kelas FRP</th>
                    <th scope="col">FRP</th>
                    <th scope="col">Lat/Lon</th>
                  </tr>
                </thead>
                <tbody>
                  {pagedKpsHotspots.map((hotspot) => {
                    const isActive = selectedDetection.id === hotspot.id;
                    return (
                      <tr
                        key={hotspot.id}
                        className={isActive ? "detect-row detect-row--active" : "detect-row"}
                        onClick={() => setSelectedDetectionId(hotspot.id)}
                        role="button"
                        tabIndex={0}
                        aria-current={isActive || undefined}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setSelectedDetectionId(hotspot.id);
                          }
                        }}
                      >
                        <td className="dt-waktu">{formatTimestamp(hotspot.detectedAt)}</td>
                        <td className="dt-satelit">{hotspot.source}</td>
                        <td className="dt-kelas">
                          <span
                            className={`confidence-pill confidence-pill--${
                              getFrpCategory(hotspot) === "Tinggi" ? "high" : getFrpCategory(hotspot) === "Sedang" ? "nominal" : "low"
                            }`}
                          >
                            {normalizeFrpCategoryLabel(hotspot)}
                          </span>
                        </td>
                        <td className="dt-frp">{formatNumber(hotspot.frp)} MW</td>
                        <td className="dt-koord" title={`${hotspot.latitude.toFixed(4)}, ${hotspot.longitude.toFixed(4)}`}>
                          {hotspot.latitude.toFixed(3)}, {hotspot.longitude.toFixed(3)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="matrix-footer">
              <span className="matrix-footer__count">{kpsHotspots.length} titik</span>
              <div className="matrix-pagination">
                <button
                  type="button"
                  className="matrix-page-btn"
                  onClick={() => setDetectionPage((page) => Math.max(1, page - 1))}
                  disabled={detectionPage === 1}
                  aria-label="Halaman sebelumnya"
                >
                  ‹
                </button>
                <span className="matrix-page-info">
                  Halaman {detectionPage} / {detectionTotalPages}
                </span>
                <button
                  type="button"
                  className="matrix-page-btn"
                  onClick={() => setDetectionPage((page) => Math.min(detectionTotalPages, page + 1))}
                  disabled={detectionPage >= detectionTotalPages}
                  aria-label="Halaman berikutnya"
                >
                  ›
                </button>
              </div>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
