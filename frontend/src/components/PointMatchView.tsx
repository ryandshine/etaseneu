import { useCallback, useRef, useState } from "react";
import { authFetch, downloadWithAuth } from "../lib/api";
import { Download, FileSpreadsheet, FileText, UploadCloud, X } from "lucide-react";

type SummaryItem = { label: string; count: number };

type PointMatchSummary = {
  total_points: number;
  inside_count: number;
  outside_count: number;
  distinct_kps: number;
  by_kps: SummaryItem[];
  by_wilker: SummaryItem[];
  by_province: SummaryItem[];
};

export type PointMatchResult = {
  token: string;
  source_name: string;
  source_format: string;
  warnings: string[];
  skipped_features: number;
  summary: PointMatchSummary;
  property_columns: string[];
  preview_rows: (string | number)[][];
  preview_truncated: boolean;
};

const BASE_HEADERS = [
  "No",
  "Latitude",
  "Longitude",
  "Status",
  "KPS (Lembaga)",
  "Balai PS",
  "Provinsi",
  "Kabupaten",
  "Kecamatan",
  "Desa",
  "Skema",
  "No. SK",
  "Tgl SK"
];

const STATUS_COLUMN = BASE_HEADERS.indexOf("Status");
const ACCEPTED = ".geojson,.json,.kml,.zip";

function formatNumber(value: number): string {
  return value.toLocaleString("id-ID");
}

function SummaryCard({
  label,
  value,
  tone
}: {
  label: string;
  value: number;
  tone?: "alert" | "normal";
}) {
  return (
    <div className={`pm-card${tone === "alert" && value > 0 ? " pm-card--alert" : ""}`}>
      <span className="pm-card__label">{label}</span>
      <strong className="pm-card__value">{formatNumber(value)}</strong>
    </div>
  );
}

