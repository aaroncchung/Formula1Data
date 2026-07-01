import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from app.services.storage_service import StorageService

T = TypeVar("T")


class CacheService:
    def __init__(self, storage: StorageService | None = None) -> None:
        self.storage = storage or StorageService()
        self._memory: dict[str, tuple[float, Any]] = {}

    def get_memory(self, key: str, ttl_seconds: int) -> Any | None:
        item = self._memory.get(key)
        if item is None:
            return None
        timestamp, value = item
        if time.time() - timestamp > ttl_seconds:
            self._memory.pop(key, None)
            return None
        return value

    def set_memory(self, key: str, value: Any) -> None:
        self._memory[key] = (time.time(), value)

    async def remember_json(
        self,
        path: str | Path,
        ttl_seconds: int,
        loader: Callable[[], T],
    ) -> T:
        metadata_path = f"{path}.metadata.json"
        if self.storage.exists(path) and self.storage.exists(metadata_path):
            metadata = self.storage.read_json(metadata_path)
            if time.time() - metadata.get("created_at", 0) <= ttl_seconds:
                return self.storage.read_json(path)
        value = loader()
        self.storage.write_json(path, value)
        self.storage.write_json(metadata_path, {"created_at": time.time()})
        return value

