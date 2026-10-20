"""Tes integrasi mesin pencocokan hotspot <-> poligon terhadap PostGIS SUNGGUHAN.

Tes ini MENULIS ke database, jadi dipagari ketat (lihat bahaya #1 di CLAUDE.md):

- hanya jalan bila ``ETASENEU_TEST_DATABASE_URL`` diisi (jika tidak: skip, bukan gagal);
- nama database WAJIB mengandung ``test``;
- URL tidak boleh sama (host:port/nama db) dengan ``DATABASE_URL`` di ``backend/.env`` / lingkungan;
- seluruh tabel dibuat di SKEMA SEMENTARA per modul (``search_path``) lalu di-drop di akhir,
  sehingga tidak menyentuh tabel ``public`` milik database uji itu sendiri.

Menjalankan: jalankan kontainer ``postgis/postgis:16-3.4`` terpisah, lalu
``ETASENEU_TEST_DATABASE_URL=postgresql://postgres:...@127.0.0.1:PORT/es_test pytest app/tests/test_hotspot_matching_integration.py``

Oracle: ``shapely`` (implementasi independen dari SQL) + nilai yang dihitung tangan -- hasil kode
yang sama tidak dipakai sebagai satu-satunya pembanding.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import pytest

TEST_URL = os.environ.get("ETASENEU_TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_URL, reason="ETASENEU_TEST_DATABASE_URL tidak diisi (tes integrasi PostGIS dilewati)"
)

psycopg = pytest.importorskip("psycopg")
shapely_geometry = pytest.importorskip("shapely.geometry")
shapely_validation = pytest.importorskip("shapely.validation")

UTC = timezone.utc
INIT_SQL = Path(__file__).resolve().parents[2] / "sql" / "init_etaseneu.sql"

# Persegi 1x1 derajat di sekitar (100, 0): tepi kiri bawah (100,0), kanan atas (101,1).
SQUARE_A = "MULTIPOLYGON(((100 0,101 0,101 1,100 1,100 0)))"
# Persegi yang menumpang tindih A di x 100.5..101.5
SQUARE_B = "MULTIPOLYGON(((100.5 0,101.5 0,101.5 1,100.5 1,100.5 0)))"
# Persegi terpisah jauh
SQUARE_C = "MULTIPOLYGON(((110 0,111 0,111 1,110 1,110 0)))"
# "Dasi kupu-kupu": self-intersection di (121,1) -> ST_IsValid = false. Cuping KIRI (segitiga
# (120,0)-(121,1)-(120,2)) dan cuping KANAN (segitiga (122,0)-(121,1)-(122,2)).
BOWTIE = "MULTIPOLYGON(((120 0,122 2,122 0,120 2,120 0)))"


def _guard_not_production(url: str) -> None:
    parsed = urlparse(url)
    name = (parsed.path or "").lstrip("/")
    assert "test" in name.lower(), f"nama database uji harus mengandung 'test', dapat: {name!r}"
    try:
        from dotenv import dotenv_values

        env_path = Path(__file__).resolve().parents[2] / ".env"
        prod_urls = [os.environ.get("DATABASE_URL", ""), dotenv_values(env_path).get("DATABASE_URL") or ""]
    except Exception:  # pragma: no cover - python-dotenv selalu ada di requirements
        prod_urls = [os.environ.get("DATABASE_URL", "")]
    for prod in prod_urls:
        if not prod:
            continue
        p = urlparse(prod)
        assert (p.hostname, p.port, p.path) != (parsed.hostname, parsed.port, parsed.path), (
            "ETASENEU_TEST_DATABASE_URL menunjuk database yang SAMA dengan DATABASE_URL -- ditolak"
        )


def _url_with_schema(url: str, schema: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query["options"] = f"-csearch_path={schema},public"
    return urlunparse(parsed._replace(query=urlencode(query, quote_via=quote)))


@pytest.fixture(scope="module")
def store():
    from app.services.postgres_store import PostgresStore

    _guard_not_production(TEST_URL)
    schema = f"t_hotspot_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(TEST_URL, autocommit=True, connect_timeout=5) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    scoped_url = _url_with_schema(TEST_URL, schema)
    with psycopg.connect(scoped_url, autocommit=True, connect_timeout=5) as conn:
        conn.execute(INIT_SQL.read_text(encoding="utf-8"))
        # Tabel atribusi kawasan hutan dibuat manual di produksi (di luar init_etaseneu.sql);
        # versi minimal cukup untuk query baca peta yang melakukan LEFT JOIN ke keduanya.
        conn.execute(
            """
            CREATE TABLE hotspot_kawasan_hutan (
                hotspot_id BIGINT PRIMARY KEY, fungsikws NUMERIC, nama_kawasan TEXT, kelompok TEXT
            );
            CREATE TABLE ref_fungsi_kawasan_label (
                kode NUMERIC PRIMARY KEY, singkatan TEXT, fungsi TEXT, kelompok TEXT
            );
            """
        )
    pg_store = PostgresStore(scoped_url)
    assert pg_store.enabled, "PostgresStore tidak bisa terhubung ke database uji"
    yield pg_store
    with psycopg.connect(TEST_URL, autocommit=True, connect_timeout=5) as admin:
        admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


@pytest.fixture(autouse=True)
def clean_tables(store):
    with store.connection() as conn:
        conn.execute(
            "TRUNCATE polygon_hotspot_summary, hotspot_polygon_relation, hotspot_observations, "
            "polygon_metadata RESTART IDENTITY CASCADE"
        )
    yield


# --------------------------------------------------------------------------- helpers


def add_polygon(store, wkt: str, *, layer_key: str = "psagustus2026", active: bool = True, name: str = "KTH") -> int:
    key = uuid.uuid4().hex
    with store.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO polygon_metadata (
                layer_key, feature_key, feature_index, lembaga, nama_prov, nama_kab, nama_kec,
                nama_desa, skema, is_active, geometry, luas_sk, luas_final, properties_raw,
                source_file, file_checksum
            ) VALUES (%s, %s, 0, %s, 'Riau', 'x', 'x', 'x', 'PPHKm', %s,
                      ST_SetSRID(ST_GeomFromText(%s), 4326), '1', '1', '{}'::jsonb, 'f', 'c')
            RETURNING id
            """,
            (layer_key, key, name, active, wkt),
        ).fetchone()
    return int(row["id"])


