import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.postgres_store import PostgresStore


class CacheService:
    def __init__(self, cache_dir: Path, ttl_hours: int, database_url: str = "") -> None:
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        self.ttl_hours = ttl_hours
        self.postgres_store = PostgresStore(database_url)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = key.replace("\\", "/").strip("/")
        if not safe_key or ".." in safe_key.split("/"):
            raise ValueError("cache key must not contain path traversal segments")
        return self.cache_dir / f"{safe_key}.json"

    def read(self, key: str) -> list[dict] | None:
        if self.postgres_store.enabled:
            try:
                cached = self.postgres_store.read_cache_entry(key)
            except Exception:
                cached = None
            if cached is not None:
                return cached

        path = self._path(key)
        if not path.exists():
            return None

        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - modified > self.ttl:
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def write(self, key: str, payload: list[dict]) -> None:
        if self.postgres_store.enabled:
            try:
                self.postgres_store.write_cache_entry(key, payload, self.ttl_hours)
            except Exception:
                pass
        self._path(key).write_text(json.dumps(payload), encoding="utf-8")

    def clear_query_cache(self) -> int:
        removed = 0
        if self.postgres_store.enabled:
            try:
                removed += self.postgres_store.clear_cache_entries()
            except Exception:
                pass

        for path in self.cache_dir.glob("*.json"):
            if not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue

        return removed
