from __future__ import annotations

import contextlib


class FakeCursor:
    def __init__(self, fetchall_result=None, fetchone_result=None, rowcount: int = 0) -> None:
        self._fetchall_result = fetchall_result or []
        self._fetchone_result = fetchone_result
        self.executed: list[tuple[str, object]] = []
        self.executemany_calls: list[tuple[str, list]] = []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params=()) -> None:
        self.executed.append((query, params))

    def executemany(self, query: str, params_list) -> None:
        self.executemany_calls.append((query, list(params_list)))

    def fetchall(self):
        return self._fetchall_result

    def fetchone(self):
        return self._fetchone_result


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


def _store_with_fake_cursor(monkeypatch, **cursor_kwargs):
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    cursor = FakeCursor(**cursor_kwargs)

    @contextlib.contextmanager
    def fake_connection():
        yield FakeConnection(cursor)

    monkeypatch.setattr(store, "connection", fake_connection)
    return store, cursor


def test_clear_burned_area_summary_deletes_all_rows(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch, rowcount=36565)

    result = store.clear_burned_area_summary()

    assert result == 36565
    query, _params = cursor.executed[0]
    assert "DELETE FROM burned_area_summary" in query


def test_refresh_burned_area_from_klhk_overlays_and_upserts(monkeypatch) -> None:
    """Overlay per (year, month) -- poligon terbakar bulan yang sama harus
    di-ST_Union dulu sebelum di-intersect ke KPS, supaya kebakaran yang
    tumpang tindih di sumber KLHK sendiri tidak dihitung dobel."""
    fake_overlay_rows = [
        {
            "polygon_metadata_id": 1,
            "layer_key": "psagustus2026",
            "year": 2026,
            "month": 5,
            "burned_area_ha": 12.5,
            "geometry_json": {"type": "MultiPolygon", "coordinates": []},
        },
        {
            "polygon_metadata_id": 2,
            "layer_key": "HUTAN_ADAT_APR26",
            "year": 2026,
            "month": 6,
            "burned_area_ha": 3.2,
            "geometry_json": {"type": "MultiPolygon", "coordinates": []},
        },
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_overlay_rows)

    features = [
        (2026, 5, {"type": "MultiPolygon", "coordinates": []}),
        (2026, 5, {"type": "MultiPolygon", "coordinates": []}),
        (2026, 6, {"type": "MultiPolygon", "coordinates": []}),
    ]
    computed = store.refresh_burned_area_from_klhk(features, source="KLHK - Areal Kebakaran Hutan dan Lahan")

    assert computed == 2

    insert_calls = [c for c in cursor.executemany_calls if "klhk_burned_features" in c[0]]
    assert len(insert_calls) == 1
    assert len(insert_calls[0][1]) == 3

    overlay_query = next(q for q, _p in cursor.executed if "monthly_union" in q)
    assert "ST_Union(geom)" in overlay_query
    assert "GROUP BY year, month" in overlay_query
    assert "ST_Intersects(p.geometry, m.geom)" in overlay_query
    assert "WHERE p.is_active" in overlay_query

    upsert_calls = [c for c in cursor.executemany_calls if "INSERT INTO burned_area_summary" in c[0]]
    assert len(upsert_calls) == 1
    params = upsert_calls[0][1]
    assert len(params) == 2
    assert params[0][:4] == (1, "psagustus2026", 2026, 5)
    assert params[0][5] == "KLHK - Areal Kebakaran Hutan dan Lahan"


def test_refresh_burned_area_from_klhk_handles_no_overlap(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=[])

    computed = store.refresh_burned_area_from_klhk([(2026, 5, {"type": "MultiPolygon", "coordinates": []})])

    assert computed == 0


