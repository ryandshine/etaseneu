import csv
from collections.abc import Iterable

import httpx
from fastapi import HTTPException

from app.core.config import get_settings


class NasaFirmsClient:
    def __init__(self) -> None:
        self.base_url = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    async def fetch_rows(self, path: str) -> Iterable[dict[str, str]]:
        settings = get_settings()
        url = path if path.startswith("http") else f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(url)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text.strip() or "NASA FIRMS request failed."
                raise HTTPException(status_code=502, detail=detail) from exc
            return list(csv.DictReader(response.text.splitlines()))
