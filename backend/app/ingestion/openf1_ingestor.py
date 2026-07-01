from typing import Any

from app.services.openf1_service import OpenF1Service


class OpenF1Ingestor:
    def __init__(self) -> None:
        self.openf1 = OpenF1Service()

    async def fetch_endpoint(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self.openf1._get(endpoint, params)

