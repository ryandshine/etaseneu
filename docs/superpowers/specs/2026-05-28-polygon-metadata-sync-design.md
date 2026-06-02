# PRD - Polygon Metadata Sync and Hotspot Mapping

## 1. Goal

Build a database-backed polygon metadata layer so the application can:

- store GeoJSON polygon metadata in normalized tables
- answer which lembaga/polygon contains hotspot records
- power the Data Matrix screen from database queries instead of raw GeoJSON scans
- detect GeoJSON file updates in `shp/` and refresh the database safely

The design must fit the current ETA SEUNEU stack and remain simple enough for local development and future deployment.

## 2. Why this is needed

Today the app reads polygon metadata from GeoJSON files in `shp/` and matches hotspots against them at runtime. That works, but it has three limits:

- metadata is hard to query directly in SQL
- UI matrix rendering depends on the in-memory GeoJSON shape
- changes to GeoJSON files are not yet managed as first-class database updates

This design makes polygon metadata a persistent dataset with a clear sync workflow.

## 3. Scope

### In scope

- import polygon features from GeoJSON into PostgreSQL
- store a normalized record for each polygon feature
- track file-level sync state for each GeoJSON file in `shp/`
- store hotspot-to-polygon matches
- store a precomputed summary for fast UI queries
- support safe re-import when a GeoJSON file changes
- support soft deactivation when a GeoJSON file is removed

### Out of scope

- changing the NASA hotspot acquisition source
- changing the existing hotspot observation schema beyond what is needed for polygon linking
- building a full GIS admin panel
- realtime filesystem watcher as the primary sync mechanism

## 4. Proposed Data Model

### 4.1 `polygon_metadata`

One row per polygon feature from GeoJSON.

Purpose:

- source of truth for polygon attributes
- queryable metadata for UI, filters, and reporting

Suggested fields:

- `id`
- `layer_key`
- `feature_key`
- `feature_index`
- `lembaga`
- `nama_prov`
- `nama_kab`
- `nama_kec`
- `nama_desa`
- `skema`
- `no_sk`
- `tgl_sk`
- `status`
- `wilker_bps`
- `ps_id`
- `kode_prov`
- `kode_kab`
- `luas_hk`
- `luas_hl`
- `luas_hpt`
- `luas_hp`
- `luas_hpk`
- `luas_sk`
- `luas_poli`
- `luas_final`
- `jml_kk`
- `shape_leng`
- `shape_area`
- `geometry`
- `properties_raw`
- `source_file`
- `file_checksum`
- `is_active`
- `created_at`
- `updated_at`

Notes:

- `feature_key` should be stable for a feature within a file.
- `properties_raw` keeps the original feature properties for audit/debugging.
- `is_active` allows soft removal when a GeoJSON file is deleted or a feature disappears.

### 4.2 `hotspot_polygon_relation`

One row per hotspot-polygon match.

Purpose:

- answer which hotspot belongs to which polygon/lembaga
- support per-lembaga hotspot listing and export

Suggested fields:

- `id`
- `hotspot_observation_id`
- `polygon_metadata_id`
- `layer_key`
- `match_method`
- `matched_at`
- `created_at`

Notes:

- v1 can use a single primary match per hotspot.
- `match_method` can store values like `point_in_polygon`.

### 4.3 `polygon_hotspot_summary`

Aggregated view for fast UI rendering.

Purpose:

- power Data Matrix and summary cards without scanning all hotspot rows
- provide quick counts per polygon and time window

Suggested fields:

- `id`
- `polygon_metadata_id`
- `layer_key`
- `year`
- `start_at`
- `end_at`
- `hotspot_count`
- `last_hotspot_at`
- `sources`
- `satellites`
- `created_at`
- `updated_at`

Notes:

- this table can be rebuilt incrementally from relation rows
- it is allowed to contain denormalized data for performance

### 4.4 `geojson_file_registry`

Track sync state for each file in `shp/`.

Purpose:

- detect changed files
- make startup sync predictable
- support manual refresh

Suggested fields:

- `id`
- `file_name`
- `file_path`
- `layer_key`
- `checksum`
- `mtime`
- `last_synced_at`
- `last_sync_status`
- `last_sync_message`
- `feature_count`
- `is_active`
- `created_at`
- `updated_at`

Notes:

- this is the main guard against duplicate imports
- `checksum` is preferred over mtime for correctness, but both may be stored

## 5. Sync Behavior

### 5.1 Startup sync

On application startup:

1. scan `shp/` for GeoJSON files
2. calculate a file fingerprint
3. compare the fingerprint with `geojson_file_registry`
4. import only new or changed files
5. mark missing files and missing features as inactive
6. rebuild affected hotspot relations and summaries

### 5.2 Manual refresh

The app should expose a manual refresh action that:

- rescans `shp/`
- reimports changed files
- updates registry rows
- refreshes affected summaries

This is the primary operational control for dev and local staging.

### 5.3 Update strategy

When a GeoJSON file changes:

- polygon rows are upserted by `layer_key + feature_key`
- rows no longer present in the file are marked inactive
- new rows are inserted
- changed rows are updated in place

When a GeoJSON file is removed:

- registry row is marked inactive
- polygon rows from that file are marked inactive
- summaries for that file are invalidated or recomputed as needed

### 5.4 Hotspot relation refresh

When polygon metadata changes:

- hotspot relations for the impacted layer are recomputed
- summary rows are rebuilt for the impacted layer and time range

## 6. UI Impact

### 6.1 Data Matrix

The Data Matrix should read from the database rather than from raw GeoJSON.

It should be able to show:

- lembaga name
- province, district, subdistrict, and village
- hotspot count per polygon
- legal / registry fields
- area fields
- last hotspot timestamp

### 6.2 Filters

The UI should support filtering by:

- lembaga
- province
- layer
- source satellite
- date window

### 6.3 Sync status

The UI should show:

- last successful NASA hotspot sync time
- last polygon sync status
- whether polygon metadata is current

## 7. Backend Behavior

Backend services should:

- import GeoJSON polygons into PostgreSQL
- store file fingerprints in `geojson_file_registry`
- store point-in-polygon matches in `hotspot_polygon_relation`
- maintain `polygon_hotspot_summary`
- keep current hotspot observation storage behavior

The sync workflow should remain safe if a file import fails midway:

- existing rows should not be corrupted
- the registry should record the failure
- the previous good state should remain queryable

## 8. Error Handling

If a GeoJSON file cannot be parsed:

- record the failure in `geojson_file_registry`
- skip the file for the current sync cycle
- keep the previous active data intact if present

If a polygon import partially succeeds:

- the transaction should be rolled back for that file
- no partial polygon rows should remain visible

If the summary rebuild fails:

- the detailed polygon metadata should still be available
- the UI can fall back to direct polygon queries

## 9. Performance Notes

The design assumes:

- GeoJSON files may be large
- sync should be incremental when possible
- matrix queries should hit summary tables first

Preferred behavior:

- read from `polygon_hotspot_summary` for matrix views
- read from `polygon_metadata` for metadata detail
- read from `hotspot_polygon_relation` for mapping and exports

## 10. Acceptance Criteria

The feature is done when:

- GeoJSON polygon metadata is stored in PostgreSQL
- the app can show which polygon/lembaga has hotspots
- the Data Matrix reads from database-backed polygon metadata
- changing a GeoJSON file in `shp/` can be detected and synced
- deleted or missing GeoJSON files are marked inactive instead of causing data corruption
- startup sync and manual refresh both work
- the current hotspot flow continues to work

