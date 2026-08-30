import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GeoJSON, MapContainer, TileLayer } from "react-leaflet";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { LAND_COVER_CLASSES, LAND_COVER_YEARS } from "../constants/landCover";
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

type OverlayFC = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: unknown;
    properties: { class_key: string; area_ha: number; pct: number };
  }>;
};

const POLL_MS = 5000;
const FIRST_YEAR = LAND_COVER_YEARS[0];
const LAST_YEAR = LAND_COVER_YEARS[LAND_COVER_YEARS.length - 1];

export function LandCoverPanel({ polygonId }: { polygonId: number }): JSX.Element {
  const [state, setState] = useState<State>("idle");
  const [step, setStep] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [result, setResult] = useState<ResultResponse | null>(null);
  const [year, setYear] = useState<number>(LAST_YEAR);
  const [overlay, setOverlay] = useState<OverlayFC | null>(null);
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
    setYear(LAST_YEAR);
    void fetchStatus();
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, [fetchStatus]);

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

  const chartData = useMemo(
    () => (result ? buildChartData(result.table) : []),
    [result],
  );

  if (state === "idle") {
    return (
      <section className="land-cover-panel">
        <h3>Tutupan Lahan 2020–2025 (Sentinel-2 + Random Forest)</h3>
        <p>Belum dianalisis.</p>
        <button type="button" onClick={() => void runAnalyze(false)}>
          Jalankan Analisis
        </button>
      </section>
    );
  }

  if (state === "running") {
    return (
      <section className="land-cover-panel">
        <h3>Tutupan Lahan 2020–2025</h3>
        <p aria-live="polite">Menghitung… {step ?? ""}</p>
      </section>
    );
  }

  if (state === "error") {
    return (
      <section className="land-cover-panel">
        <h3>Tutupan Lahan 2020–2025</h3>
        <p role="alert">{errorMsg ?? "Terjadi kesalahan."}</p>
        <button type="button" onClick={() => void runAnalyze(false)}>
          Coba lagi
        </button>
      </section>
    );
  }

  return (
    <section className="land-cover-panel">
      <header className="land-cover-panel__head">
        <h3>Tutupan Lahan 2020–2025</h3>
        <button
          type="button"
          className="land-cover-panel__rerun"
          onClick={() => {
            if (
              window.confirm("Analisis ulang poligon ini? Hasil lama akan ditimpa.")
            ) {
              void runAnalyze(true);
            }
          }}
        >
          ↻ Analisis ulang
        </button>
      </header>

      <div className="land-cover-panel__map">
        <div className="land-cover-panel__yearbar">
          <button
            type="button"
            aria-label="Tahun sebelumnya"
            onClick={() => setYear((y) => Math.max(FIRST_YEAR, y - 1))}
          >
            ◀
          </button>
          <input
            type="range"
            min={FIRST_YEAR}
            max={LAST_YEAR}
            step={1}
            value={year}
            aria-label="Tahun tutupan lahan"
            onChange={(e) => setYear(Number(e.target.value))}
          />
          <button
            type="button"
            aria-label="Tahun berikutnya"
            onClick={() => setYear((y) => Math.min(LAST_YEAR, y + 1))}
          >
            ▶
          </button>
          <strong>{year}</strong>
        </div>
        <MapContainer
          {...SMOOTH_ZOOM_MAP_PROPS}
          style={{ height: 260 }}
          center={[-2, 118]}
          zoom={9}
        >
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {overlay && (
            <GeoJSON
              key={year}
              data={overlay as never}
              style={(feature) => {
                const c = landCoverColor(
                  (feature?.properties as { class_key?: string })?.class_key ?? "",
                );
                return { color: c, weight: 1, fillColor: c, fillOpacity: 0.75 };
              }}
            />
          )}
        </MapContainer>
      </div>

      <ul
        className="land-cover-panel__legend"
        aria-label="Legenda kelas tutupan lahan"
      >
        {LAND_COVER_CLASSES.map((c) => (
          <li key={c.key}>
            <span style={{ background: c.color }} aria-hidden />
            {c.label}
          </li>
        ))}
      </ul>

      <div className="land-cover-panel__chart">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData}>
            <XAxis dataKey="year" />
            <YAxis unit="%" />
            <Tooltip />
            {LAND_COVER_CLASSES.map((c) => (
              <Bar key={c.key} dataKey={c.key} stackId="lc" fill={c.color} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      {result && (
        <table className="land-cover-panel__table">
          <thead>
            <tr>
              <th>Kelas</th>
              {LAND_COVER_YEARS.map((y) => (
                <th key={y}>{y}</th>
              ))}
              <th>
                Δ {FIRST_YEAR}→{LAST_YEAR}
              </th>
            </tr>
          </thead>
          <tbody>
            {LAND_COVER_CLASSES.map((c) => (
              <tr key={c.key}>
                <th scope="row">
                  <span style={{ background: c.color }} aria-hidden /> {c.label}
                </th>
                {LAND_COVER_YEARS.map((y) => {
                  const cell = result.table[String(y)]?.[c.key];
                  return (
                    <td key={y}>
                      {cell
                        ? `${Math.round(cell.area_ha)} (${cell.pct.toFixed(1)}%)`
                        : "–"}
                    </td>
                  );
                })}
                <td>{formatDelta(result.net_change[c.key] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {result && <p className="land-cover-panel__summary">{result.summary_text}</p>}
      <p className="land-cover-panel__note">
        &quot;Hutan&quot; = tutupan berpohon; kebun berpohon belum tentu terpisah.
        Estimasi satelit, bukan angka resmi.
      </p>
      {result && (
        <p className="land-cover-panel__foot">
          Sumber: {String(result.meta.source ?? "")} · Guru label:{" "}
          {String(result.meta.label_source ?? "")} · RF{" "}
          {String(result.meta.model_trees ?? "")} pohon ·{" "}
          {String(result.meta.n_training ?? "")} titik · OOB{" "}
          {result.meta.oob_accuracy != null
            ? Number(result.meta.oob_accuracy).toFixed(2)
            : "-"}
          {result.meta.computed_at
            ? ` · ${new Date(String(result.meta.computed_at)).toLocaleString("id-ID")}`
            : ""}
        </p>
      )}
    </section>
  );
}
