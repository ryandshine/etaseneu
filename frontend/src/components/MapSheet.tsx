import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Flame, Map as MapIcon, Satellite, Trees } from "lucide-react";
import { formatHectares } from "../lib/hotspotDisplay";
import { KAWASAN_HUTAN_LEGEND } from "../constants/kawasanHutan";

type HotspotLike = {
  source: string;
  satellite: string;
  frp?: number | null;
};

type OverlayLike<T> = { data: T | null; loading: boolean };

type BurnedSummary = {
  total_ha: number;
  kps_count: number;
};

type S2Summary = {
  meta: { total_ha: number; polygons: number; no_hotspot_but_burned: number };
};

type MapSheetProps = {
  hotspots: HotspotLike[];
  mapStyle: "dark" | "satellite";
  onMapStyleChange: (style: "dark" | "satellite") => void;
  showBurnedArea: boolean;
  onToggleBurnedArea: () => void;
  burnedArea: OverlayLike<BurnedSummary>;
  showS2Burned: boolean;
  onToggleS2Burned: () => void;
  s2Burned: OverlayLike<S2Summary>;
  showKawasan: boolean;
  onToggleKawasan: () => void;
  onExpandedChange?: (expanded: boolean) => void;
};

type Detent = "peek" | "half" | "full";
const SWIPE_THRESHOLD_PX = 34;

type SatelliteRow = {
  name: string;
  tinggi: number;
  sedang: number;
  rendah: number;
  total: number;
};

// Klasifikasi identik dengan panel statistik desktop di App.tsx
// (dynamicConfidenceStats) supaya angkanya tidak berbeda antar tampilan.
function summarise(hotspots: HotspotLike[]) {
  const rows = new Map<string, SatelliteRow>();

  for (const hotspot of hotspots) {
    const raw = (hotspot.source || hotspot.satellite || "Unknown").trim().toUpperCase();
    let name = raw || "Unknown";
    if (raw.includes("NOAA-20") || raw.includes("NOAA20")) name = "NOAA-20";
    else if (raw.includes("NOAA-21") || raw.includes("NOAA21")) name = "NOAA-21";
    else if (raw.includes("S-NPP") || raw.includes("SNPP") || raw.includes("SUOMI")) name = "S-NPP";
    else if (raw.includes("MODIS")) name = "MODIS";

    let row = rows.get(name);
    if (!row) {
      row = { name, tinggi: 0, sedang: 0, rendah: 0, total: 0 };
      rows.set(name, row);
    }

    const frp = hotspot.frp ?? 0;
    if (frp > 30) row.tinggi += 1;
    else if (frp >= 10) row.sedang += 1;
    else row.rendah += 1;
    row.total += 1;
  }

  const list = [...rows.values()].sort((a, b) => a.name.localeCompare(b.name));
  const tinggi = list.reduce((sum, row) => sum + row.tinggi, 0);
  const sedang = list.reduce((sum, row) => sum + row.sedang, 0);
  const rendah = list.reduce((sum, row) => sum + row.rendah, 0);
  const total = list.reduce((sum, row) => sum + row.total, 0);
  return { list, tinggi, sedang, rendah, total };
}

function pct(value: number, total: number): string {
  return total > 0 ? `${((value / total) * 100).toFixed(1)}%` : "0%";
}

function LayerRow({
  icon,
  label,
  hint,
  active,
  loading,
  onToggle,
  children
}: {
  icon: ReactNode;
  label: string;
  hint: string;
  active: boolean;
  loading: boolean;
  onToggle: () => void;
  children?: ReactNode;
}) {
  return (
    <div className={`map-sheet__row${active ? " is-active" : ""}`}>
      <button type="button" className="map-sheet__rowbtn" onClick={onToggle} aria-pressed={active}>
        <span className="map-sheet__rowicon">{icon}</span>
        <span className="map-sheet__rowtext">
          <span className="map-sheet__rowlabel">{label}</span>
          <span className="map-sheet__rowhint">{hint}</span>
        </span>
        <span className={`map-sheet__switch${loading ? " is-loading" : ""}`} aria-hidden="true" />
      </button>
      {children}
    </div>
  );
}

