import csv
import logging
from collections.abc import Iterable

import httpx
from fastapi import HTTPException

from app.core.config import get_settings

logger = logging.getLogger("hotspot.nasa_client")


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
                # Body error NASA (dan pesan exception httpx) bisa meng-echo
                # URL yang diminta -- URL itu berisi MAP_KEY NASA FIRMS di
                # path-nya (begitu desain API mereka). Jangan pernah teruskan
                # mentah ke response publik; log detailnya di server saja.
                logger.error("NASA FIRMS request failed (%s): %s", response.status_code, response.text.strip())
                raise HTTPException(
                    status_code=502,
                    detail="Gagal mengambil data dari NASA FIRMS. Coba lagi beberapa saat lagi.",
                ) from exc
            return list(csv.DictReader(response.text.splitlines()))
