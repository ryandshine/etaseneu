import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GeoJSON as LeafletGeoJSON } from "leaflet";
import { geoJSON as buildLeafletGeoJSON } from "leaflet";
import { GeoJSON, MapContainer, TileLayer, ZoomControl, useMap } from "react-leaflet";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import {
  LAND_COVER_CLASSES,
  LAND_COVER_YEARS,
  type LandCoverClassKey,
} from "../constants/landCover";
import { SMOOTH_ZOOM_MAP_PROPS } from "../constants/map";
import { useIsMobile } from "../hooks/useIsMobile";
import {
  buildChartData,
  formatDelta,
  landCoverColor,
  type LandCoverTable,
} from "../lib/landCover";
import { authFetch } from "../lib/api";

type State = "idle" | "running" | "done" | "error";

type StatusResponse = {
  state: State;
  step: string | null;
  error: string | null;
  computed_at: string | null;
  // true kalau poligon LAIN sedang dianalisis di server sekarang -- lock
  // global biar kuota GEE & CPU tidak diperebutkan banyak user sekaligus.
  busy_elsewhere: boolean;
  // versi formula hasil tersimpan (null kalau belum ada hasil / hasil lama
  // sebelum kolom ini ada) vs versi yang dipakai server sekarang
  formula_version?: number | null;
  current_formula_version?: number;
};

type ResultResponse = {
  meta: Record<string, unknown>;
  years: number[];
  classes: string[];
  table: LandCoverTable;
  net_change: Record<string, number>;
  summary_text: string;
};

type OverlayFeature = {
  type: "Feature";
  geometry: unknown;
  properties: { class_key: string; area_ha: number; pct: number };
};
type OverlayFC = { type: "FeatureCollection"; features: OverlayFeature[] };

const POLL_MS = 5000;
// Dipakai cuma buat menyegarkan busy_elsewhere saat idle/error (bukan
// progres analisis sendiri) -- lebih longgar dari POLL_MS biar tidak
// membebani server dengan polling ekstra dari tiap tab yang lagi dibuka.
const POLL_IDLE_MS = 10000;
const FIRST_YEAR = LAND_COVER_YEARS[0];
const LAST_YEAR = LAND_COVER_YEARS[LAND_COVER_YEARS.length - 1];

// Basemap seragam: satelit Google Maps Hybrid terbaru, plus
// jalan & topografi dari Esri ArcGIS (bebas API key).
const BASEMAPS = {
  satelit: {
    label: "Satelit",
    layers: [
      {
        url: "https://mt{s}.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        subdomains: ["0", "1", "2", "3"],
        maxZoom: 20,
      },
    ],
  },
  jalan: {
    label: "Jalan",
    layers: [
      {
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        subdomains: ["a", "b", "c"],
        maxZoom: 19,
      },
    ],
  },
  topo: {
    label: "Topografi",
    layers: [
      {
        url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        subdomains: ["a", "b", "c"],
        maxZoom: 19,
      },
    ],
  },
} as const;
type BasemapKey = keyof typeof BASEMAPS;

function Chevron({ dir }: { dir: "left" | "right" }): JSX.Element {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden focusable="false">
      <path
        d={dir === "left" ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"}
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function PlayIcon(): JSX.Element {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden focusable="false">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  );
}

function PauseIcon(): JSX.Element {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden focusable="false">
      <rect x="6" y="4" width="4" height="16" />
      <rect x="14" y="4" width="4" height="16" />
    </svg>
  );
}

// fitBounds butuh instance peta, jadi harus komponen anak MapContainer (pola
// sama dengan FitToPolygon di KpsDetailView.tsx). Fit ke rona kelas kalau ada,
// kalau tidak ke outline poligon.
function FitLandCover({
  overlay,
  outline,
  isMobile = false,
  isHudCollapsed = false,
}: {
  overlay: OverlayFC | null;
  outline: Record<string, unknown> | null;
  isMobile?: boolean;
  isHudCollapsed?: boolean;
}): null {
  const map = useMap();
  useEffect(() => {
    const source =
      overlay && overlay.features.length > 0
        ? overlay
        : outline
          ? ({ type: "Feature", geometry: outline } as unknown)
          : null;
    if (!source) return;
    try {
      const bounds = buildLeafletGeoJSON(source as never).getBounds();
      if (bounds.isValid()) {
        map.invalidateSize({ animate: false });
        const padLeft = isMobile || isHudCollapsed ? 24 : 260;
        map.fitBounds(bounds, {
          paddingTopLeft: [24, padLeft],
          paddingBottomRight: [24, 24],
          maxZoom: 15,
        });
      }
    } catch {
      /* geometri tak valid — peta tetap di posisi default */
    }
  }, [overlay, outline, isMobile, isHudCollapsed, map]);
  return null;
}

const CLASS_LABEL = new Map<LandCoverClassKey, string>(
  LAND_COVER_CLASSES.map((c) => [c.key, c.label]),
);

type TipItem = { dataKey?: string | number; value?: number; color?: string };
type TipProps = { active?: boolean; label?: string | number; payload?: TipItem[] };

