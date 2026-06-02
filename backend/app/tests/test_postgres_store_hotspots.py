from __future__ import annotations


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)


class FakeConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.cursor_obj = FakeCursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


def test_read_hotspot_observations_enriches_polygon_metadata(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    rows = [
        {
            "raw_payload": {
                "source": "MODIS",
                "satellite": "Terra",
                "latitude": 4.1,
                "longitude": 95.1,
                "detected_at": "2026-05-02T12:00:00Z",
                "layer_id": "sample_area",
                "layer_name": "sample_area",
                "agency_name": "sample_area",
            },
            "polygon_metadata_id": 99,
            "feature_key": "feature-1",
            "lembaga": "LPHD Demo",
            "nama_prov": "Jawa Tengah",
            "nama_kab": "Blora",
            "nama_kec": "Randublatung",
            "nama_desa": "Ngudi Jati",
            "skema": "PKK",
            "no_sk": "SK.001",
            "tgl_sk": "2026-01-01",
            "status": "PS 33",
            "wilker_bps": "Balai PS Yogyakarta",
            "ps_id": "331623",
            "kode_prov": "33",
            "kode_kab": "3316",
            "luas_hk": "0",
            "luas_hl": "0",
            "luas_hpt": "0",
            "luas_hp": "0",
            "luas_hpk": "0",
            "luas_sk": "0",
            "luas_poli": "0",
            "luas_final": "1960.23",
            "jml_kk": "13",
            "shape_leng": "36050.0640519",
            "shape_area": "19602261.8459",
            "properties_raw": {"LEMBAGA": "LPHD Demo"},
        }
    ]

    store = PostgresStore("postgresql://demo")

    class _FakeConnection:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor(rows)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return self.cursor_obj

    fake_connection = _FakeConnection()
    monkeypatch.setattr(store, "connection", lambda: fake_connection)

    payloads = store.read_hotspot_observations(
        start_date="2026-05-01",
        end_date="2026-05-31",
        sources=["MODIS"],
        layer_ids=["sample_area"],
    )

    assert len(payloads) == 1
    polygon_metadata = payloads[0]["polygon_metadata"]
    assert polygon_metadata["LEMBAGA"] == "LPHD Demo"
    assert polygon_metadata["NAMA_PROV"] == "Jawa Tengah"
    assert polygon_metadata["NAMA_KAB"] == "Blora"
    assert polygon_metadata["PS_ID"] == "331623"
    assert polygon_metadata["LuasFinal"] == "1960.23"

    executed_query = fake_connection.cursor_obj.executed[0][0]
    assert "ST_Covers(p.geometry, obs.geom)" in executed_query
    assert "JOIN polygon_metadata p" in executed_query
    assert "hotspot_polygon_relation" not in executed_query


def test_rebuild_polygon_hotspot_summary_uses_current_polygon_geometry(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    class _FakeConnection:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor([])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return self.cursor_obj

    store = PostgresStore("postgresql://demo")
    fake_connection = _FakeConnection()
    monkeypatch.setattr(store, "connection", lambda: fake_connection)

    store.rebuild_polygon_hotspot_summary([99])

    first_query = fake_connection.cursor_obj.executed[1][0]
    assert "FROM polygon_metadata p" in first_query
    assert "ST_Covers(p.geometry, obs.geom)" in first_query
    assert "hotspot_polygon_relation" not in first_query


def test_refresh_polygon_hotspot_summaries_rebuilds_active_and_prunes_stale_rows(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    class _FakeConnection:
        def __init__(self) -> None:
            self.cursor_obj = FakeCursor([])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return self.cursor_obj

    store = PostgresStore("postgresql://demo")
    fake_connection = _FakeConnection()
    monkeypatch.setattr(store, "connection", lambda: fake_connection)
    monkeypatch.setattr(store, "read_active_polygon_metadata_ids", lambda layer_keys=None: [11, 22])
    monkeypatch.setattr(store, "rebuild_polygon_hotspot_summary", lambda polygon_metadata_ids: len(polygon_metadata_ids))

    summary = store.refresh_polygon_hotspot_summaries()

    assert summary["active_polygon_count"] == 2
    assert summary["rebuilt"] == 2
    assert len(fake_connection.cursor_obj.executed) >= 1
    assert "DELETE FROM polygon_hotspot_summary" in fake_connection.cursor_obj.executed[0][0]
