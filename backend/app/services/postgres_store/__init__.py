"""Akses PostgreSQL/PostGIS untuk seluruh domain aplikasi.

`PostgresStore` sebelumnya satu file 1500+ baris yang mencampur 8 tanggung
jawab berbeda (layer registry, metadata polygon, cache, metrik scheduler,
observasi hotspot, relasi spasial, dan pencocokan titik) dalam satu class.
Sekarang tiap domain jadi mixin di modulnya sendiri (lihat file `_*.py` di
paket ini); `PostgresStore` di sini hanya menyusunnya jadi satu class lewat
multiple inheritance.

API publik tidak berubah sama sekali -- semua pemanggil tetap melakukan
`from app.services.postgres_store import PostgresStore` dan memanggil metode
yang sama seperti sebelumnya, karena `postgres_store` sekarang adalah paket
(bukan modul tunggal) yang mengekspor nama yang sama lewat `__init__.py` ini.
"""

from ._base import _ConnectionMixin
from ._burned_area import _BurnedAreaMixin
from ._cache import _CacheMixin
from ._history import _HistoryArchiveMixin
from ._hotspots import _HotspotObservationMixin
from ._layers import _LayerRegistryMixin
from ._polygons import _PolygonMetadataMixin
from ._relations import _PolygonRelationMixin
from ._scheduler import _SchedulerMetricsMixin
from ._spatial import _SpatialMatchMixin

__all__ = ["PostgresStore"]


class PostgresStore(
    _ConnectionMixin,
    _LayerRegistryMixin,
    _PolygonMetadataMixin,
    _HistoryArchiveMixin,
    _CacheMixin,
    _SchedulerMetricsMixin,
    _HotspotObservationMixin,
    _PolygonRelationMixin,
    _SpatialMatchMixin,
    _BurnedAreaMixin,
):
    """Fasad tunggal ke semua tabel aplikasi -- lihat docstring modul ini."""
