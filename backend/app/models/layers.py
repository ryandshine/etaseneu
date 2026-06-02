from typing import Any

from pydantic import Field

from pydantic import BaseModel


class LayerBounds(BaseModel):
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float


class LayerFeature(BaseModel):
    id: str
    name: str
    label: str = ""
    color: str
    active: bool
    feature_count: int
    bounds: LayerBounds
    geojson: dict[str, Any]
    geojson_mode: str = "full"
    agencies: list[str] = Field(default_factory=list)
