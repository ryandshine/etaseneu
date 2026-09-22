import { describe, expect, it } from "vitest";
import {
  computeScaleDenominator,
  formatScaleLabel,
  metersPerPixel,
  niceScaleDenominator,
} from "../lib/mapScale";

describe("mapScale", () => {
  it("membulatkan ke deret rapi 1-2-2.5-5-10", () => {
    expect(niceScaleDenominator(980)).toBe(1000);
    expect(niceScaleDenominator(24000)).toBe(25000);
    expect(niceScaleDenominator(240000)).toBe(250000);
    expect(niceScaleDenominator(1100000)).toBe(1000000);
  });

  it("mengembalikan 0 untuk input tak valid", () => {
    expect(niceScaleDenominator(0)).toBe(0);
    expect(niceScaleDenominator(-5)).toBe(0);
    expect(niceScaleDenominator(NaN)).toBe(0);
  });

  it("resolusi Web Mercator menyempit mendekati kutub (cos lintang)", () => {
    const atEquator = metersPerPixel(5, 0);
    const atLat60 = metersPerPixel(5, 60);
    expect(atLat60).toBeCloseTo(atEquator * 0.5, 5);
  });

  it("skala makin kecil (angka pembagi makin besar) saat zoom out", () => {
    const zoomedIn = computeScaleDenominator(10, -2);
    const zoomedOut = computeScaleDenominator(5, -2);
    expect(zoomedOut).toBeGreaterThan(zoomedIn);
  });

  it("skala di garis khatulistiwa Indonesia zoom 5 (tampilan default seluruh negara) masuk akal", () => {
    // zoom 5 dipakai sebagai default beberapa peta (mis. KompleksKebakaranView) untuk
    // menampilkan seluruh Indonesia sekaligus -- skala representatif ~1:20 juta.
    const denominator = computeScaleDenominator(5, -2);
    expect(denominator).toBeGreaterThan(10_000_000);
    expect(denominator).toBeLessThan(30_000_000);
  });

  it("skala saat zoom masuk ke level KPS (zoom 12) jadi orde puluhan ribu", () => {
    const denominator = computeScaleDenominator(12, -2);
    expect(denominator).toBeGreaterThan(50_000);
    expect(denominator).toBeLessThan(300_000);
  });

  it("format label pakai pemisah ribuan gaya Indonesia", () => {
    expect(formatScaleLabel(250000)).toBe("1:250.000");
    expect(formatScaleLabel(0)).toBe("1:—");
  });
});
