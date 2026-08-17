from __future__ import annotations


class FakeCursor:
    def __init__(self, fetchone_results: list[dict[str, object] | None]) -> None:
        self._fetchone_results = list(fetchone_results)
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.executed.append((query, params))

    def fetchone(self) -> dict[str, object] | None:
        return self._fetchone_results.pop(0)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_obj = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


def _store_with_fake_cursor(monkeypatch, fetchone_results: list[dict[str, object] | None]):
    from app.services.postgres_store import PostgresStore

    store = PostgresStore("postgresql://unused/db")
    cursor = FakeCursor(fetchone_results)

    import contextlib

    @contextlib.contextmanager
    def fake_connection():
        yield FakeConnection(cursor)

    monkeypatch.setattr(store, "connection", fake_connection)
    return store, cursor


def test_remove_geojson_file_registry_deletes_row_and_returns_layer_key(monkeypatch) -> None:
    store, cursor = _store_with_fake_cursor(
        monkeypatch,
        fetchone_results=[{"layer_key": "PS_FEB_26"}],
    )

    layer_key = store.remove_geojson_file_registry("PS_FEB_26.geojson")

    assert layer_key == "PS_FEB_26"
    # Dua statement: deactivate polygon_metadata, lalu DELETE registry.
    assert len(cursor.executed) == 2
    update_query, update_params = cursor.executed[0]
    assert "UPDATE polygon_metadata" in update_query
    assert update_params == ("PS_FEB_26.geojson",)

    delete_query, delete_params = cursor.executed[1]
    assert "DELETE FROM geojson_file_registry" in delete_query
    assert delete_params == ("PS_FEB_26.geojson",)


def test_remove_geojson_file_registry_returns_none_when_not_found(monkeypatch) -> None:
    store, _cursor = _store_with_fake_cursor(monkeypatch, fetchone_results=[None])

    layer_key = store.remove_geojson_file_registry("tidak-ada.geojson")

    assert layer_key is None
