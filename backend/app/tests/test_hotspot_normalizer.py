def test_normalize_modis_rows() -> None:
    from app.services.hotspot_normalizer import normalize_hotspots

    rows = [
        {
            "latitude": "4.10",
            "longitude": "95.10",
            "brightness": "330.4",
            "frp": "12.5",
            "acq_date": "2026-05-24",
            "acq_time": "0612",
            "confidence": "78",
            "daynight": "D",
            "satellite": "Terra",
        }
    ]

    normalized = normalize_hotspots(rows, source="MODIS")

    assert normalized[0]["source"] == "MODIS"
    assert normalized[0]["latitude"] == 4.10
    assert normalized[0]["longitude"] == 95.10
    assert normalized[0]["brightness"] == 330.4
    assert normalized[0]["frp"] == 12.5
    assert normalized[0]["confidence"] == "78"
    assert normalized[0]["daynight"] == "D"
    assert normalized[0]["detected_at"] == "2026-05-24T06:12:00Z"


def test_normalize_viirs_rows_uses_viirs_brightness_field() -> None:
    from app.services.hotspot_normalizer import normalize_hotspots

    rows = [
        {
            "latitude": "4.20",
            "longitude": "95.20",
            "bright_ti4": "345.6",
            "frp": "6.4",
            "acq_date": "2026-05-25",
            "acq_time": "0412",
            "confidence": "high",
            "daynight": "N",
            "satellite": "NOAA-20",
        }
    ]

    normalized = normalize_hotspots(rows, source="VIIRS")

    assert normalized[0]["source"] == "VIIRS"
    assert normalized[0]["brightness"] == 345.6
    assert normalized[0]["frp"] == 6.4
    assert normalized[0]["confidence"] == "high"
    assert normalized[0]["daynight"] == "N"
    assert normalized[0]["detected_at"] == "2026-05-25T04:12:00Z"
