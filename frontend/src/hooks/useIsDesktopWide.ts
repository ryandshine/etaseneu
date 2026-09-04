import { useEffect, useState } from "react";

// Ambang yang sama dengan @media (min-width: 1024px) di index.css --
// breakpoint "desktop" yang sudah dipakai override lain di file itu.
const DESKTOP_QUERY = "(min-width: 1024px)";

function matches(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(DESKTOP_QUERY).matches;
}

/**
 * True saat viewport masuk kelas "desktop lebar" (>=1024px). Dipakai untuk
 * fitur yang SENGAJA dibatasi cuma di desktop (mis. sidebar collapse) supaya
 * tidak menambah variabel baru ke sistem lebar sidebar tablet/mobile yang
 * sudah rapuh (lihat komentar di index.css sekitar .app-frame/.side-rail).
 */
export function useIsDesktopWide(): boolean {
  const [isDesktopWide, setIsDesktopWide] = useState<boolean>(matches);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const mql = window.matchMedia(DESKTOP_QUERY);
    const onChange = (event: MediaQueryListEvent) => setIsDesktopWide(event.matches);
    setIsDesktopWide(mql.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  return isDesktopWide;
}
