import { useCallback, useMemo, useState } from "react";

import type { Pm25Offset, SmokeImageryDay } from "../lib/smoke";

export type Pm25Info = {
  status: "idle" | "loading" | "ready" | "error";
  validTime?: string;
};

/**
 * State lapisan asap untuk SATU peta. Sengaja state lokal per-peta (bukan
 * global/persist): semua lapisan MATI setiap kali peta dibuka, sama seperti
 * overlay berat lainnya (Fungsi Kawasan Hutan, estimasi Sentinel-2). Dipakai
 * bersama oleh HotspotMap, Detail KPS, Kompleks Kebakaran & Siaga Rambatan Api.
 */
export function useSmokeLayers() {
  const [imagery, setImagery] = useState(false);
  const [imageryDay, setImageryDay] = useState<SmokeImageryDay>("today");
  const [pm25, setPm25] = useState(false);
  const [pm25Offset, setPm25Offset] = useState<Pm25Offset>(0);
  const [pm25Info, setPm25Info] = useState<Pm25Info>({ status: "idle" });

  const toggleImagery = useCallback(() => setImagery((current) => !current), []);
  const togglePm25 = useCallback(() => setPm25((current) => !current), []);

  return useMemo(
    () => ({
      imagery,
      imageryDay,
      pm25,
      pm25Offset,
      pm25Info,
      toggleImagery,
      setImageryDay,
      togglePm25,
      setPm25Offset,
      setPm25Info,
    }),
    [imagery, imageryDay, pm25, pm25Offset, pm25Info, toggleImagery, togglePm25],
  );
}

export type SmokeLayersState = ReturnType<typeof useSmokeLayers>;