def hotspot(lon: float, lat: float, when: str, *, layer: str = "psagustus2026", source: str = "VIIRS S-NPP", satellite: str = "N") -> dict:
    return {
        "source": source,
        "satellite": satellite,
        "latitude": lat,
        "longitude": lon,
        "brightness": 330.0,
        "confidence": "n",
        "detected_at": when,
        "layer_id": layer,
        "layer_name": layer,
        "agency_name": layer,
    }


def sync_all(store) -> dict:
    """Relasi + ringkasan untuk seluruh rentang uji (2026-2027)."""
    return store.sync_hotspot_relations_and_summaries(
        start_at=datetime(2026, 1, 1, tzinfo=UTC), end_at=datetime(2028, 1, 1, tzinfo=UTC)
    )


def relation_pairs(store) -> set[tuple[int, int]]:
    with store.connection() as conn:
        rows = conn.execute("SELECT hotspot_observation_id, polygon_metadata_id FROM hotspot_polygon_relation").fetchall()
    return {(int(r["hotspot_observation_id"]), int(r["polygon_metadata_id"])) for r in rows}


def observation_ids(store) -> dict[tuple[float, float], int]:
    with store.connection() as conn:
        rows = conn.execute("SELECT id, longitude, latitude FROM hotspot_observations ORDER BY id").fetchall()
    return {(float(r["longitude"]), float(r["latitude"])): int(r["id"]) for r in rows}


def summary_rows(store) -> dict[tuple[int, int], dict]:
    with store.connection() as conn:
        rows = conn.execute("SELECT * FROM polygon_hotspot_summary").fetchall()
    return {(int(r["polygon_metadata_id"]), int(r["year"])): r for r in rows}


