import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { geoJSON as buildLeafletGeoJSON } from "leaflet";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import {
  LAND_COVER_CLASSES,
  LAND_COVER_YEARS,
  type LandCoverClassKey,
} from "../constants/landCover";
import { SMOOTH_ZOOM_MAP_PROPS } from "../constants/map";
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

// fitBounds butuh instance peta, jadi harus komponen anak MapContainer (pola
// sama dengan FitToPolygon di KpsDetailView.tsx). Fit ke rona kelas kalau ada,
// kalau tidak ke outline poligon.
function FitLandCover({
  overlay,
  outline,
}: {
  overlay: OverlayFC | null;
  outline: Record<string, unknown> | null;
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
        map.fitBounds(bounds, { padding: [24, 24], maxZoom: 15 });
      }
    } catch {
      /* geometri tak valid — peta tetap di posisi default */
    }
  }, [overlay, outline, map]);
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

export function LandCoverPanel({ polygonId }: { polygonId: number }): JSX.Element {
  const [state, setState] = useState<State>("idle");
  const [step, setStep] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [busyElsewhere, setBusyElsewhere] = useState(false);
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [tab, setTab] = useState<"peta" | "tren">("peta");
  const [year, setYear] = useState<number>(LAST_YEAR);
  const [overlay, setOverlay] = useState<OverlayFC | null>(null);
  const [outline, setOutline] = useState<Record<string, unknown> | null>(null);
  const overlayCache = useRef<Map<number, OverlayFC>>(new Map());
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async (): Promise<State> => {
    const res = await authFetch(`/api/land-cover/status?polygon_id=${polygonId}`);
    const body = (await res.json()) as StatusResponse;
    setState(body.state);
    setStep(body.step);
    setErrorMsg(body.error);
    setBusyElsewhere(Boolean(body.busy_elsewhere));
    return body.state;
  }, [polygonId]);

  useEffect(() => {
    overlayCache.current.clear();
    setResult(null);
    setOverlay(null);
    setOutline(null);
    setYear(LAST_YEAR);
    setTab("peta");
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

  if (state === "idle") {
    return (
      <section className="land-cover-panel">
        <h3 className="lc-title">Tutupan Lahan 2021–2025</h3>
        <p className="lc-lede">
          Klasifikasi Sentinel-2 + Random Forest, 5 kelas. Sekali hitung per KPS,
          hasilnya tersimpan permanen.
        </p>
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
      </section>
    );
  }

  if (state === "running") {
    return (
      <section className="land-cover-panel">
        <h3 className="lc-title">Tutupan Lahan 2021–2025</h3>
        <div className="lc-running" aria-live="polite">
          <span className="lc-running__bar" aria-hidden />
          <p>Menghitung dari citra satelit… {step ?? "menyiapkan"}</p>
          <span className="lc-running__hint">
            Perlu 1–3 menit (lebih lama saat kuota GEE terbatas). Aman ditinggal —
            hasilnya tetap tersimpan.
          </span>
        </div>
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
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="land-cover-panel">
        <h3 className="lc-title">Tutupan Lahan 2021–2025</h3>
        <p className="lc-error" role="alert">
          {errorMsg ?? "Terjadi kesalahan saat analisis."}
        </p>
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
      </section>
    );
  }

  return (
    <section className="land-cover-panel">
      <header className="lc-head">
        <h3 className="lc-title">Tutupan Lahan 2021–2025</h3>
        <button
          type="button"
          className="lc-rerun"
          disabled={busyElsewhere}
          title={busyElsewhere ? "Ada analisis lain sedang berjalan, coba lagi nanti" : undefined}
          onClick={() => {
            if (window.confirm("Analisis ulang poligon ini? Hasil lama akan ditimpa.")) {
              void runAnalyze(true);
            }
          }}
        >
          Analisis ulang
        </button>
      </header>

      {busyElsewhere && (
        <p className="lc-busy" role="status">
          Ada analisis KPS/Hutan Adat lain sedang berjalan — harap tunggu sebentar sebelum
          menjalankan ulang.
        </p>
      )}

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
      </div>

      {tab === "peta" ? (
        <div className="lc-mapstage">
          <div className="lc-mapstage__toolbar">
            <button
              type="button"
              className="lc-step"
              aria-label="Tahun sebelumnya"
              disabled={year <= FIRST_YEAR}
              onClick={() => setYear((y) => Math.max(FIRST_YEAR, y - 1))}
            >
              <Chevron dir="left" />
            </button>
            <input
              type="range"
              className="lc-range"
              min={FIRST_YEAR}
              max={LAST_YEAR}
              step={1}
              value={year}
              aria-label="Tahun tutupan lahan"
              onChange={(e) => setYear(Number(e.target.value))}
            />
            <button
              type="button"
              className="lc-step"
              aria-label="Tahun berikutnya"
              disabled={year >= LAST_YEAR}
              onClick={() => setYear((y) => Math.min(LAST_YEAR, y + 1))}
            >
              <Chevron dir="right" />
            </button>
            <strong className="lc-year">{year}</strong>
          </div>

          <MapContainer
            {...SMOOTH_ZOOM_MAP_PROPS}
            center={[-2, 118]}
            zoom={5}
            attributionControl={false}
          >
            <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}" />
            {outline && (
              <GeoJSON
                key={`outline-${polygonId}`}
                data={{ type: "Feature", geometry: outline } as never}
                style={() => ({
                  color: "#f5efe6",
                  weight: 1.5,
                  dashArray: "4 4",
                  fill: false,
                })}
              />
            )}
            {overlay && overlay.features.length > 0 && (
              <GeoJSON
                key={`lc-${year}`}
                data={overlay as never}
                style={(feature) => {
                  const c = landCoverColor(
                    (feature?.properties as { class_key?: string })?.class_key ?? "",
                  );
                  return { color: c, weight: 0.75, fillColor: c, fillOpacity: 0.8 };
                }}
              />
            )}
            <FitLandCover overlay={overlay} outline={outline} />
          </MapContainer>
          {overlayEmpty && (
            <p className="lc-map__empty">
              Rona kelas untuk {year} tidak tersedia — tutupan terlalu seragam atau
              petak di bawah ambang luas minimum.
            </p>
          )}

          {/* Luas per kelas TAHUN TERPILIH, langsung kebaca tanpa hover
              grafik atau pindah tab -- ini yang paling sering dicari orang
              pertama kali ("berapa hektar hutannya sekarang?"). */}
          <div className="lc-floatcard">
            <ul className="lc-classgrid" aria-label={`Luas per kelas tahun ${year}`}>
              {visibleClasses.map((c) => {
                const cell = result?.table[String(year)]?.[c.key];
                const negligible = !cell || cell.area_ha < 0.5;
                return (
                  <li
                    key={c.key}
                    className={`lc-classgrid__item${negligible ? " lc-classgrid__item--zero" : ""}`}
                  >
                    <span className="lc-swatch" style={{ background: c.color }} aria-hidden />
                    <span className="lc-classgrid__label">{c.label}</span>
                    <span className="lc-classgrid__value">
                      {negligible ? "–" : `${Math.round(cell!.area_ha).toLocaleString("id-ID")} ha`}
                    </span>
                    <span className="lc-classgrid__pct">
                      {negligible ? "" : `${cell!.pct.toFixed(1)}%`}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      ) : (
        <div className="lc-trend">
          <div className="lc-chart">
            <ResponsiveContainer width="100%" height={220}>
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
                    strokeWidth={2}
                    dot={false}
                    isAnimationActive={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>

          {result && (
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
          )}

          {result && <p className="lc-summary">{result.summary_text}</p>}

          <p className="lc-note">
            &quot;Hutan&quot; = tutupan berpohon; kebun berpohon (sawit/karet) belum
            tentu terpisah. Estimasi satelit, bukan angka resmi.
          </p>

          {result && (
            <p className="lc-foot">
              {usedRandomForest
                ? `Random Forest ${result.meta.model_trees} pohon · ${result.meta.n_training} titik latih · OOB ${
                    result.meta.oob_accuracy != null
                      ? Number(result.meta.oob_accuracy).toFixed(2)
                      : "–"
                  }`
                : "Dynamic World langsung — area terlalu seragam untuk melatih Random Forest"}
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
      )}
    </section>
  );
}
