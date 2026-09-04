import { Pause, Play, X } from "lucide-react";
import type { HotspotTimeline } from "../hooks/useHotspotTimeline";

export type HotspotTimelineControlProps = Pick<
  HotspotTimeline,
  | "buckets"
  | "playheadIndex"
  | "isPlaying"
  | "speed"
  | "label"
  | "toggle"
  | "seek"
  | "cycleSpeed"
> & { onClose(): void };

/** Bar pemutar waktu melayang di bawah-tengah peta: play/pause,
 *  histogram-scrubber (jumlah titik per bucket), label WIB, kecepatan. */
export function HotspotTimelineControl({
  buckets,
  playheadIndex,
  isPlaying,
  speed,
  label,
  toggle,
  seek,
  cycleSpeed,
  onClose,
}: HotspotTimelineControlProps) {
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));
  const lastIndex = Math.max(buckets.length - 1, 0);
  const current = buckets[playheadIndex];

  return (
    <div className="timeline-control" role="group" aria-label="Pemutar waktu hotspot">
      <button
        type="button"
        className="timeline-control__play"
        onClick={toggle}
        aria-label={isPlaying ? "Jeda animasi" : "Putar animasi"}
        title={isPlaying ? "Jeda" : "Putar"}
      >
        {isPlaying ? <Pause size={16} /> : <Play size={16} />}
      </button>

      <div className="timeline-control__scrub">
        <div className="timeline-control__hist" aria-hidden="true">
          {buckets.map((b) => (
            <span
              key={b.index}
              data-testid="timeline-bar"
              className={
                "timeline-control__bar" +
                (b.index < playheadIndex ? " timeline-control__bar--past" : "") +
                (b.index === playheadIndex ? " timeline-control__bar--now" : "")
              }
              style={{ height: `${Math.max(6, Math.round((b.count / maxCount) * 100))}%` }}
            />
          ))}
        </div>
        <input
          type="range"
          className="timeline-control__range"
          min={0}
          max={lastIndex}
          step={1}
          value={playheadIndex}
          aria-label="Posisi waktu"
          aria-valuemin={0}
          aria-valuemax={lastIndex}
          aria-valuenow={playheadIndex}
          onChange={(e) => seek(Number(e.target.value))}
        />
      </div>

      <span className="timeline-control__label">
        <span className="timeline-control__label-time">{label}</span>
        {current ? (
          <span className="timeline-control__label-count">{current.count} titik</span>
        ) : null}
      </span>

      <button
        type="button"
        className="timeline-control__speed"
        onClick={cycleSpeed}
        aria-label={`Kecepatan ${speed} kali`}
        title="Ubah kecepatan"
      >
        {speed}×
      </button>

      <button
        type="button"
        className="timeline-control__close"
        onClick={onClose}
        aria-label="Tutup pemutar waktu"
        title="Tutup"
      >
        <X size={14} />
      </button>
    </div>
  );
}
