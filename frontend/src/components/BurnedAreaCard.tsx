import { useEffect, useMemo, useState } from "react";
import { authFetch } from "../lib/api";
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, XAxis, YAxis } from "recharts";

import type { BurnedAreaOverlayFeature } from "../hooks/useBurnedAreaOverlay";

const SKEMA_COLORS: Record<string, string> = {
  PPHD: "#dc2626",
  PPHKm: "#f97316",
  PPHTR: "#f59e0b",
  PPHA: "#eab308",
  PPKKPS: "#fb7185"
};

const FALLBACK_COLOR = "#dc2626";

function formatHa(value: number): string {
  return new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 }).format(value);
}

type BurnedAreaCardProps = {
  /** Disaring ke provinsi/skema yang sedang aktif di toolbar matriks, supaya
   *  kartu ini ikut konteks yang sedang dilihat -- bukan selalu angka nasional
   *  yang tidak nyambung dengan tabel di bawahnya. */
  provinceFilter: string;
  skemaFilter: string;
  onSelectSkema: (label: string) => void;
};

export function BurnedAreaCard({ provinceFilter, skemaFilter, onSelectSkema }: BurnedAreaCardProps) {
  const [features, setFeatures] = useState<BurnedAreaOverlayFeature[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    // Satu panggilan untuk semua: rekap per skema DAN peringkat KPS di bawah
    // dihitung dari data yang sama, jadi tidak perlu dua endpoint terpisah.
    authFetch("/api/burned-area/map-overlay")
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: { features?: BurnedAreaOverlayFeature[] } | null) => {
        if (!active) {
          return;
        }
        if (payload?.features) {
          setFeatures(payload.features);
        } else {
          setFailed(true);
        }
      })
      .catch(() => {
        if (active) {
          setFailed(true);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  const scoped = useMemo(() => {
    if (!features) {
      return [];
    }
    return features.filter((feature) => {
      const provinceMatch = provinceFilter
        ? (feature.properties.nama_prov ?? "") === provinceFilter
        : true;
      const skemaMatch = skemaFilter ? (feature.properties.skema ?? "") === skemaFilter : true;
      return provinceMatch && skemaMatch;
    });
  }, [features, provinceFilter, skemaFilter]);

  const bySkema = useMemo(() => {
    const totals = new Map<string, { ha: number; kps: number }>();
    scoped.forEach((feature) => {
      const skema = feature.properties.skema ?? "Lainnya";
      const current = totals.get(skema) ?? { ha: 0, kps: 0 };
      totals.set(skema, {
        ha: current.ha + feature.properties.burned_area_ha,
        kps: current.kps + 1
      });
    });
    return [...totals.entries()]
      .map(([label, value]) => ({ label, value: Math.round(value.ha * 10) / 10, kps: value.kps }))
      .sort((a, b) => b.value - a.value);
  }, [scoped]);

  const topKps = useMemo(
    () =>
      [...scoped]
        .sort((a, b) => b.properties.burned_area_ha - a.properties.burned_area_ha)
        .slice(0, 5),
    [scoped]
  );

  const totalHa = useMemo(
    () => scoped.reduce((sum, feature) => sum + feature.properties.burned_area_ha, 0),
    [scoped]
  );

  const chartHeight = Math.max(120, bySkema.length * 46 + 30);

  return (
    <section
      className="matrix-chart-card matrix-chart-card--wide glass-panel"
      style={{ display: "flex", flexDirection: "column" }}
    >
      <div className="matrix-chart-card__header">
        <div>
          <p className="panel-eyebrow">Dampak Kebakaran</p>
          <h3>Luas Bekas Terbakar per Skema</h3>
        </div>
        {scoped.length > 0 ? (
          <p className="skema-matrix__meta">
            {formatHa(Math.round(totalHa))} Ha · {scoped.length} KPS terdampak
          </p>
        ) : null}
      </div>

      {features === null && !failed ? (
        <div className="matrix-empty matrix-empty--card">Memuat data luas terbakar…</div>
      ) : failed ? (
        <div className="matrix-empty matrix-empty--card">Data luas terbakar tidak tersedia.</div>
      ) : scoped.length === 0 ? (
        <div className="matrix-empty matrix-empty--card">
          Tidak ada kawasan terbakar terdeteksi pada filter ini.
        </div>
      ) : (
        <>
          <p className="skema-matrix__lead">
            Terluas pada skema <strong>{bySkema[0]?.label}</strong> ({formatHa(bySkema[0]?.value ?? 0)} Ha ·{" "}
            {bySkema[0]?.kps} KPS). Klik batang untuk menyaring matriks per skema.
          </p>

          <div style={{ width: "100%", height: chartHeight, position: "relative" }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={bySkema}
                layout="vertical"
                margin={{ top: 4, right: 64, left: 4, bottom: 4 }}
                onClick={(state) => {
                  if (state && state.activeLabel) {
                    onSelectSkema(String(state.activeLabel));
                  }
                }}
              >
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={72}
                  stroke="rgba(255,255,255,0.2)"
                  tick={{ fill: "rgba(255,255,255,0.62)", fontSize: 11, fontFamily: "Plus Jakarta Sans, sans-serif" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Bar
                  dataKey="value"
                  radius={[0, 4, 4, 0]}
                  barSize={18}
                  background={{ fill: "rgba(255,255,255,0.03)", radius: 4 }}
                  style={{ cursor: "pointer" }}
                >
                  <LabelList
                    dataKey="value"
                    position="right"
                    formatter={(value: unknown) => `${formatHa(Number(value) || 0)} Ha`}
                    fill="rgba(255,255,255,0.72)"
                    fontSize={10}
                    fontFamily="Plus Jakarta Sans, sans-serif"
                  />
                  {bySkema.map((entry) => (
                    <Cell
                      key={entry.label}
                      fill={SKEMA_COLORS[entry.label] ?? FALLBACK_COLOR}
                      opacity={skemaFilter && skemaFilter !== entry.label ? 0.45 : 1}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="burned-top-list">
            <p className="matrix-spark-title">KPS Terdampak Terluas</p>
            {topKps.map((feature) => {
              const props = feature.properties;
              const share = totalHa ? (props.burned_area_ha / totalHa) * 100 : 0;
              return (
                <div key={props.polygon_metadata_id} className="burned-top-row">
                  <div className="burned-top-row__meta">
                    <span className="burned-top-row__name">{props.lembaga ?? "-"}</span>
                    <span className="burned-top-row__sub">
                      {props.skema ?? "-"} · {props.nama_prov ?? "-"}
                      {props.is_estimated ? " · perkiraan" : ""}
                    </span>
                  </div>
                  <div className="burned-top-row__bar">
                    <span style={{ width: `${Math.max(3, share)}%` }} />
                  </div>
                  <span className="burned-top-row__value">{formatHa(Math.round(props.burned_area_ha * 10) / 10)} Ha</span>
                </div>
              );
            })}
          </div>

          <p className="help-copy" style={{ marginTop: "0.6rem", fontSize: "0.68rem" }}>
            Sumber: Kementerian Kehutanan — Areal Kebakaran Hutan dan Lahan (akurasi H/M, terverifikasi hotspot). Luas
            dihitung sekali per kawasan walau terbakar berulang, jadi tidak bisa dijumlahkan langsung
            dengan jumlah titik hotspot.
          </p>
        </>
      )}
    </section>
  );
}
