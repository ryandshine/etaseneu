from __future__ import annotations


class FakePostgresStore:
    def __init__(self) -> None:
        self.enabled = True
        self.rows: dict[int, dict[str, object]] = {}
        self.gambut: dict[int, dict[str, object]] = {}

    def read_polygon_detail(self, polygon_metadata_id: int, *, tolerance: float | None = 0.0001):
        self.last_tolerance = tolerance
        row = self.rows.get(polygon_metadata_id)
        return dict(row) if row is not None else None

    def read_polygon_detail_by_agency(self, agency: str, *, tolerance: float | None = 0.0001):
        self.last_tolerance = tolerance
        for row in self.rows.values():
            if row.get("lembaga") == agency:
                return dict(row)
        return None

    def read_gambut_summary(self, polygon_metadata_id: int):
        return self.gambut.get(polygon_metadata_id)


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


def test_get_polygon_detail_forwards_tolerance_to_store() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    fake.rows[7] = _sample_row(7)
    service.postgres_store = fake

    service.get_polygon_detail(7, tolerance=None)
    assert fake.last_tolerance is None

    service.get_polygon_detail(7, tolerance=0.001)
    assert fake.last_tolerance == 0.001


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


def test_get_polygon_detail_by_agency_found() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    fake.rows[10] = _sample_row(10)
    service.postgres_store = fake

    detail = service.get_polygon_detail_by_agency("LPHD SEBUBUS")
    assert detail is not None
    assert detail.id == 10
    assert detail.lembaga == "LPHD SEBUBUS"


def test_get_polygon_detail_by_agency_not_found() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    service.postgres_store = fake

    assert service.get_polygon_detail_by_agency("NON_EXISTENT") is None


def test_get_polygon_detail_attaches_gambut_summary_when_present() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    fake.rows[42] = _sample_row(42)
    fake.gambut[42] = {
        "total_ha": 60.25,
        "by_fungsi": {"Lindung": 40.0, "Budidaya": 20.25},
        "khg": [
            {
                "kode_khg": "KHG.61.06.02",
                "nama_khg": "KHG Sungai Embalon - Sungai Palin",
                "fungsi": "Lindung",
                "kubah_gmbt": "Non Kubah Gambut",
                "luas_ha": 40.0,
            }
        ],
    }
    service.postgres_store = fake

    detail = service.get_polygon_detail(42)

    assert detail is not None
    assert detail.gambut == fake.gambut[42]


def test_get_polygon_detail_gambut_none_when_polygon_not_peat() -> None:
    """Mayoritas KPS -- tidak beririsan gambut sama sekali -- gambut harus None,
    bukan objek kosong, supaya frontend gampang cek `if (detail.gambut)`."""
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    fake.rows[42] = _sample_row(42)
    service.postgres_store = fake

    detail = service.get_polygon_detail(42)

    assert detail is not None
    assert detail.gambut is None


def test_get_polygon_detail_by_agency_attaches_gambut_summary() -> None:
    from app.services.polygon_service import PolygonService

    service = PolygonService("postgresql://demo")
    fake = FakePostgresStore()
    fake.rows[10] = _sample_row(10)
    fake.gambut[10] = {"total_ha": 5.0, "by_fungsi": {"Lindung": 5.0}, "khg": []}
    service.postgres_store = fake

    detail = service.get_polygon_detail_by_agency("LPHD SEBUBUS")

    assert detail is not None
    assert detail.gambut == fake.gambut[10]
