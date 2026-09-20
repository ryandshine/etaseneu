import { useState } from "react";
import { CloudFog } from "lucide-react";

import type { SmokeLayersState } from "../hooks/useSmokeLayers";
import { PM25_LEGEND, PM25_OFFSETS, formatSmokeValidTime } from "../lib/smoke";

type SmokeControlProps = {
  smoke: SmokeLayersState;
  // Terbuka dari awal: dipakai di tumpukan kiri HotspotMap & bottom sheet
  // mobile. Default tertutup: di peta lain cukup satu tombol kecil "Asap".
  defaultOpen?: boolean;
  // Kelas posisi tambahan (mis. `smoke-control--kompleks`) -- tiap peta punya
  // sudut kosong yang berbeda.
  className?: string;
};

function offsetLabel(offset: number): string {
  return offset === 0 ? "Sekarang" : `+${offset} jam`;
}

/**
 * Kontrol lapisan asap yang dipakai bersama semua halaman peta: dua tombol
 * (citra satelit VIIRS dari NASA GIBS, prakiraan PM2.5 dari CAMS), pilihan
 * hari/jam, legenda ambang BMKG, dan status pemuatan. Semua MATI secara default.
 */
export function SmokeControl({ smoke, defaultOpen = false, className = "" }: SmokeControlProps) {
  const [open, setOpen] = useState(defaultOpen);
  const anyOn = smoke.imagery || smoke.pm25;

  return (
    <div className={`smoke-control${open ? " smoke-control--open" : ""}${className ? ` ${className}` : ""}`}>
      <button
        type="button"
        className={`smoke-control__head${anyOn ? " smoke-control__head--active" : ""}`}
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        aria-label="Lapisan asap"
        title="Lapisan asap: citra satelit dan prakiraan PM2.5"
      >
        <CloudFog size={15} />
        <span>Asap</span>
      </button>

      {open ? (
        <div className="smoke-control__panel">
          <button
            type="button"
            className={`smoke-control__toggle${smoke.imagery ? " smoke-control__toggle--active" : ""}`}
            onClick={smoke.toggleImagery}
            aria-pressed={smoke.imagery}
          >
            Citra satelit asap (VIIRS)
          </button>
          {smoke.imagery ? (
            <div className="smoke-control__options">
              <div className="smoke-control__chips" role="group" aria-label="Hari citra satelit">
                <button
                  type="button"
                  className={smoke.imageryDay === "today" ? "smoke-control__chip--active" : ""}
                  onClick={() => smoke.setImageryDay("today")}
                  aria-pressed={smoke.imageryDay === "today"}
                >
                  Hari ini
                </button>
                <button
                  type="button"
                  className={smoke.imageryDay === "yesterday" ? "smoke-control__chip--active" : ""}
                  onClick={() => smoke.setImageryDay("yesterday")}
                  aria-pressed={smoke.imageryDay === "yesterday"}
                >
                  Kemarin
                </button>
              </div>
              <p className="smoke-control__note">
                Asap tampak sebagai semburan abu-abu/cokelat. Citra harian dan tertutup awan. Hari ini: bagian yang
                belum terekam satelit diisi citra kemarin.
              </p>
            </div>
          ) : null}

          <button
            type="button"
            className={`smoke-control__toggle${smoke.pm25 ? " smoke-control__toggle--active" : ""}`}
            onClick={smoke.togglePm25}
            aria-pressed={smoke.pm25}
          >
            Prakiraan PM2.5 (CAMS)
          </button>
          {smoke.pm25 ? (
            <div className="smoke-control__options">
              <div className="smoke-control__chips" role="group" aria-label="Jam prakiraan PM2.5">
                {PM25_OFFSETS.map((offset) => (
                  <button
                    key={offset}
                    type="button"
                    className={smoke.pm25Offset === offset ? "smoke-control__chip--active" : ""}
                    onClick={() => smoke.setPm25Offset(offset)}
                    aria-pressed={smoke.pm25Offset === offset}
                  >
                    {offsetLabel(offset)}
                  </button>
                ))}
              </div>
              <ul className="smoke-control__legend" aria-label="Legenda PM2.5 (µg/m³)">
                {PM25_LEGEND.map((item) => (
                  <li key={item.key}>
                    <span className="smoke-control__swatch" style={{ background: item.color }} />
                    <span>{item.label}</span>
                    <span className="smoke-control__range">{item.range}</span>
                  </li>
                ))}
              </ul>
              <p className="smoke-control__note" role="status">
                {smoke.pm25Info.status === "error"
                  ? "Gagal memuat prakiraan PM2.5."
                  : smoke.pm25Info.status === "ready" && smoke.pm25Info.validTime
                    ? `Berlaku ${formatSmokeValidTime(smoke.pm25Info.validTime)}`
                    : "Memuat prakiraan..."}
              </p>
              <p className="smoke-control__note">
                Model regional resolusi kasar (±150 km): indikatif, bukan pengukuran di lokasi.
              </p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
