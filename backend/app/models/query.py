from datetime import datetime

from pydantic import BaseModel


class HotspotQuery(BaseModel):
    start_at: datetime
    end_at: datetime
    satellites: list[str]
    active_layers: list[str]

    def cache_key(self) -> str:
        satellite_segment = "-".join(self.satellites) if self.satellites else "all"
        layer_segment = "-".join(sorted(self.active_layers)) if self.active_layers else "no-layers"
        start_segment = self.start_at.isoformat()
        end_segment = self.end_at.isoformat()
        return (
            f"{satellite_segment}-{layer_segment}-"
            f"{start_segment}-{end_segment}"
        )

    def yearly_archive_key(self, year: int, layer_id: str) -> str:
        return f"history/{year}/{layer_id}"
