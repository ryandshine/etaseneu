"""Test murni (tanpa DB) untuk logika inti ST-DBSCAN Kompleks Kebakaran, plus
test level-API dengan HotspotClusterService.compute_clusters di-monkeypatch --
tidak pernah menyentuh PostgresStore/DB produksi sungguhan, mengikuti pola yang
sama seperti test_hotspots_endpoint_returns_map_view_payload di
test_hotspots_api.py (lihat CLAUDE.md bahaya #1)."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.hotspot_cluster_service import (
    NOISE,
    HotspotClusterService,
    _graph_cluster,
    _summarize,
)


def test_graph_cluster_forms_clique_into_one_cluster() -> None:
    # Klik {1,2,3,4} saling bertetangga (derajat 3 + diri sendiri = 4) --
    # semuanya core point dengan min_samples=4. Titik 6 cuma terhubung ke
    # titik 1 (border point, ikut klaster lewat ekspansi tapi bukan core).
    # Titik 5 tidak terhubung sama sekali -- noise.
    point_ids = [1, 2, 3, 4, 5, 6]
    edges = [(1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4), (1, 6)]

    labels = _graph_cluster(point_ids, edges, min_samples=4)

    assert labels[1] == labels[2] == labels[3] == labels[4] == labels[6]
    assert labels[1] != NOISE
    assert labels[5] == NOISE


def test_graph_cluster_all_isolated_points_are_noise() -> None:
    labels = _graph_cluster([1, 2, 3], edges=[], min_samples=4)

    assert labels == {1: NOISE, 2: NOISE, 3: NOISE}


def test_graph_cluster_respects_min_samples_threshold() -> None:
    # Pasangan {1,2} cuma berderajat 1 (+diri sendiri = 2) -- di bawah
    # min_samples=4, jadi TIDAK cukup untuk jadi core point meskipun saling
    # bertetangga.
    labels = _graph_cluster([1, 2], edges=[(1, 2)], min_samples=4)

    assert labels == {1: NOISE, 2: NOISE}


def _point(id_, lat, lon, detected_at, agency, wilker_bps=None, province_name=None):
    return {
        "id": id_,
        "latitude": lat,
        "longitude": lon,
        "detected_at": detected_at,
        "agency_name": agency,
        "wilker_bps": wilker_bps,
        "province_name": province_name,
    }


def test_summarize_computes_centroid_span_and_dominant_agency() -> None:
    t1 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 8, 2, tzinfo=timezone.utc)
    t3 = datetime(2026, 8, 3, tzinfo=timezone.utc)

    points = [
        _point(1, -1.0, 110.0, t1, "LPHD A", "Balai PS Banjarbaru", "Kalimantan Barat"),
        _point(2, -1.2, 110.2, t2, "LPHD A", "Balai PS Banjarbaru", "Kalimantan Barat"),
        _point(3, -1.1, 110.1, t3, "LPHD B", "Balai PS Ketapang", "Kalimantan Barat"),
        _point(4, -5.0, 120.0, t1, None),
    ]
    labels = {1: 0, 2: 0, 3: 0, 4: NOISE}

    result = _summarize(points, labels, core_point_ids={1, 2})

    assert result["count"] == 1
    cluster = result["clusters"][0]
    assert cluster["hotspot_count"] == 3
    assert cluster["centroid_lat"] == pytest.approx((-1.0 + -1.2 + -1.1) / 3)
    assert cluster["centroid_lon"] == pytest.approx((110.0 + 110.2 + 110.1) / 3)
    assert cluster["first_detected_at"] == t1
    assert cluster["last_detected_at"] == t3
    assert cluster["dominant_agency"] == "LPHD A"
    assert cluster["core_point_count"] == 2
    assert cluster["dominant_wilker"] == "Balai PS Banjarbaru"
    assert cluster["dominant_province"] == "Kalimantan Barat"
    assert cluster["affected_wilkers"] == [
        {"name": "Balai PS Banjarbaru", "hotspot_count": 2},
        {"name": "Balai PS Ketapang", "hotspot_count": 1},
    ]
    assert cluster["affected_provinces"] == [{"name": "Kalimantan Barat", "hotspot_count": 3}]
    assert cluster["affected_agencies"] == [
        {"name": "LPHD A", "hotspot_count": 2},
        {"name": "LPHD B", "hotspot_count": 1},
    ]
    assert [point["id"] for point in result["points"]] == [1, 2, 3]
    assert all(point["cluster_id"] == 0 for point in result["points"])
    assert [point["is_core"] for point in result["points"]] == [True, True, False]

    assert result["stats"] == {
        "total_hotspots_in_range": 4,
        "clustered_hotspots": 3,
        "unclustered_hotspots": 1,
    }


def test_summarize_computes_frp_weighted_centroid_and_epicenter() -> None:
    t = datetime(2026, 8, 1, tzinfo=timezone.utc)
    points = [
        {"id": 1, "latitude": -1.0, "longitude": 100.0, "frp": 10.0, "brightness": 320.0, "detected_at": t, "agency_name": "KPS A"},
        {"id": 2, "latitude": -2.0, "longitude": 102.0, "frp": 90.0, "brightness": 380.0, "detected_at": t, "agency_name": "KPS A"},
    ]
    labels = {1: 0, 2: 0}

    result = _summarize(points, labels)
    cluster = result["clusters"][0]

    # Weighted Lat: (-1.0*10 + -2.0*90) / 100 = -1.9
    # Weighted Lon: (100.0*10 + 102.0*90) / 100 = 101.8
    assert cluster["centroid_lat"] == pytest.approx(-1.9)
    assert cluster["centroid_lon"] == pytest.approx(101.8)
    assert cluster["epicenter_lat"] == pytest.approx(-2.0)
    assert cluster["epicenter_lon"] == pytest.approx(102.0)
    assert cluster["max_frp"] == pytest.approx(90.0)


def test_summarize_ranks_clusters_by_size_descending() -> None:
    t = datetime(2026, 8, 1, tzinfo=timezone.utc)
    points = [
        _point(1, 0.0, 0.0, t, "A"),
        _point(2, 0.0, 0.0, t, "A"),
        _point(3, 0.0, 0.0, t, "B"),
        _point(4, 0.0, 0.0, t, "B"),
        _point(5, 0.0, 0.0, t, "B"),
    ]
    labels = {1: 0, 2: 0, 3: 1, 4: 1, 5: 1}

    result = _summarize(points, labels)

    assert [c["hotspot_count"] for c in result["clusters"]] == [3, 2]
    assert [c["dominant_agency"] for c in result["clusters"]] == ["B", "A"]


def test_summarize_builds_union_epsilon_footprint_from_core_points() -> None:
    t = datetime(2026, 8, 1, tzinfo=timezone.utc)
    points = [
        _point(1, -1.0, 110.0, t, "A"),
        _point(2, -1.0, 110.01, t, "A"),
        _point(3, -1.0, 110.02, t, "A"),
    ]
    labels = {1: 0, 2: 0, 3: 0}

    result = _summarize(points, labels, core_point_ids={1, 2, 3}, eps_km=1)

    footprint = result["clusters"][0]["footprint"]
    assert footprint is not None
    assert footprint["type"] in {"Polygon", "MultiPolygon"}
    assert len(footprint["coordinates"]) > 0


def test_summarize_returns_empty_result_when_no_clusters() -> None:
    t = datetime(2026, 8, 1, tzinfo=timezone.utc)
    points = [_point(1, 0.0, 0.0, t, "A")]
    labels = {1: NOISE}

    result = _summarize(points, labels)

    assert result["count"] == 0
    assert result["clusters"] == []
    assert result["stats"]["unclustered_hotspots"] == 1


def test_hotspot_clusters_endpoint_returns_service_result(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    canned_result = {
        "count": 1,
        "clusters": [
            {
                "cluster_id": 0,
                "hotspot_count": 12,
                "centroid_lat": -1.5,
                "centroid_lon": 110.5,
                "first_detected_at": "2026-08-01T00:00:00Z",
                "last_detected_at": "2026-08-02T00:00:00Z",
                "dominant_agency": "LPHD Contoh",
            }
        ],
        "stats": {
            "total_hotspots_in_range": 20,
            "clustered_hotspots": 12,
            "unclustered_hotspots": 8,
        },
    }

    def fake_compute_clusters(self, **kwargs):
        return canned_result

    get_settings.cache_clear()
    monkeypatch.setattr(HotspotClusterService, "compute_clusters", fake_compute_clusters)

    try:
        client = TestClient(create_app())
        response = client.get("/api/hotspots/clusters?sensitivity=sedang")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        assert body["clusters"][0]["dominant_agency"] == "LPHD Contoh"
        assert body["stats"]["unclustered_hotspots"] == 8
        assert body["sensitivity"] == "sedang"
        assert "range_start" in body
        assert "range_end" in body
    finally:
        get_settings.cache_clear()


def test_hotspot_clusters_endpoint_falls_back_to_sedang_for_unknown_sensitivity(monkeypatch) -> None:
    from app.core.config import get_settings
    from app.main import create_app

    def fake_compute_clusters(self, **kwargs):
        assert kwargs["eps_km"] == 2.0
        assert kwargs["eps_hours"] == 48.0
        assert kwargs["min_samples"] == 4
        return {"count": 0, "clusters": [], "stats": {
            "total_hotspots_in_range": 0, "clustered_hotspots": 0, "unclustered_hotspots": 0,
        }}

    get_settings.cache_clear()
    monkeypatch.setattr(HotspotClusterService, "compute_clusters", fake_compute_clusters)

    try:
        client = TestClient(create_app())
        response = client.get("/api/hotspots/clusters?sensitivity=tidak-dikenal")

        assert response.status_code == 200
        assert response.json()["sensitivity"] == "sedang"
    finally:
        get_settings.cache_clear()