def oracle_pairs(store, polygons: dict[int, str]) -> set[tuple[int, int]]:
    """Pembanding independen: shapely.covers atas geometri yang diperbaiki (make_valid)."""
    from shapely import wkt as shapely_wkt

    shapes = {}
    for pid, wkt in polygons.items():
        geom = shapely_wkt.loads(wkt)
        if not geom.is_valid:
            geom = shapely_validation.make_valid(geom)
        shapes[pid] = geom
    pairs = set()
    for (lon, lat), oid in observation_ids(store).items():
        point = shapely_geometry.Point(lon, lat)
        for pid, geom in shapes.items():
            if geom.covers(point):
                pairs.add((oid, pid))
    return pairs


# --------------------------------------------------------------------------- 1-3: posisi titik


def test_point_inside_polygon_gets_relation_and_summary(store):
    pid = add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations([hotspot(100.5, 0.5, "2026-10-10T06:00:00Z")])
    result = sync_all(store)
    oid = observation_ids(store)[(100.5, 0.5)]
    assert relation_pairs(store) == {(oid, pid)}
    assert result["inserted"] == 1
    assert summary_rows(store)[(pid, 2026)]["hotspot_count"] == 1


def test_point_exactly_on_boundary_and_vertex_is_covered(store):
    pid = add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations(
        [
            hotspot(100.0, 0.5, "2026-10-10T06:00:00Z"),  # tepat di tepi kiri
            hotspot(101.0, 1.0, "2026-10-10T07:00:00Z"),  # tepat di sudut
        ]
    )
    sync_all(store)
    ids = observation_ids(store)
    assert relation_pairs(store) == {(ids[(100.0, 0.5)], pid), (ids[(101.0, 1.0)], pid)}


def test_point_outside_polygon_has_no_relation_or_summary(store):
    add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations([hotspot(105.0, 5.0, "2026-10-10T06:00:00Z")])
    result = sync_all(store)
    assert relation_pairs(store) == set()
    assert summary_rows(store) == {}
    assert result["spatial_pairs"] == 0


# --------------------------------------------------------------------------- 4: geometri tidak valid


def test_invalid_polygon_is_matched_without_modifying_source_geometry(store):
    pid = add_polygon(store, BOWTIE)
    with store.connection() as conn:
        assert conn.execute("SELECT ST_IsValid(geometry) AS ok FROM polygon_metadata WHERE id=%s", (pid,)).fetchone()["ok"] is False
    store.upsert_hotspot_observations(
        [
            hotspot(120.2, 1.0, "2026-10-10T06:00:00Z"),  # di dalam cuping kiri
            hotspot(121.8, 1.0, "2026-10-10T06:30:00Z"),  # di dalam cuping kanan
            hotspot(121.0, 1.0, "2026-10-10T07:00:00Z"),  # titik simpul perpotongan
            hotspot(121.0, 1.8, "2026-10-10T07:30:00Z"),  # di antara cuping, di atas simpul: LUAR
            hotspot(121.0, 0.2, "2026-10-10T08:00:00Z"),  # di antara cuping, di bawah simpul: LUAR
        ]
    )
    sync_all(store)
    pairs = relation_pairs(store)
    ids = observation_ids(store)
    assert (ids[(121.0, 1.8)], pid) not in pairs and (ids[(121.0, 0.2)], pid) not in pairs
    assert pairs == oracle_pairs(store, {pid: BOWTIE})
    assert {(ids[(120.2, 1.0)], pid), (ids[(121.8, 1.0)], pid), (ids[(121.0, 1.0)], pid)} == pairs
    with store.connection() as conn:  # geometri sumber tidak pernah diubah
        row = conn.execute("SELECT ST_IsValid(geometry) AS ok, ST_AsText(geometry) AS wkt FROM polygon_metadata WHERE id=%s", (pid,)).fetchone()
    assert row["ok"] is False
    assert "120 0,122 2,122 0,120 2,120 0" in row["wkt"]


# --------------------------------------------------------------------------- 5 & 14: tumpang tindih