def test_upsert_burned_area_summary_writes_rows(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch)

    rows = [
        {"polygon_metadata_id": 1, "layer_key": "PS_FEB_26", "year": 2026, "month": 4, "burned_area_ha": 12.5},
        {"polygon_metadata_id": 2, "layer_key": "PS_FEB_26", "year": 2026, "month": 4, "burned_area_ha": 0.0},
    ]

    count = store.upsert_burned_area_summary(rows)

    assert count == 2
    assert len(cursor.executemany_calls) == 1
    query, params = cursor.executemany_calls[0]
    assert "INSERT INTO burned_area_summary" in query
    assert "ON CONFLICT (polygon_metadata_id, year, month)" in query
    # Kolom terakhir = geometry (NULL kalau baris tidak membawa geometry_geojson).
    assert params[0] == (1, "PS_FEB_26", 2026, 4, 12.5, "MODIS/061/MCD64A1", None)


def test_upsert_burned_area_summary_serializes_geometry(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch)

    geom = {"type": "MultiPolygon", "coordinates": [[[[109.0, 0.4], [109.1, 0.4], [109.1, 0.5], [109.0, 0.4]]]]}
    store.upsert_burned_area_summary(
        [
            {
                "polygon_metadata_id": 43617,
                "layer_key": "PS_FEB_26",
                "year": 2026,
                "month": 1,
                "burned_area_ha": 149.0,
                "geometry_geojson": geom,
            }
        ]
    )

    _query, params = cursor.executemany_calls[0]
    import json as _json

    assert _json.loads(params[0][6]) == geom


