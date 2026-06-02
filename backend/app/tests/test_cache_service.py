import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def test_cache_service_stores_and_reads_payload(tmp_path: Path) -> None:
    from app.services.cache_service import CacheService

    service = CacheService(tmp_path, ttl_hours=24)
    payload = [{"source": "MODIS", "latitude": 4.1, "longitude": 95.1}]

    service.write("modis-2026-01-01-2026-05-26", payload)
    cached = service.read("modis-2026-01-01-2026-05-26")

    assert cached == payload


def test_cache_service_returns_none_for_expired_payload(tmp_path: Path) -> None:
    from app.services.cache_service import CacheService

    service = CacheService(tmp_path, ttl_hours=1)
    payload = [{"source": "VIIRS", "latitude": 4.2, "longitude": 95.2}]
    key = "viirs-2026-01-01-2026-05-26"

    service.write(key, payload)

    expired_at = datetime.now(timezone.utc) - timedelta(hours=2)
    cache_file = tmp_path / f"{key}.json"
    timestamp = expired_at.timestamp()
    os.utime(cache_file, (timestamp, timestamp))

    assert service.read(key) is None


def test_cache_service_returns_none_for_corrupt_payload(tmp_path: Path) -> None:
    from app.services.cache_service import CacheService

    service = CacheService(tmp_path, ttl_hours=24)
    cache_file = tmp_path / "broken.json"
    cache_file.write_text("{not-valid-json", encoding="utf-8")

    assert service.read("broken") is None


def test_cache_service_rejects_path_traversal_keys(tmp_path: Path) -> None:
    import pytest

    from app.services.cache_service import CacheService

    service = CacheService(tmp_path, ttl_hours=24)

    with pytest.raises(ValueError):
        service.write("../escape", [{"source": "MODIS"}])


def test_cache_service_clear_query_cache_removes_only_root_cache_files(tmp_path: Path) -> None:
    from app.services.cache_service import CacheService

    service = CacheService(tmp_path, ttl_hours=24)
    service.write("modis-2026-05", [{"source": "MODIS"}])
    history_dir = tmp_path / "hotspot_history"
    history_dir.mkdir()
    history_file = history_dir / "archive.json"
    history_file.write_text("{}", encoding="utf-8")

    removed = service.clear_query_cache()

    assert removed == 1
    assert not (tmp_path / "modis-2026-05.json").exists()
    assert history_file.exists()
