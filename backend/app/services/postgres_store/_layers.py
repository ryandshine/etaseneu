"""Registrasi layer (dataset polygon) dan berkas GeoJSON sumbernya."""

from datetime import datetime, timezone

from ._base import Json


class _LayerRegistryMixin:
    def upsert_layer(
        self,
        *,
        layer_key: str,
        layer_name: str,
        layer_label: str,
        feature_count: int,
        bounds: dict,
        agencies: list[str],
        display_geojson: dict,
        spatial_geojson: dict,
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO layers (
                        layer_key,
                        layer_name,
                        layer_label,
                        feature_count,
                        bounds,
                        agencies,
                        display_geojson,
                        spatial_geojson
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (layer_key)
                    DO UPDATE SET
                        layer_name = EXCLUDED.layer_name,
                        layer_label = EXCLUDED.layer_label,
                        feature_count = EXCLUDED.feature_count,
                        bounds = EXCLUDED.bounds,
                        agencies = EXCLUDED.agencies,
                        display_geojson = EXCLUDED.display_geojson,
                        spatial_geojson = EXCLUDED.spatial_geojson,
                        updated_at = NOW()
                    """,
                    (
                        layer_key,
                        layer_name,
                        layer_label,
                        feature_count,
                        Json(bounds),
                        Json(agencies),
                        Json(display_geojson),
                        Json(spatial_geojson),
                    ),
                )

    def layer_sync_state(self, layer_key: str) -> dict[str, object] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT feature_count, layer_label
                    FROM layers
                    WHERE layer_key = %s
                    """,
                    (layer_key,),
                )
                return cur.fetchone()

    def read_geojson_file_registry(self, file_name: str) -> dict[str, object] | None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM geojson_file_registry
                    WHERE file_name = %s
                    """,
                    (file_name,),
                )
                return cur.fetchone()

    def read_geojson_file_registry_all(self) -> list[dict[str, object]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM geojson_file_registry
                    ORDER BY file_name ASC
                    """
                )
                rows = cur.fetchall()
        return list(rows)

    def geojson_registry_status(self) -> dict[str, object]:
        rows = self.read_geojson_file_registry_all()
        active_files = sum(1 for row in rows if row.get("is_active", True))
        return {
            "count": len(rows),
            "active_count": active_files,
            "inactive_count": len(rows) - active_files,
            "files": rows,
        }

    def upsert_geojson_file_registry(
        self,
        *,
        file_name: str,
        file_path: str,
        layer_key: str,
        checksum: str,
        mtime: datetime,
        feature_count: int,
        last_sync_status: str,
        last_sync_message: str = "",
        is_active: bool = True,
        last_synced_at: datetime | None = None,
    ) -> None:
        if last_synced_at is None:
            last_synced_at = datetime.now(timezone.utc)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO geojson_file_registry (
                        file_name,
                        file_path,
                        layer_key,
                        checksum,
                        mtime,
                        last_synced_at,
                        last_sync_status,
                        last_sync_message,
                        feature_count,
                        is_active
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (file_name)
                    DO UPDATE SET
                        file_path = EXCLUDED.file_path,
                        layer_key = EXCLUDED.layer_key,
                        checksum = EXCLUDED.checksum,
                        mtime = EXCLUDED.mtime,
                        last_synced_at = EXCLUDED.last_synced_at,
                        last_sync_status = EXCLUDED.last_sync_status,
                        last_sync_message = EXCLUDED.last_sync_message,
                        feature_count = EXCLUDED.feature_count,
                        is_active = EXCLUDED.is_active,
                        updated_at = NOW()
                    """,
                    (
                        file_name,
                        file_path,
                        layer_key,
                        checksum,
                        mtime,
                        last_synced_at,
                        last_sync_status,
                        last_sync_message,
                        feature_count,
                        is_active,
                    ),
                )

    def deactivate_geojson_file_registry(
        self,
        file_name: str,
        *,
        message: str = "file missing from scan",
    ) -> bool:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE geojson_file_registry
                    SET
                        is_active = FALSE,
                        last_sync_status = %s,
                        last_sync_message = %s,
                        updated_at = NOW()
                    WHERE file_name = %s
                    RETURNING layer_key
                    """,
                    ("removed", message, file_name),
                )
                row = cur.fetchone()
                if row and row.get("layer_key"):
                    cur.execute(
                        """
                        UPDATE polygon_metadata
                        SET is_active = FALSE, updated_at = NOW()
                        WHERE layer_key = %s AND is_active = TRUE
                        """,
                        (row["layer_key"],),
                    )
                    return True
                return False

    def remove_geojson_file_registry(self, file_name: str) -> str | None:
        """Hapus berkas GeoJSON dari sistem secara permanen.

        Beda dari `deactivate_geojson_file_registry` (dipakai mode upload
        "replace" dan pembersihan otomatis saat sync): fungsi itu menyisakan
        baris registry sebagai riwayat NONAKTIF, yang lama-lama menumpuk jadi
        sampah di daftar layer. Ini dipanggil dari aksi "Hapus" yang eksplisit
        di menu Pengaturan, jadi baris registry-nya sekalian dibuang -- tidak
        ada FK lain yang menunjuk ke `geojson_file_registry` jadi aman untuk
        hard delete.

        `polygon_metadata` milik layer itu tetap hanya dinonaktifkan (bukan
        dihapus): baris itu masih dirujuk oleh `hotspot_polygon_relation`
        lewat FK, jadi menghapusnya akan merusak riwayat pencocokan hotspot
        yang sudah tercatat.

        Return `layer_key` kalau ada baris yang ditemukan & dihapus, `None`
        kalau berkasnya memang tidak terdaftar (pemanggil lalu tahu harus
        balas 404, bukan pura-pura sukses).
        """
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE polygon_metadata
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE layer_key = (
                        SELECT layer_key FROM geojson_file_registry WHERE file_name = %s
                    ) AND is_active = TRUE
                    """,
                    (file_name,),
                )
                cur.execute(
                    """
                    DELETE FROM geojson_file_registry
                    WHERE file_name = %s
                    RETURNING layer_key
                    """,
                    (file_name,),
                )
                row = cur.fetchone()
                return row["layer_key"] if row else None
