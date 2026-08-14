"""Pencocokan titik-ke-polygon massal, dipakai fitur unggah "Cek Titik ke KPS"."""

from collections.abc import Sequence


class _SpatialMatchMixin:
    def match_points_to_polygons(
        self, points: Sequence[tuple[float, float]]
    ) -> list[dict[str, object] | None]:
        """Cocokkan banyak titik ke polygon KPS sekaligus.

        Dikerjakan satu query untuk SELURUH titik, bukan satu query per titik:
        untuk unggahan puluhan ribu titik, per-titik berarti puluhan ribu
        round-trip ke database. Dengan indeks GIST di polygon_metadata.geometry,
        50.000 titik selesai di kisaran satu detik.

        Hasilnya sejajar dengan urutan `points` -- indeks ke-i adalah hasil untuk
        titik ke-i, dan None berarti titik itu tidak masuk polygon KPS manapun.
        Titik tak-cocok sengaja tidak dibuang: pengguna perlu tahu mana yang di
        luar kawasan, bukan cuma yang di dalam.
        """
        if not points:
            return []

        # ST_Contains mengecualikan titik yang persis di garis batas; pakai
        # ST_Intersects supaya titik di tepi kawasan tetap terhitung masuk.
        sql = """
            WITH pts AS (
                SELECT
                    ordinality - 1 AS idx,
                    ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom
                FROM unnest(%s::float8[], %s::float8[])
                     WITH ORDINALITY AS t(lon, lat, ordinality)
            )
            SELECT
                pts.idx,
                poly.id,
                poly.lembaga,
                poly.nama_prov,
                poly.nama_kab,
                poly.nama_kec,
                poly.nama_desa,
                poly.skema,
                poly.no_sk,
                poly.tgl_sk,
                poly.status,
                poly.wilker_bps,
                poly.ps_id,
                poly.luas_final,
                poly.jml_kk,
                poly.layer_key
            FROM pts
            JOIN polygon_metadata poly
              ON poly.is_active AND ST_Intersects(poly.geometry, pts.geom)
            ORDER BY pts.idx, poly.id
        """

        results: list[dict[str, object] | None] = [None] * len(points)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    ([lon for _, lon in points], [lat for lat, _ in points]),
                )
                for row in cur.fetchall():
                    index = int(row["idx"])
                    if index < 0 or index >= len(results):
                        continue
                    if results[index] is not None:
                        # Satu titik bisa masuk lebih dari satu polygon kalau
                        # kawasan tumpang tindih. Satu titik tetap satu baris di
                        # laporan, tapi jumlah kecocokan dicatat supaya kasus ini
                        # tidak hilang diam-diam. Query di-ORDER BY poly.id, jadi
                        # yang terpilih selalu sama untuk masukan yang sama --
                        # laporan harus bisa direproduksi.
                        matched = results[index]
                        assert matched is not None
                        matched["match_count"] = int(matched.get("match_count", 1)) + 1
                        continue
                    results[index] = {
                        "polygon_metadata_id": int(row["id"]),
                        "lembaga": row.get("lembaga"),
                        "nama_prov": row.get("nama_prov"),
                        "nama_kab": row.get("nama_kab"),
                        "nama_kec": row.get("nama_kec"),
                        "nama_desa": row.get("nama_desa"),
                        "skema": row.get("skema"),
                        "no_sk": row.get("no_sk"),
                        "tgl_sk": row.get("tgl_sk"),
                        "status": row.get("status"),
                        "wilker_bps": row.get("wilker_bps"),
                        "ps_id": row.get("ps_id"),
                        "luas_final": row.get("luas_final"),
                        "jml_kk": row.get("jml_kk"),
                        "layer_key": row.get("layer_key"),
                        "match_count": 1,
                    }

        return results
