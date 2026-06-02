from pathlib import Path


def _read_schema() -> str:
    schema_path = Path(__file__).resolve().parents[3] / "backend/sql/init_etaseneu.sql"
    return schema_path.read_text(encoding="utf-8")


def test_polygon_metadata_schema_tables_exist() -> None:
    schema = _read_schema()

    assert "CREATE TABLE IF NOT EXISTS polygon_metadata" in schema
    assert "CREATE TABLE IF NOT EXISTS hotspot_polygon_relation" in schema
    assert "CREATE TABLE IF NOT EXISTS polygon_hotspot_summary" in schema
    assert "CREATE TABLE IF NOT EXISTS geojson_file_registry" in schema


def test_polygon_metadata_schema_contains_key_columns() -> None:
    schema = _read_schema()

    for needle in [
        "layer_key",
        "feature_key",
        "lembaga",
        "nama_prov",
        "nama_kab",
        "nama_kec",
        "nama_desa",
        "ps_id",
        "luas_final",
        "properties_raw",
        "is_active",
    ]:
        assert needle in schema
