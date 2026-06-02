from datetime import datetime, timezone

from app.models.hotspots import HotspotRecord


def normalize_hotspots(rows: list[dict[str, str]], source: str) -> list[dict]:
    normalized: list[dict] = []
    for row in rows:
        record = HotspotRecord(
            source=source,
            satellite=row.get("satellite", source),
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            brightness=_read_brightness(row, source),
            frp=_read_float(row.get("frp")),
            confidence=row.get("confidence"),
            daynight=row.get("daynight"),
            detected_at=_parse_detected_at(row["acq_date"], row["acq_time"]),
        )
        normalized.append(record.model_dump())
    return normalized


def _read_brightness(row: dict[str, str], source: str) -> float | None:
    field_name = "bright_ti4" if source.upper().startswith("VIIRS") else "brightness"
    value = row.get(field_name, "").strip()
    if not value:
        return None
    return float(value)


def _read_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return float(value)


def _parse_detected_at(acq_date: str, acq_time: str) -> str:
    normalized_time = acq_time.strip().zfill(4)
    return datetime.strptime(
        f"{acq_date.strip()} {normalized_time}",
        "%Y-%m-%d %H%M",
    ).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