def test_point_in_two_overlapping_polygons_counts_in_both_but_once_regionally(store):
    a = add_polygon(store, SQUARE_A, name="A")
    b = add_polygon(store, SQUARE_B, name="B")
    store.upsert_hotspot_observations(
        [
            hotspot(100.75, 0.5, "2026-10-10T06:00:00Z"),  # di irisan A dan B
            hotspot(100.2, 0.5, "2026-10-10T06:10:00Z"),  # hanya A
            hotspot(101.3, 0.5, "2026-10-10T06:20:00Z"),  # hanya B
        ]
    )
    sync_all(store)
    ids = observation_ids(store)
    pairs = relation_pairs(store)
    overlap = ids[(100.75, 0.5)]
    assert {(overlap, a), (overlap, b)} <= pairs
    assert pairs == oracle_pairs(store, {a: SQUARE_A, b: SQUARE_B})

    per_polygon = {pid: row["hotspot_count"] for (pid, _), row in summary_rows(store).items()}
    assert per_polygon == {a: 2, b: 2}
    assert sum(per_polygon.values()) == 4  # jumlah per-poligon menghitung titik irisan dua kali
    assert len({oid for oid, _ in pairs}) == 3  # titik unik regional (jangan dijumlahkan per poligon)


# --------------------------------------------------------------------------- 6: layer_key observasi


def test_observation_layer_label_is_not_a_spatial_condition(store):
    pid = add_polygon(store, SQUARE_A, layer_key="psagustus2026")
    store.upsert_hotspot_observations(
        [
            hotspot(100.5, 0.5, "2026-10-10T06:00:00Z", layer="perimeter_threat"),  # label usang, tapi di dalam
            hotspot(100.6, 0.5, "2026-10-10T06:10:00Z", layer="PS_FEB_26"),  # label layer lama
            hotspot(105.0, 5.0, "2026-10-10T06:20:00Z", layer="psagustus2026"),  # label cocok, tapi di luar
        ]
    )
    sync_all(store)
    ids = observation_ids(store)
    assert relation_pairs(store) == {(ids[(100.5, 0.5)], pid), (ids[(100.6, 0.5)], pid)}
    assert summary_rows(store)[(pid, 2026)]["hotspot_count"] == 2


# --------------------------------------------------------------------------- 7: tanpa geometri


def test_observation_without_geometry_is_ignored(store):
    add_polygon(store, SQUARE_A)
    with store.connection() as conn:
        conn.execute(
            """
            INSERT INTO hotspot_observations (source, satellite, latitude, longitude, detected_at, layer_key, geom)
            VALUES ('VIIRS S-NPP', 'N', 0.5, 100.5, '2026-10-10T06:00:00Z', 'psagustus2026', NULL)
            """
        )
    result = sync_all(store)
    assert result["spatial_pairs"] == 0
    assert relation_pairs(store) == set()


# --------------------------------------------------------------------------- 8, 9: idempotensi


def test_repeated_observation_upsert_and_reconcile_are_idempotent(store):
    pid = add_polygon(store, SQUARE_A)
    batch = [hotspot(100.5, 0.5, "2026-10-10T06:00:00Z"), hotspot(100.6, 0.6, "2026-10-10T06:05:00Z")]
    store.upsert_hotspot_observations(batch)
    first = sync_all(store)
    ids_before = observation_ids(store)
    pairs_before = relation_pairs(store)

    store.upsert_hotspot_observations(batch)  # ingest ulang (scheduler menarik jendela 3 hari yang sama)
    second = sync_all(store)

    assert observation_ids(store) == ids_before  # tidak ada baris observasi baru / id berubah
    assert relation_pairs(store) == pairs_before
    assert first["inserted"] == 2 and second["inserted"] == 0 and second["updated"] == 0
    assert summary_rows(store)[(pid, 2026)]["hotspot_count"] == 2


def test_dry_run_reports_missing_pairs_without_writing(store):
    add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations([hotspot(100.5, 0.5, "2026-10-10T06:00:00Z")])
    window = dict(start_at=datetime(2026, 1, 1, tzinfo=UTC), end_at=datetime(2028, 1, 1, tzinfo=UTC))
    dry = store.reconcile_hotspot_polygon_relations(dry_run=True, **window)
    assert dry["missing_pairs"] == 1 and dry["inserted"] == 0
    assert relation_pairs(store) == set()
    real = store.reconcile_hotspot_polygon_relations(**window)
    assert real["inserted"] == 1 and len(relation_pairs(store)) == 1


