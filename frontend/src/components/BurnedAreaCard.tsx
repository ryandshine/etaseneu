import { useEffect, useMemo, useState } from "react";
import { authFetch } from "../lib/api";

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
  /** Disaring ke provinsi/skema/wilker yang sedang aktif di toolbar matriks, supaya
   *  kartu ini ikut konteks yang sedang dilihat -- bukan selalu angka nasional
   *  yang tidak nyambung dengan tabel di bawahnya. */
  provinceFilter: string;
  skemaFilter: string;
  wilkerFilter?: string;
  onSelectSkema: (label: string) => void;
};

function normalizeWilker(val?: string | null): string {
  if (!val) return "";
  const clean = val.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (clean.includes("kutai") || clean.includes("kurtanegara")) return "kutaikartanegara";
  return clean;
}

function matchWilker(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return false;
  return normalizeWilker(a) === normalizeWilker(b);
}

export function BurnedAreaCard({ provinceFilter, skemaFilter, wilkerFilter, onSelectSkema }: BurnedAreaCardProps) {
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
        ? (feature.properties.nama_prov ?? "").trim().toLowerCase() === provinceFilter.trim().toLowerCase()
        : true;
      const skemaMatch = skemaFilter ? (feature.properties.skema ?? "").trim().toLowerCase() === skemaFilter.trim().toLowerCase() : true;
      const wilkerMatch = wilkerFilter
        ? matchWilker(feature.properties.wilker_bps, wilkerFilter)
        : true;
      return provinceMatch && skemaMatch && wilkerMatch;
    });
  }, [features, provinceFilter, skemaFilter, wilkerFilter]);

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

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem', margin: '0.6rem 0 1.25rem' }}>
            {bySkema.map((entry) => {
              const pct = totalHa > 0 ? Math.round((entry.value / totalHa) * 100) : 0;
              const maxVal = bySkema[0]?.value || 1;
              const barWidth = Math.max((entry.value / maxVal) * 100, 2);
              const color = SKEMA_COLORS[entry.label] ?? FALLBACK_COLOR;
              const isSelected = skemaFilter === entry.label;
              const isDimmed = skemaFilter && !isSelected;

              return (
                <div
                  key={entry.label}
                  onClick={() => onSelectSkema(entry.label)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '0.35rem',
                    padding: '0.35rem 0.5rem',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    backgroundColor: isSelected ? 'rgba(255, 255, 255, 0.08)' : 'transparent',
                    border: isSelected ? '1px solid rgba(255, 255, 255, 0.15)' : '1px solid transparent',
                    opacity: isDimmed ? 0.45 : 1,
                    transition: 'all 150ms ease'
                  }}
                  title={`Saring skema ${entry.label}`}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: '0.84rem' }}>
                    <span style={{ color: '#e5e7eb', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '2px', backgroundColor: color, flexShrink: 0 }} />
                      <span>{entry.label}</span>
                      <span style={{ color: '#9ca3af', fontWeight: '400', fontSize: '0.74rem' }}>({entry.kps} KPS)</span>
                    </span>
                    <span style={{ color: '#ffffff', fontWeight: '700', fontSize: '0.82rem', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
                      {formatHa(entry.value)} Ha{" "}
                      <span style={{ color: '#9ca3af', fontWeight: '400', fontSize: '0.74rem' }}>
                        ({pct}%)
                      </span>
                    </span>
                  </div>
                  <div
                    style={{
                      width: '100%',
                      height: '8px',
                      backgroundColor: 'rgba(255, 255, 255, 0.07)',
                      borderRadius: '999px',
                      overflow: 'hidden'
                    }}
                  >
                    <div
                      style={{
                        width: `${barWidth}%`,
                        maxWidth: '100%',
                        backgroundColor: color,
                        height: '100%',
                        borderRadius: '999px',
                        transition: 'width 0.3s ease'
                      }}
                    />
                  </div>
                </div>
              );
            })}
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
