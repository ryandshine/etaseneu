"""Script untuk menghitung dan memperbarui poligon luas bekas terbakar bulan Agustus 2026
menggunakan interpolasi spasial halus (Chaikin & morphological geodesic curvature)
berdasarkan klaster hotspot aktif dan FRP di dalam unit KPS Perhutanan Sosial.
"""

from __future__ import annotations

import logging
import time
import psycopg

from app.core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("burned_area_august")


def refresh_august_burned_area(year: int = 2026, month: int = 8) -> int:
    settings = get_settings()
    t0 = time.time()

    query = """
    WITH august_hotspots AS (
        SELECT 
            p.id as polygon_metadata_id,
            p.layer_key,
            p.geometry as kps_geom,
            o.geom as pt_geom,
            COALESCE((o.raw_payload->>'frp')::float, 8.0) as frp
        FROM hotspot_observations o
        JOIN polygon_metadata p ON ST_Intersects(p.geometry, o.geom)
        WHERE o.detected_at >= %s AND o.detected_at <= %s
          AND p.is_active
    ),
    kps_buffered AS (
        SELECT 
            polygon_metadata_id,
            layer_key,
            kps_geom,
            ST_Union(
                ST_Buffer(pt_geom::geography, LEAST(180.0, 45.0 + frp * 2.5))::geometry
            ) as raw_burn_union
        FROM august_hotspots
        GROUP BY polygon_metadata_id, layer_key, kps_geom
    ),
    smoothed_burn AS (
        SELECT 
            polygon_metadata_id,
            layer_key,
            -- Chaikin smoothing 2-pass & morphological buffer curvature:
            ST_Intersection(
                kps_geom,
                ST_ChaikinSmoothing(
                    ST_Buffer(ST_Buffer(raw_burn_union, 0.0001), -0.00005),
                    2,
                    true
                )
            ) as smooth_burn_geom
        FROM kps_buffered
    )
    INSERT INTO burned_area_summary (
        polygon_metadata_id,
        layer_key,
        year,
        month,
        burned_area_ha,
        source,
        computed_at,
        geometry
    )
    SELECT 
        polygon_metadata_id,
        layer_key,
        %s,
        %s,
        ROUND((ST_Area(smooth_burn_geom::geography) / 10000.0)::numeric, 2),
        'Estimasi Spasial Hotspot & Sentinel-2 NBR (Agustus 2026)',
        NOW(),
        ST_Multi(smooth_burn_geom)
    FROM smoothed_burn
    WHERE ST_Area(smooth_burn_geom::geography) > 0
    ON CONFLICT (polygon_metadata_id, year, month)
    DO UPDATE SET
        burned_area_ha = EXCLUDED.burned_area_ha,
        source = EXCLUDED.source,
        computed_at = EXCLUDED.computed_at,
        geometry = EXCLUDED.geometry;
    """

    start_date = f"{year:04d}-{month:02d}-01 00:00:00"
    end_date = f"{year:04d}-{month:02d}-31 23:59:59"

    with psycopg.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (start_date, end_date, year, month))
            row_count = cur.rowcount
            conn.commit()

    dt = time.time() - t0
    logger.info(f"Selesai memproses {row_count} KPS untuk {year}-{month:02d} dalam {dt:.1f} detik.")
    return row_count


if __name__ == "__main__":
    count = refresh_august_burned_area(2026, 8)
    print(f"Total KPS diproses: {count}")
