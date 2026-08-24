"""Kompleks Kebakaran: pengelompokan titik hotspot yang berdekatan ruang & waktu
sekaligus (ST-DBSCAN) jadi satu "kompleks kebakaran" -- supaya jumlah yang
ditampilkan mencerminkan kejadian nyata, bukan jumlah titik satelit lepas.

Pasangan tetangga (siapa dekat siapa) dihitung di Postgres lewat self-join
ST_DWithin (lihat postgres_store/_hotspots.py::find_proximity_edges) supaya
tidak perlu dependency numpy/scipy/scikit-learn baru. Ekspansi klaster dari
daftar pasangan itu murni Python stdlib (collections.Counter + BFS), sama
persis logikanya dengan DBSCAN klasik -- cuma predikat "tetangga"-nya sudah
digabung ruang+waktu sejak dari SQL-nya.
"""

from collections import Counter, defaultdict
from datetime import datetime

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


NOISE = -1
_UNVISITED = -2


def _build_adjacency(point_ids: list[int], edges: list[tuple[int, int]]) -> dict[int, set[int]]:
    adjacency: dict[int, set[int]] = {pid: set() for pid in point_ids}
    for id_a, id_b in edges:
        adjacency[id_a].add(id_b)
        adjacency[id_b].add(id_a)
    return adjacency


def _graph_cluster(
    point_ids: list[int],
    edges: list[tuple[int, int]],
    min_samples: int,
) -> dict[int, int]:
    """DBSCAN klasik, cuma jalan di atas daftar pasangan tetangga (edge list)
    alih-alih index spasial in-memory. Titik dianggap "core point" kalau
    jumlah tetangganya (termasuk dirinya sendiri) >= min_samples, memicu
    ekspansi klaster lewat BFS -- persis algoritma yang sudah divalidasi di
    prototipe sesi ini, cuma sumber tetangganya sekarang dari SQL.

    Return: dict {point_id: cluster_id}, dengan cluster_id == NOISE (-1)
    untuk titik yang tidak masuk kompleks mana pun.
    """
    adjacency = _build_adjacency(point_ids, edges)
    labels: dict[int, int] = {pid: _UNVISITED for pid in point_ids}
    cluster_id = 0

    for pid in point_ids:
        if labels[pid] != _UNVISITED:
            continue

        neighbors = adjacency[pid]
        if len(neighbors) + 1 < min_samples:
            labels[pid] = NOISE
            continue

        labels[pid] = cluster_id
        seeds = list(neighbors)
        seed_index = 0
        while seed_index < len(seeds):
            neighbor_id = seeds[seed_index]
            seed_index += 1

            if labels[neighbor_id] == NOISE:
                labels[neighbor_id] = cluster_id
            if labels[neighbor_id] != _UNVISITED:
                continue

            labels[neighbor_id] = cluster_id
            neighbor_neighbors = adjacency[neighbor_id]
            if len(neighbor_neighbors) + 1 >= min_samples:
                seeds.extend(neighbor_neighbors)

        cluster_id += 1

    return labels


def _summarize(points: list[dict], labels: dict[int, int]) -> dict[str, object]:
    members_by_cluster: dict[int, list[dict]] = defaultdict(list)
    for point in points:
        cluster_id = labels[point["id"]]
        if cluster_id != NOISE:
            members_by_cluster[cluster_id].append(point)

    clusters = []
    for cluster_id, members in members_by_cluster.items():
        detected_ats = [m["detected_at"] for m in members]
        agencies = Counter(m["agency_name"] for m in members if m.get("agency_name"))
        dominant_agency = agencies.most_common(1)[0][0] if agencies else None

        clusters.append(
            {
                "cluster_id": cluster_id,
                "hotspot_count": len(members),
                "centroid_lat": sum(m["latitude"] for m in members) / len(members),
                "centroid_lon": sum(m["longitude"] for m in members) / len(members),
                "first_detected_at": min(detected_ats),
                "last_detected_at": max(detected_ats),
                "dominant_agency": dominant_agency,
            }
        )

    clusters.sort(key=lambda c: c["hotspot_count"], reverse=True)

    clustered_hotspots = sum(c["hotspot_count"] for c in clusters)
    total_hotspots = len(points)

    return {
        "count": len(clusters),
        "clusters": clusters,
        "stats": {
            "total_hotspots_in_range": total_hotspots,
            "clustered_hotspots": clustered_hotspots,
            "unclustered_hotspots": total_hotspots - clustered_hotspots,
        },
    }


class HotspotClusterService:
    def __init__(self) -> None:
        settings = get_settings()
        self.postgres_store = PostgresStore(settings.database_url)

    def compute_clusters(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
        eps_km: float,
        eps_hours: float,
        min_samples: int,
    ) -> dict[str, object]:
        points = self.postgres_store.get_hotspots_in_range(start_at, end_at)
        if not points:
            return {
                "count": 0,
                "clusters": [],
                "stats": {
                    "total_hotspots_in_range": 0,
                    "clustered_hotspots": 0,
                    "unclustered_hotspots": 0,
                },
            }

        edges = self.postgres_store.find_proximity_edges(
            start_at=start_at, end_at=end_at, eps_km=eps_km, eps_hours=eps_hours
        )
        point_ids = [p["id"] for p in points]
        labels = _graph_cluster(point_ids, edges, min_samples)
        return _summarize(points, labels)
