"""Rekap titik panas per skema perhutanan sosial, termasuk silang per provinsi.

Angka yang sama dipakai di tiga tempat (sheet Excel, laporan PDF agregat, dan
tampilan Matriks Data lewat data hotspot yang sama), jadi agregasinya hanya
ditulis sekali di sini.
"""

from collections import Counter
from dataclasses import dataclass

from app.services.polygon_fields import provinsi_name, skema_name


@dataclass(frozen=True)
class SkemaProvinsiRow:
    """Satu baris provinsi: jumlah per skema (urutannya mengikuti `matrix.skema`)."""

    provinsi: str
    counts: tuple[int, ...]
    total: int


@dataclass(frozen=True)
class SkemaProvinsiMatrix:
    skema: tuple[str, ...]
    rows: tuple[SkemaProvinsiRow, ...]
    totals: tuple[int, ...]
    grand_total: int


def count_per_skema(hotspots: list[dict]) -> list[tuple[str, int]]:
    """Total titik panas per skema, terbanyak lebih dulu."""
    return Counter(skema_name(hotspot) for hotspot in hotspots).most_common()


def build_skema_provinsi_matrix(hotspots: list[dict]) -> SkemaProvinsiMatrix:
    """Tabel silang provinsi (baris) x skema (kolom).

    Baris dan kolom sama-sama diurutkan dari jumlah terbanyak: tabelnya bisa
    selebar delapan kolom dan pembaca laporan hampir selalu berhenti di
    beberapa kolom pertama.
    """
    pair_counts: Counter[tuple[str, str]] = Counter()
    for hotspot in hotspots:
        pair_counts[(provinsi_name(hotspot), skema_name(hotspot))] += 1

    skema_totals: Counter[str] = Counter()
    provinsi_totals: Counter[str] = Counter()
    for (provinsi, skema), count in pair_counts.items():
        skema_totals[skema] += count
        provinsi_totals[provinsi] += count

    skema = tuple(
        label for label, _ in sorted(skema_totals.items(), key=lambda item: (-item[1], item[0]))
    )
    rows = tuple(
        SkemaProvinsiRow(
            provinsi=provinsi,
            counts=tuple(pair_counts.get((provinsi, label), 0) for label in skema),
            total=total,
        )
        for provinsi, total in sorted(provinsi_totals.items(), key=lambda item: (-item[1], item[0]))
    )
    totals = tuple(skema_totals[label] for label in skema)

    return SkemaProvinsiMatrix(
        skema=skema,
        rows=rows,
        totals=totals,
        grand_total=sum(totals),
    )


def collapse_skema_columns(
    matrix: SkemaProvinsiMatrix, max_columns: int, other_label: str = "Lainnya"
) -> SkemaProvinsiMatrix:
    """Batasi jumlah kolom skema, sisanya digabung ke satu kolom `other_label`.

    Dipakai laporan PDF yang lebarnya tetap (A4 lanskap): kalau sumber data
    suatu saat memuat lebih banyak skema, tabelnya memampat alih-alih melewati
    batas kertas. Total per provinsi tidak berubah.
    """
    if max_columns < 1 or len(matrix.skema) <= max_columns:
        return matrix

    kept = matrix.skema[: max_columns - 1]
    skema = (*kept, other_label)
    rows = tuple(
        SkemaProvinsiRow(
            provinsi=row.provinsi,
            counts=(*row.counts[: max_columns - 1], sum(row.counts[max_columns - 1 :])),
            total=row.total,
        )
        for row in matrix.rows
    )
    totals = (*matrix.totals[: max_columns - 1], sum(matrix.totals[max_columns - 1 :]))

    return SkemaProvinsiMatrix(
        skema=skema,
        rows=rows,
        totals=totals,
        grand_total=matrix.grand_total,
    )
