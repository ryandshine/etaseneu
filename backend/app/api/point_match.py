"""Endpoint publik: unggah berkas titik, cocokkan ke KPS, unduh laporannya."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from app.services.point_match_service import (
    MAX_POINTS,
    MAX_UPLOAD_BYTES,
    MatchOutcome,
    PointMatchError,
    match_uploaded_points,
)
from app.services.point_report_service import (
    build_excel_file,
    build_pdf_file,
    build_report_rows,
)
from app.services.point_result_store import point_result_store, upload_rate_limiter
from app.services.point_upload_parser import SUPPORTED_EXTENSIONS, PointParseError
from app.services.postgres_store import PostgresStore
from app.core.config import get_settings

router = APIRouter()

# Baris yang dikirim balik ke browser dibatasi supaya respons tetap ringan.
# Data lengkapnya tetap ada di server (untuk Excel/PDF), jadi tidak ada yang
# hilang -- yang dibatasi hanya pratinjau di layar.
PREVIEW_LIMIT = 500


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _slugify(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    return "-".join(part for part in cleaned.split("-") if part) or "hasil"


def _outcome_payload(outcome: MatchOutcome, token: str, source_name: str) -> dict[str, Any]:
    summary = outcome.summary
    rows = build_report_rows(outcome)
    return {
        "token": token,
        "source_name": source_name,
        "source_format": outcome.source_format,
        "warnings": outcome.warnings,
        "skipped_features": outcome.skipped_features,
        "summary": {
            "total_points": summary.total_points,
            "inside_count": summary.inside_count,
            "outside_count": summary.outside_count,
            "distinct_kps": summary.distinct_kps,
            "by_kps": summary.by_kps,
            "by_wilker": summary.by_wilker,
            "by_province": summary.by_province,
        },
        "property_columns": outcome.property_columns,
        "preview_rows": rows[:PREVIEW_LIMIT],
        "preview_truncated": len(rows) > PREVIEW_LIMIT,
    }


@router.post("/point-match/analyze")
async def analyze_points(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    allowed, retry_after = upload_rate_limiter.check(_client_key(request))
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Terlalu banyak unggahan. Coba lagi beberapa menit lagi.",
            headers={"Retry-After": str(retry_after)},
        )

    filename = file.filename or ""
    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=(
                "Format berkas tidak didukung. Gunakan .geojson, .json, .kml, "
                "atau .zip berisi shapefile."
            ),
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Berkas kosong.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Ukuran berkas melebihi batas {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )

    settings = get_settings()
    store = PostgresStore(settings.database_url)

    try:
        outcome = match_uploaded_points(raw, filename, store)
    except (PointParseError, PointMatchError) as exc:
        # Pesan dari lapisan ini memang ditulis untuk pengguna akhir.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = point_result_store.put(outcome, filename)
    return _outcome_payload(outcome, token, filename)


def _load(token: str):
    stored = point_result_store.get(token)
    if stored is None:
        raise HTTPException(
            status_code=404,
            detail="Hasil sudah kedaluwarsa atau tidak ditemukan. Silakan unggah ulang berkasnya.",
        )
    return stored


@router.get("/point-match/{token}/export.xlsx")
async def export_point_match_excel(token: str) -> Response:
    stored = _load(token)
    return Response(
        content=build_excel_file(stored.outcome, stored.source_name),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f"attachment; filename=eta-seuneu-cek-titik-{_slugify(stored.source_name)}.xlsx"
            )
        },
    )


@router.get("/point-match/{token}/export.pdf")
async def export_point_match_pdf(token: str) -> Response:
    stored = _load(token)
    return Response(
        content=build_pdf_file(stored.outcome, stored.source_name),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f"attachment; filename=eta-seuneu-cek-titik-{_slugify(stored.source_name)}.pdf"
            )
        },
    )


@router.get("/point-match/limits")
async def point_match_limits() -> dict[str, Any]:
    """Batas yang berlaku, supaya UI bisa memberi tahu sebelum pengguna mengunggah."""
    return {
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "max_points": MAX_POINTS,
        "supported_extensions": list(SUPPORTED_EXTENSIONS),
    }