function RankTable({ title, items, total }: { title: string; items: SummaryItem[]; total: number }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="pm-rank">
      <h3>{title}</h3>
      <table className="pm-rank__table">
        <tbody>
          {items.slice(0, 10).map((item) => {
            const share = total > 0 ? (item.count / total) * 100 : 0;
            return (
              <tr key={item.label}>
                <td className="pm-rank__label">{item.label}</td>
                <td className="pm-rank__bar">
                  <span style={{ width: `${Math.max(share, 2)}%` }} />
                </td>
                <td className="pm-rank__count">{formatNumber(item.count)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {items.length > 10 && (
        <p className="pm-note">... dan {formatNumber(items.length - 10)} lainnya, lengkapnya ada di berkas unduhan.</p>
      )}
    </div>
  );
}

export function PointMatchView() {
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PointMatchResult | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const upload = useCallback(async (file: File) => {
    setIsUploading(true);
    setError(null);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await authFetch("/api/point-match/analyze", {
        method: "POST",
        body: formData
      });

      if (!response.ok) {
        // Backend menulis pesan galat untuk dibaca pengguna akhir, jadi
        // tampilkan apa adanya alih-alih menggantinya dengan pesan generik.
        let message = `Gagal memproses berkas (kode ${response.status}).`;
        try {
          const body = await response.json();
          if (body?.detail) {
            message = String(body.detail);
          }
        } catch {
          // biarkan pesan bawaan
        }
        throw new Error(message);
      }

      setResult((await response.json()) as PointMatchResult);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Gagal memproses berkas.");
    } finally {
      setIsUploading(false);
    }
  }, []);

  const handleFiles = (files: FileList | null) => {
    const file = files?.[0];
    if (file) {
      void upload(file);
    }
  };

  const headers = result ? [...BASE_HEADERS, ...result.property_columns] : BASE_HEADERS;

  return (
    <section className="panel--matrix matrix-shell">
      <div className="matrix-header-bar glass-panel">
        <div className="matrix-header-copy">
          <p className="panel-eyebrow">Cek Titik terhadap Kawasan</p>
          <h2>Cek Titik ke KPS</h2>
          <p className="muted-copy">
            Unggah berkas titik (GeoJSON, KML, atau SHP dalam ZIP) untuk mengetahui tiap titik masuk KPS mana.
          </p>
        </div>
        {result && (
          <div className="matrix-header-actions">
            <button
              type="button"
              className="matrix-header-action matrix-header-action--ghost"
              onClick={() =>
                void downloadWithAuth(
                  `/api/point-match/${result.token}/export.xlsx`,
                  "cek-titik-ke-kps.xlsx"
                )
              }
            >
              <FileSpreadsheet size={14} />
              Unduh Excel
            </button>
            <button
              type="button"
              className="matrix-header-action matrix-header-action--ghost"
              onClick={() =>
                void downloadWithAuth(
                  `/api/point-match/${result.token}/export.pdf`,
                  "cek-titik-ke-kps.pdf"
                )
              }
            >
              <FileText size={14} />
              Unduh PDF
            </button>
          </div>
        )}
      </div>

      <div
        className={`pm-drop glass-panel${isDragging ? " pm-drop--active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setIsDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          hidden
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <UploadCloud size={30} />
        <p className="pm-drop__title">
          {isUploading ? "Memproses berkas..." : "Tarik & lepas berkas di sini, atau klik untuk memilih"}
        </p>
        <p className="pm-drop__hint">
          Format: .geojson, .json, .kml, atau .zip berisi shapefile (.shp + .shx + .dbf).
          Maksimal 50 MB / 200.000 titik.
        </p>
      </div>

      {error && (
        <div className="pm-alert pm-alert--error" role="alert">
          <X size={15} />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <>
          {result.warnings.map((warning) => (
            <div className="pm-alert pm-alert--warn" key={warning}>
              <span>{warning}</span>
            </div>
          ))}
          {result.skipped_features > 0 && (
            <div className="pm-alert pm-alert--warn">
              <span>
                {formatNumber(result.skipped_features)} fitur dilewati karena bukan titik
                (mis. poligon atau garis) atau koordinatnya tidak valid.
              </span>
            </div>
          )}

          <div className="pm-cards">
            <SummaryCard label="Total Titik" value={result.summary.total_points} />
            <SummaryCard label="Masuk KPS" value={result.summary.inside_count} />
            <SummaryCard label="Di Luar KPS" value={result.summary.outside_count} tone="alert" />
            <SummaryCard label="KPS Terdampak" value={result.summary.distinct_kps} />
          </div>

          <div className="pm-ranks glass-panel">
            <RankTable title="Titik per KPS" items={result.summary.by_kps} total={result.summary.total_points} />
            <RankTable title="Titik per Balai PS" items={result.summary.by_wilker} total={result.summary.total_points} />
            <RankTable title="Titik per Provinsi" items={result.summary.by_province} total={result.summary.total_points} />
          </div>

          <div className="matrix-ledger glass-panel">
            <div className="matrix-ledger-head">
              <div>
                <p className="panel-eyebrow">Hasil Pencocokan</p>
                <h3>{result.source_name}</h3>
              </div>
              <span className="muted-copy">
                {result.preview_truncated
                  ? `Menampilkan ${formatNumber(result.preview_rows.length)} dari ${formatNumber(result.summary.total_points)} titik`
                  : `${formatNumber(result.summary.total_points)} titik`}
              </span>
            </div>

            <div className="matrix-table-wrap">
              <div className="matrix-scroll">
                <table className="matrix-table">
                  <thead>
                    <tr>
                      {headers.map((header) => (
                        <th key={header} scope="col">
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.preview_rows.map((row, index) => (
                      <tr key={index}>
                        {row.map((cell, cellIndex) => (
                          <td
                            key={cellIndex}
                            data-label={headers[cellIndex]}
                            className={
                              cellIndex === STATUS_COLUMN && cell === "Di luar KPS"
                                ? "pm-status pm-status--outside"
                                : cellIndex === STATUS_COLUMN
                                  ? "pm-status"
                                  : undefined
                            }
                          >
                            {String(cell ?? "")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {result.preview_truncated && (
              <p className="pm-note">
                <Download size={13} /> Data lengkap seluruh {formatNumber(result.summary.total_points)} titik
                tersedia di berkas Excel dan PDF.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
