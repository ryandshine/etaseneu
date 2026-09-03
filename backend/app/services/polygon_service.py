from functools import lru_cache

from app.core.config import get_settings
from app.models.polygons import PolygonDetail
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


@lru_cache(maxsize=1)
def get_polygon_service() -> PolygonService:
    return PolygonService(get_settings().database_url)
