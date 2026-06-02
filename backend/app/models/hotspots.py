from pydantic import BaseModel


class HotspotRecord(BaseModel):
    source: str
    satellite: str
    latitude: float
    longitude: float
    brightness: float | None = None
    frp: float | None = None
    confidence: str | None = None
    daynight: str | None = None
    detected_at: str