/**
 * Bottom sheet ringkas untuk peta live di mobile. Menyatukan yang sebelumnya
 * jadi tiga kluster mengambang terpisah: toggle lapisan (.burned-control),
 * peralihan basemap (.basemap-switcher), legenda titik (.map-legend), plus
 * ringkasan angka hotspot yang di desktop ada di panel kanan-atas App.tsx.
 * Tiga tinggi snap: peek (baris ringkas), half, full.
 */
export function MapSheet({
  hotspots,
  mapStyle,
  onMapStyleChange,
  showBurnedArea,
  onToggleBurnedArea,
  burnedArea,
  showS2Burned,
  onToggleS2Burned,
  s2Burned,
  showKawasan,
  onToggleKawasan,
  onExpandedChange
}: MapSheetProps) {
  const [detent, setDetent] = useState<Detent>("peek");
  const touchStartYRef = useRef<number | null>(null);

  const summary = useMemo(() => summarise(hotspots), [hotspots]);

  useEffect(() => {
    onExpandedChange?.(detent !== "peek");
  }, [detent, onExpandedChange]);

  const expand = () =>
    setDetent((current) => (current === "peek" ? "half" : current === "half" ? "full" : "full"));
  const collapse = () =>
    setDetent((current) => (current === "full" ? "half" : current === "half" ? "peek" : "peek"));
  const cycleFromHandle = () =>
    setDetent((current) => (current === "peek" ? "half" : current === "half" ? "full" : "peek"));

  const onTouchStart = (event: React.TouchEvent) => {
    touchStartYRef.current = event.touches[0]?.clientY ?? null;
  };
  const onTouchEnd = (event: React.TouchEvent) => {
    const start = touchStartYRef.current;
    touchStartYRef.current = null;
    if (start == null) return;
    const delta = (event.changedTouches[0]?.clientY ?? start) - start;
    if (delta < -SWIPE_THRESHOLD_PX) expand();
    else if (delta > SWIPE_THRESHOLD_PX) collapse();
  };

  const activeLayerHints: string[] = [];
  if (showBurnedArea) activeLayerHints.push("Bekas terbakar");
  if (showS2Burned) activeLayerHints.push("Estimasi S2");
  if (showKawasan) activeLayerHints.push("Kawasan hutan");

  return (
    <>
      {detent === "full" ? (
        <button
          type="button"
          className="map-sheet__scrim"
          aria-label="Perkecil panel"
          onClick={() => setDetent("half")}
        />
      ) : null}

      <section className={`map-sheet map-sheet--${detent}`} aria-label="Lapisan dan ringkasan peta">
        <button
          type="button"
          className="map-sheet__handle"
          onClick={cycleFromHandle}
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
          aria-expanded={detent !== "peek"}
        >
          <span className="map-sheet__grip" aria-hidden="true" />
          <span className="map-sheet__peekline">
            <Flame size={13} aria-hidden="true" />
            <strong>{summary.total.toLocaleString("id-ID")}</strong> hotspot
            {activeLayerHints.length > 0 ? <em>· {activeLayerHints.join(" · ")}</em> : null}
          </span>
        </button>

        {detent !== "peek" ? (
          <div className="map-sheet__body">
            <h3 className="map-sheet__title">Lapisan</h3>

            <LayerRow
              icon={<Flame size={15} />}
              label="Bekas Terbakar"
              hint="Sumber Kementerian Kehutanan · akurasi H/M"
              active={showBurnedArea}
              loading={burnedArea.loading}
              onToggle={onToggleBurnedArea}
            >
              {showBurnedArea && burnedArea.data ? (
                <p className="map-sheet__stat">
                  <span>{formatHectares(burnedArea.data.total_ha)} Ha</span>
                  <span>{formatHectares(burnedArea.data.kps_count)} KPS terdampak</span>
                </p>
              ) : null}
            </LayerRow>

            <LayerRow
              icon={<Flame size={15} />}
              label="Estimasi Sentinel-2"
              hint="Analisis mandiri dNBR · estimasi, belum terverifikasi"
              active={showS2Burned}
              loading={s2Burned.loading}
              onToggle={onToggleS2Burned}
            >
              {showS2Burned && s2Burned.data ? (
                <p className="map-sheet__stat">
                  <span>{formatHectares(s2Burned.data.meta.total_ha)} Ha</span>
                  <span>
                    {formatHectares(s2Burned.data.meta.polygons)} KPS ·{" "}
                    {s2Burned.data.meta.no_hotspot_but_burned} tanpa hotspot
                  </span>
                </p>
              ) : null}
            </LayerRow>

            <LayerRow
              icon={<Trees size={15} />}
              label="Fungsi Kawasan Hutan"
              hint="Layanan ArcGIS Ditjen Planologi Kehutanan · KWSHUTAN 1:250K"
              active={showKawasan}
              loading={false}
              onToggle={onToggleKawasan}
            >
              {showKawasan ? (
                <ul className="map-sheet__legend">
                  {KAWASAN_HUTAN_LEGEND.map((item) => (
                    <li key={item.label}>
                      <span style={{ background: item.color }} />
                      {item.label}
                    </li>
                  ))}
                </ul>
              ) : null}
            </LayerRow>

            <h3 className="map-sheet__title">Tampilan Dasar</h3>
            <div className="map-sheet__segmented" role="group" aria-label="Gaya peta">
              <button
                type="button"
                className={mapStyle === "dark" ? "is-active" : ""}
                onClick={() => onMapStyleChange("dark")}
                aria-pressed={mapStyle === "dark"}
              >
                <MapIcon size={14} /> Peta
              </button>
              <button
                type="button"
                className={mapStyle === "satellite" ? "is-active" : ""}
                onClick={() => onMapStyleChange("satellite")}
                aria-pressed={mapStyle === "satellite"}
              >
                <Satellite size={14} /> Satelit
              </button>
            </div>

            <h3 className="map-sheet__title">Legenda Titik</h3>
            <ul className="map-sheet__legend map-sheet__legend--flush">
              <li>
                <span style={{ background: "#ff8c42" }} />
                MODIS
              </li>
              <li>
                <span style={{ background: "#facc15" }} />
                VIIRS
              </li>
              <li>
                <span className="map-sheet__legend-pulse" />
                FRP tinggi (&gt;30&nbsp;MW)
              </li>
            </ul>

            <h3 className="map-sheet__title">Ringkasan</h3>
            {summary.total === 0 ? (
              <p className="map-sheet__empty">Tidak ada hotspot pada filter saat ini.</p>
            ) : (
              <>
                <div className="map-sheet__conf">
                  <span>
                    <i style={{ background: "#ef4444" }} />
                    Tinggi <b>{summary.tinggi.toLocaleString("id-ID")}</b>
                    <em>{pct(summary.tinggi, summary.total)}</em>
                  </span>
                  <span>
                    <i style={{ background: "#f59e0b" }} />
                    Sedang <b>{summary.sedang.toLocaleString("id-ID")}</b>
                    <em>{pct(summary.sedang, summary.total)}</em>
                  </span>
                  <span>
                    <i style={{ background: "#3b82f6" }} />
                    Rendah <b>{summary.rendah.toLocaleString("id-ID")}</b>
                    <em>{pct(summary.rendah, summary.total)}</em>
                  </span>
                </div>

                <table className="map-sheet__sat">
                  <thead>
                    <tr>
                      <th>Satelit</th>
                      <th>T</th>
                      <th>S</th>
                      <th>R</th>
                      <th>&sum;</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.list.map((row) => (
                      <tr key={row.name}>
                        <td>{row.name}</td>
                        <td>{row.tinggi.toLocaleString("id-ID")}</td>
                        <td>{row.sedang.toLocaleString("id-ID")}</td>
                        <td>{row.rendah.toLocaleString("id-ID")}</td>
                        <td>{row.total.toLocaleString("id-ID")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        ) : null}
      </section>
    </>
  );
}
