import { LocateFixed, Minus, Plus } from "lucide-react";
import type { Map as LeafletMap } from "leaflet";

type MapControlsProps = {
  map: LeafletMap | null;
  hidden?: boolean;
  userLocationActive: boolean;
  userLocationLoading: boolean;
  onToggleUserLocation: () => void;
};

/**
 * Kolom tombol ringkas di pojok kanan-bawah peta untuk mobile: zoom +/- dan
 * "lokasi saya". Dirender sebagai saudara <MapContainer> (di luar
 * .leaflet-container) sehingga sentuhannya tidak menembus ke gestur peta --
 * instance peta untuk zoom diteruskan lewat prop `map`.
 */
export function MapControls({
  map,
  hidden = false,
  userLocationActive,
  userLocationLoading,
  onToggleUserLocation
}: MapControlsProps) {
  return (
    <div className={`map-fab${hidden ? " map-fab--hidden" : ""}`} aria-hidden={hidden}>
      <div className="map-fab__cluster">
        <button
          type="button"
          className="map-fab__btn"
          aria-label="Perbesar peta"
          onClick={() => map?.zoomIn()}
        >
          <Plus size={17} />
        </button>
        <span className="map-fab__divider" aria-hidden="true" />
        <button
          type="button"
          className="map-fab__btn"
          aria-label="Perkecil peta"
          onClick={() => map?.zoomOut()}
        >
          <Minus size={17} />
        </button>
      </div>

      <button
        type="button"
        className={`map-fab__btn map-fab__btn--solo${
          userLocationActive ? " map-fab__btn--active" : ""
        }${userLocationLoading ? " map-fab__btn--loading" : ""}`}
        aria-label="Lokasi saya"
        aria-pressed={userLocationActive}
        onClick={onToggleUserLocation}
      >
        <LocateFixed size={17} />
      </button>
    </div>
  );
}