function LandCoverTooltip({ active, payload, label }: TipProps): JSX.Element | null {
  if (!active || !payload || payload.length === 0) return null;
  const rows = payload
    .filter((p): p is Required<Pick<TipItem, "value">> & TipItem => typeof p.value === "number" && p.value > 0.05)
    .sort((a, b) => b.value - a.value);
  if (rows.length === 0) return null;
  return (
    <div className="lc-tip">
      <span className="lc-tip__year">{label}</span>
      <ul>
        {rows.map((p) => (
          <li key={String(p.dataKey)}>
            <span className="lc-swatch" style={{ background: p.color }} aria-hidden />
            {CLASS_LABEL.get(p.dataKey as LandCoverClassKey) ?? String(p.dataKey)}
            <b>{p.value.toFixed(1)}%</b>
          </li>
        ))}
      </ul>
    </div>
  );
}

type LandCoverPanelProps = {
  polygonId: number;
  /** Jalankan/Hapus/Mulai ulang analisis = admin & role user yang diizinkan (backend
   *  `require_land_cover_role`); role tanpa izin cuma melihat hasil. Default false
   *  supaya lupa meneruskan prop tidak pernah memunculkan tombol yang
   *  bakal ditolak 403. */
  isAdmin?: boolean;
  canAnalyze?: boolean;
  /** Identitas poligon -- ditampilkan di chrome mengambang di atas peta
   *  (TutupanLahanView tidak lagi merender .tl-detail-head sendiri supaya
   *  peta bisa full-bleed, pola sama Live Map). */
  polygonLabel?: string;
  polygonSublabel?: string;
  onOpenKpsDetail?: () => void;
  /** Mobile: kembali ke daftar poligon. */
  onBack?: () => void;
};

