from datetime import datetime
from functools import lru_cache
from typing import Any

from app.core.config import get_settings
from app.models.polygons import PolygonDetail
from app.services.fire_spread_service import degrees_to_compass
from app.services.hotspot_service import _query_sources
from app.services.postgres_store import PostgresStore


class PolygonService:
    def __init__(self, database_url: str) -> None:
        self.postgres_store = PostgresStore(database_url)

    def get_polygon_detail(
        self, polygon_metadata_id: int, *, tolerance: float | None = 0.0001
    ) -> PolygonDetail | None:
        if not self.postgres_store.enabled:
            return None

        row = self.postgres_store.read_polygon_detail(
            polygon_metadata_id, tolerance=tolerance
        )
        if row is None:
            return None

        return PolygonDetail(**row)

    def get_polygon_detail_by_agency(
        self, agency: str, *, tolerance: float | None = 0.0001
    ) -> PolygonDetail | None:
        if not self.postgres_store.enabled:
            return None

        row = self.postgres_store.read_polygon_detail_by_agency(
            agency, tolerance=tolerance
        )
        if row is None:
            return None

        return PolygonDetail(**row)

    def get_surrounding_hotspots(
        self,
        polygon_id: int,
        *,
        buffer_km: float = 5.0,
        start_at: datetime,
        end_at: datetime,
        satellites: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ambil seluruh hotspot di dalam dan di sekitar (buffer) poligon KPS."""
        if not self.postgres_store.enabled:
            return {
                "polygon_id": polygon_id,
                "buffer_km": buffer_km,
                "total_inside": 0,
                "total_outside": 0,
                "total_hotspots": 0,
                "hotspots": [],
            }

        sources = _query_sources(satellites) if satellites else None
        rows = self.postgres_store.read_polygon_surrounding_hotspots(
            polygon_id=polygon_id,
            buffer_km=buffer_km,
            start_at=start_at,
            end_at=end_at,
            sources=sources,
        )

        formatted_hotspots = []
        inside_count = 0
        outside_count = 0

        for r in rows:
            is_inside = bool(r.get("is_inside", False))
            dist_m = int(r.get("distance_m") or 0)
            bearing_deg = (
                float(r["bearing_deg"]) if r.get("bearing_deg") is not None else None
            )
            compass = degrees_to_compass(bearing_deg) if not is_inside else "Dalam Kawasan"

            if is_inside:
                inside_count += 1
                threat_origin = "internal"
                threat_origin_label = "Di Dalam Kawasan"
            else:
                outside_count += 1
                is_non_kps = r.get("layer_key") == "perimeter_threat"
                threat_origin = "non_kps" if is_non_kps else "neighbor_kps"
                threat_origin_label = (
                    "Luar Kawasan (Bukan KPS)"
                    if is_non_kps
                    else f"KPS Tetangga ({r.get('agency_name') or 'Lain'})"
                )

            raw_payload = r.get("raw_payload") or {}
            if not isinstance(raw_payload, dict):
                raw_payload = {}

            formatted_hotspots.append({
                "id": str(r["id"]),
                "source": r.get("source"),
                "satellite": r.get("satellite"),
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
                "brightness": float(r["brightness"]) if r.get("brightness") is not None else None,
                "confidence": r.get("confidence"),
                "frp": float(r["frp"]) if r.get("frp") is not None else 0.0,
                "detected_at": r.get("detected_at"),
                "is_inside": is_inside,
                "distance_m": dist_m,
                "distance_km": round(dist_m / 1000.0, 2),
                "bearing_deg": round(bearing_deg, 1) if bearing_deg is not None else None,
                "bearing_compass": compass,
                "threat_origin": threat_origin,
                "threat_origin_label": threat_origin_label,
                "agency_name": r.get("agency_name"),
                "layer_key": r.get("layer_key"),
                "polygon_metadata": {
                    "LEMBAGA": r.get("agency_name")
                    or ("Dalam Kawasan" if is_inside else "Luar Kawasan"),
                    "is_external": not is_inside,
                    "distance_m": dist_m,
                    "bearing_compass": compass,
                },
            })

        return {
            "polygon_id": polygon_id,
            "buffer_km": buffer_km,
            "total_inside": inside_count,
            "total_outside": outside_count,
            "total_hotspots": len(formatted_hotspots),
            "hotspots": formatted_hotspots,
        }


@lru_cache(maxsize=1)
def get_polygon_service() -> PolygonService:
    return PolygonService(get_settings().database_url)

