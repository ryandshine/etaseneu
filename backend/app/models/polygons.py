from typing import Any

from pydantic import BaseModel


class PolygonDetail(BaseModel):
    id: int
    layer_key: str
    feature_key: str
    lembaga: str | None = None
    nama_prov: str | None = None
    nama_kab: str | None = None
    nama_kec: str | None = None
    nama_desa: str | None = None
    skema: str | None = None
    no_sk: str | None = None
    tgl_sk: str | None = None
    status: str | None = None
    wilker_bps: str | None = None
    ps_id: str | None = None
    luas_final: str | None = None
    jml_kk: str | None = None
    geometry: dict[str, Any]