def test_upsert_burned_area_summary_empty_is_noop(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    assert store.upsert_burned_area_summary([]) == 0


def test_read_burned_area_summary_filters_by_year_and_month(monkeypatch) -> None:
    fake_rows = [
        {"polygon_metadata_id": 1, "layer_key": "PS_FEB_26", "year": 2026, "month": 4, "burned_area_ha": 5.0}
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.read_burned_area_summary(year=2026, month=4)

    assert result == fake_rows
    query, params = cursor.executed[0]
    assert "year = %s" in query
    assert "month = %s" in query
    assert params == [2026, 4]


def test_read_burned_area_geometries_unions_real_and_estimated_rows(monkeypatch) -> None:
    """Baris burned_area_ha > 0 tanpa geometry (piksel MODIS cuma menyerempet
    tepi KPS, reduceToVectors tidak menghasilkan bentuk) harus tetap ikut
    dikirim -- sebagai centroid poligon, ditandai is_estimated=true -- bukan
    hilang begitu saja dari peta."""
    fake_rows = [
        {"polygon_metadata_id": 1, "year": 2026, "month": 3, "burned_area_ha": 50.0,
         "geometry_json": {"type": "Polygon", "coordinates": []}, "is_estimated": False},
        {"polygon_metadata_id": 2, "year": 2026, "month": 3, "burned_area_ha": 2.1,
         "geometry_json": {"type": "Point", "coordinates": [110.0, -1.0]}, "is_estimated": True},
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.read_burned_area_geometries([1, 2], year=2026)

    assert result == fake_rows
    query, params = cursor.executed[0]
    assert "UNION ALL" in query
    assert "ST_Centroid(p.geometry)" in query
    assert "geometry IS NULL AND b.burned_area_ha > 0" in query
    assert "TRUE AS is_estimated" in query
    assert "FALSE AS is_estimated" in query
    # filter tahun harus diterapkan di kedua sisi UNION, bukan cuma satu
    assert params == [[1, 2], 2026, [1, 2], 2026]


def test_read_burned_area_geometries_empty_polygon_list(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    assert store.read_burned_area_geometries([]) == []


def test_read_burned_area_map_overlay_groups_one_feature_per_kps(monkeypatch) -> None:
    """Peta utama menjawab "KPS mana yang terdampak", bukan "apa yang terbakar
    bulan apa" -- geometry bulanan harus digabung per KPS di server, supaya
    kawasan yang terbakar berulang tidak mengirim bentuk bertumpuk di titik
    yang sama."""
    fake_rows = [
        {"polygon_metadata_id": 49463, "lembaga": "KOPERASI X", "skema": "PPHKm",
         "nama_prov": "Riau", "wilker_bps": "BPSKL", "latest_period": 202604,
         "burned_months": 2, "burned_ha": 1786.3, "is_estimated": False,
         "geometry_json": {"type": "MultiPolygon", "coordinates": []}},
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.read_burned_area_map_overlay(year=2026)

    assert result == fake_rows
    query, params = cursor.executed[0]
    assert "ST_Union(b.geometry)" in query
    assert "GROUP BY b.polygon_metadata_id" in query
    # disederhanakan untuk peta, tapi tetap di bawah ukuran piksel MODIS 500m
    assert "ST_SimplifyPreserveTopology" in query
    # KPS tanpa geometry tetap ikut lewat centroid, tidak hilang dari peta
    assert "ST_Centroid(p.geometry)" in query
    assert "burned_geom IS NOT NULL OR unvectorized_ha > 0" in query
    assert params == [2026]


def test_burned_area_unique_ha_uses_st_union(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"ha": 124.1})

    result = store.burned_area_unique_ha([43617], year=2026)

    assert result == 124.1
    query, params = cursor.executed[0]
    assert "ST_Union(geometry)" in query
    assert params == [[43617], 2026]


def test_burned_area_unique_ha_query_combines_geometry_and_fallback(monkeypatch) -> None:
    """Regresi: versi awal cuma ST_Union tanpa GROUP BY per-poligon, jadi
    poligon dengan campuran bulan-ada-geometry dan bulan-tanpa-geometry
    diam-diam kehilangan kontribusi bulan yang tanpa geometry (bukan dobel
    hitung, tapi kurang hitung). Query sekarang harus menggabungkan
    keduanya per poligon (FILTER WHERE geometry IS NOT NULL / IS NULL)
    sebelum dijumlah lintas poligon."""
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"ha": 149.44})

    store.burned_area_unique_ha([49634])

    query, _params = cursor.executed[0]
    assert "GROUP BY polygon_metadata_id" in query
    assert "FILTER (WHERE geometry IS NOT NULL)" in query
    assert "FILTER (WHERE geometry IS NULL)" in query


def test_burned_area_by_skema_groups_and_filters(monkeypatch) -> None:
    fake_rows = [
        {"skema": "PPHKm", "kps_count": 10, "total_ha": 2413.9},
        {"skema": "PPHD", "kps_count": 10, "total_ha": 1866.5},
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.burned_area_by_skema(year=2026, layer_keys=["PS_FEB_26"])

    assert result == [
        {"skema": "PPHKm", "kps_count": 10, "total_ha": 2413.9},
        {"skema": "PPHD", "kps_count": 10, "total_ha": 1866.5},
    ]
    query, params = cursor.executed[0]
    assert "GROUP BY b.polygon_metadata_id, p.skema" in query
    assert "GROUP BY skema" in query
    assert params == [2026, ["PS_FEB_26"]]


def test_burned_area_unique_ha_returns_none_without_geometry(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"ha": None})
    assert store.burned_area_unique_ha([43617]) is None


def test_burned_area_unique_ha_empty_polygon_list(monkeypatch) -> None:
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    assert store.burned_area_unique_ha([]) is None


def test_latest_burned_area_period_returns_none_when_empty(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result=None)
    assert store.latest_burned_area_period() is None


def test_latest_burned_area_period_returns_tuple(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result={"year": 2026, "month": 4})
    assert store.latest_burned_area_period() == (2026, 4)


def test_save_burned_area_scheduler_state_upserts_single_row(monkeypatch) -> None:
    from datetime import datetime, timezone

    store, cursor = _store_with_fake_cursor(monkeypatch)

    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    store.save_burned_area_scheduler_state(
        last_run_at=now,
        last_successful_run_at=now,
        last_run_result={"success": True, "months": []},
        consecutive_failures=0,
    )

    query, params = cursor.executed[-1]
    assert "INSERT INTO burned_area_scheduler_state" in query
    assert "ON CONFLICT (id) DO UPDATE" in query
    assert params[0] == now
    assert params[1] == now
    assert params[3] == 0


def test_read_s2_burned_area_for_polygons_attaches_kawasan_breakdown(monkeypatch) -> None:
    fake_rows = [
        {
            "polygon_metadata_id": 49463,
            "layer_key": "psagustus2026",
            "year": 2026,
            "month": 8,
            "area_ha": 12.34,
            "hotspot_count_month": 3,
            "has_hotspot": True,
            "computed_at": None,
            "geometry_json": {"type": "MultiPolygon", "coordinates": []},
            "kawasan_rincian": [
                {"kode": 100500, "fungsi": "Hutan Produksi Tetap", "kelompok": "Produksi", "luas_ha": 10.0},
                {"kode": 100300, "fungsi": "Hutan Lindung", "kelompok": "Lindung", "luas_ha": 2.34},
            ],
            "kawasan_dominan": "Produksi",
        }
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.read_s2_burned_area_for_polygons([49463])

    assert result[0]["kawasan_dominan"] == "Produksi"
    assert result[0]["kawasan_rincian"][0]["fungsi"] == "Hutan Produksi Tetap"
    query = cursor.executed[-1][0]
    assert "LEFT JOIN LATERAL" in query
    assert "burned_kawasan_hutan bkh" in query


def test_read_s2_burned_area_overlay_puts_kawasan_dominan_in_properties(monkeypatch) -> None:
    fake_rows = [
        {
            "polygon_metadata_id": 49463,
            "area_ha": 20.0,
            "dnbr_mean": 0.51,
            "hotspot_count_month": 1,
            "has_hotspot": True,
            "computed_at": None,
            "lembaga": "KOPERASI X",
            "nama_prov": "Riau",
            "nama_kab": "Pelalawan",
            "geometry_json": {"type": "MultiPolygon", "coordinates": []},
            "kawasan_rincian": [
                {"kode": 100300, "fungsi": "Hutan Lindung", "kelompok": "Lindung", "luas_ha": 20.0}
            ],
            "kawasan_dominan": "Lindung",
        }
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.read_s2_burned_area_overlay(2026, 8)

    assert result["features"][0]["properties"]["kawasan_dominan"] == "Lindung"
    assert "LEFT JOIN LATERAL" in cursor.executed[-1][0]


def test_read_burned_area_by_kawasan_maps_rows_and_omits_province_filter(monkeypatch) -> None:
    fake_rows = [
        {"kode": 100300, "singkatan": "HP", "fungsi": "Hutan Produksi Tetap",
         "kelompok": "Produksi", "luas_ha": 6470.86},
        {"kode": 100100, "singkatan": "HL", "fungsi": "Hutan Lindung",
         "kelompok": "Lindung", "luas_ha": 2393.63},
    ]
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=fake_rows)

    result = store.read_burned_area_by_kawasan()

    assert result[0] == {
        "kode": 100300, "singkatan": "HP", "fungsi": "Hutan Produksi Tetap",
        "kelompok": "Produksi", "luas_ha": 6470.86,
    }
    query, params = cursor.executed[0]
    assert "burned_kemenhut_kawasan_hutan" in query
    assert "ref_fungsi_kawasan_label" in query
    assert "WHERE pm.nama_prov" not in query
    assert params == []


def test_read_burned_area_by_kawasan_applies_province_filter(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(monkeypatch, fetchall_result=[])

    store.read_burned_area_by_kawasan("Riau")

    query, params = cursor.executed[0]
    assert "WHERE pm.nama_prov = %s" in query
    assert params == ["Riau"]


def test_read_burned_area_scheduler_state_returns_none_when_no_row(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_result=None)
    assert store.read_burned_area_scheduler_state() is None


def test_read_burned_area_scheduler_state_parses_row(monkeypatch) -> None:
    import json as _json

    store, _cursor = _store_with_fake_cursor(
        monkeypatch,
        fetchone_result={
            "last_run_at": "2026-08-18T00:00:00+00:00",
            "last_successful_run_at": "2026-08-18T00:00:00+00:00",
            "last_run_result": _json.dumps({"success": True}),
            "consecutive_failures": 0,
        },
    )

    result = store.read_burned_area_scheduler_state()

    assert result["last_run_result"] == {"success": True}
    assert result["consecutive_failures"] == 0
