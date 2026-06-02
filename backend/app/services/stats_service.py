from collections import Counter


def build_stats(hotspots: list[dict]) -> dict:
    return {
        "total": len(hotspots),
        "by_source": dict(Counter(hotspot["source"] for hotspot in hotspots)),
        "by_layer": dict(
            Counter(hotspot.get("layer_name", "unknown") for hotspot in hotspots)
        ),
    }