def test_inactive_polygon_is_never_matched(store):
    add_polygon(store, SQUARE_A, active=False)
    store.upsert_hotspot_observations([hotspot(100.5, 0.5, "2026-10-10T06:00:00Z")])
    sync_all(store)
    assert relation_pairs(store) == set()
    assert summary_rows(store) == {}


# --------------------------------------------------------------------------- 10: kegagalan sebagian + retry


def test_partial_failure_keeps_finished_chunks_skips_summary_and_retry_converges(store, monkeypatch):
    from app.services.postgres_store._hotspot_match import HotspotRelationSyncError

    pid = add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations(
        [
            hotspot(100.5, 0.5, "2026-01-10T06:00:00Z"),  # chunk pertama (31 hari pertama)
            hotspot(100.6, 0.5, "2026-03-10T06:00:00Z"),  # chunk berikutnya
        ]
    )
    original = type(store)._reconcile_chunk
    calls = {"n": 0}

    def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("koneksi putus (simulasi)")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(store), "_reconcile_chunk", flaky)
    with pytest.raises(HotspotRelationSyncError) as excinfo:
        store.sync_hotspot_relations_and_summaries(
            start_at=datetime(2026, 1, 1, tzinfo=UTC), end_at=datetime(2026, 5, 1, tzinfo=UTC)
        )
    assert excinfo.value.progress["chunks"] == 1  # chunk pertama sudah selesai
    assert len(relation_pairs(store)) == 1  # ... dan tersimpan
    assert summary_rows(store) == {}  # ringkasan TIDAK diperbarui karena relasi gagal

    monkeypatch.setattr(type(store), "_reconcile_chunk", original)
    store.sync_hotspot_relations_and_summaries(
        start_at=datetime(2026, 1, 1, tzinfo=UTC), end_at=datetime(2026, 5, 1, tzinfo=UTC)
    )
    assert relation_pairs(store) == oracle_pairs(store, {pid: SQUARE_A})
    assert summary_rows(store)[(pid, 2026)]["hotspot_count"] == 2


# --------------------------------------------------------------------------- 11: penuh vs inkremental


def test_incremental_summary_equals_full_refresh(store):
    a = add_polygon(store, SQUARE_A, name="A")
    c = add_polygon(store, SQUARE_C, name="C")
    store.upsert_hotspot_observations(
        [hotspot(100.5, 0.5, "2026-09-01T06:00:00Z"), hotspot(110.5, 0.5, "2026-09-02T06:00:00Z")]
    )
    sync_all(store)
    # titik baru tiba belakangan; hanya jendela barunya yang direkonsiliasi
    store.upsert_hotspot_observations(
        [hotspot(100.7, 0.4, "2026-10-05T06:00:00Z", satellite="N20", source="VIIRS NOAA-20")]
    )
    store.sync_hotspot_relations_and_summaries(
        start_at=datetime(2026, 10, 5, tzinfo=UTC), end_at=datetime(2026, 10, 6, tzinfo=UTC)
    )
    incremental = {k: (v["hotspot_count"], v["sources"], v["satellites"], v["start_at"], v["end_at"]) for k, v in summary_rows(store).items()}
    relations_incremental = relation_pairs(store)

    store.refresh_polygon_hotspot_summaries()  # penuh
    full = {k: (v["hotspot_count"], v["sources"], v["satellites"], v["start_at"], v["end_at"]) for k, v in summary_rows(store).items()}

    assert incremental == full
    assert relation_pairs(store) == relations_incremental
    assert full[(a, 2026)][0] == 2 and full[(c, 2026)][0] == 1


def test_summary_semantics_distinct_sorted_lists_and_same_set_aggregates(store):
    pid = add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations(
        [
            hotspot(100.5, 0.5, "2026-10-10T06:00:00Z", source="VIIRS S-NPP", satellite="N"),
            hotspot(100.6, 0.5, "2026-10-11T09:00:00Z", source="MODIS", satellite="Aqua"),
            hotspot(100.7, 0.5, "2026-10-12T03:00:00Z", source="MODIS", satellite="Terra"),
        ]
    )
    sync_all(store)
    row = summary_rows(store)[(pid, 2026)]
    assert row["hotspot_count"] == 3
    assert row["sources"] == ["MODIS", "VIIRS S-NPP"]  # DAFTAR berbeda terurut, bukan jumlah per sumber
    assert row["satellites"] == ["Aqua", "N", "Terra"]
    assert row["start_at"] == datetime(2026, 10, 10, 6, 0, tzinfo=UTC)
    assert row["end_at"] == row["last_hotspot_at"] == datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- 12: observasi dihapus / yatim


