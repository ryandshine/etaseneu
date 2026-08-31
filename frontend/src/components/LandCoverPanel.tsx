import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { geoJSON as buildLeafletGeoJSON } from "leaflet";
import { GeoJSON, MapContainer, TileLayer, useMap } from "react-leaflet";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

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
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [year, setYear] = useState<number>(LAST_YEAR);
  const [overlay, setOverlay] = useState<OverlayFC | null>(null);
  const [outline, setOutline] = useState<Record<string, unknown> | null>(null);
  const overlayCache = useRef<Map<number, OverlayFC>>(new Map());
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchStatus = useCallback(async (): Promise<State> => {
    const res = await authFetch(`/api/land-cover/status?polygon_id=${polygonId}`);
    const body = (await res.json()) as StatusResponse;
    setState(body.state);
    setStep(body.step);
    setErrorMsg(body.error);
    return body.state;
  }, [polygonId]);

  useEffect(() => {
    overlayCache.current.clear();
    setResult(null);
    setOverlay(null);
    setOutline(null);
    setYear(LAST_YEAR);
    void fetchStatus();
    void authFetch(`/api/polygons/${polygonId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body: { geometry?: Record<string, unknown> } | null) => {
        if (body?.geometry) setOutline(body.geometry);
      })
      .catch(() => undefined);
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [fetchStatus, polygonId]);

  useEffect(() => {
    if (state !== "running") return;
    pollTimer.current = setTimeout(() => void fetchStatus(), POLL_MS);
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [state, step, fetchStatus]);

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

  if (state === "idle") {
    return (
      <section className="land-cover-panel">
        <h3 className="lc-title">Tutupan Lahan 2020–2025</h3>
        <p className="lc-lede">
          Klasifikasi Sentinel-2 + Random Forest, 5 kelas. Sekali hitung per KPS,
          hasilnya tersimpan permanen.
        </p>
        <button type="button" className="lc-cta" onClick={() => void runAnalyze(false)}>
          Jalankan Analisis
        </button>
      </section>
    );
  }

  if (state === "running") {
    return (
      <section className="land-cover-panel">
        <h3 className="lc-title">Tutupan Lahan 2020–2025</h3>
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
        <h3 className="lc-title">Tutupan Lahan 2020–2025</h3>
        <p className="lc-error" role="alert">
          {errorMsg ?? "Terjadi kesalahan saat analisis."}
        </p>
        <button type="button" className="lc-cta" onClick={() => void runAnalyze(false)}>
          Coba lagi
        </button>
      </section>
    );
  }

  return (
    <section className="land-cover-panel">
      <header className="lc-head">
        <h3 className="lc-title">Tutupan Lahan 2020–2025</h3>
        <button
          type="button"
          className="lc-rerun"
          onClick={() => {
            if (window.confirm("Analisis ulang poligon ini? Hasil lama akan ditimpa.")) {
              void runAnalyze(true);
            }
          }}
        >
          Analisis ulang
        </button>
      </header>

      <div className="lc-yearbar">
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

      <div className="lc-map">
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
      </div>

      <ul className="lc-legend" aria-label="Legenda kelas tutupan lahan">
        {LAND_COVER_CLASSES.map((c) => (
          <li key={c.key}>
            <span className="lc-swatch" style={{ background: c.color }} aria-hidden />
            {c.label}
          </li>
        ))}
      </ul>

      <div className="lc-chart">
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={chartData} margin={{ top: 8, right: 6, bottom: 0, left: -18 }} barCategoryGap="22%">
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
              cursor={{ fill: "rgba(255,255,255,0.06)" }}
              content={<LandCoverTooltip />}
              wrapperStyle={{ outline: "none" }}
            />
            {LAND_COVER_CLASSES.map((c) => (
              <Bar
                key={c.key}
                dataKey={c.key}
                stackId="lc"
                fill={c.color}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
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
              {LAND_COVER_CLASSES.map((c) => {
                const delta = result.net_change[c.key] ?? 0;
                return (
                  <tr key={c.key}>
                    <th scope="row">
                      <span className="lc-swatch" style={{ background: c.color }} aria-hidden />
                      {c.label}
                    </th>
                    {LAND_COVER_YEARS.map((y) => {
                      const cell = result.table[String(y)]?.[c.key];
                      return (
                        <td key={y}>
                          {cell ? (
                            <>
                              {Math.round(cell.area_ha)}
                              <span className="lc-pct"> {cell.pct.toFixed(1)}%</span>
                            </>
                          ) : (
                            "–"
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
    </section>
  );
}
