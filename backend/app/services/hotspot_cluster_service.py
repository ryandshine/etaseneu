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
from math import asin, cos, floor, radians, sin, sqrt

from shapely.geometry import Point, mapping
from shapely.ops import unary_union

from app.core.config import get_settings
from app.services.postgres_store import PostgresStore


NOISE = -1
_UNVISITED = -2
_EARTH_RADIUS_KM = 6371.0088


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


def _core_point_ids(
    point_ids: list[int],
    edges: list[tuple[int, int]],
    min_samples: int,
) -> set[int]:
    adjacency = _build_adjacency(point_ids, edges)
    return {
        point_id
        for point_id, neighbors in adjacency.items()
        if len(neighbors) + 1 >= min_samples
    }


def _haversine_km(point_a: dict, point_b: dict) -> float:
    lat_a = radians(float(point_a["latitude"]))
    lat_b = radians(float(point_b["latitude"]))
    delta_lat = lat_b - lat_a
    delta_lon = radians(float(point_b["longitude"]) - float(point_a["longitude"]))
    haversine = sin(delta_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(delta_lon / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(haversine))


def _spatial_edges(points: list[dict], eps_km: float) -> list[tuple[int, int]]:
    """Buat edge spasial tanpa mempertimbangkan waktu.

    Grid derajat hanya dipakai sebagai bucket kandidat; keputusan akhirnya
    tetap memakai haversine dalam kilometer. Ini menjaga sub-clustering tetap
    ringan walaupun satu kompleks berisi banyak deteksi.
    """
    if len(points) < 2:
        return []

    cell_size = eps_km / 111.32
    buckets: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for point in points:
        cell = (
            floor(float(point["latitude"]) / cell_size),
            floor(float(point["longitude"]) / cell_size),
        )
        buckets[cell].append(point)

    edges: list[tuple[int, int]] = []
    for point in points:
        point_cell = (
            floor(float(point["latitude"]) / cell_size),
            floor(float(point["longitude"]) / cell_size),
        )
        for lat_offset in (-1, 0, 1):
            for lon_offset in (-1, 0, 1):
                for candidate in buckets.get(
                    (point_cell[0] + lat_offset, point_cell[1] + lon_offset), []
                ):
                    if candidate["id"] <= point["id"]:
                        continue
                    if _haversine_km(point, candidate) <= eps_km:
                        edges.append((point["id"], candidate["id"]))
    return edges


def _spatial_location_groups(members: list[dict], eps_km: float) -> list[list[dict]]:
    """Pisahkan satu kompleks menjadi kantong lokasi yang lebih rapat.

    min_samples=1 sengaja dipakai pada tingkat ini: seluruh anggota kompleks
    tetap diberi lokasi terindikasi, termasuk bagian yang hanya berisi border
    point. Kepadatan dan hubungan ruang-waktu sudah disaring oleh tingkat
    ST-DBSCAN sebelumnya.
    """
    point_ids = [member["id"] for member in members]
    labels = _graph_cluster(point_ids, _spatial_edges(members, eps_km), min_samples=1)
    groups: dict[int, list[dict]] = defaultdict(list)
    for member in members:
        groups[labels[member["id"]]].append(member)
    return sorted(
        groups.values(),
        key=lambda group: (
            -len(group),
            sum(member["latitude"] for member in group) / len(group),
            sum(member["longitude"] for member in group) / len(group),
        ),
    )


def _location_summary(members: list[dict], location_id: int) -> dict[str, object]:
    detected_ats = [member["detected_at"] for member in members]
    polygon_members = [member for member in members if member.get("polygon_metadata_id") is not None]

    total_w = sum(max(float(m.get("frp") or 0.0), 1.0) for m in members)
    w_lat = sum(float(m["latitude"]) * max(float(m.get("frp") or 0.0), 1.0) for m in members)
    w_lon = sum(float(m["longitude"]) * max(float(m.get("frp") or 0.0), 1.0) for m in members)

    return {
        "location_id": location_id,
        "hotspot_count": len(members),
        "centroid_lat": w_lat / total_w if total_w > 0 else sum(member["latitude"] for member in members) / len(members),
        "centroid_lon": w_lon / total_w if total_w > 0 else sum(member["longitude"] for member in members) / len(members),
        "first_detected_at": min(detected_ats),
        "last_detected_at": max(detected_ats),
        "polygon_hotspot_count": len(polygon_members),
        "outside_polygon_hotspot_count": len(members) - len(polygon_members),
    }


def _cluster_footprint(
    members: list[dict],
    core_point_ids: set[int],
    eps_km: float,
) -> dict | None:
    """Union semua buffer epsilon pada core point sebuah cluster.

    Koordinat cluster saat ini memakai geometry EPSG:4326 dan predikat SQL
    yang sama-sama mengkonversi epsilon kilometer ke derajat. Footprint ini
    sengaja memakai konversi yang sama agar bentuk visual audit konsisten
    dengan tetangga yang dipakai ST-DBSCAN.
    """
    core_members = [member for member in members if member["id"] in core_point_ids]
    if not core_members:
        return None

    eps_degrees = eps_km / 111.32
    geometry = unary_union([
        Point(member["longitude"], member["latitude"]).buffer(eps_degrees)
        for member in core_members
    ])
    return mapping(geometry)


def _ranked_metadata(members: list[dict], key: str) -> list[dict[str, object]]:
    values = Counter(
        str(member[key]).strip()
        for member in members
        if member.get(key) not in (None, "") and str(member[key]).strip()
    )
    return [{"name": name, "hotspot_count": count} for name, count in values.most_common()]


def _summarize(
    points: list[dict],
    labels: dict[int, int],
    core_point_ids: set[int] | None = None,
    eps_km: float | None = None,
    location_eps_km: float | None = None,
) -> dict[str, object]:
    core_point_ids = core_point_ids or set()
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
        wilkers = _ranked_metadata(members, "wilker_bps")
        provinces = _ranked_metadata(members, "province_name")
        location_groups = (
            _spatial_location_groups(members, location_eps_km)
            if location_eps_km is not None
            else []
        )
        locations = [
            _location_summary(location_members, index + 1)
            for index, location_members in enumerate(location_groups)
        ]
        polygon_groups: dict[int, list[dict]] = defaultdict(list)
        for member in members:
            polygon_id = member.get("polygon_metadata_id")
            if polygon_id is not None:
                polygon_groups[int(polygon_id)].append(member)

        polygon_summaries = []
        for polygon_id, polygon_members in polygon_groups.items():
            polygon_location_count = sum(
                1
                for location_members in location_groups
                if any(member["id"] in {item["id"] for item in polygon_members} for member in location_members)
            )
            polygon_summaries.append(
                {
                    "polygon_metadata_id": polygon_id,
                    "name": polygon_members[0].get("polygon_agency_name"),
                    "wilker_bps": polygon_members[0].get("wilker_bps"),
                    "province_name": polygon_members[0].get("province_name"),
                    "hotspot_count": len(polygon_members),
                    "location_count": polygon_location_count,
                }
            )
        polygon_summaries.sort(key=lambda polygon: polygon["hotspot_count"], reverse=True)
        dominant_polygon = polygon_summaries[0] if polygon_summaries else None
        polygon_hotspot_count = sum(len(polygon_members) for polygon_members in polygon_groups.values())

        # Hitung FRP-Weighted Centroid & Titik Episentrum Api Terparah (Peak Hotspot)
        total_weight = 0.0
        weighted_lat = 0.0
        weighted_lon = 0.0
        max_frp = 0.0
        peak_member = members[0]

        for m in members:
            frp_val = float(m.get("frp") or 0.0)
            brightness_val = float(m.get("brightness") or 0.0)
            weight = max(frp_val, 1.0)
            weighted_lat += float(m["latitude"]) * weight
            weighted_lon += float(m["longitude"]) * weight
            total_weight += weight

            cur_score = max(frp_val, brightness_val / 10.0)
            best_score = max(float(peak_member.get("frp") or 0.0), float(peak_member.get("brightness") or 0.0) / 10.0)
            if cur_score > best_score:
                peak_member = m
            if frp_val > max_frp:
                max_frp = frp_val

        centroid_lat = weighted_lat / total_weight if total_weight > 0 else sum(m["latitude"] for m in members) / len(members)
        centroid_lon = weighted_lon / total_weight if total_weight > 0 else sum(m["longitude"] for m in members) / len(members)

        clusters.append(
            {
                "cluster_id": cluster_id,
                "hotspot_count": len(members),
                "centroid_lat": centroid_lat,
                "centroid_lon": centroid_lon,
                "epicenter_lat": float(peak_member["latitude"]),
                "epicenter_lon": float(peak_member["longitude"]),
                "max_frp": max_frp if max_frp > 0 else None,
                "first_detected_at": min(detected_ats),
                "last_detected_at": max(detected_ats),
                "dominant_agency": dominant_agency,
                "core_point_count": sum(1 for member in members if member["id"] in core_point_ids),
                "dominant_wilker": wilkers[0]["name"] if wilkers else None,
                "dominant_province": provinces[0]["name"] if provinces else None,
                "affected_wilkers": wilkers,
                "affected_provinces": provinces,
                "location_count": len(locations),
                "locations_in_polygon": sum(1 for location in locations if location["polygon_hotspot_count"] > 0),
                "polygon_hotspot_count": polygon_hotspot_count,
                "outside_polygon_hotspot_count": len(members) - polygon_hotspot_count,
                "dominant_polygon": dominant_polygon,
                "polygons": polygon_summaries,
                "locations": locations,
                "footprint": (
                    _cluster_footprint(members, core_point_ids, eps_km)
                    if eps_km is not None
                    else None
                ),
                "affected_agencies": [
                    {"name": name, "hotspot_count": count}
                    for name, count in agencies.most_common()
                ],
            }
        )

    clusters.sort(key=lambda c: c["hotspot_count"], reverse=True)

    clustered_hotspots = sum(c["hotspot_count"] for c in clusters)
    total_hotspots = len(points)
    clustered_points = [
        {
            "id": point["id"],
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "detected_at": point["detected_at"],
            "agency_name": point.get("agency_name"),
            "polygon_metadata_id": point.get("polygon_metadata_id"),
            "polygon_agency_name": point.get("polygon_agency_name"),
            "wilker_bps": point.get("wilker_bps"),
            "province_name": point.get("province_name"),
            "cluster_id": labels[point["id"]],
            "is_core": point["id"] in core_point_ids,
        }
        for point in points
        if labels[point["id"]] != NOISE
    ]

    return {
        "count": len(clusters),
        "clusters": clusters,
        # Titik anggota dikirim agar peta bisa memperlihatkan deteksi yang
        # membentuk kompleks, termasuk titik yang berada di luar polygon
        # lembaga dominan. Noise sengaja tidak dikirim karena bukan anggota
        # kompleks mana pun.
        "points": clustered_points,
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
        location_eps_km: float,
    ) -> dict[str, object]:
        points = self.postgres_store.get_hotspots_in_range(start_at, end_at)
        if not points:
            return {
                "count": 0,
                "clusters": [],
                "points": [],
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
        core_point_ids = _core_point_ids(point_ids, edges, min_samples)
        return _summarize(points, labels, core_point_ids, eps_km, location_eps_km)
