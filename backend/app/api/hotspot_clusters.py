from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query

from app.core.auth import TokenClaims, get_current_user_claims
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
    wilker_bps: str | None = None,
    claims: TokenClaims | None = Depends(get_current_user_claims),
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

    target_wilker = (claims.wilker_bps if claims and claims.role == "bps" else None) or wilker_bps
    if target_wilker:
        target_norm = "".join(ch.lower() for ch in target_wilker if ch.isalnum())
        filtered_clusters = [
            c for c in result.get("clusters", [])
            if (
                target_norm in "".join(ch.lower() for ch in str(c.get("dominant_wilker") or "") if ch.isalnum())
                or any(
                    target_norm in "".join(ch.lower() for ch in str(w.get("name") or "") if ch.isalnum())
                    for w in c.get("affected_wilkers", [])
                )
            )
        ]
        cluster_ids = {c["cluster_id"] for c in filtered_clusters}
        filtered_points = [p for p in result.get("points", []) if p.get("cluster_id") in cluster_ids]
        result = {
            **result,
            "count": len(filtered_clusters),
            "clusters": filtered_clusters,
            "points": filtered_points,
        }

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
