"""Fixture global test.

`disable_api_auth_gate` (autouse): mematikan `API_REQUIRE_AUTH` untuk SEMUA
test. Tanpa ini, belasan test yang hit endpoint baca tanpa token akan pecah
begitu gate dipasang. Test yang memang menguji gate menyala (mis.
`test_api_auth_gate.py`) memanggil `monkeypatch.setenv(...)` sendiri di dalam
body test -- itu jalan SETELAH fixture ini, jadi nilainya menang.
"""

import pytest

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def disable_api_auth_gate(monkeypatch):
    monkeypatch.setenv("API_REQUIRE_AUTH", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