def test_deleted_observation_leaves_reported_orphan_and_summary_excludes_it(store):
    pid = add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations(
        [hotspot(100.5, 0.5, "2026-10-10T06:00:00Z"), hotspot(100.6, 0.5, "2026-10-10T07:00:00Z")]
    )
    sync_all(store)
    ids = observation_ids(store)
    with store.connection() as conn:  # observasi terhapus di luar aplikasi; relasi tidak punya FK ke observasi
        conn.execute("DELETE FROM hotspot_observations WHERE id=%s", (ids[(100.5, 0.5)],))

    report = store.hotspot_relation_integrity_report()
    assert report["orphan_hotspot_rows"] == 1 and report["orphan_hotspot_ids"] == 1
    assert report["valid_rows"] == 1 and report["missing_pairs"] == 0 and report["stale_pairs"] == 0

    store.rebuild_polygon_hotspot_summary([pid])
    assert summary_rows(store)[(pid, 2026)]["hotspot_count"] == 1  # ringkasan tidak memuat observasi yang sudah hilang

    dry = store.prune_orphan_relations()  # bawaan dry_run=True
    assert dry == {"orphan_rows": 1, "orphan_ids": 1, "deleted": 0}
    assert len(relation_pairs(store)) == 2
    done = store.prune_orphan_relations(dry_run=False)
    assert done["deleted"] == 1 and len(relation_pairs(store)) == 1


def test_integrity_report_detects_missing_and_stale_pairs(store):
    pid = add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations([hotspot(100.5, 0.5, "2026-10-10T06:00:00Z"), hotspot(105.0, 5.0, "2026-10-10T07:00:00Z")])
    ids = observation_ids(store)
    with store.connection() as conn:  # relasi palsu: titik di luar poligon, dan tidak ada relasi untuk titik di dalam
        conn.execute(
            "INSERT INTO hotspot_polygon_relation (hotspot_observation_id, polygon_metadata_id, layer_key, match_method) "
            "VALUES (%s, %s, 'psagustus2026', 'contains')",
            (ids[(105.0, 5.0)], pid),
        )
    report = store.hotspot_relation_integrity_report()
    assert report["missing_pairs"] == 1
    assert report["stale_pairs"] == 1


# --------------------------------------------------------------------------- 13: tahun dan WIB


def test_year_boundary_uses_asia_jakarta(store):
    pid = add_polygon(store, SQUARE_A)
    store.upsert_hotspot_observations(
        [
            hotspot(100.5, 0.5, "2026-12-31T16:59:00Z"),  # 23:59 WIB, 31 Des 2026 -> tahun 2026
            hotspot(100.6, 0.5, "2026-12-31T17:00:00Z"),  # 00:00 WIB, 1 Jan 2027 -> tahun 2027
            hotspot(100.7, 0.5, "2027-01-01T05:00:00Z"),  # 2027
        ]
    )
    sync_all(store)
    rows = summary_rows(store)
    assert rows[(pid, 2026)]["hotspot_count"] == 1
    assert rows[(pid, 2027)]["hotspot_count"] == 2


# --------------------------------------------------------------------------- regresi bug cache satu-indeks