export function LandCoverPanel({
  polygonId,
  isAdmin = false,
  canAnalyze,
  polygonLabel,
  polygonSublabel,
  onOpenKpsDetail,
  onBack,
}: LandCoverPanelProps): JSX.Element {
  const allowAnalyze = canAnalyze ?? isAdmin;
  const [state, setState] = useState<State>("idle");
  const [step, setStep] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [busyElsewhere, setBusyElsewhere] = useState(false);
  const [formulaVersion, setFormulaVersion] = useState<number | null>(null);
  const [currentFormulaVersion, setCurrentFormulaVersion] = useState<number | null>(null);
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [tab, setTab] = useState<"peta" | "tren" | "split">("peta");
  const [year, setYear] = useState<number>(LAST_YEAR);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [basemap, setBasemap] = useState<BasemapKey>("satelit");
  const isMobile = useIsMobile();
  const [overlay, setOverlay] = useState<OverlayFC | null>(null);
  const [outline, setOutline] = useState<Record<string, unknown> | null>(null);
  const [showS2TrueColor, setShowS2TrueColor] = useState(false);
  const [s2TileUrl, setS2TileUrl] = useState<string | null>(null);
  const [s2TileLoading, setS2TileLoading] = useState(false);
  const [s2TileError, setS2TileError] = useState<string | null>(null);
  const [overlayOpacity, setOverlayOpacity] = useState(0.75);
  const [isHudCollapsed, setIsHudCollapsed] = useState<boolean>(false);
  const overlayCache = useRef<Map<number, OverlayFC>>(new Map());
  const s2TileCache = useRef<Map<string, string>>(new Map());
  const geoJsonRef = useRef<LeafletGeoJSON | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Animasi pemutaran otomatis time-lapse 2021-2025
  useEffect(() => {
    if (!isPlaying) return;
    const timer = setInterval(() => {
      setYear((prev) => (prev >= LAST_YEAR ? FIRST_YEAR : prev + 1));
    }, 1700);
    return () => clearInterval(timer);
  }, [isPlaying]);

  const totalAreaHa = useMemo(() => {
    if (!result?.table) return 0;
    const latestTable = result.table[String(LAST_YEAR)] ?? result.table[String(year)];
    if (!latestTable) return 0;
    return Object.values(latestTable).reduce((acc, c) => acc + (c.area_ha || 0), 0);
  }, [result, year]);

  const forestLatest = useMemo(() => {
    if (!result?.table) return null;
    return result.table[String(LAST_YEAR)]?.hutan ?? null;
  }, [result]);

  const forestDelta = useMemo(() => {
    if (!result?.net_change) return 0;
    return result.net_change.hutan ?? 0;
  }, [result]);

  const fetchStatus = useCallback(async (): Promise<State> => {
    const res = await authFetch(`/api/land-cover/status?polygon_id=${polygonId}`);
    const body = (await res.json()) as StatusResponse;
    setState(body.state);
    setStep(body.step);
    setErrorMsg(body.error);
    setBusyElsewhere(Boolean(body.busy_elsewhere));
    setFormulaVersion(body.formula_version ?? null);
    setCurrentFormulaVersion(body.current_formula_version ?? null);
    return body.state;
  }, [polygonId]);

  useEffect(() => {
    overlayCache.current.clear();
    s2TileCache.current.clear();
    setShowS2TrueColor(false);
    setS2TileUrl(null);
    setS2TileLoading(false);
    setS2TileError(null);
    setOverlayOpacity(0.75);
    setResult(null);
    setOverlay(null);
    setOutline(null);
    setYear(LAST_YEAR);
    setTab("peta");
    setState("idle");
    setErrorMsg(null);
    void fetchStatus();
    void authFetch(`/api/polygons/${polygonId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { geometry?: Record<string, unknown> } | null) => {
        if (body?.geometry) setOutline(body.geometry);
      })
      .catch(() => undefined);
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, [fetchStatus, polygonId]);

  // setInterval, BUKAN setTimeout yang dijadwal ulang lewat dep [state, step]:
  // kalau langkah yang sama bertahan > POLL_MS (mis. "mengunduh sampel latih"
  // ~30 dtk) effect itu tidak pernah jalan lagi -> polling mati diam-diam dan
  // UI tampak "tidak ada progres" padahal analisis sudah selesai di server.
  useEffect(() => {
    if (state !== "running") return;
    const timer = setInterval(() => void fetchStatus(), POLL_MS);
    pollTimer.current = timer;
    return () => {
      clearInterval(timer);
      pollTimer.current = null;
    };
  }, [state, fetchStatus]);

  // Idle/error tidak butuh progres, tapi busy_elsewhere bisa berubah kapan
  // saja (user lain mulai/selesai analisis) -- polling longgar di sini
  // biar tombol "Jalankan Analisis" ke-update tanpa user reload halaman.
  useEffect(() => {
    if (state !== "idle" && state !== "error") return;
    const timer = setInterval(() => void fetchStatus(), POLL_IDLE_MS);
    return () => clearInterval(timer);
  }, [state, fetchStatus]);

  useEffect(() => {
    if (state !== "done") return;
    void authFetch(`/api/land-cover/result?polygon_id=${polygonId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body: ResultResponse | null) => {
        if (body) setResult(body);
      });
  }, [state, polygonId]);

  useEffect(() => {
    if (state !== "done") return;
    const cached = overlayCache.current.get(year);
    if (cached) {
      setOverlay(cached);
      return;
    }
    void authFetch(`/api/land-cover/overlay?polygon_id=${polygonId}&year=${year}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body: OverlayFC | null) => {
        if (!body) return;
        overlayCache.current.set(year, body);
        setOverlay(body);
      });
  }, [state, polygonId, year]);

  useEffect(() => {
    if (!showS2TrueColor || state !== "done") {
      setS2TileUrl(null);
      setS2TileLoading(false);
      setS2TileError(null);
      return;
    }
    const cacheKey = `${polygonId}-${year}`;
    const cached = s2TileCache.current.get(cacheKey);
    if (cached) {
      setS2TileUrl(cached);
      setS2TileLoading(false);
      setS2TileError(null);
      return;
    }
    let active = true;
    setS2TileUrl(null);
    setS2TileLoading(true);
    setS2TileError(null);
    void authFetch(`/api/land-cover/tile-url?polygon_id=${polygonId}&year=${year}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = (await res.json().catch(() => null)) as { detail?: string } | null;
          throw new Error(
            typeof body?.detail === "string" ? body.detail : "Gagal memuat citra satelit",
          );
        }
        return (await res.json()) as { url?: string; tile_url?: string };
      })
      .then((data) => {
        if (!active) return;
        const tileUrl = data?.tile_url || data?.url;
        if (tileUrl) {
          s2TileCache.current.set(cacheKey, tileUrl);
          setS2TileUrl(tileUrl);
        }
        setS2TileLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setS2TileError(err instanceof Error ? err.message : "Gagal memuat citra satelit");
        setS2TileLoading(false);
      });
    return () => {
      active = false;
    };
  }, [showS2TrueColor, polygonId, year, state]);

  useEffect(() => {
    if (geoJsonRef.current) {
      geoJsonRef.current.setStyle((feature) => {
        const c = landCoverColor(
          (feature?.properties as { class_key?: string })?.class_key ?? "",
        );
        return {
          color: c,
          weight: overlayOpacity === 0 ? 0.5 : 0.75,
          fillColor: c,
          fillOpacity: overlayOpacity,
        };
      });
    }
  }, [overlayOpacity]);

  const runAnalyze = useCallback(
    async (force: boolean) => {
      const res = await authFetch(
        `/api/land-cover/analyze${force ? "?force=true" : ""}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ polygon_id: polygonId }),
        },
      );
      if (res.status === 202) {
        setState("running");
        setErrorMsg(null);
        void fetchStatus();
      } else if (res.status === 503) {
        setState("error");
        setErrorMsg("Analisis satelit belum aktif di server.");
      } else {
        const body = await res.json().catch(() => null);
        if (res.status === 409 && body?.detail?.busy_elsewhere) {
          // Bukan error sungguhan -- cuma race condition tombol belum
          // sempat ke-disable (mis. klik "Analisis ulang" dari state "done").
          // JANGAN pindah state ke idle/error -- itu akan membuang hasil yang
          // sudah tampil padahal datanya masih utuh, cukup tandai busy saja.
          setBusyElsewhere(true);
          return;
        }
        setState("error");
        setErrorMsg(
          typeof body?.detail === "string" ? body.detail : "Gagal memulai analisis.",
        );
      }
    },
    [polygonId, fetchStatus],
  );

  // "Hapus hasil" menggantikan "Analisis ulang" (force) dari state done:
  // alurnya sekarang hapus dulu -> kembali idle -> "Jalankan Analisis".
  const deleteResult = useCallback(async () => {
    const res = await authFetch(`/api/land-cover/result?polygon_id=${polygonId}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      window.alert(
        typeof body?.detail === "string" ? body.detail : "Gagal menghapus hasil analisis.",
      );
      return;
    }
    overlayCache.current.clear();
    s2TileCache.current.clear();
    setShowS2TrueColor(false);
    setS2TileUrl(null);
    setResult(null);
    setOverlay(null);
    setErrorMsg(null);
    setState("idle");
  }, [polygonId]);

  const chartData = useMemo(() => (result ? buildChartData(result.table) : []), [result]);
  const overlayEmpty = state === "done" && overlay !== null && overlay.features.length === 0;
  const usedRandomForest = result != null && Number(result.meta.model_trees ?? 0) > 0;

  // Kelas yang tidak pernah punya luas berarti (>= 0,5 ha) di poligon ini --
  // disembunyikan dari tabel/grafik/kartu supaya baris "0 ha" tidak merebut
  // atensi dari kelas yang beneran berdampak (ambang sama dengan backend
  // _MEANINGFUL_HA di land_cover_service.py::_build_summary_text).
  const visibleClasses = useMemo(() => {
    if (!result) return LAND_COVER_CLASSES;
    return LAND_COVER_CLASSES.filter((c) =>
      LAND_COVER_YEARS.some((y) => (result.table[String(y)]?.[c.key]?.area_ha ?? 0) >= 0.5),
    );
  }, [result]);
  const hiddenClassCount = LAND_COVER_CLASSES.length - visibleClasses.length;

  // Hasil dihitung dengan formula versi lama (server sudah pindah versi):
  // angkanya tetap sah dipakai, tapi tidak apple-to-apple dengan poligon yang
  // dianalisis pakai formula baru -- admin bisa hapus lalu jalankan lagi.
  const outdatedFormula =
    state === "done" &&
    currentFormulaVersion !== null &&
    (formulaVersion === null || formulaVersion < currentFormulaVersion);

  const nonAdminHint = (
    <p className="lc-busy" role="status">
      Menjalankan analisis hanya bisa dilakukan admin atau pengguna terdaftar.
    </p>
  );

  // Dedicated non-overlapping header bar
  const headerBar = (
    <header className="lc-header-bar">
      {/* Baris Utama: Judul & Subtitle Poligon di Kiri (beserta tombol Kembali di mobile), Aksi di Kanan */}
      <div className="lc-header-bar__main-row">
        <div className="lc-header-bar__identity">
          {onBack && (
            <button
              type="button"
              className="lc-back-btn"
              onClick={onBack}
              aria-label="Kembali ke daftar poligon"
            >
              ← Kembali ke Daftar
            </button>
          )}
          <div className="lc-header-bar__title-block">
            <h3 className="lc-header-bar__title">{polygonLabel ?? "Tutupan Lahan"}</h3>
            {polygonSublabel && (
              <span className="lc-header-bar__sublabel">{polygonSublabel}</span>
            )}
          </div>
        </div>

        <div className="lc-header-bar__actions">
          {outdatedFormula && (
            <span
              className="lc-formula-old"
              title={`Dihitung dengan formula v${formulaVersion ?? 1}; server sekarang memakai v${currentFormulaVersion}. Hapus hasil lalu jalankan lagi untuk memperbarui.`}
            >
              Metode lama (v{formulaVersion ?? 1})
            </span>
          )}
          {onOpenKpsDetail && (
            <button type="button" className="tl-detail-link" onClick={onOpenKpsDetail}>
              Lihat Detail KPS →
            </button>
          )}
          {state === "done" && allowAnalyze && (
            <button
              type="button"
              className="lc-rerun lc-rerun--danger"
              onClick={() => {
                if (
                  window.confirm(
                    "Hapus hasil analisis poligon ini? Setelah dihapus, analisis bisa dijalankan lagi dari awal.",
                  )
                ) {
                  void deleteResult();
                }
              }}
            >
              Hapus hasil
            </button>
          )}
        </div>
      </div>

      {/* Baris 3: Tab Tampilan (Peta, Tren, Split) & Quick Stat */}
      {state === "done" && (
        <div className="lc-header-bar__controls-row">
          <div className="lc-tabs" role="tablist" aria-label="Tampilan tutupan lahan">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "peta"}
              className={`lc-tab${tab === "peta" ? " lc-tab--active" : ""}`}
              onClick={() => setTab("peta")}
            >
              Peta Spasial
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "tren"}
              className={`lc-tab${tab === "tren" ? " lc-tab--active" : ""}`}
              onClick={() => setTab("tren")}
            >
              Tren Historis
            </button>
            {!isMobile && (
              <button
                type="button"
                role="tab"
                aria-selected={tab === "split"}
                className={`lc-tab${tab === "split" ? " lc-tab--active" : ""}`}
                onClick={() => setTab("split")}
              >
                Peta &amp; Tren (Split)
              </button>
            )}
          </div>

          {result && (() => {
            const curHutan = result.table?.[String(year)]?.hutan;
            if (!curHutan) return null;
            return (
              <div className="lc-quick-stat" title="Ringkasan Hasil Analisis Tutupan Lahan">
                <span className="lc-quick-stat__item">
                  <span className="lc-swatch-sm" style={{ background: landCoverColor("hutan") }} aria-hidden />
                  <span>Hutan {year}:</span>
                  <strong>{`${curHutan.pct.toFixed(0)}% (${Math.round(curHutan.area_ha).toLocaleString("id-ID")} ha)`}</strong>
                </span>
                <span className="lc-quick-stat__sep">·</span>
                <span className="lc-quick-stat__item">
                  <span>Δ Netto Hutan:</span>
                  <strong className={(result.net_change?.hutan ?? 0) < -0.5 ? "lc-delta--down" : (result.net_change?.hutan ?? 0) > 0.5 ? "lc-delta--up" : ""}>
                    {formatDelta(result.net_change?.hutan ?? 0)}
                  </strong>
                </span>
              </div>
            );
          })()}
        </div>
      )}
    </header>
  );

  if (state === "idle") {
    return (
      <section className="land-cover-panel land-cover-panel--stage">
        {headerBar}
        <div className="lc-state-center">
          <div className="lc-state-card">
            <div className="lc-state-icon">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
                <polygon points="12 2 2 7 12 12 22 7 12 2" />
                <polyline points="2 17 12 22 22 17" />
                <polyline points="2 12 12 17 22 12" />
              </svg>
            </div>
            <h3 className="lc-title">Tutupan Lahan 2021–2025</h3>
            <p className="lc-lede">
              Klasifikasi Sentinel-2 + Random Forest, 5 kelas. Sekali hitung per KPS,
              hasilnya tersimpan permanen.
            </p>
            {!allowAnalyze ? (
              nonAdminHint
            ) : (
              <div className="lc-state-actions">
                {busyElsewhere && (
                  <p className="lc-busy" role="status">
                    Ada analisis KPS/Hutan Adat lain sedang berjalan — harap tunggu sebentar,
                    biar kuota GEE &amp; server tidak dipakai bersamaan.
                  </p>
                )}
                <button
                  type="button"
                  className="lc-cta"
                  disabled={busyElsewhere}
                  onClick={() => void runAnalyze(false)}
                >
                  Jalankan Analisis
                </button>
              </div>
            )}
          </div>
        </div>
      </section>
    );
  }

  if (state === "running") {
    return (
      <section className="land-cover-panel land-cover-panel--stage">
        {headerBar}
        <div className="lc-state-center">
          <div className="lc-state-card">
            <div className="lc-state-spinner" aria-hidden />
            <h3 className="lc-title">Tutupan Lahan 2021–2025</h3>
            <div className="lc-running" aria-live="polite">
              <span className="lc-running__bar" aria-hidden />
              <p>Menghitung dari citra satelit… {step ?? "menyiapkan"}</p>
              <span className="lc-running__hint">
                Perlu 1–3 menit (lebih lama saat kuota GEE terbatas). Aman ditinggal —
                hasilnya tetap tersimpan.
              </span>
            </div>
            {allowAnalyze && (
              <button
                type="button"
                className="lc-rerun"
                onClick={() => {
                  if (window.confirm("Mulai ulang analisis? Proses yang sedang berjalan diabaikan.")) {
                    void runAnalyze(true);
                  }
                }}
              >
                Mulai ulang
              </button>
            )}
          </div>
        </div>
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="land-cover-panel land-cover-panel--stage">
        {headerBar}
        <div className="lc-state-center">
          <div className="lc-state-card">
            <div className="lc-state-icon lc-state-icon--error">
              <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            </div>
            <h3 className="lc-title">Tutupan Lahan 2021–2025</h3>
            <p className="lc-error" role="alert">
              {errorMsg ?? "Terjadi kesalahan saat analisis."}
            </p>
            {!allowAnalyze ? (
              nonAdminHint
            ) : (
              <div className="lc-state-actions">
                {busyElsewhere && (
                  <p className="lc-busy" role="status">
                    Ada analisis KPS/Hutan Adat lain sedang berjalan — harap tunggu sebentar,
                    biar kuota GEE &amp; server tidak dipakai bersamaan.
                  </p>
                )}
                <button
                  type="button"
                  className="lc-cta"
                  disabled={busyElsewhere}
                  onClick={() => void runAnalyze(false)}
                >
                  Coba lagi
                </button>
              </div>
            )}
          </div>
        </div>
      </section>
    );
  }

  const renderMapCanvas = () => (
    <div className={`lc-mapframe lc-mapframe--fill${isMobile ? " lc-mapframe--mobile" : ""}`}>
      <div className="lc-mapframe__canvas">
        <MapContainer
          {...SMOOTH_ZOOM_MAP_PROPS}
          center={[-2, 118]}
          zoom={5}
          zoomControl={false}
          attributionControl={false}
        >
          {BASEMAPS[basemap].layers.map((layer, idx) => (
            <TileLayer
              key={`${basemap}-${idx}`}
              url={layer.url}
              subdomains={"subdomains" in layer && layer.subdomains ? (layer.subdomains as readonly string[] as string[]) : ["a", "b", "c"]}
              maxZoom={layer.maxZoom}
            />
          ))}
          {showS2TrueColor && s2TileUrl && (
            <TileLayer
              key={`s2-truecolor-${polygonId}-${year}-${s2TileUrl}`}
              url={s2TileUrl}
              maxZoom={19}
            />
          )}
          {!isMobile && <ZoomControl position="bottomright" />}
          {outline && (
            <GeoJSON
              key={`outline-${polygonId}`}
              data={{ type: "Feature", geometry: outline } as never}
              style={() => ({
                color: "#E7E6C2",
                weight: 1.5,
                dashArray: "4 4",
                fill: false,
              })}
            />
          )}
          {overlay && overlay.features.length > 0 && (
            <GeoJSON
              key={`lc-${polygonId}-${year}`}
              ref={geoJsonRef}
              data={overlay as never}
              style={(feature) => {
                const c = landCoverColor(
                  (feature?.properties as { class_key?: string })?.class_key ?? "",
                );
                return {
                  color: c,
                  weight: overlayOpacity === 0 ? 0.5 : 0.75,
                  fillColor: c,
                  fillOpacity: overlayOpacity,
                };
              }}
            />
          )}
          <FitLandCover
            overlay={overlay}
            outline={outline}
            isMobile={isMobile}
            isHudCollapsed={isHudCollapsed}
          />
        </MapContainer>

        {overlayEmpty && (
          <p className="lc-map__empty">
            Rona kelas untuk {year} tidak tersedia — tutupan terlalu seragam atau
            petak di bawah ambang luas minimum.
          </p>
        )}

        {/* Basemap switcher rapi di pojok kanan atas peta */}
        <div
          className="basemap-switcher basemap-switcher--topright"
          role="group"
          aria-label="Basemap peta"
        >
          {(Object.keys(BASEMAPS) as BasemapKey[]).map((k) => (
            <button
              key={k}
              type="button"
              className={basemap === k ? "basemap-switcher-btn--active" : undefined}
              aria-pressed={basemap === k}
              onClick={() => setBasemap(k)}
            >
              {BASEMAPS[k].label}
            </button>
          ))}
        </div>

        {/* Satellite Timeline Player di bagian bawah kanvas peta */}
        <div className="lc-timeline-player" role="region" aria-label="Pemutar garis waktu satelit">
          <div className="lc-timeline-player__playback">
            <button
              type="button"
              className={`lc-playback-btn${isPlaying ? " lc-playback-btn--active" : ""}`}
              onClick={() => setIsPlaying((p) => !p)}
              title={isPlaying ? "Jeda animasi (2021–2025)" : "Putar animasi perubahan tutupan lahan 2021–2025"}
              aria-label={isPlaying ? "Jeda animasi" : "Putar animasi tahun"}
            >
              {isPlaying ? <PauseIcon /> : <PlayIcon />}
            </button>
            <button
              type="button"
              className="lc-step-btn"
              aria-label="Tahun sebelumnya"
              disabled={year <= FIRST_YEAR}
              onClick={() => {
                setIsPlaying(false);
                setYear((y) => Math.max(FIRST_YEAR, y - 1));
              }}
            >
              <Chevron dir="left" />
            </button>
            <button
              type="button"
              className="lc-step-btn"
              aria-label="Tahun berikutnya"
              disabled={year >= LAST_YEAR}
              onClick={() => {
                setIsPlaying(false);
                setYear((y) => Math.min(LAST_YEAR, y + 1));
              }}
            >
              <Chevron dir="right" />
            </button>
          </div>

          <div className="lc-timeline-player__track">
            <input
              type="range"
              className="lc-range lc-timeline-range"
              min={FIRST_YEAR}
              max={LAST_YEAR}
              step={1}
              value={year}
              aria-label="Tahun tutupan lahan"
              onChange={(e) => {
                setIsPlaying(false);
                setYear(Number(e.target.value));
              }}
            />
            <div className="lc-timeline-player__pills">
              {LAND_COVER_YEARS.map((y) => (
                <button
                  key={y}
                  type="button"
                  className={`lc-timeline-pill${year === y ? " lc-timeline-pill--active" : ""}`}
                  aria-pressed={year === y}
                  onClick={() => {
                    setIsPlaying(false);
                    setYear(y);
                  }}
                >
                  {y}
                </button>
              ))}
            </div>
          </div>

          <strong className="lc-timeline-year-glow">{year}</strong>
        </div>
      </div>

      {/* Floating Glass Layer & Legend Deck */}
      <div className={isMobile ? "lc-mobilecontrols" : `map-left-stack${isHudCollapsed ? " map-left-stack--collapsed" : ""}`}>
        {!isMobile && (
          <button
            type="button"
            className="lc-hud-toggle-btn"
            onClick={() => setIsHudCollapsed((v) => !v)}
            title={isHudCollapsed ? "Buka panel kontrol citra & legenda" : "Sembunyikan panel untuk melihat peta penuh"}
            aria-label={isHudCollapsed ? "Buka panel kontrol peta" : "Sembunyikan panel kontrol peta"}
          >
            <span className="lc-hud-toggle-title">
              {isHudCollapsed ? `🗺️ Layer & Legenda (${year})` : "🗺️ Citra & Legenda"}
            </span>
            <span className="lc-hud-toggle-action">
              {isHudCollapsed ? "Buka ▶" : "Sembunyikan ◀"}
            </span>
          </button>
        )}

        {(!isHudCollapsed || isMobile) && (
          <>
            {/* Kontrol Citra Satelit & Transparansi */}
            <div className="map-legend lc-layercard">
              <span className="map-legend-title">Citra Satelit &amp; Tampilan</span>

              <label className="lc-toggle-row">
                <input
                  type="checkbox"
                  className="lc-checkbox"
                  checked={showS2TrueColor}
                  aria-label="Citra Sentinel-2"
                  onChange={(e) => {
                    const checked = e.target.checked;
                    setShowS2TrueColor(checked);
                    if (checked && overlayOpacity > 0.45) {
                      setOverlayOpacity(0.35);
                    } else if (!checked && overlayOpacity <= 0.45) {
                      setOverlayOpacity(0.75);
                    }
                  }}
                />
                <div className="lc-toggle-text">
                  <span className="lc-toggle-title">Citra Sentinel-2 ({year})</span>
                  <span className="lc-toggle-sub">True Color RGB (Bebas Awan)</span>
                </div>
              </label>

              {showS2TrueColor && s2TileLoading && (
                <div className="lc-layer-status lc-layer-status--loading">
                  <span className="lc-layer-spinner" aria-hidden />
                  <span>Mengambil citra dari GEE…</span>
                </div>
              )}

              {showS2TrueColor && s2TileError && (
                <div className="lc-layer-status lc-layer-status--error">
                  <span>{s2TileError}</span>
                </div>
              )}

              <div className="lc-opacity-box">
                <div className="lc-opacity-box__head">
                  <span>Opasitas Rona</span>
                  <span className="lc-opacity-box__val">{Math.round(overlayOpacity * 100)}%</span>
                </div>
                <input
                  type="range"
                  className="lc-range lc-range--sm"
                  min={0}
                  max={100}
                  step={5}
                  value={Math.round(overlayOpacity * 100)}
                  aria-label="Opasitas rona tutupan lahan"
                  onChange={(e) => setOverlayOpacity(Number(e.target.value) / 100)}
                />
              </div>
            </div>

            {/* Legenda + luas per kelas TAHUN TERPILIH */}
            <div
              className="map-legend lc-legendcard"
              role="list"
              aria-label={`Luas per kelas tahun ${year}`}
            >
              <span className="map-legend-title">Tutupan Lahan {year}</span>
              {visibleClasses.map((c) => {
                const cell = result?.table[String(year)]?.[c.key];
                const negligible = !cell || cell.area_ha < 0.5;
                return (
                  <div
                    key={c.key}
                    role="listitem"
                    className={`map-legend-row lc-legendrow${negligible ? " lc-legendrow--zero" : ""}`}
                  >
                    <span className="lc-swatch" style={{ background: c.color }} aria-hidden />
                    <span className="lc-legendrow__label">{c.label}</span>
                    {negligible ? (
                      <span className="lc-legendrow__value">–</span>
                    ) : (
                      <span className="lc-legendrow__value">
                        <span className="lc-legendrow__ha">
                          {Math.round(cell!.area_ha).toLocaleString("id-ID")} ha
                        </span>
                        <span className="lc-legendrow__pct"> · {cell!.pct.toFixed(0)}%</span>
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );

  const renderAnalyticsDashboard = () => (
    <div className="lc-trend lc-trend--fill">
      {result && (
        <div className="lc-kpi-grid">
          <div className="lc-kpi-card">
            <span className="lc-kpi-label">Luas Poligon</span>
            <div className="lc-kpi-val">
              {Math.round(totalAreaHa).toLocaleString("id-ID")}{" "}
              <span className="lc-kpi-unit">ha</span>
            </div>
            <span className="lc-kpi-sub">Total petak KPS teranalisis</span>
          </div>

          <div className="lc-kpi-card">
            <span className="lc-kpi-label">Area Hutan ({LAST_YEAR})</span>
            <div className="lc-kpi-val">
              {forestLatest ? `${forestLatest.pct.toFixed(1)}%` : "–"}
            </div>
            <span className="lc-kpi-sub">
              {forestLatest ? `${Math.round(forestLatest.area_ha).toLocaleString("id-ID")} ha` : "–"}
            </span>
          </div>

          <div className="lc-kpi-card">
            <span className="lc-kpi-label">Dinamika Area ({FIRST_YEAR}→{LAST_YEAR})</span>
            <div className={`lc-kpi-val ${forestDelta < -0.5 ? "lc-delta--down" : forestDelta > 0.5 ? "lc-delta--up" : ""}`}>
              {formatDelta(forestDelta)}
            </div>
            <span className="lc-kpi-sub">
              {forestDelta < -0.5 ? "Penurunan area hutan" : forestDelta > 0.5 ? "Pertambahan area hutan" : "Area relatif stabil"}
            </span>
          </div>

          <div className="lc-kpi-card">
            <span className="lc-kpi-label">Model Satelit</span>
            <div className="lc-kpi-val lc-kpi-val--sm">
              {usedRandomForest ? "Random Forest" : "Biofisik"}
            </div>
            <span className="lc-kpi-sub">
              {usedRandomForest ? `${result.meta.model_trees} Pohon · Sentinel-2` : "Aturan Spektral S2+SAR"}
            </span>
          </div>
        </div>
      )}

      <div className="lc-trend-card">
        <div className="lc-trend-header">
          <h4>Tren Perubahan Tutupan Lahan (2021–2025)</h4>
          <span className="lc-trend-sub">Persentase luas (%) per tahun dari klasifikasi citra Sentinel-2</span>
        </div>
        <div className="lc-chart">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData} margin={{ top: 8, right: 10, bottom: 0, left: -18 }}>
              <XAxis
                dataKey="year"
                tick={{ fontSize: 11, fill: "rgba(245,239,230,0.6)" }}
                tickLine={false}
                axisLine={{ stroke: "rgba(255,255,255,0.12)" }}
              />
              <YAxis
                width={40}
                domain={[0, 100]}
                ticks={[0, 25, 50, 75, 100]}
                tickFormatter={(v) => `${v}%`}
                tick={{ fontSize: 11, fill: "rgba(245,239,230,0.6)" }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                cursor={{ stroke: "rgba(255,255,255,0.15)" }}
                content={<LandCoverTooltip />}
                wrapperStyle={{ outline: "none" }}
              />
              {visibleClasses.map((c) => (
                <Line
                  key={c.key}
                  type="monotone"
                  dataKey={c.key}
                  stroke={c.color}
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: c.color }}
                  activeDot={{ r: 5 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {result && (
        <div className="lc-table-card">
          <div className="lc-trend-header">
            <h4>Tabel Rincian Luas &amp; Perubahan Netto</h4>
          </div>
          <div className="lc-table-wrap">
            <table className="lc-table">
              <thead>
                <tr>
                  <th scope="col">Kelas</th>
                  {LAND_COVER_YEARS.map((y) => (
                    <th key={y} scope="col">
                      {y}
                    </th>
                  ))}
                  <th scope="col">
                    Δ {FIRST_YEAR}→{LAST_YEAR}
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleClasses.map((c) => {
                  const delta = result.net_change[c.key] ?? 0;
                  return (
                    <tr key={c.key}>
                      <th scope="row">
                        <span className="lc-swatch" style={{ background: c.color }} aria-hidden />
                        {c.label}
                      </th>
                      {LAND_COVER_YEARS.map((y) => {
                        const cell = result.table[String(y)]?.[c.key];
                        const negligible = !cell || cell.area_ha < 0.5;
                        return (
                          <td key={y}>
                            {negligible ? (
                              "–"
                            ) : (
                              <div className="lc-cell">
                                <span className="lc-cell__ha">{Math.round(cell!.area_ha)} ha</span>
                                <span className="lc-cell__pct">{cell!.pct.toFixed(1)}%</span>
                              </div>
                            )}
                          </td>
                        );
                      })}
                      <td
                        className={
                          delta > 0.5 ? "lc-delta lc-delta--up" : delta < -0.5 ? "lc-delta lc-delta--down" : "lc-delta"
                        }
                      >
                        {formatDelta(delta)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {hiddenClassCount > 0 && (
              <p className="lc-hidden-note">
                {hiddenClassCount} kelas lain tidak ditemukan di poligon ini.
              </p>
            )}
          </div>
        </div>
      )}

      {result && (
        <div className="lc-summary-card">
          <div className="lc-summary-card__head">
            <span className="lc-summary-card__tag">IKHTISAR ANALISIS</span>
          </div>
          <p className="lc-summary">{result.summary_text}</p>
        </div>
      )}

      <p className="lc-note">
        5 kelas tutupan lahan mandiri ETA SENEU (Hutan, Pertanian/Perkebunan,
        Semak/Belukar, Lahan Basah/Perairan, Lahan Terbuka) dianalisis langsung
        dari citra Sentinel-2 L2A &amp; radar Sentinel-1 SAR tanpa ketergantungan
        model pihak ketiga. Estimasi satelit, bukan angka resmi.
      </p>

      {result && (
        <p className="lc-foot">
          {usedRandomForest
            ? `Random Forest ${result.meta.model_trees} pohon · ${result.meta.n_training} titik latih · OOB ${
                result.meta.oob_accuracy != null
                  ? Number(result.meta.oob_accuracy).toFixed(2)
                  : "–"
              }`
            : "Aturan Spektral Biofisik (Decision Tree) — poligon homogen"}
          {result.meta.computed_at
            ? ` · ${new Date(String(result.meta.computed_at)).toLocaleDateString("id-ID", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}`
            : ""}
        </p>
      )}
    </div>
  );

  return (
    <section
      className={`land-cover-panel land-cover-panel--stage${
        tab === "split" ? " land-cover-panel--split-active" : ""
      }`}
    >
      {headerBar}
      {tab === "peta" && renderMapCanvas()}
      {tab === "tren" && renderAnalyticsDashboard()}
      {tab === "split" && (
        <div className="lc-split-stage">
          <div className="lc-split-stage__map">{renderMapCanvas()}</div>
          <div className="lc-split-stage__analytics">{renderAnalyticsDashboard()}</div>
        </div>
      )}
    </section>
  );
}
