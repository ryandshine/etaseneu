"""Ringkas overlay "Fungsi Kawasan Hutan" KLHK (KWSHUTAN_AR_250K) untuk peta.

CARA PALING SEDERHANA & ANTI-GAGAL: TIDAK ada operasi topologi (union/dissolve/
simplify GEOS) -- geometri sumber KWSHUTAN penuh error ring & sliver, tiap kali
GEOS menyentuhnya prosesnya gagal di fitur yang beda. Di sini murni aritmetika:

  1. bulatkan tiap koordinat ke `NDIGITS` desimal (~110 m di 3 desimal),
  2. buang titik berturut yang jadi kembar setelah pembulatan,
  3. buang ring < 4 titik dan fitur tanpa geometri,
  4. simpan hanya properti FUNGSIKWS (untuk pewarnaan).

Semua fitur (bukan hasil dissolve) tetap ada -- frontend mewarnai per FUNGSIKWS
dan me-render di canvas. Jalankan ulang hanya saat KLHK merilis KWSHUTAN baru:

    python build_kawasan_hutan_overlay.py <src.geojson> <out.geojson> [ndigits]
"""

from __future__ import annotations

import json
import sys

NDIGITS_DEFAULT = 3  # ~110 m -- overview nasional


def round_ring(ring: list, nd: int) -> list | None:
    out: list[list[float]] = []
    for pt in ring:
        rp = [round(pt[0], nd), round(pt[1], nd)]
        if not out or out[-1] != rp:
            out.append(rp)
    # ring valid butuh minimal 4 titik (tertutup)
    if len(out) < 4:
        return None
    if out[0] != out[-1]:
        out.append(out[0][:])
    if len(out) < 4:
        return None
    return out


def round_polygon(coords: list, nd: int) -> list | None:
    rings = []
    for i, ring in enumerate(coords):
        rr = round_ring(ring, nd)
        if rr is None:
            if i == 0:
                return None  # ring luar hilang -> poligon hilang
            continue          # lubang kecil hilang -> abaikan
        rings.append(rr)
    return rings or None


def round_geometry(geom: dict, nd: int) -> dict | None:
    t = geom.get("type")
    c = geom.get("coordinates")
    if not c:
        return None
    if t == "Polygon":
        rp = round_polygon(c, nd)
        return {"type": "Polygon", "coordinates": rp} if rp else None
    if t == "MultiPolygon":
        polys = [p for p in (round_polygon(poly, nd) for poly in c) if p]
        return {"type": "MultiPolygon", "coordinates": polys} if polys else None
    return None


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src_path, out_path = sys.argv[1], sys.argv[2]
    nd = int(sys.argv[3]) if len(sys.argv) > 3 else NDIGITS_DEFAULT

    with open(src_path, encoding="utf-8") as fh:
        data = json.load(fh)

    out_features = []
    skipped = 0
    for feature in data.get("features", []):
        geom = feature.get("geometry")
        if not geom:
            skipped += 1
            continue
        rg = round_geometry(geom, nd)
        if rg is None:
            skipped += 1
            continue
        kode = (feature.get("properties") or {}).get("FUNGSIKWS")
        out_features.append(
            {
                "type": "Feature",
                "properties": {"fungsikws": None if kode is None else int(kode)},
                "geometry": rg,
            }
        )

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {"type": "FeatureCollection", "features": out_features},
            fh,
            separators=(",", ":"),
        )

    print(f"selesai: {len(out_features)} fitur ({skipped} dilewati) -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
