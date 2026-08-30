"""Wiring mixin tutupan lahan. TIDAK menyentuh DB — hanya cek method ada
di PostgresStore (bahaya #1: tidak ada DB test terpisah)."""

from app.services.postgres_store import PostgresStore

EXPECTED = [
    "read_land_cover_target_polygon",
    "mark_land_cover_running",
    "mark_land_cover_error",
    "save_land_cover_result",
    "read_land_cover_status",
    "read_land_cover_result",
    "read_land_cover_overlay",
]


def test_postgres_store_exposes_land_cover_methods() -> None:
    for name in EXPECTED:
        assert callable(getattr(PostgresStore, name, None)), name
