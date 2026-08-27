from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from app.services.hotspot_cluster_service import HotspotClusterService


router = APIRouter()


# Parameter mentah (eps_km/eps_hours/min_samples) sengaja TIDAK diekspos
# langsung ke API publik -- diterjemahkan lewat tiga preset bahasa awam
# supaya frontend tidak perlu tahu istilah teknis DBSCAN. "sedang" adalah
# parameter yang sudah divalidasi terhadap data hotspot produksi sungguhan
# (lihat riwayat sesi perencanaan fitur ini).
SENSITIVITY_PRESETS: dict[str, dict[str, float]] = {
    "ketat": {"eps_km": 1.0, "eps_hours": 12.0, "min_samples": 4, "location_eps_km": 0.5},
    "sedang": {"eps_km": 2.0, "eps_hours": 48.0, "min_samples": 4, "location_eps_km": 1.0},
    "longgar": {"eps_km": 5.0, "eps_hours": 72.0, "min_samples": 3, "location_eps_km": 2.5},
}


@router.get("/hotspots/clusters")
async def get_hotspot_clusters(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    sensitivity: str = Query(default="sedang"),
) -> dict[str, object]:
    preset = SENSITIVITY_PRESETS.get(sensitivity, SENSITIVITY_PRESETS["sedang"])

    resolved_end_at = _normalize_datetime(end_at) if end_at else datetime.now(timezone.utc)
    resolved_start_at = (
        _normalize_datetime(start_at) if start_at else resolved_end_at - timedelta(days=7)
    )

    service = HotspotClusterService()
    result = service.compute_clusters(
        start_at=resolved_start_at,
        end_at=resolved_end_at,
        eps_km=preset["eps_km"],
        eps_hours=preset["eps_hours"],
        min_samples=int(preset["min_samples"]),
        location_eps_km=preset["location_eps_km"],
    )

    return {
        **result,
        "sensitivity": sensitivity if sensitivity in SENSITIVITY_PRESETS else "sedang",
        "range_start": resolved_start_at.isoformat(),
        "range_end": resolved_end_at.isoformat(),
    }


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
