from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.core.auth import TokenClaims, get_current_user_claims
from app.models.query import HotspotQuery
from app.services.hotspot_service import HotspotService
from app.services.polygon_fields import PROVINSI_FALLBACK, provinsi_name
from app.services.stats_service import build_stats


router = APIRouter()


@router.get("/hotspots")
async def get_hotspots(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    satellites: list[str] = Query(default=[]),
    active_layers: list[str] = Query(default=[]),
    view: str | None = Query(default=None),
    claims: TokenClaims | None = Depends(get_current_user_claims),
) -> dict[str, object]:
    query = HotspotQuery(
        start_at=_resolve_start_at(start_at, start_date),
        end_at=_resolve_end_at(end_at, end_date),
        satellites=satellites,
        active_layers=active_layers,
    )
    service = HotspotService()
    result = await service.fetch_filtered_hotspots(query)

    hotspots = result.get("hotspots", [])
    if claims and claims.role == "bps" and claims.wilker_bps:
        hotspots = [
            h for h in hotspots
            if (h.get("polygon_metadata") or {}).get("WILKER_BPS") == claims.wilker_bps
        ]
        result = {
            **result,
            "count": len(hotspots),
            "hotspots": hotspots,
            "stats": build_stats(hotspots),
        }

    if view == "map":
        return {
            **result,
            "hotspots": [_to_map_hotspot(hotspot) for hotspot in hotspots],
        }

    return result


def _resolve_start_at(start_at: datetime | None, start_date: date | None) -> datetime:
    if start_at is not None:
        return _normalize_datetime(start_at)
    if start_date is not None:
        return datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - timedelta(hours=24)


def _resolve_end_at(end_at: datetime | None, end_date: date | None) -> datetime:
    if end_at is not None:
        return _normalize_datetime(end_at)
    if end_date is not None:
        return datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _to_map_hotspot(hotspot: dict[str, object]) -> dict[str, object]:
    """Payload ringkas untuk peta.

    Sengaja tidak memuat polygon_metadata utuh (puluhan field per titik) supaya
    respons peta tetap kecil. WILKER_BPS tetap disertakan karena filter Wilker
    di panel peta memerlukannya: tanpa ini daftar pilihannya selalu kosong dan
    dropdown-nya terlihat rusak.
    """
    metadata = hotspot.get("polygon_metadata") or {}
    wilker = metadata.get("WILKER_BPS") if isinstance(metadata, dict) else None
    # `hotspot_observations` tidak punya kolom province_name sendiri -- untuk
    # hotspot yang baru dicocokkan di request ini (spatial_service.py,
    # in-memory) province_name ada di top-level dict, tapi untuk hotspot yang
    # lewat _hydrate_polygon_metadata (join DB, read_hotspot_observations)
    # provinsinya cuma masuk ke polygon_metadata["NAMA_PROV"] -- tanpa
    # fallback ini popup peta selalu menampilkan "Tidak tersedia" walau
    # lembaga/KPS-nya sendiri kebetulan sudah benar (agency_name kolom
    # tersendiri di tabel, jadi tidak kena masalah yang sama). Pakai helper
    # bersama provinsi_name() (dipakai juga export XLSX/PDF) supaya alias
    # NAMA_PROV/NAMA_PROVINSI/PROVINSI konsisten satu tempat -- tapi
    # fallback stringnya ("Tanpa Provinsi") diabaikan di sini, biar peta
    # tetap tampil "Tidak tersedia" seperti field lain yang genuinely kosong.
    province_name = provinsi_name(hotspot)
    if province_name == PROVINSI_FALLBACK:
        province_name = None

    payload: dict[str, object] = {
        "id": hotspot.get("id"),
        "source": hotspot.get("source"),
        "satellite": hotspot.get("satellite"),
        "latitude": hotspot.get("latitude"),
        "longitude": hotspot.get("longitude"),
        "brightness": hotspot.get("brightness"),
        "frp": hotspot.get("frp"),
        "confidence": hotspot.get("confidence"),
        "detected_at": hotspot.get("detected_at"),
        "agency_name": hotspot.get("agency_name"),
        "province_name": province_name,
    }

    # Key-nya sama sekali tidak dikirim kalau Wilker tidak diketahui, supaya
    # payload tetap seminimal sebelumnya untuk titik tanpa metadata.
    if wilker:
        payload["polygon_metadata"] = {"WILKER_BPS": wilker}

    # Hanya 2 field ringkas dari atribusi fungsi kawasan hutan -- objek
    # kawasan_hutan lengkap sengaja tidak dikirim ke peta.
    kawasan = hotspot.get("kawasan_hutan")
    if isinstance(kawasan, dict):
        fungsi = kawasan.get("fungsi")
        kelompok = kawasan.get("kelompok")
        if fungsi:
            payload["fungsi_kawasan"] = fungsi
        if kelompok:
            payload["kelompok"] = kelompok

    return payload
