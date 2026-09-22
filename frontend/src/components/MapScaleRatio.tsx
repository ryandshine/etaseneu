import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import { computeScaleDenominator, formatScaleLabel } from "../lib/mapScale";

/**
 * Kontrol skala peta bergaya kartografi ("1:250.000") menggantikan bar jarak
 * bawaan Leaflet ("300 km") — permintaan user 2026-09-22: skala rasio lebih
 * familiar buat konteks pemetaan kehutanan (mis. peta KWSHUTAN_AR_250K resmi
 * yang disebut namanya sendiri pakai skala 1:250.000). Rumus & pembulatan
 * "rapi" ada di lib/mapScale.ts (diuji terpisah tanpa perlu Leaflet).
 */

type MapScaleRatioProps = {
  position?: L.ControlPosition;
};

export function MapScaleRatio({ position = "bottomleft" }: MapScaleRatioProps) {
  const map = useMap();

  useEffect(() => {
    const control = new L.Control({ position });
    let update: () => void = () => {};

    control.onAdd = () => {
      const container = L.DomUtil.create("div", "leaflet-control map-scale-ratio");
      update = () => {
        const denominator = computeScaleDenominator(map.getZoom(), map.getCenter().lat);
        container.textContent = formatScaleLabel(denominator);
      };
      update();
      map.on("zoomend moveend", update);
      return container;
    };

    control.onRemove = () => {
      map.off("zoomend moveend", update);
    };

    control.addTo(map);
    return () => {
      control.remove();
    };
  }, [map, position]);

  return null;
}
