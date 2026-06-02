from pathlib import Path

def test_settings_use_local_defaults() -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        nasa_firms_api_key="demo-key",
        database_url="postgresql://demo:demo@localhost:5432/etaseneu",
        shp_dir="../shp",
        cache_dir=".cache",
    )

    assert settings.api_prefix == "/api"
    assert settings.frontend_origin == "http://localhost:5173"
    assert settings.nasa_firms_api_key == "demo-key"
    assert settings.database_url == "postgresql://demo:demo@localhost:5432/etaseneu"
    assert settings.shp_dir == "../shp"
    assert settings.cache_dir == ".cache"
    assert settings.cache_ttl_hours == 24
    assert settings.request_timeout_seconds == 30.0
    assert settings.scheduler_new_hotspot_alert_threshold == 1


def test_settings_load_env_values_and_resolve_paths(tmp_path: Path, monkeypatch) -> None:
    from app.core.config import BACKEND_DIR, Settings

    monkeypatch.delenv("DATABASE_URL", raising=False)

    env_file = tmp_path / "test.env"
    env_file.write_text(
        "\n".join(
            [
                "NASA_FIRMS_API_KEY=demo-key",
                "DATABASE_URL=postgresql://demo:demo@localhost:5432/etaseneu",
                "FRONTEND_ORIGIN=http://localhost:5173",
                "SHP_DIR=../shp",
                "CACHE_DIR=.cache",
                "CACHE_TTL_HOURS=24",
                "REQUEST_TIMEOUT_SECONDS=30",
                "SCHEDULER_NEW_HOTSPOT_ALERT_THRESHOLD=5",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.api_prefix == "/api"
    assert settings.frontend_origin == "http://localhost:5173"
    assert settings.nasa_firms_api_key == "demo-key"
    assert settings.database_url == "postgresql://demo:demo@localhost:5432/etaseneu"
    assert settings.shp_dir == "../shp"
    assert settings.cache_dir == ".cache"
    assert settings.cache_ttl_hours == 24
    assert settings.request_timeout_seconds == 30.0
    assert settings.scheduler_new_hotspot_alert_threshold == 5
    assert settings.resolved_shp_dir == (BACKEND_DIR / "../shp").resolve()
    assert settings.resolved_cache_dir == (BACKEND_DIR / ".cache").resolve()


def test_settings_preserve_absolute_shp_path() -> None:
    from app.core.config import Settings

    settings = Settings(
        _env_file=None,
        nasa_firms_api_key="demo-key",
        database_url="postgresql://demo:demo@localhost:5432/etaseneu",
        shp_dir="/app/shp",
        cache_dir=".cache",
    )

    assert settings.shp_dir == "/app/shp"
    assert settings.resolved_shp_dir == Path("/app/shp")