def test_persist_creates_relations_for_every_polygon_not_only_the_first_hotspots(store):
    """Regresi akar masalah produksi: relasi hanya dibuat untuk hotspot yang satu poligon dengan
    hotspot pertama di layernya. Di sini hotspot tersebar di tiga poligon berbeda dan tidak ada
    metadata poligon pada dict hotspot -- semuanya harus punya relasi."""
    from app.services.hotspot_service import HotspotService

    a = add_polygon(store, SQUARE_A, name="A")
    c = add_polygon(store, SQUARE_C, name="C")
    d = add_polygon(store, "MULTIPOLYGON(((130 0,131 0,131 1,130 1,130 0)))", name="D")
    batch = []
    for i in range(5):
        batch.append(hotspot(100.1 + i * 0.1, 0.5, f"2026-10-10T0{i}:00:00Z"))
        batch.append(hotspot(110.1 + i * 0.1, 0.5, f"2026-10-10T0{i}:10:00Z"))
        batch.append(hotspot(130.1 + i * 0.1, 0.5, f"2026-10-10T0{i}:20:00Z"))
    service = HotspotService.__new__(HotspotService)
    service.postgres_store = store

    outcome = service._persist_observations_and_relations(batch)

    assert outcome["ok"] is True
    pairs = relation_pairs(store)
    assert len(pairs) == 15
    assert {pid for _, pid in pairs} == {a, c, d}
    assert pairs == oracle_pairs(store, {a: SQUARE_A, c: SQUARE_C, d: "MULTIPOLYGON(((130 0,131 0,131 1,130 1,130 0)))"})
    assert {k: v["hotspot_count"] for (k, _), v in summary_rows(store).items()} == {a: 5, c: 5, d: 5}


def test_persist_reports_failure_instead_of_swallowing(store, monkeypatch):
    from app.services.hotspot_service import HotspotService

    add_polygon(store, SQUARE_A)
    service = HotspotService.__new__(HotspotService)
    service.postgres_store = store

    def boom(**_kwargs):
        raise RuntimeError("database sedang down (simulasi)")

    monkeypatch.setattr(store, "sync_hotspot_relations_and_summaries", boom)
    outcome = service._persist_observations_and_relations([hotspot(100.5, 0.5, "2026-10-10T06:00:00Z")])
    assert outcome == {"ok": False}


# --------------------------------------------------------------------------- jalur baca peta


def test_map_read_uses_polygon_layer_and_relabels_stale_perimeter_points(store):
    add_polygon(store, SQUARE_A, layer_key="psagustus2026", name="KTH Peta")
    store.upsert_hotspot_observations(
        [
            hotspot(100.5, 0.5, "2026-10-10T06:00:00Z", layer="perimeter_threat"),
            hotspot(100.6, 0.5, "2026-10-10T07:00:00Z", layer="psagustus2026"),
            hotspot(105.0, 5.0, "2026-10-10T08:00:00Z", layer="psagustus2026"),
        ]
    )
    payloads = store.read_hotspot_observations(
        start_date="2026-10-10T00:00:00+00:00",
        end_date="2026-10-11T00:00:00+00:00",
        sources=["VIIRS S-NPP"],
        layer_ids=["psagustus2026"],
    )
    assert len(payloads) == 2  # titik di luar poligon tidak ikut, satu baris per observasi
    assert {p["layer_id"] for p in payloads} == {"psagustus2026"}  # label usang diselaraskan dengan poligon
    assert all(p["polygon_metadata"]["LEMBAGA"] == "KTH Peta" for p in payloads)
    in_range = store.get_hotspots_in_range(
        datetime(2026, 10, 10, tzinfo=UTC), datetime(2026, 10, 11, tzinfo=UTC)
    )
    assert len(in_range) == 2


def test_map_read_returns_one_row_per_observation_even_when_polygons_overlap(store):
    add_polygon(store, SQUARE_A, name="A")
    add_polygon(store, SQUARE_B, name="B")
    store.upsert_hotspot_observations([hotspot(100.75, 0.5, "2026-10-10T06:00:00Z")])
    payloads = store.read_hotspot_observations(
        start_date="2026-10-10T00:00:00+00:00",
        end_date="2026-10-11T00:00:00+00:00",
        sources=["VIIRS S-NPP"],
        layer_ids=["psagustus2026"],
    )
    assert len(payloads) == 1
    assert len(store.get_hotspots_in_range(datetime(2026, 10, 10, tzinfo=UTC), datetime(2026, 10, 11, tzinfo=UTC))) == 1


def test_naive_datetime_is_rejected(store):
    with pytest.raises(ValueError):
        store.reconcile_hotspot_polygon_relations(start_at=datetime(2026, 1, 1), end_at=datetime(2026, 2, 1, tzinfo=UTC))
