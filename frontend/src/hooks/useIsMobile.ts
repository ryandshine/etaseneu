import { useEffect, useState } from "react";

// Ambang yang sama dengan blok @media (max-width: 639px) di index.css.
const MOBILE_QUERY = "(max-width: 639px)";

function matches(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(MOBILE_QUERY).matches;
}

/**
 * True saat viewport masuk kelas "mobile" (<=639px). Dipakai peta live untuk
 * memilih antara kontrol mengambang desktop dan bottom sheet ringkas mobile.
 */
export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState<boolean>(matches);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(MOBILE_QUERY);
    const onChange = (event: MediaQueryListEvent) => setIsMobile(event.matches);
    // Sinkronkan sekali kalau lebar berubah antara render awal dan efek.
    setIsMobile(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return isMobile;
}
