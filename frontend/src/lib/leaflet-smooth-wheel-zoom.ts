/**
 * Zoom scroll/trackpad kontinu untuk Leaflet -- mengganti handler
 * `scrollWheelZoom` bawaan yang melangkah per level. Diadaptasi dari
 * Leaflet.SmoothWheelZoom (mutsuyuki, MIT); di-vendor karena tidak ada paket
 * npm yang terawat.
 *
 * Pakai: impor modul ini sekali (side-effect), lalu di <MapContainer> set
 * `scrollWheelZoom={false}` + `smoothWheelZoom` + `smoothSensitivity`.
 * Lihat constants/map.ts.
 */
import * as L from "leaflet";

declare module "leaflet" {
  interface MapOptions {
    smoothWheelZoom?: boolean | "center";
    smoothSensitivity?: number;
  }
}

/* eslint-disable @typescript-eslint/no-explicit-any */
const LAny = L as any;

if (!LAny.Map.SmoothWheelZoom) {
  LAny.Map.mergeOptions({
    smoothWheelZoom: true,
    smoothSensitivity: 1,
  });

  LAny.Map.SmoothWheelZoom = LAny.Handler.extend({
    addHooks(this: any) {
      L.DomEvent.on(this._map._container, "wheel", this._onWheelScroll, this);
    },

    removeHooks(this: any) {
      L.DomEvent.off(this._map._container, "wheel", this._onWheelScroll, this);
    },

    _onWheelScroll(this: any, e: WheelEvent) {
      if (!this._isWheeling) {
        this._onWheelStart(e);
      }
      this._onWheeling(e);
    },

    _onWheelStart(this: any, e: WheelEvent) {
      const map = this._map;
      this._isWheeling = true;
      this._wheelMousePosition = map.mouseEventToContainerPoint(e);
      this._centerPoint = map.getSize().divideBy(2);
      this._startLatLng = map.containerPointToLatLng(this._centerPoint);
      this._wheelStartLatLng = map.containerPointToLatLng(this._wheelMousePosition);
      this._startZoom = map.getZoom();
      this._moved = false;
      this._zooming = true;

      map._stop();
      if (map._panAnim) {
        map._panAnim.stop();
      }

      this._goalZoom = map.getZoom();
      this._prevCenter = map.getCenter();
      this._prevZoom = map.getZoom();

      this._zoomAnimationId = requestAnimationFrame(this._updateWheelZoom.bind(this));
    },

    _onWheeling(this: any, e: WheelEvent) {
      const map = this._map;

      this._goalZoom =
        this._goalZoom - e.deltaY * 0.003 * map.options.smoothSensitivity;
      if (this._goalZoom < map.getMinZoom() || this._goalZoom > map.getMaxZoom()) {
        this._goalZoom = map._limitZoom(this._goalZoom);
      }
      this._wheelMousePosition = map.mouseEventToContainerPoint(e);

      clearTimeout(this._timeoutId);
      this._timeoutId = setTimeout(this._onWheelEnd.bind(this), 200);

      L.DomEvent.preventDefault(e);
      L.DomEvent.stopPropagation(e);
    },

    _onWheelEnd(this: any) {
      this._isWheeling = false;
      cancelAnimationFrame(this._zoomAnimationId);
      this._map._moveEnd(true);
    },

    _updateWheelZoom(this: any) {
      const map = this._map;

      if (
        !map.getCenter().equals(this._prevCenter) ||
        map.getZoom() !== this._prevZoom
      ) {
        return;
      }

      this._zoom = map.getZoom() + (this._goalZoom - map.getZoom()) * 0.3;
      this._zoom = Math.floor(this._zoom * 100) / 100;

      const delta = this._wheelMousePosition.subtract(this._centerPoint);
      if (delta.x === 0 && delta.y === 0) {
        return;
      }

      if (map.options.smoothWheelZoom === "center") {
        this._center = this._startLatLng;
      } else {
        this._center = map.unproject(
          map.project(this._wheelStartLatLng, this._zoom).subtract(delta),
          this._zoom,
        );
      }

      map.setView(this._center, this._zoom, { animate: false });

      this._prevCenter = map.getCenter();
      this._prevZoom = map.getZoom();

      this._zoomAnimationId = requestAnimationFrame(this._updateWheelZoom.bind(this));
    },
  });

  LAny.Map.addInitHook("addHandler", "smoothWheelZoom", LAny.Map.SmoothWheelZoom);
}
