import json
from pathlib import Path

from app.services.postgres_store import PostgresStore


class HotspotHistoryStore:
    def __init__(self, history_dir: Path, database_url: str = "") -> None:
        self.history_dir = history_dir
        self.postgres_store = PostgresStore(database_url)
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe_key = key.replace("\\", "/").strip("/")
        if not safe_key or ".." in safe_key.split("/"):
            raise ValueError("history key must not contain path traversal segments")
        return self.history_dir / f"{safe_key}.json"

    def read(self, key: str) -> dict[str, object] | None:
        archive_meta = _parse_history_key(key)
        if self.postgres_store.enabled and archive_meta is not None:
            try:
                cached = self.postgres_store.read_history_archive(
                    archive_meta["year"],
                    archive_meta["layer_key"],
                )
            except Exception:
                cached = None
            if cached is not None:
                return cached

        path = self._path(key)
        if not path.exists():
            return None

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def write(self, key: str, payload: dict[str, object]) -> None:
        archive_meta = _parse_history_key(key)
        if self.postgres_store.enabled and archive_meta is not None:
            try:
                self.postgres_store.write_history_archive(
                    year=archive_meta["year"],
                    layer_key=archive_meta["layer_key"],
                    coverage_start=str(payload.get("coverage_start", "")),
                    coverage_end=str(payload.get("coverage_end", "")),
                    satellites=_normalize_satellites(payload.get("satellites")),
                    hotspots=_ensure_hotspots(payload.get("hotspots")),
                )
            except Exception:
                pass
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


def _parse_history_key(key: str) -> dict[str, object] | None:
    parts = key.replace("\\", "/").strip("/").split("/")
    if len(parts) != 3 or parts[0] != "history":
        return None

    try:
        year = int(parts[1])
    except ValueError:
        return None

    return {"year": year, "layer_key": parts[2]}


def _normalize_satellites(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(entry) for entry in value]


def _ensure_hotspots(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]
