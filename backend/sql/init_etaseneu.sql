CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS layers (
    id BIGSERIAL PRIMARY KEY,
    layer_key TEXT NOT NULL UNIQUE,
    layer_name TEXT NOT NULL,
    layer_label TEXT NOT NULL,
    feature_count INTEGER NOT NULL DEFAULT 0,
    bounds JSONB NOT NULL DEFAULT '{}'::jsonb,
    agencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    display_geojson JSONB NOT NULL DEFAULT '{"type":"FeatureCollection","features":[]}'::jsonb,
    spatial_geojson JSONB NOT NULL DEFAULT '{"type":"FeatureCollection","features":[]}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hotspot_observations (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    satellite TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    brightness DOUBLE PRECISION,
    confidence TEXT,
    detected_at TIMESTAMPTZ NOT NULL,
    layer_key TEXT,
    layer_name TEXT,
    agency_name TEXT,
    geom geometry(Point, 4326),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS hotspot_observations_unique_idx
    ON hotspot_observations (
        source,
        satellite,
        latitude,
        longitude,
        detected_at,
        COALESCE(layer_key, '')
    );

CREATE INDEX IF NOT EXISTS hotspot_observations_detected_at_idx
    ON hotspot_observations (detected_at DESC);

CREATE INDEX IF NOT EXISTS hotspot_observations_layer_key_idx
    ON hotspot_observations (layer_key);

CREATE INDEX IF NOT EXISTS hotspot_observations_geom_idx
    ON hotspot_observations
    USING GIST (geom);

CREATE TABLE IF NOT EXISTS hotspot_history_archives (
    id BIGSERIAL PRIMARY KEY,
    archive_year INTEGER NOT NULL,
    layer_key TEXT NOT NULL,
    satellites JSONB NOT NULL DEFAULT '[]'::jsonb,
    coverage_start DATE NOT NULL,
    coverage_end DATE NOT NULL,
    hotspot_count INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{"hotspots":[]}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (archive_year, layer_key)
);

CREATE TABLE IF NOT EXISTS api_cache_entries (
    id BIGSERIAL PRIMARY KEY,
    cache_key TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL DEFAULT '[]'::jsonb,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS api_cache_entries_expires_at_idx
    ON api_cache_entries (expires_at);

CREATE TABLE IF NOT EXISTS hotspot_sync_state (
    sync_key TEXT PRIMARY KEY,
    last_hotspot_sync_at TIMESTAMPTZ,
    last_hotspot_sync_count INTEGER NOT NULL DEFAULT 0,
    last_sync_at TIMESTAMPTZ,
    last_sync_result JSONB,
    consecutive_failures INTEGER DEFAULT 0,
    last_hotspot_fingerprints JSONB,
    last_new_hotspot_count INTEGER DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS polygon_metadata (
    id BIGSERIAL PRIMARY KEY,
    layer_key TEXT NOT NULL,
    feature_key TEXT NOT NULL,
    feature_index INTEGER NOT NULL,
    lembaga TEXT,
    nama_prov TEXT,
    nama_kab TEXT,
    nama_kec TEXT,
    nama_desa TEXT,
    skema TEXT,
    no_sk TEXT,
    tgl_sk TEXT,
    status TEXT,
    wilker_bps TEXT,
    ps_id TEXT,
    kode_prov TEXT,
    kode_kab TEXT,
    luas_hk TEXT,
    luas_hl TEXT,
    luas_hpt TEXT,
    luas_hp TEXT,
    luas_hpk TEXT,
    luas_sk TEXT,
    luas_poli TEXT,
    luas_final TEXT,
    jml_kk TEXT,
    shape_leng TEXT,
    shape_area TEXT,
    geometry geometry(MultiPolygon, 4326) NOT NULL,
    properties_raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_file TEXT NOT NULL,
    file_checksum TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (layer_key, feature_key)
);

CREATE TABLE IF NOT EXISTS hotspot_polygon_relation (
    id BIGSERIAL PRIMARY KEY,
    hotspot_observation_id BIGINT NOT NULL,
    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
    layer_key TEXT NOT NULL,
    match_method TEXT NOT NULL,
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (hotspot_observation_id, polygon_metadata_id)
);

CREATE TABLE IF NOT EXISTS polygon_hotspot_summary (
    id BIGSERIAL PRIMARY KEY,
    polygon_metadata_id BIGINT NOT NULL REFERENCES polygon_metadata(id),
    layer_key TEXT NOT NULL,
    year INTEGER NOT NULL,
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    hotspot_count INTEGER NOT NULL DEFAULT 0,
    last_hotspot_at TIMESTAMPTZ,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    satellites JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (polygon_metadata_id, year)
);

CREATE TABLE IF NOT EXISTS geojson_file_registry (
    id BIGSERIAL PRIMARY KEY,
    file_name TEXT NOT NULL UNIQUE,
    file_path TEXT NOT NULL,
    layer_key TEXT NOT NULL,
    checksum TEXT NOT NULL,
    mtime TIMESTAMPTZ NOT NULL,
    last_synced_at TIMESTAMPTZ,
    last_sync_status TEXT NOT NULL DEFAULT 'pending',
    last_sync_message TEXT NOT NULL DEFAULT '',
    feature_count INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
