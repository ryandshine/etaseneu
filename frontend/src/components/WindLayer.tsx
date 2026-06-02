import { useEffect, useRef, useState } from 'react';
import { useMap } from 'react-leaflet';
import L, { type Layer } from 'leaflet';

type WindLayerProps = {
  visible: boolean;
};

const REFRESH_INTERVAL_MS = 15 * 60 * 1000;
const WIND_COLOR_SCALE = [
  "rgba(196, 253, 255, 0.35)",
  "rgba(103, 232, 249, 0.52)",
  "rgba(56, 189, 248, 0.68)",
  "rgba(59, 130, 246, 0.78)",
  "rgba(251, 191, 36, 0.86)",
  "rgba(249, 115, 22, 0.93)",
  "rgba(239, 68, 68, 1.0)",
];

export function WindLayer({ visible }: WindLayerProps) {
  const map = useMap();
  const layerRef = useRef<Layer | null>(null);
  const [windData, setWindData] = useState<unknown[] | null>(null);

  const fetchWindData = async () => {
    try {
      const response = await fetch('/api/wind');
      const data = (await response.json()) as unknown[];
      if (Array.isArray(data)) {
        setWindData(data);
      }
    } catch {
      // ignore, layer will simply keep existing data or clear on cleanup
    }
  };

  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    const run = async () => {
      await fetchWindData();
      if (cancelled) {
        return;
      }
    };

    void run();
    const timer = window.setInterval(() => {
      void fetchWindData();
    }, REFRESH_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [visible]);

  useEffect(() => {
    if (!visible || !windData) {
      if (layerRef.current) {
        map.removeLayer(layerRef.current);
        layerRef.current = null;
      }
      return;
    }

    if (typeof window !== "undefined") {
      (window as any).L = L;
    }

    import("leaflet-velocity").then(() => {
      if (layerRef.current) {
        map.removeLayer(layerRef.current);
      }
      const velocityLayerFn = (L as any).velocityLayer;
      if (!velocityLayerFn) {
        console.error("leaflet-velocity loaded but L.velocityLayer is undefined");
        return;
      }
      const layer = velocityLayerFn({
        displayValues: true,
        displayOptions: {
          velocityType: "Angin Global",
          position: "bottomleft",
          emptyString: "Data angin tidak tersedia",
          speedUnit: "m/s",
        },
        data: windData,
        maxVelocity: 15,
        velocityScale: 0.008,
        particleAge: 64,
        lineWidth: 1.8,
        particleMultiplier: 0.001,
        frameRate: 15,
        colorScale: WIND_COLOR_SCALE,
        opacity: 0.92,
      });
      layer.addTo(map);
      layerRef.current = layer;
    });

    return () => {
      if (layerRef.current) {
        map.removeLayer(layerRef.current);
        layerRef.current = null;
      }
    };
  }, [visible, windData, map]);

  return null;
}
