from __future__ import annotations


class FakePostgresStore:
    def __init__(self) -> None:
        self.enabled = True
        self.rows: dict[int, dict[str, object]] = {}

    def read_polygon_detail(self, polygon_metadata_id: int):
        return self.rows.get(polygon_metadata_id)


def _sample_row(polygon_metadata_id: int) -> dict[str, object]:
    return {
        "id": polygon_metadata_id,
        "layer_key": "PS_FEB_26",
        "feature_key": "abc123",
        "lembaga": "LPHD SEBUBUS",
        "nama_prov": "KALIMANTAN BARAT",
        "nama_kab": None,
        "nama_kec": None,
        "nama_desa": None,
        "skema": None,
        "no_sk": None,
        "tgl_sk": None,
        "status": None,
        "wilker_bps": "Balai PS Banjarbaru",
        "ps_id": "PS-001",
        "luas_final": "120.5",
        "jml_kk": "35",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[107.0, -1.0], [107.1, -1.0], [107.1, -1.1], [107.0, -1.0]]],
        },
    }


def test_get_polygon_detail_returns_model_when_found() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    fake.rows[42] = _sample_row(42)
    service.postgres_store = fake

    detail = service.get_polygon_detail(42)

    assert detail is not None
    assert detail.id == 42
    assert detail.lembaga == "LPHD SEBUBUS"
    assert detail.geometry["type"] == "Polygon"


def test_get_polygon_detail_returns_none_when_not_found() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    service.postgres_store = FakePostgresStore()

    assert service.get_polygon_detail(999) is None


def test_get_polygon_detail_returns_none_when_store_disabled() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    fake.enabled = False
    fake.rows[1] = _sample_row(1)
    service.postgres_store = fake

    assert service.get_polygon_detail(1) is None
