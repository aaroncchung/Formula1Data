from typing import Any

import httpx

from app.config import get_settings
from app.services.cache_service import CacheService


class OpenF1Service:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.cache = CacheService()

    async def current_session(self) -> dict[str, Any]:
        return await self._cached_get("sessions", {"session_key": "latest"})

    async def live_timing(self) -> dict[str, Any]:
        return {
            "drivers": await self._cached_get("drivers", {"session_key": "latest"}),
            "intervals": await self._cached_get("intervals", {"session_key": "latest"}),
            "laps": await self._cached_get("laps", {"session_key": "latest"}),
        }

    async def race_control(self) -> dict[str, Any]:
        return await self._cached_get("race_control", {"session_key": "latest"})

    async def positions(self) -> dict[str, Any]:
        return await self._cached_get("position", {"session_key": "latest"})

    async def weather(self) -> dict[str, Any]:
        return await self._cached_get("weather", {"session_key": "latest"})

    async def _cached_get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        key = f"openf1:{endpoint}:{params}"
        cached = self.cache.get_memory(key, ttl_seconds=15)
        if cached is not None:
            return cached
        value = await self._get(endpoint, params)
        self.cache.set_memory(key, value)
        return value

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = {}
        if self.settings.openf1_api_key:
            headers["x-api-key"] = self.settings.openf1_api_key
        url = f"{self.settings.openf1_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return {"endpoint": endpoint, "data": response.json(), "cached": False}

